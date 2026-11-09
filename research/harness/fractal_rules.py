"""Do fractal estimators carry anything a trading desk can use, once volatility is held fixed?

    ./.secrets/lab.sh sync
    ./.secrets/lab.sh exec 'cd $HOME/till_infinity && nohup env OMP_NUM_THREADS=1 \
        OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PART=all \
        SEQLAB=$HOME/till_infinity/data/seqlab SYN=$HOME/till_infinity/data/syn \
        PYTHONPATH=$HOME/till_infinity/repo \
        $HOME/till_infinity/.venv/bin/python -u \
        repo/research/harness/fractal_rules.py > logs/fractal_rules.log 2>&1 &'

`lab.sh run` would sync over a file pushed by hand, so the sync happens first and
explicitly. `PART` is one of `cost`, `power`, `signal`, `trade` or `all`.

## What is already answered, and is therefore not the question

Most of the fractal family is measured here and most of it is closed:

* **A Hurst exponent on the level** has been in `inputs.py` for years and reads
  0.489 to 0.506 - a walk to three decimals on every instrument.
* **DFA on `|returns|`** reads 0.67 to 0.84 against a walk's 0.528
  (`fractal-twins.md`): volatility has long memory and direction does not.
* **The multifractality of returns** is a measured stylized fact:
  `statespace-fractals.md` reads `lambda^2` of 0.076 on traded markets against
  0.001 to 0.010 on every control.
* **A ladder on log-volatility** wins by +191 to +547 nats on 7 of 7 traded
  markets and loses on 5 of 5 controls - and then **fails its gate**, because a
  plain 24-bar trailing standard deviation produces a narrower band at equal
  coverage (1.933 against 1.999).
* **The adverse excursion's scaling exponent** is measured and fails all four
  of its pre-registered criteria: every real deviation from 0.5 is smaller than
  its own surrogate's.
* **Expansion from compression** is forecastable at AUC 0.73 and is already
  live as the spike switch.

Every one of those is an **unconditional** statement: one exponent per
instrument, fitted over the whole series, reported as a property of the process.
None of them asks the question a desk asks, which is whether the reading **at
bar `t`** says anything about bar `t+1`.

So the claim here, written as a sentence those studies could not have tested:

> **A fractal estimator read on a trailing window, at a moment, carries
> information about the next few hours' direction, volatility or barrier race
> that survives holding trailing volatility fixed.**

and the specific trading folklore it tests, which is the reason the estimators
are interesting at all:

> **The sign of a momentum edge flips with the rolling Hurst exponent** - trade
> continuation when `H > 0.5` and reversion when `H < 0.5`.

That second one is directional, and `direction-is-closed-not-just-null` records
the direction gate finding a *planted* drift at z +2.90 while earning 2% of a
spread. It is carried anyway because it is the claim the fractal literature
actually makes, and because the claim is about a **conditional sign flip**
rather than an unconditional edge, which nothing above tests.

## The expected answer, written before the run

`topology.md` found levels, ranges and shapes all null and all restatements of
volatility. `auc-is-free-on-volatility-targets` prices the trap: AUC 0.805 on a
constant-volatility process collapsing to 0.525 within volatility strata. A
fractal dimension is a volatility-structure statistic, so **the expected result
is that every reading is a volatility restatement and the within-strata column
is empty.** That is the valued outcome, and the within-strata column is the one
the verdict is read from.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

import numpy as np

from research.harness import fractalest
from till_infinity.statespace import nulls

SEQLAB = Path(os.environ.get("SEQLAB", ".data/seqlab"))
SYN = Path(os.environ.get("SYN", ".data/syn"))
OUT = Path(os.environ.get("OUT", "."))
PART = os.environ.get("PART", "all")
WORKERS = int(os.environ.get("WORKERS", "12"))

BASE = "15m"

#: Production's stop, in volatility units: `Intent.stop_vol` has a median of
#: 3.0. Cost in R is `cost_px / risk` and is set by this, not by the target -
#: `a-shorter-clock-multiplies-cost-in-r` measures the same spread as 19x
#: dearer at 15m than at 1d.
STOP_MULT = 3.0
#: Target at twice the stop, so a driftless walk reaches it before the stop
#: exactly `1 / (1 + 2)` of the time. Beating 0.3333 is the entire game.
TARGET_MULT = 2.0
RACE_BASE = 1.0 / (1.0 + TARGET_MULT)
#: One trading day at 15m. A trade still open after this is marked out at the
#: close, which is a loss of the spread and not a free option.
MAXBARS = 96
#: `vol_gate.py`'s forward-volatility horizon, so the two studies measure one
#: object.
HORIZON = 12
#: The EWMA span and the half-normal correction `sqrt(pi/2)` that turns a mean
#: absolute return into a standard deviation, as `vetoes.py` defines it.
VOL_SPAN = 14

#: Three reaches, swept. `null-structure-claims-on-the-same-detector` requires
#: it: a single window length is a single cell, and an estimator's bias moves
#: with the number of scales the window affords.
WIDTHS = (64, 128, 256)
#: One reading every two hours. The readings are forward-filled to every bar for
#: the race, which stays causal - a reading from bar `t` is used at `t + k`.
STRIDE = 8

#: Blocks of 24 bars - six hours - for the block-shuffled arm. **Not 96.** A
#: one-day block leaves the shortest window (64 bars) entirely inside a single
#: block, so the null would be almost the real series and a gap of zero there
#: would mean nothing. At 24 the shortest window straddles two blocks and the
#: longest ten.
BLOCK = 24
#: Sub-steps per generated bar, so a bar's high and low are the path's own
#: extremes. `excursion-scaling.md` spent three control failures on a generator
#: that added an independent wick and returned a scaling exponent of 0.42 where
#: the truth was 0.5.
SUBSTEPS = 20

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD", "XAGUSD", "BTCUSD")

#: Each control is labelled with the **property it controls for**, because
#: `a-control-is-only-for-a-named-property` records Boom/Crash gaining more than
#: any traded class on a statistic nobody had said they should be flat on.
PROPERTY = {
    "Volatility 75 Index": "constant volatility: no volatility structure to restate",
    "Volatility 25 Index": "constant volatility, lower dose: the same, at a different scale",
    "Step Index": "fixed step: neither clustering nor a tail",
    "Jump 75 Index": "jumps on a constant-volatility base: a tail without clustering",
    "Range Break 100 Index": "a range by construction: the positive control for a level",
    "Range Break 200 Index": "a range by construction, longer: the dose",
    "Drift Switch Index 10": "a drift that genuinely switches: the planted regime",
    "Drift Switch Index 30": "the same, at a third of the rate: the dose",
    "Boom 500 Index": "one-sided spikes: skew without two-sided clustering",
    "Crash 500 Index": "the mirror of Boom: the sign control for skew",
}
CONTROL = tuple(PROPERTY)

#: The broker's point per symbol, and the spread the terminal **quoted** on
#: 2026-11-05, in points. **`spread` in the bar data is a count of points, not a
#: price** - `seqlab.tick_size`'s docstring puts the error at a factor of one
#: thousand to one hundred thousand, and it is silent because the number stays
#: small and positive. The quoted figure is used rather than the stored column
#: because the column reads 3.3-8.3x below it on FX and 6.5x above it on
#: `Volatility 75 Index`.
POINT = {
    "EURUSD": 1e-05, "GBPUSD": 1e-05, "USDJPY": 0.001, "AUDUSD": 1e-05,
    "USDCAD": 1e-05, "XAUUSD": 0.01, "XAGUSD": 0.001, "BTCUSD": 0.001,
    "Volatility 75 Index": 0.01, "Volatility 25 Index": 0.001,
    "Step Index": 0.1, "Jump 75 Index": 0.01,
}
SPREAD_POINTS = {
    "EURUSD": 9, "GBPUSD": 11, "USDJPY": 9, "AUDUSD": 7, "USDCAD": 10,
    "XAUUSD": 16, "XAGUSD": 30, "BTCUSD": 18_424, "Volatility 75 Index": 1_343,
    "Volatility 25 Index": 331, "Step Index": 1, "Jump 75 Index": 180,
}
#: The desk's ceiling: a round trip above this share of the risk is refused
#: unmeasured rather than measured and reported as a loss.
COST_CEILING = 0.16

ESTIMATORS = ("higuchi", "boxdim", "dfa_ret", "dfa_abs", "rs", "mf_hurst", "mf_curv")
#: `trailing` is not a fractal statistic. It is the incumbent `nulls.py` calls
#: "the one nothing here has beaten", carried in every cell so a fractal reading
#: is judged against what the desk already has rather than against zero.
INCUMBENT = "trailing"
READINGS = (*ESTIMATORS, INCUMBENT)

SIGNAL_ARMS = ("real", "bar-shuffle", "block", "garch", "walk")
#: The race arms are **permutations of real bars only.** A generated arm would
#: need a generated high and low, and the bar geometry of a barrier race is
#: exactly what a generator gets wrong; permuting real bars keeps every bar's
#: own range and skew by construction.
RACE_ARMS = ("real", "bar-shuffle", "block")

RULES = ("mom1", "rev1", "donch")
DONCHIAN = 20


def seeded(*parts: object) -> np.random.Generator:
    """A generator seeded by the cell's name. `hash()` of a tuple holding a
    string is salted per process and has broken four harnesses here."""
    digest = sha256("|".join(str(p) for p in parts).encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


@dataclass
class Bars:
    """OHLC and the causal volatility estimate, oldest first."""

    symbol: str
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    vol: np.ndarray = field(default_factory=lambda: np.empty(0))

    def __len__(self) -> int:
        return len(self.close)


def volatility(close: np.ndarray, span: int = VOL_SPAN) -> np.ndarray:
    """EWMA of `|log return|` scaled by `sqrt(pi / 2)`, as a **relative** sd.

    Causal: the value at `t` uses returns up to and including `t`. The first
    `span` entries are warming and are refused by the callers rather than used.
    """
    step = np.zeros(len(close))
    step[1:] = np.abs(np.diff(np.log(np.maximum(close, 1e-12))))
    alpha = 2.0 / (span + 1.0)
    out = np.empty(len(close))
    running = step[1] if len(step) > 1 else 0.0
    for i in range(len(close)):
        running = alpha * step[i] + (1.0 - alpha) * running
        out[i] = running
    return out * np.sqrt(np.pi / 2.0)


def load(symbol: str) -> Bars | None:
    """`$SEQLAB/<symbol>.15m.npz`, falling back to `$SYN`, bars repaired to
    contain their own open and close."""
    for root in (SEQLAB, SYN):
        path = root / f"{symbol}.{BASE}.npz"
        if not path.exists():
            continue
        z = np.load(path)
        order = np.argsort(z["time"].astype(np.int64), kind="stable")
        time = z["time"].astype(np.int64)[order]
        keep = np.concatenate([[True], np.diff(time) > 0])
        o, h, lo, c = (np.asarray(z[k], dtype=float)[order][keep] for k in ("open", "high", "low", "close"))
        bars = Bars(
            symbol=symbol,
            open=o,
            high=np.maximum.reduce([o, h, c]),
            low=np.minimum.reduce([o, lo, c]),
            close=c,
        )
        bars.vol = volatility(bars.close)
        return bars
    return None


def rechained(bars: Bars, order: np.ndarray) -> Bars:
    """The same bars in a new order, re-chained onto a running close.

    Each bar keeps its **own** log offsets from its open - high, low, close -
    and its own opening gap, so the bar distribution, its skew and its range are
    preserved exactly and only the order is destroyed. That is the
    `bar-shuffle` arm `excursion-scaling-prereg.md` names: it is simultaneously
    the null and a positive control on the estimator, because shuffled bars must
    return the estimator's own bias whatever the marginal distribution is.
    """
    log_open = np.log(np.maximum(bars.open, 1e-12))
    offsets = {
        k: np.log(np.maximum(getattr(bars, k), 1e-12)) - log_open for k in ("high", "low", "close")
    }
    gap = np.empty(len(bars))
    gap[0] = 0.0
    gap[1:] = log_open[1:] - np.log(np.maximum(bars.close[:-1], 1e-12))

    level = log_open[0]
    opens = np.empty(len(order))
    for i, j in enumerate(order):
        level = level + gap[j] if i else level
        opens[i] = level
        level = level + offsets["close"][j]
    out = Bars(
        symbol=bars.symbol,
        open=np.exp(opens),
        high=np.exp(opens + offsets["high"][order]),
        low=np.exp(opens + offsets["low"][order]),
        close=np.exp(opens + offsets["close"][order]),
    )
    out.vol = volatility(out.close)
    return out


def arm_bars(bars: Bars, arm: str) -> Bars:
    """One null arm's bars, built from `bars` with the same length and geometry."""
    n = len(bars)
    if arm == "real":
        return bars
    rng = seeded(bars.symbol, arm, n)
    if arm == "bar-shuffle":
        return rechained(bars, rng.permutation(n))
    if arm == "block":
        blocks = [np.arange(i, min(i + BLOCK, n)) for i in range(0, n, BLOCK)]
        return rechained(bars, np.concatenate([blocks[i] for i in rng.permutation(len(blocks))]))
    if arm in ("garch", "walk"):
        # Matched to the real series' own return standard deviation, so the two
        # differ in dependence and not in scale.
        sigma = float(np.std(np.diff(np.log(np.maximum(bars.close, 1e-12)))))
        if arm == "walk":
            step = rng.standard_normal(n * SUBSTEPS) * sigma / np.sqrt(SUBSTEPS)
        else:
            persistence = nulls.garch_persistence()
            if persistence >= 1.0:
                raise ValueError(f"garch persistence {persistence} would explode")
            step = np.asarray(
                nulls.garch(n * SUBSTEPS, seed=int(rng.integers(1 << 31)), sigma=sigma / np.sqrt(SUBSTEPS))
            )
        built = fractalest.bars_from_path(step, SUBSTEPS)
        base = float(bars.close[0])
        out = Bars(
            symbol=bars.symbol,
            open=base * np.exp(built["open"]),
            high=base * np.exp(built["high"]),
            low=base * np.exp(built["low"]),
            close=base * np.exp(built["close"]),
        )
        out.vol = volatility(out.close)
        return out
    raise ValueError(f"unknown arm {arm}")


