"""Accuracy, calibration, and confidence intervals over predicted probabilities.

A score here is P(flaky). Accuracy alone cannot separate a model that is right
three times in four from one that is right three times in four while claiming
certainty, so calibration is reported beside it rather than as an extra.
"""

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from isflaky.core.models import Label

_THRESHOLD = 0.5
_BINS = 10
_RESAMPLES = 2000
_LEVEL = 0.95
_SEED = 0

Metric = Callable[[Sequence[Label], Sequence[float]], float]


class ClassScores(NamedTuple):
    precision: float
    recall: float


@dataclass(frozen=True)
class Evaluation:
    # The dataset is small enough that n belongs next to every number.
    n: int
    accuracy: float
    ece: float
    brier: float
    per_class: Mapping[Label, ClassScores]


def evaluate(truth: Sequence[Label], scores: Sequence[float]) -> Evaluation:
    _require_same_length(truth, scores)
    return Evaluation(
        n=len(truth),
        accuracy=accuracy(truth, scores),
        ece=expected_calibration_error(truth, scores),
        brier=brier(truth, scores),
        per_class=precision_recall(truth, scores),
    )


def accuracy(truth: Sequence[Label], scores: Sequence[float]) -> float:
    _require_same_length(truth, scores)
    if not truth:
        return 0.0
    hits = sum(1 for label, score in zip(truth, scores) if _predict(score) is label)
    return hits / len(truth)


def precision_recall(
    truth: Sequence[Label], scores: Sequence[float]
) -> dict[Label, ClassScores]:
    _require_same_length(truth, scores)
    predictions = [_predict(score) for score in scores]
    return {label: _scores_for(label, truth, predictions) for label in Label}


def brier(truth: Sequence[Label], scores: Sequence[float]) -> float:
    """Mean squared error against the outcome, so miscalibration costs directly."""
    _require_same_length(truth, scores)
    if not truth:
        return 0.0
    return sum(
        (score - _outcome(label)) ** 2 for label, score in zip(truth, scores)
    ) / len(truth)


def expected_calibration_error(
    truth: Sequence[Label], scores: Sequence[float], bins: int = _BINS
) -> float:
    """Gap between stated confidence and observed accuracy, weighted by bin size.

    Confidence is the distance from the coin flip in whichever direction the
    prediction went, matching how the gate derives it from a Noul answer.
    """
    _require_same_length(truth, scores)
    if not truth:
        return 0.0
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]
    for label, score in zip(truth, scores):
        confidence = max(score, 1.0 - score)
        buckets[_bucket_of(confidence, bins)].append(
            (confidence, _predict(score) is label)
        )
    error = 0.0
    for bucket in buckets:
        if not bucket:
            continue
        stated = sum(confidence for confidence, _ in bucket) / len(bucket)
        observed = sum(1 for _, hit in bucket if hit) / len(bucket)
        error += len(bucket) / len(truth) * abs(stated - observed)
    return error


def confidence_interval(
    truth: Sequence[Label],
    scores: Sequence[float],
    metric: Metric,
    level: float = _LEVEL,
    resamples: int = _RESAMPLES,
    seed: int = _SEED,
) -> tuple[float, float]:
    """Percentile bootstrap interval, seeded so published numbers reproduce."""
    _require_same_length(truth, scores)
    if not truth:
        return (0.0, 0.0)
    rng = random.Random(seed)
    indices = range(len(truth))
    estimates = []
    for _ in range(resamples):
        drawn = [rng.choice(indices) for _ in indices]
        estimates.append(
            metric([truth[i] for i in drawn], [scores[i] for i in drawn])
        )
    estimates.sort()
    tail = (1.0 - level) / 2.0
    return (_percentile(estimates, tail), _percentile(estimates, 1.0 - tail))


def _predict(score: float) -> Label:
    return Label.FLAKY if score >= _THRESHOLD else Label.REAL


def _outcome(label: Label) -> float:
    return 1.0 if label is Label.FLAKY else 0.0


def _bucket_of(confidence: float, bins: int) -> int:
    # Confidence runs over [0.5, 1.0], so the bins cover that half only.
    position = int((confidence - 0.5) * 2.0 * bins)
    return min(max(position, 0), bins - 1)


def _scores_for(
    label: Label, truth: Sequence[Label], predictions: Sequence[Label]
) -> ClassScores:
    predicted = sum(1 for prediction in predictions if prediction is label)
    actual = sum(1 for actual_label in truth if actual_label is label)
    hits = sum(
        1
        for actual_label, prediction in zip(truth, predictions)
        if prediction is label and actual_label is label
    )
    # A class never predicted has zero precision, not an undefined one: the
    # published table must have a number in every cell.
    return ClassScores(
        precision=hits / predicted if predicted else 0.0,
        recall=hits / actual if actual else 0.0,
    )


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    position = fraction * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    weight = position - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def _require_same_length(truth: Sequence[Label], scores: Sequence[float]) -> None:
    if len(truth) != len(scores):
        raise ValueError(f"{len(truth)} labels against {len(scores)} scores")
