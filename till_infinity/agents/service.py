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
from collections import OrderedDict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass

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

#: Messages held for one judgement.
#:
#: This is where the memory went, and it was not where anyone looked first. A
#: thirty-minute window over fourteen instruments held **101,297 messages,
#: 199MB** — about half the resident size when the box was OOM-killed — and all
#: of it to derive fifteen triggers. Quotes dominate: fourteen instruments times
#: six venues at a fifteen-second poll is a message every few hundredths of a
#: second, and the window keeps every one until it elapses.
#:
#: 20,000 is roughly 40MB, which is affordable, and comfortably more than the
#: gate needs — it wants the widest spread and the loudest signal per
#: instrument, not a complete record. The cost of overflowing is that the
#: *oldest* messages go, so a spread spike early in a very busy window can be
#: missed. That is a real loss and it is logged rather than hidden.
#:
#: The better fix is to fold each message into the running answer as it arrives
#: and never hold the list at all — the gate already computes exactly that. Left
#: as the next step because a bounded list is small, obvious and reversible,
#: while streaming aggregation changes what `prompt_for` can say.
WINDOW_MESSAGES = 20_000

#: Triggers handed to the analyst in one window.
#:
#: Not a cost control so much as a shape control: the model investigates what
#: it is given, so the tool calls it makes scale with this number, and the
#: number scales with how many instruments are tracked. Fourteen instruments
#: across six venues produced forty-two tool calls against a limit of
#: thirty-two, having produced fourteen against twelve a fortnight earlier —
#: raising the limit each time is chasing rather than fixing.
#:
#: Deduplicating per instrument does most of the work: one dislocation seen at
#: four venues is one instrument dislocating. This is the backstop for a window
#: where genuinely many instruments move at once, which is exactly the window
#: worth analysing and the worst one to hand over whole.
MAX_TRIGGERS = 10


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
    #: The strongest signal per instrument. One dislocation seen at four venues
    #: is one instrument dislocating, not four findings — the same reasoning the
    #: quote gate below already applies to a hundred ticks.
    loudest: dict[str, tuple[float, Trigger]] = {}

    for message in messages:
        payload = message.payload
        if message.topic == SIGNALS:
            # A signal has already cleared the numeric layer's own guards, so
            # it needs no second arithmetic gate here — it arrives *because*
            # something passed one. Re-filtering would discard the work that
            # made it worth sending.
            feed = str(payload.get("feed") or "")
            score = abs(float(payload.get("score") or 0.0))
            trigger = Trigger(
                reason=(
                    f"{payload.get('venue', '')} {payload.get('feed', '')}: "
                    f"{payload.get('detail') or payload.get('shape', 'signal')}"
                ).strip(),
                topic=SIGNALS,
                payload=dict(payload),
            )
            known = loudest.get(feed)
            if known is None or score > known[0]:
                loudest[feed] = (score, trigger)
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

    # Loudest first, so anything the cap below drops is the least of them.
    triggers += [trigger for _score, trigger in sorted(loudest.values(), key=lambda it: -it[0])]

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

    if len(triggers) > MAX_TRIGGERS:
        # Said out loud rather than trimmed quietly. A cap that silently drops
        # findings reads afterwards as "that is all there was".
        log.info(
            "agents: %d triggers in this window, analysing the strongest %d",
            len(triggers),
            MAX_TRIGGERS,
        )
        triggers = triggers[:MAX_TRIGGERS]
    return triggers


