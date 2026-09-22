import dataclasses

import pytest

from isflaky.core.models import Answers, Label, Verdict


def test_answers_carry_values_latency_and_truncation():
    answers = Answers(values={"flaky": 0.8}, latency_ms=120.0, truncated=False)
    assert answers.values["flaky"] == 0.8
    assert answers.latency_ms == 120.0
    assert answers.truncated is False


def test_answers_are_frozen():
    answers = Answers(values={"flaky": 0.8}, latency_ms=120.0, truncated=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        answers.latency_ms = 1.0  # type: ignore[misc]


def test_verdict_carries_probability_confidence_cause_and_reason():
    verdict = Verdict(
        label=Label.FLAKY,
        probability=0.91,
        confidence=0.88,
        cause="L2841: ConnectionResetError: [Errno 104]",
        reason="network error present",
        escalated=False,
    )
    assert verdict.label is Label.FLAKY
    assert verdict.probability == 0.91
    assert verdict.confidence == 0.88
    assert "ConnectionResetError" in verdict.cause
    assert verdict.reason == "network error present"
    assert verdict.escalated is False


def test_escalation_is_independent_of_the_chosen_label():
    """Spec 7.3 maps uncertainty to exit code 1 whichever label was picked."""
    verdict = Verdict(
        label=Label.FLAKY,
        probability=0.55,
        confidence=0.2,
        cause="L1: boom",
        reason="no strong signal",
        escalated=True,
    )
    assert verdict.label is Label.FLAKY
    assert verdict.escalated is True


def test_verdict_is_frozen():
    verdict = Verdict(
        label=Label.REAL,
        probability=0.2,
        confidence=0.9,
        cause="L1: boom",
        reason="deterministic assertion",
        escalated=False,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.probability = 0.5  # type: ignore[misc]
