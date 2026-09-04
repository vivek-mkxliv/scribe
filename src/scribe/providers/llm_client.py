"""Pluggable LLM client wrapper supporting Anthropic, OpenAI, and any
OpenAI-compatible endpoint (Groq, OpenRouter, Together AI, Ollama, LM
Studio, etc. -- see `registry.py`).

Each provider's SDK is imported lazily so the package doesn't hard-require
all of them to be installed; install the relevant optional extra
(`pip install scribe[anthropic]` or `scribe[openai]`). OpenAI-compatible
providers reuse the `openai` package with a custom `base_url`.
"""

from __future__ import annotations

import random
import time
from typing import Protocol

from scribe.providers.registry import NATIVE_PROVIDERS, PROVIDER_PRESETS, resolve_base_url

RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


class UnsupportedProviderError(ValueError):
    """Raised when an unknown --provider value is supplied."""


class LLMClient(Protocol):
    def complete(
        self, prompt: str, model: str, *, temperature: float | None = None, max_tokens: int | None = None
    ) -> str: ...


def _retry_call(func, *, max_attempts: int = 5) -> str:
    """Call `func()` with exponential backoff + jitter on retryable errors.

    A `status_code` attribute (as SDKs like `openai`/`anthropic` set on their
    API error classes) that is present and NOT in `RETRYABLE_STATUS_CODES`
    (e.g. a 401/403 auth error) is raised immediately, no retry. Everything
    else (retryable status codes, or unknown/network errors with no status
    code at all) is retried with backoff up to `max_attempts`.
    """
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as exc:
            status_code = getattr(exc, "status_code", None)
            if status_code is not None and status_code not in RETRYABLE_STATUS_CODES:
                raise
            if attempt == max_attempts - 1:
                raise
            sleep_for = min(2**attempt, 30) + random.uniform(0, 1)
            time.sleep(sleep_for)
    raise AssertionError("unreachable")  # pragma: no cover - satisfies type checkers


class AnthropicClient:
    def __init__(self, api_key: str) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - import guard
            raise ImportError(
                "The 'anthropic' package is required for --provider anthropic. "
                "Install it with: pip install scribe[anthropic]"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)

    def complete(
        self, prompt: str, model: str, *, temperature: float | None = None, max_tokens: int | None = None
    ) -> str:
        def call() -> str:
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens or 8192,
                messages=[{"role": "user", "content": prompt}],
                **({"temperature": temperature} if temperature is not None else {}),
            )
            return "".join(block.text for block in response.content if block.type == "text")

        return _retry_call(call)


class OpenAIClient:
    """Native OpenAI client, also reused for any OpenAI-compatible endpoint."""

    def __init__(self, api_key: str, base_url: str | None = None) -> None:
        try:
            import openai
        except ImportError as exc:  # pragma: no cover - import guard
            raise ImportError(
                "The 'openai' package is required for --provider openai (and for "
                "OpenAI-compatible providers like groq/ollama/openrouter/together/lmstudio). "
                "Install it with: pip install scribe[openai]"
            ) from exc
        self._client = openai.OpenAI(api_key=api_key or "not-required", base_url=base_url)

    def complete(
        self, prompt: str, model: str, *, temperature: float | None = None, max_tokens: int | None = None
    ) -> str:
        extra_kwargs: dict[str, object] = {}
        if temperature is not None:
            extra_kwargs["temperature"] = temperature
        # Always set an explicit cap (matching AnthropicClient's own `max_tokens or 8192`
        # fallback below) rather than omitting the key entirely -- local/self-hosted
        # OpenAI-compatible servers (Ollama chief among them) apply their own, often much
        # smaller and version-dependent, default completion length when this is left
        # unset, which silently truncates a multi-document response into "very minimal"
        # per-page content. Observed in practice against a real Ollama run.
        extra_kwargs["max_tokens"] = max_tokens or 8192

        def call() -> str:
            # openai's create() is a large union of overloads keyed on `stream`; a
            # dynamically-built kwargs dict can never satisfy any single overload
            # even though every key here is valid at runtime.
            response = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                **extra_kwargs,  # type: ignore[call-overload]
            )
            return response.choices[0].message.content or ""

        return _retry_call(call)


def build_client(provider: str, api_key: str | None, base_url: str | None = None) -> LLMClient:
    """Factory returning the appropriate LLM client for `provider`.

    `provider` may be a native provider ("anthropic", "openai") or any key in
    `PROVIDER_PRESETS` (openai-compatible endpoints), or an arbitrary string
    when combined with an explicit `base_url` override for unlisted endpoints.
    """
    if provider == "anthropic":
        if not api_key:
            raise ValueError("Anthropic requires an API key (--api-key or ANTHROPIC_API_KEY).")
        return AnthropicClient(api_key)

    if provider == "openai" and base_url is None:
        if not api_key:
            raise ValueError("OpenAI requires an API key (--api-key or OPENAI_API_KEY).")
        return OpenAIClient(api_key)

    resolved_base_url = resolve_base_url(provider, base_url)
    if resolved_base_url is None:
        known = ", ".join(sorted(set(PROVIDER_PRESETS) | NATIVE_PROVIDERS))
        raise UnsupportedProviderError(
            f"Unsupported provider: {provider!r}. Known providers: {known}. "
            "Pass --base-url to use an unlisted OpenAI-compatible endpoint."
        )
    return OpenAIClient(api_key or "", base_url=resolved_base_url)
