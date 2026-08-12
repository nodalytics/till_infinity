"""Which model, from which provider.

Claude is the default, not a requirement. A model is named `provider:model`
(`openai:gpt-5`, `google:gemini-2.5-pro`, `xai:grok-4`) and a bare name is
treated as Anthropic's, which keeps `claude-opus-5` working as it always has.

Two things are provider-shaped and everything else is not:

**Reasoning.** Every provider spells it differently — Anthropic takes
`anthropic_thinking`, OpenAI an effort level, Google a thinking config — so
`reasoning()` maps one `thinking` switch onto whichever key the provider wants.
The settings objects are TypedDicts, which are plain dicts at runtime, so this
needs no import from an SDK that may not be installed.

**Credentials.** Each provider reads its own environment variable, and this
module knows which, so `agents ask` can say *"OPENAI_API_KEY is not set"*
rather than failing somewhere inside an HTTP call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

#: Provider a bare model name belongs to. Claude is the project default.
DEFAULT_PROVIDER = "anthropic"


@dataclass(frozen=True, slots=True)
class Provider:
    """What we need to know about a provider to use it or explain why we cannot."""

    name: str
    env: str
    #: uv extra that installs its client, when one is needed.
    extra: str = ""
    label: str = ""

    @property
    def key(self) -> str:
        return os.environ.get(self.env, "")

    @property
    def install(self) -> str:
        return f'uv add "pydantic-ai-slim[{self.extra}]"' if self.extra else ""


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider("anthropic", "ANTHROPIC_API_KEY", "anthropic", "Claude"),
    "openai": Provider("openai", "OPENAI_API_KEY", "openai", "GPT"),
    "openai-chat": Provider("openai-chat", "OPENAI_API_KEY", "openai", "GPT"),
    "openai-responses": Provider("openai-responses", "OPENAI_API_KEY", "openai", "GPT"),
    "google": Provider("google", "GOOGLE_API_KEY", "google", "Gemini"),
    "google-gla": Provider("google-gla", "GEMINI_API_KEY", "google", "Gemini"),
    # xAI's Grok. Not to be confused with `groq`, a different company whose
    # name differs by one letter and which serves other people's models.
    "xai": Provider("xai", "XAI_API_KEY", "openai", "Grok"),
    "groq": Provider("groq", "GROQ_API_KEY", "groq", "Groq-hosted"),
    "deepseek": Provider("deepseek", "DEEPSEEK_API_KEY", "openai", "DeepSeek"),
    "mistral": Provider("mistral", "MISTRAL_API_KEY", "mistral", "Mistral"),
    "cohere": Provider("cohere", "CO_API_KEY", "cohere", "Command"),
    "openrouter": Provider("openrouter", "OPENROUTER_API_KEY", "openai", "OpenRouter"),
    "bedrock": Provider("bedrock", "AWS_ACCESS_KEY_ID", "bedrock", "Bedrock"),
    # Local models need no key at all, which `ready` has to allow for.
    "ollama": Provider("ollama", "", "openai", "local"),
}


def split(model: str) -> tuple[str, str]:
    """`provider:model` -> the two parts. A bare name is Anthropic's."""
    name = (model or "").strip()
    if ":" not in name:
        return DEFAULT_PROVIDER, name
    provider, _, rest = name.partition(":")
    return provider.strip().lower(), rest.strip()


def qualified(model: str) -> str:
    """The full `provider:model` string pydantic-ai infers from."""
    provider, name = split(model)
    return f"{provider}:{name}"


def provider_for(model: str) -> Provider:
    """What we know about the provider behind this model name."""
    provider, _ = split(model)
    return PROVIDERS.get(provider, Provider(provider, "", "", provider))


def ready(model: str) -> bool:
    """Whether this model can be used right now.

    A provider we have never heard of is assumed usable — better to let it try
    and fail with the SDK's own message than to refuse something that works.
    """
    known = provider_for(model)
    return bool(known.key) if known.env else True


def missing(model: str) -> str:
    """A sentence saying exactly what is not set, or "" when nothing is."""
    if ready(model):
        return ""
    known = provider_for(model)
    return f"{known.env} is not set (needed for {qualified(model)})"


def reasoning(model: str, on: bool) -> dict[str, Any]:
    """Extended thinking, in whichever dialect this provider speaks.

    Returns the settings keys to merge, empty when thinking is off or the
    provider has no equivalent. Anthropic gets adaptive thinking rather than a
    token budget: the current Claude models reject `budget_tokens` outright.
    """
    if not on:
        return {}
    provider, _ = split(model)
    match provider:
        case "anthropic":
            return {"anthropic_thinking": {"type": "adaptive"}}
        case "openai" | "openai-chat" | "openai-responses":
            return {"openai_reasoning_effort": "medium"}
        case "google" | "google-gla":
            return {"google_thinking_config": {"include_thoughts": True}}
        case _:
            # Grok reasons without being asked; everything else either has no
            # equivalent or turns it on server-side.
            return {}
