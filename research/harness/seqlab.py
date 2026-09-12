"""The shared floor under every sequence-model arm: cache, features, splits, controls.

Six arms run on top of this file - recurrent nets, echo state networks, a
fine-tuned Kronos, a reinforcement learner, a cross-sectional test and the
non-Volatility synthetics - and they are only comparable because they load the
same bars, build the same features and cut the same folds. Writing that layer
once is not tidiness. `research/forecasting.md` had to be revised twice and
retracted two headline claims because two volatility conventions were being
mixed in harnesses that each did their own arithmetic, and the mixing was not
symmetric so the comparisons looked clean.

## What is actually being asked, and what the answer is already known to be

`research/deriving.md` proves `E[net] = -(c/2) x turnover` for **any** predictable
position on a martingale, and `research/rebuilding.md` confirmed it on these
feeds: boosted models on tick windows, k-tuples and bar OHLC found nothing,
`n*` infinite on every arm. **Direction on a Volatility index is not an open
question.** A Volatility index is geometric Brownian motion with a published,
constant sigma; its increments are independent by construction.

So the direction arm here is a **null calibration, not a hunt**. Its job is to
come back at AUC 0.50. If it does not, the finding is a leak in this file, and
the controls below exist to catch that before it is reported as an edge. This
is the same discipline `groundgru.py` states: a learned model has paid twice on
this project and both times the payment was a feature importance that exposed a
defect, never a score.

The open question is **magnitude**.

**A claim that was in this docstring has been withdrawn, and reading the
withdrawal matters more than the claim did.** It said that because a pure GBM
has constant expected realised volatility, the unconditional mean beating the
last realised value measures whether sigma is constant. `research/controls.md`
refuted it: at horizon 1 the target is `|r_{t+1}|`, a single squared return and
the noisiest possible estimate of a variance, and a symmetric relative error
charges a forecaster for **its own noise as well as its bias**. The naive
forecast carries a full half-normal of noise where a constant carries none, so
**a forecaster that knew `sigma_t` exactly would still score about 0.88.** The
gap is dominated by noise in the target. It says nothing about whether sigma
moves, and its sign carries no information about clustering.

What the same number *is*, measured on the same rows: a **discriminator between
a real market and a Volatility index at more than twenty standard errors** on
every timeframe on the grid - -0.09 against -0.21, within-symbol standard error
0.003. A simulated GBM at gold's *own* measured sigma scores the Volatility
family's number and not gold's, which is what pins the reading: the gap is about
whether a series has a variance process at all, not about the level of its
volatility.

That these feeds have constant sigma is true and is established elsewhere -
`research/generators.md` has largest `|acf|` of absolute return at 0.017 against
0.219-0.453 on real controls, `H = 0.50`, kurtosis 2.98 to 3.02. It was never
established here, and this file should not be cited for it.

## The four controls, because a positive result means nothing without them

* **`shuffle`** - targets permuted inside the training block. Catches a model
  reading the answer through the feature matrix.
* **`surrogate`** - phase-randomised returns. Preserves the spectrum and the
  full linear autocorrelation, destroys every nonlinear dependence. A model that
  scores the same here as on the real series learned nothing but the spectrum.
* **`gbm`** - simulated geometric Brownian motion at the symbol's own measured
  sigma. The known null, where the true answer is exactly 0.50.
* **`real`** - an actual market. **The positive control, and the one that makes
  a negative result falsifiable.** If this harness cannot find volatility
  clustering on gold, "we found nothing on synthetics" is a statement about the
  harness and not about the synthetics.

## The leak boundary

Every feature at row `t` is a function of bars `<= t`. Every target is a
function of bars `> t`. `check_causality` asserts it by perturbing a future bar
and confirming no feature moves, and it runs in `main()` rather than living in
a test nobody executes.

Folds are walk-forward and never shuffled, and each carries a **purge** of
`horizon` bars - a target at the end of train overlaps the start of test, which
is the standard way this class of study leaks - plus an **embargo** after test.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import time
from pathlib import Path

import numpy as np

from research.harness import feed

#: Where pulled bars live. The feed is HTTP and 50,000 bars is a real transfer;
#: twenty-two symbols across six timeframes is an hour of waiting if every arm
#: re-pulls, and six arms running at once would hammer one terminal.
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"

#: The family this study is aimed at, by the broker's own spelling.
VOLATILITY = (
    "Volatility 10 Index",
    "Volatility 10 (1s) Index",
    "Volatility 15 Index",
    "Volatility 15 (1s) Index",
    "Volatility 25 Index",
    "Volatility 25 (1s) Index",
    "Volatility 30 Index",
    "Volatility 30 (1s) Index",
    "Volatility 50 Index",
    "Volatility 50 (1s) Index",
    "Volatility 75 Index",
    "Volatility 75 (1s) Index",
    "Volatility 90 Index",
    "Volatility 90 (1s) Index",
    "Volatility 100 Index",
    "Volatility 100 (1s) Index",
    "Volatility 5 Index",
    "Volatility 5 (1s) Index",
    "Volatility 150 (1s) Index",
    "Volatility 250 (1s) Index",
)

#: Named sigma, annualised, read off the instrument name. `grounding.md` tier 1
#: verified these to within 0.49% on 12 of 12, so they are ground truth here and
#: the simulated null can be built at the true parameter rather than a fitted one.
NAMED_SIGMA = {v: float(v.split()[1]) / 100.0 for v in VOLATILITY}

#: The two Volatility-family members whose **name says the variance moves**.
#: Everything else in the family is constant-sigma by construction, so these are
#: the only place in it where a volatility forecast could have anything to
#: forecast. They are held apart from `VOLATILITY` so a pooled result cannot be
#: carried by them.
SPOT_UP = ("Spot Up - Volatility Up Index", "Spot Up - Volatility Down Index")

#: The rest of the book, by family. `deriving.md`'s theorem covers all of them,
#: but they are not one process: Boom and Crash are compound Poisson with a
#: drift, Step is a bounded fair coin, Jump is diffusion with jumps, Range Break
#: has a reflecting geometry. A sequence model has different things to find in
#: each, which is why they are not pooled.
SYNTHETIC = {
    "boom": tuple(f"Boom {n} Index" for n in (50, 100, 150, 200, 300, 500, 600, 900, 1000)),
    "crash": tuple(f"Crash {n} Index" for n in (50, 100, 150, 200, 300, 500, 600, 900, 1000)),
    "step": (
        "Step Index",
        "Step Index 200",
        "Multi Step 2 Index",
        "Multi Step 3 Index",
        "Multi Step 4 Index",
        "Skew Step Index 4 Up",
        "Skew Step Index 4 Down",
        "Skew Step Index 5 Up",
        "Skew Step Index 5 Down",
    ),
    "jump": tuple(f"Jump {n} Index" for n in (10, 25, 50, 75, 100)),
    "range_break": ("Range Break 100 Index", "Range Break 200 Index"),
    "drift_switch": tuple(f"Drift Switch Index {n}" for n in (10, 20, 30)),
    "dex": (
        "DEX 600 UP Index",
        "DEX 600 DOWN Index",
        "DEX 900 UP Index",
        "DEX 900 DOWN Index",
        "DEX 1500 UP Index",
        "DEX 1500 DOWN Index",
    ),
}

#: The positive control. Real markets, where volatility clustering is a fact and
#: any harness that misses it is broken.
REAL = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD")

#: Bars per year, for annualising a realised volatility onto the same scale the
#: instrument names are quoted in. These indices trade continuously - no weekend,
#: no session - which is why this is 365 and not 252.
PER_YEAR = {
    "1m": 525_600.0,
    "2m": 262_800.0,
    "3m": 175_200.0,
    "5m": 105_120.0,
    "10m": 52_560.0,
    "15m": 35_040.0,
    "30m": 17_520.0,
    "1h": 8_760.0,
    "2h": 4_380.0,
    "4h": 2_190.0,
    "6h": 1_460.0,
    "8h": 1_095.0,
    "12h": 730.0,
    "1d": 365.0,
}

#: The grid this study runs on. 1h, 4h and 1d were commissioned, then 3m as the
#: low end and 6h, 8h, 12h across the middle; 15m bridges the bottom.
#: **The sample falls off a cliff across this range** - 3m holds about fifteen
#: weeks of history where 1h holds five years and 1d holds under three thousand
#: bars - so the architecture that fits is not the same at both ends, and the
#: arms are expected to disagree about which model wins where. At 1d an LSTM has
#: more parameters than it has samples; that is what the ESN arm is for.
GRID = ("3m", "15m", "1h", "4h", "6h", "8h", "12h", "1d")

#: How many bars to ask for. The route caps out around fifty thousand and
#: returns what it has when there is less.
DEPTH = 50_000

#: The HAR triple, in bars. Every volatility feature is built at these three
#: scales so `har.py` in production and this file are measuring one object.
HAR = (1, 5, 22)

#: Shortest usable history. Below this a walk-forward split leaves test folds
#: too small for an AUC to mean anything.
FEWEST = 600


class Thin(RuntimeError):
    """The symbol did not return enough history to study."""


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------


def _slug(symbol: str, interval: str) -> str:
    return f"{symbol.replace(' ', '_').replace('(', '').replace(')', '')}.{interval}"


def fetch(symbol: str, interval: str, count: int = DEPTH, *, tries: int = 4) -> list[dict]:
    """Bars from the terminal, with retry.

    **The route intermittently 404s.** On 2026-09-12 `Volatility 75 Index` at H4
    returned `HTTP 404 Not Found` while the 1s variant at the same timeframe
    returned 13,755 bars one second later. A 404 read as "this timeframe is not
    supported" would silently drop 4h from the study, which is one of the three
    timeframes it was commissioned to cover.
    """
    last = None
    for attempt in range(tries):
        try:
            rows = feed.bars(symbol, interval, count)
            if rows:
                return rows
            last = RuntimeError("empty")
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{symbol} {interval}: {last}")


def cache(symbol: str, interval: str, *, refresh: bool = False) -> dict[str, np.ndarray]:
    """Bars as column arrays, pulled once and kept on disk."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{_slug(symbol, interval)}.npz"
    if path.exists() and not refresh:
        got = np.load(path)
        return {k: got[k] for k in got.files}
    rows = fetch(symbol, interval)
    cols = {
        k: np.asarray([r[k] for r in rows], dtype=float)
        for k in ("time", "open", "high", "low", "close", "volume", "spread")
    }
    np.savez_compressed(path, **cols)
    return cols


