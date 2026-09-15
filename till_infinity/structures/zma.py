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
from collections import deque
from dataclasses import dataclass, field

from ..shared import effects
from .state import Restorable

#: Recorded and surfaced always; it costs one array pass a bar.
ENABLED = os.environ.get("STRUCTURES_ZMA", "1") not in ("0", "false", "no")

#: **Whether it may influence a decision.** Off, and it should stay off until the
#: scored record on this desk's own bars justifies turning it on - see the module
#: note. Recording is free; acting is not.
ZMA_ACTS = os.environ.get("STRUCTURES_ZMA_ACTS", "0") not in ("0", "false", "no")

#: Bars in the z window, and how much history the dynamic thresholds see.
PERIOD = 50
LOOKBACK = 200

#: Percentiles for the two threshold tiers, matching the reference implementation.
STRONG, WEAK = 85.0, 65.0

#: Thresholds before there is enough history to take a percentile of.
COLD_STRONG, COLD_WEAK = 1.5, 1.0

#: Calls before `accuracy` is worth reading.
WARM = 200

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
        # Attention weights: a softmax over absolute returns, so the bars that
        # moved carry the mean rather than the quiet ones smoothing it away.
        rets = [(arr[i + 1] - arr[i]) / (arr[i] + 1e-12) for i in range(len(arr) - 1)]
        biggest = max((abs(r) for r in rets), default=0.0)
        exp_w = [math.exp(abs(r) - biggest) for r in rets]
        total = sum(exp_w) + 1e-12
        weights = [w / total for w in exp_w]
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

        call = self.agrees
        if call:
            self._open_call, self._open_price = call, float(price)
            effects.fired("structures.zma")

    def _settle(self, price: float) -> None:
        """Score the call the previous bar made, before this bar changes anything.

        Settled on the **next bar** rather than at some horizon, because that is
        the only outcome available without keeping a schedule, and because a
        signal that cannot survive one bar will not survive twenty.
        """
        if not self._open_call or self._open_price <= 0:
            return
        moved = price - self._open_price
        if moved != 0.0:
            self.calls += 1
            if (moved > 0) == (self._open_call > 0):
                self.right += 1
        self._open_call, self._open_price = 0, 0.0

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
            "acts": ZMA_ACTS,
        }


@dataclass(slots=True)
class Book(Restorable):
    """One `Zma` per feed and timeframe, keyed as `volatility.Book` keys its own."""

    _by_key: dict[tuple[str, str], Zma] = field(default_factory=dict)

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

    def to_dict(self) -> dict:
        return {
            "enabled": ENABLED,
            "acts": ZMA_ACTS,
            "series": len(self._by_key),
            "warm": sum(1 for z in self._by_key.values() if z.warm),
            "standings": [[k, round(a, 4), n] for k, a, n in self.standings()[:10]],
        }
