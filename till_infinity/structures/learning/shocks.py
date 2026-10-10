"""Anomalies before they happen: the probability of a price shock in the next few bars.

`anomaly.py` flags cross-venue dislocations as they happen. This forecasts the price kind before it
arrives: a **shock**, a bar whose |return| is more than `SHOCK_MULTIPLE` times the series' own
trailing mean |return|, within the next `AHEAD` bars.

## Why it can be seen coming

`research/docs/anomalies.md` measured it on two years of 15m and 1h bars. On FX, metals and crypto,
a model on volatility state, anomaly clustering and the calendar ranks the next four bars' shocks
at AUC 0.76-0.79, with 3-4x the base rate in its top decile. The warning persists: shocks 17-20 bars
out are still ranked at 0.72-0.74. On the Deriv indices whose shocks are published as memoryless
(Boom, Crash, Jump, Volatility) the same model scores 0.49-0.52, as it must. Volatility state
carries it - the 14-bar true-range average against its own norm, and where it sits among its
recent readings - and recent shocks add to it, because they cluster.

## What this is

**A frozen gradient-boosted model**, trained offline by `research/harness/shocktrain.py` on
production's own features (this module's `_features`, replayed over two years of bars) and shipped
as plain trees in `till_infinity/models/shocks.json`, read and evaluated by `shared/frozen.py`
with no dependency, and retrained on a schedule by `research/pipeline/`. The features are
scale-free, so one model serves every feed and timeframe.

It is frozen because the online alternatives lost the signal. `research/harness/shockreplay.py`
replayed an online logistic model on the same features (AUC 0.60-0.68 on real markets) and an
online count table (0.62-0.69), against 0.73-0.76 for the boosted model on the same held-out
period. A model
that is trained offline and refitted by rerunning the harness beats one that learns live and learns
badly. If the file is missing or was trained on a different feature recipe, nothing is published:
a number from the wrong features is worse than no number.

## What it is not

**It has no direction.** A shock is a shock either way. And **it decides nothing**:
`research/docs/session-switch.md` found that production's stops already scale with volatility, so a
second volatility-based size cut on top of them sized on reversion rather than on risk. It is
published on every call and printed on the cards when the risk is well above normal, and any use in
sizing waits for a measurement in production's R.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from ...shared import frozen
from ..state import Restorable

#: A shock is a bar this many times the trailing mean |return|. The anomalies study's threshold.
SHOCK_MULTIPLE = 4.0
#: The forecast window, in bars of the series' own timeframe.
AHEAD = 4
#: Bars behind the trailing means. Long enough to be the series' norm, short enough to follow it.
NORM = 500
#: Bars before a series' features mean anything.
WARM = 250
#: The frozen model's name, read through `shared/frozen.py`: `.data/models/shocks.json` when the
#: retraining pipeline has delivered one, the shipped `till_infinity/models/shocks.json` otherwise.
MODEL = "shocks"
#: What changing the meaning of an input requires bumping. The shipped model records the recipe it
#: was trained on, and a model trained on a different one is not used (the rule `breaking.RECIPE`
#: states).
RECIPE = "2026-09-30 vol state, clustering, clock, range, tick volume"
#: A card mentions the risk only above this multiple of the base rate. At 2x it would have warned on
#: 14-23% of real-market bars in the held-out period; 3x is about the model's top decile, where
#: shocks ran at 3.1-3.6x their base rate.
CARD_LIFT = 3.0

NAMES = (
    "vol_vs_norm",
    "vol_vs_norm_sq",
    "tr_rank",
    "tr_rank_sq",
    "vol_of_vol",
    "shocks_20",
    "shocks_100",
    "hour_sin",
    "hour_cos",
    "to_weekend",
    "interval_log",
    # research/docs/infoflow.md: the two inputs carrying information about the next bar's size
    # beyond the state above, in both halves and far above GARCH walks (vpin.md, causal.md agree).
    "range_vol",
    "volume_z",
    "volume_z_hour",
)

#: Resolved log volumes a volume z needs before it is read; NaN before, which the trees route.
VOLUME_WARM = 50
#: Per hour-of-day log volumes kept, and needed, for the clock-adjusted z - so the intraday volume
#: profile is not mistaken for a surge (`vol/clock.py` does the same for volatility).
HOUR_KEEP, HOUR_WARM = 60, 10


@dataclass(slots=True)
class Series(Restorable):
    """One (feed, interval): the history its features are read from, and its waiting examples."""

    seconds: float = 0.0
    prev_close: float = 0.0
    abs_returns: deque = field(default_factory=lambda: deque(maxlen=NORM))
    true_ranges: deque = field(default_factory=lambda: deque(maxlen=NORM))
    log_tr: deque = field(default_factory=lambda: deque(maxlen=50))
    ewma_tr: float = 0.0
    tr_history: deque = field(default_factory=lambda: deque(maxlen=NORM))
    shocks: deque = field(default_factory=lambda: deque(maxlen=100))
    latest: list[float] = field(default_factory=list)
    #: Log tick volumes, and the same by UTC hour of day. Empty for a venue that reports none.
    log_volume: deque = field(default_factory=lambda: deque(maxlen=NORM))
    #: Plain lists trimmed by hand, not deques: a dict's values come back from the state file as
    #: whatever they were saved as, and only a top-level deque field is re-bounded on restore.
    volume_by_hour: dict[int, list[float]] = field(default_factory=dict)
    #: This bar's range in the volatility unit, and its tick volume (0 when none was reported).
    last_range: float = 0.0
    last_volume: float = 0.0

    @property
    def warm(self) -> bool:
        return len(self.abs_returns) >= WARM


def _features(s: Series, when: float) -> list[float]:
    mean_tr = sum(s.true_ranges) / len(s.true_ranges)
    ratio = math.log(s.ewma_tr / mean_tr) if s.ewma_tr > 0 and mean_tr > 0 else 0.0
    rank = (
        sum(1 for v in s.tr_history if v < s.ewma_tr) / len(s.tr_history) if s.tr_history else 0.5
    )
    logs = list(s.log_tr)
    mean_log = sum(logs) / len(logs) if logs else 0.0
    vol_of_vol = (
        math.sqrt(sum((v - mean_log) ** 2 for v in logs) / len(logs)) if len(logs) > 1 else 0.0
    )
    recent = list(s.shocks)
    hour = (when % 86_400) / 3_600
    # Hours to Friday 21:00 UTC, FX's weekly close. 1970-01-01 was a Thursday, 72 hours into a
    # week that starts on Monday 00:00 UTC.
    week_hour = (when / 3_600 + 72) % 168
    to_close = (4 * 24 + 21 - week_hour) % 168
    return [
        ratio,
        ratio * ratio,
        rank,
        rank * rank,
        vol_of_vol,
        sum(recent[-20:]) / 20.0,
        sum(recent) / 100.0,
        math.sin(2 * math.pi * hour / 24),
        math.cos(2 * math.pi * hour / 24),
        math.log1p(to_close),
        math.log(s.seconds) if s.seconds > 0 else 0.0,
        s.last_range,
        _z(_log(s.last_volume), s.log_volume, VOLUME_WARM),
        _z(_log(s.last_volume), s.volume_by_hour.get(int(hour), ()), HOUR_WARM),
    ]


def _log(volume: float) -> float:
    return math.log(volume) if volume > 0 else float("nan")


def _z(value: float, history, warm: int) -> float:
    """`value` against `history` in standard deviations; NaN without enough history or a value."""
    if math.isnan(value) or len(history) < warm:
        return float("nan")
    n = len(history)
    mean = sum(history) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in history) / n)
    return (value - mean) / sd if sd > 0 else float("nan")


@dataclass(slots=True)
class Shocks(Restorable):
    """Every series' feature history, read by the frozen model. See the module note."""

    series: dict[str, Series] = field(default_factory=dict)

    def observe(
        self,
        feed: str,
        interval: str,
        seconds: float,
        when: float,
        high: float,
        low: float,
        close: float,
        volume: float | None = None,
    ) -> None:
        """One closed bar: update the series' history and hold this bar's features.

        `volume` is the bar's tick volume where the venue reports one; without it the volume
        features are NaN, which the trees route like any missing value."""
        if close <= 0 or high < low:
            return
        key = f"{feed}|{interval}"
        s = self.series.get(key)
        if s is None:
            s = self.series[key] = Series(seconds=seconds)
        if s.prev_close <= 0:
            s.prev_close = close
            return
        r = abs(math.log(close / s.prev_close))
        tr = max(high - low, abs(high - s.prev_close), abs(low - s.prev_close)) / s.prev_close
        norm = sum(s.abs_returns) / len(s.abs_returns) if s.abs_returns else 0.0
        shock = bool(s.warm and norm > 0 and r > SHOCK_MULTIPLE * norm)
        s.abs_returns.append(r)
        s.true_ranges.append(tr)
        s.log_tr.append(math.log(tr) if tr > 0 else -20.0)
        s.ewma_tr = tr if s.ewma_tr <= 0 else s.ewma_tr + (tr - s.ewma_tr) / 14.0
        s.tr_history.append(s.ewma_tr)
        s.shocks.append(1.0 if shock else 0.0)
        s.last_range = (high - low) / s.prev_close / s.ewma_tr if s.ewma_tr > 0 else 0.0
        # The bar's own volume is part of its z, as infoflow.py measured it (a rolling window that
        # includes the bar); features are read after the bar closes, so nothing here is ahead.
        s.last_volume = float(volume) if volume and volume > 0 else 0.0
        if s.last_volume > 0:
            s.log_volume.append(math.log(s.last_volume))
            hour = int((when % 86_400) // 3_600)
            bucket = s.volume_by_hour.setdefault(hour, [])
            bucket.append(math.log(s.last_volume))
            if len(bucket) > HOUR_KEEP:
                del bucket[: len(bucket) - HOUR_KEEP]
        s.prev_close = close
        if s.warm:
            s.latest = _features(s, when)

    def reading(self, feed: str, interval: str) -> dict[str, float]:
        """P(shock within `AHEAD` bars) for this series, and that as a multiple of the base rate.

        Absent while the series is cold or no usable model is shipped - "no opinion" is not
        "no risk"."""
        spec = frozen.load(MODEL, recipe=RECIPE, names=NAMES)
        s = self.series.get(f"{feed}|{interval}")
        if spec is None or s is None or not s.latest:
            return {}
        # The spec's own feature order, not this module's - see `frozen.vector`.
        row = frozen.vector(spec, NAMES, s.latest)
        if row is None:
            return {}
        p = frozen.Trees(spec).predict(row)
        base = float(spec.get("base_rate", 0.0))
        # The base rate is the trained model's, a constant, so it is carried inside the lift rather
        # than published on every call (`test_published` refuses a feature that never varies).
        return {
            "shock_probability": round(p, 4),
            "shock_lift": round(p / base, 3) if base > 0 else 0.0,
        }

    def forget(self, keep: set[str]) -> int:
        gone = [k for k in self.series if k.split("|", 1)[0] not in keep]
        for k in gone:
            del self.series[k]
        return len(gone)


def card_line(got: dict) -> list[str]:
    """One card line when a shock is well above its normal rate; nothing otherwise."""
    p, lift = got.get("shock_probability"), got.get("shock_lift")
    if not isinstance(p, int | float) or not isinstance(lift, int | float) or lift < CARD_LIFT:
        return []
    return [f"⚠️ shock risk next {AHEAD} bars {p:.0%} · {lift:.1f}x normal · no side"]