def load(symbol: str, interval: str, *, refresh: bool = False) -> dict[str, np.ndarray]:
    got = cache(symbol, interval, refresh=refresh)
    if len(got["close"]) < FEWEST:
        raise Thin(f"{symbol} {interval}: {len(got['close'])} bars < {FEWEST}")
    return got


def align(
    symbols, interval: str, *, refresh: bool = False, min_share: float = 0.0
) -> tuple[np.ndarray, dict[str, dict[str, np.ndarray]], dict[str, str]]:
    """Several symbols on one timestamp index, for anything cross-sectional.

    A cross-sectional test compares feed `i` at bar `t` against feed `j` at the
    same `t`, and "the same `t`" has to be a claim about the clock rather than
    about a shared row number. These feeds do not all carry the same depth -
    `Volatility 250 (1s) Index` was listed later than the rest and
    `Spot Up - Volatility Down Index` 404s on every timeframe in `GRID` - so
    stacking raw columns would shift one feed against its neighbours by however
    many bars it is short, and a constant shift reads as a lead.

    Timestamps are rounded to the second before intersecting. They arrive as
    floats through `datetime.timestamp()` and two feeds that agree to the
    microsecond can still disagree in the last bit of a float, which would empty
    the intersection without raising anything.

    `min_share` drops any feed whose own history is shorter than that fraction of
    the median before intersecting, and **the check has to happen here rather
    than on the returned bars**. Three of these instruments - Volatility 15, 30
    and 90 - were listed about 211 days ago where the rest reach five years, so at
    1h a straight intersection of all twenty-one is 5,066 bars against the 32,668
    the other eighteen hold. A caller that filters on the *output* of this
    function is filtering columns that have already been cut to the intersection,
    so every depth looks identical and the filter silently never fires. That cost
    a tenfold loss of sample on the first run of `seqcross.py` and is the reason
    this parameter exists rather than living in the caller.

    A dropped feed is a real trade: `N` falls, which loosens the
    Marchenko-Pastur bulk, while `T` rises, which tightens it far faster. Both
    universes are worth running and the default of 0.0 keeps every feed, so no
    existing caller changes behaviour.

    Returns `(times, kept, dropped)`. `dropped` carries the reason per symbol,
    because a universe that silently shrinks from 22 feeds to 6 is how a
    cross-sectional page ends up describing a different study than its title.
    """
    kept: dict[str, dict[str, np.ndarray]] = {}
    dropped: dict[str, str] = {}
    for symbol in symbols:
        try:
            kept[symbol] = load(symbol, interval, refresh=refresh)
        except Exception as exc:  # noqa: BLE001 - one absent feed must not end the study
            dropped[symbol] = str(exc)[:90]
    if not kept:
        return np.array([], dtype=np.int64), {}, dropped

    if min_share > 0.0 and len(kept) > 2:
        depths = {s: len(b["close"]) for s, b in kept.items()}
        floor = min_share * float(np.median(list(depths.values())))
        for symbol in [s for s, d in depths.items() if d < floor]:
            dropped[symbol] = (f"short: {depths[symbol]:,} bars < {min_share:g} x median "
                               f"{float(np.median(list(depths.values()))):,.0f}")
            kept.pop(symbol)
        if not kept:
            return np.array([], dtype=np.int64), {}, dropped

    common: np.ndarray | None = None
    for symbol, bars in kept.items():
        stamps = np.rint(bars["time"]).astype(np.int64)
        common = stamps if common is None else np.intersect1d(common, stamps)
    assert common is not None

    out: dict[str, dict[str, np.ndarray]] = {}
    for symbol, bars in kept.items():
        stamps = np.rint(bars["time"]).astype(np.int64)
        order = np.argsort(stamps)
        pos = order[np.searchsorted(stamps[order], common)]
        out[symbol] = {k: v[pos] for k, v in bars.items()}
    return common, out, dropped


# --------------------------------------------------------------------------
# Features - every one of them a function of bars <= t
# --------------------------------------------------------------------------


def _roll_mean(x: np.ndarray, k: int) -> np.ndarray:
    """Causal rolling mean: position `t` uses `x[t-k+1..t]`, NaN until full."""
    out = np.full(len(x), np.nan)
    if k <= 0 or len(x) < k:
        return out
    c = np.concatenate(([0.0], np.nancumsum(np.nan_to_num(x))))
    out[k - 1 :] = (c[k:] - c[:-k]) / k
    return out


def _roll_std(x: np.ndarray, k: int) -> np.ndarray:
    m = _roll_mean(x, k)
    m2 = _roll_mean(x * x, k)
    return np.sqrt(np.maximum(m2 - m * m, 0.0))


