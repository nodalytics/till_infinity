"""Z-Momentum Attention, recorded and scored before it is ever given a vote.

An attention-weighted z-score with a normalised slope and **dynamic 85th/65th
percentile thresholds**, firing `oversold` and `overbought` at extremes of this
series' own recent z distribution.

## What is already measured, and why this does not act by default

`research/zma.md` ran the indicator against a graded positive control - an
Ornstein-Uhlenbeck process whose reversion speed is a dial - and it works: AUC
0.518, 0.549, **0.620** and hit rates 0.509, 0.583, **0.705** at theta = 0.02,
0.05, 0.15. It detects reversion, and detects more of it when there is more.

On this desk's instruments it does not.

| where | result |
| --- | --- |
| Volatility, Step, Jump | AUC 0.493 to 0.504, on their own shuffles |
| **Boom and Crash** | **hit 37.6% to 46.1% - reliably wrong** |
| real outright prices | 0.485 to 0.515, inside noise |
| **constructed spreads** | **AUC 0.67 to 0.73, hit 78.7% to 83.7%** |

So it is a working detector pointed at processes that do not revert -
`generators.md` has the synthetics at `H = 0.50`, and a random walk has no mean
to come back to. The one place it pays is spreads, which this book does not
trade yet.

**That is why this records and scores rather than votes.** A signal measured at
0.50 on the traded book should not size a position on the strength of an
argument, and the two of those are settled the same way everything else here is:
by keeping the call, settling it against what happened, and letting the record
decide. `consensus_vol` does this for volatility estimators and
`projection.Calibration` for the forward law.

**`ZMA_ACTS` is the switch that gives it a vote**, and it should stay off until
`accuracy` on this desk's own bars says otherwise.

## The agreement condition

An extreme alone is a weak claim - the thresholds are percentiles, so something
is always extreme. The condition worth recording is **displacement and momentum
pointing the same way**:

* **oversold and the slope rising** - stretched down, already turning up.
* **overbought and the slope falling** - stretched up, already turning down.

That is stricter than either alone and it is what `agrees` reports. It is also
the form `research/zma.md`'s changepoint work points at: the gate that raised
precision from 0.8367 to 0.9103 on the best spread required the changepoint to be
**active**, not quiet, because on a reverting series the excursion is the
evidence.
"""

from __future__ import annotations

import math
import os
import pickle
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from ..logging import get_logger
from ..shared import effects
from .state import Restorable

#: Recorded and surfaced always; it costs one array pass a bar.
ENABLED = os.environ.get("STRUCTURES_ZMA", "1") not in ("0", "false", "no")

#: **Whether it may influence a decision.** Off, and it should stay off until the
#: scored record on this desk's own bars justifies turning it on - see the module
#: note. Recording is free; acting is not.
ZMA_ACTS = os.environ.get("STRUCTURES_ZMA_ACTS", "0") not in ("0", "false", "no")

#: **The softmax temperature**, as a multiple of the window's own mean absolute
#: return. Lower sharpens onto the bars that moved; higher flattens toward a
#: plain rolling mean. There was no temperature at all until
#: `research/streaming.md` measured the attention as inert - every weight came
#: out at 1.0000 because the exponent was a raw return near 1e-4 - which is why
#: this constant exists rather than being buried inside an `exp`.
#:
#: **Set high, because sharper was measured as worse.** On the instruments where
#: this detector has any signal, AUC falls monotonically as the weighting
#: sharpens:
#:
#: | temperature | 99 (flat) | 8 | 4 | 2 | 1 | 0.5 |
#: | --- | --- | --- | --- | --- | --- | --- |
#: | btc BINANCE-COINBASE spread | 0.7221 | 0.7220 | 0.7218 | 0.7197 | 0.7049 | 0.6655 |
#: | btc BINANCE-DERIV spread | 0.7141 | 0.7141 | 0.7136 | 0.7085 | 0.6827 | 0.6434 |
#: | OU theta=0.05 control | 0.5498 | 0.5498 | 0.5497 | 0.5497 | 0.5493 | 0.5458 |
#:
#: At 8 the effective sample size is 47.99 of 50 and every column is inside
#: 0.002 of the flat weighting, so nothing already recorded is disturbed. The
#: sharper settings do lift the feeds sitting at 0.50 - btc 0.4995 to 0.5152 -
#: but a 1.5-point move inside noise is not evidence and picking the argmax of a
#: six-by-six table is what `calibrating.md` exists to warn about.
#:
#: The value of the fix is therefore not the number: it is that the weighting
#: **works** now and can be argued about from a measurement, where before it was
#: an exponent that could not do anything whatever anyone set.
TEMPERATURE = 8.0

