import json
from pathlib import Path

import httpx2
import pytest
import typesafe_sdk as ts

from isflaky.engine.jev import JevModel
from isflaky.engine.questions import load_question_set

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "api" / "jev_atomic.json").read_text(
        encoding="utf-8"
    )
)

STATE = {
    "test_id": "tests/test_api.py::test_retry",
    "error": "ConnectionResetError: [Errno 104] Connection reset by peer",
    "traceback": "",
    "log_context": "",
    "changed_files": "",
}


def recorded_client(capture: list | None = None) -> JevModel:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if capture is not None:
            capture.append(json.loads(request.read()))
        return httpx2.Response(FIXTURE["status"], json=FIXTURE["body"])

    return JevModel(api_key="fake", transport=httpx2.MockTransport(handler))


def test_maps_noul_answers_to_probabilities():
    answers = recorded_client().decide(STATE, load_question_set("atomic"))
    assert answers.values["network_error"] == 0.86
    assert answers.values["assertion_failure"] == 0.04


def test_normalises_score_answers_into_zero_to_one():
    """The contract is a probability, but Score returns a rubric level."""
    answers = recorded_client().decide(STATE, load_question_set("atomic"))
    assert 0.0 <= answers.values["determinism"] <= 1.0


def test_sends_every_question_in_one_call():
    capture: list = []
    questions = load_question_set("atomic")
    recorded_client(capture).decide(STATE, questions)
    assert len(capture) == 1
    assert set(capture[0]["questions"]) == {q.name for q in questions.questions}


def test_sends_the_collapsed_state_as_given():
    capture: list = []
    recorded_client(capture).decide(STATE, load_question_set("atomic"))
    assert capture[0]["state"] == STATE


def test_reports_latency():
    answers = recorded_client().decide(STATE, load_question_set("atomic"))
    assert answers.latency_ms > 0.0


def test_state_over_budget_is_marked_truncated():
    """Spec section 13: never silently exceed the state budget."""
    oversized = {**STATE, "traceback": "x" * 200_000}
    answers = recorded_client().decide(oversized, load_question_set("atomic"))
    assert answers.truncated is True


def test_state_within_budget_is_not_marked_truncated():
    answers = recorded_client().decide(STATE, load_question_set("atomic"))
    assert answers.truncated is False


def test_auth_error_is_not_swallowed():
    """Spec section 13: no silent fallback when the model is unavailable."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"error": {"message": "bad key"}})

    model = JevModel(api_key="fake", transport=httpx2.MockTransport(handler))
    with pytest.raises(ts.TypeSafeAuthenticationError):
        model.decide(STATE, load_question_set("direct"))
