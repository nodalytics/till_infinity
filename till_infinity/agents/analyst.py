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
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.usage import UsageLimits

from ..logging import get_logger
from . import tools
from .config import Settings
from .models import Analysis, Run
from .roles import Role, resolve

log = get_logger(__name__)


class NotConfiguredError(RuntimeError):
    """No API key. Raised rather than logged, because nothing can proceed."""


def build_model(settings: Settings) -> AnthropicModel | FallbackModel:
    """The model to run against, with fallbacks behind it.

    A monitor that goes quiet because one model returned a 529 is a monitor
    that failed at the only moment it mattered, so a degraded answer from the
    next model down beats no answer.
    """
    if not settings.ready:
        raise NotConfiguredError("ANTHROPIC_API_KEY is not set")
    provider = AnthropicProvider(api_key=settings.api_key)
    primary = AnthropicModel(settings.model, provider=provider)
    spares = [AnthropicModel(name, provider=provider) for name in settings.fallbacks]
    return FallbackModel(primary, *spares) if spares else primary


def model_settings(settings: Settings) -> AnthropicModelSettings:
    """Claude-specific levers, set once.

    Adaptive thinking rather than a fixed budget: the current models reject
    `budget_tokens`, and the depth wanted here genuinely varies — "is this
    spread unusual" is one tool call, "does the calendar explain this move" is
    several rounds of reading and comparing.
    """
    options: dict[str, Any] = {
        "max_tokens": settings.max_tokens,
        "timeout": settings.timeout,
    }
    if settings.thinking:
        options["anthropic_thinking"] = {"type": "adaptive"}
    return AnthropicModelSettings(**options)


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
    usage = result.usage()
    return Run(
        analysis=result.output,
        role=chosen.name,
        model=settings.model,
        elapsed=time.monotonic() - started,
        requests=getattr(usage, "requests", 0) or 0,
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
    )
