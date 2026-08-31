"""Registry of supported LLM providers, including OpenAI-compatible ones.

Rather than writing a bespoke client per vendor, most "open source" and
cloud providers today expose an OpenAI-compatible `/chat/completions`
endpoint. `OpenAICompatibleClient` (in `llm_client.py`) covers all of them
with a single implementation; this registry just supplies the base URL,
whether an API key is required, and recommended models per provider so the
CLI/docs can present a curated list instead of a blank text field.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderPreset:
    name: str
    display_name: str
    base_url: str | None  # None for native SDK providers (anthropic/openai)
    requires_api_key: bool
    api_key_env_var: str
    cost: str  # "paid" | "free" | "free-tier" | "local"
    recommended_models: list[str] = field(default_factory=list)
    notes: str = ""
    # Distinctive API key prefixes (e.g. "sk-ant-") used for auto-detecting the
    # provider from a bare key. Empty for providers with no recognizable prefix.
    key_prefixes: tuple[str, ...] = ()


NATIVE_PROVIDERS = {"anthropic", "openai"}

PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "anthropic": ProviderPreset(
        name="anthropic",
        display_name="Anthropic (Claude)",
        base_url=None,
        requires_api_key=True,
        api_key_env_var="ANTHROPIC_API_KEY",
        cost="paid",
        recommended_models=["claude-sonnet-4-5", "claude-opus-4-1"],
        notes="Best overall quality for long, structured technical documentation. "
        "Free trial credit on signup.",
        key_prefixes=("sk-ant-",),
    ),
    "openai": ProviderPreset(
        name="openai",
        display_name="OpenAI",
        base_url=None,
        requires_api_key=True,
        api_key_env_var="OPENAI_API_KEY",
        cost="paid",
        recommended_models=["gpt-4.1", "gpt-4o", "o3-mini"],
        notes="Strong general-purpose alternative to Claude. Free trial credit on signup.",
        key_prefixes=("sk-proj-", "sk-"),
    ),
    "google": ProviderPreset(
        name="google",
        display_name="Google Gemini (OpenAI-compatible endpoint)",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        requires_api_key=True,
        api_key_env_var="GOOGLE_API_KEY",
        cost="paid",
        recommended_models=["gemini-2.0-flash", "gemini-1.5-pro"],
        notes="Large context windows; useful for whole-repo digests. Free trial credit on signup.",
        key_prefixes=("AIza",),
    ),
    "groq": ProviderPreset(
        name="groq",
        display_name="Groq",
        base_url="https://api.groq.com/openai/v1",
        requires_api_key=True,
        api_key_env_var="GROQ_API_KEY",
        cost="free-tier",
        recommended_models=["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
        notes="Free tier available; serves open-weight models at very high speed.",
        key_prefixes=("gsk_",),
    ),
    "openrouter": ProviderPreset(
        name="openrouter",
        display_name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        requires_api_key=True,
        api_key_env_var="OPENROUTER_API_KEY",
        cost="free-tier",
        recommended_models=["meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen-2.5-72b-instruct:free"],
        notes="Aggregator; many `:free`-suffixed open-weight models with no cost.",
        key_prefixes=("sk-or-",),
    ),
    "together": ProviderPreset(
        name="together",
        display_name="Together AI",
        base_url="https://api.together.xyz/v1",
        requires_api_key=True,
        api_key_env_var="TOGETHER_API_KEY",
        cost="paid",
        recommended_models=["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
        notes="Cheap hosted inference for open-weight models.",
    ),
    "ollama": ProviderPreset(
        name="ollama",
        display_name="Ollama (fully local)",
        base_url="http://localhost:11434/v1",
        requires_api_key=False,
        api_key_env_var="OLLAMA_API_KEY",
        cost="local",
        recommended_models=["llama3.1:8b", "qwen2.5-coder:32b", "deepseek-r1:14b"],
        notes="Runs entirely on your machine, no API key, no network egress. Requires `ollama serve`.",
    ),
    "lmstudio": ProviderPreset(
        name="lmstudio",
        display_name="LM Studio (fully local)",
        base_url="http://localhost:1234/v1",
        requires_api_key=False,
        api_key_env_var="LMSTUDIO_API_KEY",
        cost="local",
        recommended_models=["(whatever model is loaded in LM Studio)"],
        notes="Point-and-click local model runner with an OpenAI-compatible server.",
    ),
}


def resolve_base_url(provider: str, override: str | None) -> str | None:
    if override:
        return override
    preset = PROVIDER_PRESETS.get(provider)
    return preset.base_url if preset else None


def resolve_api_key_requirement(provider: str) -> bool:
    preset = PROVIDER_PRESETS.get(provider)
    return preset.requires_api_key if preset else True


def detect_provider_from_api_key(api_key: str) -> str | None:
    """Best-effort provider detection from `key_prefixes` in the registry above.

    Deliberately reads `key_prefixes` off `PROVIDER_PRESETS` rather than
    duplicating a separate prefix->provider table, so adding/changing a
    provider's key format only ever requires editing one place.
    """
    candidates = [
        (preset.name, prefix) for preset in PROVIDER_PRESETS.values() for prefix in preset.key_prefixes
    ]
    for name, prefix in sorted(candidates, key=lambda item: len(item[1]), reverse=True):
        if api_key.startswith(prefix):
            return name
    return None
