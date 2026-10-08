"""Whether the envelope's bands will be touched: P(P90 touched) and P(P10 touched) in the next bars.

The envelope (`vol/envelope.py`) quotes where the *close* N bars out is likely to be. A price
crosses a band on the way more often than it closes beyond it, and how much more often is a
volatility question, which is forecastable where the direction is not.

## Why it can be seen

`research/docs/bandrace.md` labelled every 15m bar with whether the next N bars' highs reached the
production P90 and their lows the P10, and fitted gradient boosting on volatility state, recent
moves, the clock and the bands themselves. It scored the model against the same boosting on the
band distances alone (geometry), so the skill is what the market adds beyond how far away the bands
are:

- **FX:** Brier skill over geometry +0.087 / +0.059 (P90 / P10) at N = 5, calibrated within 20% by
  decile, five to seven times what memoryless walks show.
- **Metals and crypto:** skill, but badly calibrated.
- **Deriv:** nothing beyond the walks.

So this publishes it for **FX at 15m** only, and says nothing elsewhere.

## What this is

Two frozen gradient-boosted models (`touch90_fx15m`, `touch10_fx15m`), trained offline by
`models/touches_train.py` on this module's `_features` replayed over the broker's bars through the
production envelope, and retrained on a schedule by `models/retrain.py`. They are read by
`shared/frozen.py` with no dependency. If a model is missing or was trained on a different feature
recipe, nothing is published.

## What it is not

**It has no direction.** "P90 touched 38%" is not "price goes up": both bands can be touched, and
the race between them is not forecastable after costs (`bandrace.md`). It decides nothing; it is
published on the calls and printed on the cards.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field

from ...shared import frozen
from .. import rollover as ro
from ..state import Restorable

#: The bars ahead the touch is forecast for: the card's envelope horizon.
AHEAD = 5
#: The only timeframe the models were trained and measured on.
INTERVAL = "15m"
#: Bars behind the long-run volatility and its percentile, and behind vol of vol.
NORM, VOV = 500, 50
#: Bars before a series' features mean anything (the percentile's minimum history).
WARM = 250
#: The frozen models, one per band, read through `shared/frozen.py`.
MODELS = {"touch90": "touch90_fx15m", "touch10": "touch10_fx15m"}
#: What changing the meaning of an input requires bumping (the rule `breaking.RECIPE` states).
#: Bumped when the FX 15m envelope became boosted (`vol/envelope.py`): the bands the touch is
#: measured against changed, so a model trained on the history envelope's bands no longer applies.
RECIPE = "2026-09-29 touch: vol state, moves, clock, bands of the boosted envelope"

NAMES = (
    "lvol",
    "tr_pct",
    "vov",
    "r1",
    "r5",
    "r20",
    "rng",
    "hsin",
    "hcos",
    "to_weekend",
    "d90",
    "d10",
    "asym",
)
#: The geometry baseline's inputs: the bands alone. The trainer's reference, not published.
GEOMETRY = ("d90", "d10", "asym")


def applies(feed: str, interval: str) -> bool:
    """Whether a series is one the models were trained for: an FX pair at 15m."""
    return interval == INTERVAL and ro.is_fx(feed)


@dataclass(slots=True)
class Series(Restorable):
    """One FX 15m series: the history its features are read from, and its latest features."""

    prev_close: float = 0.0
    closes: deque = field(default_factory=lambda: deque(maxlen=21))
    true_ranges: deque = field(default_factory=lambda: deque(maxlen=NORM))
    sigmas: deque = field(default_factory=lambda: deque(maxlen=NORM))
    log_sigmas: deque = field(default_factory=lambda: deque(maxlen=VOV))
    #: The last few bars' **signed body ratio** - how much of each bar's range
    #: was net directional travel, positive up. Three is all the displacement
    #: rule needs and the bound is in the factory so a restore rebuilds it
    #: (`shared/state._deque_bounds`).
    bodies: deque = field(default_factory=lambda: deque(maxlen=3))
    #: The forward readings the engine already computes and nothing gated on -
    #: `vol.ensemble_bps`, `forecast_bps`, `garch_bps`, `stretch`. Supplied by
    #: `advance`, latest only, and empty when the caller offers none.
    forward: dict = field(default_factory=dict)
    latest: list[float] = field(default_factory=list)
    #: The bar last advanced over, as (when, high, low, close, sigma): what `base` reads.
    bar: list[float] = field(default_factory=list)

    @property
    def warm(self) -> bool:
        return len(self.sigmas) >= WARM and len(self.closes) > 20


#: A bar counts as impulsive when this much of its range is body, and a
#: displacement is `PUSH_N` of them in a row the same way. Both are the zone
#: rule's own numbers (`research/ideas/zones.py`), given by the desk on
#: 2026-10-07 - "for the impulsive candles make the body at least 70% of the
#: total candle range" and "the impulsive move must have at least 2 momentum
#: candles" - and kept identical here so the two subsystems mean the same thing
#: by the same word.
PUSH_BODY, PUSH_N = 0.70, 2

#: Bars the `movz` denominator looks back over. Ten, as measured.
MOVZ = 10


def _movz(values, window: int) -> float:
    """The last value in units of its own recent spread, 0.0 when there is none."""
    xs = list(values)[-window:]
    if len(xs) < 3:
        return 0.0
    mean = sum(xs) / len(xs)
    var = sum((v - mean) ** 2 for v in xs) / (len(xs) - 1)
    sd = math.sqrt(var)
    return (xs[-1] - mean) / sd if sd > 0 else 0.0


def _ratio(bps: float | None, sigma: float) -> float:
    """A bps reading against the bar's own volatility unit; 0.0 without either."""
    unit = sigma * 10_000.0
    return float(bps) / unit if bps and unit > 0 else 0.0


