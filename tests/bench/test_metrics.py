"""Metrics verified on synthetic models whose scores are known in advance.

Spec section 14 requires this before any metric touches real data: if a
deliberately miscalibrated model slips past the calibration metrics, every
number the project publishes is false.
"""

import random

import pytest

from isflaky.bench.metrics import (
    accuracy,
    brier,
    confidence_interval,
    evaluate,
    expected_calibration_error,
    precision_recall,
    predict,
)
from isflaky.core.models import Label

# The gate owns the threshold in production; these synthetic models have no
# gate, so the tests state the one they are scored at.
THRESHOLD = 0.5


def graded(scores):
    """Pair scores with the labels a gate at THRESHOLD would return."""
    return (TRUTH, predict(scores, THRESHOLD), scores)

TRUTH = [Label.FLAKY if index % 3 else Label.REAL for index in range(300)]


def perfect() -> list[float]:
    return [1.0 if label is Label.FLAKY else 0.0 for label in TRUTH]


def coin_flip() -> list[float]:
    """Predicts flaky at chance, at the honest probability of 0.5."""
    rng = random.Random(0)
    return [rng.choice([0.49, 0.51]) for _ in TRUTH]


def overconfident() -> list[float]:
    """Right three times in four, but claims certainty every time.

    Accuracy alone cannot tell this apart from a well-calibrated model of the
    same accuracy, which is exactly why the calibration metrics exist.
    """
    rng = random.Random(1)
    return [
        (1.0 if label is Label.FLAKY else 0.0)
        if rng.random() < 0.75
        else (0.0 if label is Label.FLAKY else 1.0)
        for label in TRUTH
    ]


def well_calibrated() -> list[float]:
    """Same accuracy as `overconfident`, but says 0.75 instead of 1.0."""
    rng = random.Random(1)
    return [
        (0.75 if label is Label.FLAKY else 0.25)
        if rng.random() < 0.75
        else (0.25 if label is Label.FLAKY else 0.75)
        for label in TRUTH
    ]


def test_a_perfect_model_scores_one():
    assert evaluate(*graded(perfect())).accuracy == pytest.approx(1.0)


def test_a_perfect_model_has_no_calibration_error():
    scores = perfect()
    assert expected_calibration_error(*graded(scores)) == pytest.approx(0.0)
    assert brier(TRUTH, scores) == pytest.approx(0.0)


def test_a_coin_flip_model_scores_about_one_half():
    assert evaluate(*graded(coin_flip())).accuracy == pytest.approx(0.5, abs=0.1)


def test_a_coin_flip_model_has_the_worst_brier_score_of_an_honest_model():
    """Saying 0.5 forever earns 0.25: the price of knowing nothing, honestly."""
    assert brier(TRUTH, coin_flip()) == pytest.approx(0.25, abs=0.01)


def test_calibration_catches_the_overconfident_model():
    scores = overconfident()
    assert evaluate(*graded(scores)).accuracy == pytest.approx(0.75, abs=0.06)
    assert expected_calibration_error(*graded(scores)) == pytest.approx(0.25, abs=0.06)


def test_the_calibrated_model_wins_on_calibration_at_equal_accuracy():
    """The whole point: equal accuracy, and the metrics still separate them."""
    loud = evaluate(*graded(overconfident()))
    honest = evaluate(*graded(well_calibrated()))
    assert loud.accuracy == pytest.approx(honest.accuracy)
    assert honest.ece < loud.ece
    assert honest.brier < loud.brier


def test_per_class_precision_and_recall_are_reported_for_both_labels():
    scores = precision_recall(TRUTH, predict(perfect(), THRESHOLD))
    assert set(scores) == {Label.FLAKY, Label.REAL}
    assert all(value == pytest.approx(1.0) for pair in scores.values() for value in pair)


def test_recall_falls_when_a_class_is_never_predicted():
    """The majority-class trap: 67% accuracy, zero recall on the minority."""
    always_flaky = [1.0] * len(TRUTH)
    scores = precision_recall(TRUTH, predict(always_flaky, THRESHOLD))
    assert scores[Label.REAL].recall == pytest.approx(0.0)
    assert scores[Label.FLAKY].recall == pytest.approx(1.0)


def test_precision_is_zero_rather_than_undefined_without_predictions():
    never_flaky = predict([0.0] * len(TRUTH), THRESHOLD)
    assert precision_recall(TRUTH, never_flaky)[Label.FLAKY].precision == 0.0


def test_a_confidence_interval_brackets_the_point_estimate():
    low, high = confidence_interval(lambda truth, scores: 1.0, TRUTH, overconfident())
    assert low <= 1.0 <= high


def test_a_wider_interval_comes_from_a_smaller_sample():
    """The dataset is small, so every published number must carry this."""
    predictions = predict(overconfident(), THRESHOLD)
    narrow = confidence_interval(accuracy, TRUTH, predictions)
    wide = confidence_interval(accuracy, TRUTH[:20], predictions[:20])
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])


def test_the_interval_of_a_perfect_model_is_pinned_to_one():
    low, high = confidence_interval(accuracy, TRUTH, predict(perfect(), THRESHOLD))
    assert low == pytest.approx(1.0)
    assert high == pytest.approx(1.0)


def test_evaluate_reports_the_sample_size():
    """Spec section 18: no number is published without its n."""
    assert evaluate(*graded(perfect())).n == len(TRUTH)


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError):
        evaluate(TRUTH, predict(perfect(), THRESHOLD), perfect()[:10])
