"""Can a detector's parameters differ by side, and does it buy anything?

Two questions, two passes, and only the second is a measurement.

    uv run python research/ideas/sided_thresholds.py backtest
    uv run python research/ideas/sided_thresholds.py nulls

**backtest** is the wiring. A `BacktestEngine` over recorded 15m bars with the
real `StatespaceActor` folding and publishing proposals, the real
`StatespaceLong`/`StatespaceShort` leaves consuming them, and a CUSUM
registered through `DeskConfig.indicators` and read by the decision. Three
arms: no detector, a symmetric threshold, and a per-side pair. It reports bars,
proposals, intents, orders, every gate and what the detector read - including
the zeros, because a run that reports a number computed from no trades is the
failure this desk has on record more than any other.

**nulls** is the question that decides whether a per-side threshold ships on by
default. The answer below is no.

## What the detector reads, and what the gate does with it

`indicators.Cusum` accumulates signed progress in volatility units and fires
when one side passes its threshold. The gate here takes the **side of the last
event**, not the accumulator: a CUSUM restarts when it fires, so the strongest
case it can report reads a pressure of exactly zero, and
`momentum.Ensemble._opinion` already falls back the same way. The per-side
threshold therefore acts through the *event stream* - it decides when each side
speaks at all.

## The null, written before the result

The statistic is the **asymmetry premium**: the best cell of a k x k threshold
grid minus the best cell of its diagonal, where a cell scores the mean forward
move in the event's own direction, per event, in volatility units. Both halves
are best-of selections, so the premium isolates the part of a grid's advantage
that needs an asymmetry to exist rather than a wider search.

A premium above zero is expected under the null and says nothing: picking the
best of 36 cells beats the best of 6 by construction. So the premium is
compared against the same grid, the same detector and the same selection on

* **shuffled** - the same bars' returns block-shuffled within days, each return
  carrying its own bar's shape, so the bar geometry and the volatility
  clustering survive and the ordering does not;
* **walk** - iid normal returns at the sample standard deviation, with shapes
  drawn from the real bars.

The shuffled arm is the higher-powered one and is the one that decides, per
`shuffled-twin-names-the-mechanical-observables`.

And a **planted** arm, because a null with no power statement beside it is not
a result: a process in which an up run above a known size really is followed by
continuation and a down run is not, swept over the strength of the plant, so
the report can say where the test goes blind.

## The result, on 5,135 recorded 15m eurusd bars from Deriv

| arm | asymmetry premium | p |
|---|---|---|
| real | +0.0960 | - |
| shuffled, 40 draws | mean +0.0731, max +0.1229 | **0.244** |
| walk, 40 draws | mean +0.0394, max +0.2307 | 0.146 |

Null. And the symmetric reading is null on the same arm - best symmetric
+0.2243 real against a shuffled mean of +0.2463, p = 0.683 - while it clears
the iid walk at p = 0.024, which is the trap the shuffled arm exists to catch:
an iid walk has no volatility clustering, so its event rate and its forward
moves differ from a market's for a mechanical reason that has nothing to do
with the threshold.

Power: a planted one-sided effect of 0.25v returns a premium of +0.1050, which
is where the real reading sits, and 0.10v returns +0.0455, which is inside the
shuffled twin's own spread. So this test resolves a one-sided effect of about a
quarter of a volatility unit and is blind below a tenth of one.

## What that costs, stated rather than implied

A symmetric sweep over k thresholds is k trials; a per-side sweep is k**2,
because `Cusum.restart` zeroes *both* accumulators - raising one side's
threshold changes which events the other side fires. At k = 6 that is 30 new
cells where a month of data at a target Sharpe of 1.5 supports about one. So
the capability ships declarable and **off**: `threshold_up` and
`threshold_down` are zero, which means "use `threshold`", and a detector built
without them is the one that existed before.
"""

from __future__ import annotations

import math
import os
import pathlib
import random
import shutil
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from typing import Any, ClassVar

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

HERE = pathlib.Path(__file__).resolve().parent
STATE = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "sided-thresholds-state"
os.environ.setdefault("STATESPACE_INTERVALS", "15m")

STORE = pathlib.Path(".data/prices/prices.db")
FEED, VENUE_NAME, INTERVAL = "eurusd", "DERIV", "15m"

#: Bars of forward move a score is taken over. Eight 15m bars is two hours.
HORIZON = 8

