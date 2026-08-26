"""Several agents, thinking differently, arguing once, then deciding.

The other four strategies read the measured signal and apply arithmetic to it.
This one hands the same evidence to a handful of models with **different
reasoning modes** and lets them reach their own conclusion, including the
conclusion that there is no trade.

## Why different modes rather than several copies

Asking one model five times gives five answers with the same blind spots.
Asking five models that have been told to reason in *different* ways gives
answers that fail differently - and only then does agreement mean anything. A
committee that agrees because every member made the same mistake is a committee
that has confirmed nothing.

So each voice is given a lens it must argue from: continuation, exhaustion,
arithmetic, and refusal. The last one matters most. Somebody whose job is to
say no is the difference between a panel and a chorus.

## The discussion

Two rounds, and only two.

1. **Independently.** Each voice sees the evidence and nothing else - not the
   others' answers. A first round that could see its neighbours would collapse
   onto whoever answered first, which is the failure mode a committee exists to
   avoid.
2. **Once, together.** Each voice is shown what the others concluded and may
   revise. One round, because the second is where a panel starts agreeing for
   social reasons rather than evidential ones, and because every round is N
   more model calls.

There is no judge. A judge is another model with another blind spot; the
resolution here is arithmetic - a quorum on a side, and the median of what
those who agreed proposed.

## Abstain is a real answer

A voice may decline, and declining is not a vote against - it is removed from
the count rather than counted as opposition. `structures` already publishes
"nothing is happening" as a valid finding and the agents' ground rules say the
same; a trading panel that cannot say "I don't know" will always find a trade.

## What the agents may and may not decide

They choose the **side**, and the **stop and target in volatility units** -
which is to say the shape of the trade, in the project's own scale-free
currency. They do not choose the size: that is `sizing.lots` against the
account's risk budget, and it is not a matter of opinion.

Their numbers are clamped. A model proposing a forty-unit stop is not
expressing conviction, it is failing, and the clamp is what makes the failure
harmless rather than expensive.

**Everything still passes the gates.** The council's intent goes through
`Guard` exactly as any other: the news blackout, the drift pause, the broker
dislocation check, exposure, reward-to-risk, spread, the daily loss stop. This
strategy decides what to propose. It does not decide what is allowed.
"""

from __future__ import annotations

import asyncio
import statistics
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ..logging import get_logger
from .models import Intent, Refusal, Side, SymbolSpec, Tick, Verdict
from .sizing import lots, respects_stops_level
from .strategy import Strategy, register

log = get_logger(__name__)

#: Bounds on what a voice may propose, in volatility units. A model asking for
#: a stop forty units away is not being bold, it is failing; clamping is what
#: keeps that cheap. The floor exists for the same reason in reverse - a
#: hairline stop is a guaranteed loss dressed as conviction.
MIN_STOP_VOL, MAX_STOP_VOL = 0.4, 4.0
MIN_TARGET_VOL, MAX_TARGET_VOL = 0.5, 8.0


class Opinion(BaseModel):
    """One voice's view. `abstain` is a first-class answer, not a failure."""

    side: str = Field(description="buy, sell, or abstain. Abstain freely.")
    conviction: float = Field(
        default=0.0,
        description="0 to 1. How strongly the evidence supports this, not how it feels.",
    )
    stop_vol: float = Field(
        default=1.0, description="Distance to the stop in volatility units, from the level."
    )
    target_vol: float = Field(
        default=1.5, description="Distance to the target in volatility units, from the entry."
    )
    because: str = Field(default="", description="One or two sentences. The reason, not a summary.")

    @property
    def trades(self) -> bool:
        return self.side.strip().lower() in ("buy", "sell")

    @property
    def as_side(self) -> Side | None:
        return {"buy": Side.BUY, "sell": Side.SELL}.get(self.side.strip().lower())


@dataclass(frozen=True, slots=True)
class Voice:
    """One seat at the table, and the way it is required to think."""

    name: str
    lens: str


