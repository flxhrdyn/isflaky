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
    """Partition by CI run, never by row, so every model sees the same split.

    Grouping by run rather than by test is what keeps the holdout honest: one
    broken fixture fails dozens of tests in the same run, and splitting those
    across the two sides would let the fitted threshold see its own answers.

    Runs differ enormously in size - a single run can hold most of the dataset -
    so they are packed largest first onto whichever side is furthest below its
    share, and the result is rejected if either side ends up without both
    labels. A fit split holding one class cannot fit a threshold at all.
    """
    runs = _runs(rows)
    if len(runs) < 2:
        return (list(rows), [])

    order = sorted(runs, key=lambda run: len(runs[run]), reverse=True)
    random.Random(seed).shuffle(order)
    order.sort(key=lambda run: len(runs[run]), reverse=True)

    target = len(rows) * (1.0 - holdout)
    fit_runs: set[int] = set()
    packed = 0
    for run in order:
        if packed < target:
            fit_runs.add(run)
            packed += len(runs[run])

    _repair(runs, fit_runs)
    fit = [row for row in rows if row.run_id in fit_runs]
    holdout_rows = [row for row in rows if row.run_id not in fit_runs]
    _reject_single_class(fit, holdout_rows, runs)
    return (fit, holdout_rows)


def _reject_single_class(
    fit: Sequence[Row], holdout: Sequence[Row], runs: dict[int, list[Row]]
) -> None:
    """Refuse a split that cannot measure both classes.

    When every record of a label comes from one CI run, no run-level split can
    put that label on both sides, and the run is one event rather than many
    observations. Reporting a number from it would describe a single broken
    commit, so the benchmark stops here instead.
    """
    if {row.truth for row in fit} == {row.truth for row in holdout} == set(Label):
        return
    origins = {
        label: {run for run, group in runs.items() if any(r.truth is label for r in group)}
        for label in Label
    }
    trapped = [label.value for label, where in origins.items() if len(where) < 2]
    raise ValueError(
        "cannot split: "
        + (
            f"every {', '.join(trapped)} record comes from a single CI run"
            if trapped
            else "one side would hold a single class"
        )
    )


def _runs(rows: Sequence[Row]) -> dict[int, list[Row]]:
    grouped: dict[int, list[Row]] = {}
    for row in rows:
        grouped.setdefault(row.run_id, []).append(row)
    return grouped


def _repair(runs: dict[int, list[Row]], fit_runs: set[int]) -> None:
    """Move the smallest run that supplies a label the side is missing.

    A fit side holding one class cannot fit a threshold, and a holdout side
    holding one class cannot measure recall on the other. Packing by size alone
    produces both often enough on a dataset this concentrated.
    """
    for label in Label:
        _ensure(runs, fit_runs, label, into_fit=True)
        _ensure(runs, fit_runs, label, into_fit=False)


def _ensure(
    runs: dict[int, list[Row]], fit_runs: set[int], label: Label, into_fit: bool
) -> None:
    side = {run for run in runs if (run in fit_runs) == into_fit}
    other = set(runs) - side
    if any(row.truth is label for run in side for row in runs[run]):
        return
    donors = [
        run
        for run in other
        if any(row.truth is label for row in runs[run])
        # Never empty the other side to fill this one.
        and len(other) > 1
    ]
    if not donors:
        return
    smallest = min(donors, key=lambda run: len(runs[run]))
    fit_runs.add(smallest) if into_fit else fit_runs.discard(smallest)


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