#: How far below the largest bar a weight may fall, in the exponent. A single
#: print a hundred times the typical move would otherwise drive every other
#: weight to underflow and leave a mean that is one bar, which is not attention
#: - it is a lookup. Applied to the gap rather than to the scaled return, so
#: that lowering the temperature always sharpens.
CAP = 6.0

#: Bars in the z window, and how much history the dynamic thresholds see.
PERIOD = 50
LOOKBACK = 200

#: Percentiles for the two threshold tiers, matching the reference implementation.
STRONG, WEAK = 85.0, 65.0

#: Thresholds before there is enough history to take a percentile of.
COLD_STRONG, COLD_WEAK = 1.5, 1.0

#: Calls before `accuracy` is worth reading.
WARM = 200

#: Where the scored record lives, **outside the engine state**.
#:
#: The book used to live only inside the pickled engine, and
#: `structures/store.py` hashes the shape of every persisted dataclass and
#: invalidates the whole file when any of them changes. So the record was lost
#: on any deploy that touched any persisted class, not merely a zma one - and
#: `TRADING_ZMA_GATE` needs **200 settled calls per feed** before it may act.
#: On 2026-09-15 the desk deployed eleven times and the book was back at zero
#: series each time, which meant a gate that could not accumulate the evidence
#: it was waiting for however long it ran.
#:
#: `cycles.Book` already had its own file for exactly this reason; this is the
#: same fix applied to the book that needed it more.
WEIGHTS = Path(os.environ.get("STRUCTURES_ZMA_RECORD", ".data/structures/zma.pkl"))

log = get_logger(__name__)

effects.declare("structures.zma", enabled=ENABLED)


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile, without pulling numpy into this module."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    at = (pct / 100.0) * (len(ordered) - 1)
    lo = math.floor(at)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (at - lo)


