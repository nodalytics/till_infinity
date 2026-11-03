"""Does a fear or greed label on a level's *formation* carry anything?

A level formed at a down-crash is a fear level, one formed at an up-spike is a
greed level, one formed along a trend run is neither. The label is a property
of the **bar shape that produced the level**, not of any sentiment source -
there is no sentiment feed in this store, so shape is the proxy.

## Real legs only, and that is a measurement not a preference

Every level book here reads a bar's high and low, and a synthetic cross's
extremes are bounds inflated about 1.7x on the JPY pairs: on audjpy the median
body-over-range is 0.268 against audusd's 0.463 and `levels.chains` finds **4
displacement legs in 19 years against 83**. A displacement label on a cross
would be a label on the bound. So this study runs on the eight real legs, and
the crosses carry the close-exact questions (`fear_greed_asym`,
`fear_greed_trade`) instead.

## The pre-registered prediction, which is sharp

The desk's own results make a specific prediction rather than a hopeful one.
`topology-restates-volatility` has levels, ranges and shapes all null once
volatility is stratified; `auc-is-free-on-volatility-targets` reads 0.805 on a
constant-volatility process and 0.525 within strata. A crash is a big bar, big
bars cluster, so conditioning on one **selects on volatility**. So:

1. the raw fear-minus-greed hold gap is **non-zero**, and
2. it is **the volatility term**: it goes away within quintiles of trailing
   compression, and
3. `directional_off` carries nothing **pooled** - but the interaction, direction
   inside a volatility state, is the open question and is reported, not assumed.

A result that contradicted (2) would be the finding. The test is **two-sided**
on the label gap, because unlike `level-shield.md`'s barrier claim the framing
does not fix a sign: a panic low might be defended harder or blown through, and
pretending to have pre-stated one would be choosing it after the fact.

## What a finding has to survive

* the real gap **outside the range of the hardest null arm's draws** - every
  arm replays the same book over the same bar geometry, which is what
  `null-structure-claims-on-the-same-detector` asks;
* the sign consistent across a majority of the eight legs and across both
  intervals;
* present **within strata**, not only pooled;
* Benjamini-Hochberg over every cell - 4 books x 8 legs x 3 contrasts is 96
  cells and picking the best of them gives a winner every time;
* and the **shuffled twin** named first, because a crash-formed level sits where
  a big down bar printed and `bar-shuffle` keeps every bar's own shape. If
  crash-formed levels hold differently on a shuffle, the difference is bar
  shape and not path.
"""

from __future__ import annotations

import numpy as np

import research.ideas.fear_greed as F
from till_infinity.indicators import BjorgumLevels, Levels, Pips, Pivots
from till_infinity.indicators.levels import (
    FORGET_BARS,
    KEEP,
    MERGE_VOL,
    TOUCH_NOISE_VOL,
)
from till_infinity.indicators.trend import REACH

#: The level kinds, every one at its own module defaults. **Nothing here is
#: tuned for this study**: `Levels` at `reach` 3 / `keep` 24 / `merge_vol` 0.35
#: is the book a strategy on this desk reads, `BjorgumLevels.measured()` is the
#: constructor carrying this repo's own measured parameters, `Pips` is at
#: `DEFAULT_COUNT` 12 / `DEFAULT_SPAN` 240, and `Pivots` is the
#: **no-parameter control** - arithmetic on the prior period's range, nothing
#: to fit. If the fitted books do not beat `Pivots`, the fitting is not earning
#: its complexity.
BOOKS: tuple[str, ...] = ("levels", "bjorgum", "pips", "pivots")

#: How close a bar has to come to count as touching the level, in volatility
#: units. `levels.TOUCH_NOISE_VOL`, the repo's own, so a touch here is a touch
#: there.
TOUCH_VOL = TOUCH_NOISE_VOL


class _Bar:
    """What a level book reads off a bar, and nothing else.

    A Nautilus `Bar` carries fixed-precision `Price` objects and a bar type;
    building five million of them to drive an indicator costs more than the
    measurement. `indicators/bars.read` is duck-typed through `float()`, and
    `Candles` reads `is_revision`, so this is the same input by every path that
    matters.
    """

    __slots__ = ("close", "high", "is_revision", "low", "open", "ts_event", "volume")

    def __init__(self, o: float, h: float, lo: float, c: float, ts: float) -> None:
        self.open, self.high, self.low, self.close = o, h, lo, c
        self.volume = 0.0
        self.ts_event = int(ts * F.NANOS)
        self.is_revision = False


def _build(book: str, unit_span: int):
    if book == "levels":
        return Levels(
            reach=REACH,
            keep=KEEP,
            merge_vol=MERGE_VOL,
            touch_noise_vol=TOUCH_NOISE_VOL,
            forget=FORGET_BARS,
            span=240,
            unit_span=unit_span,
        )
    if book == "bjorgum":
        return BjorgumLevels.measured()
    if book == "pips":
        return Pips()
    if book == "pivots":
        return Pivots()
    raise ValueError(f"{book!r} is not one of {BOOKS}")


