"""Deterministic, network-free policy: answers plus thresholds become a verdict.

Every asymmetric-cost decision in the project lives here, which is what makes
the hard requirement in spec section 7.3 - uncertainty must never read as safe
to rerun - checkable in one place.
"""

from dataclasses import dataclass, field

from isflaky.core.models import Answers, Failure, Label, Verdict
from isflaky.engine.questions import QuestionSet

# Signed prior weights: positive evidence argues flaky, negative argues real.
# These are hand-set starting points, not fitted parameters; the threshold sweep
# in the benchmark reports the operating point rather than tuning these.
_WEIGHTS = {
    "flaky": 1.0,
    "network_error": 1.0,
    "timing_dependent": 1.0,
    "resource_contention": 0.9,
    "external_service": 0.8,
    "assertion_failure": -1.0,
    "touches_test_code": -0.9,
    "determinism": -1.0,
    "import_or_env": -0.6,
}

# Read when the answer is above 0.5, and when it is below.
_PHRASES = {
    "flaky": ("model reads this as flaky", "model reads this as a real failure"),
    "network_error": ("network error present", "no network error"),
    "timing_dependent": ("timing dependent", "not timing dependent"),
    "resource_contention": ("resource contention", "no resource contention"),
    "external_service": ("external service involved", "no external service"),
    "assertion_failure": ("deterministic assertion mismatch", "no assertion mismatch"),
    "touches_test_code": (
        "diff touches the failing module",
        "no diff touching this module",
    ),
    "determinism": ("looks deterministic", "looks nondeterministic"),
    "import_or_env": ("import or environment break", "no import or environment problem"),
}

_REASONS_SHOWN = 2


@dataclass(frozen=True)
class Thresholds:
    """The gate's operating point.

    `cost_ratio` is how much worse it is to call a real regression flaky than
    the reverse, and it sets the decision boundary unless `flaky` overrides it
    (the CLI's `--threshold`).
    """

    confidence: float = 0.6
    cost_ratio: float = 4.0
    flaky: float | None = field(default=None)

    @property
    def flaky_threshold(self) -> float:
        if self.flaky is not None:
            return self.flaky
        return self.cost_ratio / (1.0 + self.cost_ratio)


def decide(
    answers: Answers,
    questions: QuestionSet,
    thresholds: Thresholds,
    failure: Failure | None = None,
) -> Verdict:
    probability = _combine(answers, questions)
    # Noul carries no confidence field, so confidence is the decision's distance
    # from the coin flip. Benchmarked against a Score-based variant.
    confidence = min(abs(probability - 0.5) * 2.0, 1.0)
    label = Label.FLAKY if probability >= thresholds.flaky_threshold else Label.REAL
    escalated = confidence < thresholds.confidence or answers.truncated
    return Verdict(
        label=label,
        probability=probability,
        confidence=confidence,
        cause=_cause(failure),
        reason=_reason(answers, questions, label),
        escalated=escalated,
    )


def _contributions(answers: Answers, questions: QuestionSet) -> dict[str, float]:
    """Each answer's signed pull on the decision, centred on the coin flip."""
    return {
        question.name: _WEIGHTS.get(question.name, 0.0)
        * (answers.values.get(question.name, 0.5) - 0.5)
        for question in questions.questions
    }


def _combine(answers: Answers, questions: QuestionSet) -> float:
    contributions = _contributions(answers, questions)
    mass = sum(abs(_WEIGHTS.get(name, 0.0)) for name in contributions)
    if mass == 0.0:
        return 0.5
    return min(max(0.5 + sum(contributions.values()) / mass, 0.0), 1.0)


def _reason(answers: Answers, questions: QuestionSet, label: Label) -> str:
    """The answers that argued hardest for the verdict actually reached.

    Ranking by the pull toward the label, rather than by raw size, keeps the
    reason a defence of the decision instead of a list of loud signals that may
    have argued the other way.
    """
    direction = 1.0 if label is Label.FLAKY else -1.0
    moved = sorted(
        _contributions(answers, questions).items(),
        key=lambda item: item[1] * direction,
        reverse=True,
    )
    phrases = [
        _phrase(name, answers.values.get(name, 0.5))
        for name, pull in moved[:_REASONS_SHOWN]
        if pull != 0.0
    ]
    return "; ".join(phrases)


def _phrase(name: str, value: float) -> str:
    above, below = _PHRASES.get(name, (f"{name} present", f"no {name}"))
    return above if value > 0.5 else below


def _cause(failure: Failure | None) -> str:
    if failure is None:
        return ""
    return f"L{failure.line_no}: {failure.error}"