@dataclass(slots=True)
class Zma(Restorable):
    """One series' z-score, slope and zone flags, with its calls scored.

    `Restorable` because it is held per feed and timeframe and therefore saved.
    """

    period: int = PERIOD
    lookback: int = LOOKBACK
    #: Carried as a field, not only read from the module, for two reasons. It
    #: makes the sharpness settable per series, and - because `store._schema`
    #: hashes the shape of every persisted dataclass - adding it invalidates
    #: saved state, which is **correct** here: the z-scores this now produces
    #: are not the ones the stored `calls` and `right` were scored against, so
    #: carrying that record forward would be comparing two indicators.
    temperature: float = TEMPERATURE

    _prices: deque[float] = field(default_factory=lambda: deque(maxlen=PERIOD))
    _zs: deque[float] = field(default_factory=lambda: deque(maxlen=LOOKBACK))
    _slopes: deque[float] = field(default_factory=lambda: deque(maxlen=LOOKBACK))
    _previous_slope: float = 0.0

    z_score: float = 0.0
    slope: float = 0.0
    strong: float = COLD_STRONG
    weak: float = COLD_WEAK
    seen: int = 0

    #: The open call, kept until the next bar settles it: +1 expects a rise,
    #: -1 a fall, 0 no call.
    _open_call: int = 0
    _open_price: float = 0.0
    calls: int = 0
    right: int = 0

    #: The **continuous** call open on the same bar, scored separately: bet
    #: against the displacement whenever it is past the threshold, without
    #: waiting for momentum to turn. `research/adapting.md` measured this
    #: winning by 2.5 to 7.8 points over `agrees` at an identical bet count on
    #: three OU controls, so the two are kept apart rather than one standing in
    #: for the other - a veto has to be justified by the record of the reading
    #: it actually uses.
    _open_edge: int = 0
    edge_calls: int = 0
    edge_right: int = 0

    def __post_init__(self) -> None:
        """Make `period` and `lookback` mean something.

        A `default_factory` is evaluated with no access to the instance, so
        `deque(maxlen=PERIOD)` captures the *module* constant and every `Zma`
        kept fifty prices and two hundred z-scores however it was constructed.
        The two fields were decorative, and silently so: `Zma(period=200)`
        built, reported `period == 200`, and behaved exactly like the default.

        Found by `research/harness/zmaonline.py`, whose mixture over periods
        20/50/100/200 produced four experts with identical predictions and
        therefore an exactly uniform weight vector - which is not a result a
        mixture can produce by accident.

        Production only ever builds the default, so nothing shipped was wrong;
        a study of whether some other period is better could not have been run.
        """
        if self._prices.maxlen != self.period:
            self._prices = deque(self._prices, maxlen=self.period)
        if self._zs.maxlen != self.lookback:
            self._zs = deque(self._zs, maxlen=self.lookback)
            self._slopes = deque(self._slopes, maxlen=self.lookback)

    # ------------------------------------------------------------------ state

    @property
    def oversold(self) -> bool:
        return self.z_score < -self.strong

    @property
    def overbought(self) -> bool:
        return self.z_score > self.strong

    @property
    def weakly_oversold(self) -> bool:
        return not self.oversold and self.z_score < -self.weak

    @property
    def weakly_overbought(self) -> bool:
        return not self.overbought and self.z_score > self.weak

    @property
    def rising(self) -> bool:
        return self.slope > 0.0

    @property
    def agrees(self) -> int:
        """Displacement and momentum pointing the same way: +1 up, -1 down, 0 no.

        Stricter than either alone, and deliberately so. The thresholds are
        percentiles of this series' own history, so **something is always
        extreme** - roughly 15% of bars by construction, on a trend, on noise and
        on a shuffled series alike. An extreme on its own is therefore not a
        claim about anything; an extreme that momentum has already begun to
        unwind is.
        """
        if self.oversold and self.rising:
            return 1
        if self.overbought and not self.rising:
            return -1
        return 0

    @property
    def stretched(self) -> int:
        """Displacement alone: +1 expects a rise, -1 a fall, 0 inside the band.

        The agreement condition without the momentum half. Weaker as an
        argument and **stronger as a measurement**, which is the finding in
        `research/adapting.md`: a flag fires on a handful of bars and throws
        away the ordering on the rest, and thresholding the z-score turned out
        to be a loss rather than a filter.
        """
        if self.oversold:
            return 1
        if self.overbought:
            return -1
        return 0

    @property
    def state(self) -> str:
        if self.oversold:
            return "oversold"
        if self.overbought:
            return "overbought"
        if self.weakly_oversold:
            return "weakly_oversold"
        if self.weakly_overbought:
            return "weakly_overbought"
        return "neutral"

    @property
    def warm(self) -> bool:
        return self.calls >= WARM

    @property
    def accuracy(self) -> float:
        """Share of settled calls that were right. `nan` until `warm`.

        **This is the number that decides whether `ZMA_ACTS` is ever turned on.**
        A coin is 0.50; `research/zma.md` measured 0.376 to 0.461 on Boom and
        Crash, which is worse than a coin and would cost the spread as well as
        the side.
        """
        return self.right / self.calls if self.calls else float("nan")

    @property
    def edge_accuracy(self) -> float:
        """The same, for the continuous call. `nan` until there is one."""
        return self.edge_right / self.edge_calls if self.edge_calls else float("nan")

    # ----------------------------------------------------------------- update

    def observe(self, price: float) -> None:
        """One bar's close. Settles the previous call, then makes a new one."""
        if price <= 0:
            return
        self._settle(price)
        self._prices.append(float(price))
        self.seen += 1
        if len(self._prices) < 3:
            return

        arr = list(self._prices)
        weights = self._attention(arr)
        prices = arr[1:]
        mean = sum(w * p for w, p in zip(weights, prices, strict=True))
        var = sum(w * (p - mean) ** 2 for w, p in zip(weights, prices, strict=True))
        self.z_score = (prices[-1] - mean) / (math.sqrt(var) + 1e-12)
        self._zs.append(abs(self.z_score))

        # Slope of a normalised series, so the number means the same thing on
        # gold at 4,400 and on a volatility index at 1.0.
        n = len(arr)
        base = arr[0] if arr[0] else 1.0
        norm = [(p / base) * 100.0 for p in arr]
        sx = n * (n - 1) / 2.0
        sx2 = sum(i * i for i in range(n))
        denom = n * sx2 - sx * sx
        self.slope = (n * sum(i * v for i, v in enumerate(norm)) - sx * sum(norm)) / (denom + 1e-12)
        self._slopes.append(abs(self.slope))
        self._previous_slope = self.slope

        if len(self._zs) >= 10:
            self.strong = _percentile(list(self._zs), STRONG)
            self.weak = _percentile(list(self._zs), WEAK)
        else:
            self.strong, self.weak = COLD_STRONG, COLD_WEAK

        call, edge = self.agrees, self.stretched
        if call or edge:
            self._open_call, self._open_edge = call, edge
            self._open_price = float(price)
            if call:
                effects.fired("structures.zma")

    def _attention(self, arr: list[float]) -> list[float]:
        """A softmax over absolute returns - with the temperature it needs.

        **This was inert for the whole life of the indicator.** The weights were
        `exp(|r| - max|r|)` over raw returns, and a softmax only has an opinion
        when its inputs differ by O(1). Absolute one-minute returns differ by
        about 1e-4, so every weight came out at 1.0000 and the
        "attention-weighted" mean was the plain one. `research/streaming.md`
        measured Kish's effective sample size at **49.00 of 50** on real BTC
        bars, on a deliberately spiky series and on an Ornstein-Uhlenbeck
        process - a uniform weighting over this window is exactly 50.

        The fix is a **temperature**: divide by the window's own mean absolute
        return before exponentiating. That puts the exponent at O(1), where a
        softmax discriminates, and makes the weighting scale-free at the same
        time - gold at 4,400 and a volatility index at 1.0 weight their moves
        alike, which the raw form never did either.

        Subtracting the maximum is kept and is now doing its actual job. It
        cancels in the normalisation and exists only to stop `exp` overflowing;
        applied to *unscaled* inputs, as before, it was the entire computation.

        `CAP` bounds how far one bar can get above the rest. Without it a single
        print a hundred times the typical move drives every other weight to
        underflow and the mean is that one bar, which is not attention - it is
        a lookup.
        """
        rets = [abs((arr[i + 1] - arr[i]) / (arr[i] + 1e-12)) for i in range(len(arr) - 1)]
        typical = sum(rets) / len(rets) if rets else 0.0
        scale = self.temperature * typical
        if scale <= 0:
            # A window that never moved. Every bar is equally uninformative and
            # saying so explicitly beats dividing by an epsilon.
            return [1.0 / len(rets)] * len(rets) if rets else []
        scaled = [r / scale for r in rets]
        biggest = max(scaled)
        # **The cap goes here, on the gap below the largest bar - not on the
        # scaled return itself.** Capping before this flattens every bar that
        # clears the cap into one value, so lowering the temperature makes the
        # weighting *less* discriminating past a point: effective sample size
        # went 28.99, 6.90, 7.67, 17.14 as the temperature fell 2.0, 1.0, 0.5,
        # 0.25, which is not a knob anybody can reason about. Bounding the gap
        # instead floors the smallest weight at `exp(-CAP)` of the largest and
        # leaves the ordering alone, so the temperature is monotone.
        exp_w = [math.exp(max(v - biggest, -CAP)) for v in scaled]
        total = sum(exp_w) + 1e-12
        return [w / total for w in exp_w]

    def _settle(self, price: float) -> None:
        """Score the call the previous bar made, before this bar changes anything.

        Settled on the **next bar** rather than at some horizon, because that is
        the only outcome available without keeping a schedule, and because a
        signal that cannot survive one bar will not survive twenty.
        """
        if self._open_price <= 0:
            return
        moved = price - self._open_price
        # A bar that did not move settles nothing. Counting it as a loss would
        # score the tick size on a Step index, where a flat bar is common.
        if moved != 0.0:
            if self._open_call:
                self.calls += 1
                if (moved > 0) == (self._open_call > 0):
                    self.right += 1
            if self._open_edge:
                self.edge_calls += 1
                if (moved > 0) == (self._open_edge > 0):
                    self.edge_right += 1
        self._open_call = self._open_edge = 0
        self._open_price = 0.0

    def to_dict(self) -> dict:
        return {
            "z": round(self.z_score, 4),
            "slope": round(self.slope, 6),
            "state": self.state,
            "agrees": self.agrees,
            "rising": self.rising,
            "strong": round(self.strong, 4),
            "calls": self.calls,
            "accuracy": round(self.accuracy, 4) if self.warm else None,
            "edge_calls": self.edge_calls,
            "edge_accuracy": (round(self.edge_accuracy, 4) if self.edge_calls >= WARM else None),
            "acts": ZMA_ACTS,
        }


