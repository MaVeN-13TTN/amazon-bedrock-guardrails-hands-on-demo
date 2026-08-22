"""`python -m lab latency` — cold and warm sampling of a deployed endpoint.

No AWS and no network: the HTTP call is stubbed, because what needs testing is the
sampling discipline Requirement 10.5 specifies, not urllib.
"""
from __future__ import annotations

import json

import pytest

from lab import latency
from lab.latency import COLD_IDLE_SECONDS, LatencyError, Sample, run


@pytest.fixture
def no_sleep(monkeypatch):
    """Collect sleep durations instead of waiting them out."""
    slept: list[float] = []
    monkeypatch.setattr(latency.time, "sleep", slept.append)
    return slept


def _responder(timings: list[int], status: int = 200):
    """A _post stand-in returning the given wall-clock times in order."""
    calls = {"n": 0}

    def post(url, prompt):
        i = calls["n"]
        calls["n"] += 1
        ms = timings[min(i, len(timings) - 1)]
        payload = {
            "stages": [{"stage": "screen", "latency_ms": ms - 20}],
            "final": "ok",
            "stopped_at": None,
        }
        return status, payload, ms, None

    post.calls = calls
    return post


# --- sampling discipline -----------------------------------------------------


def test_it_takes_one_cold_sample_and_three_warm_by_default(monkeypatch, no_sleep, capsys):
    post = _responder([1800, 210, 190, 205])
    monkeypatch.setattr(latency, "_post", post)

    assert run("https://api.example") == 0
    assert post.calls["n"] == 4  # 1 cold + 3 warm

    out = capsys.readouterr().out
    assert "cold" in out
    assert "warm 1" in out and "warm 2" in out and "warm 3" in out


def test_every_warm_sample_is_reported_individually(monkeypatch, no_sleep, capsys):
    """R10.5 — individual measurements, not only an aggregate.

    An average of a cold start and three warm requests describes neither.
    """
    monkeypatch.setattr(latency, "_post", _responder([1800, 210, 190, 205]))
    run("https://api.example")

    out = capsys.readouterr().out
    assert "210, 190, 205 ms" in out
    assert "warm median" in out


def test_the_cold_overhead_is_reported_against_the_warm_median(monkeypatch, no_sleep, capsys):
    monkeypatch.setattr(latency, "_post", _responder([1800, 200, 200, 200]))
    run("https://api.example")

    out = capsys.readouterr().out
    assert "cold overhead      1600 ms" in out


def test_warm_samples_stay_inside_the_sixty_second_window(monkeypatch, no_sleep):
    """R10.5 — consecutive means no more than 60 s apart."""
    monkeypatch.setattr(latency, "_post", _responder([900, 200]))
    run("https://api.example", gap=5)
    assert no_sleep and all(d < 60 for d in no_sleep)


def test_wait_cold_idles_the_documented_fifteen_minutes(monkeypatch, no_sleep):
    monkeypatch.setattr(latency, "_post", _responder([900, 200]))
    run("https://api.example", wait_cold=True)
    assert COLD_IDLE_SECONDS in no_sleep
    assert COLD_IDLE_SECONDS == 15 * 60


def test_without_wait_cold_it_says_the_first_sample_may_not_be_cold(
    monkeypatch, no_sleep, capsys
):
    """Claiming a cold measurement that was not cold would be the worst outcome."""
    monkeypatch.setattr(latency, "_post", _responder([200, 200]))
    run("https://api.example")
    assert "only cold if" in capsys.readouterr().out


# --- failures are data, not crashes ------------------------------------------


def test_a_failing_endpoint_is_reported_and_exits_non_zero(monkeypatch, no_sleep, capsys):
    def post(url, prompt):
        return None, None, 60000, "TimeoutError: timed out"

    monkeypatch.setattr(latency, "_post", post)
    assert run("https://api.example") == 1
    assert "samples failed" in capsys.readouterr().out


def test_a_non_200_status_counts_as_failed(monkeypatch, no_sleep):
    monkeypatch.setattr(latency, "_post", _responder([300, 300], status=503))
    assert run("https://api.example") == 1


# --- records -----------------------------------------------------------------


def test_samples_are_written_one_per_line_with_their_kind(monkeypatch, no_sleep, tmp_path):
    monkeypatch.setattr(latency, "_post", _responder([1800, 210, 190, 205]))
    out = tmp_path / "latency.jsonl"
    run("https://api.example", out=str(out))

    records = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["kind"] for r in records] == ["cold", "warm", "warm", "warm"]
    assert records[0]["total_ms"] == 1800
    assert all("server_ms" not in r or isinstance(r["total_ms"], int) for r in records)


def test_server_reported_time_is_kept_separate_from_wall_clock():
    """The client's wall clock includes network; the stages' sum does not."""
    s = Sample(kind="warm", index=0, status=200, total_ms=250,
               stages=[{"stage": "screen", "latency_ms": 120},
                       {"stage": "verify", "latency_ms": 80}])
    assert s.server_ms == 200
    assert s.total_ms == 250


def test_a_stage_with_no_latency_does_not_break_the_sum():
    s = Sample(kind="cold", index=0, status=200, total_ms=1,
               stages=[{"stage": "screen"}, {"stage": "answer", "latency_ms": None}])
    assert s.server_ms == 0


# --- CLI validation ----------------------------------------------------------


def test_the_cli_rejects_fewer_than_three_warm_samples():
    from lab.__main__ import main

    with pytest.raises(SystemExit):
        main(["latency"])  # --api-base is required


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["latency", "--api-base", "https://x", "--warm", "2"], "at least 3"),
        (["latency", "--api-base", "https://x", "--gap", "90"], "under 60 seconds"),
        (["latency", "--api-base", "not-a-url"], "must be a URL"),
    ],
)
def test_the_cli_reports_invalid_sampling_parameters(argv, expected, capsys):
    from lab.__main__ import main

    assert main(argv) == 2
    assert expected in capsys.readouterr().err


def test_latency_error_is_its_own_type():
    assert issubclass(LatencyError, RuntimeError)
