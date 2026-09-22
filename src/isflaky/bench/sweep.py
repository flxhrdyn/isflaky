"""Fit the gate's operating point on one split and report it on another.

The sweep re-gates recorded probabilities through the gate's own policy, so a
fitted operating point and a live decision cannot drift apart. Fitting and
reporting on the same rows would measure memorisation, which is why `split`
exists and why the published numbers come from the holdout side.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass, replace

from isflaky.bench.runner import Row
from isflaky.core.models import Label
from isflaky.gate.policy import Thresholds, apply

_HOLDOUT = 0.5
_SEED = 0


@dataclass(frozen=True)
class Operating:
    threshold: float
    # Mean cost per record, in units of one flaky-called-real mistake.
    expected_cost: float


def split(
    rows: Sequence[Row], holdout: float = _HOLDOUT, seed: int = _SEED
) -> tuple[list[Row], list[Row]]:
    """Partition by record, never by row, so every model sees the same split."""
    identities = sorted({row.test_id for row in rows})
    random.Random(seed).shuffle(identities)
    cut = max(1, min(len(identities) - 1, round(len(identities) * (1.0 - holdout))))
    fit_side = set(identities[:cut])
    return (
        [row for row in rows if row.test_id in fit_side],
        [row for row in rows if row.test_id not in fit_side],
    )


def sweep(rows: Sequence[Row], cost_ratio: float) -> Operating:
    """Pick the cheapest threshold under the asymmetric cost.

    Candidates are the observed probabilities themselves rather than a fixed
    grid: the cost function only changes where a record crosses the line, so
    those are the only points worth testing and the answer is exact.
    """
    candidates = sorted({row.probability for row in rows} | {0.0, 1.0})
    best = Operating(threshold=candidates[-1], expected_cost=float("inf"))
    for candidate in candidates:
        cost = expected_cost(
            regate(rows, Thresholds(flaky=candidate, confidence=0.0)), cost_ratio
        )
        if cost < best.expected_cost:
            best = Operating(threshold=candidate, expected_cost=cost)
    return best


def regate(rows: Sequence[Row], thresholds: Thresholds) -> list[Row]:
    return [_regate(row, thresholds) for row in rows]


def expected_cost(rows: Sequence[Row], cost_ratio: float) -> float:
    """Mean cost, charging cost_ratio for calling a real regression flaky."""
    if not rows:
        return 0.0
    total = 0.0
    for row in rows:
        if row.truth is row.predicted:
            continue
        total += cost_ratio if row.truth is Label.REAL else 1.0
    return total / len(rows)


def _regate(row: Row, thresholds: Thresholds) -> Row:
    if row.error:
        return row
    verdict = apply(row.probability, thresholds)
    return replace(
        row,
        predicted=verdict.label,
        confidence=verdict.confidence,
        escalated=verdict.escalated,
    )