#: Thresholds swept per side, in volatility units.
GRID = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)

#: A cell firing fewer than this many times is not scored: a mean over a
#: handful of events is the cell a best-of selection picks for free.
LEAST_EVENTS = 30

#: Bars to a day on a 15m clock, which is the shuffle block. A day, because the
#: intraday volatility cycle is day-shaped and a shorter block shuffles the
#: cycle away and calls the difference structure.
BLOCK = 96

SEED = 20261101


# ───────────────────────────────────────────────────────────── the bar source


@dataclass(frozen=True, slots=True)
class Candle:
    """One bar, as the four floats a detector reads."""

    when: float
    open: float
    high: float
    low: float
    close: float

    @property
    def typical(self) -> float:
        return (self.high + self.low + self.close) / 3.0

    @property
    def range(self) -> float:
        return self.high - self.low


def recorded() -> tuple[list[Candle], float] | None:
    """The store's own bars and the venue's own median spread, or None.

    `node/backtest.catalogue()` wants a Nautilus parquet catalogue under
    `~/till-data/catalog` and there is not one on every box. `.data/prices`
    is what the live `prices` service writes and is the fallback - read at
    `nice -n 19 ionice -c3` from the host, never through `docker exec`.
    """
    if not STORE.exists():
        return None
    db = sqlite3.connect(f"file:{STORE}?mode=ro", uri=True)
    rows = db.execute(
        "select ts, open, high, low, close from bars where feed = ? and venue = ? "
        "and interval = ? order by ts",
        (FEED, VENUE_NAME, INTERVAL),
    ).fetchall()
    spreads = [
        value
        for (value,) in db.execute(
            "select ask - bid from quotes where feed = ? and venue = ? and bid is not null "
            "and ask is not null and ask > bid",
            (FEED, VENUE_NAME),
        )
    ]
    db.close()
    if not rows or not spreads:
        return None
    return [Candle(*row) for row in rows], statistics.median(spreads)


def generated(count: int = 2_000, seed: int = SEED) -> tuple[list[Candle], float]:
    """A feed when there is no store. **Says so**, because a result off this is
    a result about a generator.

    The spread is the one real number kept from the measurement that produced
    the recorded arm: 1.2 pips, which is Deriv's median on this pair.
    """
    rng = random.Random(seed)
    base, price = 1_780_000_000.0, 1.1000
    out = []
    for i in range(count):
        close = price * math.exp(rng.gauss(0.0, 0.0004))
        high = max(price, close) * (1.0 + abs(rng.gauss(0.0, 0.0002)))
        low = min(price, close) * (1.0 - abs(rng.gauss(0.0, 0.0002)))
        out.append(Candle(base + i * 900.0, price, high, low, close))
        price = close
    return out, 0.00012


def candles() -> tuple[list[Candle], float, str]:
    found = recorded()
    if found is not None:
        return found[0], found[1], "recorded"
    bars, spread = generated()
    return bars, spread, "GENERATED - no price store on this box"


# ───────────────────────────────────────────────────────────────── the nulls


def score(rows: list[Candle], up: float, down: float) -> tuple[float, int]:
    """`(mean forward move per event, events)` for one threshold pair.

    Driven through `Cusum.push` with the typical price and the bar range, which
    is what `bars.bar_input` hands it on the engine path with `source=TYPICAL`
    and `unit_from=RANGE` - the same arithmetic without a Nautilus `Bar` per
    candle.
    """
    from till_infinity.indicators import Cusum

    detector = Cusum(threshold_up=up, threshold_down=down, unit=1.0, unit_from=None)
    unit = statistics.median(c.range for c in rows if c.range > 0.0)
    moves: list[float] = []
    for i, candle in enumerate(rows):
        got = detector.push(candle.typical, candle.range, index=i)
        if got is None or i + HORIZON >= len(rows):
            continue
        ahead = rows[i + HORIZON].typical - candle.typical
        moves.append((ahead if got.side == "up" else -ahead) / unit)
    if len(moves) < LEAST_EVENTS:
        return float("nan"), len(moves)
    return statistics.fmean(moves), len(moves)


def premium(rows: list[Candle]) -> tuple[float, float, float, tuple[float, float]]:
    """`(premium, best asymmetric, best symmetric, the winning pair)`."""
    best, flat, pair = float("-inf"), float("-inf"), (0.0, 0.0)
    for up in GRID:
        for down in GRID:
            value, _ = score(rows, up, down)
            if math.isnan(value):
                continue
            if up == down:
                flat = max(flat, value)
            if value > best:
                best, pair = value, (up, down)
    return best - flat, best, flat, pair


