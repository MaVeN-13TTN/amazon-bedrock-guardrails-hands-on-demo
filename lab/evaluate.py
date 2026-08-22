"""`lab-cli evaluate` — screen one prompt and print what the policy engine did.

Prints the no-intervention case explicitly. Silence on a clean pass would leave an
attendee unsure whether the call happened at all, which is the opposite of what a
first exercise should teach.
"""
from __future__ import annotations

from lab.core import Observation, evaluate_prompt


def format_observation(obs: Observation, *, show_forwarded: bool = True) -> str:
    lines = [
        f"prompt          {obs.prompt}",
        f"guardrail action  {obs.action}",
        f"model invoked     {'yes' if obs.model_invoked else 'no'}",
        f"latency           {obs.latency_ms}ms",
    ]

    if obs.findings:
        lines.append(f"findings          {len(obs.findings)}")
        for finding in obs.findings:
            detail = finding.detail or "(unnamed)"
            action = finding.action or "(no action)"
            line = f"  · {finding.policy:<18} {detail:<28} {action}"
            if finding.score is not None:
                line += f"  score={finding.score}"
            if finding.threshold is not None:
                line += f" threshold={finding.threshold}"
            lines.append(line)
    else:
        # Stated, not implied: an attendee must be able to tell "evaluated and
        # allowed" from "nothing ran".
        lines.append("findings          none — no policy intervened")

    if show_forwarded and obs.forwarded_text and obs.forwarded_text != obs.prompt:
        lines.append(f"text forwarded    {obs.forwarded_text}")
        lines.append("                  (rewritten: a policy masked part of the input)")

    return "\n".join(lines)


def run(service, prompt: str, repeat: int = 1) -> list[Observation]:
    """Evaluate one prompt `repeat` times, printing each result."""
    observations: list[Observation] = []
    for index in range(repeat):
        if repeat > 1:
            print(f"\n--- repetition {index + 1} of {repeat}")
        obs = evaluate_prompt(service, prompt)
        observations.append(obs)
        print(format_observation(obs))

    if repeat > 1:
        blocked = sum(o.intervened for o in observations)
        print(
            f"\nsummary           intervened in {blocked} of {repeat} repetitions"
            + ("  (probabilistic)" if 0 < blocked < repeat else "")
        )
    return observations
