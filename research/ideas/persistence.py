"""Does motion persist - contiguous activity, and whether a pull origin confirms.

Two questions from the operator, 2026-11-17, on one machine because they are
the same question with two labels:

* **"Can we estimate or predict sequential volatility - for the next N candles
  there will be continuous volatility, with no or very little stalling?"** Not
  the *size* of the next N bars, which [`expansion.md`](../docs/expansion.md)
  already calls at AUC 0.781 from compression, but their **contiguity**: a
  window holding one three-ATR bar and fifteen dead ones has the same mean
  range as one that moves on every bar, and only the second is tradable.
* **"Can we predict when a pull origin is about to reverse?"** The operator's
  own detector, quoted below. Its first two clauses are known at the candle's
  close and its last two are the forward confirmation, so the question has an
  exact form: **at a candle that is already a 15-bar pivot with a 1.5-ATR fall
  into it, can anything call whether the 3-ATR directional rise follows?**

The detector, as supplied (bullish; bearish is the mirror):

1. a real low - the candle's low is the lowest of the 15 candles before it;
2. price fell into it - at least 1.5 ATR within the previous 24 candles;
3. a strong move away - within the next 24 candles price rises at least 3 ATR
   from that low without going below it;
4. the rise is directional - it covers a good share of its own back-and-forth,
   or it includes a big strong-bodied displacement candle.

Clauses 1 and 2 define the **candidate set**, which is the universe this study
measures in. That matters more than it looks:
[`turns-fast.md`](../docs/turns-fast.md)'s better-looking first attempt scored
0.66 with a universe gate that kept **94.1% of bars**, which is the series and
not a comparison set, and its label was a **fixed** drop that current
volatility predicts almost by construction.

**Both questions have the same incumbent, and that incumbent is why this file
exists.** [`turns.md`](../docs/turns.md) called a major turn at AUC 0.595 and
says `vol` alone carries it; `turns-fast.md` ported that to an hourly clock and
read 0.5457. So the only number worth reporting is the one measured *inside* a
volatility stratum, and `auc-is-free-on-volatility-targets` puts a size on why:
a volatility-shaped target reads AUC 0.805 on a constant-volatility process and
0.525 within strata.

The arms, and what each is for:

* `real` against `shuffled` - whole days reordered, each bar's own shape
  intact, and **a valid null for the pull question and not for continuity.**
  For the pull question it removes the one thing the detector is about: that
  the fall into the candle and the rise out of it are the same market. For
  continuity at 15m it removes almost nothing - the backward and forward
  windows are 16 bars either side of a decision inside a **96-bar preserved
  day** - and worse, it *decouples the hour from the prices*, which removes a
  confound rather than the effect. Measured: on shuffled 15m bars the memory
  set reads **0.7854 within the hour** against the real arm's 0.6121, so the
  shuffled market is the *more* predictable one. Reported, not used as a
  verdict. The arms that do decide continuity are the within-hour AUC and the
  Step Index.
* `base`, then `clock`, then `full` - volatility and the arrival geometry
  first, then the hour, then the candle and the path. **The lift of `full` over
  `base` is the whole claim.**
* **Step Index must read nothing.** Deriv generates it with a fixed step, so
  there is no volatility clustering in it to find; a harness reporting
  persistence there is reporting its own estimation error.
  `clocks-must-pass-an-iid-control` is the precedent - range time looked best
  on 8 of 8 markets and invented clustering at 5.3x on a specified process.
* `--plant`, an effect of known size swept, so the null has a resolution.

Run as:

    uv run python research/ideas/persistence.py --target continuity
    uv run python research/ideas/persistence.py --target pull --frame 1h
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reactive_zones import (  # noqa: E402
    CATALOGUE,
    Candles,
    atr,
    fold,
    load,
    load_csv,
    shuffled,
    window,
)

SYMBOLS = ("EURUSD", "GBPUSD", "GOLD", "USDJPY", "AUDUSD")

#: The regime window. A **trailing** rank, never a global quantile: a global
#: one labels the past with the future, which is the fault `impulse-vol.md`
#: records and the reason its state is a trailing rank too.
REGIME = 480

#: Feature sets. `base` is the incumbent both prior turn studies found was
#: carrying their result on its own, so it is what `full` has to beat.
SETS = {
    "continuity": {
        "base": ("atr_q", "atr_ratio"),
        # **The clock and the recent activity are two readings of one thing.**
        # On day-shuffled bars, where the hour is decoupled from the prices,
        # `memory` alone reaches 0.8148 within strata while `clock` reads
        # 0.5526; on the real series `clock` alone reads 0.8734 and the memory
        # terms add 0.015 on top. Both are measuring the diurnal activity
        # cycle, so each set is reported rather than one being chosen.
        "memory": (
            "past_stalls",
            "past_worst_run",
            "past_travel",
            "past_efficiency",
            "tr_cv",
            "last_tr",
        ),
        "clock": ("atr_q", "atr_ratio", "hour_sin", "hour_cos", "dow"),
        "full": (
            "atr_q",
            "atr_ratio",
            "hour_sin",
            "hour_cos",
            "dow",
            "past_stalls",
            "past_worst_run",
            "past_travel",
            "past_efficiency",
            "tr_cv",
            "last_tr",
        ),
    },
    "pull": {
        # `approach`, `remaining` and `cushion` are in the base set
        # deliberately, and `remaining` is the one that matters. The label is
        # "price reaches the origin plus 3 ATR", and at the decision bar price
        # is already at that bar's **close** - so `3 - (close - low) / ATR` is
        # how much of the target is left, and a model holding the bar's size
        # and where in its range it closed can compute it exactly. Left out of
        # the incumbent it read as a 0.15 AUC lift for candle shape, which is
        # the arithmetic of the chosen target and not a forecast of anything.
        # `cushion` is the same point for the other clause: the distance to the
        # origin is the distance the "without going below it" test allows.
        "base": ("atr_q", "atr_ratio", "approach", "remaining", "cushion"),
        "clock": (
            "atr_q",
            "atr_ratio",
            "approach",
            "remaining",
            "cushion",
            "hour_sin",
            "hour_cos",
            "dow",
        ),
        "full": (
            "atr_q",
            "atr_ratio",
            "approach",
            "remaining",
            "cushion",
            "hour_sin",
            "hour_cos",
            "dow",
            "approach_efficiency",
            "fall_bars",
            "pivot_strength",
            "reject_wick",
            "body_ratio",
            "close_in_range",
            "bar_size",
            "range_pos",
            "round_dist",
            "past_travel",
            "past_efficiency",
            "tr_cv",
            "last_tr",
        ),
    },
}


def true_range(bars: Candles) -> np.ndarray:
    """Wilder's true range, with the first bar's range as its own."""
    previous = np.concatenate(([bars.close[0]], bars.close[:-1]))
    return np.maximum(
        bars.high - bars.low,
        np.maximum(np.abs(bars.high - previous), np.abs(bars.low - previous)),
    )


def trailing_rank(values: np.ndarray, span: int = REGIME) -> np.ndarray:
    """Share of the previous `span` readings this one exceeds, causally.

    The window **ends at the previous bar** so a reading never ranks itself.
    """
    n = values.size
    out = np.full(n, np.nan)
    if n <= span:
        return out
    stack = np.lib.stride_tricks.sliding_window_view(values[:-1], span)
    here = values[span:]
    with np.errstate(invalid="ignore"):
        out[span:] = (stack < here[:, None]).sum(axis=1) / float(span)
    return out


def windowed(values: np.ndarray, span: int) -> np.ndarray:
    """`values` as rows of `span`, row `i` holding `values[i - span + 1 .. i]`.

    Everything computed from row `i` is therefore known at the close of bar
    `i`. Rows before `span - 1` are NaN.
    """
    n = values.size
    out = np.full((n, span), np.nan)
    if n < span:
        return out
    out[span - 1 :] = np.lib.stride_tricks.sliding_window_view(values, span)
    return out


def rolling(values: np.ndarray, span: int, kind: str, offset: int = 0) -> np.ndarray:
    """Rolling min or max over `span` values ending `offset` bars before each bar.

    `offset=1` is "the 15 candles **before** it" and `offset=0` includes the
    bar itself, which is the difference between the detector's clause 1 and its
    clause 2. Padded with NaN rather than aggregated with `np.nanmin`, which
    warns on the leading all-NaN rows and costs a minute of reading the log to
    decide the warnings were harmless.
    """
    n = values.size
    out = np.full(n, np.nan)
    need = span + offset
    if n < need:
        return out
    view = np.lib.stride_tricks.sliding_window_view(values, span)
    taken = view[: n - need + 1]
    out[need - 1 :] = taken.min(axis=1) if kind == "min" else taken.max(axis=1)
    return out


def longest_run(flags: np.ndarray) -> np.ndarray:
    """Longest run of True along each row.

    Written out rather than reached for: the obvious vectorisation counts
    transitions, which gives the *number* of runs and not the longest, and
    "very little stalling" is a claim about the longest one.
    """
    rows, span = flags.shape
    out = np.zeros(rows, dtype=np.int32)
    run = np.zeros(rows, dtype=np.int32)
    for j in range(span):
        run = np.where(flags[:, j], run + 1, 0)
        out = np.maximum(out, run)
    return out


def readings(bars: Candles, horizon: int, stall: float) -> dict[str, np.ndarray]:
    """Every feature, aligned to the bar it is known at the close of.

    The backward half of each forward quantity is here on purpose: the natural
    predictor of "the next sixteen bars keep moving" is "the last sixteen did",
    and a model's lift reported without that term in it has not measured
    anything the operator could not read off the chart.
    """
    band = atr(bars)
    tr = true_range(bars)
    rows = windowed(tr, horizon)
    n = len(bars)
    with np.errstate(invalid="ignore", divide="ignore"):
        unit = band[:, None]
        quiet = rows < stall * unit
        quiet[~np.isfinite(rows)] = False
        path = np.nansum(rows, axis=1)
        net = np.full(n, np.nan)
        net[horizon - 1 :] = np.abs(bars.close[horizon - 1 :] - bars.close[: n - horizon + 1])
        complete = np.isfinite(rows[:, 0])
        middle = np.where(complete, np.nansum(rows, axis=1) / horizon, np.nan)
        spread = np.sqrt(np.where(complete, np.nansum((rows - middle[:, None]) ** 2, axis=1) / horizon, np.nan))
        span = bars.span
        out = {
            "atr_q": trailing_rank(band),
            "atr_ratio": band / atr(bars, period=REGIME),
            "past_stalls": np.where(np.isfinite(rows[:, 0]), quiet.sum(axis=1), np.nan).astype(float),
            "past_worst_run": np.where(np.isfinite(rows[:, 0]), longest_run(quiet), np.nan).astype(float),
            "past_travel": np.where(np.isfinite(rows[:, 0]), path / (horizon * band), np.nan),
            "past_efficiency": np.where(path > 0, net / np.where(path > 0, path, np.nan), np.nan),
            "tr_cv": spread / np.where(middle > 0, middle, np.nan),
            "last_tr": tr / band,
            "body_ratio": bars.body / np.where(span > 0, span, np.nan),
            "close_in_range": (bars.close - bars.low) / np.where(span > 0, span, np.nan),
            "bar_size": span / band,
        }
    hour = ((bars.ts // 3_600_000_000_000) % 24).astype(float)
    out["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    out["dow"] = ((bars.ts // 86_400_000_000_000) % 7).astype(float)
    out["_band"] = band
    return out


def continuity_label(
    bars: Candles, horizon: int, stall: float, allowed: int
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Is the **next** `horizon` bars' activity contiguous, and its parts.

    `allowed` is how many consecutive sub-`stall` bars still counts as
    continuous - the operator's "no or very little stalling". The label is a
    claim about the longest stalled run and not about the total, because the
    total is `expansion.md`'s question: one three-ATR bar and fifteen dead ones
    sums to the same as a window that moves throughout.
    """
    band = atr(bars)
    tr = true_range(bars)
    n = len(bars)
    forward = np.full((n, horizon), np.nan)
    for k in range(horizon):
        forward[: n - horizon, k] = tr[k + 1 : n - horizon + k + 1]
    with np.errstate(invalid="ignore", divide="ignore"):
        unit = band[:, None]
        quiet = forward < stall * unit
        quiet[~np.isfinite(forward)] = False
        live = np.isfinite(forward[:, -1]) & np.isfinite(band)
        worst = np.where(live, longest_run(quiet), np.nan).astype(float)
        path = np.nansum(forward, axis=1)
        net = np.full(n, np.nan)
        net[: n - horizon] = np.abs(bars.close[horizon:] - bars.close[: n - horizon])
        parts = {
            "worst_run": worst,
            "stalls": np.where(live, quiet.sum(axis=1), np.nan).astype(float),
            "travel": np.where(live, path / (horizon * band), np.nan),
            "efficiency": np.where(live & (path > 0), net / np.where(path > 0, path, np.nan), np.nan),
        }
    return np.where(live, (parts["worst_run"] <= allowed).astype(float), np.nan), parts


