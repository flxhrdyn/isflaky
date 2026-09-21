import re

from isflaky.core.models import Failure

# GitHub Actions prefixes every log line with an ISO-8601 timestamp.
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s?")
_ANSI = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_SUMMARY_HEADER = re.compile(r"=+\s*short test summary info\s*=+")
_FAILED_LINE = re.compile(r"^FAILED (?P<test_id>\S+)(?: - (?P<error>.*))?$")
_FAILURES_HEADER = re.compile(r"=+\s*FAILURES\s*=+")
_BLOCK_DELIMITER = re.compile(r"^_+ (?P<name>\S+) _+$")
_SECTION_END = re.compile(r"^=+\s*.*in \d+\.?\d*s.*=+$|^=+\s*[0-9]+ (?:passed|failed|skipped).*=+$")


def _strip(line: str) -> str:
    cleaned = _TIMESTAMP.sub("", line)
    return _ANSI.sub("", cleaned).rstrip()


def parse_pytest_log(text: str) -> list[Failure]:
    lines = [_strip(line) for line in text.splitlines()]
    tracebacks = _collect_tracebacks(lines)

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
                            Failure(
                                test_id=test_id,
                                error=match.group("error") or "",
                                traceback=tracebacks.get(_short_name(test_id), ""),
                                log_context="",
                                line_no=i + 1,
                            )
                        )
                i += 1
        else:
            i += 1

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