def _steps(rows: list[Candle]) -> list[tuple[float, tuple[float, float, float]]]:
    """Each bar as `(log return of the close, its shape relative to the close)`."""
    return [
        (
            math.log(now.close / before.close),
            (now.open / now.close, now.high / now.close, now.low / now.close),
        )
        for before, now in zip(rows, rows[1:], strict=False)
    ]


def _rebuild(rows: list[Candle], steps) -> list[Candle]:
    """Candles from returns and shapes, on the real bars' own timestamps."""
    out = [rows[0]]
    close = rows[0].close
    for (ret, (o, h, lo)), when in zip(steps, (c.when for c in rows[1:]), strict=False):
        close *= math.exp(ret)
        out.append(
            Candle(when, close * o, max(close * h, close), min(close * lo, close), close)
        )
    return out


def shuffled(rows: list[Candle], rng: random.Random) -> list[Candle]:
    """The same returns in a different order, each keeping its own bar's shape.

    A return and the bar it happened in travel together, so the shape of a bar
    and the size of its move stay paired: a twin that drew a fresh shape would
    differ from the real arm in two things at once and name neither.
    """
    steps = _steps(rows)
    blocks = [steps[i : i + BLOCK] for i in range(0, len(steps), BLOCK)]
    rng.shuffle(blocks)
    return _rebuild(rows, [step for block in blocks for step in block])


def walk(rows: list[Candle], rng: random.Random) -> list[Candle]:
    """iid normal returns at the sample sd, with shapes drawn from the real bars."""
    steps = _steps(rows)
    sigma = statistics.stdev(ret for ret, _ in steps)
    shapes = [shape for _, shape in steps]
    return _rebuild(rows, [(rng.gauss(0.0, sigma), rng.choice(shapes)) for _ in steps])


def planted(
    rows: list[Candle], rng: random.Random, strength: float, trigger: float = 1.0
) -> list[Candle]:
    """A walk in which an up run really is followed by continuation.

    One-sided on purpose: a cumulative up move of `trigger` volatility units
    adds `strength` units of drift over the next `HORIZON` bars and a down move
    of the same size adds nothing. That is the shape a per-side threshold would
    exist to exploit, so a grid that cannot find it here cannot find it at all.
    """
    steps = _steps(rows)
    sigma = statistics.stdev(ret for ret, _ in steps)
    shapes = [shape for _, shape in steps]
    out, run, boost = [], 0.0, 0
    for _ in steps:
        step = rng.gauss(sigma * strength / HORIZON if boost else 0.0, sigma)
        out.append((step, rng.choice(shapes)))
        boost = max(0, boost - 1)
        run = max(0.0, run + step / sigma)
        if run >= trigger:
            run, boost = 0.0, HORIZON
    return _rebuild(rows, out)