def _prices(book: str, ind) -> list[float]:
    """The book's current level prices, however that book publishes them.

    One function because the four books have four different shapes - a Kalman
    estimate, a zone with a width, a perceptually important point, a computed
    pivot set - and the study's question is about the *price*, so the shapes
    are reduced here once rather than at each call site.
    """
    if book == "levels":
        when = ind.when
        return [lv.at(when) for lv in ind.levels]
    if book == "bjorgum":
        return [z.mid for z in (list(ind.resistance) + list(ind.support))]
    if book == "pips":
        return [p.price for p in list(ind.points)]
    if book == "pivots":
        return sorted(ind.set_for("daily").values())
    raise ValueError(f"{book!r} is not one of {BOOKS}")


def formations(
    series: F.Series, book: str, unit: np.ndarray, *, unit_span: int
) -> dict[str, np.ndarray]:
    """Every level the book publishes, stamped with the bar it first appeared on.

    A level is "formed" at the first bar its price is in the book and was not
    in the book before, matched within `TOUCH_VOL` units so a Kalman estimate
    drifting by a tenth of a unit is the same level rather than a new one.
    Causal by construction: every book here only publishes a level once its
    pivot has confirmed, so the formation bar is the bar a strategy could first
    have read it on.
    """
    ind = _build(book, unit_span)
    seen: list[float] = []
    out_price: list[float] = []
    out_at: list[int] = []
    for i in range(len(series.close)):
        ind.handle_bar(
            _Bar(
                float(series.open[i]),
                float(series.high[i]),
                float(series.low[i]),
                float(series.close[i]),
                float(series.ts[i]),
            )
        )
        scale = float(unit[i])
        if not np.isfinite(scale) or scale <= 0.0:
            continue
        now = [p for p in _prices(book, ind) if np.isfinite(p) and p > 0.0]
        tol = TOUCH_VOL * scale
        for price in now:
            if any(abs(price - old) <= tol for old in seen):
                continue
            out_price.append(price)
            out_at.append(i)
        seen = now
    return {
        "price": np.asarray(out_price, dtype=float),
        "at": np.asarray(out_at, dtype=np.int64),
    }


def outcomes(
    series: F.Series,
    unit: np.ndarray,
    found: dict[str, np.ndarray],
    *,
    horizon: int,
) -> dict[str, np.ndarray]:
    """For each level: whether price touched it, and whether it then held.

    **Held** means the close `horizon` bars after the first touch is still on
    the side the level was approached from. Broken means it is beyond. A level
    never touched inside `horizon` bars from formation is reported as
    untouched, which is a third outcome and not a hold - counting it as one
    would make a level nobody tested look like a level that worked.

    `a-return-rate-is-geometry` is why the statistic used downstream is always
    a **difference between label classes on the same series** rather than a
    hold rate on its own: a walk reads 0.825 where `fade-to-value` read 0.82,
    and only a contrast within one series cancels that.
    """
    n = len(series.close)
    price, at = found["price"], found["at"]
    touched = np.zeros(len(price), dtype=bool)
    held = np.zeros(len(price), dtype=bool)
    touch_at = np.full(len(price), -1, dtype=np.int64)
    above = np.zeros(len(price), dtype=np.int8)
    for k in range(len(price)):
        start = int(at[k])
        level = float(price[k])
        scale = float(unit[start])
        if not np.isfinite(scale) or scale <= 0.0:
            continue
        # The side the level sits on at formation. A level price is already
        # inside the formation bar's range for several of these books, so the
        # side is taken from the **close**, and a level the close sits exactly
        # on is skipped rather than assigned a side by rounding.
        here = float(series.close[start])
        if abs(here - level) <= 1e-12:
            continue
        side = 1 if level > here else -1
        above[k] = side
        tol = TOUCH_VOL * scale
        stop = min(n, start + horizon + 1)
        for i in range(start + 1, stop):
            if series.low[i] - tol <= level <= series.high[i] + tol:
                touched[k] = True
                touch_at[k] = i
                break
        if not touched[k]:
            continue
        end = min(n - 1, int(touch_at[k]) + horizon)
        after = float(series.close[end])
        # Held: the close is back on the approach side of the level.
        held[k] = (after - level) * side < 0.0
    return {"touched": touched, "held": held, "touch_at": touch_at, "side": above}


def de_overlap(at: np.ndarray, touch_at: np.ndarray, horizon: int) -> np.ndarray:
    """A greedy non-overlapping subset: no two outcome windows share a bar.

    `overlapping-outcome-windows-leak` is the recorded failure - a short skip
    rule with a long forward window gave direction AUC 0.79 that collapsed to
    0.51, and the tell was the placebo and shuffled arms tracking it. Reported
    beside the dense version with a day-block bootstrap, never instead of it,
    because de-overlapping throws away most of the sample.
    """
    order = np.argsort(at, kind="stable")
    keep = np.zeros(len(at), dtype=bool)
    free = -1
    for k in order:
        begin = int(touch_at[k]) if touch_at[k] >= 0 else int(at[k])
        if begin <= free:
            continue
        keep[k] = True
        free = begin + horizon
    return keep