@dataclass(slots=True)
class Quiet:
    """How close a window came, for a window that crossed nothing.

    Exists because a gate that never fires and a gate that never runs look
    identical from outside, and this one looked like the second for seven hours
    — the whole log held a single `agents started` line. It was in fact the
    first, declining correctly and saying so only at DEBUG, which production
    does not print.

    Reporting the *closest approach* rather than the fact of declining is what
    makes it useful: "nothing crossed" is unfalsifiable, while "widest spread
    1.9bps against 8.0 needed" is a threshold someone can judge.
    """

    messages: int = 0
    quotes: int = 0
    events: int = 0
    #: The widest spread seen, and where — the near-miss on the quote gate.
    widest_bps: float = 0.0
    widest_at: str = ""
    spread_threshold: float = 0.0
    #: Self-calibrating gates compare against a venue's own history, so the
    #: configured number is a ceiling rather than the line actually applied.
    calibrated: bool = False
    #: The strongest release that actually printed, against what was needed.
    top_importance: int = 0
    importance_threshold: int = 0
    #: Calendar entries that have not printed yet. Counted separately because
    #: a window full of high-importance events that are all still scheduled is
    #: a different situation from a quiet calendar, and reads the same.
    unreleased: int = 0

    def __str__(self) -> str:
        if not self.quotes and not self.events:
            return f"{self.messages} message(s), none of them a quote or a release"
        parts: list[str] = []
        if self.quotes:
            where = f" at {self.widest_at}" if self.widest_at else ""
            gate = "its own recent range" if self.calibrated else f"{self.spread_threshold:.1f}bps"
            parts.append(f"widest spread {self.widest_bps:.1f}bps{where} against {gate} needed")
        if self.events:
            parts.append(
                f"strongest release importance {self.top_importance} "
                f"against {self.importance_threshold} needed"
            )
        if self.unreleased:
            parts.append(f"{self.unreleased} scheduled but not yet printed")
        return (
            f"{self.messages} message(s) ({self.quotes} quote(s), {self.events} event(s)) "
            f"and nothing crossed: " + "; ".join(parts)
        )


def why_quiet(
    messages: Sequence[Message], settings: Settings, spreads: object | None = None
) -> Quiet:
    """Summarise a window that woke nobody, so the silence can be read.

    Deliberately a second pass rather than a richer return from `interesting`:
    it runs only when nothing fired, and keeping the hot path returning a plain
    list of triggers means the gate itself stays the cheap, blunt thing it is
    described as being.
    """
    found = Quiet(
        messages=len(messages),
        spread_threshold=settings.spread_bps,
        importance_threshold=settings.importance,
        calibrated=spreads is not None,
    )
    for message in messages:
        payload = message.payload
        if message.topic == QUOTES:
            bps = payload.get("spread_bps")
            if not isinstance(bps, int | float):
                continue
            found.quotes += 1
            if float(bps) > found.widest_bps:
                found.widest_bps = float(bps)
                found.widest_at = (f"{payload.get('venue', '')} {payload.get('feed', '')}").strip()
        elif message.topic == EVENTS:
            found.events += 1
            importance = int(payload.get("importance") or 0)
            if not payload.get("released"):
                found.unreleased += 1
            elif importance > found.top_importance:
                found.top_importance = importance
    return found


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
        #: Bounded, because this is where the memory went. A thirty-minute
        #: window over fourteen instruments held **101,297 messages — 199MB**,
        #: about half the resident size at the moment the box was OOM-killed,
        #: to derive fifteen triggers from. `deque` drops from the front, so a
        #: window that overflows keeps the recent end.
        self._window: deque[Message] = deque(maxlen=WINDOW_MESSAGES)
        #: How many were dropped, so the truncation can be reported rather than
        #: leaving the count in the prompt quietly wrong.
        self._dropped = 0
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
            # At INFO, and saying how close it came. This was DEBUG and said
            # only that nothing crossed, which production never printed — so a
            # gate declining correctly every thirty minutes was indistinguishable
            # from an agent loop that had never run at all.
            log.info("no wake: %s", why_quiet(window, self.settings, self.spreads))
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
                    window = list(self._window)
                    if self._dropped:
                        log.info(
                            "agents: window held %d of %d message(s); the oldest %d "
                            "were dropped to keep it bounded",
                            len(window),
                            len(window) + self._dropped,
                            self._dropped,
                        )
                    self._window.clear()
                    self._dropped = 0
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
                if len(self._window) == self._window.maxlen:
                    self._dropped += 1
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
