from pathlib import Path

from isflaky.parse.pytest_log import parse_pytest_log

FIXTURES = Path(__file__).parent.parent / "fixtures" / "logs"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_extracts_every_failed_test_id():
    failures = parse_pytest_log(read("simple_failure.txt"))
    assert [f.test_id for f in failures] == [
        "tests/test_api.py::test_retry",
        "tests/test_auth.py::test_expiry",
    ]


def test_extracts_error_message_without_timestamp_prefix():
    failures = parse_pytest_log(read("simple_failure.txt"))
    assert failures[0].error == "ConnectionResetError: [Errno 104] Connection reset by peer"
    assert not failures[0].error.startswith("2026")


def test_attaches_traceback_when_failures_block_exists():
    failures = parse_pytest_log(read("simple_failure.txt"))
    assert "def test_retry():" in failures[0].traceback


def test_missing_failures_block_yields_empty_traceback():
    failures = parse_pytest_log(read("simple_failure.txt"))
    assert failures[1].traceback == ""


def test_records_the_summary_line_number():
    failures = parse_pytest_log(read("simple_failure.txt"))
    assert failures[0].line_no > 0


def test_log_without_failures_returns_empty_list():
    assert parse_pytest_log(read("no_failures.txt")) == []


def test_log_without_pytest_output_returns_empty_list():
    assert parse_pytest_log("Error: runner lost connection\n") == []


def test_strips_ansi_color_codes():
    raw = (
        "\x1b[36m\x1b[1m=========================== short test summary info ===========================\x1b[0m\n"
        "\x1b[31mFAILED\x1b[0m tests/test_ui.py::\x1b[1mtest_render\x1b[0m - AssertionError: assert False\n"
        "\x1b[31m= \x1b[31m1 failed\x1b[0m, \x1b[32m10 passed\x1b[0m in 1.20s =\n"
    )
    failures = parse_pytest_log(raw)
    assert len(failures) == 1
    assert failures[0].test_id == "tests/test_ui.py::test_render"
    assert failures[0].error == "AssertionError: assert False"


MATRIX_LOG = """\
=================================== FAILURES ===================================
_________________________ TestHttp.test_download_fails _________________________

self = <tests.test_http.TestHttp object at 0x7f00>

    def test_download_fails(self):
>       assert response.status == 200
E       AssertionError: assert 500 == 200

tests/test_http.py:41: AssertionError
----------------------------- Captured stdout call -----------------------------
connecting to 127.0.0.1:8080
------------------------------ Captured log call -------------------------------
WARNING  urllib3:connectionpool.py:812 Retrying after connection broken
=========================== short test summary info ============================
FAILED tests/test_http.py::TestHttp::test_download_fails - AssertionError: asse
============================ 1 failed in 3.21s =================================
=================================== FAILURES ===================================
____________________ test_retry[client-max-below-server] _______________________

    def test_retry(param):
>       raise ConnectionResetError(104, "Connection reset by peer")
E       ConnectionResetError: [Errno 104] Connection reset by peer

tests/test_retry.py:12: ConnectionResetError
=========================== short test summary info ============================
FAILED tests/test_retry.py::test_retry[client-max-below-server]
============================ 1 failed in 2.10s =================================
"""


def find(failures, test_id):
    return next(failure for failure in failures if failure.test_id == test_id)


def test_a_class_based_test_gets_its_traceback():
    """The block is titled TestHttp.test_x; the id says ::TestHttp::test_x."""
    failure = find(
        parse_pytest_log(MATRIX_LOG), "tests/test_http.py::TestHttp::test_download_fails"
    )
    assert "assert 500 == 200" in failure.traceback


def test_a_traceback_in_a_later_matrix_job_is_still_collected():
    """Matrix builds concatenate jobs, so one log holds many FAILURES blocks."""
    failure = find(
        parse_pytest_log(MATRIX_LOG),
        "tests/test_retry.py::test_retry[client-max-below-server]",
    )
    assert "ConnectionResetError" in failure.traceback


def test_captured_output_lands_in_log_context_not_the_traceback():
    failure = find(
        parse_pytest_log(MATRIX_LOG), "tests/test_http.py::TestHttp::test_download_fails"
    )
    assert "connecting to 127.0.0.1:8080" in failure.log_context
    assert "Retrying after connection broken" in failure.log_context
    assert "Captured stdout" not in failure.traceback


def test_a_failure_without_captured_output_has_empty_log_context():
    failure = find(
        parse_pytest_log(MATRIX_LOG),
        "tests/test_retry.py::test_retry[client-max-below-server]",
    )
    assert failure.log_context == ""


def test_the_error_line_survives_when_the_summary_omits_it():
    """Some runs print FAILED with no trailing reason; the traceback still has one."""
    failure = find(
        parse_pytest_log(MATRIX_LOG),
        "tests/test_retry.py::test_retry[client-max-below-server]",
    )
    assert failure.error == "ConnectionResetError: [Errno 104] Connection reset by peer"
