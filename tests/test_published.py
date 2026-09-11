"""Every number this package publishes has to move, or somebody has to say why.

## The bug this is a gate for

`run_vol` and `pivot` were published on every level call and journalled on every
outcome, and both read **identically zero across 20,000 production outcomes**.
Nothing noticed until somebody cut by them by hand. Three separate faults with
one symptom, and the symptom is the only cheap thing about them:

* `run_vol` had **no producer**. `features_for` took it as a keyword-only
  argument defaulting to 0.0 and no call site in any revision passed one.
* `pivot`'s **producer was never reached**. `Engine.check` opened with
  `if not vol.warm: return []` against a *daily* estimate, and no bar stream
  warms a daily one, so every pivot level was skipped on the first line of
  every bar and every quote for the whole life of the formation.
* `round` was **constant by construction**. Its grid sat 2.5 volatility units
  apart against a clustering tolerance of 1.0, so every cluster held one point
  and `form`'s minimum of three dropped all of them.

A constant feature is worse than a missing one. It is fed to models that weight
it, it dilutes every distance in the kNN, and it looks like a working input in
every listing. None of the three raised, warned, or failed a test.

## Why a fixture, and why it has to be this rich

A first pass at this ran three engine-only fixtures over 970 calls and reported
ten fields with one distinct value. **Eight of the ten were the fixture.**
`hour_hold`, `hour_n` and `hour_vol_share` were frozen because `to_signal` got
`clock=None`; `liquidity_beyond_*` because `peers` was empty; `activity` and
`change_*_tf` because they are folded on in `service` and an engine-only
fixture never runs it. A fixture that cannot reach a producer reports its own
shape and calls it a finding, which is worse than not looking.

So this one drives the **service**, and carries every input a producer reads:

* three feeds at three price scales, because every published distance is
  divided by a volatility unit derived from the price;
* three venues, because `Consensus` needs `MIN_VENUES` before a bar reaches a
  series at all - a two-venue fixture warms nothing and every level feature is
  *absent* rather than constant, which reads as a pass;
* every interval in `config.INTERVALS` and `config.DRIFT_INTERVALS` and the
  coarse ones the level book draws on;
* real `open` and `volume` on every bar - the range estimators need the open,
  and `activity` is a share of this instrument's own typical volume, so a
  fixture without volume reports 1.0 forever and looks dead;
* quotes as well as bars, since a touch is opened on a quote;
* a **real journal**, because `emit` is what fills `_awaiting` and `_awaiting`
  is what lets `record_outcomes` teach the session clock. With `journal=None`
  every `decide` returns "", nothing is remembered, and `hour_hold`/`hour_n`
  sit at their cold defaults;
* days of wall clock, so hour-of-day fills and the coarse series have enough
  bars for an origin.

## Slow is not dead

Nine macro features were called dead on 2026-09-11 and every one carried real,
moving values. `macro_us_core_inflation` is published **monthly**, so it is
constant in any window shorter than a month and will always look dead in one.
Nothing here is allowed onto the list below because it happened to be flat;
each entry names the reason, and "it did not move in my window" is not one.

## The allow-list

An entry with no reason is how this bug comes back. Every key in `ALLOWED`
carries why the field cannot vary *in a fixture* - never why it does not vary
in production, which is the finding rather than the excuse.
"""

from __future__ import annotations

import math
import random
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from till_infinity.shared import liveness

# ----------------------------------------------------------------- the book

#: Three price scales. Every published distance is a price divided by a
#: volatility unit derived from that price, so a one-scale fixture cannot show
#: a field that is constant only because the scale cancels.
FEEDS: tuple[tuple[str, float, float], ...] = (
    ("gold", 2400.0, 0.9),
    ("eurusd", 1.0850, 0.30),
    ("btcusd", 62_000.0, 2.4),
)

#: `Consensus` needs `MIN_VENUES` (3) before a bar reaches a series at all.
VENUES: tuple[str, ...] = ("OANDA", "FXCM", "PEPPERSTONE")

#: The union of `config.INTERVALS` and `config.DRIFT_INTERVALS`, plus the
#: coarse ones the level book draws on. 1w is left out: a week of bars needs
#: months of fixture, and nothing published is 1w-only.
INTERVALS: tuple[str, ...] = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d")

