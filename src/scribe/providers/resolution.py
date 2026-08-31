"""Resolves which provider/API key to use for a `generate` run.

Precedence, from strongest to weakest signal:
1. An explicit `--provider` (the API key, if any, still comes from
   `--api-key` or that provider's own env var).
2. An explicit `--api-key` with a recognizable prefix -> sniff the provider.
3. A provider-specific env var (`ANTHROPIC_API_KEY`, `GROQ_API_KEY`, ...) is
   already set -> use that provider directly, no sniffing needed.
4. Ollama is reachable on localhost -> use it, no key required at all.
5. Nothing available -> raise `NoProviderResolvedError` with setup guidance
   covering free, free-tier, and paid options.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from scribe.providers.registry import PROVIDER_PRESETS, detect_provider_from_api_key

OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
OLLAMA_PROBE_TIMEOUT_SECONDS = 0.5

SETUP_GUIDANCE = """No API key was provided and no local model server (Ollama) was detected.

FREE / LOCAL (no signup, no cost):
  Install Ollama (https://ollama.com), run `ollama pull llama3.1:8b`, then `ollama serve`,
  and re-run this command -- Ollama is auto-detected once it's running.

FREE TIER (signup required, no cost):
  Groq:       https://console.groq.com/keys   then --provider groq       --api-key gsk_...
  OpenRouter: https://openrouter.ai/keys      then --provider openrouter --api-key sk-or-...

PAID (best quality; most also include free trial credit on signup):
  Anthropic:  https://console.anthropic.com/  then --provider anthropic  --api-key sk-ant-...
  OpenAI:     https://platform.openai.com/    then --provider openai     --api-key sk-...

Run `scribe models` for the full list, or see MODELS.md. To add a new provider (paid, free-trial,
or local) to this list, see "Adding a Provider" in MODELS.md.
"""


class NoProviderResolvedError(RuntimeError):
    """Raised when no provider could be determined and none was explicitly requested."""


@dataclass(frozen=True)
class ProviderResolution:
    provider: str
    api_key: str | None
    note: str = ""  # human-readable explanation of how the provider was chosen


def _env_key_for(provider: str) -> str | None:
    preset = PROVIDER_PRESETS.get(provider)
    return os.environ.get(preset.api_key_env_var) if preset else None


def is_ollama_running(probe_url: str = OLLAMA_TAGS_URL) -> bool:
    """Check whether a local Ollama server is reachable (short timeout, no exceptions raised)."""
    try:
        with urllib.request.urlopen(probe_url, timeout=OLLAMA_PROBE_TIMEOUT_SECONDS):
            return True
    except (OSError, urllib.error.URLError):
        return False


def resolve_provider_and_key(
    explicit_provider: str | None,
    explicit_api_key: str | None,
    *,
    ollama_probe: Callable[[], bool] = is_ollama_running,
) -> ProviderResolution:
    """Determine which provider/API key to use, per the precedence in the module docstring."""
    if explicit_provider:
        api_key = explicit_api_key or _env_key_for(explicit_provider)
        return ProviderResolution(provider=explicit_provider, api_key=api_key)

    if explicit_api_key:
        detected = detect_provider_from_api_key(explicit_api_key)
        if detected:
            return ProviderResolution(
                provider=detected,
                api_key=explicit_api_key,
                note=f"Detected provider '{detected}' from the API key's format.",
            )
        raise NoProviderResolvedError(
            "Couldn't determine the provider from the supplied API key's format. "
            "Pass --provider explicitly (run `scribe models` to see options)."
        )

    for preset in PROVIDER_PRESETS.values():
        env_value = _env_key_for(preset.name)
        if env_value:
            return ProviderResolution(
                provider=preset.name,
                api_key=env_value,
                note=f"Using {preset.api_key_env_var} found in the environment.",
            )

    if ollama_probe():
        return ProviderResolution(
            provider="ollama",
            api_key=None,
            note="No API key found; Ollama is running locally, using it for free generation.",
        )

    raise NoProviderResolvedError(SETUP_GUIDANCE)
