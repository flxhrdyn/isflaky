import dataclasses

import pytest

from isflaky.core.models import Failure, Label, LabeledFailure, Provenance


def test_failure_is_frozen():
    failure = Failure(
        test_id="tests/test_api.py::test_retry",
        error="ConnectionResetError: [Errno 104]",
        traceback="",
        log_context="",
        line_no=2841,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        failure.test_id = "other"


def test_label_values_are_stable_strings():
    assert Label.FLAKY.value == "flaky"
    assert Label.REAL.value == "real"


def test_labeled_failure_carries_provenance():
    labeled = LabeledFailure(
        failure=Failure("t::a", "boom", "", "", 1),
        label=Label.FLAKY,
        provenance=Provenance(
            repo="psf/requests",
            run_id=123,
            attempt=1,
            head_sha="abc123",
            url="https://github.com/psf/requests/actions/runs/123",
        ),
    )
    assert labeled.provenance.repo == "psf/requests"
    assert labeled.label is Label.FLAKY
