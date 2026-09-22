"""Fitting the operating point, and reporting it somewhere it was not fitted.

Spec section 9: thresholds are fitted on the fit split and reported on the
holdout split. A threshold chosen and reported on the same rows reports how
well it memorised them.
"""

import pytest

from isflaky.bench.runner import Row
from isflaky.bench.sweep import regate, split, sweep
from isflaky.core.models import Label
from isflaky.gate.policy import Thresholds


def row(model: str, test_id: str, truth: Label, probability: float) -> Row:
    return Row(
        model=model,
        question_set="direct",
        test_id=test_id,
        repo="owner/repo",
        truth=truth,
        predicted=Label.REAL,
        probability=probability,
        confidence=0.0,
        escalated=True,
        latency_ms=1.0,
        error="",
    )


def dataset(model: str = "m") -> list[Row]:
    """Twelve records whose probability tracks the truth with some overlap."""
    flaky = [row(model, f"flaky{i}", Label.FLAKY, 0.5 + i * 0.05) for i in range(8)]
    real = [row(model, f"real{i}", Label.REAL, 0.35 + i * 0.1) for i in range(4)]
    return flaky + real


def test_the_split_covers_every_row_exactly_once():
    fit, holdout = split(dataset())
    assert len(fit) + len(holdout) == len(dataset())
    assert not {r.test_id for r in fit} & {r.test_id for r in holdout}


def test_both_sides_of_the_split_are_non_empty():
    fit, holdout = split(dataset())
    assert fit and holdout


def test_the_same_records_land_on_the_same_side_for_every_model():
    """McNemar pairs rows by record, so the split cannot differ per model."""
    rows = dataset("a") + dataset("b")
    fit, holdout = split(rows)
    for side in (fit, holdout):
        by_model: dict[str, set[str]] = {}
        for item in side:
            by_model.setdefault(item.model, set()).add(item.test_id)
        assert by_model["a"] == by_model["b"]


def test_the_split_is_stable_across_calls():
    first, _ = split(dataset())
    second, _ = split(dataset())
    assert [r.test_id for r in first] == [r.test_id for r in second]


def test_a_costlier_false_flaky_never_lowers_the_threshold():
    """Calling a real regression flaky is the expensive direction."""
    cheap = sweep(dataset(), cost_ratio=1.0)
    dear = sweep(dataset(), cost_ratio=9.0)
    assert dear.threshold >= cheap.threshold


def test_the_fitted_threshold_beats_the_default_on_the_fit_split():
    fitted = sweep(dataset(), cost_ratio=4.0)
    assert fitted.expected_cost <= _cost(dataset(), Thresholds(cost_ratio=4.0), 4.0)


def test_a_separable_dataset_is_fitted_perfectly():
    clean = [
        row("m", "f1", Label.FLAKY, 0.9),
        row("m", "f2", Label.FLAKY, 0.8),
        row("m", "r1", Label.REAL, 0.2),
        row("m", "r2", Label.REAL, 0.1),
    ]
    assert sweep(clean, cost_ratio=4.0).expected_cost == pytest.approx(0.0)


def test_regate_recomputes_the_verdict_from_the_recorded_probability():
    lenient = regate(dataset(), Thresholds(flaky=0.3, confidence=0.0))
    strict = regate(dataset(), Thresholds(flaky=0.95, confidence=0.0))
    assert all(item.predicted is Label.FLAKY for item in lenient)
    assert all(item.predicted is Label.REAL for item in strict)


def test_regate_keeps_the_probability_and_the_record_identity():
    before = dataset()
    after = regate(before, Thresholds(flaky=0.6))
    assert [item.test_id for item in after] == [item.test_id for item in before]
    assert [item.probability for item in after] == [item.probability for item in before]


def test_regate_leaves_a_failed_call_escalated():
    """A model that never answered has no probability to re-gate."""
    failed = Row(
        model="m",
        question_set="direct",
        test_id="t",
        repo="owner/repo",
        truth=Label.FLAKY,
        predicted=Label.REAL,
        probability=0.5,
        confidence=0.0,
        escalated=True,
        latency_ms=0.0,
        error="RuntimeError: rate limited",
    )
    regated = regate([failed], Thresholds(flaky=0.1, confidence=0.0))[0]
    assert regated.escalated is True
    assert regated.error == failed.error


def _cost(rows, thresholds: Thresholds, cost_ratio: float) -> float:
    from isflaky.bench.sweep import expected_cost

    return expected_cost(regate(rows, thresholds), cost_ratio)
