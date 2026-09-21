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
