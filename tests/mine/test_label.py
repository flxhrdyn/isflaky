from isflaky.core.models import Label
from isflaky.mine.github import WorkflowRun
from isflaky.mine.label import label_attempt_pair

RUN = WorkflowRun(
    run_id=101,
    head_sha="aaa111",
    attempts=2,
    url="https://github.com/acme/proj/actions/runs/101",
    repo="acme/proj",
)

SUMMARY = "=========================== short test summary info ============================"


def log_with(*failed: str) -> str:
    lines = [SUMMARY]
    lines += [f"FAILED {test_id} - boom" for test_id in failed]
    lines.append("========================= 1 failed, 1 passed in 1.00s =========================")
    return "\n".join(lines)


def test_fail_then_pass_is_flaky():
    labeled = label_attempt_pair(RUN, 1, log_with("tests/a.py::test_x"), log_with())
    assert [(item.failure.test_id, item.label) for item in labeled] == [
        ("tests/a.py::test_x", Label.FLAKY)
    ]


def test_fail_then_fail_is_real():
    labeled = label_attempt_pair(
        RUN, 1, log_with("tests/a.py::test_x"), log_with("tests/a.py::test_x")
    )
    assert labeled[0].label is Label.REAL


def test_second_attempt_without_pytest_output_labels_nothing():
    assert label_attempt_pair(RUN, 1, log_with("tests/a.py::test_x"), "runner lost connection") == []


def test_first_attempt_without_failures_labels_nothing():
    assert label_attempt_pair(RUN, 1, log_with(), log_with()) == []


def test_provenance_records_the_first_attempt_of_the_pair():
    labeled = label_attempt_pair(RUN, 2, log_with("tests/a.py::test_x"), log_with())
    assert labeled[0].provenance.attempt == 2
    assert labeled[0].provenance.run_id == 101
    assert labeled[0].provenance.head_sha == "aaa111"


def test_each_failure_in_the_pair_is_labeled_independently():
    labeled = label_attempt_pair(
        RUN,
        1,
        log_with("tests/a.py::test_x", "tests/b.py::test_y"),
        log_with("tests/b.py::test_y"),
    )
    by_id = {item.failure.test_id: item.label for item in labeled}
    assert by_id == {"tests/a.py::test_x": Label.FLAKY, "tests/b.py::test_y": Label.REAL}
