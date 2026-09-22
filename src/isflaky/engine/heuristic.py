import re
import time
from collections.abc import Mapping

from isflaky.core.models import Answers
from isflaky.engine.questions import Question, QuestionSet

# Spec section 12 requires this baseline to be taken seriously: if a regex
# reaches the same accuracy as Jev, the project's premise collapses, and that
# has to be discovered here rather than by a reader.
_UNKNOWN = 0.5
_PRESENT = 0.9
_ABSENT = 0.1

_PATTERNS = {
    "network_error": r"connection|connect|reset by peer|timed? ?out|timeout|"
    r"econnre|dns|unreachable|socket|ssl|http|network",
    "timing_dependent": r"timed? ?out|timeout|sleep|schedul|race|deadline|"
    r"async|await|eventually|retry|flake",
    "assertion_failure": r"assertionerror|assert |expected .* but|"
    r"!=|does not equal|mismatch",
    "resource_contention": r"address already in use|already in use|port|lock|"
    r"file handle|too many open files|no space|out of memory|memoryerror|"
    r"permissionerror|resource temporarily unavailable",
    "external_service": r"api|endpoint|upstream|gateway|502|503|504|"
    r"service unavailable|rate limit|throttl",
    "import_or_env": r"modulenotfounderror|importerror|no module named|"
    r"cannot import|distributionnotfound|versionconflict|command not found|"
    r"environment variable",
}

# The direct question has no observable signal of its own, so the regex baseline
# answers it from the terms spec section 12 names as the keyword baseline.
_FLAKY_TERMS = r"connection|reset|timed? ?out|timeout|flake|race|socket|" r"unreachable|throttl"
_REAL_TERMS = r"assertionerror|assert |mismatch|does not equal"


class HeuristicModel:
    """Regex and majority-class baseline. No network, no key."""

    def decide(self, state: Mapping[str, str], questions: QuestionSet) -> Answers:
        started = time.perf_counter()
        haystack = " ".join(state.get(key, "") for key in ("error", "traceback", "log_context"))
        values = {
            question.name: self._answer(question, haystack.lower(), state)
            for question in questions.questions
        }
        return Answers(
            values=values,
            latency_ms=(time.perf_counter() - started) * 1000,
            truncated=False,
        )

    def _answer(self, question: Question, haystack: str, state: Mapping[str, str]) -> float:
        if question.name == "flaky":
            return self._flaky(haystack)
        if question.name == "touches_test_code":
            return self._touches_test_code(state)
        if question.name == "determinism":
            return self._determinism(haystack)

        pattern = _PATTERNS.get(question.name)
        if pattern is None:
            return _UNKNOWN
        return _PRESENT if re.search(pattern, haystack) else _ABSENT

    def _flaky(self, haystack: str) -> float:
        if re.search(_FLAKY_TERMS, haystack):
            return _PRESENT
        if re.search(_REAL_TERMS, haystack):
            return _ABSENT
        return _UNKNOWN

    def _touches_test_code(self, state: Mapping[str, str]) -> float:
        changed = state.get("changed_files", "")
        module = state.get("test_id", "").split("::", 1)[0]
        if not changed or not module:
            return _UNKNOWN
        return _PRESENT if module in changed else _ABSENT

    def _determinism(self, haystack: str) -> float:
        """High means deterministic, which points at a real regression."""
        if re.search(_REAL_TERMS, haystack):
            return _PRESENT
        if re.search(_FLAKY_TERMS, haystack):
            return _ABSENT
        return _UNKNOWN
