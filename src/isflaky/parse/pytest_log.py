import re
from dataclasses import dataclass

from isflaky.core.models import Failure

# GitHub Actions prefixes every log line with an ISO-8601 timestamp.
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")
_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_SUMMARY_HEADER = re.compile(r"=+\s*short test summary info\s*=+")
_FAILED_LINE = re.compile(r"^FAILED (?P<test_id>\S+)(?: - (?P<error>.*))?$")
_FAILURES_HEADER = re.compile(r"=+\s*FAILURES\s*=+")
# A parametrised block title contains spaces, so the name cannot be \S+.
_BLOCK_DELIMITER = re.compile(r"^_{3,}\s+(?P<name>.+?)\s+_{3,}$")
_CAPTURED = re.compile(r"^-+\s*Captured .*-+$")
_ERROR_LINE = re.compile(r"^E\s+(?P<error>\S.*)$")
_SECTION_END = re.compile(
    r"^=+\s*.*in \d+\.?\d*s.*=+$|^=+\s*[0-9]+ (?:passed|failed|skipped).*=+$"
)


@dataclass(frozen=True)
class _Block:
    traceback: str
    log_context: str
    error: str


def _strip(line: str) -> str:
    cleaned = _TIMESTAMP.sub("", line)
    return _ANSI.sub("", cleaned).rstrip()


def parse_pytest_log(text: str) -> list[Failure]:
    lines = [_strip(line) for line in text.splitlines()]
    blocks = _collect_blocks(lines)

    failures: list[Failure] = []
    seen_test_ids: set[str] = set()

    i = 0
    n = len(lines)
    while i < n:
        if _SUMMARY_HEADER.search(lines[i]):
            i += 1
            while i < n:
                line = lines[i]
                if _SECTION_END.match(line) or _SUMMARY_HEADER.search(line):
                    break
                match = _FAILED_LINE.match(line)
                if match is not None:
                    test_id = match.group("test_id")
                    if test_id not in seen_test_ids:
                        seen_test_ids.add(test_id)
                        failures.append(
                            _failure(test_id, match.group("error"), blocks, i + 1)
                        )
                i += 1
        else:
            i += 1

    return failures


def _failure(
    test_id: str, summary_error: str | None, blocks: dict[str, _Block], line_no: int
) -> Failure:
    block = _block_for(test_id, blocks)
    return Failure(
        test_id=test_id,
        # The summary line truncates long reasons and is sometimes absent
        # entirely, so the traceback's own E line is the better source.
        error=(summary_error or "").strip() or (block.error if block else ""),
        traceback=block.traceback if block else "",
        log_context=block.log_context if block else "",
        line_no=line_no,
    )


def _block_for(test_id: str, blocks: dict[str, _Block]) -> _Block | None:
    """Match a summary id against a FAILURES block title.

    pytest writes the id as `path::Class::test` but titles the block
    `Class.test`, so neither form finds the other without normalising.
    """
    for key in _keys_of(test_id):
        block = blocks.get(key)
        if block is not None:
            return block
    return None


def _keys_of(test_id: str) -> list[str]:
    parts = test_id.split("::")
    keys = [".".join(parts[1:]), parts[-1]]
    # A parametrised id ends in [param]; the block title keeps it, but a run
    # that reports the base name should still match.
    bare = parts[-1].split("[", 1)[0]
    if bare != parts[-1]:
        keys.append(bare)
    return keys


def _collect_blocks(lines: list[str]) -> dict[str, _Block]:
    """Every FAILURES section in the log, not only the first.

    A matrix build concatenates one log per job, so the tracebacks for most
    failures live in a section other than the first one.
    """
    blocks: dict[str, _Block] = {}
    name: str | None = None
    body: list[str] = []
    inside = False

    for line in lines:
        if _FAILURES_HEADER.search(line):
            _store(blocks, name, body)
            name, body, inside = None, [], True
            continue
        if not inside:
            continue

        delimiter = _BLOCK_DELIMITER.match(line)
        if delimiter:
            _store(blocks, name, body)
            name, body = delimiter.group("name"), []
            continue
        if _SECTION_END.match(line) or _SUMMARY_HEADER.search(line):
            _store(blocks, name, body)
            name, body, inside = None, [], False
            continue
        body.append(line)

    _store(blocks, name, body)
    return blocks


def _store(blocks: dict[str, _Block], name: str | None, body: list[str]) -> None:
    if name is None:
        return
    blocks.setdefault(name, _split(body))


def _split(body: list[str]) -> _Block:
    """Separate the traceback from pytest's captured output sections."""
    traceback: list[str] = []
    captured: list[str] = []
    target = traceback
    for line in body:
        if _CAPTURED.match(line):
            target = captured
            continue
        target.append(line)
    return _Block(
        traceback="\n".join(traceback).strip(),
        log_context="\n".join(captured).strip(),
        error=_first_error(traceback),
    )


def _first_error(traceback: list[str]) -> str:
    for line in traceback:
        match = _ERROR_LINE.match(line)
        if match is not None:
            return match.group("error").strip()
    return ""
