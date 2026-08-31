"""Tests for provider/API-key auto-detection and the local-fallback flow.

All provider env vars are cleared before each test so the suite is
deterministic regardless of what's actually set on the machine running it.
"""

from __future__ import annotations

import pytest

from scribe.providers.registry import PROVIDER_PRESETS, detect_provider_from_api_key
from scribe.providers.resolution import (
    NoProviderResolvedError,
    resolve_provider_and_key,
)


@pytest.fixture(autouse=True)
def _clear_provider_env_vars(monkeypatch):
    for preset in PROVIDER_PRESETS.values():
        monkeypatch.delenv(preset.api_key_env_var, raising=False)


@pytest.mark.parametrize(
    ("api_key", "expected_provider"),
    [
        ("sk-ant-abc123", "anthropic"),
        ("sk-or-abc123", "openrouter"),
        ("sk-proj-abc123", "openai"),
        ("sk-abc123", "openai"),
        ("gsk_abc123", "groq"),
        ("AIzaSyAbc123", "google"),
        ("totally-unrecognized-format", None),
    ],
)
def test_detect_provider_from_api_key(api_key, expected_provider):
    assert detect_provider_from_api_key(api_key) == expected_provider


def test_explicit_provider_wins_even_with_a_key_that_looks_like_another_provider():
    resolution = resolve_provider_and_key("openai", "sk-ant-looks-like-anthropic")
    assert resolution.provider == "openai"
    assert resolution.api_key == "sk-ant-looks-like-anthropic"


def test_explicit_provider_falls_back_to_its_env_var(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_from_env")
    resolution = resolve_provider_and_key("groq", None)
    assert resolution.provider == "groq"
    assert resolution.api_key == "gsk_from_env"


def test_api_key_alone_sniffs_the_provider():
    resolution = resolve_provider_and_key(None, "sk-ant-abc123")
    assert resolution.provider == "anthropic"
    assert "Detected provider" in resolution.note


def test_unrecognizable_api_key_without_explicit_provider_raises():
    with pytest.raises(NoProviderResolvedError):
        resolve_provider_and_key(None, "not-a-known-format")


def test_falls_back_to_provider_specific_env_var_when_nothing_explicit(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    resolution = resolve_provider_and_key(None, None)
    assert resolution.provider == "openai"
    assert resolution.api_key == "sk-from-env"


def test_falls_back_to_local_ollama_when_nothing_else_available():
    resolution = resolve_provider_and_key(None, None, ollama_probe=lambda: True)
    assert resolution.provider == "ollama"
    assert resolution.api_key is None
    assert "Ollama" in resolution.note


def test_raises_with_setup_guidance_when_nothing_is_available():
    with pytest.raises(NoProviderResolvedError) as exc_info:
        resolve_provider_and_key(None, None, ollama_probe=lambda: False)
    message = str(exc_info.value)
    assert "FREE" in message
    assert "PAID" in message
