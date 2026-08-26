"""Watching the bus and deciding when to wake the model.

The bus carries tens of quotes a second; a model call takes seconds and costs
money. Something has to absorb that difference, and a queue is the wrong shape
- by the time a backlog drained, the market would have moved on. So messages
are gathered into a window and the window is judged as a whole.

Two gates stand between a quote and an API call:

1. `interesting()` - arithmetic, not a model. A spread inside its normal range
   and a calendar with nothing high-impact in it never cost a token.
2. The analyst itself, which is told plainly that returning no findings is a
   correct answer.

The first gate does **not** decide what is unusual by comparing against a
constant. `structures` already answers that question properly - calibrated,
per-venue, self-tuning - and a threshold here would be a worse duplicate of it,
wrong for every instrument but whichever one it was chosen on. A signal from
`structures` is therefore a trigger on its own.

The quote gate that remains is a fallback for when `structures` is not running,
and it is self-calibrating: a running quantile of the spreads actually seen at
each venue, so "wide" means wide for that venue rather than wide against a
number somebody picked.

Headlines are gated the same way and for the same reason. A headline is worth
waking a model for when there is more news about an instrument than usual, and
"usual" is per instrument - three hundred btc headlines a week against five for
usdchf. See `Headlines`.

What survives both is published to `alerts`, which `notify listen` delivers.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
from collections import Counter, OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ..bus import ALERTS, ARTICLES, BARS, EVENTS, QUOTES, SIGNALS, Bus, Message
from ..journal import Journal, decide, observe
from ..logging import get_logger
from ..news.symbols import feeds_for
from . import data
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
#: A quantile alone is degenerate on a steady venue - if every reading is 20bps
#: then the 99th percentile is 20bps and 20.1 clears it, so a hair above normal
#: would wake a model. The multiple is what makes "wide" mean wide.
SPREAD_MULTIPLE = 1.5

#: Triggers handed to the analyst in one window.
#:
#: Not a cost control so much as a shape control: the model investigates what
#: it is given, so the tool calls it makes scale with this number, and the
#: number scales with how many instruments are tracked. Fourteen instruments
#: across six venues produced forty-two tool calls against a limit of
#: thirty-two, having produced fourteen against twelve a fortnight earlier -
#: raising the limit each time is chasing rather than fixing.
#:
#: Deduplicating per instrument does most of the work: one dislocation seen at
#: four venues is one instrument dislocating. This is the backstop for a window
#: where genuinely many instruments move at once, which is exactly the window
#: worth analysing and the worst one to hand over whole.
MAX_TRIGGERS = 10

#: How long a headline counts as recent when judging whether the flow about an
#: instrument has picked up.
NEWS_WINDOW = 600.0

#: How improbable that many headlines must be, against the feed's own rate,
#: before one is worth waking a model for. Replaying the last seven days of the
#: corpus through the real gate, this wakes the analyst **12.0 times a day**
#: across every tracked instrument; 0.02 gives 20.1 and 0.005 gives 7.6.
NEWS_ALPHA = 0.01

#: How long a feed's arrival rate remembers. Three days, which is short for a
#: rate estimate and deliberate: the thing being estimated moves. Adding the
#: crypto sources multiplied btc's headline volume roughly tenfold inside a
#: week, and a rate still carrying the old number read that as news - **34.9
#: windows a day** on the same replay that a three-day constant answers with
#: 12.0. Seven days gets 18.3 of the way there.
#:
#: The system keeps gaining instruments and sources, so this is not a one-off
#: to be waited out. It is the normal condition.
NEWS_TAU = 3 * 86400.0

#: How much a feed's rate is pulled toward the average feed's, as a fraction of
#: its own evidence. A quarter is weak - a feed with any history of its own
#: barely moves - and it exists to give a feed with *no* history something
#: better than zero, which would make its first headline infinitely surprising.
#:
#: This replaces a per-feed warmup count, which was the same idea done badly:
#: it left exactly the feeds worth hearing about deaf, since usdchf runs at five
#: headlines a week and needed eleven days to clear it. Shrinking has no cliff.
#:
#: It changes nothing on the replay - every feed there has history of its own -
#: and that is the point. It exists for the feed that does not: an instrument
#: added yesterday, or the first run after the news store is lost.
NEWS_PRIOR = 0.25

#: Arrivals *across all feeds* before the rates are trusted at all. Below this
#: the gate asks for two headlines in the window rather than reasoning from a
#: rate it cannot yet estimate.
#:
#: Pooled rather than per feed on purpose. The cold start this guards is the
#: whole gate having no history - a missing news store, a first run - and that
#: clears in hours at the rate headlines actually arrive. A per-feed version
#: would take weeks to clear for the quiet feeds and would be silently gating
#: the ones it is least safe to gate.
NEWS_WARMUP = 30

#: Arrivals kept per feed for the count. Only those inside `NEWS_WINDOW` are
#: counted, so this is a memory bound rather than a parameter.
NEWS_MEMORY = 64

#: Days of headline history read at startup to prime the rates. Comfortably
#: more than `NEWS_TAU`, past which an arrival counts for almost nothing.
NEWS_HISTORY = 14


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
        to place a quantile - a percentile from six observations would be worse
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


class Headlines:
    """How much is normally written about an instrument, and when that changes.

    A headline is worth waking a model for when there is more of it than usual
    - and "usual" differs by two orders of magnitude across the instruments
    tracked. Over seven days: **300 headlines about btc and five about usdchf**.
    A gate that fired on every routed headline would be 90 model calls a day,
    almost half of them btc doing nothing but being btc; one that demanded a
    burst would never hear about usdchf at all, which is the instrument a
    headline is most informative about precisely because it is so rarely
    mentioned.

    So the comparison is per feed, against that feed's own arrival rate - the
    same argument the spread gate makes about venues. Treating arrivals as
    Poisson, the question is how unlikely this many headlines in ten minutes
    would be at the rate this feed normally runs at. A lone usdchf headline
    sits right at the threshold and clears it whenever the feed has been
    quieter than its average - three times over the replay week - while btc
    needs a cluster before it means anything.

    ## The rate has to move

    An average over all of history was the first attempt and it was wrong in a
    way worth recording. Adding the crypto sources multiplied btc's headline
    volume roughly tenfold inside a week; the all-time rate still carried the
    old number, so the gate read the collection change as news and fired on
    **34.9 windows a day**, most of them btc. The rate is therefore a decaying
    count with a three-day constant - recent arrivals count fully, a week-old
    one barely - which brings the same replay to 10.3/day.

    Rates are also shrunk toward the average feed's, weakly. A feed with no
    history of its own would otherwise have a rate of zero, under which its
    first headline is infinitely surprising. Toward the *median* feed rather
    than the mean, which btc's volume alone would otherwise define.

    ## What this cannot see

    Nothing about the *time of day*: Asian hours are quieter than the New York
    open, and the gate will be a little eager in a busy session and a little
    deaf in a dead one. Modelling that is a bigger change than the size of the
    effect justifies at ten wakes a day.

    Nor anything about what a headline *says*. This measures how much is being
    written, not whether it matters, which is deliberate - judging the content
    is the analyst's job, and it is the thing being woken.
    """

    def __init__(
        self,
        window: float = NEWS_WINDOW,
        alpha: float = NEWS_ALPHA,
        tau: float = NEWS_TAU,
        prior: float = NEWS_PRIOR,
        warmup: int = NEWS_WARMUP,
        memory: int = NEWS_MEMORY,
    ) -> None:
        self.window = window
        self.alpha = alpha
        self.tau = tau
        self.prior = prior
        self.warmup = warmup
        self.memory = memory
        #: Arrival times inside `window`, for the count.
        self._seen: dict[str, list[float]] = {}
        #: The decaying arrival count per feed, and when it was last decayed.
        #: Kept apart from `_seen` because it spans days rather than minutes.
        self._rate: dict[str, float] = {}
        self._last: dict[str, float] = {}

    def observe(self, feed: str, when: float) -> None:
        seen = self._seen.setdefault(feed, [])
        seen.append(when)
        if len(seen) > self.memory:
            del seen[: len(seen) - self.memory]
        # Decay to now, then count this arrival. `max(..., 0.0)` because
        # `published` is the publisher's clock and runs backwards between
        # sources; a negative gap would turn the decay into growth.
        elapsed = max(when - self._last.get(feed, when), 0.0)
        self._rate[feed] = self._rate.get(feed, 0.0) * math.exp(-elapsed / self.tau) + 1.0
        self._last[feed] = max(when, self._last.get(feed, when))

    def unusual(self, feed: str, when: float) -> bool:
        """Whether the flow about this feed has picked up, for this feed."""
        return self._surprise(feed, when) <= self.alpha

    def _surprise(self, feed: str, when: float) -> float:
        """How unlikely this much news about this feed is. Lower is stranger.

        Separate from `unusual` so the threshold can be seen rather than only
        its verdict - the interesting cases here sit within a factor of two of
        it, and a bare True/False hides that.
        """
        recent = sum(1 for at in self._seen.get(feed, ()) if when - at < self.window)
        if not recent:
            return 1.0
        if sum(self._rate.values()) < self.warmup:
            # Two in ten minutes. Conservative, and deliberately so: the
            # alternative while nothing is known is to treat a first-ever
            # headline as a surprise, which it is not - it is a cold start.
            return 0.0 if recent >= 2 else 1.0
        # Shrunk toward the typical feed, so one with no history of its own is
        # treated as ordinary rather than as silent.
        #
        # The **median**, not the mean. btc carries sixty times usdchf's volume,
        # and a mean is that one feed's rate wearing everyone else's name - it
        # pulled usdchf's estimate up by a factor of seven, which is exactly the
        # feed the shrinkage exists to protect.
        ordered = sorted(self._rate.values())
        pooled = ordered[len(ordered) // 2]
        shrunk = (self._rate.get(feed, 0.0) + self.prior * pooled) / (1.0 + self.prior)
        expected = (shrunk / self.tau) * self.window
        return _poisson_tail(recent, expected)


def because(error: BaseException, depth: int = 0) -> str:
    """Why it actually failed, rather than how many ways it did.

    A fallback model raises an `ExceptionGroup`, and `str()` on one of those is
    **"All models from FallbackModel failed (2 sub-exceptions)"** - a sentence
    with no information in it. Production logged exactly that twenty-six times
    in a day while both models answered a direct call perfectly, and finding
    out why meant reproducing it by hand on the box.

    So the group is unwrapped, and so is the `__cause__` chain underneath it,
    because the useful line is usually the one furthest in: a rate limit, a
    token ceiling, a decommissioned model name.
    """
    label = type(error).__name__
    inner = getattr(error, "exceptions", ())
    if inner and depth < 3:
        return f"{label}[" + "; ".join(because(sub, depth + 1) for sub in inner) + "]"
    text = str(error).strip() or label
    cause = error.__cause__
    if cause is not None and depth < 3:
        return f"{label}: {text} <- {because(cause, depth + 1)}"
    return f"{label}: {text}"


def _poisson_tail(count: int, expected: float) -> float:
    """P(X >= count) for X ~ Poisson(expected).

    Summed from the bottom rather than evaluated term by term, so it holds up
    at the small rates most feeds run at without ever computing a factorial.
    """
    if count <= 0:
        return 1.0
    term = math.exp(-expected)
    below = term
    for k in range(1, count):
        term *= expected / k
        below += term
    return max(0.0, 1.0 - below)


@dataclass(slots=True)
class Window:
    """What a window of bus traffic amounts to, folded in as it arrives.

    The list this replaces held every message until the window elapsed -
    101,297 of them, 199MB, to derive fifteen triggers. Nothing downstream
    ever wanted the messages: `interesting` reduces them to the widest spread,
    the loudest signal per instrument and the releases that printed, and
    `prompt_for` wants counts. All of that is computable one message at a time,
    so none of it needs keeping.

    Bounding the list was the stopgap; this removes the question. Memory is now
    proportional to the number of *instruments*, not to the traffic, so a busy
    session costs no more than a quiet one - and the spread spike that a bound
    could drop from the front of a full window can no longer be lost.

    One accumulator, used by both paths: `interesting()` folds a sequence into
    it and asks the same questions the watcher asks live, so the two cannot
    drift.
    """

    settings: Settings
    spreads: Spreads | None = None
    headlines: Headlines | None = None
    messages: int = 0
    quotes: int = 0
    events: int = 0
    unreleased: int = 0
    articles: int = 0
    #: Headlines that named an instrument we actually price. The rest cannot be
    #: joined to anything, so they are counted and dropped.
    routed: int = 0
    topics: Counter = field(default_factory=Counter)
    #: The strongest signal per instrument. One dislocation seen at four venues
    #: is one instrument dislocating, not four findings.
    loudest: dict[str, tuple[float, Trigger]] = field(default_factory=dict)
    #: Releases that actually printed and cleared the importance floor.
    releases: list[Trigger] = field(default_factory=list)
    #: One headline per instrument, for the instruments whose news flow picked
    #: up. Per feed for the same reason `loudest` is: four outlets writing about
    #: one instrument is one story, not four.
    stories: dict[str, Trigger] = field(default_factory=dict)
    #: The widest spread that was unusual *for its venue*, and the widest seen
    #: at all - the second is for explaining a decline, not for triggering.
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
        elif message.topic == ARTICLES:
            self._article(payload)

    def _signal(self, payload: dict) -> None:
        # A signal has already cleared the numeric layer's own guards, so it
        # needs no second arithmetic gate - it arrives *because* something
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

    def _article(self, payload: dict) -> None:
        """A headline, kept only if it names something we price and is unusual.

        Publishers tag articles `VENUE:TICKER`; `news.symbols` maps that onto a
        feed using the symbols `prices` already collects. Of 3,058 articles 44%
        carry tags at all and 60% of those name a tracked instrument, so most
        of what arrives is counted here and goes no further - correctly, since
        a headline about `XRPUSD` or `DXY` cannot be joined to anything we hold.
        """
        self.articles += 1
        feeds = feeds_for(payload.get("symbols"))
        if not feeds:
            return
        self.routed += 1
        if self.headlines is None:
            return
        # `published` is when the publisher says it ran, which for a backfilled
        # feed can be days old; arrival is what the gate is about.
        when = float(payload.get("published") or 0.0) or time.time()
        for feed in feeds:
            self.headlines.observe(feed, when)
        for feed in feeds:
            if not self.headlines.unusual(feed, when):
                continue
            title = str(payload.get("title") or "").strip()
            provider = str(payload.get("provider") or payload.get("source") or "").strip()
            self.stories[feed] = Trigger(
                reason=f"{feed}: news flow picked up - {provider} “{title}”".strip(),
                topic=ARTICLES,
                payload={**payload, "feed": feed},
            )

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
        # Last, so the cap sheds a headline before it sheds a measurement. A
        # story is the softest evidence here - prose about an instrument rather
        # than the instrument doing something - and its value is in waking the
        # analyst when nothing else would, not in competing with a dislocation
        # for a place in a crowded window.
        found += [self.stories[feed] for feed in sorted(self.stories)]
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
            articles=self.articles,
            routed=self.routed,
        )

    def seen(self) -> str:
        """What arrived, for the prompt - counts rather than the messages."""
        return ", ".join(f"{n} {topic}" for topic, n in sorted(self.topics.items())) or "nothing"


def interesting(
    messages: Sequence[Message],
    settings: Settings,
    spreads: Spreads | None = None,
    headlines: Headlines | None = None,
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
    return _fold(messages, settings, spreads, headlines).triggers()


def why_quiet(
    messages: Sequence[Message],
    settings: Settings,
    spreads: Spreads | None = None,
    headlines: Headlines | None = None,
) -> Quiet:
    """Summarise a window that woke nobody, so the silence can be read."""
    return _fold(messages, settings, spreads, headlines).quiet()


def _fold(
    messages: Sequence[Message],
    settings: Settings,
    spreads: Spreads | None = None,
    headlines: Headlines | None = None,
) -> Window:
    window = Window(settings=settings, spreads=spreads, headlines=headlines)
    for message in messages:
        window.add(message)
    return window


@dataclass(slots=True)
class Quiet:
    """How close a window came, for a window that crossed nothing.

    Exists because a gate that never fires and a gate that never runs look
    identical from outside, and this one looked like the second for seven hours
    - the whole log held a single `agents started` line. It was in fact the
    first, declining correctly and saying so only at DEBUG, which production
    does not print.

    Reporting the *closest approach* rather than the fact of declining is what
    makes it useful: "nothing crossed" is unfalsifiable, while "widest spread
    1.9bps against 8.0 needed" is a threshold someone can judge.
    """

    messages: int = 0
    quotes: int = 0
    events: int = 0
    #: The widest spread seen, and where - the near-miss on the quote gate.
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
    #: Headlines seen, and how many named an instrument we price. Both, because
    #: "forty headlines and none of them about anything we hold" is a different
    #: silence from "no news at all", and they read the same otherwise.
    articles: int = 0
    routed: int = 0

    def __str__(self) -> str:
        if not self.quotes and not self.events and not self.articles:
            return f"{self.messages} message(s), none of them a quote, a release or a headline"
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
        if self.articles:
            parts.append(
                f"{self.articles} headline(s), {self.routed} about a tracked instrument "
                "and none of them unusual for it"
                if self.routed
                else f"{self.articles} headline(s), none about a tracked instrument"
            )
        return (
            f"{self.messages} message(s) ({self.quotes} quote(s), {self.events} event(s), "
            f"{self.articles} headline(s)) and nothing crossed: " + "; ".join(parts)
        )


def prompt_for(triggers: Sequence[Trigger], seen: str | Sequence[Message]) -> str:
    """Turn a window into a question.

    The triggers are stated as what changed rather than as conclusions, and the
    model is pointed at its tools instead of being handed the data - the store
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
    times. It is the same reasoning as the news announcer - being told is only
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
        #: How much is normally written about each instrument. Held on the
        #: watcher rather than the window, because it takes days of arrivals to
        #: mean anything and a window is minutes long.
        self.headlines = Headlines()
        self._warm_headlines()
        #: Folded in as messages arrive rather than kept. This is where the
        #: memory went: a thirty-minute window over fourteen instruments held
        #: **101,297 messages - 199MB**, about half the resident size when the
        #: box was OOM-killed, to derive fifteen triggers from. Nothing
        #: downstream wanted the messages, so none are kept.
        self._window = Window(
            settings=self.settings, spreads=self.spreads, headlines=self.headlines
        )

    def _warm_headlines(self, days: int = NEWS_HISTORY) -> None:
        """Start knowing how much is normally written about each instrument.

        Without this the gate relearns every feed's rate from nothing after
        every restart, and the deploy cadence is measured in hours.

        Best effort. A missing or unreadable news store means the gate starts
        cold, which is the behaviour without this and is not worth refusing to
        start over.
        """
        try:
            arrivals = data.arrivals(self.settings.news_db, days=days)
        except Exception as error:
            log.debug("agents: no headline history to warm from (%s)", error)
            return
        warmed = 0
        for when, symbols in arrivals:
            for feed in feeds_for(symbols):
                self.headlines.observe(feed, when)
                warmed += 1
        if warmed:
            log.info("agents: headline rates warmed from %d arrival(s)", warmed)

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

        Takes the accumulator the watcher fills, or a plain sequence - folded
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
            # only that nothing crossed, which production never printed - so a
            # gate declining correctly every thirty minutes was indistinguishable
            # from an agent loop that had never run at all.
            log.info("no wake: %s", window.quiet())
            return None

        log.info("%d message(s) -> %s", window.messages, "; ".join(t.reason for t in triggers))
        try:
            run = await analyse(
                prompt_for(triggers, window.seen()),
                role=self.role,
                settings=self.settings,
                # The budget follows the work: the model investigates what it
                # is handed, so the calls it makes scale with the instruments
                # in the window. See `analyst.budget`.
                subjects=len(triggers),
            )
        except Exception as exc:  # a bad run must not end the watch
            log.error("analysis failed: %s", because(exc))
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
                        Window(
                            settings=self.settings,
                            spreads=self.spreads,
                            headlines=self.headlines,
                        ),
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
