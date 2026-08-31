# Supported Models & Providers

`scribe generate` picks a provider automatically: pass `--provider` explicitly, or just supply
`--api-key` and S.C.R.I.B.E. detects the provider from the key's format (e.g. `sk-ant-...` ->
Anthropic, `gsk_...` -> Groq). With no key at all, it uses a locally running Ollama server if one
is found, or prints free/paid setup options if not. Run `scribe models` for the same table below
from the CLI.

Every non-native provider (everything except `anthropic`/`openai`) is served through a single
OpenAI-compatible client, so adding a new one is a registry entry, not new code — see
[`src/scribe/core/providers.py`](src/scribe/core/providers.py).

**The tables below are auto-generated from `providers.py` by
[`scripts/generate_models_doc.py`](scripts/generate_models_doc.py) — do not hand-edit between the
markers.** Run `python scripts/generate_models_doc.py` after changing `providers.py`, or
`--check` to verify this file isn't stale (CI-friendly, exits 1 if out of date).

<!-- AUTO-GENERATED:PROVIDERS:START (run `python scripts/generate_models_doc.py` to refresh) -->

## Recommended (Paid, Best Quality)

| Provider | Recommended Models | Why |
|---|---|---|
| `anthropic` | `claude-sonnet-4-5`, `claude-opus-4-1` | Best overall quality for long, structured technical documentation. Free trial credit on signup. |
| `openai` | `gpt-4.1`, `gpt-4o`, `o3-mini` | Strong general-purpose alternative to Claude. Free trial credit on signup. |
| `google` | `gemini-2.0-flash`, `gemini-1.5-pro` | Large context windows; useful for whole-repo digests. Free trial credit on signup. |
| `together` | `meta-llama/Llama-3.3-70B-Instruct-Turbo` | Cheap hosted inference for open-weight models. |

## Free / Open-Source / Local

| Provider | Recommended Models | Cost | Notes |
|---|---|---|---|
| `groq` | `llama-3.3-70b-versatile`, `mixtral-8x7b-32768` | free-tier | Free tier available; serves open-weight models at very high speed. |
| `openrouter` | `meta-llama/llama-3.3-70b-instruct:free`, `qwen/qwen-2.5-72b-instruct:free` | free-tier | Aggregator; many `:free`-suffixed open-weight models with no cost. |
| `ollama` | `llama3.1:8b`, `qwen2.5-coder:32b`, `deepseek-r1:14b` | local | Runs entirely on your machine, no API key, no network egress. Requires `ollama serve`. |
| `lmstudio` | `(whatever model is loaded in LM Studio)` | local | Point-and-click local model runner with an OpenAI-compatible server. |

<!-- AUTO-GENERATED:PROVIDERS:END -->

## Using an Unlisted Provider

Any endpoint that speaks the OpenAI `/chat/completions` API works via `--provider <anything> --base-url <url>`, even if it's not in the table above (e.g. vLLM, Fireworks, DeepInfra, Anyscale).

## Adding a Provider

Submitting a new provider (paid, free-trial, or local) is a single `ProviderPreset` entry in
[`src/scribe/core/providers.py`](src/scribe/core/providers.py) — no new client code needed as long
as it speaks the OpenAI-compatible `/chat/completions` API:

```python
"your-provider": ProviderPreset(
    name="your-provider",
    display_name="Human-readable name",
    base_url="https://api.your-provider.com/v1",   # None only for anthropic/openai's native SDKs
    requires_api_key=True,                           # False for fully local servers
    api_key_env_var="YOUR_PROVIDER_API_KEY",
    cost="paid",                                     # "paid" | "free-tier" | "local"
    recommended_models=["their-best-model-for-docs"],
    notes="One line: why pick this, and any free-trial/signup detail.",
    key_prefixes=("yp-",),                            # omit if keys have no recognizable prefix
),
```

Then run `python scripts/generate_models_doc.py` to refresh the tables above and open a PR.

## Choosing for This Team

- **No budget / air-gapped machine:** `ollama` with `qwen2.5-coder:32b` or `llama3.1:8b`.
- **Best quality, cost is not a concern:** `anthropic` with `claude-sonnet-4-5`.
- **Fast iteration while prototyping prompts:** `groq` (free tier, very low latency).

