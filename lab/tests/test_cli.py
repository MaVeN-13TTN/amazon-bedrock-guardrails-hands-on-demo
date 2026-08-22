"""The CLI surface: exit statuses and the messages a stuck attendee reads."""
from __future__ import annotations

import pytest

from lab.__main__ import build_parser, main


def test_every_documented_subcommand_parses():
    parser = build_parser()
    assert parser.parse_args(["evaluate", "--prompt", "hi"]).command == "evaluate"
    assert parser.parse_args(["checkpoint", "--module", "1"]).module == 1
    assert parser.parse_args(["conformance", "--repeat", "5"]).repeat == 5
    assert parser.parse_args(["teardown"]).command == "teardown"


def test_no_subcommand_is_an_error():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_a_missing_prerequisite_exits_two_before_any_aws_call(monkeypatch, capsys):
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    status = main(["evaluate", "--prompt", "When do points open?"])
    err = capsys.readouterr().err

    assert status == 2
    assert "GUARDRAIL_ID" in err
    assert "terraform" in err


def test_an_empty_prompt_exits_two_naming_the_limit(monkeypatch, capsys):
    monkeypatch.setenv("GUARDRAIL_ID", "g-1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    status = main(["evaluate", "--prompt", "   "])
    assert status == 2
    assert "empty" in capsys.readouterr().err


def test_an_over_long_prompt_exits_two_naming_the_limit(monkeypatch, capsys):
    monkeypatch.setenv("GUARDRAIL_ID", "g-1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    status = main(["evaluate", "--prompt", "x" * 2001])
    assert status == 2
    assert "2000" in capsys.readouterr().err


def test_an_out_of_range_repeat_is_rejected(monkeypatch, capsys):
    monkeypatch.setenv("GUARDRAIL_ID", "g-1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")

    assert main(["conformance", "--repeat", "21"]) == 2
    assert "between 1 and 20" in capsys.readouterr().err


def test_an_unknown_case_set_exits_two_without_calling_aws(monkeypatch, capsys):
    """A typo in --set is a declaration error, diagnosable with no credentials."""
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)

    assert main(["conformance", "--set", "nope"]) == 2
    assert "no case set" in capsys.readouterr().err


def test_an_unknown_module_exits_two_without_calling_aws(monkeypatch, capsys):
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)

    assert main(["checkpoint", "--module", "99"]) == 2
    assert "no checkpoints declared for module 99" in capsys.readouterr().err