@dataclass(slots=True)
class Book(Restorable):
    """One `Zma` per feed and timeframe, keyed as `volatility.Book` keys its own."""

    _by_key: dict[tuple[str, str], Zma] = field(default_factory=dict)
    #: Series whose record came back from the file rather than from bars.
    loaded: int = 0

    def of(self, feed: str, interval: str = "") -> Zma:
        key = (feed, interval)
        found = self._by_key.get(key)
        if found is None:
            found = self._by_key[key] = Zma()
        return found

    def observe(self, feed: str, interval: str, price: float) -> Zma:
        got = self.of(feed, interval)
        got.observe(price)
        return got

    def forget(self, keep: set[str]) -> int:
        gone = [k for k in self._by_key if k[0] not in keep]
        for k in gone:
            del self._by_key[k]
        return len(gone)

    def standings(self) -> list[tuple[str, float, int]]:
        """Feeds by how accurate the agreement call has been, worst first.

        Worst first on purpose: the question this book exists to answer is
        whether the signal is ever worth acting on, and the instruments where it
        is **reliably wrong** are the ones that would cost money first.
        """
        rows = [
            (f"{feed} {interval}".strip(), z.accuracy, z.calls)
            for (feed, interval), z in self._by_key.items()
            if z.warm
        ]
        return sorted(rows, key=lambda r: r[1])

    def warm(self, series) -> int:
        """Replay stored closes into the book. Returns series warmed.

        **Because nothing else fills it on a restore.** `Engine.seed` feeds
        this through `observe_bar`, but `warm_new` only replays feeds the
        engine has *no series* for - and a restored engine has series for
        everything, so on any restart that keeps its levels the book stays
        empty and starts counting from the next live bar. That is weeks to
        reach the two hundred settled calls `TRADING_ZMA_GATE` and `cycle-turn`
        both wait on, and it was measured at zero series against 261,192
        restored level closes on the live desk.

        `series` yields `(feed, interval, closes)` oldest-first. Kept free of
        where the bars came from: this module has no business knowing about the
        price store, and a caller that hands it the wrong closes - several
        venues interleaved by timestamp, say - would be handing it a violently
        reverting series that is an artefact of the query.

        A series that already has a record is skipped rather than replayed on
        top of it. Doubling counts would be worse than not warming at all,
        because the gate reads the count as evidence.
        """
        warmed = 0
        for feed, interval, closes in series:
            if len(closes) < WARM:
                continue
            found = self.of(feed, interval)
            if found.calls or found.edge_calls:
                continue
            for close in closes:
                found.observe(float(close))
            warmed += 1
        return warmed

    # ------------------------------------------------------------ persistence

    def save(self, path: Path | None = None) -> int:
        """Write the scored record to its own file. Returns series written.

        **Only the record, not the stream.** The prices, z-scores and dynamic
        thresholds rebuild themselves from a few hundred bars, and a restored
        window pasted beside counts earned on a different stretch of history is
        a mismatch nobody would notice. What cannot be rebuilt is how often
        this reading has been right on this feed, which is the only number that
        decides whether it is ever allowed to act.

        Written to a temporary file and renamed, so an interrupted save leaves
        the previous record rather than a truncated one.
        """
        target = Path(path or WEIGHTS)
        try:
            payload = {
                f"{feed}\u0000{interval}": (z.calls, z.right, z.edge_calls, z.edge_right)
                for (feed, interval), z in self._by_key.items()
                if z.calls or z.edge_calls
            }
            if not payload:
                return 0
            target.parent.mkdir(parents=True, exist_ok=True)
            spare = target.with_suffix(target.suffix + ".tmp")
            with spare.open("wb") as handle:
                pickle.dump({"version": 1, "record": payload}, handle)
            spare.replace(target)
            return len(payload)
        except Exception as exc:
            log.warning("zma: could not save the record to %s: %s", target, exc)
            return 0

    def load(self, path: Path | None = None) -> int:
        """Read the record back onto the series that own it. Returns series loaded."""
        target = Path(path or WEIGHTS)
        if not target.exists():
            return 0
        try:
            with target.open("rb") as handle:
                got = pickle.load(handle)
            if not isinstance(got, dict) or got.get("version") != 1:
                log.warning("zma: %s is not a record file this build reads", target)
                return 0
            for key, counts in got["record"].items():
                feed, _, interval = str(key).partition("\u0000")
                z = self.of(feed, interval)
                z.calls, z.right, z.edge_calls, z.edge_right = (int(c) for c in counts)
            self.loaded = len(got["record"])
            return self.loaded
        except Exception as exc:
            log.warning("zma: could not load the record from %s: %s", target, exc)
            return 0

    def to_dict(self) -> dict:
        return {
            "enabled": ENABLED,
            "acts": ZMA_ACTS,
            "loaded": self.loaded,
            "series": len(self._by_key),
            "warm": sum(1 for z in self._by_key.values() if z.warm),
            "standings": [[k, round(a, 4), n] for k, a, n in self.standings()[:10]],
        }
