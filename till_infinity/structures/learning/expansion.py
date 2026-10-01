"""The compression-to-expansion alert: from a quiet market, will volatility break out soon?

## What it answers, and what it does not

A series is **compressed** when its 14-bar true range sits in the bottom fifth of its last 1,500
bars. From there, does that range reach the top fifth within the next `AHEAD` bars? This reads the
probability, as a multiple of the base rate, and puts a line on the card when it is high.

It says **nothing about the side**. Among compressed moments that did expand, every model tested
called the direction at a coin (AUC 0.47-0.53, `research/docs/fractal-twins.md`), and the card says
so. It is a risk and timing reading: size, stops, and direction-free entries, not a call.

## Where it comes from

`research/docs/fractal-twins.md` found it with gradient boosting on 288 raw window values (AUC 0.728
at 15m, 0.738 at 1h; about 3x the base rate in the top decile). Production keeps compact running
state instead of windows, so the features below are the same information in summary form:
compression depth and duration, short against long range, the volatility of volatility, the last
bar, how directional the last 16 bars were, the clock, the next timeframe up, and tick volume.
`research/docs/expansion.md` re-validates it on these features against walks we generate.

## Model

A frozen gradient-boosted classifier (`shared/frozen.py`), trained offline by
`models/expansion_train.py` through this class itself, and retrained by the fortnightly contest
(`models/retrain.py`). Without a usable model file the reading is absent: no opinion, not no risk.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right, insort
from collections import deque
from dataclasses import dataclass, field

from ...shared import frozen
from ..state import Restorable
from .shocks import _log, _z

MODEL = "expansion"
RECIPE = "2026-10-01b compression state, range, clock, calendar ahead, higher timeframe, volume"

#: Bars ahead the expansion must arrive within.
AHEAD = 16
#: The percentile window, the true range's smoothing, and the two thresholds.
WINDOW = 1_500
SMOOTH = 14
COMPRESSED = 0.2
EXPANDED = 0.8
#: Percentiles needed before a series is read at all.
WARM = 300
#: The timeframes it is trained and read on, and the one above each that informs it.
INTERVALS = ("15m", "1h")
#: Scored and read on 15m and 1h. A pooled model over 4h and 1d as well failed the gate there
#: (held-out 0.651 and 0.633, against >= 0.68 in both halves) and cost 15m 0.014; a model of its
#: own for the slow intervals is a separate trial (research/docs/expansion.md).
UP = {"15m": "1h", "1h": "4h"}
#: A card line from this multiple of the base rate: about the top decile in research.
CARD_LIFT = 2.5

NAMES = (
    "pct",
    "depth",
    "run_log",
    "fast_slow",
    "tr_ratio",
    "vol_of_vol",
    "last_range",
    "efficiency",
    "hour_sin",
    "hour_cos",
    "to_weekend",
    "interval_log",
    "up_pct",
    "volume_z",
    "volume_z_hour",
    # research/docs/expansion.md, precursors: the one sensor besides compression that adds (+0.017
    # AUC in both halves) - the series' own weekday x hour range profile over the next AHEAD bars
    # against the last AHEAD. The calendar is known in advance: a quiet session with a busier one
    # coming expands by the clock alone.
    "clock_ahead",
)

#: The weekday x hour profile: slots of the UTC week, the most observations a slot's mean weighs
#: (after that it moves like an average of the last SLOT_KEEP), and the fewest it needs to count.
SLOTS, SLOT_KEEP, SLOT_WARM = 168, 200, 5

VOLUME_WARM = 50
HOUR_KEEP, HOUR_WARM = 60, 10


def applies(interval: str) -> bool:
    return interval in INTERVALS or interval in UP.values()


@dataclass(slots=True)
class Series(Restorable):
    """One (feed, interval): its smoothed range history, the compression run, and its features."""

    seconds: float = 0.0
    prev_close: float = 0.0
    slow: float = 0.0  # true range, smoothed over SMOOTH bars (the research definition)
    fast: float = 0.0  # the same over 4 bars
    history: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    #: The same values kept sorted, so a percentile is a bisection rather than a scan.
    ranked: list = field(default_factory=list)
    total: float = 0.0
    log_tr: deque = field(default_factory=lambda: deque(maxlen=50))
    closes: deque = field(default_factory=lambda: deque(maxlen=AHEAD + 1))
    abs_moves: deque = field(default_factory=lambda: deque(maxlen=AHEAD))
    pct: float = float("nan")
    run: int = 0
    depth: float = 1.0
    last_range: float = 0.0
    log_volume: deque = field(default_factory=lambda: deque(maxlen=500))
    volume_by_hour: dict[int, list[float]] = field(default_factory=dict)
    last_volume: float = 0.0
    #: Mean log true range by hour of the UTC week, and how many bars each mean has seen.
    slot_mean: list = field(default_factory=lambda: [0.0] * SLOTS)
    slot_n: list = field(default_factory=lambda: [0] * SLOTS)
    latest: list[float] = field(default_factory=list)

    @property
    def warm(self) -> bool:
        return len(self.history) >= WARM

    @property
    def compressed(self) -> bool:
        return self.warm and self.pct <= COMPRESSED


def slot(t: float) -> int:
    """Hour of the UTC week, Monday 00:00 = 0. 1970-01-01 was a Thursday, 72 hours in."""
    return int((t / 3_600 + 72) % 168)


def clock_ahead(s: Series, when: float) -> float:
    """log(profile over the next AHEAD bars / profile over the last AHEAD), from bar opens; NaN
    until most of both windows' slots have been seen."""
    if s.seconds <= 0:
        return float("nan")

    def level(starts) -> float:
        got = [math.exp(s.slot_mean[slot(t)]) for t in starts if s.slot_n[slot(t)] >= SLOT_WARM]
        return sum(got) / len(got) if len(got) >= 0.75 * AHEAD else float("nan")

    ahead = level(when + k * s.seconds for k in range(AHEAD))
    behind = level(when - (k + 1) * s.seconds for k in range(AHEAD))
    if math.isnan(ahead) or math.isnan(behind) or behind <= 0:
        return float("nan")
    return math.log(ahead / behind)


