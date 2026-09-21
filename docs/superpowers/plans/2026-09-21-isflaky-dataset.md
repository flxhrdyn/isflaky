# isflaky Dataset Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a labeled dataset of real pytest CI failures whose flaky/real labels are proven by rerun evidence, together with the parser and domain types that the rest of `isflaky` builds on.

**Architecture:** A pure-domain `core` package holds frozen dataclasses with no I/O. A `parse` package turns raw pytest logs into `Failure` objects and collapses them into a bounded `state` payload. A `mine` package walks the GitHub Actions API, fetches consecutive attempts of the same failed run, parses both with the same production parser, and pairs failures by test id to derive labels. Nothing in this plan calls TypeSafe Jev; the decision engine arrives in Plan 2.

**Tech Stack:** Python 3.10+, uv, hatchling, pytest, ruff, mypy, httpx.

**Spec:** `docs/superpowers/specs/2026-09-21-isflaky-design.md`

## Global Constraints

- Python 3.10 or later. The TypeSafe SDK requires 3.10+; do not use syntax below that floor.
- The entire test suite runs offline with no API key and no network access. Every GitHub interaction in tests uses recorded fixtures.
- `parse/` never imports anything from `mine/`, and never touches the network.
- `mine/` is never imported by `cli/` or `engine/`. Its dependencies live behind the `[mine]` extra.
- The `state` budget is 32,000 tokens, approximated as 4 characters per token. This approximation is documented in code, not silently assumed.
- Labels come only from rerun evidence at an identical commit SHA. A failure with no rerun is unlabeled and dropped. Never infer a `real` label from the absence of a rerun.
- License MIT. Conventional Commits. No agent name as co-author.
- Keep comments minimal and prefer good names. Comment only what a junior developer could not infer, favouring why over what.

---

### Task 1: Spike - measure the supply of rerun-proven labeled pairs

This task is a **throwaway spike**, not production code. Its output is an answer and a go/no-go decision. Delete the script afterwards; do not build on it.

Spec section 18 gates every later task on this result.

**Files:**
- Create: `spike/supply_probe.py` (throwaway, deleted in Step 6)

**Interfaces:**
- Consumes: nothing.
- Produces: a decision only. No later task imports this code.

- [ ] **Step 1: Confirm a GitHub token is available**

Run: `echo ${GITHUB_TOKEN:+present}`
Expected: `present`

If empty, stop and ask the user for a token with `public_repo` scope. Without it the API allows 60 requests per hour, which is not enough to probe run history.

- [ ] **Step 2: Write the probe script**

```python
"""THROWAWAY SPIKE - deleted after the supply question is answered."""
import os
import httpx

REPOS = [
    "pandas-dev/pandas",
    "psf/requests",
    "encode/httpx",
    "pallets/flask",
    "scikit-learn/scikit-learn",
    "aio-libs/aiohttp",
    "pydantic/pydantic",
    "tiangolo/fastapi",
]

HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
}


def probe(repo: str) -> tuple[int, int]:
    """Return (failed runs seen, failed runs that were rerun at least once)."""
    url = f"https://api.github.com/repos/{repo}/actions/runs"
    params = {"status": "failure", "per_page": 100}
    r = httpx.get(url, headers=HEADERS, params=params, timeout=30.0)
    r.raise_for_status()
    runs = r.json()["workflow_runs"]
    rerun = [run for run in runs if run["run_attempt"] > 1]
    return len(runs), len(rerun)


if __name__ == "__main__":
    total_runs = total_rerun = 0
    for repo in REPOS:
        try:
            seen, rerun = probe(repo)
        except httpx.HTTPStatusError as exc:
            print(f"{repo:35} SKIP {exc.response.status_code}")
            continue
        total_runs += seen
        total_rerun += rerun
        print(f"{repo:35} {seen:4} failed runs, {rerun:3} with reruns")
    print(f"\nTOTAL {total_runs} failed runs, {total_rerun} rerun")
```

