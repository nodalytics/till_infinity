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
from collections import Counter, OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

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


@dataclass(slots=True)
class Window:
    """What a window of bus traffic amounts to, folded in as it arrives.

    The list this replaces held every message until the window elapsed —
    101,297 of them, 199MB, to derive fifteen triggers. Nothing downstream
    ever wanted the messages: `interesting` reduces them to the widest spread,
    the loudest signal per instrument and the releases that printed, and
    `prompt_for` wants counts. All of that is computable one message at a time,
    so none of it needs keeping.

    Bounding the list was the stopgap; this removes the question. Memory is now
    proportional to the number of *instruments*, not to the traffic, so a busy
    session costs no more than a quiet one — and the spread spike that a bound
    could drop from the front of a full window can no longer be lost.

    One accumulator, used by both paths: `interesting()` folds a sequence into
    it and asks the same questions the watcher asks live, so the two cannot
    drift.
    """

    settings: Settings
    spreads: Spreads | None = None
    messages: int = 0
    quotes: int = 0
    events: int = 0
    unreleased: int = 0
    topics: Counter = field(default_factory=Counter)
    #: The strongest signal per instrument. One dislocation seen at four venues
    #: is one instrument dislocating, not four findings.
    loudest: dict[str, tuple[float, Trigger]] = field(default_factory=dict)
    #: Releases that actually printed and cleared the importance floor.
    releases: list[Trigger] = field(default_factory=list)
    #: The widest spread that was unusual *for its venue*, and the widest seen
    #: at all — the second is for explaining a decline, not for triggering.
    widest: Message | None = None
    widest_bps: float = 0.0
    widest_at: str = ""
    top_importance: int = 0

    def add(self, message: Message) -> None:
        """Fold one message in. Constant work, constant memory."""
        payload = message.payload
        self.messages += 1
        self.topics[message.topic] += 1
        if message.topic == SIGNALS:
            self._signal(payload)
        elif message.topic == QUOTES:
            self._quote(payload)
        elif message.topic == EVENTS:
            self._event(payload)

    def _signal(self, payload: dict) -> None:
        # A signal has already cleared the numeric layer's own guards, so it
        # needs no second arithmetic gate — it arrives *because* something
        # passed one. Re-filtering would discard the work that made it worth
        # sending.
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
        known = self.loudest.get(feed)
        if known is None or score > known[0]:
            self.loudest[feed] = (score, trigger)

    def _quote(self, payload: dict) -> None:
        bps = payload.get("spread_bps")
        if not isinstance(bps, int | float):
            return
        self.quotes += 1
        feed = str(payload.get("feed") or "")
        venue = str(payload.get("venue") or "")
        if float(bps) > self.widest_bps:
            self.widest_bps = float(bps)
            self.widest_at = f"{venue} {feed}".strip()
        if self.spreads is not None:
            self.spreads.observe(feed, venue, float(bps))
            wide = self.spreads.unusual(feed, venue, float(bps), self.settings.spread_bps)
        else:
            wide = bps >= self.settings.spread_bps
        if wide and (self.widest is None or bps > (self.widest.payload.get("spread_bps") or 0)):
            self.widest = Message(topic=QUOTES, payload=dict(payload))

    def _event(self, payload: dict) -> None:
        self.events += 1
        importance = int(payload.get("importance") or 0)
        # A release *printing* is the event, not its being on the calendar.
        if not payload.get("released"):
            self.unreleased += 1
            return
        self.top_importance = max(self.top_importance, importance)
        if importance >= self.settings.importance:
            self.releases.append(
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

    def triggers(self) -> list[Trigger]:
        """What in this window is worth waking a model for."""
        found = list(self.releases)
        # Loudest first, so anything the cap drops is the least of them.
        found += [
            trigger for _score, trigger in sorted(self.loudest.values(), key=lambda it: -it[0])
        ]
        # One trigger for the worst spread, not one per quote: the whole point
        # of the window is that a hundred ticks are one situation.
        if self.widest is not None:
            found.append(
                Trigger(
                    reason=(
                        f"{self.widest.payload.get('venue')} is quoting "
                        f"{self.widest.payload.get('feed')} at "
                        f"{float(self.widest.payload.get('spread_bps') or 0):.1f}bps"
                    ),
                    topic=QUOTES,
                    payload=dict(self.widest.payload),
                )
            )
        if len(found) > MAX_TRIGGERS:
            # Said out loud rather than trimmed quietly. A cap that silently
            # drops findings reads afterwards as "that is all there was".
            log.info(
                "agents: %d triggers in this window, analysing the strongest %d",
                len(found),
                MAX_TRIGGERS,
            )
            found = found[:MAX_TRIGGERS]
        return found

    def quiet(self) -> Quiet:
        """How close this window came, for one that crossed nothing."""
        return Quiet(
            messages=self.messages,
            quotes=self.quotes,
            events=self.events,
            widest_bps=self.widest_bps,
            widest_at=self.widest_at,
            spread_threshold=self.settings.spread_bps,
            calibrated=self.spreads is not None,
            top_importance=self.top_importance,
            importance_threshold=self.settings.importance,
            unreleased=self.unreleased,
        )

    def seen(self) -> str:
        """What arrived, for the prompt — counts rather than the messages."""
        return ", ".join(f"{n} {topic}" for topic, n in sorted(self.topics.items())) or "nothing"


def interesting(
    messages: Sequence[Message], settings: Settings, spreads: Spreads | None = None
) -> list[Trigger]:
    """Decide, without a model, whether this window is worth analysing.

    Cheap and deliberately blunt. Its only job is to keep quiet markets free;
    anything it lets through is judged properly by the analyst afterwards.

    A fold over `Window`, which is the same accumulator the watcher fills live.
    Keeping one implementation matters more than it looks: the streaming path
    and the batch path answering differently would be a bug nobody could see
    from either side.

    `spreads` makes the quote gate self-calibrating. Without it the configured
    threshold is used, which is the old behaviour and is only right for
    whichever instrument it was chosen on.
    """
    return _fold(messages, settings, spreads).triggers()


def why_quiet(
    messages: Sequence[Message], settings: Settings, spreads: object | None = None
) -> Quiet:
    """Summarise a window that woke nobody, so the silence can be read."""
    return _fold(messages, settings, spreads).quiet()


def _fold(messages: Sequence[Message], settings: Settings, spreads: object | None = None) -> Window:
    window = Window(settings=settings, spreads=spreads)
    for message in messages:
        window.add(message)
    return window


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


def prompt_for(triggers: Sequence[Trigger], seen: str | Sequence[Message]) -> str:
    """Turn a window into a question.

    The triggers are stated as what changed rather than as conclusions, and the
    model is pointed at its tools instead of being handed the data — the store
    holds far more than the window does, and the comparison it needs (is this
    spread unusual *for this venue*) is not in the messages at all.

    `seen` is the one-line summary of what arrived. A sequence of messages is
    still accepted and counted, because that is what the tests hand it and the
    counting is trivial; the watcher passes the string, having counted as the
    messages went past rather than keeping them to count later.
    """
    if not isinstance(seen, str):
        counts: dict[str, int] = {}
        for message in seen:
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
        #: What each venue's spread normally is, so the fallback gate does not
        #: need a constant. `structures` answers this better when it is running.
        self.spreads = Spreads()
        #: Folded in as messages arrive rather than kept. This is where the
        #: memory went: a thirty-minute window over fourteen instruments held
        #: **101,297 messages — 199MB**, about half the resident size when the
        #: box was OOM-killed, to derive fifteen triggers from. Nothing
        #: downstream wanted the messages, so none are kept.
        self._window = Window(settings=self.settings, spreads=self.spreads)

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

    async def consider(self, window: Window | Sequence[Message]) -> Run | None:
        """Judge one window. Returns the run if the model was actually asked.

        Takes the accumulator the watcher fills, or a plain sequence — folded
        into one on the way in, so a caller with a list of messages (a test, a
        replay) is not obliged to build one.
        """
        if not isinstance(window, Window):
            window = _fold(window, self.settings, self.spreads)
        if not window.messages:
            return None
        triggers = window.triggers()
        if not triggers:
            # At INFO, and saying how close it came. This was DEBUG and said
            # only that nothing crossed, which production never printed — so a
            # gate declining correctly every thirty minutes was indistinguishable
            # from an agent loop that had never run at all.
            log.info("no wake: %s", window.quiet())
            return None

        log.info("%d message(s) -> %s", window.messages, "; ".join(t.reason for t in triggers))
        try:
            run = await analyse(
                prompt_for(triggers, window.seen()), role=self.role, settings=self.settings
            )
        except Exception as exc:  # a bad run must not end the watch
            log.error("analysis failed: %s", exc)
            return None
        context = {
            "triggers": [t.reason for t in triggers],
            "window_messages": window.messages,
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
                    window, self._window = (
                        self._window,
                        Window(settings=self.settings, spreads=self.spreads),
                    )
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
                # Folded in here, so the message is not retained past this line.
                self._window.add(message)


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