def nulls(draws: int = 40) -> None:
    rows, _, source = candles()
    print(f"{len(rows)} {INTERVAL} {FEED} bars ({source})")
    print(f"grid {len(GRID)}x{len(GRID)}: {len(GRID) ** 2} trials where symmetric is {len(GRID)}\n")

    value, best, flat, pair = premium(rows)
    print(f"real      premium {value:+.4f}  best {best:+.4f} at {pair}, symmetric {flat:+.4f}")

    for name, arm in (("shuffled", shuffled), ("walk", walk)):
        rng = random.Random(SEED)
        got = [premium(arm(rows, rng)) for _ in range(draws)]
        over = sum(1 for g in got if g[0] >= value)
        flat_over = sum(1 for g in got if g[2] >= flat)
        print(
            f"{name:9s} premium: mean {statistics.fmean(g[0] for g in got):+.4f} "
            f"max {max(g[0] for g in got):+.4f}; {over}/{draws} at or above the real "
            f"one, p = {(over + 1) / (draws + 1):.3f}"
        )
        print(
            f"{'':9s} best symmetric: mean {statistics.fmean(g[2] for g in got):+.4f}; "
            f"{flat_over}/{draws} at or above the real {flat:+.4f}, "
            f"p = {(flat_over + 1) / (draws + 1):.3f}"
        )

    print("\npower: the same grid on a process with a one-sided effect planted")
    for strength in (0.0, 0.1, 0.25, 0.5, 1.0):
        rng = random.Random(7)
        got = [premium(planted(rows, rng, strength)) for _ in range(max(3, draws // 4))]
        print(
            f"  plant {strength:4.2f}v  premium {statistics.fmean(g[0] for g in got):+.4f}  "
            f"best {statistics.fmean(g[1] for g in got):+.4f}  "
            f"winning pairs {sorted({g[3] for g in got})}"
        )


# ──────────────────────────────────────────────────────────── the backtest


SYMMETRIC = "cusum:typical,threshold.buy=1.0,threshold.sell=1.0"
ASYMMETRIC = "cusum:typical,threshold.buy=0.5,threshold.sell=1.8"


def backtest() -> None:
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import Bar, BarType, QuoteTick
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.identifiers import Venue
    from nautilus_trader.model.objects import Money, Price, Quantity
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    from till_infinity.domain.models import Intent, Refusal, Side
    from till_infinity.statespace.actor import StatespaceActor, StatespaceConfig
    from till_infinity.strategies.entries import EdgeEntry, EdgeEntryConfig
    from till_infinity.strategies.exits import ManagedExit
    from till_infinity.strategies.leaves import StatespaceLong, StatespaceShort

    venue = Venue("SIM")
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD", venue)
    bar_type = BarType.from_str(f"{instrument.id}-15-MINUTE-LAST-EXTERNAL")
    digits = 5

    class Recording(EdgeEntry):
        """`EdgeEntry` that keeps what it saw, so the run can be counted."""

        def __init__(self, config: EdgeEntryConfig) -> None:
            super().__init__(config)
            self.bars_seen = 0
            self.proposals = 0
            self.readings: list[tuple[str, str]] = []
            self.fired: dict[str, int] = {}
            self._newest: dict[int, Any] = {}

        def on_bar(self, bar) -> None:
            # Total events by side. `Cusum.events` is capped at 64, so the
            # deque alone undercounts a 5,000-bar run.
            for detector in self.detectors.values():
                events = getattr(detector, "events", None)
                if not events or events[-1] is self._newest.get(id(detector)):
                    continue
                self._newest[id(detector)] = events[-1]
                self.fired[events[-1].side] = self.fired.get(events[-1].side, 0) + 1
            self.bars_seen += 1

        def on_data(self, data) -> None:
            if isinstance(data, dict):
                self.proposals += 1
            super().on_data(data)

    class CusumGate:
        """A reading off a registered detector, used as a gate.

        `Desk._register` fills `self.detectors` from `DeskConfig.indicators`
        before the bar subscription, so the engine warms it and this reads it.
        """

        declaration: ClassVar[str] = ""

        def decide(self, payload: dict[str, Any]) -> Intent | Refusal | None:
            verdict = super().decide(payload)  # type: ignore[misc]
            if not isinstance(verdict, Intent):
                return verdict
            events = self.detectors[self.declaration].events  # type: ignore[attr-defined]
            latest = events[-1].side if events else ""
            wanted = "up" if verdict.side is Side.BUY else "down"
            self.readings.append((verdict.side.value, latest))  # type: ignore[attr-defined]
            if latest != wanted:
                return Refusal(
                    gate="cusum",
                    detail=f"last event was {latest or 'none'}, wanted {wanted}",
                    feed=verdict.feed,
                )
            return verdict

    class PlainLong(StatespaceLong, ManagedExit, Recording):
        pass

    class PlainShort(StatespaceShort, ManagedExit, Recording):
        pass

    class SymmetricLong(CusumGate, StatespaceLong, ManagedExit, Recording):
        declaration: ClassVar[str] = SYMMETRIC

    class SymmetricShort(CusumGate, StatespaceShort, ManagedExit, Recording):
        declaration: ClassVar[str] = SYMMETRIC

    class AsymmetricLong(CusumGate, StatespaceLong, ManagedExit, Recording):
        declaration: ClassVar[str] = ASYMMETRIC

    class AsymmetricShort(CusumGate, StatespaceShort, ManagedExit, Recording):
        declaration: ClassVar[str] = ASYMMETRIC

    arms = {
        "production": (PlainLong, PlainShort),
        "symmetric": (SymmetricLong, SymmetricShort),
        "asymmetric": (AsymmetricLong, AsymmetricShort),
    }

    rows, spread, source = candles()
    print(f"{len(rows)} {INTERVAL} {FEED} bars ({source}), spread {spread:.6f}")
    print(
        "the quote stream is built from those bars - one quote a nanosecond "
        "before each close, straddling it by half the measured spread. The "
        "recorded `quotes` table holds a 0.36-day burst, 13 of 5,135 buckets, "
        "so there is no real top of book to replay.\n"
    )
    step = 900 * 1_000_000_000
    bars = [
        Bar(
            bar_type,
            Price(c.open, digits),
            Price(c.high, digits),
            Price(c.low, digits),
            Price(c.close, digits),
            Quantity(1000, 0),
            ts_event=int(c.when * 1e9) + step,
            ts_init=int(c.when * 1e9) + step,
        )
        for c in rows
    ]
    quotes = [
        QuoteTick(
            instrument_id=instrument.id,
            bid_price=Price(float(b.close) - spread / 2.0, digits),
            ask_price=Price(float(b.close) + spread / 2.0, digits),
            bid_size=Quantity(1_000_000, 0),
            ask_size=Quantity(1_000_000, 0),
            ts_event=b.ts_event - 1,
            ts_init=b.ts_event - 1,
        )
        for b in bars
    ]
    data = sorted([*bars, *quotes], key=lambda d: d.ts_init)

    for arm, (long_cls, short_cls) in arms.items():
        # A fresh progress file per arm. `Engine.restore` reads the last bar
        # time out of it and `observe_bar` refuses a bar that is not strictly
        # after it, so a second run over one series folds nothing and publishes
        # nothing - which looks exactly like a quiet market.
        shutil.rmtree(STATE / arm, ignore_errors=True)
        (STATE / arm).mkdir(parents=True, exist_ok=True)
        os.environ["STATESPACE_STATE_DIR"] = str(STATE / arm)

        engine = BacktestEngine(
            config=BacktestEngineConfig(
                trader_id="BACKTEST-001", logging=LoggingConfig(bypass_logging=True)
            )
        )
        engine.add_venue(
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=USD,
            starting_balances=[Money(100_000, USD)],
        )
        engine.add_instrument(instrument)
        engine.add_data(data)
        declared = getattr(long_cls, "declaration", "")
        actor = StatespaceActor(
            StatespaceConfig(
                bar_types=(str(bar_type),),
                feeds={"EUR/USD": FEED},
                # The same declaration the desks get, not a symmetric one:
                # `StatespaceActor._register` is a second registrar with its
                # own catalogue check, so a grammar that reached only
                # `Desk._register` would raise here.
                indicators=(declared,) if declared else (),
            )
        )
        engine.add_actor(actor)
        desks = []
        for cls in (long_cls, short_cls):
            desk = cls(
                EdgeEntryConfig(
                    instrument_id=instrument.id,
                    bar_type=bar_type,
                    indicators=(declared,) if declared else (),
                    order_id_tag=f"{abs(hash(cls.__name__)) % 10_000:04d}",
                )
            )
            engine.add_strategy(desk)
            desks.append(desk)
        engine.run()

        print(f"==== {arm} ====")
        print(f"actor detectors {sorted(actor.detectors)}")
        for desk in desks:
            orders = desk.cache.orders(strategy_id=desk.id)
            print(
                f"{type(desk).__name__}: bars {desk.bars_seen} proposals {desk.proposals} "
                f"intents {desk.taken} refused {desk.refused} orders {len(orders)}"
            )
            print(f"   gates {dict(sorted(desk.passed_over.items()))}")
            print(f"   detectors {sorted(desk.detectors)}")
            if desk.readings:
                agreed = sum(
                    1 for side, last in desk.readings if last == ("up" if side == "buy" else "down")
                )
                print(f"   detector read {len(desk.readings)} times, agreed {agreed}")
            for key, detector in desk.detectors.items():
                print(
                    f"   {key}: thresholds {detector.thresholds} sided {detector.sided}, "
                    f"events {desk.fired}"
                )
        account = engine.portfolio.account(venue)
        print(f"   equity at the end {account.balance_total()}\n")


PASSES = {"backtest": backtest, "nulls": nulls}


if __name__ == "__main__":
    wanted = sys.argv[1] if len(sys.argv) > 1 else ""
    if wanted not in PASSES:
        print(f"usage: {sys.argv[0]} [{' | '.join(PASSES)}]")
        raise SystemExit(2)
    PASSES[wanted]()
