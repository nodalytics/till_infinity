"""Building and running one analyst.

pydantic-ai supplies the loop, the tool plumbing and the output validation.
What is added here is the Claude-specific configuration it exposes but does not
choose for you — thinking, a token ceiling, a tool-call limit — and a fallback
model, so a run does not die because one model is briefly unavailable.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model, infer_model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from ..logging import get_logger
from . import providers, tools
from .config import Settings
from .models import Analysis, Run
from .roles import Role, resolve

log = get_logger(__name__)


class NotConfiguredError(RuntimeError):
    """No credentials for the chosen provider. Nothing can proceed."""


class ProviderUnavailableError(RuntimeError):
    """The provider's client is not installed. Says which extra installs it."""


def one_model(name: str) -> Model:
    """Resolve one `provider:model` name, turning SDK gaps into a clear error."""
    try:
        return infer_model(providers.qualified(name))
    except ImportError as exc:
        known = providers.provider_for(name)
        hint = f" — install it with `{known.install}`" if known.extra else ""
        raise ProviderUnavailableError(f"{providers.qualified(name)} needs a client{hint}") from exc


def build_model(settings: Settings) -> Model:
    """The model to run against, with fallbacks behind it.

    A monitor that goes quiet because one model returned a 529 is a monitor
    that failed at the only moment it mattered, so a degraded answer from the
    next model down beats no answer. Fallbacks may cross providers — a Claude
    primary with a GPT spare survives an outage at either.

    A fallback whose client is not installed, or whose key is not set, is
    dropped with a warning rather than taking the run down. It is a spare;
    refusing to start because a spare is missing defeats the point.
    """
    if not settings.ready:
        raise NotConfiguredError(providers.missing(settings.model))
    primary = one_model(settings.model)

    spares: list[Model] = []
    for name in settings.fallbacks:
        if not providers.ready(name):
            log.debug("fallback %s skipped: %s", name, providers.missing(name))
            continue
        try:
            spares.append(one_model(name))
        except ProviderUnavailableError as exc:
            log.warning("fallback %s unavailable: %s", name, exc)
    return FallbackModel(primary, *spares) if spares else primary


def model_settings(settings: Settings) -> ModelSettings:
    """Per-run levers, in whichever dialect the provider speaks.

    `max_tokens` and `timeout` are common to every provider. Reasoning is not —
    each spells it differently — so `providers.reasoning` maps the one
    `thinking` switch onto the right key. The depth wanted here genuinely
    varies: "is this spread unusual" is one tool call, "does the calendar
    explain this move" is several rounds of reading and comparing.
    """
    options: dict[str, Any] = {
        "max_tokens": settings.max_tokens,
        "timeout": settings.timeout,
        **providers.reasoning(settings.model, settings.thinking),
    }
    return ModelSettings(**options)


def build(
    role: Role | str | None = None, settings: Settings | None = None
) -> Agent[tools.Deps, Analysis]:
    """One configured analyst. Cheap to build; build one per run if you like."""
    settings = settings or Settings.from_env()
    chosen = role if isinstance(role, Role) else resolve(role)
    return Agent(
        build_model(settings),
        deps_type=tools.Deps,
        output_type=Analysis,
        instructions=chosen.instructions,
        tools=tools.build(chosen.tools),
        model_settings=model_settings(settings),
        name=f"till-infinity-{chosen.name}",
        retries=2,
    )


async def analyse(
    question: str,
    *,
    role: Role | str | None = None,
    settings: Settings | None = None,
    agent: Agent[tools.Deps, Analysis] | None = None,
) -> Run:
    """Ask one analyst one question and get a validated answer back."""
    settings = settings or Settings.from_env()
    chosen = role if isinstance(role, Role) else resolve(role)
    agent = agent or build(chosen, settings)
    deps = tools.Deps(
        prices_db=settings.prices_db,
        news_db=settings.news_db,
        journal_db=settings.journal_db,
    )

    started = time.monotonic()
    result = await agent.run(
        question,
        deps=deps,
        # A tool-call ceiling, not a token one: the failure mode worth bounding
        # is a model that keeps re-reading the same table looking for a story.
        usage_limits=UsageLimits(tool_calls_limit=settings.tool_calls),
    )
    # A property, not a method. Calling it raised "'RunUsage' object is not
    # callable" *after* a successful analysis, so a working run was thrown away
    # at the last step — and only a live call could show that, since the
    # failure is in accounting for work already done.
    usage = result.usage
    return Run(
        analysis=result.output,
        role=chosen.name,
        model=settings.model,
        elapsed=time.monotonic() - started,
        requests=getattr(usage, "requests", 0) or 0,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )
