import json
from pathlib import Path

from isflaky.engine.groq import GroqModel
from isflaky.engine.questions import load_question_set

FIXTURE = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "api" / "groq_atomic.json").read_text(
        encoding="utf-8"
    )
)

STATE = {
    "test_id": "tests/test_api.py::test_retry",
    "error": "ConnectionResetError: [Errno 104] Connection reset by peer",
    "traceback": "",
}


class FakeCompletions:
    def __init__(self, content: str, capture: list | None = None) -> None:
        self._content = content
        self._capture = capture

    def create(self, **kwargs):
        if self._capture is not None:
            self._capture.append(kwargs)
        message = type("Message", (), {"content": self._content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class FakeGroq:
    def __init__(self, content: str, capture: list | None = None) -> None:
        completions = FakeCompletions(content, capture)
        self.chat = type("Chat", (), {"completions": completions})()


def model(content: str, capture: list | None = None) -> GroqModel:
    return GroqModel(api_key="fake", client=FakeGroq(content, capture))


def test_parses_a_probability_per_question():
    answers = model(FIXTURE["content"]).decide(STATE, load_question_set("atomic"))
    assert answers.values["network_error"] == 0.95
    assert answers.values["assertion_failure"] == 0.0


def test_asks_every_question_in_one_call():
    capture: list = []
    questions = load_question_set("atomic")
    model(FIXTURE["content"], capture).decide(STATE, questions)
    assert len(capture) == 1
    prompt = capture[0]["messages"][-1]["content"]
    assert all(question.name in prompt for question in questions.questions)


def test_a_missing_question_falls_back_to_one_half():
    """One bad answer must not abort a benchmark run of hundreds."""
    answers = model('{"network_error": 0.9}').decide(STATE, load_question_set("atomic"))
    assert answers.values["network_error"] == 0.9
    assert answers.values["assertion_failure"] == 0.5


def test_unparseable_reply_answers_one_half_throughout():
    answers = model("I cannot help with that.").decide(STATE, load_question_set("atomic"))
    assert set(answers.values.values()) == {0.5}


def test_a_non_numeric_value_falls_back_to_one_half():
    answers = model('{"flaky": "very likely"}').decide(STATE, load_question_set("direct"))
    assert answers.values["flaky"] == 0.5


def test_out_of_range_values_are_clamped():
    answers = model('{"flaky": 7}').decide(STATE, load_question_set("direct"))
    assert answers.values["flaky"] == 1.0


def test_answers_cover_exactly_the_asked_questions():
    questions = load_question_set("atomic")
    answers = model(FIXTURE["content"]).decide(STATE, questions)
    assert set(answers.values) == {question.name for question in questions.questions}


def test_reports_latency():
    answers = model(FIXTURE["content"]).decide(STATE, load_question_set("direct"))
    assert answers.latency_ms >= 0.0
