"""Table-driven gate tests.

The gate holds every asymmetric-cost decision, so it is the one component that
must be exhaustively testable with no model and no network present.
"""

import pytest

from isflaky.core.models import Answers, Failure, Label
from isflaky.engine.questions import load_question_set
from isflaky.gate.policy import Thresholds, decide

ATOMIC = load_question_set("atomic")
DIRECT = load_question_set("direct")


def answers(values: dict[str, float], truncated: bool = False) -> Answers:
    return Answers(values=values, latency_ms=1.0, truncated=truncated)


def atomic(**overrides: float) -> Answers:
    values = {question.name: 0.5 for question in ATOMIC.questions}
    values.update(overrides)
    return answers(values)


CONFIDENT_FLAKY = atomic(
    network_error=0.95,
    external_service=0.9,
    timing_dependent=0.8,
    assertion_failure=0.02,
    touches_test_code=0.02,
    determinism=0.05,
    resource_contention=0.6,
    import_or_env=0.05,
)
CONFIDENT_REAL = atomic(
    network_error=0.02,
    external_service=0.02,
    timing_dependent=0.05,
    assertion_failure=0.97,
    touches_test_code=0.95,
    determinism=0.95,
    resource_contention=0.02,
    import_or_env=0.1,
)


def test_a_single_question_set_passes_its_probability_through():
    """Spec 7.1 prints p; for one question it must be that question's answer."""
    verdict = decide(answers({"flaky": 0.91}), DIRECT, Thresholds(flaky=0.5))
    assert verdict.probability == pytest.approx(0.91)


def test_probability_stays_in_range_for_every_corner_of_the_atomic_set():
    for value in (0.0, 0.5, 1.0):
        values = {question.name: value for question in ATOMIC.questions}
        verdict = decide(answers(values), ATOMIC, Thresholds())
        assert 0.0 <= verdict.probability <= 1.0


@pytest.mark.parametrize("threshold", [0.3, 0.5, 0.8])
def test_flaky_above_the_threshold_with_confidence_is_not_escalated(threshold):
    verdict = decide(
        CONFIDENT_FLAKY, ATOMIC, Thresholds(flaky=threshold, confidence=0.3)
    )
    assert verdict.label is Label.FLAKY
    assert verdict.escalated is False
    assert verdict.safe_to_rerun is True


@pytest.mark.parametrize("threshold", [0.3, 0.5, 0.8])
def test_real_evidence_is_labelled_real_at_every_threshold(threshold):
    verdict = decide(
        CONFIDENT_REAL, ATOMIC, Thresholds(flaky=threshold, confidence=0.3)
    )
    assert verdict.label is Label.REAL
    assert verdict.safe_to_rerun is False


@pytest.mark.parametrize("probability", [0.51, 0.6, 0.99])
def test_low_confidence_escalates_regardless_of_probability(probability):
    """Confidence gates independently of which side of the line p falls on."""
    verdict = decide(
        answers({"flaky": probability}), DIRECT, Thresholds(flaky=0.5, confidence=1.01)
    )
    assert verdict.escalated is True
    assert verdict.safe_to_rerun is False


@pytest.mark.parametrize(
    "values",
    [
        {"flaky": 0.0},
        {"flaky": 0.5},
        {"flaky": 1.0},
    ],
)
@pytest.mark.parametrize("confidence", [0.0, 0.5, 0.9, 1.0])
def test_an_escalated_verdict_is_never_safe_to_rerun(values, confidence):
    """Spec 7.3, hard requirement: uncertainty never reads as safe."""
    verdict = decide(answers(values), DIRECT, Thresholds(confidence=confidence))
    assert not (verdict.escalated and verdict.safe_to_rerun)


def test_a_wholly_unknown_answer_escalates():
    verdict = decide(answers({"flaky": 0.5}), DIRECT, Thresholds())
    assert verdict.probability == pytest.approx(0.5)
    assert verdict.confidence == pytest.approx(0.0)
    assert verdict.escalated is True


def test_a_truncated_state_escalates_even_when_certain():
    """A verdict read off a truncated state cannot claim to have seen the log."""
    verdict = decide(
        answers({"flaky": 0.99}, truncated=True), DIRECT, Thresholds(confidence=0.1)
    )
    assert verdict.escalated is True
    assert verdict.safe_to_rerun is False


@pytest.mark.parametrize(
    ("cost_ratio", "expected"),
    [(1.0, 0.5), (4.0, 0.8), (9.0, 0.9)],
)
def test_the_cost_ratio_sets_the_boundary_when_no_threshold_is_given(
    cost_ratio, expected
):
    """Mislabelling a real regression as flaky costs cost_ratio times more."""
    assert Thresholds(cost_ratio=cost_ratio).flaky_threshold == pytest.approx(expected)


def test_an_explicit_threshold_overrides_the_cost_ratio():
    assert Thresholds(flaky=0.35, cost_ratio=9.0).flaky_threshold == pytest.approx(0.35)


@pytest.mark.parametrize("cost_ratio", [1.0, 4.0, 19.0])
def test_a_rising_cost_ratio_never_makes_a_borderline_case_safer(cost_ratio):
    verdict = decide(
        answers({"flaky": 0.85}), DIRECT, Thresholds(cost_ratio=cost_ratio, confidence=0.3)
    )
    if cost_ratio > 5.0:
        assert verdict.label is Label.REAL
    else:
        assert verdict.label is Label.FLAKY


def test_the_reason_only_cites_answers_that_argued_for_the_verdict():
    """A reason listing signals that argued the other way defends nothing."""
    verdict = decide(CONFIDENT_FLAKY, ATOMIC, Thresholds(confidence=0.3))
    against = ("deterministic assertion mismatch", "looks deterministic")
    assert verdict.reason.count(";") == 1
    assert not any(phrase in verdict.reason for phrase in against)


def test_the_reason_is_readable_for_a_real_regression():
    verdict = decide(CONFIDENT_REAL, ATOMIC, Thresholds(confidence=0.3))
    assert "assertion" in verdict.reason


def test_the_cause_comes_from_the_failure_when_one_is_given():
    failure = Failure(
        test_id="tests/test_api.py::test_retry",
        error="ConnectionResetError: [Errno 104]",
        traceback="",
        log_context="",
        line_no=2841,
    )
    verdict = decide(CONFIDENT_FLAKY, ATOMIC, Thresholds(), failure=failure)
    assert verdict.cause == "L2841: ConnectionResetError: [Errno 104]"


def test_the_cause_is_empty_without_a_failure():
    assert decide(CONFIDENT_FLAKY, ATOMIC, Thresholds()).cause == ""