def auc(score: np.ndarray, label: np.ndarray) -> float:
    """Rank AUC of `score` for the boolean `label`, or nan without both classes.

    The Mann-Whitney form, so ties count a half - which matters here because
    the basket index is a mean of five bounded components and reads exact
    repeats more often than a continuous score would.
    """
    good = np.isfinite(score)
    score, label = score[good], label[good]
    pos, neg = score[label], score[~label]
    if len(pos) < 2 or len(neg) < 2:
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]), kind="stable")
    ranks = np.empty(len(order), dtype=float)
    ranks[order] = np.arange(1, len(order) + 1)
    # Average ranks within ties, so a block of equal scores reads 0.5.
    values = np.concatenate([pos, neg])[order]
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[j + 1] == values[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = ranks[order[i : j + 1]].mean()
        i = j + 1
    total = ranks[: len(pos)].sum()
    return float((total - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg)))


def one_series(
    series: F.Series,
    basket: F.Basket,
    *,
    book: str,
    unit_span: int,
    horizon: int,
) -> dict:
    """The label table for one series, one book, one arm.

    Pooled, within compression quintiles, de-overlapped, and with the two
    halves' AUC for the hold - every one of which is required before a number
    here means anything.
    """
    unit = F.unit_for(series, unit_span)
    found = formations(series, book, unit, unit_span=unit_span)
    got = outcomes(series, unit, found, horizon=horizon)
    labels = F.shape_labels(series)
    comp = F.compression(series, unit_span)
    out: dict = {
        "feed": series.feed,
        "book": book,
        "levels": int(len(found["price"])),
        "touched": int(got["touched"].sum()),
        "shares": {},
        "hold": {},
        "strata": {},
        "deoverlapped": {},
        "auc": {},
    }
    if not got["touched"].any():
        return out
    at = found["at"]
    label = labels[at]
    live = got["touched"]
    held = got["held"]
    for code, name in F.LABELS.items():
        out["shares"][name] = float((label == code).mean())
        keep = live & (label == code)
        out["hold"][name] = {
            "n": int(keep.sum()),
            "rate": float(held[keep].mean()) if keep.any() else float("nan"),
        }
    bins = F.strata(comp[at], 5)
    for code, name in F.LABELS.items():
        rows = []
        for q in range(5):
            keep = live & (label == code) & (bins == q)
            if keep.sum() >= 10:
                rows.append(float(held[keep].mean()))
        out["strata"][name] = {
            "quintiles": rows,
            "mean": float(np.mean(rows)) if rows else float("nan"),
            "cells": len(rows),
        }
    thin = de_overlap(at, got["touch_at"], horizon)
    for code, name in F.LABELS.items():
        keep = live & thin & (label == code)
        out["deoverlapped"][name] = {
            "n": int(keep.sum()),
            "rate": float(held[keep].mean()) if keep.sum() >= 10 else float("nan"),
        }
    for name in ("risk_off", "volatile_off", "directional_off"):
        out["auc"][name] = {
            "pooled": auc(getattr(basket, name)[at][live], held[live]),
            "within_strata": _auc_within(
                getattr(basket, name)[at][live], held[live], bins[live]
            ),
        }
    out["gaps"] = _gaps(out)
    return out


def _auc_within(score: np.ndarray, label: np.ndarray, bins: np.ndarray) -> float:
    """AUC averaged over compression quintiles, weighted by cell size.

    The number `auc-is-free-on-volatility-targets` says to report: that entry
    records 0.805 on a constant-volatility process against 0.525 within
    strata, so a pooled AUC on a volatility-linked target is close to
    uninformative on its own.
    """
    got: list[tuple[float, int]] = []
    for q in np.unique(bins):
        if q < 0:
            continue
        keep = bins == q
        if keep.sum() < 20:
            continue
        value = auc(score[keep], label[keep])
        if np.isfinite(value):
            got.append((value, int(keep.sum())))
    if not got:
        return float("nan")
    total = sum(w for _, w in got)
    return float(sum(v * w for v, w in got) / total)


def _gaps(row: dict) -> dict:
    """fear minus greed, and each against the run class, pooled and in strata.

    Three contrasts rather than one, because "crash levels differ from spike
    levels" and "crash levels differ from ordinary ones" are different claims
    and a single number cannot carry both. `nan` where a class is empty, never
    0.0: `absent-is-not-zero`, and a zero gap is a legitimate reading.
    """
    out: dict[str, float] = {}
    field = {"hold": "rate", "strata": "mean", "deoverlapped": "rate"}
    name = {"hold": "pooled", "strata": "strata", "deoverlapped": "thin"}
    for where, key in field.items():
        rates = {
            cls: float(row[where].get(cls, {}).get(key, float("nan")))
            for cls in ("crash", "spike", "run")
        }
        tag = name[where]
        out[f"fear_minus_greed_{tag}"] = rates["crash"] - rates["spike"]
        out[f"fear_minus_run_{tag}"] = rates["crash"] - rates["run"]
        out[f"greed_minus_run_{tag}"] = rates["spike"] - rates["run"]
    return out
