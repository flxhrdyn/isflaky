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