NAMES: tuple[str, ...] = (
    "ret",
    "gap",
    "body",
    "upper",
    "lower",
    "logrange",
    "rv1",
    "rv5",
    "rv22",
    "har_5_22",
    "har_1_5",
    "z5",
    "z22",
    "parkinson",
    "garman_klass",
    "vol_of_vol",
    "sign",
    "runlen",
    "sign_ac10",
    "logvolume",
    "volume_z",
    "spread_rel",
    "frac_zero",
    "n_distinct",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
)


def build(bars: dict[str, np.ndarray]) -> tuple[np.ndarray, tuple[str, ...]]:
    """The feature matrix. Row `t` uses bars up to and including `t`, never past it.

    The vocabulary is what this project has already learned rather than a
    textbook list:

    * **The HAR triple** at 1, 5 and 22 bars, because `har.py` is in production
      and `forecasting.md` scores against it - measuring a different object
      would make this page incomparable with that one.
    * **Candle shape** - body and both wicks as fractions of range - because
      `forecasting.md`'s whole argument for a nonlinear model was that a straight
      line over three lagged magnitudes cannot express an interaction between
      magnitude and shape.
    * **`frac_zero` and `n_distinct`**, which are here on their record. Those two
      paid twice: `frac_zero` at AUC 0.686 opened the quote-lattice question and
      `n_distinct` exposed a float-precision artefact and then a real defect in
      the published grind specification. On a quantised feed they are where the
      generator shows through.
    * **`logvolume`** is the tick count, which on a generated feed is the
      **generator's own clock**. `twins.md` found all sixteen synthetics publish
      within 9ms of each other, so if anything about the scheduler leaks, it
      leaks here.
    * **Clock features**, which should be inert on a synthetic and are not on a
      real market. They are a second free discriminator.

    Everything is dimensionless. A raw price into a recurrent net trained on a
    trending series is the classic way this study leaks: the net learns the
    level, the walk-forward split hands it a level it has never seen, and the
    score is a statement about drift.
    """
    o, h, l, c = bars["open"], bars["high"], bars["low"], bars["close"]
    v, sp, ts = bars["volume"], bars["spread"], bars["time"]
    n = len(c)

    with np.errstate(divide="ignore", invalid="ignore"):
        ret = np.concatenate(([np.nan], np.diff(np.log(c))))
        gap = np.log(o / np.concatenate(([np.nan], c[:-1])))
        rng = np.maximum(h - l, 1e-12)
        logrange = np.log(np.maximum(h, 1e-12) / np.maximum(l, 1e-12))
        body = np.abs(c - o) / rng
        upper = (h - np.maximum(o, c)) / rng
        lower = (np.minimum(o, c) - l) / rng

    r0 = np.nan_to_num(ret)
    rv1, rv5, rv22 = (np.sqrt(_roll_mean(r0 * r0, k)) for k in HAR)
    with np.errstate(divide="ignore", invalid="ignore"):
        har_5_22 = np.log(rv5 / rv22)
        har_1_5 = np.log(np.maximum(rv1, 1e-12) / rv5)
        z5, z22 = ret / np.maximum(rv5, 1e-12), ret / np.maximum(rv22, 1e-12)
        # Parkinson and Garman-Klass: range estimators, which use the high and
        # the low that a close-to-close estimator throws away.
        parkinson = np.sqrt(_roll_mean(logrange**2, 22) / (4.0 * math.log(2.0)))
        gk = 0.5 * logrange**2 - (2.0 * math.log(2.0) - 1.0) * np.log(c / o) ** 2
        garman_klass = np.sqrt(np.maximum(_roll_mean(gk, 22), 0.0))
        vol_of_vol = _roll_std(np.log(np.maximum(rv5, 1e-12)), 22)

    sign = np.sign(r0)
    runlen = np.zeros(n)
    for i in range(1, n):
        runlen[i] = runlen[i - 1] + sign[i] if sign[i] == sign[i - 1] else sign[i]
    sign_ac10 = _roll_mean(sign * np.concatenate(([0.0], sign[:-1])), 10)

    with np.errstate(divide="ignore", invalid="ignore"):
        logvolume = np.log(np.maximum(v, 1.0))
        vm, vs = _roll_mean(logvolume, 22), _roll_std(logvolume, 22)
        volume_z = (logvolume - vm) / np.maximum(vs, 1e-9)
        # **`sp` is a count of points, not a price**, and treating it as one was
        # a defect every arm inherited through this matrix. MetaTrader quotes the
        # bar `spread` column in points of `10^-digits` and the route does not
        # carry `digits`, so the raw column is out by 1e3 to 1e5 and **wrong
        # quietly** - still small, still positive, still plausible. `rel_spread`
        # infers the lattice and returns the spread as a fraction of price, which
        # `research/policies.md` validated against the `(1s)` twins: Volatility 25
        # quotes 153 points on a 0.001 grid and its 1s twin 2,898 points on a 0.01
        # grid, and the two land on **0.666 and 0.663 bps** - a factor of 19 in
        # the point count agreeing to half a percent.
        #
        # Within one symbol the old form was monotone and harmless. Across
        # symbols it was meaningless, and arms that pooled symbols pooled it.
        spread_rel = rel_spread(bars) / np.maximum(rng / np.maximum(c, 1e-12), 1e-12)

    frac_zero = _roll_mean((r0 == 0.0).astype(float), 22)
    n_distinct = np.full(n, np.nan)
    for i in range(21, n):
        n_distinct[i] = len(np.unique(c[i - 21 : i + 1])) / 22.0

    stamps = [dt.datetime.fromtimestamp(t, dt.UTC) for t in ts]
    hour = np.array([s.hour + s.minute / 60.0 for s in stamps])
    dow = np.array([s.weekday() for s in stamps], dtype=float)
    cols = {
        "ret": ret,
        "gap": gap,
        "body": body,
        "upper": upper,
        "lower": lower,
        "logrange": logrange,
        "rv1": rv1,
        "rv5": rv5,
        "rv22": rv22,
        "har_5_22": har_5_22,
        "har_1_5": har_1_5,
        "z5": z5,
        "z22": z22,
        "parkinson": parkinson,
        "garman_klass": garman_klass,
        "vol_of_vol": vol_of_vol,
        "sign": sign,
        "runlen": runlen,
        "sign_ac10": sign_ac10,
        "logvolume": logvolume,
        "volume_z": volume_z,
        "spread_rel": spread_rel,
        "frac_zero": frac_zero,
        "n_distinct": n_distinct,
        "hour_sin": np.sin(2 * np.pi * hour / 24.0),
        "hour_cos": np.cos(2 * np.pi * hour / 24.0),
        "dow_sin": np.sin(2 * np.pi * dow / 7.0),
        "dow_cos": np.cos(2 * np.pi * dow / 7.0),
    }
    x = np.column_stack([cols[k] for k in NAMES])
    return np.where(np.isfinite(x), x, np.nan), NAMES


# --------------------------------------------------------------------------
# Targets - every one of them a function of bars > t
# --------------------------------------------------------------------------


