import json
import time
from collections.abc import Mapping
from typing import Any

from isflaky.core.models import Answers
from isflaky.engine.questions import QuestionSet

# Spec section 12 names llama-3.1-8b-instant and llama-3.3-70b-versatile, but
# Groq has since retired both. These are the current equivalents: a small fast
# model as the default baseline, and a larger one as the stronger comparison.
_DEFAULT_MODEL = "qwen/qwen3.8-27b"
STRONGER_MODEL = "openai/gpt-oss-120b"

_UNKNOWN = 0.5
_SYSTEM = (
    "Answer each question with a probability from 0.0 to 1.0. Reply with a JSON "
    "object mapping each question name to its number. No other keys."
)


class GroqModel:
    """Small-LLM baseline behind the same protocol as Jev.

    Anything unparseable answers 0.5 rather than raising: a single refusal must
    not abort a benchmark run of hundreds of cases.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from groq import Groq

            client = Groq(api_key=api_key)
        self._client = client
        self._model = model

    def decide(self, state: Mapping[str, str], questions: QuestionSet) -> Answers:
        started = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": _prompt(state, questions)},
            ],
            temperature=0,
            max_tokens=500,
        )
        latency_ms = (time.perf_counter() - started) * 1000

        replied = _parse(response.choices[0].message.content)
        values = {
            question.name: _probability(replied.get(question.name))
            for question in questions.questions
        }
        return Answers(values=values, latency_ms=latency_ms, truncated=False)


def _prompt(state: Mapping[str, str], questions: QuestionSet) -> str:
    asked = "\n".join(f"- {q.name}: {q.prompt.strip()}" for q in questions.questions)
    return f"State:\n{json.dumps(dict(state))}\n\nQuestions:\n{asked}"


def _parse(content: str | None) -> dict[str, object]:
    try:
        replied = json.loads(content or "")
    except json.JSONDecodeError:
        return {}
    return replied if isinstance(replied, dict) else {}


def _probability(raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return _UNKNOWN
    return min(max(float(raw), 0.0), 1.0)