- [ ] **Step 3: Run the probe**

Run: `uv run --with httpx python spike/supply_probe.py`
Expected: a per-repository table and a total. Record the totals.

- [ ] **Step 4: Inspect one real log**

Pick one run id from a repository that showed reruns, then download and read its log so the parser in Task 3 is written against reality rather than assumption.

```bash
curl -sL -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/<owner>/<repo>/actions/runs/<run_id>/attempts/1/logs" \
  -o /tmp/attempt1.zip
unzip -o /tmp/attempt1.zip -d /tmp/attempt1
grep -rl "short test summary info" /tmp/attempt1 | head -3
```

Expected: at least one file containing a pytest summary section. Read it and note the exact shape of the `FAILED` lines and the `FAILURES` block delimiters.

If no pytest output appears in any probed repository, the framework assumption is wrong. Stop and report before continuing.

- [ ] **Step 5: Apply the gate from spec section 18**

Estimate labeled pairs as (runs with reruns) multiplied by the average number of failing tests per run observed in Step 4.

- 1,000 or more: proceed to Task 2 with the full plan.
- 300 to 1,000: proceed, but widen `REPOS` substantially and soften the claims in the README.
- Fewer than 300: **stop**. Report the number and revisit the labeling strategy with the user before writing any further code.

Report the estimate to the user and wait for acknowledgement before Task 2.

- [ ] **Step 6: Delete the spike**

```bash
rm -rf spike/
```

No commit. The spike produced an answer, not an artifact.

---

### Task 2: Project scaffolding and core domain types

**Files:**
- Create: `pyproject.toml`
- Create: `src/isflaky/__init__.py`
- Create: `src/isflaky/core/__init__.py`
- Create: `src/isflaky/core/models.py`
- Create: `tests/core/test_models.py`
- Create: `LICENSE`

**Interfaces:**
- Consumes: nothing.
- Produces: `Failure(test_id: str, error: str, traceback: str, log_context: str, line_no: int)`, `Label` enum with members `FLAKY` and `REAL` whose values are `"flaky"` and `"real"`, `Provenance(repo: str, run_id: int, attempt: int, head_sha: str, url: str)`, and `LabeledFailure(failure: Failure, label: Label, provenance: Provenance)`. All are frozen dataclasses except `Label`, which is a `str` enum. Every later task in every plan imports these.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "isflaky"
version = "0.1.0"
description = "Flaky test triage for CI, powered by TypeSafe Jev. Ships with a reproducible benchmark on real CI failures."
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
dependencies = []

[project.optional-dependencies]
mine = ["httpx>=0.27"]

