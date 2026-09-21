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