def base(
    s: Series, when: float, high: float, low: float, close: float, sigma: float
) -> dict[str, float]:
    """The bar's quote-free features by name - volatility state, recent moves, range, the clock.

    Shared: the touch features below are these plus the bands, and the boosted envelope's inputs
    (`vol/envelope.py`) are a subset of them. `sigma` is the production volatility unit as a log
    return; every move is measured in it, as in `bandrace.py` and `gbmenvelope.py`.
    """
    mean_tr = sum(s.true_ranges) / len(s.true_ranges)
    lvol = math.log(sigma / mean_tr) if mean_tr > 0 else 0.0
    rank = sum(1 for v in s.sigmas if v < sigma) / len(s.sigmas)
    logs = list(s.log_sigmas)
    mean_log = sum(logs) / len(logs)
    vov = (
        math.sqrt(sum((v - mean_log) ** 2 for v in logs) / (len(logs) - 1))
        if len(logs) > 1
        else 0.0
    )
    closes = list(s.closes)
    bodies = list(s.bodies)
    fwd = s.forward or {}

    def move(bars: int) -> float:
        return math.log(close / closes[-1 - bars]) / sigma

    hour = (when % 86_400) / 3_600
    # 1970-01-01 was a Thursday, 72 hours into a week that starts on Monday 00:00 UTC.
    week_hour = (when / 3_600 + 72) % 168
    return {
        "lvol": lvol,
        "tr_pct": rank,
        "vov": vov,
        "r1": move(1),
        "r5": move(5),
        "r20": move(20),
        "rng": math.log(high / low) / sigma if low > 0 else 0.0,
        "hsin": math.sin(2 * math.pi * hour / 24),
        "hcos": math.cos(2 * math.pi * hour / 24),
        "to_weekend": (4 * 24 + 21 - week_hour) % 168,
        # The UTC hour as a whole number, the boosted envelope's clock (`gbmenvelope.py`).
        "hour": float(int(hour)),
        # **The candle's own character**, asked for 2026-10-08 and carried over
        # from the zone rule, where `PUSH_BODY` is the same 0.70: a bar that is
        # nearly all body is a bar that travelled, and two of them in a row the
        # same way is a displacement. `zscore-window.md` measured the first of
        # these as worth more than the z-score it was meant to support - a 70%
        # body roughly tripled the separation at every window and threshold -
        # which is why they are offered to a volatility model rather than only
        # to the zone scan.
        # **The level against its own recent spread**, which `transforms.py`
        # measured as the best single gate of the lot - `movz` of `activity`
        # won 58.3% against a same-duty random 50.3%, p = 0.0005, ahead of the
        # raw level. A standard deviation on its own said nothing (p = 0.844);
        # it earns its place as a denominator. Here on the volatility unit,
        # which this series already keeps.
        "sigma_movz": _movz(s.sigmas, MOVZ),
        # The forward readings the engine computes and nothing gated on, each
        # against the bar's own unit so it means the same on gold as on BTC.
        "ens_ratio": _ratio(fwd.get("ensemble_bps"), sigma),
        "fc_ratio": _ratio(fwd.get("forecast_bps"), sigma),
        "garch_ratio": _ratio(fwd.get("garch_bps"), sigma),
        "vol_stretch": fwd.get("vol_stretch", 0.0),
        "body": abs(bodies[-1]) if bodies else 0.0,
        "displaced": float(
            len(bodies) >= PUSH_N
            and all(abs(b) >= PUSH_BODY for b in list(bodies)[-PUSH_N:])
            and len({b > 0 for b in list(bodies)[-PUSH_N:]}) == 1
        ),
    }


def features(
    s: Series, when: float, high: float, low: float, close: float, sigma: float, quote: list[float]
) -> list[float] | None:
    """This bar's features, in the order of `NAMES`, or None when the bands say nothing.

    `quote` is the envelope's current 5-bar P10 / P50 / P90 in the volatility unit.
    """
    q10, q50, q90 = quote
    if not (q90 > 0 > q10) or q90 <= q50 or q50 <= q10:
        return None
    got = base(s, when, high, low, close, sigma)
    return [got[name] for name in NAMES[:10]] + [q90, -q10, (q90 - q50) / (q50 - q10)]


