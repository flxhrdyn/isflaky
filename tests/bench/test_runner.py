"""The runner must measure the same path production takes.

Spec section 9.3: a benchmark that collapses state differently, or gates
differently, than the CLI reports numbers that are quietly false.
"""

import pytest

from isflaky.bench.runner import mcnemar, run
from isflaky.core.models import Answers, Failure, Label, LabeledFailure, Provenance
from isflaky.engine.questions import load_question_set
from isflaky.gate.policy import Thresholds

DIRECT = load_question_set("direct")


def record(test_id: str, label: Label) -> LabeledFailure:
    return LabeledFailure(
        failure=Failure(
            test_id=test_id,
            error="ConnectionResetError: [Errno 104]",
            traceback="",
            log_context="",
            line_no=1,
        ),
        label=label,
        provenance=Provenance(
            repo="owner/repo",
            run_id=abs(hash(test_id)) % 1000,
            attempt=1,
            head_sha="abc",
            url="",
        ),
    )


DATASET = [
    record("tests/test_a.py::test_one", Label.FLAKY),
    record("tests/test_b.py::test_two", Label.REAL),
    record("tests/test_c.py::test_three", Label.FLAKY),
]


class Fixed:
    """Answers the same probability for every question, every time."""

    def __init__(self, value: float) -> None:
        self._value = value

    def decide(self, state, questions) -> Answers:
        return Answers(
            values={question.name: self._value for question in questions.questions},
            latency_ms=1.0,
            truncated=False,
        )


class Exploding:
    def __init__(self, fails_on: str) -> None:
        self._fails_on = fails_on

    def decide(self, state, questions) -> Answers:
        if state["test_id"] == self._fails_on:
            raise RuntimeError("rate limited")
        return Answers(values={q.name: 0.9 for q in questions.questions}, latency_ms=1.0, truncated=False)


class Recording:
    def __init__(self) -> None:
        self.states: list[dict] = []

    def decide(self, state, questions) -> Answers:
        self.states.append(dict(state))
        return Answers(values={q.name: 0.9 for q in questions.questions}, latency_ms=1.0, truncated=False)


def test_one_row_per_record_per_model():
    rows = run(DATASET, {"high": Fixed(0.9), "low": Fixed(0.1)}, DIRECT, Thresholds())
    assert len(rows) == len(DATASET) * 2
    assert {row.model for row in rows} == {"high", "low"}
    assert len([row for row in rows if row.model == "high"]) == len(DATASET)


def test_every_row_carries_the_run_it_came_from():
    """The split groups by run, so the row must remember which one it was."""
    rows = run(DATASET, {"m": Fixed(0.9)}, DIRECT, Thresholds())
    assert [r.run_id for r in rows] == [item.provenance.run_id for item in DATASET]


def test_every_row_carries_the_ground_truth_label():
    rows = run(DATASET, {"high": Fixed(0.9)}, DIRECT, Thresholds())
    assert [row.truth for row in rows] == [item.label for item in DATASET]


def test_a_model_raising_on_one_record_does_not_abort_the_run():
    """A rate limit at record 2 of 300 must not cost the other 299."""
    model = Exploding("tests/test_b.py::test_two")
    rows = run(DATASET, {"flaky": model}, DIRECT, Thresholds(confidence=0.3))
    assert len(rows) == len(DATASET)
    failed = [row for row in rows if row.error]
    assert len(failed) == 1
    assert "rate limited" in failed[0].error


def test_a_failed_call_escalates_rather_than_guessing():
    model = Exploding("tests/test_b.py::test_two")
    rows = run(DATASET, {"flaky": model}, DIRECT, Thresholds(confidence=0.3))
    failed = next(row for row in rows if row.error)
    assert failed.escalated is True
    assert failed.probability == pytest.approx(0.5)
    assert failed.predicted is Label.REAL


def test_the_state_comes_from_the_production_collapse():
    recording = Recording()
    run(DATASET[:1], {"m": recording}, DIRECT, Thresholds())
    assert set(recording.states[0]) == {
        "test_id",
        "error",
        "traceback",
        "log_context",
        "changed_files",
    }


def test_the_verdict_comes_from_the_gate():
    """Same answers, different thresholds, different label: the gate decides."""
    lenient = run(DATASET, {"m": Fixed(0.7)}, DIRECT, Thresholds(flaky=0.6, confidence=0.3))
    strict = run(DATASET, {"m": Fixed(0.7)}, DIRECT, Thresholds(flaky=0.8, confidence=0.3))
    assert all(row.predicted is Label.FLAKY for row in lenient)
    assert all(row.predicted is Label.REAL for row in strict)


def test_rows_expose_the_score_the_metrics_consume():
    rows = run(DATASET, {"m": Fixed(0.9)}, DIRECT, Thresholds())
    assert all(0.0 <= row.probability <= 1.0 for row in rows)


def test_mcnemar_finds_no_difference_between_identical_models():
    rows = run(DATASET, {"a": Fixed(0.9), "b": Fixed(0.9)}, DIRECT, Thresholds())
    result = mcnemar(
        [row for row in rows if row.model == "a"],
        [row for row in rows if row.model == "b"],
    )
    assert result.discordant == 0
    assert result.p_value == pytest.approx(1.0)


def test_mcnemar_counts_only_the_records_the_models_disagree_on():
    """The paired test's whole point: agreements carry no information."""
    truth = [record(f"t{i}::x", Label.FLAKY) for i in range(10)]
    rows = run(truth, {"right": Fixed(0.99), "wrong": Fixed(0.01)}, DIRECT, Thresholds())
    result = mcnemar(
        [row for row in rows if row.model == "right"],
        [row for row in rows if row.model == "wrong"],
    )
    assert result.discordant == 10
    assert result.only_first_correct == 10
    assert result.p_value < 0.01


def test_mcnemar_rejects_unpaired_rows():
    rows = run(DATASET, {"a": Fixed(0.9)}, DIRECT, Thresholds())
    with pytest.raises(ValueError):
        mcnemar(rows, rows[:1])
