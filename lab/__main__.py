"""Lab_CLI entry point.

    python -m lab evaluate    --prompt TEXT [--repeat N]
    python -m lab checkpoint  --module N
    python -m lab conformance [--repeat N] [--set NAME] [--out PATH] [--record [DIR]]
    python -m lab latency     --api-base URL [--warm N] [--wait-cold]
    python -m lab teardown

Every subcommand runs preflight first, so a missing prerequisite costs no AWS call
and reports the command that fixes it.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

from lab.cases import CaseSetError
from lab.checkpoints import CheckpointError
from lab.core import (
    MAX_PROMPT_CHARS,
    PreflightError,
    PromptError,
    aws_error_code,
    build_service,
    failed_operation,
    preflight,
    validate_prompt,
)
from lab.latency import LatencyError

# Where recorded fixtures live, so `--record` needs no argument in the common case.
_DEFAULT_FIXTURES = (
    pathlib.Path(__file__).resolve().parent.parent
    / "backend" / "app" / "fixtures" / "replay"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lab-cli",
        description="Kilimo Desk guardrail lab — ApplyGuardrail only, no model required.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ev = sub.add_parser("evaluate", help="screen one prompt against the guardrail")
    ev.add_argument("--prompt", required=True, help=f"1 to {MAX_PROMPT_CHARS} characters")
    ev.add_argument("--answer", help="candidate answer, to grounding-check instead of screen")
    ev.add_argument("--repeat", type=int, default=1, help="repetitions (default 1)")

    doc = sub.add_parser(
        "doctor",
        help="check AWS prerequisites before creating anything",
        description="Verifies credentials, account type, guardrail permissions, tag "
                    "permissions, SDK version and model access. Distinguishes an "
                    "organisation SCP deny from a missing IAM grant, and prints the "
                    "exact fix for each.",
    )
    doc.add_argument(
        "--check-deploy",
        action="store_true",
        help="also probe iam:CreateRole, needed only to deploy the stack",
    )
    doc.add_argument(
        "--probe-write", action="store_true",
        help="also create and delete a throwaway guardrail to prove write access",
    )

    cp = sub.add_parser("checkpoint", help="verify one Lab_Guide module's checkpoints")
    cp.add_argument("--module", type=int, required=True)

    cf = sub.add_parser("conformance", help="run the declared case set")
    cf.add_argument("--repeat", type=int, default=1, help="1 to 20 (default 1)")
    cf.add_argument("--set", dest="case_set", help="evaluate one named case set only")
    cf.add_argument("--out", type=pathlib.Path, help="write JSONL records here")
    cf.add_argument(
        "--record",
        nargs="?",
        type=pathlib.Path,
        const=_DEFAULT_FIXTURES,
        help=(
            "also write Replay_Mode fixtures from these live responses "
            f"(default {_DEFAULT_FIXTURES})"
        ),
    )

    lat = sub.add_parser("latency", help="measure a deployed endpoint, cold and warm")
    lat.add_argument("--api-base", required=True,
                     help="e.g. $(terraform -chdir=infrastructure output -raw api_base_url)")
    lat.add_argument("--warm", type=int, default=3, help="warm samples (default 3, minimum 3)")
    lat.add_argument("--gap", type=float, default=5.0,
                     help="seconds between warm samples (default 5, must stay under 60)")
    lat.add_argument("--wait-cold", action="store_true",
                     help="idle 15 minutes first so the first sample is genuinely cold")
    lat.add_argument("--out", help="write one JSONL record per sample")

    sub.add_parser("teardown", help="remove every resource the lab created")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "teardown":
            return _teardown(args)
        if args.command == "evaluate":
            return _evaluate(args)
        if args.command == "checkpoint":
            return _checkpoint(args)
        if args.command == "conformance":
            return _conformance(args)
        if args.command == "latency":
            return _latency(args)
    except PreflightError as exc:
        print(f"prerequisite missing:\n{exc}", file=sys.stderr)
        return 2
    except PromptError as exc:
        print(f"invalid prompt: {exc}", file=sys.stderr)
        return 2
    except (CaseSetError, CheckpointError) as exc:
        print(f"declaration error: {exc}", file=sys.stderr)
        return 2
    except LatencyError as exc:
        print(f"cannot measure: {exc}", file=sys.stderr)
        return 2
    return 2


def _evaluate(args) -> int:
    from lab.core import evaluate_answer
    from lab.evaluate import format_observation, run

    prompt = validate_prompt(args.prompt)
    if args.repeat < 1:
        raise PromptError("--repeat must be at least 1")

    pf = preflight()
    service = build_service(pf)
    try:
        if args.answer:
            answer = validate_prompt(args.answer)
            print(format_observation(evaluate_answer(service, prompt, answer)))
        else:
            run(service, prompt, repeat=args.repeat)
    except Exception as exc:  # noqa: BLE001 — reported without a traceback
        print(
            f"\n{failed_operation(exc)} failed: {aws_error_code(exc)}\n"
            "The guardrail configuration was not modified.",
            file=sys.stderr,
        )
        return 1
    return 0


def _checkpoint(args) -> int:
    from lab.checkpoints import load_checkpoints, run

    # Same reasoning as conformance: an unknown module number is a typo.
    load_checkpoints(module=args.module)

    pf = preflight()
    return run(build_service(pf), args.module)


def _conformance(args) -> int:
    from lab.cases import load_cases
    from lab.conformance import run

    if not 1 <= args.repeat <= 20:
        raise CaseSetError("--repeat must be between 1 and 20")

    # Validate the declaration before touching AWS: an unknown set name or an
    # unreadable case file is a typo, and a typo should not cost a credentials
    # round trip to diagnose.
    load_cases(only=args.case_set)

    pf = preflight()
    return run(
        build_service(pf),
        pf,
        repeat=args.repeat,
        only=args.case_set,
        out=args.out,
        record=args.record,
    )


def _latency(args) -> int:
    """No preflight: this calls the deployed HTTP API, not Bedrock, so it needs
    no credentials and no guardrail id."""
    from lab.latency import run

    if args.warm < 3:
        raise LatencyError("--warm must be at least 3 (Requirement 10.5)")
    if args.gap >= 60:
        raise LatencyError(
            "--gap must stay under 60 seconds, or the samples are not consecutive "
            "and the environment may go cold between them"
        )
    if not args.api_base.startswith(("http://", "https://")):
        raise LatencyError(f"--api-base must be a URL, got {args.api_base!r}")

    return run(
        args.api_base,
        warm=args.warm,
        gap=args.gap,
        wait_cold=args.wait_cold,
        out=args.out,
    )


def _doctor(args) -> int:
    # Region only: the doctor's job is to find out what is missing, so requiring a
    # guardrail id or working credentials up front would defeat the purpose.
    import os

    from lab.doctor import run

    region = (
        os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or ""
    ).strip()
    if not region:
        raise PreflightError(
            "No AWS Region resolved. Set it with:\n  export AWS_REGION=eu-west-1"
        )
    return run(region, probe_write=args.probe_write, check_deploy=args.check_deploy)


def _teardown(args) -> int:
    import boto3

    from lab.teardown import run

    # Teardown needs no guardrail id: it finds the resource by name, so it works
    # after the environment variable is gone.
    pf = preflight(require_guardrail=False)
    return run(boto3.client("bedrock", region_name=pf.region))


if __name__ == "__main__":
    sys.exit(main())