@dataclass(slots=True)
class Origins:
    """The operator's pull origins, split into what is known when.

    `candidate` is clauses 1 and 2 - a 15-bar pivot with a `--approach` ATR
    fall into it - and holds at the **close of the candle**, which is what
    makes a prediction question possible. `label` is clauses 3 and 4, the
    forward confirmation, and is NaN wherever the forward window is short.
    """

    candidate: np.ndarray
    side: np.ndarray
    label: np.ndarray
    padded: np.ndarray
    timeout: np.ndarray
    reached: np.ndarray
    waited: np.ndarray
    returned: np.ndarray
    came_back: np.ndarray
    bounced: np.ndarray
    bounce_r: np.ndarray
    bounce_ratio: np.ndarray
    bounce_late: np.ndarray
    parts: dict[str, np.ndarray]


def pull_origins(
    bars: Candles,
    band: np.ndarray,
    left: int = 15,
    approach: float = 1.5,
    reach: float = 3.0,
    ahead: int = 24,
    behind: int = 24,
    share: float = 0.5,
    displacement: float = 1.0,
    pad: float = 0.25,
    kind: str = "origin",
    after: int = 96,
    tol: float = 0.25,
) -> Origins:
    """The supplied detector, with its forward clauses kept separate.

    Clause 4's "a good share of its own back-and-forth" is `share` of net over
    path, and its "big, strong-bodied candle" is a body of `displacement` ATR
    that is also more than half its own range - two readings of one English
    phrase, taken as alternatives because the supplied text says "either".

    **Both sides, labelled.** A pooled answer here once agreed with a claim
    every subgroup refuted (`pooled-medians-invert-subgroups`), and a bullish
    origin and a bearish one are different populations on an instrument with
    any drift at all.
    """
    n = len(bars)
    high, low, close, open_ = bars.high, bars.low, bars.close, bars.open
    tr = true_range(bars)
    body = np.abs(close - open_)
    strong = (body >= displacement * band) & (body > 0.5 * np.maximum(bars.span, 1e-12))

    floor_before = rolling(low, left, "min", offset=1)
    ceiling_before = rolling(high, left, "max", offset=1)
    pivot_low = low < floor_before
    pivot_high = high > ceiling_before
    ceiling = rolling(high, behind + 1, "max")
    floor = rolling(low, behind + 1, "min")
    fell = windowed(high, behind + 1)
    rose = windowed(low, behind + 1)
    with np.errstate(invalid="ignore"):
        drop = (ceiling - low) / band
        rally = (high - floor) / band
        back_path = np.nansum(windowed(tr, behind + 1), axis=1)

    candidate = np.zeros(n, dtype=bool)
    side = np.zeros(n, dtype=np.int8)
    label = np.full(n, np.nan)
    padded = np.full(n, np.nan)
    timeout = np.zeros(n)
    reached = np.full(n, np.nan)
    returned = np.full(n, np.nan)
    came_back = np.full(n, np.nan)
    bounced = np.full(n, np.nan)
    bounce_r = np.full(n, np.nan)
    bounce_ratio = np.full(n, np.nan)
    bounce_late = np.zeros(n)
    waited = np.full(n, np.nan)
    pivot_strength = np.full(n, np.nan)
    reject_wick = np.full(n, np.nan)
    remaining = np.full(n, np.nan)
    cushion = np.full(n, np.nan)
    fall_bars = np.full(n, np.nan)
    approach_eff = np.full(n, np.nan)
    approach_size = np.full(n, np.nan)

    for i in range(left, n):
        unit = band[i]
        if not np.isfinite(unit) or unit <= 0:
            continue
        deep = np.isfinite(drop[i]) and drop[i] >= approach
        tall = np.isfinite(rally[i]) and rally[i] >= approach
        shallow = np.isfinite(drop[i]) and drop[i] < approach
        short = np.isfinite(rally[i]) and rally[i] < approach
        if kind == "origin":
            up, down = bool(pivot_low[i]) and deep, bool(pivot_high[i]) and tall
        elif kind == "no_approach":
            # Clause 1 without clause 2: a 15-bar pivot that price did **not**
            # fall hard into. Names the property removed, which is the rule
            # `a-control-is-only-for-a-named-property` exists for.
            up, down = bool(pivot_low[i]) and shallow, bool(pivot_high[i]) and short
        else:
            # Clause 2 without clause 1: the 1.5 ATR fall, into a bar that is
            # not the lowest of its fifteen.
            up, down = (not pivot_low[i]) and deep, (not pivot_high[i]) and tall
        # A bar can satisfy neither, one, or - with a wide enough range - both.
        # Both is a two-sided candidate and is dropped rather than coined: it is
        # a different object and there are few of them.
        if up == down:
            continue
        candidate[i] = True
        side[i] = 1 if up else -1
        origin = float(low[i]) if up else float(high[i])
        pivot_strength[i] = (
            (float(floor_before[i]) - origin) / unit
            if up
            else (origin - float(ceiling_before[i])) / unit
        )
        reject_wick[i] = (bars.lower_wick[i] if up else bars.upper_wick[i]) / max(bars.span[i], 1e-12)
        approach_size[i] = drop[i] if up else rally[i]
        here = float(close[i])
        cushion[i] = (here - origin) / unit if up else (origin - here) / unit
        remaining[i] = reach - cushion[i]
        net = float(ceiling[i] - origin if up else origin - floor[i])
        approach_eff[i] = net / back_path[i] if back_path[i] > 0 else np.nan
        arm = fell[i] if up else rose[i]
        if np.isfinite(arm).all():
            fall_bars[i] = behind - int(np.argmax(arm) if up else np.argmin(arm))

        if i + ahead >= n:
            continue
        target = origin + reach * unit if up else origin - reach * unit
        guard = origin - pad * unit if up else origin + pad * unit
        entry = float(close[i])
        risk = abs(entry - guard)

        # **The trade's race is not the detector's clause.** Clause 3 says the
        # rise happens "without going below" the origin, which is a statement
        # about the shape; a trade's stop sits `pad` ATR *beyond* the origin,
        # so a wick through the low that recovers is a broken clause and a
        # surviving position. Measured together they were the same array -
        # the clause loop breaks at the origin and never reaches the lower
        # stop - which made the padded arm a copy of the unpadded one.
        if risk > 0:
            for j in range(i + 1, i + 1 + ahead):
                stopped = (low[j] <= guard) if up else (high[j] >= guard)
                made = (high[j] >= target) if up else (low[j] <= target)
                if stopped:
                    # Both on one bar charges the loss: the stop is a quarter
                    # of an ATR from the entry and the target is three, so the
                    # near barrier is the one a tick sequence reaches first far
                    # more often than not.
                    padded[i] = -1.0
                    break
                if made:
                    padded[i] = abs(target - entry) / risk
                    break
            else:
                # Out of time, not stopped: marked out at the close rather than
                # charged a full stop, which is what scoring a timeout as -1R
                # does and it read -0.34R a trade where the mark-out reads a
                # different number entirely.
                padded[i] = (float(close[i + ahead]) - entry) * (1.0 if up else -1.0) / risk
                timeout[i] = 1.0

        hit, broke = -1, False
        for j in range(i + 1, i + 1 + ahead):
            if (low[j] < origin) if up else (high[j] > origin):
                broke = True
                break
            if (high[j] >= target) if up else (low[j] <= target):
                hit = j
                break
        if broke or hit < 0:
            label[i], reached[i] = 0.0, 0.0
            continue
        reached[i] = 1.0
        leg = slice(i + 1, hit + 1)
        path = float(np.nansum(tr[leg]))
        moved = abs(float(close[hit]) - origin)
        directional = (path > 0 and moved / path >= share) or bool(strong[leg].any())
        label[i] = 1.0 if directional else 0.0
        waited[i] = hit - i
        if not directional:
            continue

        # **The round trip, on confirmed origins only.** Price left the origin,
        # made its `reach` ATR, and the question is whether a return to the
        # origin goes back to where it came from.
        #
        # `a-return-rate-is-geometry` is the standing warning: the 82% return
        # rate that started the fade-to-value family was matched by a
        # distance-matched placebo on every asset class, and a walk read 0.825.
        # So the readings that matter are this arm beside `--kind no_pivot` and
        # `no_approach` at the same distance, and beside the fair rate, which
        # at a `reach`-to-`pad` geometry is nowhere near a half.
        #
        # **This block sat above the clause-4 test once**, and its `continue`
        # skipped the label: every row that survived to be counted had returned
        # by construction and the return rate read 1.0000 on 588 origins.
        zone = origin + tol * unit if up else origin - tol * unit
        came = -1
        for j in range(hit + 1, min(n, hit + 1 + after)):
            if (low[j] <= zone) if up else (high[j] >= zone):
                came = j
                break
        if came < 0:
            returned[i] = 0.0
            continue
        returned[i], came_back[i] = 1.0, came - hit
        entry_back = float(close[came])
        # **The entry can be past its own stop.** The return is a touch within
        # `--tol` of the origin, and the bar that touches it can close beyond
        # the guard - which is not a trade, it is a position that was never
        # opened. Counted and dropped rather than scored, because scoring it
        # divides a three-ATR reward by a risk of almost nothing and one row
        # then carries a whole instrument.
        past = (entry_back <= guard) if up else (entry_back >= guard)
        if past:
            bounce_late[i] = 2.0
            continue
        risk_back = abs(entry_back - guard)
        if risk_back <= 0:
            continue
        bounce_ratio[i] = abs(target - entry_back) / risk_back
        for k in range(came + 1, min(n, came + 1 + after)):
            if (low[k] <= guard) if up else (high[k] >= guard):
                bounced[i], bounce_r[i] = 0.0, -1.0
                break
            if (high[k] >= target) if up else (low[k] <= target):
                bounced[i], bounce_r[i] = 1.0, abs(target - entry_back) / risk_back
                break
        else:
            last = min(n - 1, came + after)
            bounced[i] = 0.0
            bounce_r[i] = (float(close[last]) - entry_back) * (1.0 if up else -1.0) / risk_back
            bounce_late[i] = 1.0

    parts = {
        "approach": approach_size,
        "approach_efficiency": approach_eff,
        "fall_bars": fall_bars,
        "pivot_strength": pivot_strength,
        "reject_wick": reject_wick,
        "remaining": remaining,
        "cushion": cushion,
    }
    return Origins(
        candidate=candidate,
        side=side,
        label=label,
        padded=padded,
        timeout=timeout,
        reached=reached,
        waited=waited,
        returned=returned,
        came_back=came_back,
        bounced=bounced,
        bounce_r=bounce_r,
        bounce_ratio=bounce_ratio,
        bounce_late=bounce_late,
        parts=parts,
    )


