"""Runs every model over the dataset through the production decision path.

The runner calls `collapse` and the gate exactly as the CLI does. A benchmark
that built its own state or applied its own thresholds would report numbers
for a system nobody ships (spec section 9.3).
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from isflaky.core.models import Label, LabeledFailure
from isflaky.engine.protocol import DecisionModel
from isflaky.engine.questions import QuestionSet
from isflaky.gate.policy import Thresholds, decide
from isflaky.parse.collapse import collapse

# A call that never returned is not evidence for either label.
_NO_EVIDENCE = 0.5


@dataclass(frozen=True)
class Row:
    model: str
    question_set: str
    test_id: str
    repo: str
    truth: Label
    predicted: Label
    probability: float
    confidence: float
    escalated: bool
    latency_ms: float
    # Empty unless the model raised; the row survives either way.
    error: str


@dataclass(frozen=True)
class McNemar:
    """Paired comparison over the records where two models disagree."""

    only_first_correct: int
    only_second_correct: int
    p_value: float

    @property
    def discordant(self) -> int:
        return self.only_first_correct + self.only_second_correct


def run(
    dataset: Sequence[LabeledFailure],
    models: Mapping[str, DecisionModel],
    questions: QuestionSet,
    thresholds: Thresholds,
    changed_files: str = "",
) -> list[Row]:
    return [
        _row(name, model, item, questions, thresholds, changed_files)
        for name, model in models.items()
        for item in dataset
    ]


def scores(rows: Sequence[Row]) -> list[float]:
    return [row.probability for row in rows]


def truth(rows: Sequence[Row]) -> list[Label]:
    return [row.truth for row in rows]


def mcnemar(first: Sequence[Row], second: Sequence[Row]) -> McNemar:
    """Exact two-sided binomial test on the discordant pairs.

    Exact rather than chi-squared because the dataset is small enough that the
    chi-squared approximation would be unsound at exactly the sample sizes this
    project has.
    """
    if len(first) != len(second):
        raise ValueError(f"{len(first)} rows against {len(second)} rows")
    for left, right in zip(first, second):
        if left.test_id != right.test_id:
            raise ValueError(f"unpaired rows: {left.test_id} against {right.test_id}")

    only_first = sum(
        1
        for left, right in zip(first, second)
        if _correct(left) and not _correct(right)
    )
    only_second = sum(
        1
        for left, right in zip(first, second)
        if _correct(right) and not _correct(left)
    )
    return McNemar(
        only_first_correct=only_first,
        only_second_correct=only_second,
        p_value=_binomial_p(only_first, only_second),
    )


def _row(
    name: str,
    model: DecisionModel,
    item: LabeledFailure,
    questions: QuestionSet,
    thresholds: Thresholds,
    changed_files: str,
) -> Row:
    state = collapse(item.failure, changed_files=changed_files)
    try:
        answers = model.decide(state, questions)
    except Exception as failed:  # noqa: BLE001 - one bad record must not end the run
        return _failed_row(name, item, questions, failed)

    verdict = decide(answers, questions, thresholds, failure=item.failure)
    return Row(
        model=name,
        question_set=questions.name,
        test_id=item.failure.test_id,
        repo=item.provenance.repo,
        truth=item.label,
        predicted=verdict.label,
        probability=verdict.probability,
        confidence=verdict.confidence,
        escalated=verdict.escalated,
        latency_ms=answers.latency_ms,
        error="",
    )


def _failed_row(
    name: str, item: LabeledFailure, questions: QuestionSet, failed: Exception
) -> Row:
    """A model that did not answer escalates to the expensive-safe side."""
    return Row(
        model=name,
        question_set=questions.name,
        test_id=item.failure.test_id,
        repo=item.provenance.repo,
        truth=item.label,
        predicted=Label.REAL,
        probability=_NO_EVIDENCE,
        confidence=0.0,
        escalated=True,
        latency_ms=0.0,
        error=f"{type(failed).__name__}: {failed}",
    )


def _correct(row: Row) -> bool:
    return row.predicted is row.truth


def _binomial_p(first: int, second: int) -> float:
    """Two-sided probability of a split this lopsided under a fair coin."""
    total = first + second
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, k) for k in range(min(first, second) + 1))
    return min(2.0 * tail / 2.0**total, 1.0)