#: The cast. Each lens is a *reasoning mode*, not a topic - the point is that
#: they make different kinds of mistake, so disagreement carries information.
VOICES: tuple[Voice, ...] = (
    Voice(
        "trend",
        "Argue from continuation. What is already in motion tends to stay in motion, "
        "and a level that has been broken once is weaker the second time. Your "
        "characteristic error is being late and buying exhaustion; say so when you "
        "suspect it of yourself.",
    ),
    Voice(
        "contrarian",
        "Argue from exhaustion and mean reversion. Crowded moves run out of buyers, "
        "and the obvious trade at an obvious level is the one that gets trapped. Your "
        "characteristic error is standing in front of something that keeps going; say "
        "so when you suspect it of yourself.",
    ),
    Voice(
        "quant",
        "Argue only from the numbers in front of you. Ignore narrative entirely. "
        "Compare every conditional against its base rate - a probability that matches "
        "the base rate has told you nothing however large it is. If the edge is inside "
        "the spread, say so and abstain.",
    ),
    Voice(
        "skeptic",
        "Your job is to refuse. Assume the trade is a mistake and try to establish it: "
        "thin evidence, a level with little history, a target beyond what the recent "
        "range supports, a release about to land. Only agree when you have tried to "
        "break the case and failed. Abstaining is a win for you, not a cost.",
    ),
)


def evidence(payload: dict[str, Any], tick: Tick, spec: SymbolSpec, feed: str) -> str:
    """What every voice sees, identically, and nothing else.

    Assembled from the signal and the live quote rather than fetched by the
    model. That is deliberate on two counts: it is deterministic, so two runs
    differ because the models differ rather than because the evidence moved;
    and it carries no free text from outside the system, so there is nothing
    here for a headline to smuggle an instruction through.
    """
    got = {k: v for k, v in (payload.get("features") or {}).items() if isinstance(v, int | float)}
    vol_bps = float(got.get("vol_bps") or 0.0)
    unit = tick.mid * vol_bps / 10_000 if vol_bps else 0.0
    confluence = payload.get("confluence") or []
    probability = got.get("probability", 0.0)
    base = got.get("base_rate_up", 0.5)

    return "\n".join(
        [
            f"instrument: {feed} ({spec.symbol}), timeframe {payload.get('interval')}",
            f"price now: bid {tick.bid:.5g} / ask {tick.ask:.5g}, spread {tick.spread:.5g} "
            f"({tick.spread_bps:.2f}bps)",
            f"one volatility unit = {unit:.5g} in price ({vol_bps:.2f}bps)",
            "",
            "what the level model measured:",
            f"  level at {got.get('level', 0.0):.5g}, price is arriving at it",
            f"  it calls {payload.get('direction') or 'no direction'} "
            f"with p={probability:.0%} against a {base:.0%} unconditional rate",
            f"  edge {got.get('edge', 0.0):+.3f} (the gap between those two)",
            f"  expected push {got.get('expected_push_vol', 0.0):+.2f}v, "
            f"risk to invalidation {got.get('risk_vol', 0.0):.2f}v",
            f"  this level's own hold rate on this side: "
            f"{got.get('record_hold', 0.0):.0%} over {got.get('record_n', 0.0):.0f} "
            f"decisive interactions",
            f"  {got.get('own_touches', 0.0):.0f} touches here, "
            f"{got.get('neighbours', 0.0):.0f} similar levels elsewhere",
            f"  timeframes agreeing on this price: {', '.join(confluence) or 'this one only'}",
            "",
            "the spread costs "
            f"{(tick.spread / unit if unit else 0.0):.2f}v to enter and the same to leave.",
            "",
            "You are not obliged to agree with the level model. It is one input. "
            "You may abstain, and abstaining is a valid answer.",
        ]
    )


