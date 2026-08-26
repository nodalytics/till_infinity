"""LLM analysis over the collected data, and an agent that watches the bus.

Two ways in. `analyse()` asks one question and returns a validated answer:

    from till_infinity.agents import analyse

    run = await analyse("Is anyone quoting gold out of line right now?")
    print(run.analysis.summary)

`watch()` is the standing version - it consumes prices and news off the bus,
decides when something is worth a model call, and publishes what it finds to
`alerts` for the notifiers to deliver.

Everything the model can read goes through `data.py`, which opens every store
read-only. A prompt injection in a headline reaches a model whose only
available verbs are SELECT.
"""

from __future__ import annotations

from . import data, providers
from .analyst import (
    NotConfiguredError,
    ProviderUnavailableError,
    analyse,
    build,
    build_model,
    model_settings,
)
from .config import DEFAULT_MODEL, Settings
from .models import Analysis, Finding, Run, Trigger
from .roles import DEFAULT_ROLE, GROUND_RULES, ROLES, Role, resolve
from .service import MIN_CONFIDENCE, TOPICS, Watcher, interesting, prompt_for, watch
from .tools import REGISTRY, Deps

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_ROLE",
    "GROUND_RULES",
    "MIN_CONFIDENCE",
    "REGISTRY",
    "ROLES",
    "TOPICS",
    "Analysis",
    "Deps",
    "Finding",
    "NotConfiguredError",
    "ProviderUnavailableError",
    "Role",
    "Run",
    "Settings",
    "Trigger",
    "Watcher",
    "analyse",
    "build",
    "build_model",
    "data",
    "interesting",
    "model_settings",
    "prompt_for",
    "providers",
    "resolve",
    "watch",
]
