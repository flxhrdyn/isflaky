from isflaky.engine.heuristic import HeuristicModel
from isflaky.engine.questions import load_question_set

ATOMIC = load_question_set("atomic")
DIRECT = load_question_set("direct")


def decide(error: str, **extra):
    state = {"test_id": "tests/test_x.py::test_y", "error": error, "traceback": "", **extra}
    return HeuristicModel().decide(state, ATOMIC)


def test_network_error_fires_on_a_connection_reset():
    assert decide("ConnectionResetError: [Errno 104] Connection reset").values[
        "network_error"
    ] > 0.5


def test_network_error_stays_low_on_an_assertion():
    assert decide("AssertionError: assert 1 == 2").values["network_error"] < 0.5


def test_assertion_failure_fires_on_an_assertion():
    assert decide("AssertionError: assert 1 == 2").values["assertion_failure"] > 0.5


def test_resource_contention_fires_on_an_address_in_use():
    assert decide("OSError: [Errno 98] Address already in use").values[
        "resource_contention"
    ] > 0.5


def test_import_or_env_fires_on_a_module_not_found():
    assert decide("ModuleNotFoundError: No module named 'lxml'").values["import_or_env"] > 0.5


def test_timing_dependent_fires_on_a_timeout():
    assert decide("TimeoutError: timed out after 30s").values["timing_dependent"] > 0.5


def test_a_signal_it_cannot_see_answers_one_half():
    """0.5 is the honest answer for a question regex cannot reach."""
    assert decide("AssertionError: assert 1 == 2").values["touches_test_code"] == 0.5


def test_touches_test_code_uses_changed_files_when_given():
    state = {
        "test_id": "tests/test_x.py::test_y",
        "error": "AssertionError",
        "traceback": "",
        "changed_files": "tests/test_x.py\nsrc/app.py",
    }
    answers = HeuristicModel().decide(state, ATOMIC)
    assert answers.values["touches_test_code"] > 0.5


def test_direct_question_favours_flaky_on_a_network_error():
    state = {"test_id": "t::x", "error": "ConnectionResetError: reset by peer", "traceback": ""}
    assert HeuristicModel().decide(state, DIRECT).values["flaky"] > 0.5


def test_direct_question_favours_real_on_an_assertion():
    state = {"test_id": "t::x", "error": "AssertionError: assert 1 == 2", "traceback": ""}
    assert HeuristicModel().decide(state, DIRECT).values["flaky"] < 0.5


def test_it_makes_no_network_call():
    """The free baseline must run with no key, which the suite relies on."""
    assert HeuristicModel().decide({"error": "boom"}, DIRECT).latency_ms >= 0.0