@dataclass(slots=True)
class Touches(Restorable):
    """Every FX 15m series' feature history, read by the frozen models. See the module note."""

    series: dict[str, Series] = field(default_factory=dict)

    def observe(
        self,
        feed: str,
        interval: str,
        when: float,
        high: float,
        low: float,
        close: float,
        sigma: float,
        quote: list[float] | None,
    ) -> None:
        """One closed bar, after the envelope has quoted it: `advance`, then `hold`.

        `when` is the bar's open time, `sigma` the unit the envelope quoted in, `quote` its 5-bar
        P10 / P50 / P90 (None while it is cold).
        """
        if self.advance(feed, interval, when, high, low, close, sigma):
            self.hold(feed, interval, quote)

    def advance(
        self,
        feed: str,
        interval: str,
        when: float,
        high: float,
        low: float,
        close: float,
        sigma: float,
        forward: Mapping[str, float] | None = None,
    ) -> bool:
        """Fold one closed bar into the series' history. Returns whether it was taken.

        Before the envelope quotes, so the boosted envelope can read `base` for this bar."""
        if not applies(feed, interval) or close <= 0 or high < low or not (sigma > 0):
            return False
        key = f"{feed}|{interval}"
        s = self.series.get(key)
        if s is None:
            s = self.series[key] = Series()
        if s.prev_close > 0:
            s.true_ranges.append(
                max(high - low, abs(high - s.prev_close), abs(low - s.prev_close)) / s.prev_close
            )
        # **The body, without an open.** `advance` is never given one, and it does
        # not need one: in a continuous market a bar opens where the last closed,
        # which is the identity the zone rule is built on - "that bearish candle
        # close and the 1st displacement candle open, that is the level". So the
        # body is the close-to-close travel over the bar's own range, signed.
        if s.prev_close > 0 and high > low:
            s.bodies.append((close - s.prev_close) / (high - low))
        if forward:
            # NaN-free: a reading that is not yet warm comes through as NaN and
            # would poison every feature derived from it.
            s.forward = {k: float(v) for k, v in forward.items() if not math.isnan(float(v))}
        s.sigmas.append(sigma)
        s.log_sigmas.append(math.log(sigma))
        s.closes.append(close)
        s.prev_close = close
        s.bar = [when, high, low, close, sigma]
        s.latest = []
        return True

    def base(self, feed: str, interval: str) -> dict[str, float] | None:
        """The last advanced bar's quote-free features, or None while the series is cold."""
        s = self.series.get(f"{feed}|{interval}")
        if s is None or not s.warm or not s.true_ranges or len(s.bar) != 5:
            return None
        return base(s, *s.bar)

    def hold(self, feed: str, interval: str, quote: list[float] | None) -> None:
        """After the envelope has quoted the last advanced bar: hold its touch features."""
        s = self.series.get(f"{feed}|{interval}")
        if s is None or len(s.bar) != 5:
            return
        s.latest = []
        if s.warm and quote is not None and s.true_ranges:
            s.latest = features(s, *s.bar, quote) or []

    def reading(self, feed: str, interval: str) -> dict[str, float]:
        """P(P90 touched) and P(P10 touched) within `AHEAD` bars, and the models' base rates.

        Absent for series the models were not trained for, while cold, and when no usable model
        is shipped."""
        if not applies(feed, interval):
            return {}
        s = self.series.get(f"{feed}|{interval}")
        if s is None or not s.latest:
            return {}
        out: dict[str, float] = {}
        for band, name in MODELS.items():
            spec = frozen.load(name, recipe=RECIPE, names=NAMES)
            if spec is None:
                return {}
            out[f"{band}_prob{AHEAD}"] = round(frozen.Trees(spec).predict(s.latest), 4)
        return out

    def forget(self, keep: set[str]) -> int:
        gone = [k for k in self.series if k.split("|", 1)[0] not in keep]
        for k in gone:
            del self.series[k]
        return len(gone)


#: How often each boosted band is touched within the next `AHEAD` bars, measured on the 90-day
#: out-of-sample block (P90 0.20, P10 0.21-0.24). Over the boosted bands the rate barely moves with
#: the regime - they already carry it - and the touch models did not beat this constant by 0.03
#: (research/docs/gbm-envelope.md, the touch contest on 2026-09-30), so the card states it.
BOOSTED_TOUCH_RATE = 0.20


def card_line(got: dict) -> list[str]:
    """The chance each band is touched in the next bars, as a card line.

    A trained model's per-signal probabilities where one has passed its gate; otherwise, on a
    boosted band, the measured constant; nothing otherwise.
    """
    up, down = got.get(f"touch90_prob{AHEAD}"), got.get(f"touch10_prob{AHEAD}")
    if isinstance(up, int | float) and isinstance(down, int | float):
        return [f"👆 next {AHEAD} bars · P90 touched {up:.0%} · P10 touched {down:.0%}"]
    if got.get(f"env{AHEAD}_model"):
        return [
            f"👆 each band is touched about {BOOSTED_TOUCH_RATE:.0%} of the time "
            f"within the next {AHEAD} bars"
        ]
    return []