def range_position(bars: Candles, span: int = REGIME) -> np.ndarray:
    """Where the close sits in the trailing `span`-bar range, 0 low to 1 high."""
    top = rolling(bars.high, span, "max")
    bottom = rolling(bars.low, span, "min")
    with np.errstate(invalid="ignore", divide="ignore"):
        width = top - bottom
        return np.where(width > 0, (bars.close - bottom) / np.where(width > 0, width, np.nan), np.nan)


def round_distance(bars: Candles, band: np.ndarray) -> np.ndarray:
    """Distance to the nearest round price, in ATR.

    A watchedness proxy and the one from the levels family that survived
    reformulation: `a-magnet-is-a-shared-reference` is a claim about many
    participants computing the same number, not about attraction.
    """
    scale = 10.0 ** np.floor(np.log10(np.maximum(np.abs(bars.close), 1e-12)) - 2.0)
    step = scale * 5.0
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.abs(bars.close - np.round(bars.close / step) * step) / band


def _midranks(values: np.ndarray) -> np.ndarray:
    """Ranks with ties averaged. Discrete features make this matter."""
    order = np.argsort(values, kind="stable")
    sorted_v = values[order]
    ranks = np.empty(values.size, dtype=np.float64)
    i = 0
    while i < sorted_v.size:
        j = i
        while j + 1 < sorted_v.size and sorted_v[j + 1] == sorted_v[i]:
            j += 1
        ranks[order[i : j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return ranks


def auc(score: np.ndarray, label: np.ndarray) -> float:
    """Mann-Whitney AUC, ties at 0.5."""
    ok = np.isfinite(score) & np.isfinite(label)
    s, y = score[ok], label[ok] > 0.5
    positives, negatives = int(y.sum()), int((~y).sum())
    if positives < 25 or negatives < 25:
        return float("nan")
    ranks = _midranks(s)
    return float((ranks[y].sum() - positives * (positives + 1) / 2.0) / (positives * negatives))


def strata_auc(score: np.ndarray, label: np.ndarray, stratum: np.ndarray, cells: int = 5) -> float:
    """AUC inside each volatility stratum, pooled by Mann-Whitney weight.

    **The headline statistic.** A pooled AUC on a volatility-shaped target is
    free: `auc-is-free-on-volatility-targets` measured 0.805 on a process whose
    volatility is constant by construction, and 0.525 once the comparison was
    made within strata. What is left here is what is not already volatility.
    """
    ok = np.isfinite(score) & np.isfinite(label) & np.isfinite(stratum)
    if ok.sum() < 200:
        return float("nan")
    edges = np.nanpercentile(stratum[ok], np.linspace(0, 100, cells + 1))
    total, weight = 0.0, 0.0
    for c in range(cells):
        lo, hi = edges[c], edges[c + 1]
        pick = ok & (stratum >= lo) & ((stratum < hi) if c < cells - 1 else (stratum >= lo))
        if pick.sum() < 100:
            continue
        here = auc(score[pick], label[pick])
        if not np.isfinite(here):
            continue
        y = label[pick] > 0.5
        w = float(y.sum()) * float((~y).sum())
        total, weight = total + here * w, weight + w
    return total / weight if weight > 0 else float("nan")


def permuted_floor(score: np.ndarray, label: np.ndarray, draws: int = 20, seed: int = 5) -> float:
    """How far from 0.5 a **permuted** score lands, averaged over draws.

    The right null for "does this reading sort the labels". The rows are not
    independent - windows overlap and cluster in days - so one permutation is
    one draw and the spread over draws is what an AUC has to clear.
    """
    ok = np.isfinite(score) & np.isfinite(label)
    s, y = score[ok], label[ok]
    rng = np.random.default_rng(seed)
    return float(np.mean([abs(auc(rng.permutation(s), y) - 0.5) for _ in range(draws)]))


def deciles(name: str, values: np.ndarray, label: np.ndarray, cells: int = 10) -> None:
    """One feature, by decile, with the label rate each decile was followed by."""
    ok = np.isfinite(values) & np.isfinite(label)
    if ok.sum() < 500:
        print(f"    {name}: {ok.sum()} rows, too few")
        return
    v, y = values[ok], label[ok]
    edges = np.percentile(v, np.linspace(0, 100, cells + 1))
    print(f"    {name}  ({ok.sum():,} rows, rate {y.mean():.4f}, AUC {auc(v, y):.4f})")
    for c in range(cells):
        lo, hi = edges[c], edges[c + 1]
        pick = (v >= lo) & (v < hi) if c < cells - 1 else (v >= lo)
        if pick.sum() < 50:
            continue
        rate = float(y[pick].mean())
        print(
            f"      d{c + 1:<2} {lo:+9.3f}..{hi:+9.3f}  n {pick.sum():>7,}  "
            f"{rate:.4f}  {'#' * min(int(round(rate * 40)), 40)}"
        )


def fitted(
    table: dict[str, np.ndarray],
    label: np.ndarray,
    names: tuple[str, ...],
    train: np.ndarray,
    test: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Gradient-boosted trees on one feature set, fitted on `train` only.

    Split by time and never at random: the rows overlap by the horizon and
    cluster in days, so a random split puts a row's own neighbours on the other
    side of it. Returns the test-row scores and the mask they belong to.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier

    stack = np.column_stack([table[n] for n in names])
    good = np.isfinite(stack).all(axis=1) & np.isfinite(label)
    fit_on, score_on = train & good, test & good
    if fit_on.sum() < 1000 or score_on.sum() < 300:
        return np.array([]), np.zeros(label.size, dtype=bool)
    if len(np.unique(label[fit_on] > 0.5)) < 2:
        return np.array([]), np.zeros(label.size, dtype=bool)
    model = HistGradientBoostingClassifier(
        max_iter=200, max_depth=4, learning_rate=0.06, l2_regularization=1.0, random_state=7
    )
    model.fit(stack[fit_on], label[fit_on] > 0.5)
    return model.predict_proba(stack[score_on])[:, 1], score_on


def planted(
    table: dict[str, np.ndarray],
    label: np.ndarray,
    names: tuple[str, ...],
    strength: float,
    seed: int = 13,
) -> np.ndarray:
    """`label`, with `strength` of its rows replaced by a readable effect.

    A fixed random direction in standardised feature space, thresholded at its
    own median. Nothing in a null is worth reporting without this: it says what
    size of effect the harness would have seen, and `atr-ml.md` found its own
    models blind to 0.02 ATR and recovering about a third of 0.05.

    **Planted on the columns the baseline cannot see.** The first version drew
    its direction over the whole `full` set, which includes every `base`
    column - so a planted effect lifted both arms together and `full - base`
    stayed flat at every strength. That is not a power curve for the claim
    being tested; it is a power curve for a claim nobody made. The caller
    passes the set difference, and the planted effect is then something only
    the geometry can represent.
    """
    if strength <= 0:
        return label
    stack = np.column_stack([table[n] for n in names])
    good = np.isfinite(stack).all(axis=1)
    centred = np.zeros_like(stack)
    if good.any():
        centred[good] = (stack[good] - stack[good].mean(axis=0)) / (stack[good].std(axis=0) + 1e-12)
    rng = np.random.default_rng(seed)
    score = centred @ rng.normal(size=len(names))
    readable = (score > np.median(score[good])).astype(float) if good.any() else np.zeros(label.size)
    swap = rng.random(label.size) < strength
    return np.where(swap & good & np.isfinite(label), readable, label)


def thin(mask: np.ndarray, gap: int) -> np.ndarray:
    """Keep rows at least `gap` apart, greedily from the left.

    **De-overlapping, not tidying.** `overlapping-outcome-windows-leak` is a
    direct measurement of what this prevents: a short skip rule with a long
    forward window read direction AUC 0.79 and collapsed to 0.51 once the
    windows no longer shared outcomes.
    """
    out = np.zeros(mask.size, dtype=bool)
    last = -gap - 1
    for i in np.flatnonzero(mask):
        if i - last > gap:
            out[i] = True
            last = i
    return out


def day_block_interval(
    score_a: np.ndarray,
    score_b: np.ndarray,
    label: np.ndarray,
    stratum: np.ndarray,
    day: np.ndarray,
    draws: int = 200,
    seed: int = 29,
) -> tuple[float, float]:
    """A day-block bootstrap of the within-strata AUC difference `a - b`.

    Whole days, because regime labels persist for hours and these rows cluster
    in days; an ordinary standard error here is far too narrow.
    """
    days = np.unique(day)
    if days.size < 20:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    index = {d: np.flatnonzero(day == d) for d in days}
    spread = []
    for _ in range(draws):
        pick = np.concatenate([index[d] for d in rng.choice(days, size=days.size, replace=True)])
        first = strata_auc(score_a[pick], label[pick], stratum[pick])
        second = strata_auc(score_b[pick], label[pick], stratum[pick])
        if np.isfinite(first) and np.isfinite(second):
            spread.append(first - second)
    if len(spread) < 50:
        return float("nan"), float("nan")
    return float(np.percentile(spread, 5)), float(np.percentile(spread, 95))


def assemble(bars: Candles, args: argparse.Namespace) -> dict[str, np.ndarray] | None:
    """One instrument's rows: features, label, stratum, day, and the split.

    Returns None when the series is too short for the windows asked for, which
    is the common case for a synthetic held only at 4h.
    """
    table = readings(bars, args.horizon, args.stall)
    band = table.pop("_band")
    table["range_pos"] = range_position(bars)
    table["round_dist"] = round_distance(bars, band)
    n = len(bars)

    if args.target == "continuity":
        label, parts = continuity_label(bars, args.horizon, args.stall, args.allowed)
        rows = np.zeros(n, dtype=bool)
        rows[:: max(args.stride, 1)] = True
        rows &= np.isfinite(label)
        side = np.zeros(n, dtype=np.int8)
        extra = parts
    else:
        found = pull_origins(
            bars,
            band,
            left=args.left,
            approach=args.approach,
            reach=args.reach,
            ahead=args.ahead,
            behind=args.behind,
            share=args.share,
            displacement=args.displacement,
            pad=args.pad,
            kind=args.kind,
            after=args.after,
            tol=args.tol,
        )
        for name, values in found.parts.items():
            table[name] = values
        label, side = found.label, found.side
        rows = found.candidate & np.isfinite(label)
        if args.thin:
            rows = thin(rows, args.ahead)
        extra = {
            "reached": found.reached,
            "padded": found.padded,
            "timeout": found.timeout,
            "waited": found.waited,
            "returned": found.returned,
            "came_back": found.came_back,
            "bounced": found.bounced,
            "bounce_r": found.bounce_r,
            "bounce_ratio": found.bounce_ratio,
            "bounce_late": found.bounce_late,
        }

    needed = SETS[args.target]["full"]
    stack = np.column_stack([table[k] for k in needed])
    rows &= np.isfinite(stack).all(axis=1)
    if rows.sum() < 400:
        return None

    cut = np.quantile(bars.ts[rows], 0.5)
    purge = args.ahead if args.target == "pull" else args.horizon
    gap = int(purge) * int(np.median(np.diff(bars.ts[:1000])) if n > 1000 else 0)
    out = {k: v[rows] for k, v in table.items()}
    out["_label"] = label[rows]
    out["_side"] = side[rows].astype(float)
    out["_day"] = (bars.ts[rows] // 86_400_000_000_000).astype(float)
    out["_train"] = (bars.ts[rows] < cut - gap).astype(float)
    out["_test"] = (bars.ts[rows] >= cut).astype(float)
    for name, values in extra.items():
        out[f"_{name}"] = values[rows]
    return out


def economics(pooled: dict[str, np.ndarray], args: argparse.Namespace, cells: int = 6) -> None:
    """What a candidate is worth in R, by how much of the target it has covered.

    **The number that decides whether `cushion` is a forecast.** Entering at
    the candidate's close with the stop `--pad` ATR beyond the origin and the
    target where clause 3 puts it, the risk *is* the cushion: the reading that
    calls the outcome at AUC 0.76 is the distance already travelled, and it is
    bought at exactly that distance. A driftless walk pays `1/(1+N)` at a
    reward-to-risk of `N`, so the column to read is not the hit rate but
    whether it clears its own fair rate - `barrier-geometry-is-irrelevant.md`
    and `a-martingale-cannot-pay` are the same statement from two directions.

    Quoted gross, which is the operator's standing instruction: a rule with no
    side before costs cannot have one after.
    """
    cushion, remaining = pooled["cushion"], pooled["remaining"]
    outcome_all = pooled["_padded"]
    late = pooled["_timeout"] > 0.5
    risk = cushion + args.pad
    ok = np.isfinite(risk) & np.isfinite(remaining) & np.isfinite(outcome_all) & (risk > 0) & ~late
    if ok.sum() < 200:
        print("    economics: too few rows")
        return
    ratio = remaining[ok] / risk[ok]
    outcome = outcome_all[ok]
    fair = 1.0 / (1.0 + ratio)
    print(
        f"    {late.mean():.3f} of candidates time out unstopped in {args.ahead} bars and are "
        f"marked out at the close, mean {np.nanmean(outcome_all[late]):+.4f}R; "
        f"the table below is the {ok.sum():,} that resolved"
    )
    print(
        f"    gross R entering at the close, stop {args.pad:.2f} ATR past the origin "
        f"({ok.sum():,} rows)"
    )
    print("      cushion ATR      n     R:R   hit    fair   hit-fair    mean R")
    edges = np.percentile(cushion[ok], np.linspace(0, 100, cells + 1))
    seen = cushion[ok]
    for c in range(cells):
        lo, hi = edges[c], edges[c + 1]
        pick = (seen >= lo) & (seen < hi) if c < cells - 1 else (seen >= lo)
        if pick.sum() < 50:
            continue
        hit = float((outcome[pick] > 0).mean())
        expect = float(fair[pick].mean())
        print(
            f"      {lo:5.2f}..{hi:5.2f} {pick.sum():>7,}  {ratio[pick].mean():6.2f}  "
            f"{hit:.3f}  {expect:.3f}   {hit - expect:+.3f}    {outcome[pick].mean():+.4f}"
        )
    day = pooled["_day"][ok]
    days = np.unique(day)
    rng = np.random.default_rng(31)
    index = {d: np.flatnonzero(day == d) for d in days}
    draws = [
        float(outcome[np.concatenate([index[d] for d in rng.choice(days, days.size, replace=True)])].mean())
        for _ in range(400)
    ]
    print(
        f"      all {ok.sum():,} rows  mean R {outcome.mean():+.4f}  "
        f"day-block 90% [{np.percentile(draws, 5):+.4f}, {np.percentile(draws, 95):+.4f}]  "
        f"hit {float((outcome > 0).mean()):.4f} against fair {float(fair.mean()):.4f}"
    )
    every = outcome_all[np.isfinite(outcome_all)]
    print(f"      with the timeouts marked in, {every.size:,} rows at {every.mean():+.4f}R")


def round_trip(pooled: dict[str, np.ndarray], args: argparse.Namespace) -> None:
    """Did it come back, and did coming back go back to where it came from.

    Three rates, and the third is the only one that is a claim:

    * **P(return)** - price revisits the origin within `--tol` ATR inside
      `--after` bars of making its target. A return rate is geometry; `a-return
      -rate-is-geometry` measured an 82% figure matched by a distance-matched
      placebo on every asset class, with a walk at 0.825.
    * **P(bounce | return)** - from the return it reaches the old extreme again
      before `--pad` ATR past the origin. Compare with the **fair** rate for
      that geometry, `1/(1+N)`, and with the same number on `--kind no_pivot`
      and `no_approach`.
    * **the R of taking it** - entering at the returning bar's close, which is
      where a desk could actually be filled rather than at the touch.
    """
    returned, bounced = pooled["_returned"], pooled["_bounced"]
    outcome, late = pooled["_bounce_r"], pooled["_bounce_late"]
    came_back, ratio = pooled["_came_back"], pooled["_bounce_ratio"]
    confirmed = np.isfinite(returned)
    if confirmed.sum() < 100:
        print("    round trip: too few confirmed origins")
        return
    back = confirmed & (returned > 0.5)
    raced = np.isfinite(outcome) & np.isfinite(ratio)
    print(
        f"    round trip: {confirmed.sum():,} confirmed, {back.sum():,} returned "
        f"({back.sum() / confirmed.sum():.4f}) after a median {np.nanmedian(came_back[back]):.0f} bars; "
        f"{int((late == 2.0).sum()):,} closed past the stop on the returning bar"
    )
    if raced.sum() < 50:
        print("      nothing raced")
        return
    fair = float(np.nanmean(1.0 / (1.0 + ratio[raced])))
    print(
        f"      bounced back {float(np.nanmean(bounced[raced])):.4f} of {raced.sum():,} "
        f"against a fair {fair:.4f} at a realised R:R of "
        f"{float(np.nanmean(ratio[raced])):.2f} (median {float(np.nanmedian(ratio[raced])):.2f}); "
        f"{float(np.nanmean(late[raced] == 1.0)):.3f} ran out of bars"
    )
    day = pooled["_day"][raced]
    days = np.unique(day)
    values = outcome[raced]
    rng = np.random.default_rng(37)
    index = {d: np.flatnonzero(day == d) for d in days}
    draws = [
        float(values[np.concatenate([index[d] for d in rng.choice(days, days.size, replace=True)])].mean())
        for _ in range(400)
    ]
    print(
        f"      taking the return: {values.mean():+.4f}R, day-block 90% "
        f"[{np.percentile(draws, 5):+.4f}, {np.percentile(draws, 95):+.4f}]"
    )


def report(pooled: dict[str, np.ndarray], args: argparse.Namespace, title: str) -> None:  # noqa: C901
    """Base rate, three feature sets, pooled AUC and AUC within strata."""
    label = pooled["_label"]
    stratum = pooled["atr_q"]
    # `hour_sin` alone collides at two hours a day, so the pair is turned back
    # into an angle - a stratum has to be one hour, not two.
    clock_of = np.arctan2(pooled["hour_sin"], pooled["hour_cos"])
    train, test = pooled["_train"] > 0.5, pooled["_test"] > 0.5
    print(f"\n  {title}: {label.size:,} rows, rate {label.mean():.4f}, test {test.sum():,}")
    if "_reached" in pooled:
        got = pooled["_reached"]
        print(
            f"    clause 3 alone (the {args.reach:.1f} ATR rise) {np.nanmean(got):.4f}; "
            f"clause 4 then rejects {np.nanmean(got > 0.5) - np.nanmean(label > 0.5):.4f}"
        )
        for arm, name in ((1.0, "bullish"), (-1.0, "bearish")):
            pick = pooled["_side"] == arm
            if pick.sum() > 100:
                print(f"    {name}: n {pick.sum():,}, rate {label[pick].mean():.4f}")

    scores: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    # **One label, built once.** Each set used to plant its own copy inside the
    # loop and the interval below then scored them against the *unplanted*
    # label - so at a 0.20 plant the per-set AUCs read base 0.7008 and full
    # 0.7466 while the interval printed `[-0.0481, -0.0258]`. A model fitted
    # on one label and scored against another is not a measurement of
    # anything. Unaffected at `--plant 0`, where the two are the same array.
    if args.plant > 0:
        spare = tuple(n for n in SETS[args.target]["full"] if n not in SETS[args.target]["base"])
        wanted = planted(pooled, label, spare, args.plant)
    else:
        wanted = label
    for name, names in SETS[args.target].items():
        score, used = fitted(pooled, wanted, names, train, test)
        if score.size == 0:
            print(f"    {name:<6} not fitted")
            continue
        scores[name] = (score, used)
        flat = auc(score, wanted[used])
        inside = strata_auc(score, wanted[used], stratum[used])
        floor = permuted_floor(score, wanted[used])
        # **And within the hour of day**, because the hour is what the
        # continuity answer turned out to be: a model scoring 0.89 pooled and
        # 0.55 inside the hour has predicted the session and nothing else.
        clock_strata = strata_auc(score, wanted[used], clock_of[used], cells=12)
        print(
            f"    {name:<7} n {used.sum():>7,}  AUC {flat:.4f}  within vol strata {inside:.4f}  "
            f"within the hour {clock_strata:.4f}  permuted floor +/-{floor:.4f}"
        )
    if "full" in scores and "base" in scores:
        full_score, full_used = scores["full"]
        base_score, base_used = scores["base"]
        both = full_used & base_used
        if both.sum() > 500:
            a = np.full(both.sum(), np.nan)
            b = np.full(both.sum(), np.nan)
            a[:] = full_score[both[full_used]]
            b[:] = base_score[both[base_used]]
            lo, hi = day_block_interval(a, b, wanted[both], stratum[both], pooled["_day"][both])
            print(f"    full - base within strata, day-block 90%: [{lo:+.4f}, {hi:+.4f}]")

    if args.target == "pull" and args.plant <= 0 and "_padded" in pooled:
        economics(pooled, args)
        round_trip(pooled, args)

    wanted = [f.strip() for f in args.deciles.split(",") if f.strip()]
    if not wanted:
        return
    print("    one feature at a time, every row, against a permuted copy of itself")
    for feature in wanted:
        if feature not in pooled:
            continue
        alone = auc(pooled[feature], label)
        floor = permuted_floor(pooled[feature], label)
        inside = strata_auc(pooled[feature], label, stratum)
        print(
            f"      {feature:<20} AUC {alone:.4f}  within strata {inside:.4f}  "
            f"permuted floor +/-{floor:.4f}"
        )
    if args.tables:
        for feature in wanted:
            if feature in pooled:
                deciles(feature, pooled[feature], label)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--csv", default="", help="name=path,name=path, read at --unit")
    parser.add_argument("--unit", default="5m", help="base frame of the source")
    parser.add_argument("--frame", default="1h")
    parser.add_argument("--years", type=float, default=0.0)
    parser.add_argument("--before", type=float, default=0.0)
    parser.add_argument("--target", default="continuity", choices=sorted(SETS))
    parser.add_argument("--arms", default="real,shuffled")
    parser.add_argument("--horizon", type=int, default=16, help="continuity: bars ahead and behind")
    parser.add_argument("--stall", type=float, default=0.5, help="continuity: ATR under which a bar stalls")
    parser.add_argument("--allowed", type=int, default=1, help="continuity: stalled bars still 'continuous'")
    parser.add_argument("--stride", type=int, default=0, help="continuity: row spacing, 0 means the horizon")
    parser.add_argument("--left", type=int, default=15, help="pull: candles the pivot must be lowest of")
    parser.add_argument("--approach", type=float, default=1.5, help="pull: ATR fall into the candle")
    parser.add_argument("--reach", type=float, default=3.0, help="pull: ATR rise out of it")
    parser.add_argument("--ahead", type=int, default=24, help="pull: candles the rise has")
    parser.add_argument("--behind", type=int, default=24, help="pull: candles the fall is measured over")
    parser.add_argument("--share", type=float, default=0.5, help="pull: net over path for 'directional'")
    parser.add_argument("--displacement", type=float, default=1.0, help="pull: ATR body for a strong candle")
    parser.add_argument("--pad", type=float, default=0.25, help="pull: ATR the stop sits beyond the origin")
    parser.add_argument(
        "--kind",
        default="origin",
        choices=("origin", "no_approach", "no_pivot"),
        help="pull: the detector, or it with one clause removed",
    )
    parser.add_argument("--after", type=int, default=96, help="pull: bars the round trip has, each leg")
    parser.add_argument("--tol", type=float, default=0.25, help="pull: ATR within the origin that counts as back")
    parser.add_argument("--thin", action="store_true", help="pull: keep candidates --ahead apart")
    parser.add_argument("--plant", type=float, default=0.0)
    parser.add_argument("--deciles", default="", help="features to score one at a time")
    parser.add_argument("--tables", action="store_true", help="print the decile table too")
    args = parser.parse_args()
    if args.stride <= 0:
        args.stride = args.horizon

    sources: list[tuple[str, Candles]] = []
    if args.csv:
        for pair in args.csv.split(","):
            name, _, path = pair.partition("=")
            sources.append((name, load_csv(Path(path), name, args.unit)))
    else:
        for symbol in (s for s in args.symbols.split(",") if s):
            sources.append((symbol, load(Path(args.catalogue), symbol)))

    print(
        f"target {args.target}  frame {args.frame}  horizon {args.horizon}  stall {args.stall}  "
        f"allowed {args.allowed}  left {args.left}  approach {args.approach}  reach {args.reach}  "
        f"ahead {args.ahead}  plant {args.plant}"
    )
    for arm in (a.strip() for a in args.arms.split(",") if a.strip()):
        print(f"\n=== {arm}")
        gathered: list[dict[str, np.ndarray]] = []
        for name, base in sources:
            series = shuffled(base, seed=17) if arm == "shuffled" else base
            if args.years > 0 or args.before > 0:
                series = window(series, args.years, args.before)
            bars = fold(series, args.frame, unit=args.unit)
            built = assemble(bars, args)
            if built is None:
                print(f"\n  {name}: too few rows")
                continue
            report(built, args, name)
            gathered.append(built)
        if len(gathered) > 1:
            keys = set(gathered[0])
            for one in gathered[1:]:
                keys &= set(one)
            pooled = {k: np.concatenate([one[k] for one in gathered]) for k in keys}
            report(pooled, args, "pooled")


if __name__ == "__main__":
    main()
