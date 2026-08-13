"""Watching the bus and deciding when to wake the model.

The bus carries tens of quotes a second; a model call takes seconds and costs
money. Something has to absorb that difference, and a queue is the wrong shape
— by the time a backlog drained, the market would have moved on. So messages
are gathered into a window and the window is judged as a whole.

Two gates stand between a quote and an API call:

1. `interesting()` — arithmetic, not a model. A spread inside its normal range
   and a calendar with nothing high-impact in it never cost a token.
2. The analyst itself, which is told plainly that returning no findings is a
   correct answer.

The first gate does **not** decide what is unusual by comparing against a
constant. `structures` already answers that question properly — calibrated,
per-venue, self-tuning — and a threshold here would be a worse duplicate of it,
wrong for every instrument but whichever one it was chosen on. A signal from
`structures` is therefore a trigger on its own.

The quote gate that remains is a fallback for when `structures` is not running,
and it is self-calibrating: a running quantile of the spreads actually seen at
each venue, so "wide" means wide for that venue rather than wide against a
number somebody picked.

What survives both is published to `alerts`, which `notify listen` delivers.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence

from ..bus import ALERTS, ARTICLES, BARS, EVENTS, QUOTES, SIGNALS, Bus, Message
from ..journal import Journal, decide, observe
from ..logging import get_logger
from .analyst import analyse
from .config import Settings
from .models import Finding, Run, Trigger
from .roles import DEFAULT_ROLE, Role

log = get_logger(__name__)

#: What the watcher listens to. Macro is left out on purpose: reserves move
#: monthly, so a bulk row count is not a reason to wake anything.
TOPICS: tuple[str, ...] = (QUOTES, BARS, EVENTS, ARTICLES, SIGNALS)

#: A finding has to clear this to become an alert.
MIN_CONFIDENCE = 0.5

#: Spreads remembered per venue for the fallback gate. Enough to place a
#: quantile, few enough that it follows the session rather than the month.
SPREAD_MEMORY = 400

#: Observations before a quantile is trusted. Below this the fallback defers to
#: `settings.spread_bps`, because a percentile from six readings is a confident
#: number derived from nothing.
SPREAD_WARMUP = 60

#: How unusual a spread must be, against that venue's own recent spreads.
SPREAD_QUANTILE = 0.99

#: ...and how much wider than that venue's *typical* spread. Both are needed.
#: A quantile alone is degenerate on a steady venue — if every reading is 20bps
#: then the 99th percentile is 20bps and 20.1 clears it, so a hair above normal
#: would wake a model. The multiple is what makes "wide" mean wide.
SPREAD_MULTIPLE = 1.5


class Spreads:
    """What each venue's spread normally looks like.

    Exists only so the fallback gate has something better than a constant. The
    real answer lives in `structures`, which scores per venue against a fitted
    distribution; this is the cheap version for when that is not running, and
    it is still self-calibrating, which the constant never was.
    """

    def __init__(
        self,
        memory: int = SPREAD_MEMORY,
        quantile: float = SPREAD_QUANTILE,
        multiple: float = SPREAD_MULTIPLE,
    ) -> None:
        self.memory = memory
        self.quantile = quantile
        self.multiple = multiple
        self._seen: dict[tuple[str, str], list[float]] = {}

    def observe(self, feed: str, venue: str, bps: float) -> None:
        seen = self._seen.setdefault((feed, venue), [])
        seen.append(bps)
        if len(seen) > self.memory:
            del seen[: len(seen) - self.memory]

    def unusual(self, feed: str, venue: str, bps: float, fallback: float) -> bool:
        """Whether this spread is wide *for this venue*.

        Falls back to the configured threshold until there are enough readings
        to place a quantile — a percentile from six observations would be worse
        than the constant it replaced.
        """
        seen = self._seen.get((feed, venue), [])
        if len(seen) < SPREAD_WARMUP:
            return bps >= fallback
        ordered = sorted(seen)
        cut = ordered[min(int(len(ordered) * self.quantile), len(ordered) - 1)]
        typical = ordered[len(ordered) // 2]
        # Rare *and* materially wide. Either alone fails: the quantile is
        # degenerate on a steady venue, and a multiple alone fires every time a
        # normally-tight venue has an ordinary busy minute.
        return bps >= cut and bps >= typical * self.multiple


def interesting(
    messages: Sequence[Message], settings: Settings, spreads: Spreads | None = None
) -> list[Trigger]:
    """Decide, without a model, whether this window is worth analysing.

    Cheap and deliberately blunt. Its only job is to keep quiet markets free;
    anything it lets through is judged properly by the analyst afterwards.

    `spreads` makes the quote gate self-calibrating. Without it the configured
    threshold is used, which is the old behaviour and is only right for
    whichever instrument it was chosen on.
    """
    triggers: list[Trigger] = []
    widest: Message | None = None

    for message in messages:
        payload = message.payload
        if message.topic == SIGNALS:
            # A signal has already cleared the numeric layer's own guards, so
            # it needs no second arithmetic gate here — it arrives *because*
            # something passed one. Re-filtering would discard the work that
            # made it worth sending.
            triggers.append(
                Trigger(
                    reason=(
                        f"{payload.get('venue', '')} {payload.get('feed', '')}: "
                        f"{payload.get('detail') or payload.get('shape', 'signal')}"
                    ).strip(),
                    topic=SIGNALS,
                    payload=dict(payload),
                )
            )
        elif message.topic == QUOTES:
            bps = payload.get("spread_bps")
            if not isinstance(bps, int | float):
                continue
            feed = str(payload.get("feed") or "")
            venue = str(payload.get("venue") or "")
            if spreads is not None:
                spreads.observe(feed, venue, float(bps))
                wide = spreads.unusual(feed, venue, float(bps), settings.spread_bps)
            else:
                wide = bps >= settings.spread_bps
            if wide and (widest is None or bps > (widest.payload.get("spread_bps") or 0)):
                widest = message
        elif message.topic == EVENTS:
            importance = payload.get("importance") or 0
            # A release *printing* is the event, not its being on the calendar.
            if payload.get("released") and int(importance) >= settings.importance:
                triggers.append(
                    Trigger(
                        reason=(
                            f"{payload.get('country', '')} {payload.get('title', '')} printed at "
                            f"{payload.get('actual')} against a forecast of "
                            f"{payload.get('forecast')}"
                        ).strip(),
                        topic=EVENTS,
                        payload=dict(payload),
                    )
                )

    # One trigger for the worst spread in the window, not one per quote: the
    # whole point of the window is that a hundred ticks are one situation.
    if widest is not None:
        triggers.append(
            Trigger(
                reason=(
                    f"{widest.payload.get('venue')} is quoting {widest.payload.get('feed')} "
                    f"at {float(widest.payload.get('spread_bps') or 0):.1f}bps"
                ),
                topic=QUOTES,
                payload=dict(widest.payload),
            )
        )
    return triggers


def prompt_for(triggers: Sequence[Trigger], messages: Sequence[Message]) -> str:
    """Turn a window into a question.

    The triggers are stated as what changed rather than as conclusions, and the
    model is pointed at its tools instead of being handed the data — the store
    holds far more than the window does, and the comparison it needs (is this
    spread unusual *for this venue*) is not in the messages at all.
    """
    counts: dict[str, int] = {}
    for message in messages:
        counts[message.topic] = counts.get(message.topic, 0) + 1
    seen = ", ".join(f"{n} {topic}" for topic, n in sorted(counts.items())) or "nothing"
    lines = "\n".join(f"- {trigger.reason}" for trigger in triggers)
    return (
        f"In the last window the collectors reported {seen}. "
        f"These crossed the threshold worth a second look:\n{lines}\n\n"
        "Check them against what is normal for those venues and instruments, "
        "and against anything on the calendar that would explain them. "
        "Report only what the data supports; if this is ordinary, say so and "
        "return no findings."
    )


class Watcher:
    """Consumes the bus, publishes alerts.

    Holds one piece of state worth naming: an LRU of alerts already sent, so a
    spread that stays wide for an hour is reported once rather than sixty
    times. It is the same reasoning as the news announcer — being told is only
    useful the first time.
    """

    def __init__(
        self,
        bus: Bus,
        *,
        settings: Settings | None = None,
        role: Role | str = DEFAULT_ROLE,
        group: str = "agents",
        memory: int = 500,
        journal: Journal | None = None,
    ) -> None:
        self.bus = bus
        self.settings = settings or Settings.from_env()
        self.role = role
        self.group = group
        self.memory = memory
        self.journal = journal
        self._sent: OrderedDict[tuple[str, str], float] = OrderedDict()
        self._window: list[Message] = []
        #: What each venue's spread normally is, so the fallback gate does not
        #: need a constant. `structures` answers this better when it is running.
        self.spreads = Spreads()

    # ------------------------------------------------------------- alerting

    def unseen(self, finding: Finding) -> bool:
        """True the first time a finding is seen, and again after an hour."""
        now = time.time()
        last = self._sent.get(finding.key)
        if last is not None and now - last < 3600:
            return False
        self._sent[finding.key] = now
        self._sent.move_to_end(finding.key)
        while len(self._sent) > self.memory:
            self._sent.popitem(last=False)
        return True

    async def publish(self, run: Run, trigger_context: dict | None = None) -> int:
        """Send what survived, and record why. Returns how many alerts went out."""
        sent = 0
        for finding in run.analysis.findings:
            if finding.confidence < MIN_CONFIDENCE:
                log.debug("dropping low-confidence finding: %s", finding.title)
                continue
            if not self.unseen(finding):
                log.debug("already alerted: %s", finding.title)
                continue
            # `shape` is what the notification filter routes on, and an agent
            # finding needs one for the same reason a detector does: a channel
            # narrowed to `level,drift` would otherwise drop every one of these
            # silently, which is the worst way for an analysis to fail.
            fields = {"shape": "agent"}
            if finding.instrument:
                fields["instrument"] = finding.instrument
            if finding.evidence:
                fields["evidence"] = "; ".join(finding.evidence[:4])
            fields["confidence"] = f"{finding.confidence:.0%}"
            await self.bus.publish(
                ALERTS,
                {
                    "title": finding.title,
                    "body": finding.detail,
                    "level": finding.level,
                    "fields": fields,
                    "source": f"agents/{run.role}",
                },
                source="agents",
            )
            # Recorded *with* the state it was decided from, not a pointer to
            # it: by the time anyone reads this back the quotes table will have
            # moved on, and an example is only usable with the inputs the
            # decision actually had.
            await decide(
                self.journal,
                finding.title,
                rationale=finding.detail or run.analysis.summary,
                actor=f"agents/{run.role}",
                context={
                    "level": finding.level,
                    "evidence": list(finding.evidence),
                    "summary": run.analysis.summary,
                    "model": run.model,
                    **(trigger_context or {}),
                },
                tags=tuple(t for t in (finding.instrument, finding.level) if t),
                confidence=finding.confidence,
            )
            sent += 1
        return sent

    # -------------------------------------------------------------- running

    async def consider(self, window: Sequence[Message]) -> Run | None:
        """Judge one window. Returns the run if the model was actually asked."""
        if not window:
            return None
        triggers = interesting(window, self.settings, self.spreads)
        if not triggers:
            log.debug("%d message(s), nothing above threshold", len(window))
            return None

        log.info("%d message(s) -> %s", len(window), "; ".join(t.reason for t in triggers))
        try:
            run = await analyse(
                prompt_for(triggers, window), role=self.role, settings=self.settings
            )
        except Exception as exc:  # a bad run must not end the watch
            log.error("analysis failed: %s", exc)
            return None
        context = {
            "triggers": [t.reason for t in triggers],
            "window_messages": len(window),
            "spread_bps_threshold": self.settings.spread_bps,
        }
        sent = await self.publish(run, context)
        if not sent:
            # The valuable negative example: something crossed the arithmetic
            # gate, a model looked at it properly, and decided it was nothing.
            # A dataset of only the times we acted teaches when to act, never
            # when to hold off.
            await observe(
                self.journal,
                f"Looked at {triggers[0].reason} and did not alert",
                rationale=run.analysis.summary,
                actor=f"agents/{run.role}",
                context=context,
            )
        log.info("%s -> %d alert(s)", run, sent)
        return run

    async def run(
        self,
        *,
        windows: int | None = None,
        on_window: Callable[[int, Sequence[Message], Run | None], None] | None = None,
    ) -> int:
        """Watch until the bus closes, or for `windows` windows. Returns runs made."""
        made = 0
        count = 0
        async with asyncio.TaskGroup() as group:
            readers = [group.create_task(self._read(topic)) for topic in TOPICS]
            try:
                while windows is None or count < windows:
                    await asyncio.sleep(self.settings.window_seconds)
                    window, self._window = self._window, []
                    count += 1
                    run = await self.consider(window)
                    made += run is not None
                    if on_window is not None:
                        on_window(count, window, run)
            finally:
                for reader in readers:
                    reader.cancel()
        return made

    async def _read(self, topic: str) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            async for message in self.bus.subscribe(topic, group=self.group):
                self._window.append(message)


async def watch(
    bus: Bus,
    *,
    settings: Settings | None = None,
    role: Role | str = DEFAULT_ROLE,
    group: str = "agents",
    windows: int | None = None,
    on_window: Callable[[int, Sequence[Message], Run | None], None] | None = None,
    journal: Journal | None = None,
) -> int:
    """Run a watcher over the bus. The everyday entry point."""
    watcher = Watcher(bus, settings=settings, role=role, group=group, journal=journal)
    return await watcher.run(windows=windows, on_window=on_window)
