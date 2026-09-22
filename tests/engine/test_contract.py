"""One contract suite, run against every DecisionModel implementation.

Spec section 14 requires this: baselines are free precisely because no
separate code path exists per model, so they must all satisfy one contract.
"""

import json
from pathlib import Path

import httpx2
import pytest

from isflaky.engine.heuristic import HeuristicModel
from isflaky.engine.jev import JevModel
from isflaky.engine.protocol import DecisionModel
from isflaky.engine.questions import load_question_set

FIXTURES = Path(__file__).parent.parent / "fixtures" / "api"


def replaying_jev() -> JevModel:
    """Jev backed by a recorded response, so the contract runs with no key."""
    recorded = json.loads((FIXTURES / "jev_atomic.json").read_text(encoding="utf-8"))

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked = json.loads(request.read())["questions"]
        answers = {
            name: recorded["body"]["answers"].get(name, {"type": "noul", "noul": 0.5})
            for name in asked
        }
        return httpx2.Response(200, json={**recorded["body"], "answers": answers})

    return JevModel(api_key="fake", transport=httpx2.MockTransport(handler))


MODELS: list[tuple[str, DecisionModel]] = [
    ("heuristic", HeuristicModel()),
    ("jev", replaying_jev()),
]

STATE = {
    "test_id": "tests/test_api.py::test_retry",
    "error": "ConnectionResetError: [Errno 104] Connection reset by peer",
    "traceback": "def test_retry():\n    resp = session.get(url)",
    "log_context": "",
    "changed_files": "",
}


def model_ids() -> list[str]:
    return [name for name, _ in MODELS]


def models() -> list[DecisionModel]:
    return [model for _, model in MODELS]


@pytest.mark.parametrize("model", models(), ids=model_ids())
@pytest.mark.parametrize("question_set", ["direct", "atomic"])
def test_answers_cover_exactly_the_asked_questions(model, question_set):
    questions = load_question_set(question_set)
    answers = model.decide(STATE, questions)
    assert set(answers.values) == {q.name for q in questions.questions}


@pytest.mark.parametrize("model", models(), ids=model_ids())
@pytest.mark.parametrize("question_set", ["direct", "atomic"])
def test_every_value_is_a_probability(model, question_set):
    questions = load_question_set(question_set)
    answers = model.decide(STATE, questions)
    assert all(0.0 <= value <= 1.0 for value in answers.values.values())


@pytest.mark.parametrize("model", models(), ids=model_ids())
def test_latency_is_reported(model):
    answers = model.decide(STATE, load_question_set("direct"))
    assert answers.latency_ms >= 0.0


@pytest.mark.parametrize("model", models(), ids=model_ids())
def test_an_empty_state_still_answers_every_question(model):
    """A log with no traceback must not crash the engine."""
    empty = {"test_id": "t::x", "error": "", "traceback": "", "log_context": ""}
    questions = load_question_set("atomic")
    answers = model.decide(empty, questions)
    assert set(answers.values) == {q.name for q in questions.questions}