@dataclass
class Council:
    """The panel, and how it reaches an answer."""

    voices: tuple[Voice, ...] = VOICES
    #: Agreeing voices needed before anything is traded. Two of four is a
    #: majority of those who spoke when two abstain, which is the common case.
    quorum: int = 2
    #: Below this the panel is not confident enough to be worth the spread.
    min_conviction: float = 0.55
    discuss: bool = True
    timeout: float = 25.0
    _agent_cache: dict[str, Any] = field(default_factory=dict, repr=False)

    def _agent(self, voice: Voice):
        """One pydantic-ai agent per voice, built once and reused."""
        if voice.name not in self._agent_cache:
            from pydantic_ai import Agent

            from ..agents.analyst import build_model
            from ..agents.config import Settings as AgentSettings

            instructions = (
                "You are one voice on a small trading desk deciding whether to take a "
                "single short-term trade. Answer only with the structured fields.\n\n"
                f"Your lens: {voice.lens}\n\n"
                "Rules that bind every voice:\n"
                "- Abstain unless the evidence supports a trade. Abstaining is free; "
                "a bad trade is not.\n"
                "- A probability only means something against its base rate.\n"
                "- Your stop and target are in volatility units, and must be reachable "
                "in the recent range rather than aspirational.\n"
                "- Say your reason in one or two sentences. Do not restate the evidence."
            )
            self._agent_cache[voice.name] = Agent(
                build_model(AgentSettings.from_env()),
                output_type=Opinion,
                instructions=instructions,
            )
        return self._agent_cache[voice.name]

    async def _ask(self, voice: Voice, prompt: str) -> Opinion | None:
        """One voice, once. None on any failure - which reads as an abstention.

        Failing to an abstention rather than to an exception is the whole
        posture of this module: a model that times out has not made a case for
        a trade, and the absence of a case is exactly what abstaining means.
        """
        try:
            result = await asyncio.wait_for(self._agent(voice).run(prompt), timeout=self.timeout)
        except TimeoutError:
            log.warning("council: %s timed out", voice.name)
            return None
        except Exception as exc:
            log.warning("council: %s failed: %s", voice.name, exc)
            return None
        return result.output

    async def deliberate(self, brief: str) -> tuple[dict[str, Opinion], str]:
        """Two rounds, then the record of what was said."""
        first = await asyncio.gather(
            *(self._ask(voice, brief) for voice in self.voices), return_exceptions=False
        )
        opinions = {v.name: o for v, o in zip(self.voices, first, strict=True) if o is not None}
        if not opinions or not self.discuss:
            return opinions, _minutes(opinions)

        table = _minutes(opinions)
        revised = await asyncio.gather(
            *(
                self._ask(
                    voice,
                    f"{brief}\n\nThe rest of the desk has now spoken:\n{table}\n\n"
                    "Answer again. Change your mind if they have made a better case, "
                    "and hold it if they have not - agreeing to agree is worse than "
                    "disagreeing. Abstaining is still open to you.",
                )
                for voice in self.voices
            ),
            return_exceptions=False,
        )
        after = {v.name: o for v, o in zip(self.voices, revised, strict=True) if o is not None}
        # A voice that failed the second round keeps its first answer rather
        # than vanishing: it made a case, and a timeout is not a retraction.
        merged = {**opinions, **after}
        return merged, f"{table}\n-- after discussion --\n{_minutes(merged)}"

    def resolve(self, opinions: dict[str, Opinion]) -> tuple[Side | None, float, float, str]:
        """The panel's answer: side, stop, target - or no side at all."""
        voting = {n: o for n, o in opinions.items() if o.trades and o.as_side is not None}
        if not voting:
            return None, 0.0, 0.0, "every voice abstained"

        sides: dict[Side, list[Opinion]] = {}
        for opinion in voting.values():
            sides.setdefault(opinion.as_side, []).append(opinion)

        side, agreed = max(sides.items(), key=lambda kv: (len(kv[1]), _mean_conviction(kv[1])))
        against = sum(len(v) for k, v in sides.items() if k is not side)
        if len(agreed) < self.quorum:
            return (
                None,
                0.0,
                0.0,
                (f"only {len(agreed)} voice(s) for {side}, quorum is {self.quorum}"),
            )
        if against >= len(agreed):
            return None, 0.0, 0.0, f"the desk is split {len(agreed)}-{against}"

        conviction = _mean_conviction(agreed)
        if conviction < self.min_conviction:
            return None, 0.0, 0.0, f"conviction {conviction:.2f} under {self.min_conviction:.2f}"

        stop = _clamp(statistics.median(o.stop_vol for o in agreed), MIN_STOP_VOL, MAX_STOP_VOL)
        target = _clamp(
            statistics.median(o.target_vol for o in agreed), MIN_TARGET_VOL, MAX_TARGET_VOL
        )
        why = f"{len(agreed)}-{against} for {side}, conviction {conviction:.2f}"
        return side, stop, target, why


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(float(value), low), high)


def _mean_conviction(opinions: list[Opinion]) -> float:
    return statistics.fmean(_clamp(o.conviction, 0.0, 1.0) for o in opinions) if opinions else 0.0


def _minutes(opinions: dict[str, Opinion]) -> str:
    if not opinions:
        return "  (nobody answered)"
    return "\n".join(
        f"  {name}: {o.side} conviction {o.conviction:.2f} "
        f"stop {o.stop_vol:.2f}v target {o.target_vol:.2f}v - {o.because}"
        for name, o in opinions.items()
    )


