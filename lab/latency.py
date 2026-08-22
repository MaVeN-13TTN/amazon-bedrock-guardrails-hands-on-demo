"""`python -m lab latency` — measure a deployed endpoint, cold and warm.

Requirement 10.5 asks for one cold measurement after at least 15 minutes of
silence, and at least three consecutive warm ones no more than 60 seconds apart,
recorded **individually** rather than only as an aggregate. An average hides the
shape: a cold start is not a slow warm request, it is a different event, and
averaging the two produces a number that describes neither.

Nothing here needs AWS credentials — it calls the deployed HTTP API, not Bedrock.
"""
from __future__ import annotations

import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

# The idle period after which a Lambda execution environment is assumed reclaimed.
# AWS does not document a guaranteed figure; 15 minutes is the requirement's floor
# and is treated as an assumption, not a fact.
COLD_IDLE_SECONDS = 15 * 60
WARM_GAP_SECONDS = 5
WARM_COUNT = 3
TIMEOUT = 60


class LatencyError(RuntimeError):
    """The endpoint could not be measured, with the reason."""


@dataclass
class Sample:
    kind: str  # "cold" | "warm"
    index: int
    status: int | None
    total_ms: int
    stages: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def server_ms(self) -> int:
        """Time the pipeline reported, as distinct from wall clock at the client."""
        return sum(s.get("latency_ms") or 0 for s in self.stages)


def _post(url: str, prompt: str) -> tuple[int | None, dict | None, int, str | None]:
    body = json.dumps({"input": prompt}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"content-type": "application/json"}, method="POST"
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read())
            return resp.status, payload, int((time.perf_counter() - started) * 1000), None
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace")
        return exc.code, None, int((time.perf_counter() - started) * 1000), detail
    except Exception as exc:  # noqa: BLE001 — reported, not raised: a timeout is data
        elapsed = int((time.perf_counter() - started) * 1000)
        return None, None, elapsed, f"{type(exc).__name__}: {exc}"


def _sample(url: str, prompt: str, kind: str, index: int) -> Sample:
    status, payload, total, error = _post(url, prompt)
    return Sample(
        kind=kind,
        index=index,
        status=status,
        total_ms=total,
        stages=(payload or {}).get("stages", []),
        error=error,
    )


def run(
    api_base: str,
    *,
    prompt: str = "When are the collection points open?",
    warm: int = WARM_COUNT,
    gap: float = WARM_GAP_SECONDS,
    wait_cold: bool = False,
    out: str | None = None,
) -> int:
    """Take one cold sample and `warm` warm ones, printing each individually."""
    url = api_base.rstrip("/") + "/api/ask"

    if wait_cold:
        print(f"waiting {COLD_IDLE_SECONDS // 60} minutes for the execution environment "
              "to be reclaimed — Ctrl-C to skip")
        try:
            time.sleep(COLD_IDLE_SECONDS)
        except KeyboardInterrupt:
            print("\n  skipped: the first sample may not be genuinely cold")
    else:
        print("NOTE: --wait-cold was not given. The first sample is only cold if the")
        print("      endpoint has been idle at least 15 minutes already.")

    print(f"\nendpoint {url}\nprompt   {prompt!r}\n")

    samples = [_sample(url, prompt, "cold", 0)]
    print(f"  cold          {samples[0].total_ms:>6} ms  "
          f"(server {samples[0].server_ms} ms)"
          f"{'  ERROR: ' + samples[0].error if samples[0].error else ''}")

    for i in range(warm):
        time.sleep(gap)
        s = _sample(url, prompt, "warm", i)
        samples.append(s)
        print(f"  warm {i + 1:<8} {s.total_ms:>6} ms  (server {s.server_ms} ms)"
              f"{'  ERROR: ' + s.error if s.error else ''}")

    failed = [s for s in samples if s.error or s.status != 200]
    warm_ms = [s.total_ms for s in samples if s.kind == "warm" and not s.error]

    print()
    if warm_ms:
        cold = samples[0]
        print(f"warm individually  {', '.join(str(m) for m in warm_ms)} ms")
        print(f"warm median        {int(statistics.median(warm_ms))} ms")
        if not cold.error:
            overhead = cold.total_ms - int(statistics.median(warm_ms))
            print(f"cold overhead      {overhead} ms over the warm median")
            print("                   (this is the figure the runbook's warm-up step exists for)")
    if failed:
        print(f"\n{len(failed)} of {len(samples)} samples failed:")
        for s in failed:
            print(f"  {s.kind} {s.index}: status={s.status} {s.error}")

    if out:
        with open(out, "w", encoding="utf-8") as fh:
            for s in samples:
                fh.write(json.dumps(asdict(s)) + "\n")
        print(f"\nsamples written to {out}")

    return 1 if failed else 0