def percentile(value: float, ranked: list) -> float:
    """Share of the sorted `ranked` at or below `value` (pandas' `rank(pct=True)`, ties at max)."""
    return bisect_right(ranked, value) / len(ranked)


def _push(s: Series, value: float) -> None:
    """Append to the window, keeping its sorted copy and running sum in step."""
    if len(s.history) == WINDOW:
        old = s.history[0]
        del s.ranked[bisect_left(s.ranked, old)]
        s.total -= old
    s.history.append(value)
    insort(s.ranked, value)
    s.total += value


@dataclass(slots=True)
class Expansion(Restorable):
    """Every series' compression state, read by the frozen model. See the module note."""

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
        """One closed bar, `when` being its close time."""
        if not applies(interval) or close <= 0 or high < low:
            return
        key = f"{feed}|{interval}"
        s = self.series.get(key)
        if s is None:
            s = self.series[key] = Series(seconds=seconds)
        if s.prev_close <= 0:
            s.prev_close = close
            s.closes.append(close)
            return
        lh, ll, lp = math.log(high), math.log(low), math.log(s.prev_close)
        tr = max(lh - ll, abs(lh - lp), abs(ll - lp))
        s.slow = tr if s.slow <= 0 else s.slow + (tr - s.slow) / SMOOTH
        s.fast = tr if s.fast <= 0 else s.fast + (tr - s.fast) / 4.0
        _push(s, s.slow)
        s.log_tr.append(math.log(tr) if tr > 0 else -20.0)
        s.abs_moves.append(abs(math.log(close / s.prev_close)))
        if tr > 0:
            k = slot(when - seconds)  # the bar's own hour, by its open
            s.slot_n[k] = min(s.slot_n[k] + 1, SLOT_KEEP)
            s.slot_mean[k] += (math.log(tr) - s.slot_mean[k]) / s.slot_n[k]
        s.closes.append(close)
        s.last_range = (lh - ll) / s.slow if s.slow > 0 else 0.0
        s.last_volume = float(volume) if volume and volume > 0 else 0.0
        if s.last_volume > 0:
            s.log_volume.append(math.log(s.last_volume))
            bucket = s.volume_by_hour.setdefault(int((when % 86_400) // 3_600), [])
            bucket.append(math.log(s.last_volume))
            if len(bucket) > HOUR_KEEP:
                del bucket[: len(bucket) - HOUR_KEEP]
        s.prev_close = close
        if not s.warm:
            return
        s.pct = percentile(s.slow, s.ranked)
        if s.pct <= COMPRESSED:
            s.depth = min(s.depth, s.pct) if s.run else s.pct
            s.run += 1
        else:
            s.run, s.depth = 0, 1.0
        up = self.series.get(f"{feed}|{UP.get(interval, '')}")
        s.latest = _features(s, when, up)

    def reading(self, feed: str, interval: str) -> dict[str, float]:
        """P(expansion within `AHEAD` bars) while compressed, and that over the base rate.

        Absent when the series is not compressed, is cold, or no usable model is shipped."""
        s = self.series.get(f"{feed}|{interval}")
        if s is None or not s.latest or not s.compressed or interval not in INTERVALS:
            return {}
        spec = frozen.load(MODEL, recipe=RECIPE, names=NAMES)
        if spec is None:
            return {}
        p = frozen.Trees(spec).predict(s.latest)
        base = float(spec.get("base_rate", 0.0))
        return {
            "expansion_probability": round(p, 4),
            "expansion_lift": round(p / base, 3) if base > 0 else 0.0,
        }

    def forget(self, keep: set[str]) -> int:
        gone = [k for k in self.series if k.split("|", 1)[0] not in keep]
        for k in gone:
            del self.series[k]
        return len(gone)


def _features(s: Series, when: float, up: Series | None) -> list[float]:
    mean = s.total / len(s.history)
    logs = list(s.log_tr)
    mean_log = sum(logs) / len(logs)
    vol_of_vol = math.sqrt(sum((v - mean_log) ** 2 for v in logs) / len(logs))
    path = sum(s.abs_moves)
    efficiency = (
        abs(math.log(s.closes[-1] / s.closes[0])) / path if path > 0 and len(s.closes) > 1 else 0.0
    )
    hour = (when % 86_400) / 3_600
    week_hour = (when / 3_600 + 72) % 168
    to_close = (4 * 24 + 21 - week_hour) % 168
    return [
        s.pct,
        s.depth if s.run else s.pct,
        math.log1p(s.run),
        math.log(s.fast / s.slow) if s.fast > 0 and s.slow > 0 else 0.0,
        math.log(s.slow / mean) if s.slow > 0 and mean > 0 else 0.0,
        vol_of_vol,
        s.last_range,
        efficiency,
        math.sin(2 * math.pi * hour / 24),
        math.cos(2 * math.pi * hour / 24),
        math.log1p(to_close),
        math.log(s.seconds) if s.seconds > 0 else 0.0,
        up.pct if up is not None and up.warm else float("nan"),
        _z(_log(s.last_volume), s.log_volume, VOLUME_WARM),
        _z(_log(s.last_volume), s.volume_by_hour.get(int(hour), ()), HOUR_WARM),
        clock_ahead(s, when),
    ]


def card_line(got: dict) -> list[str]:
    """One card line when an expansion out of compression is well above its normal rate."""
    p, lift = got.get("expansion_probability"), got.get("expansion_lift")
    if not isinstance(p, int | float) or not isinstance(lift, int | float) or lift < CARD_LIFT:
        return []
    return [f"🌀 coiled · expansion next {AHEAD} bars {p:.0%} · {lift:.1f}x normal · no side"]
