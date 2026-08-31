"""Token/cost estimation used for pre-flight warnings before an LLM call."""

from __future__ import annotations

CHARS_PER_TOKEN_HEURISTIC = 4


def estimate_token_count(text: str) -> int:
    """Estimate token count for `text`.

    Uses `tiktoken` when installed for an accurate count; otherwise falls
    back to a conservative chars-per-token heuristic. Good enough for
    pre-flight cost warnings, not billing-accurate.
    """
    try:
        import tiktoken
    except ImportError:
        return max(1, len(text) // CHARS_PER_TOKEN_HEURISTIC)

    encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(text))


def exceeds_budget(text: str, max_tokens: int) -> bool:
    return estimate_token_count(text) > max_tokens