def readings(bars: Bars, width: int, chunk: int = 8192) -> dict[str, np.ndarray]:
    """Every estimator at `width`, one value per strided window, chunked.

    Chunked because a 294,000-bar series at stride 8 is 36,000 windows and the
    structure function holds a `(windows, width)` increment array per scale; at
    width 256 that is 75MB a scale, times twelve workers.
    """
    log_close = np.log(np.maximum(bars.close, 1e-12))
    step = np.concatenate([[0.0], np.diff(log_close)])
    out: dict[str, list[np.ndarray]] = {k: [] for k in READINGS}
    total = max((len(bars) - width) // STRIDE + 1, 0)
    for start in range(0, total, chunk):
        # Row `i` ends at bar `i * STRIDE + width - 1`, so rows `start` to
        # `end - 1` need bars up to `(end - 1) * STRIDE + width - 1`. Writing
        # `end * STRIDE + width` instead returns **one extra window per chunk**,
        # which only shows up on a series long enough to need more than one:
        # a 294,499-bar feed produced 36,809 readings against 36,805 window
        # ends and the misalignment surfaced as an IndexError four chunks later,
        # not as a wrong number.
        end = min(start + chunk, total)
        lo = start * STRIDE
        hi = (end - 1) * STRIDE + width
        price = fractalest.windows(log_close[lo:hi], width, STRIDE)
        rets = fractalest.windows(step[lo:hi], width, STRIDE)
        hurst, curvature = fractalest.structure_scaling(price)
        out["higuchi"].append(fractalest.higuchi(price))
        out["boxdim"].append(fractalest.box_dimension(price))
        out["dfa_ret"].append(fractalest.dfa(rets))
        out["dfa_abs"].append(fractalest.dfa(np.abs(rets)))
        out["rs"].append(fractalest.rescaled_range(rets))
        out["mf_hurst"].append(hurst)
        out["mf_curv"].append(curvature)
        out[INCUMBENT].append(rets.std(axis=1))
    return {k: (np.concatenate(v) if v else np.empty(0)) for k, v in out.items()}


def ends(bars: Bars, width: int) -> np.ndarray:
    """The bar index each strided window ends at - where its reading is usable."""
    total = max((len(bars) - width) // STRIDE + 1, 0)
    return np.arange(total) * STRIDE + width - 1


def auc(score: np.ndarray, label: np.ndarray) -> float:
    """Rank-based AUC. `nan` when either class is empty, never 0.5 - a fabricated
    0.5 enters a mean as a measurement of indifference rather than as a gap."""
    ok = np.isfinite(score) & np.isfinite(label)
    score, label = score[ok], label[ok].astype(bool)
    positives = int(label.sum())
    negatives = int((~label).sum())
    if positives == 0 or negatives == 0:
        return float("nan")
    rank = np.empty(len(score))
    order = np.argsort(score, kind="stable")
    sorted_score = score[order]
    # Average ranks within ties, or a constant reading would score 1.0 on the
    # class that happens to sort first.
    i = 0
    while i < len(sorted_score):
        j = i
        while j + 1 < len(sorted_score) and sorted_score[j + 1] == sorted_score[i]:
            j += 1
        rank[order[i : j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return (rank[label].sum() - positives * (positives + 1) / 2.0) / (positives * negatives)


def _rank_corr(xs: np.ndarray, ys: np.ndarray) -> float:
    """Spearman correlation over the entries where both are finite."""
    ok = np.isfinite(xs) & np.isfinite(ys)
    if ok.sum() < 30:
        return float("nan")
    a = np.argsort(np.argsort(xs[ok])).astype(float)
    b = np.argsort(np.argsort(ys[ok])).astype(float)
    if a.std() == 0 or b.std() == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def strata(values: np.ndarray, fitted: np.ndarray, bands: int = 5) -> np.ndarray:
    """Quintile label per value, from thresholds fitted on `fitted` alone.

    Thresholds from the training block, not from the scored block: quantiles
    read off the scored sample are a mild look-ahead that makes every stratum
    exactly equal in size and flatters a within-strata figure.
    """
    edges = np.nanquantile(fitted, np.linspace(0, 1, bands + 1)[1:-1])
    return np.digitize(values, edges)


def within_strata(score: np.ndarray, label: np.ndarray, band: np.ndarray) -> float:
    """AUC computed inside each volatility quintile and pooled by weight of n.

    **This is the column the verdict is read from.**
    `auc-is-free-on-volatility-targets` measures 0.805 pooled against 0.525
    within strata on a constant-volatility process, so a pooled AUC on a
    volatility-linked target carries almost no information about whether a
    reading adds anything.
    """
    total = 0.0
    weight = 0.0
    for b in np.unique(band[np.isfinite(band)]):
        m = band == b
        if m.sum() < 200:
            continue
        got = auc(score[m], label[m])
        if np.isfinite(got):
            total += got * int(m.sum())
            weight += int(m.sum())
    return total / weight if weight else float("nan")


def race(
    bars: Bars, entries: np.ndarray, side: np.ndarray, cost_px: np.ndarray
) -> dict[str, np.ndarray]:
    """A de-overlapped barrier race: one position at a time, stop and target in R.

    Entry at the close of a flagged bar, stop `STOP_MULT` relative volatility
    units away, target `TARGET_MULT` times that. Scanned forward to `MAXBARS`
    and marked out at the close if neither barrier is reached.

    **One position at a time, and that is not a nicety.**
    `overlapping-outcome-windows-leak` records a direction AUC of 0.79
    collapsing to 0.51 once the outcome windows stopped overlapping; two open
    positions over the same bars are one observation counted twice, and the
    standard error it produces is the standard error of a larger sample than
    exists.

    **A bar that touches both barriers is scored as the stop.** The bar's path
    is not in the data, so the alternative is to award the better of two
    outcomes on no evidence.
    """
    out_r: list[float] = []
    out_i: list[int] = []
    out_hit: list[int] = []
    out_cost: list[float] = []
    free_at = 0
    high, low, close, vol = bars.high, bars.low, bars.close, bars.vol
    n = len(close)
    for i in np.flatnonzero(entries):
        if i < free_at or i + 1 >= n:
            continue
        s = int(side[i])
        if s == 0 or not np.isfinite(vol[i]) or vol[i] <= 0:
            continue
        risk = STOP_MULT * vol[i] * close[i]
        if risk <= 0:
            continue
        stop = close[i] - s * risk
        target = close[i] + s * TARGET_MULT * risk
        stop_px = low if s > 0 else high
        target_px = high if s > 0 else low
        last = min(i + MAXBARS, n - 1)
        hit = 0
        gross = 0.0
        for j in range(i + 1, last + 1):
            stopped = (stop_px[j] <= stop) if s > 0 else (stop_px[j] >= stop)
            reached = (target_px[j] >= target) if s > 0 else (target_px[j] <= target)
            if stopped:
                hit, gross = -1, -1.0
                break
            if reached:
                hit, gross = 1, TARGET_MULT
                break
        if hit == 0:
            j = last
            gross = s * (close[j] - close[i]) / risk
        # Cost in R is `cost_px / risk` and `risk` is this trade's own stop, so
        # it is carried per trade rather than reconstructed from a median later:
        # the median stop and the median cost are not the stop and cost of any
        # trade, and gross would then not be net plus cost.
        out_cost.append(float(cost_px[i]) / risk)
        out_r.append(gross - out_cost[-1])
        out_i.append(int(i))
        out_hit.append(hit)
        free_at = j + 1
    return {
        "net": np.asarray(out_r),
        "entry": np.asarray(out_i, dtype=int),
        "hit": np.asarray(out_hit, dtype=int),
        "cost": np.asarray(out_cost),
    }


def day_block_error(values: np.ndarray, index: np.ndarray, draws: int = 400) -> float:
    """Standard error by resampling whole days, not trades.

    `block bootstrap when the rows are not independent`: trades cluster in days,
    so an ordinary standard error is far too narrow.
    """
    if len(values) < 30:
        return float("nan")
    day = index // MAXBARS
    unique = np.unique(day)
    if len(unique) < 10:
        return float("nan")
    rng = seeded("dayblock", len(values))
    means = np.empty(draws)
    groups = [values[day == d] for d in unique]
    for k in range(draws):
        pick = rng.integers(0, len(groups), len(groups))
        means[k] = np.concatenate([groups[i] for i in pick]).mean()
    return float(np.std(means))


def benjamini_hochberg(p: Sequence[float], alpha: float = 0.05) -> np.ndarray:
    """Which of `p` survive at `alpha`. Picking the best of many cells gives a
    winner every time: on this desk 18 of 43 instruments were nominally
    profitable where chance gives 22, and not one survived this."""
    values = np.asarray(p, dtype=float)
    ok = np.isfinite(values)
    out = np.zeros(len(values), dtype=bool)
    if not ok.any():
        return out
    order = np.argsort(values[ok])
    m = int(ok.sum())
    passed = values[ok][order] <= alpha * np.arange(1, m + 1) / m
    if passed.any():
        cut = np.max(np.flatnonzero(passed))
        keep = np.flatnonzero(ok)[order][: cut + 1]
        out[keep] = True
    return out


def normal_p(z: float) -> float:
    """Two-sided normal tail, by the error function."""
    if not np.isfinite(z):
        return float("nan")
    from math import erfc, sqrt

    return float(erfc(abs(z) / sqrt(2.0)))


# ---------------------------------------------------------------- A: the cost screen


def part_cost() -> dict[str, float]:
    """Price the round trip before measuring anything. It ends most intraday ideas."""
    print(f"\n{'=' * 104}\nA. COST, at a {STOP_MULT:g}-volatility-unit stop on {BASE}")
    print(
        f"{'instrument':24s} {'bars':>9s} {'med vol':>9s} {'quoted bps':>11s} "
        f"{'round trip R':>13s} {'target %':>9s}  clears {COST_CEILING:.2f}R"
    )
    out: dict[str, float] = {}
    for symbol in (*TRADED, *CONTROL):
        bars = load(symbol)
        if bars is None:
            print(f"{symbol:24s} {'-':>9s}  not in the store")
            continue
        if symbol not in SPREAD_POINTS:
            print(
                f"{symbol:24s} {len(bars):>9,}  no quoted spread: run gross, and say so"
            )
            continue
        vol = bars.vol[VOL_SPAN * 4 :]
        spread_px = SPREAD_POINTS[symbol] * POINT[symbol]
        median_px = float(np.median(bars.close[VOL_SPAN * 4 :]))
        cost_r = spread_px / (STOP_MULT * float(np.median(vol)) * median_px)
        out[symbol] = cost_r
        print(
            f"{symbol:24s} {len(bars):>9,} {float(np.median(vol)):>9.5f} "
            f"{spread_px / median_px * 1e4:>11.3f} {cost_r:>13.3f} "
            f"{cost_r / TARGET_MULT * 100:>8.1f}%  {'yes' if cost_r <= COST_CEILING else 'NO'}"
        )
    return out


# ---------------------------------------------------------------- B: power


#: The planted exponents. 0.50 is the reference every other row is compared
#: against, and the ladder is symmetric so an estimator that only resolves
#: persistence is told apart from one that resolves both sides.
PLANTED = (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)
POWER_DRAWS = 24
POWER_BARS = 40_000


#: The per-bar return standard deviation every plant is rescaled to, which is
#: EURUSD's measured median at this clock (0.00034).
PLANT_VOL = 4e-4


def planted_bars(hurst: float, draw: int, count: int = POWER_BARS) -> Bars:
    """`count` bars of a fractional Brownian motion with exponent `hurst`.

    **Rescaled to `PLANT_VOL` a bar, and that is not cosmetic.** A fractional
    Brownian path grows as `N**H`, so at `H = 0.70` and 800,000 steps a fixed
    multiplier that was sane at `H = 0.30` put the log price across a span of
    137. Every window was then a near-deterministic ramp and the estimators
    reported it faithfully: Higuchi read **1.01 at H = 0.65 and 0.58 at 0.70** -
    the dimension of a straight line - after rising monotonically from 1.71 to
    1.38 across `H` of 0.30 to 0.60. The power curve looked like an estimator
    that breaks down above 0.6 and was a generator on the wrong scale.

    Rescaling the increments is safe for the exponent: `H` is invariant under a
    linear rescaling of the path, which is what makes this the right fix rather
    than a shorter series. `a-synthetic-at-price-one-hides-scale-bugs` is why
    the level is 100 and not 1.
    """
    rng = seeded("power", hurst, draw)
    built = fractalest.bars_from_path(fractalest.fbm(count * SUBSTEPS, hurst, rng), SUBSTEPS)
    spread = float(np.std(np.diff(built["close"])))
    scale = PLANT_VOL / max(spread, 1e-18)
    bars = Bars(
        symbol=f"fbm-{hurst:.2f}",
        open=100.0 * np.exp(built["open"] * scale),
        high=100.0 * np.exp(built["high"] * scale),
        low=100.0 * np.exp(built["low"] * scale),
        close=100.0 * np.exp(built["close"] * scale),
    )
    bars.vol = volatility(bars.close)
    return bars


def _power_cell(job: tuple[float, int]) -> dict[str, object]:
    """One `(hurst, draw)`: every estimator at every width, plus the rule's gross R."""
    hurst, draw = job
    bars = planted_bars(hurst, draw)
    out: dict[str, object] = {"hurst": hurst, "draw": draw}
    sides = _rule_side(bars)
    # Gross, with no cost: the plant has no quoted spread, and inventing one is
    # the one error that looks like a measurement. `cost-screen-the-book-you-have`
    # is about real instruments; this arm answers whether the rule can see a
    # planted exponent at all, which is a question before cost.
    free = np.zeros(len(bars))
    for width in WIDTHS:
        got = readings(bars, width)
        at = ends(bars, width)
        for k in ESTIMATORS:
            out[f"{k}@{width}"] = float(np.nanmedian(got[k]))
        if len(at) < 100:
            continue
        split = len(at) // 2
        warm = np.zeros(len(bars), dtype=bool)
        warm[at[split] :] = True
        edges = np.nanquantile(got["dfa_ret"][:split], [1 / 3, 2 / 3])
        label = np.full(len(bars), -1, dtype=int)
        label[at] = np.digitize(got["dfa_ret"], edges)
        last = -1
        for i in range(len(label)):
            if label[i] >= 0:
                last = label[i]
            else:
                label[i] = last
        base = sides["mom1"]
        switched = np.where(label == 2, base, np.where(label == 0, -base, 0.0))
        for name, entries, side in (
            (f"switch@{width}", warm & (switched != 0), switched),
            (f"always@{width}", warm & (base != 0), base),
        ):
            got_race = race(bars, entries, side, free)
            out[name] = float(got_race["net"].mean()) if len(got_race["net"]) >= 30 else float("nan")
            out[f"n-{name}"] = int(len(got_race["net"]))
    return out


def part_power() -> None:
    """Plant a known exponent, read it back, and say where the test goes blind."""
    print(f"\n{'=' * 104}\nB. POWER - a planted fractional Brownian motion, read through the same estimators")
    print(
        f"bars built from {SUBSTEPS} aggregated path steps, so the high and low are the path's own "
        f"extremes;\n{POWER_DRAWS} independent draws of {POWER_BARS:,} bars per exponent, "
        f"{len(WIDTHS)} widths. The rule arm is **gross**: a plant has no quoted spread"
    )
    jobs = [(h, d) for h in PLANTED for d in range(POWER_DRAWS)]
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        got = list(pool.map(_power_cell, jobs))

    def column(key: str, hurst: float) -> np.ndarray:
        return np.array([float(r[key]) for r in got if r["hurst"] == hurst and key in r])

    for width in WIDTHS:
        print(f"\n  width {width}: the estimator's own reading, mean over draws")
        print(f"    {'H':>5s} " + " ".join(f"{k:>10s}" for k in ESTIMATORS))
        for h in PLANTED:
            cells = [np.nanmean(column(f"{k}@{width}", h)) for k in ESTIMATORS]
            print(f"    {h:>5.2f} " + " ".join(f"{c:>10.4f}" for c in cells))
        print(
            f"    {'sd':>5s} "
            + " ".join(f"{np.nanstd(column(f'{k}@{width}', 0.50)):>10.4f}" for k in ESTIMATORS)
        )
        print("    smallest |H - 0.5| the estimator separates at |z| > 2:")
        for k in ESTIMATORS:
            reference = column(f"{k}@{width}", 0.50)
            blind = "never"
            for h in PLANTED:
                if h == 0.50:
                    continue
                here = column(f"{k}@{width}", h)
                spread = np.sqrt(np.nanstd(reference) ** 2 + np.nanstd(here) ** 2) / np.sqrt(
                    POWER_DRAWS
                )
                if spread > 0 and abs(np.nanmean(here) - np.nanmean(reference)) / spread > 2.0:
                    blind = f"{abs(h - 0.50):.2f}"
                    break
            print(f"      {k:>10s}  resolves from {blind}")

    print("\n  the RULE on the same plants: gross R a trade, and whether the switch finds the regime")
    print(
        f"    {'H':>5s} " + " ".join(f"{'sw@' + str(w):>12s} {'alw@' + str(w):>12s}" for w in WIDTHS)
    )
    for h in PLANTED:
        cells: list[str] = []
        for w in WIDTHS:
            for key in (f"switch@{w}", f"always@{w}"):
                values = column(key, h)
                spread = np.nanstd(values) / np.sqrt(max(len(values), 1))
                mark = "*" if spread > 0 and abs(np.nanmean(values)) / spread > 2.0 else " "
                cells.append(f"{np.nanmean(values):>+11.4f}{mark}")
        print(f"    {h:>5.2f} " + " ".join(cells))
    print("    * the mean is more than two standard errors from zero over the draws")


# ---------------------------------------------------------------- C: the signal


def _signal_cell(job: tuple[str, str]) -> list[dict[str, object]]:
    symbol, arm = job
    bars = load(symbol)
    if bars is None:
        return []
    bars = arm_bars(bars, arm)
    log_close = np.log(np.maximum(bars.close, 1e-12))
    rows: list[dict[str, object]] = []
    for width in WIDTHS:
        got = readings(bars, width)
        at = ends(bars, width)
        if not len(at):
            continue
        ahead = at + HORIZON
        usable = ahead < len(bars)
        at, ahead = at[usable], ahead[usable]
        # Forward realised volatility and forward direction, both de-overlapped
        # by the stride: consecutive readings are STRIDE apart and the horizon
        # is HORIZON, so they overlap whenever HORIZON > STRIDE. Thinned to
        # every ceil(HORIZON / STRIDE)-th reading so no two outcomes share a bar.
        thin = int(np.ceil(HORIZON / STRIDE))
        keep = np.zeros(len(at), dtype=bool)
        keep[::thin] = True
        at, ahead = at[keep], ahead[keep]
        forward = np.array(
            [np.abs(np.diff(log_close[a : b + 1])).sum() for a, b in zip(at, ahead, strict=True)]
        )
        signed = log_close[ahead] - log_close[at]
        split = len(at) // 2
        vol_at = bars.vol[at]
        band = strata(vol_at, vol_at[:split])
        big = forward > np.nanmedian(forward[:split])
        up = signed > 0.0
        for name in READINGS:
            value = got[name][usable][keep]
            rows.append(
                {
                    "symbol": symbol, "arm": arm, "width": width, "reading": name,
                    "n": int(np.isfinite(value).sum()),
                    "vol_auc": auc(value, big),
                    "vol_auc_strata": within_strata(value, big, band),
                    "dir_auc": auc(value, up),
                    "dir_auc_strata": within_strata(value, up, band),
                    # Rank correlation with trailing volatility: how much of
                    # the reading **is** the volatility. Computed over finite
                    # readings only - `nan_to_num` would rank every missing
                    # window as the smallest value and report a correlation
                    # with the pattern of missingness.
                    "vol_corr": _rank_corr(value, vol_at),
                }
            )
    return rows


def part_signal() -> list[dict[str, object]]:
    print(f"\n{'=' * 104}\nC. THE SIGNAL - forward volatility and forward direction, pooled and within volatility quintiles")
    print(
        f"outcome horizon {HORIZON} bars, de-overlapped so no two outcomes share a bar; "
        f"strata fitted on the first half"
    )
    jobs = [(s, a) for s in (*TRADED, *CONTROL) for a in SIGNAL_ARMS]
    rows: list[dict[str, object]] = []
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for got in pool.map(_signal_cell, jobs):
            rows.extend(got)
    _report_signal(rows)
    return rows


def _report_signal(rows: Iterable[dict[str, object]]) -> None:
    rows = list(rows)
    for width in WIDTHS:
        print(f"\n  width {width}: forward-volatility AUC, pooled -> within strata (real arm)")
        print(
            f"    {'instrument':24s} " + " ".join(f"{k:>16s}" for k in READINGS)
        )
        for symbol in (*TRADED, *CONTROL):
            cells = []
            for name in READINGS:
                hit = [
                    r for r in rows
                    if r["symbol"] == symbol and r["arm"] == "real"
                    and r["width"] == width and r["reading"] == name
                ]
                if not hit:
                    cells.append(f"{'-':>16s}")
                    continue
                cells.append(f"{hit[0]['vol_auc']:>7.3f}->{hit[0]['vol_auc_strata']:<8.3f}")
            label = symbol if symbol in TRADED else f"  {symbol}"
            print(f"    {label:24s} " + " ".join(cells))

    print("\n  the same, by arm: median over traded instruments")
    print(f"    {'arm':14s} {'reading':10s} {'vol pooled':>11s} {'vol strata':>11s} {'dir pooled':>11s} {'dir strata':>11s} {'rank vs vol':>12s}")
    for arm in SIGNAL_ARMS:
        for name in READINGS:
            hit = [r for r in rows if r["arm"] == arm and r["reading"] == name and r["symbol"] in TRADED]
            if not hit:
                continue
            def med(key: str) -> float:
                return float(np.nanmedian([h[key] for h in hit]))
            print(
                f"    {arm:14s} {name:10s} {med('vol_auc'):>11.3f} {med('vol_auc_strata'):>11.3f} "
                f"{med('dir_auc'):>11.3f} {med('dir_auc_strata'):>11.3f} {med('vol_corr'):>12.3f}"
            )


# ---------------------------------------------------------------- D: the trade


def _rule_side(bars: Bars) -> dict[str, np.ndarray]:
    """The base direction rules, causal at each bar's close."""
    close = bars.close
    step = np.concatenate([[0.0], np.diff(np.log(np.maximum(close, 1e-12)))])
    mom = np.sign(step)
    out = {"mom1": mom, "rev1": -mom}
    high = np.full(len(close), np.nan)
    low = np.full(len(close), np.nan)
    if len(close) > DONCHIAN:
        rolled = fractalest.windows(close, DONCHIAN, 1)
        high[DONCHIAN - 1 :] = rolled.max(axis=1)
        low[DONCHIAN - 1 :] = rolled.min(axis=1)
    donch = np.zeros(len(close))
    donch[1:] = np.where(
        close[1:] >= high[:-1], 1.0, np.where(close[1:] <= low[:-1], -1.0, 0.0)
    )
    out["donch"] = donch
    return out


def _trade_cell(job: tuple[str, str]) -> list[dict[str, object]]:
    """The switch rule and its controls on one (instrument, arm)."""
    symbol, arm = job
    if symbol not in SPREAD_POINTS:
        return []
    bars = load(symbol)
    if bars is None:
        return []
    bars = arm_bars(bars, arm)
    cost_px = np.full(len(bars), SPREAD_POINTS[symbol] * POINT[symbol])
    sides = _rule_side(bars)
    rows: list[dict[str, object]] = []
    for width in WIDTHS:
        got = readings(bars, width)
        at = ends(bars, width)
        if len(at) < 100:
            continue
        split = len(at) // 2
        for name in ESTIMATORS:
            value = got[name]
            if not np.isfinite(value).any():
                continue
            # Terciles of the training half. The switch takes continuation in
            # the top tercile, reversion in the bottom, and nothing in the
            # middle - so the rule is on for two thirds of the readings and its
            # duty-cycle twin is matched to exactly that.
            edges = np.nanquantile(value[:split], [1 / 3, 2 / 3])
            label = np.digitize(value, edges)
            filled = np.full(len(bars), -1, dtype=int)
            filled[at] = label
            # Forward-filled: a reading taken at bar `t` stays usable until the
            # next one. Causal, since it never moves earlier.
            last = -1
            for i in range(len(filled)):
                if filled[i] >= 0:
                    last = filled[i]
                else:
                    filled[i] = last
            warm = np.zeros(len(bars), dtype=bool)
            warm[at[split] :] = True
            for rule in RULES:
                base = sides[rule]
                switched = np.where(filled == 2, base, np.where(filled == 0, -base, 0.0))
                on = warm & (switched != 0)
                rng = seeded(symbol, arm, width, name, rule, "twin")
                # The duty-cycle twin: the same number of trades, the same base
                # rule, the switch replaced by a coin. On a net-negative book any
                # rule that trades less shows a profit improvement, so a headline
                # against "always on" carries no information.
                coin = np.where(rng.random(len(bars)) < 0.5, base, -base)
                twin_on = warm & (base != 0) & (rng.random(len(bars)) < float(on.mean() / max((warm & (base != 0)).mean(), 1e-9)))
                for label_name, entries, side in (
                    ("switch", on, switched),
                    ("inverted", on, -switched),
                    ("twin", twin_on, coin),
                    ("base-always", warm & (base != 0), base),
                ):
                    got_race = race(bars, entries, side, cost_px)
                    net = got_race["net"]
                    if len(net) < 30:
                        continue
                    vol_band = strata(bars.vol[got_race["entry"]], bars.vol[: at[split]])
                    rows.append(
                        {
                            "symbol": symbol, "arm": arm, "width": width,
                            "reading": name, "rule": rule, "variant": label_name,
                            "n": int(len(net)),
                            "net": float(net.mean()),
                            "se": day_block_error(net, got_race["entry"]),
                            "win": float((got_race["hit"] == 1).mean()),
                            "cost": float(got_race["cost"].mean()),
                            "gross": float(net.mean() + got_race["cost"].mean()),
                            "by_band": [
                                (
                                    int(b),
                                    int((vol_band == b).sum()),
                                    float(net[vol_band == b].mean()),
                                )
                                for b in range(5)
                                if (vol_band == b).sum() >= 30
                            ],
                        }
                    )
    return rows


def part_trade() -> list[dict[str, object]]:
    print(f"\n{'=' * 104}\nD. THE TRADE - the Hurst switch: continuation in the top tercile, reversion in the bottom")
    print(
        f"de-overlapped, one position at a time, stop {STOP_MULT:g} volatility units, target "
        f"{TARGET_MULT:g}x it,\nmarked out at {MAXBARS} bars, net of the quoted round trip; "
        f"a walk reaches the target first {RACE_BASE:.4f} of the time"
    )
    jobs = [(s, a) for s in (*TRADED, *CONTROL) for a in RACE_ARMS]
    rows: list[dict[str, object]] = []
    with ProcessPoolExecutor(max_workers=WORKERS) as pool:
        for got in pool.map(_trade_cell, jobs):
            rows.extend(got)
    _report_trade(rows)
    return rows


def _report_trade(rows: Iterable[dict[str, object]]) -> None:
    rows = list(rows)
    if not rows:
        print("  nothing measured")
        return
    real = [r for r in rows if r["arm"] == "real" and r["variant"] == "switch"]
    print(f"\n  {len(rows)} cells measured, {len(real)} of them the real arm's switch")

    print("\n  per instrument: the best switch cell, and the same cell's twin and shuffled arms")
    print(
        f"    {'instrument':24s} {'reading':10s} {'w':>4s} {'rule':6s} {'n':>6s} "
        f"{'net R':>9s} {'se':>7s} {'win':>7s} {'twin':>9s} {'shuffled':>9s}"
    )
    for symbol in (*TRADED, *CONTROL):
        here = [r for r in real if r["symbol"] == symbol and np.isfinite(r["se"])]
        if not here:
            continue
        best = max(here, key=lambda r: float(r["net"]))
        def mate(arm: str, variant: str) -> float:
            hit = [
                r for r in rows
                if r["symbol"] == symbol and r["arm"] == arm and r["variant"] == variant
                and r["width"] == best["width"] and r["reading"] == best["reading"]
                and r["rule"] == best["rule"]
            ]
            return float(hit[0]["net"]) if hit else float("nan")
        label = symbol if symbol in TRADED else f"  {symbol}"
        print(
            f"    {label:24s} {best['reading']:10s} {best['width']:>4d} {best['rule']:6s} "
            f"{best['n']:>6,} {best['net']:>+9.4f} {best['se']:>7.4f} {best['win']:>7.4f} "
            f"{mate('real', 'twin'):>+9.4f} {mate('bar-shuffle', 'switch'):>+9.4f}"
        )

    scored = [r for r in real if np.isfinite(r["se"]) and r["se"] > 0]
    if scored:
        z = [float(r["net"]) / float(r["se"]) for r in scored]
        p = [normal_p(v) for v in z]
        kept = benjamini_hochberg(p)
        winners = int(sum(1 for i, r in enumerate(scored) if kept[i] and float(r["net"]) > 0))
        losers = int(sum(1 for i, r in enumerate(scored) if kept[i] and float(r["net"]) < 0))
        positive = int(sum(1 for r in scored if float(r["net"]) > 0))
        print(
            f"\n  multiplicity over {len(scored)} real-arm switch cells: {positive} nominally positive, "
            f"Benjamini-Hochberg keeps {winners} as profitable and {losers} as losing"
        )

    print("\n  pooled by variant, traded instruments only: mean net R and the hit rate against 1/(1+N)")
    print(
        f"    {'variant':14s} {'arm':14s} {'cells':>7s} {'n':>9s} {'gross R':>9s} "
        f"{'cost R':>8s} {'net R':>9s} {'win':>8s}"
    )
    for variant in ("switch", "inverted", "twin", "base-always"):
        for arm in RACE_ARMS:
            hit = [
                r for r in rows
                if r["variant"] == variant and r["arm"] == arm and r["symbol"] in TRADED
            ]
            if not hit:
                continue
            weight = [r["n"] for r in hit]
            total = int(sum(int(r["n"]) for r in hit))
            print(
                f"    {variant:14s} {arm:14s} {len(hit):>7,} {total:>9,} "
                f"{float(np.average([r['gross'] for r in hit], weights=weight)):>+9.4f} "
                f"{float(np.average([r['cost'] for r in hit], weights=weight)):>8.4f} "
                f"{float(np.average([r['net'] for r in hit], weights=weight)):>+9.4f} "
                f"{float(np.average([r['win'] for r in hit], weights=weight)):>8.4f}"
            )

    # A regime split is information, not a verdict - the operator's standing
    # instruction. If the switch pays in one volatility band and loses in the
    # others, that is a gating condition and is reported as one.
    print("\n  the real switch by volatility quintile of the entry bar, traded instruments pooled")
    print(f"    {'quintile':10s} {'n':>9s} {'net R':>9s}")
    for band in range(5):
        taken = [
            (n, value)
            for r in rows
            if r["arm"] == "real" and r["variant"] == "switch" and r["symbol"] in TRADED
            for b, n, value in r["by_band"]
            if b == band
        ]
        if not taken:
            continue
        total = sum(n for n, _ in taken)
        print(
            f"    {band + 1:<10d} {total:>9,} "
            f"{float(np.average([v for _, v in taken], weights=[n for n, _ in taken])):>+9.4f}"
        )


def main() -> None:
    print(f"fractal estimators as indicators and as rules - {BASE} base, PART={PART}")
    print(f"store: {SEQLAB}  controls: {SYN}")
    if PART in ("cost", "all"):
        part_cost()
    if PART in ("power", "all"):
        part_power()
    if PART in ("signal", "all"):
        part_signal()
    if PART in ("trade", "all"):
        part_trade()
    print("\ndone", flush=True)


if __name__ == "__main__":
    sys.exit(main())