#: Minutes per interval, for cutting the minute path into bars.
STEP: dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "1d": 1440,
}

#: How long the synthetic book runs, in days.
#:
#: Two and a half rather than one, and the half is load-bearing: the swing box
#: is anchored to 4h (`level_range.ANCHOR`) and `_origin_at` refuses a series
#: shorter than twelve bars, so `swing_range_*` and `swing_room_*` cannot exist
#: before 48 hours of 4h bars. A one-day fixture publishes none of them and
#: they would have to be allow-listed as unreachable - which would be six
#: entries excusing the fixture rather than testing the code.
DAYS = 2.5

#: A quote every other minute rather than every minute. Quotes are the
#: expensive half - each one runs `check` against every interval this feed has
#: levels at - and halving them halves the runtime while still opening and
#: resolving thousands of touches.
QUOTE_EVERY = 2

#: A Monday, so the session clock sees weekdays and `Engine.trading` does not
#: refuse every touch. A fixture that starts on a Saturday opens no touches at
#: all, and every level feature is then absent rather than constant - which
#: reads as a pass.
START = 1_788_508_800


def path(price: float, vol_bps: float, minutes: int, rand: random.Random) -> list[float]:
    """A minute path that keeps returning to the same prices.

    Mean-reverting to a *ladder* rather than to one level, and on purpose: a
    pure random walk touches a level once and leaves, so no level ever
    accumulates the history that `record_hold`, `sweep_rate`, `wick_n` and the
    kNN's neighbours are all counted from - and every one of those would read
    zero for want of a market rather than for want of a producer.
    """
    unit = price * vol_bps / 10_000.0
    base = price
    rungs = [base * (1.0 + k * 0.004) for k in (-3, -2, -1, 0, 1, 2, 3)]
    out, here = [], price
    for i in range(minutes):
        # A 3% step every two hours, alternating sign. `change_up_tf` and
        # `change_down_tf` count two **separate** `Focus` detectors and
        # `changing()` only counts a firing inside `CHANGE_WINDOW` - one hour -
        # so a gentle path fires each of them a handful of times across days
        # and almost no call lands near one. Measured while tuning this: a 1.2%
        # step every six hours left `change_up_tf` at zero on all 879 published
        # calls, which is a fixture artefact that looks exactly like a detector
        # wired up one way. At 3% every two hours it is 32 up and 34 down in
        # 226 calls - the symmetry is the part that matters.
        if i and i % 120 == 0:
            base *= 1.0 + (0.03 if (i // 120) % 2 else -0.03)
            rungs = [base * (1.0 + k * 0.004) for k in (-3, -2, -1, 0, 1, 2, 3)]
        # A slow tide on top, so the ladder is visited in several regimes
        # rather than at one volatility - `regime` and `vol_stretch` have
        # nothing to separate otherwise.
        tide = math.sin(i / 900.0) * unit * 6.0
        target = min(rungs, key=lambda r: abs(r + tide - here))
        here += (target + tide - here) * 0.02 + rand.gauss(0.0, unit)
        out.append(here)
    return out


def bars(feed: str, closes: Sequence[float], rand: random.Random) -> Iterator[dict]:
    """Every interval's bars and the quotes between them, in time order.

    The wick has a **floor in volatility units**, which is not cosmetic. A 1m
    bar is one close, so `max(block) == min(block)` and a wick proportional to
    the block's range is exactly zero. The engine then warns that the series
    "carries no high/low" and forms every 1m level from closes alone - and a
    fixture in that state cannot move `wick_below_vol`, `wick_above_vol`,
    `wick_n`, `sweep_low` or `sweep_high`, so all five would read as dead code.
    """
    scale = abs(closes[0]) if closes else 1.0
    floor = scale * 3e-4
    for i, close in enumerate(closes):
        when = START + i * 60
        # Busier in the European and US hours, so `activity`, `hour_vol_share`
        # and the session clock all have something to separate.
        hour = (when // 3600) % 24
        busy = 1.0 + 1.6 * math.exp(-(((hour - 14) / 5.0) ** 2))
        for interval in INTERVALS:
            step = STEP[interval]
            if (i + 1) % step or i + 1 < step:
                continue
            block = closes[i + 1 - step : i + 1]
            opened = closes[i - step] if i >= step else block[0]
            high, low = max(block), min(block)
            wick = (high - low) * 0.25 + abs(rand.gauss(0.0, floor))
            for venue in VENUES:
                drift = rand.gauss(0.0, floor * 0.05)
                yield {
                    "topic": "bars",
                    "feed": feed,
                    "venue": venue,
                    "interval": interval,
                    "time": when - (step - 1) * 60,
                    "open": opened + drift,
                    "high": high + wick + drift,
                    "low": low - wick + drift,
                    "close": close + drift,
                    "volume": round(busy * step * (80.0 + rand.random() * 40.0), 2),
                }
        if i % QUOTE_EVERY:
            continue
        for venue in VENUES[:2]:
            yield {
                "topic": "quotes",
                "feed": feed,
                "venue": venue,
                "mid": close * (1.0 + rand.gauss(0.0, 2e-6)),
                "spread_bps": round(1.2 + abs(rand.gauss(0.0, 0.6)), 3),
                "time": float(when),
            }


def stream(days: float = DAYS, seed: int = 11) -> list[dict]:
    """The whole synthetic book, in time order across every feed."""
    rand = random.Random(seed)
    minutes = int(days * 1440)
    out: list[dict] = []
    for feed, price, vol_bps in FEEDS:
        out.extend(bars(feed, path(price, vol_bps, minutes, rand), rand))
    out.sort(key=lambda m: (m["time"], m["topic"] == "quotes"))
    return out


async def drive(days: float = DAYS, seed: int = 11) -> dict:
    """Run the service over the synthetic book and collect what it published.

    The service and not the engine. `activity`, `hour_vol_share`, `drawn_by_n`,
    `break_probability`, `up_first`, the range features and every macro field
    are folded on at the publish site, and an engine-only fixture reaches none
    of them.
    """
    from till_infinity.bus import BARS, QUOTES, Bus, Message
    from till_infinity.journal import Journal
    from till_infinity.structures import config as sx
    from till_infinity.structures.service import Watcher

    published: list[dict] = []
    resolved: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        book = Journal(Path(tmp) / "journal.db")
        await book.open()
        watcher = Watcher(Bus(), settings=sx.Settings(macro=False), journal=book)
        try:
            for payload in stream(days, seed):
                topic = BARS if payload["topic"] == "bars" else QUOTES
                plain = {k: v for k, v in payload.items() if k != "topic"}
                signals = await watcher.handle(Message(topic=topic, payload=plain))
                # Every signal, not only the ones `emit`'s cooldown lets
                # through: the question is what the *producers* put on a call,
                # and a per-instrument cooldown is a publishing policy rather
                # than a feature.
                published.extend({"score": s.score, **(s.features or {})} for s in signals)
                await watcher.emit(signals)
                # Snapshot before draining. `record_outcomes` is what teaches
                # `breaks`, the session clock and the benchmark, and it empties
                # the queue on the way past.
                pending = list(watcher.engine._resolved)
                await watcher.record_outcomes()
                resolved.extend(
                    {
                        k: v
                        for k, v in touch.features.to_dict().items()
                        if isinstance(v, int | float) and not isinstance(v, bool)
                    }
                    for _level, touch in pending
                )
        finally:
            await book.close()
    return {"published": published, "resolved": resolved, "watcher": watcher}


@pytest.fixture(scope="module")
def book():
    """One run of the book, shared. It takes about a minute; two would be two."""
    import asyncio

    return asyncio.run(drive())


# ------------------------------------------------------------ the allow-list

#: Rows a field needs before this has an opinion about it.
#:
#: One observation is not a distribution. `swing_range_width_vol` needs origins
#: on both sides of price and a trending stretch legitimately has open air on
#: one, so on some seeds it is published two or three times - and a survey of
#: three rows reports "constant" for a field that is simply unmeasured. Those
#: two want different answers, so the floor separates them and the richness
#: test below reports whatever falls under it rather than letting it vanish.
MIN_ROWS = 25


def judged(rows: Sequence[dict]) -> dict[str, liveness.Reading]:
    """Every numeric field with enough rows behind it to be judged."""
    return {
        name: reading for name, reading in liveness.survey(rows).items() if reading.seen >= MIN_ROWS
    }


#: Published fields that cannot vary **in a fixture**, and why.
#:
#: The reason must be a property of the fixture, not of production. "It did not
#: move in my window" is the finding, not the excuse - see the module docstring
#: on `macro_us_core_inflation`.
ALLOWED: dict[str, str] = {
    "neighbours": (
        "the kNN returns DEFAULT_K = 12 whenever it is warm, and it pools across "
        "instruments so it is warm almost immediately. Measured in production: 12 on "
        "19,992 of 20,000 calls. Genuinely near-constant rather than a fixture "
        "artefact, and already recorded as the sixth entry in research/inert.md - "
        "the `actionable` gate that has never rejected anything. Listed so this gate "
        "stays green on a known finding instead of being switched off."
    ),
}

#: kNN features that cannot vary **in a fixture**, and why. Kept apart from
#: `ALLOWED` because the thirteen numbers the neighbour search compares on are
#: a different population from what a signal publishes, and an excuse that
#: holds for one need not hold for the other.
ALLOWED_KNN: dict[str, str] = {
    "pivot": (
        "1.0 for a level drawn from a session pivot, 0.0 for a swing level. "
        "`pivots.PERIODS` is daily and weekly, so an instrument acquires a pivot set "
        "at most once a day and never a weekly one inside a fixture - and whether "
        "price then returns to one of ten prices is a coincidence. Measured across "
        "four seeds at 2.5 days: alive on two, constant on one, 99.1% on one value "
        "on the fourth. "
        "That is rarity, not deadness, and the fault it is guarding against was "
        "neither: pivot levels were *drawn and never checked*, because "
        "`Engine.check` opened on a daily volatility estimate that no bar stream "
        "warms. `test_every_level_bucket_has_a_volatility_that_warms` asserts that "
        "directly and deterministically, which is the assertion that bug fails."
    ),
}

#: Field prefixes this fixture cannot reach at all, and why.
#:
#: **Absence is a different fault from constancy**, and it is the one no survey
#: can see: `liveness.survey` reports the keys it was handed, so a field that
#: stopped being written vanishes rather than reading zero. That is precisely
#: how four origin fields were lost for four days while a live strategy went on
#: asking for them.
#:
#: This is asserted rather than merely written down - see
#: `test_the_fields_this_fixture_cannot_reach_are_still_the_ones_documented`.
#: A note about what is missing is worth nothing if it is not checked, which is
#: the whole subject of research/inert.md.
ABSENT: dict[str, str] = {
    "macro_": (
        "every macro feature comes from `Macro.features`, which reads the news "
        "service's database. There is no news service in a fixture, so the sixteen "
        "keys are absent rather than constant. Their liveness is a question for the "
        "journal, and the journal's answer is that they are slow, not dead: over an "
        "11.8-day sample `macro_dollar` takes 3 values, `macro_us_real_yield` 6 and "
        "`macro_carry_gap` 27."
    ),
    "learned_": (
        "`_learned_at` returns {} until the volatility learner is warm, and the "
        "learner is off by default - see `config.vol_learner` and "
        "`STRUCTURES_VOL_LEARNER`."
    ),
}


# ------------------------------------------------------------------ the gate


def test_no_published_feature_is_constant(book):
    """A published number that never moves is a dead input wearing a live name.

    This is the assertion the three faults in the docstring would all have
    failed, and none of the tests that existed at the time did.
    """
    dead = {
        name: reading.describe()
        for name, reading in judged(book["published"]).items()
        if reading.constant is not None and name not in ALLOWED
    }
    assert not dead, (
        "these published features are constant across the fixture, which drives "
        f"every producer: {dead}. Either the producer is broken or the field belongs "
        "in ALLOWED with the reason it cannot vary here."
    )


def test_no_published_feature_is_near_constant(book):
    """Alive by the letter is the shape a field takes while it is dying.

    Separate from the constant check because it needs a different answer: a
    field on one value in 99% of rows still varies, so nothing raises and no
    survey calls it dead, and it carries about as much as one that does not.
    """
    dying = {
        name: reading.describe()
        for name, reading in judged(book["published"]).items()
        if reading.near_constant and name not in ALLOWED
    }
    assert not dying, f"these published features are near-constant: {dying}"


def test_no_knn_feature_is_constant(book):
    """The thirteen numbers the neighbour search actually compares on.

    A constant here is worse than a constant on the signal: it is a dimension
    of a distance metric that contributes nothing to the distance while every
    other dimension is divided by one more axis.
    """
    dead = {
        name: reading.describe()
        for name, reading in judged(book["resolved"]).items()
        if (reading.constant is not None or reading.near_constant) and name not in ALLOWED_KNN
    }
    assert not dead, f"these kNN features carry nothing across resolved touches: {dead}"


def test_the_fixture_is_rich_enough_for_a_pass_to_mean_anything(book):
    """A gate that can pass by producing nothing is not a gate.

    Every fault in the docstring produced a *legal* value, and so does an empty
    fixture: no calls, no fields, nothing constant, green. These are the floors
    under which the three tests above are vacuous, and they are deliberately
    specific - "some calls happened" would be satisfied by a fixture that had
    stopped exercising nine tenths of the package.
    """
    watcher = book["watcher"]
    published, resolved = book["published"], book["resolved"]

    assert len(published) >= 200, f"only {len(published)} published calls"
    assert len(resolved) >= 500, f"only {len(resolved)} resolved touches"

    fields = judged(published)
    thin = {
        name: reading.seen
        for name, reading in liveness.survey(published).items()
        if reading.seen < MIN_ROWS
    }
    assert len(fields) >= 60, (
        f"only {len(fields)} numeric fields published often enough to judge "
        f"(needs {MIN_ROWS} rows); under the floor: {thin}"
    )

    # Every configured formation drew at least one level. `round` shipped for
    # its whole life unable to form one, and nothing said so - a pass that
    # draws nothing is silence, not a neutral choice.
    drew: set[str] = set()
    for found in watcher.engine._levels.values():
        for level in found:
            drew.update(part.partition(":")[0] for part in str(level.origin).split("+") if part)
    missing = [name for name in watcher.engine.passes if name not in drew]
    assert not missing, f"these formation passes drew no levels at all: {missing}"

    # The three inputs an engine-only fixture cannot supply, asserted directly
    # rather than inferred from the fields they feed - eight of the ten fields
    # a first pass reported as dead were exactly this.
    assert any(row.get("hour_n", 0.0) > 0 for row in published), "the session clock never learned"
    assert any(row.get("liquidity_beyond_n", 0.0) > 0 for row in published), "no peers were passed"
    assert any(row.get("activity", 1.0) != 1.0 for row in published), "no volume reached activity"

    # And the swing box, which is anchored to 4h (`level_range.ANCHOR`) and is
    # the reason DAYS is 2.5: `_origin_at` refuses a series shorter than twelve
    # bars, so no 4h origin can exist before 48 hours of them.
    #
    # Any `swing_` reading, not `swing_range_width_vol` specifically. The width
    # needs origins on **both** sides and a trending stretch legitimately has
    # open air on one - `LevelRange.features` omits an absent bound rather than
    # zeroing it, which is the correct behaviour and not something to assert
    # against.
    assert any(any(key.startswith("swing_") for key in row) for row in published), (
        "no 4h origin box was published - the fixture is too short for ANCHOR"
    )


def test_the_fields_this_fixture_cannot_reach_are_still_the_ones_documented(book):
    """`ABSENT` has to be true, or it is a comment pretending to be a check.

    Two directions, and the second is the one that matters. If a documented
    prefix starts appearing, the note is stale and should be deleted rather
    than left to be believed. If a prefix stops appearing that is not
    documented, a producer has gone quiet in exactly the way this whole module
    exists to catch - and no survey of the published rows would say so, because
    a survey can only report keys it was given.
    """
    seen = {key for row in book["published"] for key in row}
    stale = [prefix for prefix in ABSENT if any(key.startswith(prefix) for key in seen)]
    assert not stale, (
        f"these prefixes are documented in ABSENT as unreachable and are being "
        f"published after all: {stale}. Delete the entry rather than leaving it."
    )


def test_every_level_bucket_has_a_volatility_that_warms(book):
    """A level nothing can price is a level nothing will ever check.

    This is the pivot fault, stated as a property rather than as a symptom.
    `Engine.check` opens with `if not vol.warm: return []`, and it asked
    `vol.of(feed, interval)` where `interval` is the bucket's key. Pivot levels
    live under their **session period** - "daily" - and there is no daily bar
    stream to warm a daily estimate, so every pivot level was skipped on the
    first line of every bar and every quote for the whole life of the
    formation, and `pivot` read zero on 20,000 outcomes.

    Asserted on the bucket rather than on the feature because the feature is a
    rare-event flag whose variation needs luck, while this needs none: it is
    true or false the moment the levels exist. `Engine.vol_for` is the fix and
    this is what says so.
    """
    engine = book["watcher"].engine
    buckets = sorted({(feed, name) for (feed, name), found in engine._levels.items() if found})
    assert buckets, "the fixture drew no levels at all"

    cold = [f"{feed}/{name}" for feed, name in buckets if not engine.vol_for(feed, name).warm]
    assert not cold, (
        f"these level buckets hold levels that `check` can never price, so every "
        f"level in them is skipped on its first line: {cold}"
    )
    # And the session buckets specifically, so a fixture that stopped producing
    # them cannot make this pass by having nothing to check.
    sessions = [name for _feed, name in buckets if name not in INTERVALS]
    assert sessions, "no session bucket was formed - the pivot path is untested"


def test_the_break_model_is_scored_on_the_touch_and_not_on_zeros(book):
    """`Call.features`, and the `getattr` that could never find it.

    `service._level_calls` scores the break model with
    `getattr(call, "features", None) or {}`. `Call` is a slotted dataclass, so
    until it carried a `features` field the attribute could never be set and
    the `or {}` fired on every call ever made - `Breaks.inputs` read six
    missing keys as zeros and the model scored **one input vector** for every
    level on every instrument.

    It did not read as a dead field, which is why nothing caught it: a constant
    input through a continuously-learning model produces a number that varies
    plausibly and says nothing about the call. Asserted on the input rather
    than on the output, because the output was never the tell.
    """
    from till_infinity.structures.engine import Call
    from till_infinity.structures.learning.breaking import Breaks

    assert "features" in Call.__slots__, "Call cannot carry the features it is scored from"

    seen: list[object] = []
    original = Breaks.reading
    Breaks.reading = lambda self, features: (seen.append(features), original(self, features))[1]
    try:
        import asyncio

        asyncio.run(drive(days=0.5, seed=5))
    finally:
        Breaks.reading = original

    assert seen, "the break model was never asked for a reading"
    vectors = {tuple(Breaks.inputs(features)) for features in seen}
    assert len(vectors) > 1, (
        f"the break model saw {len(vectors)} distinct input vector(s) across {len(seen)} "
        "calls - it is being scored on something that is not the touch"
    )


def test_the_origin_bracket_carries_the_zone_its_edge_came_from(book):
    """Four fields lost their producer on 2026-09-07 and two consumers did not.

    `_origin_at` chose the bracketing bounds from a list of bare floats, which
    threw away which origin each came from. `origin_above_high`,
    `origin_above_revisits`, `origin_below_low` and `origin_below_revisits`
    stopped being published, and `trading/strategies/swing.py` went on reading
    all four: `OriginSwing._anchored_stop` falls back to the level-anchored
    stop without the far edge - the exact placement that commit was written to
    correct - and its `max_revisits` staleness gate reads a count that is never
    there, so it can never refuse anything.

    Absent, not constant, so no survey of the published rows could have seen
    it. This asserts presence.
    """
    published = book["published"]
    for name in (
        "origin_above_high",
        "origin_above_revisits",
        "origin_below_low",
        "origin_below_revisits",
    ):
        seen = [row[name] for row in published if name in row]
        assert seen, f"{name} is published by nothing, and swing.py reads it"
        assert len(set(seen)) > 1, f"{name} is present but constant across {len(seen)} calls"