@register
class CouncilStrategy(Strategy):
    """A panel of agents that reasons its own way to a trade, or to no trade."""

    name: ClassVar[str] = "council"
    description: ClassVar[str] = (
        "Four agents with different reasoning modes decide independently, discuss "
        "once, then need a quorum. Costs a model call per voice per round."
    )
    shape: ClassVar[str] = "level"
    hold_seconds: ClassVar[float] = 2_700.0
    #: Every timeframe the operator allows, and every timeframe as context.
    #: The panel is told both and is expected to weigh them - a 1h call and a
    #: 1m call are different trades, and deciding that is exactly what it is
    #: for. The arithmetic strategies cannot make that judgement, so they are
    #: pinned to fast data with a fixed anchor instead.
    entries: ClassVar[tuple[str, ...]] = ()
    context: ClassVar[tuple[str, ...]] = ()

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.council = Council(
            quorum=settings.council_quorum,
            min_conviction=settings.council_min_conviction,
            discuss=settings.council_discuss,
            timeout=settings.council_timeout,
        )
        self.calls = 0
        self.abstained = 0

    def consider(
        self, payload: dict[str, Any], *, spec: SymbolSpec, tick: Tick, equity: float
    ) -> Verdict:
        """Synchronous by interface; the panel is async. See `service`.

        The Strategy port is deliberately synchronous - the other four are pure
        arithmetic and making them async would be a lie about their cost. This
        one genuinely blocks on the network, so it is driven by `consider_async`
        and refuses if called on the sync path, rather than quietly running an
        event loop inside one.
        """
        return Refusal(
            "async",
            "the council must be driven by consider_async",
            str(payload.get("feed") or ""),
        )

    async def consider_async(
        self, payload: dict[str, Any], *, spec: SymbolSpec, tick: Tick, equity: float
    ) -> Verdict:
        self.seen += 1
        feed = str(payload.get("feed") or "")
        settings = self.settings

        if not self.wants(payload):
            return Refusal("shape", f"{payload.get('shape')} is not a level call", feed)
        interval = str(payload.get("interval") or "")
        if interval not in self.intervals:
            return Refusal("interval", f"{interval} is not scalped", feed)
        if self.calls >= settings.council_daily_calls > 0:
            return Refusal("budget", f"{self.calls} model calls today, at the ceiling", feed)

        got = {
            k: float(v)
            for k, v in (payload.get("features") or {}).items()
            if isinstance(v, int | float)
        }
        vol_bps = got.get("vol_bps", 0.0)
        level = got.get("level", 0.0)
        if vol_bps <= 0 or level <= 0:
            return Refusal("volatility", "the call carries no volatility unit", feed)

        self.calls += len(self.council.voices) * (2 if self.council.discuss else 1)
        opinions, minutes = await self.council.deliberate(evidence(payload, tick, spec, feed))
        side, stop_vol, target_vol, verdict = self.council.resolve(opinions)
        log.info("council: %s - %s\n%s", feed, verdict, minutes)

        if side is None:
            self.abstained += 1
            return Refusal("council", verdict, feed)

        unit = level * vol_bps / 10_000
        entry = tick.entry(side)
        stop = spec.round_price(level - side.sign * stop_vol * unit)
        target = spec.round_price(entry + side.sign * target_vol * unit)

        if (side is Side.BUY and entry <= stop) or (side is Side.SELL and entry >= stop):
            return Refusal("through", f"price is already past {stop:.5g}", feed)
        broker_says = respects_stops_level(spec, entry, stop, target)
        if broker_says:
            return Refusal("stops_level", broker_says, feed)

        sized = lots(
            spec,
            equity=equity,
            risk_fraction=settings.risk_fraction,
            stop_distance=abs(entry - stop),
            max_risk_money=settings.max_risk_money,
        )
        if not sized.ok:
            return Refusal("size", sized.reason, feed)

        self.wanted += 1
        return Intent(
            feed=feed,
            symbol=spec.symbol,
            side=side,
            volume=sized.volume,
            entry=entry,
            stop=stop,
            target=target,
            reason=verdict,
            interval=interval,
            confluence=tuple(str(t) for t in (payload.get("confluence") or [])),
            features={**got, "council_voices": float(len(opinions))},
            risk_money=sized.risk_money,
            hold=self.hold_seconds,
        )