[dependency-groups]
dev = ["pytest>=8.0", "ruff>=0.6", "mypy>=1.11"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/isflaky"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100

[tool.mypy]
python_version = "3.10"
strict = true
```

- [ ] **Step 2: Write the failing test**

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'isflaky.core'`

- [ ] **Step 4: Write minimal implementation**

`src/isflaky/core/models.py`:

```python
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
```

`src/isflaky/__init__.py` and `src/isflaky/core/__init__.py` are empty files.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/test_models.py -v`
Expected: 3 passed

- [ ] **Step 6: Add the MIT license file**

Write a standard MIT `LICENSE` with copyright line `Copyright (c) 2026 Felix`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml LICENSE src/isflaky tests/core
git commit -m "feat(core): add domain types for failures, labels, and provenance"
```

---

### Task 3: pytest log parser

The parser reads the authoritative list of failed tests from pytest's `short test summary info` section, then attaches the traceback from the matching `FAILURES` block when one is present. The summary section is used as the source of truth because it is a single stable line per failure, whereas `FAILURES` block delimiters vary with terminal width.

**Files:**
- Create: `src/isflaky/parse/__init__.py`
- Create: `src/isflaky/parse/pytest_log.py`
- Create: `tests/parse/test_pytest_log.py`
- Create: `tests/fixtures/logs/simple_failure.txt`
- Create: `tests/fixtures/logs/no_failures.txt`

**Interfaces:**
- Consumes: `isflaky.core.models.Failure`.
- Produces: `parse_pytest_log(text: str) -> list[Failure]`. Returns an empty list when the log contains no pytest summary section. Task 4 and Task 6 both call it.

- [ ] **Step 1: Create the log fixtures**

`tests/fixtures/logs/simple_failure.txt`:

```
2026-09-20T10:14:02.1Z ============================= test session starts ==============================
2026-09-20T10:14:02.2Z collected 42 items
2026-09-20T10:14:09.4Z
2026-09-20T10:14:09.4Z =================================== FAILURES ===================================
2026-09-20T10:14:09.4Z _________________________________ test_retry __________________________________
2026-09-20T10:14:09.5Z
2026-09-20T10:14:09.5Z     def test_retry():
2026-09-20T10:14:09.5Z >       resp = client.get("/health")
2026-09-20T10:14:09.5Z E       ConnectionResetError: [Errno 104] Connection reset by peer
2026-09-20T10:14:09.6Z
2026-09-20T10:14:09.6Z tests/test_api.py:31: ConnectionResetError
2026-09-20T10:14:09.7Z =========================== short test summary info ============================
2026-09-20T10:14:09.7Z FAILED tests/test_api.py::test_retry - ConnectionResetError: [Errno 104] Connection reset by peer
2026-09-20T10:14:09.7Z FAILED tests/test_auth.py::test_expiry - AssertionError: assert 1758412800 < 1758412800
2026-09-20T10:14:09.8Z ========================= 2 failed, 40 passed in 7.31s =========================
```

`tests/fixtures/logs/no_failures.txt`:

```
2026-09-20T10:11:00.1Z ============================= test session starts ==============================
2026-09-20T10:11:00.2Z collected 42 items
2026-09-20T10:11:06.9Z ============================== 42 passed in 6.70s ==============================
```

Note the Actions timestamp prefix on every line. Real downloaded logs carry it, so the parser must tolerate it.

- [ ] **Step 2: Write the failing test**

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/parse/test_pytest_log.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'isflaky.parse'`

- [ ] **Step 4: Write minimal implementation**

```python
import re

from isflaky.core.models import Failure

# GitHub Actions prefixes every log line with an ISO-8601 timestamp.
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")
_SUMMARY_HEADER = re.compile(r"=+ short test summary info =+")
_FAILED_LINE = re.compile(r"^FAILED (?P<test_id>\S+)(?: - (?P<error>.*))?$")
_FAILURES_HEADER = re.compile(r"=+ FAILURES =+")
_BLOCK_DELIMITER = re.compile(r"^_+ (?P<name>\S+) _+$")
_SECTION_END = re.compile(r"^=+ .* =+$")


def _strip(line: str) -> str:
    return _TIMESTAMP.sub("", line).rstrip()


def parse_pytest_log(text: str) -> list[Failure]:
    lines = [_strip(line) for line in text.splitlines()]

    summary_start = _find(lines, _SUMMARY_HEADER)
    if summary_start is None:
        return []

    tracebacks = _collect_tracebacks(lines)

    failures = []
    for offset, line in enumerate(lines[summary_start + 1 :], start=summary_start + 1):
        if _SECTION_END.match(line):
            break
        match = _FAILED_LINE.match(line)
        if match is None:
            continue
        test_id = match.group("test_id")
        failures.append(
            Failure(
                test_id=test_id,
                error=match.group("error") or "",
                traceback=tracebacks.get(_short_name(test_id), ""),
                log_context="",
                line_no=offset + 1,
            )
        )
    return failures


def _find(lines: list[str], pattern: re.Pattern[str]) -> int | None:
    for index, line in enumerate(lines):
        if pattern.search(line):
            return index
    return None


def _short_name(test_id: str) -> str:
    return test_id.rsplit("::", 1)[-1]


def _collect_tracebacks(lines: list[str]) -> dict[str, str]:
    start = _find(lines, _FAILURES_HEADER)
    if start is None:
        return {}

    blocks: dict[str, str] = {}
    name: str | None = None
    body: list[str] = []
    for line in lines[start + 1 :]:
        delimiter = _BLOCK_DELIMITER.match(line)
        if delimiter:
            if name is not None:
                blocks[name] = "\n".join(body).strip()
            name = delimiter.group("name")
            body = []
            continue
        if _SECTION_END.match(line):
            break
        body.append(line)
    if name is not None:
        blocks[name] = "\n".join(body).strip()
    return blocks
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/parse/test_pytest_log.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add src/isflaky/parse tests/parse tests/fixtures
git commit -m "feat(parse): extract failures from pytest logs via summary section"
```

---

### Task 4: Context collapse under the state budget

**Files:**
- Create: `src/isflaky/parse/collapse.py`
- Create: `tests/parse/test_collapse.py`

**Interfaces:**
- Consumes: `isflaky.core.models.Failure`.
- Produces: `collapse(failure: Failure, changed_files: str = "", budget_tokens: int = 32_000) -> dict[str, str]` returning keys `test_id`, `error`, `traceback`, `log_context`, `changed_files`. Also exports `estimate_tokens(text: str) -> int`. Plan 2's engine calls `collapse` to build the `state` payload.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/parse/test_collapse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'isflaky.parse.collapse'`

- [ ] **Step 3: Write minimal implementation**

```python
from isflaky.core.models import Failure

# Jev bills and bounds by tokens, but exposes no tokenizer. Four characters per
# token is the usual English approximation and is deliberately conservative here:
# overestimating tokens truncates early, which is safe, while underestimating
# would push state past the API's 32k limit and fail the call.
_CHARS_PER_TOKEN = 4
_MARKER = "\n... truncated ...\n"


def estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


def collapse(
    failure: Failure,
    changed_files: str = "",
    budget_tokens: int = 32_000,
) -> dict[str, str]:
    """Build a Jev state payload guaranteed to fit the budget.

    test_id and error are never truncated: they carry the decision's subject and
    its single most informative line, so losing them would make the state useless.
    """
    fixed = {"test_id": failure.test_id, "error": failure.error}
    fixed_tokens = estimate_tokens("".join(fixed.values()))
    remaining = max(budget_tokens - fixed_tokens, 0)

    flexible = {
        "traceback": _dedupe(failure.traceback),
        "log_context": _dedupe(failure.log_context),
        "changed_files": changed_files,
    }
    share = remaining // max(len(flexible), 1)

    return {**fixed, **{key: _fit(value, share) for key, value in flexible.items()}}


def _dedupe(text: str) -> str:
    seen: set[str] = set()
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and stripped in seen:
            continue
        seen.add(stripped)
        kept.append(line)
    return "\n".join(kept)


def _fit(text: str, budget_tokens: int) -> str:
    limit = budget_tokens * _CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    if limit <= len(_MARKER):
        return _MARKER.strip()
    head = (limit - len(_MARKER)) // 2
    tail = limit - len(_MARKER) - head
    return text[:head] + _MARKER + text[len(text) - tail :]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/parse/test_collapse.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/isflaky/parse/collapse.py tests/parse/test_collapse.py
git commit -m "feat(parse): collapse failures into a bounded state payload"
```

---

### Task 5: GitHub Actions client

**Files:**
- Create: `src/isflaky/mine/__init__.py`
- Create: `src/isflaky/mine/github.py`
- Create: `tests/mine/test_github.py`
- Create: `tests/fixtures/api/runs_page.json`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `WorkflowRun(run_id: int, head_sha: str, attempts: int, url: str, repo: str)` as a frozen dataclass, `GitHubClient(token: str, transport=None)` with methods `failed_runs_with_reruns(repo: str) -> list[WorkflowRun]` and `attempt_log(repo: str, run_id: int, attempt: int) -> str`. Task 6 consumes both.

Reruns of a workflow run keep the same `run_id` and the same `head_sha` while incrementing `run_attempt`. Pairing inside one run therefore satisfies the identical-SHA requirement of spec section 8.1 automatically, with no SHA comparison needed.

- [ ] **Step 1: Create the API fixture**

`tests/fixtures/api/runs_page.json`:

```json
{
  "workflow_runs": [
    {
      "id": 101,
      "head_sha": "aaa111",
      "run_attempt": 2,
      "html_url": "https://github.com/acme/proj/actions/runs/101"
    },
    {
      "id": 102,
      "head_sha": "bbb222",
      "run_attempt": 1,
      "html_url": "https://github.com/acme/proj/actions/runs/102"
    },
    {
      "id": 103,
      "head_sha": "ccc333",
      "run_attempt": 3,
      "html_url": "https://github.com/acme/proj/actions/runs/103"
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from isflaky.mine.github import GitHubClient

FIXTURES = Path(__file__).parent.parent / "fixtures" / "api"


def make_log_zip(content: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("0_build.txt", content)
    return buffer.getvalue()


def make_client(handler) -> GitHubClient:
    return GitHubClient(token="fake", transport=httpx.MockTransport(handler))


def test_keeps_only_runs_that_were_rerun():
    payload = json.loads((FIXTURES / "runs_page.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    runs = make_client(handler).failed_runs_with_reruns("acme/proj")
    assert [run.run_id for run in runs] == [101, 103]


def test_run_carries_sha_attempts_and_repo():
    payload = json.loads((FIXTURES / "runs_page.json").read_text())
    runs = make_client(lambda request: httpx.Response(200, json=payload)).failed_runs_with_reruns(
        "acme/proj"
    )
    assert runs[0].head_sha == "aaa111"
    assert runs[0].attempts == 2
    assert runs[0].repo == "acme/proj"


def test_attempt_log_unzips_and_concatenates_members():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=make_log_zip("FAILED tests/a.py::test_x - boom"))

    text = make_client(handler).attempt_log("acme/proj", 101, 1)
    assert "FAILED tests/a.py::test_x" in text


def test_expired_log_returns_empty_string():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(410)

    assert make_client(handler).attempt_log("acme/proj", 101, 1) == ""


def test_auth_error_is_not_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    with pytest.raises(httpx.HTTPStatusError):
        make_client(handler).failed_runs_with_reruns("acme/proj")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run --extra mine pytest tests/mine/test_github.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'isflaky.mine'`

- [ ] **Step 4: Write minimal implementation**

```python
import io
import zipfile
from dataclasses import dataclass

import httpx

_API = "https://api.github.com"
# Actions log retention defaults to 90 days; expired logs answer 410.
_EXPIRED = 410


@dataclass(frozen=True)
class WorkflowRun:
    run_id: int
    head_sha: str
    attempts: int
    url: str
    repo: str


class GitHubClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url=_API,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
            },
            transport=transport,
            timeout=60.0,
            follow_redirects=True,
        )

    def failed_runs_with_reruns(self, repo: str) -> list[WorkflowRun]:
        response = self._client.get(
            f"/repos/{repo}/actions/runs",
            params={"status": "failure", "per_page": 100},
        )
        response.raise_for_status()
        return [
            WorkflowRun(
                run_id=run["id"],
                head_sha=run["head_sha"],
                attempts=run["run_attempt"],
                url=run["html_url"],
                repo=repo,
            )
            for run in response.json()["workflow_runs"]
            if run["run_attempt"] > 1
        ]

    def attempt_log(self, repo: str, run_id: int, attempt: int) -> str:
        response = self._client.get(
            f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/logs"
        )
        if response.status_code == _EXPIRED:
            return ""
        response.raise_for_status()
        return _read_zip(response.content)


def _read_zip(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [
            archive.read(name).decode("utf-8", errors="replace")
            for name in archive.namelist()
            if name.endswith(".txt")
        ]
    return "\n".join(members)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --extra mine pytest tests/mine/test_github.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/isflaky/mine tests/mine tests/fixtures/api
git commit -m "feat(mine): add GitHub Actions client for reran failed runs"
```

---

### Task 6: Attempt pairing and labeling

This task implements spec section 8.1 exactly. Read that section before starting.

**Files:**
- Create: `src/isflaky/mine/label.py`
- Create: `tests/mine/test_label.py`

**Interfaces:**
- Consumes: `parse_pytest_log` from Task 3, `WorkflowRun` from Task 5, and `Failure`, `Label`, `Provenance`, `LabeledFailure` from Task 2.
- Produces: `label_attempt_pair(run: WorkflowRun, attempt: int, log_a: str, log_b: str) -> list[LabeledFailure]`. Task 7 calls it.

Rules, all derived from spec section 8.1:

- A test that failed in attempt A and is absent from attempt B's failures is `FLAKY`, but only if attempt B actually ran tests.
- A test that failed in both attempts is `REAL`.
- If attempt B's log contains no pytest summary section, the job did not rerun the tests. Nothing is labeled. Returning `REAL` here would be an inference, which section 8.1 forbids.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra mine pytest tests/mine/test_label.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'isflaky.mine.label'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra mine pytest tests/mine/test_label.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/isflaky/mine/label.py tests/mine/test_label.py
git commit -m "feat(mine): derive flaky and real labels from rerun evidence"
```

---

### Task 7: Dataset writer and mining entry point

**Files:**
- Create: `src/isflaky/mine/dataset.py`
- Create: `src/isflaky/mine/__main__.py`
- Create: `tests/mine/test_dataset.py`
- Modify: `pyproject.toml` (add the `isflaky-mine` script entry point)

**Interfaces:**
- Consumes: everything from Tasks 2 through 6.
- Produces: `write_dataset(records: Iterable[LabeledFailure], path: Path) -> int` returning the count written, `read_dataset(path: Path) -> list[LabeledFailure]`, and `mine_repo(client: GitHubClient, repo: str) -> Iterator[LabeledFailure]`. Plan 2's benchmark calls `read_dataset`.

Records are written as JSONL holding the derived state plus full provenance, never raw logs, per spec section 8.4.

- [ ] **Step 1: Write the failing test**

```python
from isflaky.core.models import Failure, Label, LabeledFailure, Provenance
from isflaky.mine.dataset import read_dataset, write_dataset


def make_record(test_id: str, label: Label) -> LabeledFailure:
    return LabeledFailure(
        failure=Failure(test_id, "boom", "trace", "context", 12),
        label=label,
        provenance=Provenance("acme/proj", 101, 1, "aaa111", "https://example.test/101"),
    )


def test_roundtrip_preserves_every_field(tmp_path):
    path = tmp_path / "dataset.jsonl"
    written = write_dataset([make_record("tests/a.py::test_x", Label.FLAKY)], path)
    assert written == 1

    restored = read_dataset(path)
    assert restored[0].failure.test_id == "tests/a.py::test_x"
    assert restored[0].failure.traceback == "trace"
    assert restored[0].label is Label.FLAKY
    assert restored[0].provenance.head_sha == "aaa111"


def test_one_json_object_per_line(tmp_path):
    path = tmp_path / "dataset.jsonl"
    write_dataset(
        [make_record("tests/a.py::test_x", Label.FLAKY), make_record("tests/b.py::test_y", Label.REAL)],
        path,
    )
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


def test_write_is_resumable_by_appending(tmp_path):
    path = tmp_path / "dataset.jsonl"
    write_dataset([make_record("tests/a.py::test_x", Label.FLAKY)], path)
    write_dataset([make_record("tests/b.py::test_y", Label.REAL)], path)
    assert len(read_dataset(path)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra mine pytest tests/mine/test_dataset.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'isflaky.mine.dataset'`

- [ ] **Step 3: Write minimal implementation**

`src/isflaky/mine/dataset.py`:

```python
import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from pathlib import Path

from isflaky.core.models import Failure, Label, LabeledFailure, Provenance
from isflaky.mine.github import GitHubClient
from isflaky.mine.label import label_attempt_pair


def write_dataset(records: Iterable[LabeledFailure], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(
                json.dumps(
                    {
                        "failure": asdict(record.failure),
                        "label": record.label.value,
                        "provenance": asdict(record.provenance),
                    }
                )
                + "\n"
            )
            count += 1
    return count


def read_dataset(path: Path) -> list[LabeledFailure]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            records.append(
                LabeledFailure(
                    failure=Failure(**raw["failure"]),
                    label=Label(raw["label"]),
                    provenance=Provenance(**raw["provenance"]),
                )
            )
    return records


def mine_repo(client: GitHubClient, repo: str) -> Iterator[LabeledFailure]:
    for run in client.failed_runs_with_reruns(repo):
        for attempt in range(1, run.attempts):
            log_a = client.attempt_log(repo, run.run_id, attempt)
            log_b = client.attempt_log(repo, run.run_id, attempt + 1)
            if not log_a or not log_b:
                continue
            yield from label_attempt_pair(run, attempt, log_a, log_b)
```

`src/isflaky/mine/__main__.py`:

```python
import argparse
import os
import sys
from pathlib import Path

from isflaky.mine.dataset import mine_repo, write_dataset
from isflaky.mine.github import GitHubClient


def main() -> int:
    parser = argparse.ArgumentParser(prog="isflaky-mine")
    parser.add_argument("repos", nargs="+", help="owner/name")
    parser.add_argument("--out", type=Path, default=Path("data/dataset.jsonl"))
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("GITHUB_TOKEN is not set", file=sys.stderr)
        return 2

    client = GitHubClient(token=token)
    total = 0
    for repo in args.repos:
        written = write_dataset(mine_repo(client, repo), args.out)
        total += written
        print(f"{repo}: {written} labeled failures")
    print(f"total: {total} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add the script entry point**

In `pyproject.toml`, after the `[project.optional-dependencies]` table:

```toml
[project.scripts]
isflaky-mine = "isflaky.mine.__main__:main"
```

- [ ] **Step 5: Run the full test suite offline**

Run: `uv run --extra mine pytest -v`
Expected: all tests pass, with no network access and no API key set.

- [ ] **Step 6: Run ruff and mypy**

Run: `uv run ruff check src tests && uv run mypy src`
Expected: no errors. Fix any that appear before committing.

- [ ] **Step 7: Commit**

```bash
git add src/isflaky/mine/dataset.py src/isflaky/mine/__main__.py tests/mine/test_dataset.py pyproject.toml
git commit -m "feat(mine): write labeled datasets as JSONL with provenance"
```

- [ ] **Step 8: Build the real dataset**

Run `isflaky-mine` over every repository from Task 1's `REPOS` list that showed reruns, for example:

```bash
uv run --extra mine isflaky-mine \n  pandas-dev/pandas psf/requests encode/httpx pallets/flask \n  scikit-learn/scikit-learn aio-libs/aiohttp pydantic/pydantic tiangolo/fastapi \n  --out data/dataset.jsonl
```

Expected: a labeled count matching the Task 1 estimate within an order of magnitude.

Report three numbers to the user: total labeled failures, the flaky-to-real ratio, and the number of distinct repositories represented. A ratio far from balanced changes the baselines in Plan 2, because a majority-class baseline gets stronger as the ratio skews.

- [ ] **Step 9: Commit the dataset**

```bash
git add data/dataset.jsonl
git commit -m "feat(mine): add labeled CI failure dataset"
```

---

## Plan Complete

After Task 9, the repository holds a labeled dataset of real CI failures, a parser shared by production and mining, and a bounded state builder. Plan 2 adds the decision engine, the gate, and the benchmark that turns this dataset into published numbers.
