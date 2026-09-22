import time
from collections.abc import Mapping

import httpx2
import typesafe_sdk as ts

from isflaky.core.models import Answers
from isflaky.engine.questions import Kind, Question, QuestionSet
from isflaky.parse.collapse import estimate_tokens

_DEFAULT_MODEL = "jev-latest"
# Jev's documented state budget. Exceeding it is reported, never hidden.
_STATE_BUDGET_TOKENS = 32_000


class JevModel:
    """TypeSafe Jev behind the DecisionModel protocol.

    Every question runs in parallel over one state read, so asking eight costs
    tokens and almost no extra time compared with asking one.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        http_client = httpx2.Client(transport=transport) if transport is not None else None
        self._client = ts.TypeSafeClient(api_key=api_key, model=model, http_client=http_client)

    def decide(self, state: Mapping[str, str], questions: QuestionSet) -> Answers:
        started = time.perf_counter()
        response = self._client.system_one(dict(state), _as_sdk_questions(questions))
        latency_ms = (time.perf_counter() - started) * 1000

        by_name = {question.name: question for question in questions.questions}
        values = {
            name: _to_probability(answer, by_name[name])
            for name, answer in response.answers.items()
        }
        return Answers(
            values=values,
            latency_ms=latency_ms,
            truncated=_over_budget(state),
        )


def _as_sdk_questions(questions: QuestionSet) -> dict[str, ts.Noul | ts.Score]:
    return {question.name: _as_sdk_question(question) for question in questions.questions}


def _as_sdk_question(question: Question) -> ts.Noul | ts.Score:
    if question.kind is Kind.SCORE:
        return ts.Score(instructions=question.prompt, criteria=list(question.levels))
    return ts.Noul(instructions=question.prompt)


def _to_probability(answer: object, question: Question) -> float:
    """Collapse either answer type onto the protocol's 0-to-1 contract."""
    if question.kind is Kind.SCORE:
        top = max(len(question.levels) - 1, 1)
        return min(max(getattr(answer, "score", 0.0) / top, 0.0), 1.0)
    return float(getattr(answer, "noul", 0.0))


def _over_budget(state: Mapping[str, str]) -> bool:
    return estimate_tokens("".join(state.values())) > _STATE_BUDGET_TOKENS