def targets(bars: dict[str, np.ndarray], horizon: int = 1) -> dict[str, np.ndarray]:
    """What row `t` is asked to predict about bars `t+1 .. t+horizon`.

    `logvol` is the one that matters. `direction` is the null calibration and
    `absret` is its continuous twin, kept because an AUC on a sign throws away
    the magnitude that decides whether a call is worth acting on.
    """
    c = bars["close"]
    n = len(c)
    fwd = np.full(n, np.nan)
    fwd[: n - horizon] = np.log(c[horizon:] / c[: n - horizon])

    r0 = np.nan_to_num(np.concatenate(([np.nan], np.diff(np.log(c)))))
    rvf = np.full(n, np.nan)
    for t in range(n - horizon):
        seg = r0[t + 1 : t + 1 + horizon]
        rvf[t] = math.sqrt(float(np.mean(seg * seg))) if len(seg) else np.nan

    with np.errstate(divide="ignore", invalid="ignore"):
        logvol = np.log(np.maximum(rvf, 1e-12))
    return {
        "direction": np.where(np.isnan(fwd), np.nan, (fwd > 0).astype(float)),
        "fwd_return": fwd,
        "absret": np.abs(fwd),
        "realised": rvf,
        "logvol": np.where(np.isfinite(logvol), logvol, np.nan),
    }


