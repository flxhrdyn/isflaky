from isflaky.core.models import Failure
from isflaky.parse.collapse import collapse, estimate_tokens


def make_failure(traceback: str = "", log_context: str = "") -> Failure:
    return Failure(
        test_id="tests/test_api.py::test_retry",
        error="ConnectionResetError: [Errno 104]",
        traceback=traceback,
        log_context=log_context,
        line_no=2841,
    )


def test_state_has_the_documented_keys():
    state = collapse(make_failure())
    assert set(state) == {"test_id", "error", "traceback", "log_context", "changed_files"}


def test_all_values_are_strings():
    state = collapse(make_failure(traceback="x" * 100))
    assert all(isinstance(value, str) for value in state.values())


def test_short_input_is_untouched():
    failure = make_failure(traceback="line one\nline two")
    assert collapse(failure)["traceback"] == "line one\nline two"


def test_oversized_input_is_brought_within_budget():
    failure = make_failure(traceback="x" * 500_000, log_context="y" * 500_000)
    state = collapse(failure, budget_tokens=1_000)
    assert estimate_tokens("".join(state.values())) <= 1_000


def test_error_survives_collapse_even_at_a_tiny_budget():
    failure = make_failure(traceback="x" * 500_000)
    state = collapse(failure, budget_tokens=50)
    assert state["error"] == "ConnectionResetError: [Errno 104]"


def test_repeated_lines_are_deduplicated():
    failure = make_failure(traceback="\n".join(["same line"] * 200))
    assert collapse(failure)["traceback"].count("same line") < 200


def test_truncation_is_marked_not_silent():
    failure = make_failure(traceback="x" * 500_000)
    state = collapse(failure, budget_tokens=100)
    assert "truncated" in state["traceback"]
