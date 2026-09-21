import re

from isflaky.core.models import Label, LabeledFailure, Provenance
from isflaky.mine.github import WorkflowRun
from isflaky.parse.pytest_log import parse_pytest_log

_RAN_TESTS = re.compile(r"short test summary info|\d+ (?:passed|failed)")


def label_attempt_pair(
    run: WorkflowRun,
    attempt: int,
    log_a: str,
    log_b: str,
) -> list[LabeledFailure]:
    """Label attempt A's failures using attempt B as rerun evidence.

    Returns nothing when attempt B did not run the tests. Calling that REAL would
    be an inference, and spec section 8.1 admits only proven labels.
    """
    failures = parse_pytest_log(log_a)
    if not failures or not _RAN_TESTS.search(log_b):
        return []

    failed_again = {failure.test_id for failure in parse_pytest_log(log_b)}
    provenance = Provenance(
        repo=run.repo,
        run_id=run.run_id,
        attempt=attempt,
        head_sha=run.head_sha,
        url=run.url,
    )
    return [
        LabeledFailure(
            failure=failure,
            label=Label.REAL if failure.test_id in failed_again else Label.FLAKY,
            provenance=provenance,
        )
        for failure in failures
    ]
