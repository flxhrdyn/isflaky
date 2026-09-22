from collections.abc import Mapping
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


@dataclass(frozen=True)
class Answers:
    values: Mapping[str, float]
    latency_ms: float
    truncated: bool


@dataclass(frozen=True)
class Verdict:
    label: Label
    probability: float
    confidence: float
    cause: str
    reason: str
    # Separate from label: an uncertain FLAKY must never read as safe to rerun.
    escalated: bool
