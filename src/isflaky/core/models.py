from dataclasses import dataclass
from enum import Enum


class Label(str, Enum):
    FLAKY = "flaky"
    REAL = "real"


@dataclass(frozen=True)
class Failure:
    test_id: str
    error: str
    traceback: str
    log_context: str
    line_no: int


@dataclass(frozen=True)
class Provenance:
    repo: str
    run_id: int
    attempt: int
    head_sha: str
    url: str


@dataclass(frozen=True)
class LabeledFailure:
    failure: Failure
    label: Label
    provenance: Provenance