def usable(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Rows where every feature and the target are finite. The warm-up dies here."""
    return np.isfinite(x).all(axis=1) & np.isfinite(y)


# --------------------------------------------------------------------------
# Splits
# --------------------------------------------------------------------------


def walk_forward(
    n: int, *, folds: int = 5, horizon: int = 1, min_train: int = 250
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window folds with a purge and an embargo, never shuffled.

    **The purge is the part that is usually missing.** A target at row `t` reads
    bars `t+1..t+horizon`, so the last `horizon` rows of any training block
    overlap the first rows of the test block and hand the model part of its own
    answer. Dropping them costs `horizon` rows and buys the split its meaning.

    **No embargo is applied and that is deliberate.** An embargo guards the
    reverse direction - training rows drawn from *after* a test block, whose
    rolling windows reach back into it. These folds only ever train on rows
    before the test block, so that direction does not exist here. Carrying an
    unused embargo would be a comment claiming a protection the code does not
    perform, which is worse than not having it.

    `min_train` is raised to a share of the series rather than taken literally:
    a first fold that trains on 249 rows and is tested on 9,945 reports mostly
    the weakness of its own warm-up, and it drags the pooled score with it.
    """
    if n < min_train + folds:
        return []
    floor = max(min_train, n // (folds + 1))
    edges = np.linspace(floor, n, folds + 1).astype(int)
    out = []
    for i in range(folds):
        lo, hi = edges[i], edges[i + 1]
        tr_end = lo - horizon
        if tr_end < floor // 2 or hi - lo < 30:
            continue
        out.append((np.arange(0, tr_end), np.arange(lo, hi)))
    return out


# --------------------------------------------------------------------------
# Controls
# --------------------------------------------------------------------------


def shuffle_target(y: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    out = y.copy()
    ok = np.isfinite(out)
    vals = out[ok]
    rng.shuffle(vals)
    out[ok] = vals
    return out


def phase_surrogate(series: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A series with the same power spectrum and no nonlinear structure.

    The amplitude of every Fourier component is kept and the phase is replaced
    with a uniform draw, conjugate-symmetric so the inverse transform is real.
    Linear autocorrelation survives exactly; anything a nonlinear model could
    have found does not. A net that scores the same on this as on the truth
    learned the spectrum, which a straight line already had.
    """
    x = np.asarray(series, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    spec = np.fft.rfft(x)
    phases = rng.uniform(0, 2 * np.pi, len(spec))
    phases[0] = 0.0
    if n % 2 == 0:
        phases[-1] = 0.0
    return np.fft.irfft(np.abs(spec) * np.exp(1j * phases), n=n)


def circular_shift(x: np.ndarray, rng: np.random.Generator, *, at: int | None = None) -> np.ndarray:
    """The same series, rotated. The right control for a *shared clock*.

    A plain permutation is the wrong null for a cross-sectional test. It
    destroys the feed's own serial dependence as well as its alignment with its
    neighbours, so a pooled model that scores above a shuffled control has only
    been shown to beat a series with no autocorrelation - which every one of
    these feeds already has none of. A rotation keeps each feed's own law and
    its own memory **exactly** and moves only where it sits against the others,
    which is the single thing a shared generator would put there.
    """
    x = np.asarray(x)
    n = len(x)
    if n < 2:
        return x.copy()
    k = int(rng.integers(1, n)) if at is None else int(at) % n
    return np.roll(x, k)


def moving_block(n: int, rng: np.random.Generator, *, block: int | None = None) -> np.ndarray:
    """Indices of a moving-block bootstrap resample, for a standard error on a serial statistic.

    `nstar` takes a standard error and its default of 0.01 is a placeholder, not
    a measurement. Every discriminator on this grid is computed on overlapping
    windows of an autocorrelated series, where the iid formula understates the
    error - sometimes by a factor of three - and an `n*` built on an understated
    error is an under-estimate of how much data the question needs, which is the
    direction that gets a null called prematurely.

    Block length defaults to `n**(1/3)`, the usual rate for a stationary series.
    """
    if n <= 1:
        return np.zeros(max(n, 0), dtype=int)
    b = int(block or max(2, round(n ** (1.0 / 3.0))))
    b = min(b, n)
    starts = rng.integers(0, n - b + 1, size=int(np.ceil(n / b)))
    idx = np.concatenate([np.arange(s, s + b) for s in starts])
    return idx[:n]


def mp_edges(n_series: int, n_obs: int) -> tuple[float, float]:
    """Marchenko-Pastur bulk edges for a correlation matrix of independent series.

    This is the **exact null** for the question "is there a shared factor across
    these feeds": the eigenvalues of a sample correlation matrix built from `N`
    independent series of length `T` fall inside `(1 +- sqrt(N/T))^2` as both
    grow, and anything outside the bulk is a factor rather than sampling noise.
    It is a far sharper instrument than a maximum over 231 pairwise
    correlations, because a weak factor spread across all 22 feeds moves the top
    eigenvalue long before it makes any single pair look unusual.

    The law assumes iid entries with a finite fourth moment. Volatility-index
    returns are Gaussian by construction so it is close to exact on them;
    `|return|` is half-normal and `log volume` is neither, so on those the
    analytic edge is a reference and a rotation null is the test.
    """
    if n_obs <= 0:
        return (float("nan"), float("nan"))
    q = float(n_series) / float(n_obs)
    return ((1.0 - math.sqrt(q)) ** 2, (1.0 + math.sqrt(q)) ** 2)


def gbm_bars(
    sigma: float, n: int, interval: str, rng: np.random.Generator, *, start: float = 1000.0
) -> dict[str, np.ndarray]:
    """A simulated Volatility index at a known sigma - the exact null.

    Built as a sub-path so the high and the low are real extremes rather than
    `max(open, close)`: candle shape is a feature here, and a two-point bar has
    shape by construction that a traded bar does not.

    **The open belongs to the bar, and leaving it out of the extrema was a free
    discriminator.** The first version took the high as the maximum of the 24
    sub-points alone, but the open is the previous bar's close and the move from
    it to the first sub-point is part of *this* bar's path. Without it,
    **11.28% of simulated bars had a high below `max(open, close)`** and 11.43%
    a low above `min(open, close)` - which is impossible on a traded bar, and
    which `build` turns into a negative `upper` (down to -0.910), a negative
    `lower` (down to -1.178) and a `body` of up to 2.12, where the feed's are all
    in [0, 1] by construction.

    That is not cosmetic. `gbm` is the null every arm of this study scores
    against, and a classifier asked "feed or simulation" could have had the
    answer from **the sign of one feature, on one bar in nine, for free**. Every
    model reading candle shape was reading a differently-supported variable on
    the control than on the feed. Found by `seqnets.py` while validating
    `surrogate_bars`, which had inherited the same construction and the same
    defect.
    """
    per = PER_YEAR[interval]
    step = sigma / math.sqrt(per)
    sub = 24
    inc = rng.normal(0.0, step / math.sqrt(sub), (n, sub))
    path = start * np.exp(np.cumsum(inc.reshape(-1)))
    grid = path.reshape(n, sub)
    o = np.concatenate(([start], grid[:-1, -1]))
    return {
        "time": np.arange(n, dtype=float) * (365 * 86400.0 / per),
        "open": o,
        "high": np.maximum(grid.max(axis=1), o),
        "low": np.minimum(grid.min(axis=1), o),
        "close": grid[:, -1],
        "volume": rng.poisson(1800, n).astype(float),
        "spread": np.full(n, 2.0),
    }


def measured_sigma(bars: dict[str, np.ndarray], interval: str) -> float:
    """Annualised volatility from the bars themselves.

    `NAMED_SIGMA` covers the twenty constant-sigma members and nothing else, so
    `SPOT_UP` - the two whose name says the variance moves - and every symbol in
    `REAL` have no published parameter to build a simulated null at. Measuring it
    here rather than once per arm is the point: six arms building their `gbm`
    control at six slightly different fitted sigmas would make their nulls
    incomparable, and the null is the only thing that makes any of their
    positives readable.

    This is a close-to-close estimator on purpose. It is the same object
    `grounding.md` tier 1 verified the names against to within 0.49%, so on a
    named member `measured_sigma` and `NAMED_SIGMA` are checkable against each
    other, and on an unnamed one the estimator has a known accuracy.
    """
    c = np.asarray(bars["close"], dtype=float)
    r = np.diff(np.log(np.maximum(c, 1e-12)))
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return float("nan")
    return float(np.std(r) * math.sqrt(PER_YEAR[interval]))


def surrogate_bars(
    bars: dict[str, np.ndarray], rng: np.random.Generator, *, sub: int = 24
) -> dict[str, np.ndarray]:
    """Phase-randomised bars: the same return spectrum, no nonlinear structure.

    `phase_surrogate` returns a series and a sequence model is fed bars, and the
    conversion between the two is exactly where a surrogate control leaks.
    The tempting construction - keep the real bars, swap only the closes - hands
    the model back `high`, `low`, `parkinson` and `garman_klass`, which are the
    volatility signal the control exists to destroy. A surrogate that leaves the
    candle geometry in place is not a control, it is the real series with a
    cosmetic change to one column.

    So the path is rebuilt the way `gbm_bars` builds one. Each bar's surrogate
    return is split into `sub` pieces that sum to it exactly - a discrete
    Brownian bridge - so the high and the low are real extrema of a real
    sub-path rather than `max(open, close)`. **The intra-bar wiggle is scaled by
    the series' unconditional standard deviation, never by a local one**: a
    locally scaled bridge would put the volatility clustering back inside the
    bar and quietly restore the thing being removed.

    Volume and spread are permuted rather than simulated. That keeps their
    marginals exactly, destroys their order and their coupling to returns, and
    leaves `logvolume`, `volume_z` and `spread_rel` with the right distribution
    and no information - which is what a null for those columns has to be.
    Timestamps are kept, so the clock features are real and the control is
    strictly harder than one that randomises them too.

    What survives: the linear autocorrelation of returns, exactly. What does
    not: volatility clustering, return-volume coupling, the quote lattice, and
    every nonlinear dependence a recurrent net could be finding. A model that
    scores the same here as on the truth learned the spectrum, and a straight
    line already had the spectrum.
    """
    c = np.asarray(bars["close"], dtype=float)
    r = np.diff(np.log(np.maximum(c, 1e-12)))
    r = r[np.isfinite(r)]
    rs = phase_surrogate(r, rng)
    n = len(rs)
    if n < 2:
        raise Thin(f"surrogate: {n} returns")

    z = rng.normal(0.0, 1.0, (n, sub))
    z -= z.mean(axis=1, keepdims=True)
    inc = z * (float(np.std(r)) / math.sqrt(sub)) + (rs / sub)[:, None]
    start = float(c[0])
    path = start * np.exp(np.cumsum(inc.reshape(-1)))
    grid = path.reshape(n, sub)
    o = np.concatenate(([start], grid[:-1, -1]))

    v = np.asarray(bars["volume"], dtype=float)[-n:].copy()
    sp = np.asarray(bars["spread"], dtype=float)[-n:].copy()
    rng.shuffle(v)
    rng.shuffle(sp)
    return {
        "time": np.asarray(bars["time"], dtype=float)[-n:],
        "open": o,
        # Same correction as `gbm_bars`: the open is part of this bar's path.
        "high": np.maximum(grid.max(axis=1), o),
        "low": np.minimum(grid.min(axis=1), o),
        "close": grid[:, -1],
        "volume": v,
        "spread": sp,
    }


# --------------------------------------------------------------------------
# The shared linear floor
# --------------------------------------------------------------------------


def ridge(
    x_train: np.ndarray, y_train: np.ndarray, x_test: np.ndarray, *, lam: float = 1.0
) -> np.ndarray:
    """Ridge fit on train, predicted on test. The floor every arm has to clear.

    It lives here rather than in one arm because `research/models.md` found a
    straight line beating trees, forests, cosine similarity and an MLP on this
    project's other classification problem, and six arms each writing their own
    linear baseline would mean six different regularisations and six different
    standardisations - which is exactly the mixing that cost `forecasting.md`
    two headline claims.

    **Standardised on the training block only.** Scaling by the full sample's
    mean and standard deviation is the quiet leak in this class of study: it is
    not a look-ahead in the target, so `check_causality` does not see it, and it
    is worth a few basis points of fake skill on every fold.
    """
    xtr = np.asarray(x_train, float)
    xte = np.asarray(x_test, float)
    mu, sd = xtr.mean(axis=0), xtr.std(axis=0)
    sd = np.where(sd > 1e-12, sd, 1.0)
    a = np.column_stack([(xtr - mu) / sd, np.ones(len(xtr))])
    b = np.column_stack([(xte - mu) / sd, np.ones(len(xte))])
    pen = lam * np.eye(a.shape[1])
    pen[-1, -1] = 0.0  # never shrink the intercept toward zero
    beta = np.linalg.solve(a.T @ a + pen, a.T @ np.asarray(y_train, float))
    return b @ beta


def tick_size(bars: dict[str, np.ndarray]) -> float:
    """The quote grid, inferred from the closes, because the feed never sends it.

    **The `spread` column is an integer count of points, not a price.**
    `feed.bars` copies MetaTrader's `spread` field straight through and
    MetaTrader quotes it in points, where a point is `10^-digits`. A harness
    that treats it as a price is wrong by a factor of one thousand to one
    hundred thousand, and it is wrong *silently* - the number is still small and
    still positive, so a cost model built on it looks plausible and charges
    nothing. This is the single most likely way a cost-aware arm on this study
    reports an edge that is not there.

    `digits` is not on the route, so it is recovered from the data: the coarsest
    decimal grid that every close in the series lies on. With fifty thousand
    bars every digit is exercised, so the coarsest grid containing the data is
    the grid.

    **It is validated against a published measurement rather than trusted.**
    `research/deriving.md` measured the Volatility family's spread at 0.39-4.31
    bps from tick bid/ask, which is an independent route that never touches this
    column. Converted through this function the bar column gives 0.27-3.12 bps
    across the same family - the same order, the same ordering by symbol. The
    sharpest check is internal: `Volatility 10 Index` quotes on a 0.001 grid at
    162 points and `Volatility 10 (1s) Index` quotes on a 0.01 grid at 27
    points, two different digits and two different point counts, and they land
    on 0.282 and 0.284 bps. Two wrong tick sizes do not agree to three figures.
    """
    c = np.asarray(bars["close"], dtype=float)
    c = c[np.isfinite(c) & (c > 0)]
    if not len(c):
        return float("nan")
    for d in range(0, 9):
        scaled = c * (10.0**d)
        if np.max(np.abs(scaled - np.round(scaled))) < 1e-4:
            return 10.0 ** (-d)
    return float("nan")


def rel_spread(bars: dict[str, np.ndarray]) -> np.ndarray:
    """`c_t`: the full quoted spread at bar `t` as a fraction of price.

    This is the `c` in `research/deriving.md`'s `E[net] = -(c/2) x turnover`.
    The half appears there because crossing once - flat to long, or long to
    flat - pays half of it; a round trip pays the whole thing and carries two
    units of turnover. Returned as the *full* spread so the theorem's arithmetic
    can be written in the same letters it is proved in.
    """
    tick = tick_size(bars)
    c = np.asarray(bars["close"], dtype=float)
    sp = np.asarray(bars["spread"], dtype=float)
    return sp * tick / np.maximum(c, 1e-12)


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def auc(score: np.ndarray, label: np.ndarray) -> float:
    """Rank AUC. Same arithmetic as `groundgru.auc`, kept local so this file stands alone."""
    score, label = np.asarray(score, float), np.asarray(label)
    order = np.argsort(score)
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    n1, n0 = float((label == 1).sum()), float((label == 0).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    return float((ranks[label == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def srel(pred: np.ndarray, truth: np.ndarray) -> float:
    """Symmetric relative error - the score `consensus_vol.Score` uses.

    Deliberately not RMSE. `forecasting.md` scored naive, HAR and a learned
    model on this and its table is the comparison this study has to join.
    """
    p, t = np.asarray(pred, float), np.asarray(truth, float)
    ok = np.isfinite(p) & np.isfinite(t)
    if not ok.any():
        return float("nan")
    p, t = p[ok], t[ok]
    return float(np.mean(np.abs(p - t) / np.maximum((np.abs(p) + np.abs(t)) / 2.0, 1e-12)))


def nstar(a: float, floor: float, n: int, se: float = 0.01) -> float:
    gap = abs(a - floor)
    return float("inf") if gap <= 1e-9 else float(n * (1.96 * 2 * se / gap) ** 2)


def max_of_k(observed: float, null_draws: np.ndarray) -> float:
    """Family-wise p-value: how often the best of K nulls beats this.

    With 22 symbols x 3 timeframes x 5 models there are 330 chances to find
    0.53, and the best of 330 fair coins clears 0.53 routinely. Reporting a
    per-test p-value on this grid is how a folder fills with findings that do
    not replicate.
    """
    draws = np.asarray(null_draws, float)
    draws = draws[np.isfinite(draws)]
    if not len(draws):
        return float("nan")
    return float((draws >= observed).mean())


# --------------------------------------------------------------------------
# The causality assertion
# --------------------------------------------------------------------------


def check_causality(bars: dict[str, np.ndarray], *, at: int = -50) -> dict:
    """Perturb a future bar; assert no feature at an earlier row moves.

    This is the single check that decides whether anything else on the page is
    worth reading, so it runs in `main()` and its result is printed before any
    score. A silent look-ahead is the one bug that makes every arm succeed.
    """
    base, _ = build(bars)
    poked = {k: v.copy() for k, v in bars.items()}
    idx = len(poked["close"]) + at if at < 0 else at
    for k in ("open", "high", "low", "close"):
        poked[k][idx] *= 1.05
    poked["volume"][idx] *= 3.0
    after, _ = build(poked)

    rows = slice(0, idx)
    a, b = base[rows], after[rows]
    both = np.isfinite(a) & np.isfinite(b)
    moved = np.abs(np.where(both, a - b, 0.0)).max(axis=0)
    guilty = [NAMES[i] for i in range(len(NAMES)) if moved[i] > 1e-12]
    return {"poked_row": idx, "rows_checked": idx, "leaking": guilty, "clean": not guilty}


# --------------------------------------------------------------------------
# The rest of the book: tick history, spike detection, hazard tests and the
# family-appropriate nulls.
#
# Added by the families arm (`seqfamilies.py`). Everything above this line is
# shared by six arms and is left untouched; everything below is used by one arm
# and is here rather than in its own file for the reason the module docstring
# gives - a second data layer is how two harnesses end up measuring two
# different objects and calling them the same name.
#
# **`gbm_bars` is the wrong null for every symbol below.** A Volatility index is
# GBM; Boom is a compound Poisson, Step is a lattice walk, Drift Switch is a
# Markov-modulated drift. Simulating GBM and finding that Boom does not look
# like it is a measurement of the simulator. The three generators here are the
# right nulls, and each is built from the feed's own pooled marginals rather
# than from a published parameter - `research/rebuilding.md`'s `spec` arm was
# caught on 24 of 24 discriminators and its `pool` arm on 0 of 24, so a null
# built from the published table is a hypothesis already falsified three ways.
# --------------------------------------------------------------------------


#: Symbol -> family, the reverse of `SYNTHETIC`. Built once so a pooled table
#: cannot silently put a Boom row under `step`.
FAMILY_OF: dict[str, str] = {s: fam for fam, syms in SYNTHETIC.items() for s in syms}

#: Where tick history lives. Separate from the bar cache because it is an order
#: of magnitude larger and a different arm may want to drop one and not the other.
TICK_CACHE = CACHE / "ticks"

#: A spike is a tick whose move is this many times the median absolute move.
#: **Not a new detector.** This is exactly `genspike.THRESHOLDS`, and it is
#: reused rather than re-chosen so this page's rates can be set beside
#: `research/generators.md`'s without a conversion. The headline is 10x; 5x and
#: 20x are reported so a rate that depends on the threshold shows up as the
#: detector artefact it would be.
SPIKE_MULTS = (5.0, 10.0, 20.0)


def tick_window(symbol: str, hours_back: float, count: int) -> list[dict[str, float]]:
    """One tick pull, with the module timeout raised for the size of it.

    `feed.TIMEOUT` is 120s, which is right for a bar pull and wrong here: the
    measured rate is about 2,200 ticks a second, so 200,000 ticks is 90s and
    400,000 is past the default. A timeout reads as an empty feed rather than
    as a slow one, which is the failure mode `feed.ticks` was already written
    around once.
    """
    was = feed.TIMEOUT
    feed.TIMEOUT = max(was, 600.0)
    try:
        return feed.ticks(symbol, count, hours_back=hours_back)
    finally:
        feed.TIMEOUT = was


def tick_cache(symbol: str, want: int = 250_000, *, refresh: bool = False,
               rate: float = 1.0) -> dict[str, np.ndarray]:
    """`want` ticks for `symbol`, pulled in backward chunks and kept on disk.

    **Why chunks.** The route answers `date_from` plus a count, so one call
    returns the *first* `count` ticks after that stamp. Asking for 400,000 with
    a 48-hour lookback returns 48 hours, which is 170,000, and the caller sees a
    short array with no error. Sizing the lookback from the observed tick rate
    and then walking backwards until the target is met is the only way to ask
    for a sample size rather than for a time span.

    **Why a sample size and not a time span.** The object being measured is the
    spike gap, and its sample size is the spike count, not the hour count. Boom
    1000 spikes once per thousand ticks: 24 hours of it is 94 spikes, which is
    what `research/generators.md` had, and a coefficient of variation on 94 has
    a standard error of 0.073 - wide enough that the whole measured range of
    0.844 to 1.103 sits inside two of them. Fixing the tick count fixes the
    spike count, and fixing the spike count is what makes the exponentiality
    test say anything.

    `rate` is ticks per second - 1.0 for the standard feeds, 2.0 for the `(1s)`
    variants - and only sets how far back the first chunk reaches.
    """
    TICK_CACHE.mkdir(parents=True, exist_ok=True)
    path = TICK_CACHE / f"{_slug(symbol, 'tick')}.npz"
    if path.exists() and not refresh:
        got = np.load(path)
        if len(got["time"]) >= int(0.85 * want):
            return {k: got[k] for k in got.files}

    span = want / max(rate, 1e-9) / 3600.0 * 1.35 + 1.0
    rows: list[dict[str, float]] = []
    seen: set[float] = set()
    back = span
    for _ in range(8):
        try:
            chunk = tick_window(symbol, back, min(want, 250_000))
        except Exception:  # noqa: BLE001 - a dropped chunk is not a dropped symbol
            chunk = []
        fresh = [r for r in chunk if r["time"] not in seen]
        for r in fresh:
            seen.add(r["time"])
        rows.extend(fresh)
        if len(rows) >= want or not fresh:
            break
        # Walk forward from the end of what was just pulled.
        newest = max(r["time"] for r in chunk)
        back = max(0.05, (time.time() - newest) / 3600.0)
    rows.sort(key=lambda r: r["time"])
    rows = rows[-want:] if len(rows) > want else rows
    cols = {k: np.asarray([r[k] for r in rows], dtype=float)
            for k in ("time", "bid", "ask", "mid")}
    if len(rows):
        np.savez_compressed(path, **cols)
    return cols


def spikes(moves: np.ndarray, mult: float = 10.0) -> dict:
    """Which ticks are spikes, on `genspike.py`'s detector and no other.

    `spike = |move| > mult * median(|move|)`. The grind is everything else.
    Returned together because every closure test needs both halves and
    recomputing the complement is how two tables end up with different
    denominators.
    """
    m = np.asarray(moves, float)
    m = m[np.isfinite(m)]
    med = float(np.median(np.abs(m))) if len(m) else float("nan")
    cut = mult * med
    hit = np.abs(m) > cut
    return {"mult": mult, "median_abs": med, "cut": cut, "is_spike": hit,
            "idx": np.flatnonzero(hit), "n_spikes": int(hit.sum()),
            "n_moves": len(m), "spike": m[hit], "grind": m[~hit],
            "per_spike": float(len(m) / hit.sum()) if hit.sum() else float("inf")}


def _geom_cdf(k: np.ndarray, p: float) -> np.ndarray:
    """P(G <= k) for a geometric on {1, 2, ...}. The gap between two ticks is at
    least one tick, so the support starts at 1 and a continuous exponential is
    the wrong reference by exactly that offset."""
    return 1.0 - np.power(1.0 - p, np.maximum(np.asarray(k, float), 0.0))


def hazard(gaps: np.ndarray, *, bins: int = 6) -> dict:
    """Is the waiting time memoryless? Five tests, not one.

    `research/generators.md` tested this with a coefficient of variation alone,
    on 86 to 306 spikes a feed, and concluded the family is memoryless at
    "CV 0.84 to 1.10 against 1.00". **A CV is one moment and it is the moment a
    Poisson process shares with a great many non-Poisson ones.** A gamma renewal
    at shape 1.2 has CV 0.91; a process with a hard refractory period and an
    otherwise flat hazard has a CV below 1 that no amount of sample separates
    from a short one. So:

    * **`cv`** - the existing statistic, kept so the two pages compare.
    * **`ks`** - Kolmogorov-Smirnov against a geometric fitted by its mean. The
      p-value is *not* taken from the table: the parameter is fitted, so the
      table is wrong in the anticonservative direction, and the caller is
      expected to get the null band from `compound_poisson_ticks` instead.
    * **`fano`** - variance over mean of the spike count in fixed windows. A
      Poisson process has exactly 1. This is the one test that sees *clustering*,
      which is invisible to a CV computed over pooled gaps.
    * **`acf1`** - lag-one correlation of consecutive gaps. Any renewal process,
      memoryless or not, has zero here; a non-zero value says the gaps are not
      even independent, which is a stronger statement than non-exponential.
    * **`hz`** - the empirical hazard by elapsed-tick bin, `P(fire at k | alive
      at k)`. Flat is memoryless. This is the shape a model would have to learn
      and the only one of the five that says *where* in the wait the structure
      is, so `hz_ratio` (last bin over first) is the headline.

    `min_gap` is reported beside them because a generator that forbids two
    spikes inside N ticks is non-memoryless in the single most exploitable way,
    and it shows up in the minimum before it shows up in any moment.
    """
    g = np.asarray(gaps, float)
    g = g[np.isfinite(g) & (g > 0)]
    n = len(g)
    out = {"n_gaps": n, "mean": float("nan"), "cv": float("nan"),
           "ks": float("nan"), "fano": float("nan"), "acf1": float("nan"),
           "hz_ratio": float("nan"), "hz_slope": float("nan"),
           "min_gap": float("nan"), "hz": [], "hz_edges": []}
    if n < 8:
        return out
    mu, sd = float(g.mean()), float(g.std(ddof=1))
    out["mean"], out["cv"], out["min_gap"] = mu, sd / max(mu, 1e-12), float(g.min())

    p = 1.0 / mu
    srt = np.sort(g)
    emp_hi = np.arange(1, n + 1) / n
    emp_lo = np.arange(0, n) / n
    theo = _geom_cdf(srt, p)
    out["ks"] = float(max(np.max(np.abs(emp_hi - theo)), np.max(np.abs(emp_lo - theo))))

    # Fano on windows of about ten mean gaps, so a window holds ~10 events.
    width = max(int(round(10 * mu)), 2)
    total = float(g.sum())
    nwin = int(total // width)
    if nwin >= 8:
        edges = np.arange(nwin + 1) * width
        counts = np.histogram(np.cumsum(g), bins=edges)[0].astype(float)
        out["fano"] = float(counts.var(ddof=1) / max(counts.mean(), 1e-12))

    if n >= 12:
        a, b = g[:-1] - mu, g[1:] - mu
        denom = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
        out["acf1"] = float((a * b).sum() / denom) if denom > 0 else float("nan")

    # Empirical hazard, in **equal-width** bins of elapsed ticks out to three
    # mean waits - which is 95% of the mass of an exponential - and with the
    # exact per-tick rate rather than the fraction that failed.
    #
    # **Both of those are corrections, and the first version of this had both
    # wrong.** Quantile bins put the top decile in a bin hundreds of ticks wide;
    # over such a bin essentially every survivor fails, so `failed / at_risk`
    # is 1 and dividing by the width gives `1/width`, which is small for a
    # reason that has nothing to do with the hazard. On a *simulated memoryless*
    # process the ratio of last bin to first came back at 0.148, and reading
    # that as decaying hazard would have been this page's headline.
    #
    # `rate = -log(1 - failed/at_risk) / width` is the per-tick rate a bin of
    # that width implies, and it returns `p` exactly in every bin of a geometric
    # of any width. Equal widths then make the bins comparable to each other
    # rather than only to their own null. Flat is memoryless; `hz_ratio` is the
    # last bin over the first and the null is 1.00.
    top = max(3.0 * mu, 3.0)
    qs = np.unique(np.round(np.linspace(1.0, top, bins + 1)))
    hz: list[float] = []
    for i in range(len(qs) - 1):
        lo, hi = qs[i], qs[i + 1]
        at_risk = float((g >= lo).sum())       # survived to the start of the bin
        failed = float(((g >= lo) & (g < hi)).sum())
        frac = failed / max(at_risk, 1.0)
        width_i = max(hi - lo, 1.0)
        hz.append(-math.log(max(1.0 - frac, 1e-12)) / width_i if at_risk >= 20
                  else float("nan"))
    out["hz"], out["hz_edges"] = [float(v) for v in hz], [float(v) for v in qs]
    good = [v for v in hz if np.isfinite(v) and v > 0]
    if len(good) >= 2:
        out["hz_ratio"] = float(good[-1] / good[0])
        # A single slope over the whole curve, which uses every bin rather than
        # only the two ends: the sign is the direction of the trend and the
        # magnitude is per mean-wait.
        xs = np.array([(qs[i] + qs[i + 1]) / 2.0 for i, v in enumerate(hz)
                       if np.isfinite(v) and v > 0], float)
        ys = np.log(np.array(good, float))
        if len(xs) >= 3 and xs.std() > 0:
            out["hz_slope"] = float(np.polyfit(xs / max(mu, 1e-9), ys, 1)[0])
    return out


def compound_poisson_ticks(grind: np.ndarray, jump: np.ndarray, p: float,
                           n: int, rng: np.random.Generator,
                           *, start: float = 1000.0) -> np.ndarray:
    """A memoryless spike process with the feed's own marginals. The right null.

    A spike fires with constant probability `p` every tick, independent of
    everything - which is precisely the hypothesis `hazard` is testing - and its
    size is drawn from the feed's own observed spike pool. The grind is drawn
    from the feed's own observed grind pool. **Every marginal matches the feed
    exactly by construction**, so any statistic that separates this from the
    feed separates it on timing alone.

    That is deliberately not the published compound Poisson.
    `research/rebuilding.md` caught a spec-built Boom on 24 of 24 discriminators
    at 724 to 3,506 ticks; simulating from the table would give a null that the
    hazard tests reject for reasons that have nothing to do with the hazard.
    """
    hit = rng.random(n) < p
    out = np.empty(n)
    ng, nj = int((~hit).sum()), int(hit.sum())
    out[~hit] = rng.choice(grind, ng, replace=True) if len(grind) else 0.0
    out[hit] = rng.choice(jump, nj, replace=True) if len(jump) else 0.0
    return start + np.cumsum(out)


def step_ticks(up: float, down: float, p_up: float, n: int,
               rng: np.random.Generator, *, start: float = 1000.0) -> np.ndarray:
    """A lattice walk with the measured up size, down size and up probability.

    The Step family's null is not a Brownian motion and not a fair coin either -
    the Skew Step variants are named asymmetric, so the null that matters is
    "asymmetric exactly as measured, and independent". A model that beats this
    found order; a model that only beats a fair coin found the skew, which is a
    marginal and not a sequence.
    """
    s = np.where(rng.random(n) < p_up, up, -abs(down))
    return start + np.cumsum(s)


def switch_bars(mu: np.ndarray, sigma: np.ndarray, trans: np.ndarray, n: int,
                rng: np.random.Generator, *, start: float = 1000.0) -> dict:
    """A Markov-modulated drift - the null for Drift Switch, and its positive control.

    Returned with the true state path, which is the whole point: on this
    generator the hidden regime is known, so a filter can be scored against the
    truth rather than against its own likelihood. A hidden-state model fitted to
    a series always reports states; whether those states are *the* states is a
    question only a generator can answer, and this is the generator.
    """
    k = len(mu)
    state = np.empty(n, dtype=int)
    state[0] = rng.integers(k)
    u = rng.random(n)
    for t in range(1, n):
        state[t] = int(np.searchsorted(np.cumsum(trans[state[t - 1]]), u[t]))
    r = mu[state] + sigma[state] * rng.standard_normal(n)
    return {"ret": r, "state": state, "close": start * np.exp(np.cumsum(r))}


def bars_from_ticks(t: np.ndarray, price: np.ndarray, per: int) -> dict[str, np.ndarray]:
    """OHLC bars of exactly `per` ticks each - a tick clock, not a wall clock.

    **The wall clock is the wrong clock for Boom, Crash, DEX and Jump**, and it
    is worth saying why rather than reporting a number from the wrong one. The
    event these families are made of is a spike, and its rate is quoted per
    *tick*: Boom 500 spikes once in five hundred ticks, Boom 50 once in fifty.
    A three-minute bar is about 180 ticks, so the same bar holds 0.36 spikes on
    Boom 500 and 3.6 on Boom 50, and a one-day bar holds 173 and 1,728. At that
    point "did a spike happen in the next bar" is not a question - the answer is
    yes, always, and the classifier is scoring a constant.

    A tick bar sized to the nominal rate makes one question well posed on every
    member of the family at once, which a wall clock cannot do for a family
    whose members differ by a factor of twenty in event rate.
    """
    n = len(price) // max(per, 1)
    if n < 2:
        return {k: np.zeros(0) for k in
                ("time", "open", "high", "low", "close", "volume", "spread")}
    grid = price[: n * per].reshape(n, per)
    stamp = t[: n * per].reshape(n, per)
    return {
        "time": stamp[:, -1],
        "open": grid[:, 0], "high": grid.max(axis=1), "low": grid.min(axis=1),
        "close": grid[:, -1],
        "volume": np.full(n, float(per)),
        "spread": np.zeros(n),
    }


def main() -> None:
    rng = np.random.default_rng(7)
    print("seqlab - the floor under the sequence arms\n")

    sym, tf = "Volatility 75 Index", "1h"
    bars = load(sym, tf)
    print(f"{sym} {tf}: {len(bars['close']):,} bars")

    verdict = check_causality(bars)
    print(
        f"causality: {'CLEAN' if verdict['clean'] else 'LEAKING ' + str(verdict['leaking'])}"
        f"  ({verdict['rows_checked']:,} rows checked)"
    )

    x, names = build(bars)
    y = targets(bars, horizon=1)
    ok = usable(x, y["logvol"])
    print(f"features: {x.shape[1]}  usable rows: {ok.sum():,} of {len(x):,}")

    folds = walk_forward(int(ok.sum()), folds=5, horizon=1)
    print(f"folds: {len(folds)}  " + ", ".join(f"{len(tr)}/{len(te)}" for tr, te in folds))

    # The real-vs-synthetic discriminator, on one symbol, before any model.
    # **Not** a test of whether sigma is constant - see the docstring's
    # withdrawal. At h=1 an oracle that knew sigma_t exactly scores ~0.88.
    rv = y["realised"][ok]
    prev = x[ok][:, names.index("rv1")]
    print(
        f"\nvol: naive srel {srel(prev, rv):.4f}   mean srel {srel(np.full(len(rv), rv.mean()), rv):.4f}"
    )

    sim = gbm_bars(NAMED_SIGMA[sym], 20_000, tf, rng)
    xs, _ = build(sim)
    ys = targets(sim, horizon=1)
    oks = usable(xs, ys["logvol"])
    rvs, prevs = ys["realised"][oks], xs[oks][:, names.index("rv1")]
    print(
        f"gbm: naive srel {srel(prevs, rvs):.4f}   mean srel {srel(np.full(len(rvs), rvs.mean()), rvs):.4f}"
    )
    print(json.dumps({"cache": str(CACHE), "features": len(names)}, indent=None))


if __name__ == "__main__":
    main()
