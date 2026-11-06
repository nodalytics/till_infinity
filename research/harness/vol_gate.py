"""Does gating a direction rule on predicted high volatility produce a book that pays?

    ./.secrets/lab.sh sync
    ./.secrets/lab.sh exec 'cd $HOME/till_infinity && nohup env OMP_NUM_THREADS=4 \
        SEQLAB=$HOME/till_infinity/data/seqlab OUT=$HOME/till_infinity/out \
        $SKPY -u repo/research/harness/vol_gate.py \
        > logs/vol_gate.log 2>&1 &'

`$SKPY` is any interpreter on the lab that has scikit-learn: the one
`lab.sh run` uses does not, which is why this launches through `exec`. `lab.sh run` also syncs the repo first and would
overwrite a file pushed by hand, so the sync happens before, explicitly.

## What is already answered, and is therefore not the question

**Volatility is forecastable here.** `fractal-twins.md` reads expansion from
compression at AUC 0.728-0.738; `impulse-vol.md` adds +0.167 to +0.355 of a
forecast unit on 8 of 8 traded markets; `crash-timing.md` reads a large bar at
AUC 0.748 intraday. `vol-particle.md` measures the shipped EWMA as 18-29%
over-confident at 1h and `surprise-rate.md` puts the standardised innovation's
sd at 0.67-0.76. Stage A rebuilds a forecast and reports its calibration
because a gate cannot be judged without knowing what it gates on - **not**
because the question is open. Beating the EWMA is the bar, not the finding.

**Direction is closed**, five ways: `trigger-expectancy.md`,
`chart-patterns.md`, `bos-predict.md`, `fractal-twins.md` and `findings.md`'s
planted-drift gate. The direction rules here are carried as arms **expected to
be null**, with a coin on the same entry bars as their surrogate.

**The sizing version of this gate is also closed.** `spike_above` in
`strategies/config.py` halves size when the 14-bar true-range average reaches
the 80th percentile of its own last 1,500 bars, and its default is 0.0 -
**off is the measured setting**. Halving on the switch beat halving a random
fifth in 1 of 18 cells unstopped and **0 of 18 with a stop**, and a uniform
cut in risk per trade beat it everywhere (`crash-timing.md`,
`session-switch.md`).

## The actual question, which those did not ask

> Does gating a direction rule **on entry** on predicted high volatility
> produce a book that pays?

The closed studies asked what to do with the *size* of a position already
taken. This asks whether to take it. Three further things they measured are
carried in here as controls rather than assumed away.

## The three controls, each for one named property

**1. The duty-cycle twin, for trading less.** "Only trade when volatility is
predicted high" is a rule that trades *less*, and on a net-negative book any
rule that trades less improves. Every pause rule tested here beat its baseline
and none beat its own random twin (`strategy-switching.md`,
`statespace-regime-gates.md`, p 0.45-0.51). Every gated arm is scored against a
random gate **keeping exactly the number of signals the gate kept**, reported
net **per unit traded**.

The twin is drawn by **whole days**. A volatility gate selects bars that
cluster in days, so a twin drawing candidates independently has a narrower
spread and would hand a duty-cycle effect a significant p. `twin_iid_sd` is
reported beside it - computed exactly for sampling without replacement rather
than simulated - to show how much the clustering matters.

**And the duty-cycle twin alone is not enough, which this harness found before
it ran on a market.** The twin keeps the same number of trades but keeps them
at the book's *average* cost in R, while a volatility gate keeps the ones
whose stop is widest and whose spread is therefore cheapest in R. It controls
for trading **less** and not for trading **cheaper**. On generated bars a
**coin** - no direction content whatever - cleared its net twin at **z =
+12.8** at keep 0.5, with gross expectancy flat (-0.141 to -0.138) and cost in
R falling from 0.676 to 0.279. So every control here is run on three measures:
`net` (which carries the arithmetic), **`gross` (which does not, and is the
test that decides the study)** and `cash`.

**2. The hour-matched placebo, for the session clock.** `manifold.md` found the
largest structure in these states is the hour of day, and `session-switch.md`
found the hour explains **17-40%** of production's switch firing at 3m and
6.7-9.5% at 15m. So a volatility gate is partly an instruction to trade at
14-15 UTC, where this desk's own intraday profile already puts FX volatility
at about 3x its quiet hours (`calendar-returns.md`).
Every gate is therefore also scored against a placebo drawn from the same
candidates with the **gate's own hour histogram**, and `hour_share` reports how
much of the gate's firing the hour explains. The placebo's mean and standard
error are the exact stratified-sampling ones, so this control costs nothing to
run at every cell.

**3. The unit, because R already absorbs the effect.** This desk sets risk in
multiples of the entry-time volatility, so a position opened into high
volatility is *already small*. In `crash-timing.md` the switch looked useful in
fixed units (+10.79 against a placebo's +3.83 on 15m FX) and vanished in
production's R (+1.68 against +1.81). Every outcome here is therefore reported
twice: in **R**, and in a fixed session-blind **cash** unit, the series' own
median EWMA volatility. The gap between those two numbers is the lesson, so
both are columns.

## The mechanism that is real and is not direction skill

Cost in R is `cost_px / risk`, and `risk = STOP_MULT x predicted volatility`.
In high volatility the stop is wider, so the same spread is a smaller fraction
of R. **A zero-edge direction rule is less unprofitable in high volatility for
that reason alone**, with no forecasting involved. Every cell reports gross
expectancy, cost in R and net expectancy separately, and
`vol_gate_buckets.csv` reports all three per predicted-volatility quintile, so
the write-up can decompose `d_net = d_gross - d_cost`.

## The arms

| arm | what it is for |
| --- | --- |
| `real` | the market as served |
| `walk` | the same bars with whole **days** permuted. Each bar's wick, range and body travel with it, so the tail is the market's own, while direction memory and clustering **across** days are gone. `findings.md` forbids Deriv as a general control, and the synthetics are a poor tail control in any case - their kurtosis is 3.19 against 20.07 on the traded series - so a real leg is block-shuffled instead. Clustering *within* a day survives, which makes this a conservative null for the gate rather than an empty one - the constant-volatility synthetics are the empty one. |
| `plant<d>` | a momentum drift of `d` forecast units planted **only in the high-volatility regime**, so the power sweep asks the study's own question: can the twin test see an edge that really is concentrated where the gate looks? |

Deriv synthetics are carried as named-property controls, not a general null:
`Volatility 25/75 Index` and `Step Index` are generated at constant
volatility, so a gate on predicted volatility has nothing to select and **any**
gating benefit there is the cost arithmetic or a bug. `Jump 75 Index` has fat
tails without clustering.

## The rules as frozen

* **Bars** 15m from the broker cache, 8 traded markets and 4 Deriv synthetics.
* **Split** first half by time is discovery, second half confirmation. Every
  model is fitted on discovery only; both halves are reported separately.
* **Mask** no rollover hour (20-23 UTC) and no bar within 4 of a session gap -
  `fx-reversal.md`'s mask, reused.
* **Stage A** target `log mean(|r|)` over the next 12 bars. Features use bars
  **up to and including** the decision bar, because the trade is entered at
  that bar's close and the target begins at the next one. Three models:
  `ewma` (the shipped EWMA of `|r|`, span 60, untouched), `har` (OLS on log
  realised volatility at 1h, 1d, 1w) and `gbm` (histogram gradient boosting on
  the compression, range and clock features). Reported: QLIKE, Spearman rank
  correlation, pinball loss at 0.1/0.5/0.9 and next-bar interval coverage
  against **Gaussian** and **Student-t(4)** nominals and against a
  discovery-calibrated one.
* **Stage B** at every masked bar a direction rule gives a side. Risk is
  `3.0 x the book's volatility estimate` - `risk_vol` is a structures feature
  about the level; the stop is `Intent.stop_vol`, whose live median is 3.0.
  The target is `N x risk`, the stop `1 x risk`, raced bar by bar over at most
  96 bars on each bar's own high and low; **both barriers inside one bar
  counts as the stop**, because a bar is a summary and the adverse order is
  the one that cannot be argued away. Unresolved at 96 bars, marked to market.
  Cost is one quoted round trip, charged in R and in cash.
* **Non-overlap** the ungated book is sequential: a signal is taken only when
  flat. The gate, its twin and its hour placebo then select subsets of **that**
  candidate set, which is what makes the keep-rate comparison exact. A truly
  gated book could re-enter sooner; this understates its trade count, and that
  is a caveat rather than something modelled here.
* **Two books** `ewma` and `gbm`, differing only in the volatility the stop is
  a multiple of. Within each, **three gate statistics** at keep rates 0.50,
  0.30, 0.20 and 0.10:
  - `model` - the trailing rank of that book's own **forecast** of the next 12
    bars;
  - `trpct` - production's switch, the 14-bar EWMA of the bar range ranked in
    its own last 1,500 bars. **Contemporaneous, not a forecast**, which is the
    comparison nobody here has run;
  - `samehour` - `session-switch.md`'s `deseason`: the forecast divided by its
    own 20-day mean at the same UTC hour, then ranked. If the gate is the
    clock, this is the arm that says so.

  Every rank window is 1,500 bars (minimum 500), production's, so the three
  gates differ in **what** they rank and not in how far back.
* **Direction rules** `mom1` (sign of the last return), `rev1` (its opposite),
  `donch` (20-bar closing extreme) and `coin` (a seeded pseudo-random side).
  The coin is the sign-flip surrogate: identical entry bars, identical stops,
  identical costs, no direction content.
* **Errors** day-block bootstrap on every mean, because trades cluster in days.
* **Multiplicity** Benjamini-Hochberg at q=0.05 over the full real-arm
  gate-versus-twin cell count, which the run prints.
* **Lead with the tail** `P(gross >= N R)` for real, for the walk, for the
  coin on the same bars, and against `1/(1+N)`.

## The twin's p, and why it is not a rank

A rank inside `NTWIN` draws floors at `1/(NTWIN+1)`, and Benjamini-Hochberg
over ten thousand cells needs a p near 5e-6 at the first rank, which no
affordable rank could reach. The twin distribution is a mean over a random
subset - a mean of day means - and is close to Gaussian, so the p used for BH
is `z = (gate - twin_mean) / twin_sd` read off a normal. `rank_p` is reported
beside it, and a twin that is not Gaussian shows up as the two disagreeing.
"""

from __future__ import annotations

import math
import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

SEQLAB = os.environ.get("SEQLAB", ".data/seqlab")
OUT = os.environ.get("OUT", ".")
BASE = os.environ.get("BASE", "15m")

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD", "XAGUSD", "BTCUSD")
SYNTH = ("Volatility 75 Index", "Volatility 25 Index", "Step Index", "Jump 75 Index")
#: Written down so a reading cannot later be credited to a property nobody
#: claimed. `findings.md`: Deriv synthetics are a real market, never a general
#: control.
PROPERTY = {
    "Volatility 75 Index": "constant volatility: nothing for a volatility gate to select",
    "Volatility 25 Index": "constant volatility: nothing for a volatility gate to select",
    "Step Index": "fixed step: neither clustering nor a tail",
    "Jump 75 Index": "fat tails without clustering",
}

#: `point` per symbol, read from the bridge's `GET /api/v1/symbols/info/` on
#: 2026-11-05 and carried here from `impulse_vol.py`. The stored `spread`
#: column is in **points, not price**; reading it as price once put a 476%
#: round trip on EURUSD and reordered every instrument by cost.
POINT: dict[str, float] = {
    "EURUSD": 1e-05, "GBPUSD": 1e-05, "USDJPY": 0.001, "AUDUSD": 1e-05,
    "USDCAD": 1e-05, "XAUUSD": 0.01, "XAGUSD": 0.001, "BTCUSD": 0.001,
    "Volatility 75 Index": 0.01, "Volatility 25 Index": 0.001,
    "Step Index": 0.1, "Jump 75 Index": 0.01,
}
#: The spread the terminal **quoted** on 2026-11-05, in points. Every cost
#: statement here is made at this, not at the stored per-bar column, which
#: reads 3.3-8.3x below it on FX and 6.5x above it on `Volatility 75 Index`.
SPREAD_POINTS: dict[str, float] = {
    "EURUSD": 9, "GBPUSD": 11, "USDJPY": 9, "AUDUSD": 7, "USDCAD": 10,
    "XAUUSD": 16, "XAGUSD": 30, "BTCUSD": 18_424, "Volatility 75 Index": 1_343,
    "Volatility 25 Index": 331, "Step Index": 1, "Jump 75 Index": 180,
}

ROLLOVER_HOURS = (20, 21, 22, 23)
GAP_SECONDS = 3_600
GAP_BARS = 4

HORIZON = 12          # bars of forward volatility the model forecasts
STOP_MULT = 3.0       # risk = STOP_MULT x the book's volatility estimate
MAXBARS = 96          # one trading day at 15m, after which a trade is marked out
TARGETS = (1.0, 2.0, 4.0)
KEEPS = (0.50, 0.30, 0.20, 0.10)
RULES = ("mom1", "rev1", "donch", "coin")
BOOKS = ("ewma", "gbm")                     # what the stop is a multiple of
GATES = ("model", "trpct", "samehour")      # what the gate ranks
CALIB = ("ewma", "har", "gbm")              # what the calibration table reports
#: The power sweep is one cell wide on purpose: it asks whether the twin test
#: can see a planted edge, not whether every rule can.
PLANT_BOOK, PLANT_GATE, PLANT_RULE, PLANT_TARGET = "gbm", "model", "donch", 2.0
DONCH = 20
#: Production's window: `tr_percentile` ranks in the instrument's own last
#: 1,500 bars. Every gate here uses it, so the three differ in **what** they
#: rank rather than in how far back they look.
STATE_WIN, STATE_MIN = 1_500, 500
EWMA_SPAN = 60
#: Production's switch statistic: a 14-bar EWMA of true range.
TR_SPAN = 14
#: `session-switch.md`'s `deseason` baseline, in days at the same UTC hour.
SEASON_DAYS = 20
PLANTED = (0.02, 0.05, 0.10, 0.20)
#: 400 twins estimates the twin spread to about 3.5%, which is all the
#: Gaussian p needs; the rank it also yields floors at 1/401 and is reported
#: rather than used.
NTWIN = 400
BOOT = 400
MIN_TRADES = 50
QUANTILES = (0.1, 0.5, 0.9)
NOMINAL = (0.80, 0.90, 0.95, 0.99)
SEED = 20261105

#: One-sided normal quantiles, hard-coded so the run needs no scipy.
NORMAL_Q = {0.80: 1.2815515655, 0.90: 1.6448536270, 0.95: 1.9599639845,
            0.99: 2.5758293035}
#: The matching Student-t(4) quantiles. For a Student-t(4), E|X| equals the
#: scale exactly, so these multiply a mean-|r| forecast directly; for a
#: Gaussian E|X| = sigma sqrt(2/pi), so that arm carries the sqrt(pi/2).
T4_Q = {0.80: 1.5332063483, 0.90: 2.1318467863, 0.95: 2.7764451052,
        0.99: 4.6040948714}


def _seqlab(ticker: str, interval: str) -> pd.DataFrame:
    """`$SEQLAB/<TICKER>.<interval>.npz`, oldest first, bars repaired to
    contain their own open and close."""
    z = np.load(f"{SEQLAB}/{ticker}.{interval}.npz")
    df = pd.DataFrame({
        "ts": z["time"].astype(np.int64),
        "open": z["open"], "high": z["high"], "low": z["low"], "close": z["close"],
        "spread": z["spread"] if "spread" in z.files else np.zeros(len(z["time"])),
    })
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


def frame(symbol: str) -> dict[str, np.ndarray] | None:
    """Per-bar arrays in log price, with each bar's wick carried as an offset
    from its own close so a permuted or drifted path can be rebuilt with the
    bar geometry intact."""
    try:
        df = _seqlab(symbol, BASE)
    except Exception as exc:  # a symbol the cache does not hold
        print(f"  {symbol}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    if len(df) < 20_000:
        print(f"  {symbol}: {len(df)} bars, too few", file=sys.stderr)
        return None
    close = df.close.to_numpy(float)
    lc = np.log(close)
    when = pd.to_datetime(df.ts.to_numpy(), unit="s", utc=True)
    point = POINT[symbol]
    out = {
        "ts": df.ts.to_numpy(),
        "r": np.concatenate([[np.nan], np.diff(lc)]),
        "up": np.log(df.high.to_numpy(float)) - lc,   # >= 0 after the repair
        "dn": lc - np.log(df.low.to_numpy(float)),    # >= 0 after the repair
        "quoted": SPREAD_POINTS[symbol] * point / close,
        "stored": df.spread.to_numpy(float) * point / close,
        "hour": when.hour.to_numpy(),
        "dow": when.dayofweek.to_numpy(),
    }
    gap = np.diff(out["ts"], prepend=out["ts"][0]) > GAP_SECONDS
    bad = np.zeros(len(lc), bool)
    for step in range(GAP_BARS):
        hit = np.flatnonzero(gap) + step
        bad[hit[hit < len(bad)]] = True
    out["mask"] = (~np.isin(out["hour"], ROLLOVER_HOURS)) & (~bad)
    out["day"] = np.unique(out["ts"] // 86_400, return_inverse=True)[1]
    good = np.isfinite(out["r"])
    return {k: v[good] for k, v in out.items()}


def _ewma_abs(r: np.ndarray, span: int) -> np.ndarray:
    """EWMA of `|r|` **including the current bar**: the decision is taken at
    that bar's close, so the bar is known. The target starts at the next bar,
    which is what keeps this out of the future."""
    return pd.Series(np.abs(r)).ewm(span=span, min_periods=span).mean().to_numpy()


def _roll_mean(x: np.ndarray, win: int) -> np.ndarray:
    return pd.Series(x).rolling(win, min_periods=win).mean().to_numpy()


def features(arm: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
    """Everything known at the close of the decision bar.

    `volatility-estimators.md` ranked the range-based estimators above the
    close-to-close one for forecasting the forward range, so the range enters
    as its own column rather than as an afterthought.
    """
    r, up, dn = arm["r"], arm["up"], arm["dn"]
    rng = up + dn
    eps = 1e-12
    cols = {
        "ewma20": np.log(_ewma_abs(r, 20) + eps),
        "ewma60": np.log(_ewma_abs(r, EWMA_SPAN) + eps),
        "ewma240": np.log(_ewma_abs(r, 240) + eps),
        "har1h": np.log(_roll_mean(np.abs(r), 4) + eps),
        "har1d": np.log(_roll_mean(np.abs(r), 96) + eps),
        "har1w": np.log(_roll_mean(np.abs(r), 480) + eps),
        "range4": np.log(_roll_mean(rng, 4) + eps),
        "range96": np.log(_roll_mean(rng, 96) + eps),
    }
    cols["compress"] = cols["ewma20"] - cols["ewma240"]
    cols["range_vs_close"] = cols["range4"] - cols["har1h"]
    cols["innovation"] = np.log(np.abs(r) + eps) - cols["ewma60"]
    cols["hour"] = arm["hour"].astype(float)
    cols["dow"] = arm["dow"].astype(float)
    names = list(cols)
    return np.column_stack([cols[k] for k in names]), names


def forward_vol(r: np.ndarray, k: int) -> np.ndarray:
    """Mean `|return|` over the next `k` bars - the unit the forecast is in.

    An RMS would be one estimator divided by a MAD one, and their ratio moves
    with the shape of the tail, so the null would not be 1.
    """
    n = len(r)
    cua = np.concatenate([[0.0], np.cumsum(np.abs(np.nan_to_num(r)))])
    out = np.full(n, np.nan)
    i = np.arange(n - k)
    out[i] = (cua[i + 1 + k] - cua[i + 1]) / k
    return out


def fit_vol_models(
    x: np.ndarray, y: np.ndarray, fit: np.ndarray, arm: dict,
    names: list[str], seed: int,
) -> dict[str, np.ndarray]:
    """Point forecasts of forward mean `|r|`, in price units.

    The log target is exponentiated with a **smearing** factor estimated on
    the discovery rows, so a model unbiased in logs is not left biased in
    levels. The `ewma` arm is the shipped estimator untouched:
    Reproducing the incumbent before adding to it is not a formality here: a
    HAR once read +0.036 against a shelf's +0.110 on this desk and the cause
    was the data window, not the model.
    """
    out: dict[str, np.ndarray] = {"ewma": _ewma_abs(arm["r"], EWMA_SPAN)}

    cols = [names.index(c) for c in ("har1h", "har1d", "har1w")]
    design = np.column_stack([np.ones(len(x)), x[:, cols]])
    beta, *_ = np.linalg.lstsq(design[fit], y[fit], rcond=None)
    pred = design @ beta
    out["har"] = np.exp(pred) * float(np.mean(np.exp(y[fit] - pred[fit])))

    model = HistGradientBoostingRegressor(
        loss="squared_error", max_iter=300, learning_rate=0.06,
        max_leaf_nodes=31, min_samples_leaf=200, l2_regularization=1.0,
        early_stopping=False, random_state=seed,
    )
    model.fit(x[fit], y[fit])
    pred = model.predict(x)
    out["gbm"] = np.exp(pred) * float(np.mean(np.exp(y[fit] - pred[fit])))
    return out


def quantile_preds(
    x: np.ndarray, y: np.ndarray, fit: np.ndarray, point: dict[str, np.ndarray], seed: int
) -> dict[tuple[str, float], np.ndarray]:
    """Level quantiles of forward volatility.

    `gbm` fits a quantile objective in logs, and a quantile is equivariant
    under a monotone transform, so exponentiating the log quantile **is** the
    level quantile. `ewma` and `har` get the discovery quantile of
    `realised / forecast` as a multiplier - the same calibration either would
    get if it were shipped, so the comparison is not against a straw man.
    """
    out: dict[tuple[str, float], np.ndarray] = {}
    for q in QUANTILES:
        model = HistGradientBoostingRegressor(
            loss="quantile", quantile=q, max_iter=300, learning_rate=0.06,
            max_leaf_nodes=31, min_samples_leaf=200, l2_regularization=1.0,
            early_stopping=False, random_state=seed,
        )
        model.fit(x[fit], y[fit])
        out[("gbm", q)] = np.exp(model.predict(x))
        for name in ("ewma", "har"):
            ratio = np.exp(y[fit]) / point[name][fit]
            out[(name, q)] = point[name] * float(np.quantile(ratio[np.isfinite(ratio)], q))
    return out


def trailing_rank(x: np.ndarray) -> np.ndarray:
    """Production's `tr_percentile` shape: a percentile inside the
    instrument's own last 1,500 bars. A global quantile would label the past
    with the future."""
    return pd.Series(x).rolling(STATE_WIN, min_periods=STATE_MIN).rank(pct=True).to_numpy()


def gate_ranks(pred: np.ndarray, arm: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """The three gate statistics, all ranked in the same 1,500-bar window so
    they differ in what they rank and not in how far back.

    `samehour` is `session-switch.md`'s `deseason` arm. At 3m the hour
    explained 17-40% of production's switch firing and both session-aware
    variants brought that to 0.7% or less, so this is the arm that says
    whether the gate is the clock.
    """
    out = {"model": trailing_rank(pred)}
    tr = pd.Series(arm["up"] + arm["dn"]).ewm(
        span=TR_SPAN, min_periods=TR_SPAN).mean().to_numpy()
    out["trpct"] = trailing_rank(tr)
    season = np.full(len(pred), np.nan)
    for h in range(24):
        idx = np.flatnonzero(arm["hour"] == h)
        if len(idx) <= SEASON_DAYS:
            continue
        base = pd.Series(pred[idx]).rolling(
            SEASON_DAYS, min_periods=SEASON_DAYS).mean().to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            season[idx] = pred[idx] / base
    out["samehour"] = trailing_rank(season)
    return out


def sides(arm: dict[str, np.ndarray], rule: str, rng: np.random.Generator) -> np.ndarray:
    """A side in {-1, 0, +1} at every bar; 0 is no signal.

    `np.sign` is 0 on a bar that rounds to no move, which a five-decimal FX
    quote does in a quiet hour - `vol-particle.md` found those same bars
    blowing up a filter. They become no-signal rather than a long.
    """
    r = arm["r"]
    if rule == "mom1":
        return np.sign(r)
    if rule == "rev1":
        return -np.sign(r)
    if rule == "coin":
        return rng.choice((-1.0, 1.0), size=len(r))
    if rule == "donch":
        lc = np.cumsum(np.nan_to_num(r))
        top = pd.Series(lc).rolling(DONCH, min_periods=DONCH).max().to_numpy()
        bot = pd.Series(lc).rolling(DONCH, min_periods=DONCH).min().to_numpy()
        out = np.zeros(len(r))
        out[lc >= top] = 1.0
        out[lc <= bot] = -1.0
        return out
    raise ValueError(rule)


def race(
    lc: np.ndarray, lh: np.ndarray, ll: np.ndarray,
    idx: np.ndarray, side: np.ndarray, risk: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """First passage to `+N x risk` or `-1 x risk`, for every N in `TARGETS`
    at once.

    Both barriers inside one bar counts as the **stop**. Unresolved after
    `MAXBARS`, the trade is marked to market, so no trade is silently dropped
    for failing to resolve - a dropped cell is invisible.

    Returns gross R, the resolution offset and whether a barrier was
    actually reached, each `(len(idx), len(TARGETS))`. The third is reported
    because `P(>= N R)` falls short of `1/(1+N)` partly for the honest reason
    that a trade marked out at 96 bars reached neither barrier, and a reader
    cannot tell that from the tail alone.
    """
    m, t = len(idx), len(TARGETS)
    if m == 0:
        return np.zeros((0, t)), np.zeros((0, t), int), np.zeros((0, t), bool)
    n = len(lc)
    entry = lc[idx]
    stop = entry - side * risk
    tgts = np.asarray(TARGETS)
    tgt = entry[:, None] + side[:, None] * tgts[None, :] * risk[:, None]
    out = np.full((m, t), np.nan)
    dur = np.full((m, t), MAXBARS, dtype=int)
    live = np.ones((m, t), bool)
    for step in range(1, MAXBARS + 1):
        u = np.minimum(idx + step, n - 1)
        hi, lo = lh[u], ll[u]
        adverse = np.where(side > 0, lo <= stop, hi >= stop)[:, None]
        favour = np.where(side[:, None] > 0, hi[:, None] >= tgt, lo[:, None] <= tgt)
        hit_stop = live & adverse
        hit_tgt = live & favour & ~hit_stop
        out[hit_stop] = -1.0
        out[hit_tgt] = np.broadcast_to(tgts[None, :], (m, t))[hit_tgt]
        newly = hit_stop | hit_tgt
        dur[newly] = step
        live &= ~newly
        if not live.any():
            break
    if live.any():
        mtm = side * (lc[np.minimum(idx + MAXBARS, n - 1)] - entry) / risk
        out[live] = np.broadcast_to(mtm[:, None], (m, t))[live]
    return out, dur, ~live


def sequential(signal: np.ndarray, dur: np.ndarray) -> np.ndarray:
    """The ungated book: take a signal only when flat.

    `dur` is the resolution offset of the trade that *would* open at each bar,
    so the walk forward is causal - nothing here reads an outcome before
    deciding to enter one.
    """
    keep: list[int] = []
    free = 0
    for i in np.flatnonzero(signal):
        if i < free:
            continue
        keep.append(int(i))
        free = int(i) + int(dur[i]) + 1
    return np.array(keep, dtype=int)


def _day_blocks(day: np.ndarray, value: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-day sums and counts, so a bootstrap or a twin draw is O(days)
    rather than O(days x trades) - the loop-per-day version does not finish on
    eleven years of candidates."""
    _, inv = np.unique(day, return_inverse=True)
    return np.bincount(inv, weights=value), np.bincount(inv).astype(float)


def boot_mean(day: np.ndarray, value: np.ndarray, rng) -> tuple[float, float]:
    """Day-block bootstrap mean and standard error: trades cluster in days and
    an ordinary standard error is far too narrow."""
    if len(value) == 0:
        return float("nan"), float("nan")
    tot, num = _day_blocks(day, value)
    picks = rng.integers(0, len(tot), size=(BOOT, len(tot)))
    means = tot[picks].sum(1) / num[picks].sum(1)
    return float(value.mean()), float(means.std(ddof=1))


def twin_draws(day: np.ndarray, values: dict[str, np.ndarray], want: int, rng
               ) -> dict[str, np.ndarray]:
    """`NTWIN` random gates, each keeping about `want` candidates, drawn by
    **whole days**.

    A volatility gate selects bars that cluster in days, so a twin drawing
    candidates independently has a narrower spread and would hand a
    duty-cycle effect a significant p. Days are taken in random order until
    the count reaches `want`, so a twin keeps at most one day's worth more
    than the gate did.

    Every measure is served from **one** set of permutations, because the draw
    depends on the days and the keep count and never on which measure is being
    read. Doing it per measure made this 64% of the run.
    """
    _, inv = np.unique(day, return_inverse=True)
    num = np.bincount(inv).astype(float)
    perm = np.argsort(rng.random((NTWIN, len(num))), axis=1)
    cnt = np.cumsum(num[perm], axis=1)
    k = np.argmax(cnt >= want, axis=1)
    rows = np.arange(NTWIN)
    denom = cnt[rows, k]
    return {
        name: np.cumsum(np.bincount(inv, weights=v, minlength=len(num))[perm],
                        axis=1)[rows, k] / denom
        for name, v in values.items()
    }


def iid_twin_sd(value: np.ndarray, want: int) -> float:
    """The same twin drawn candidate by candidate, **exactly** rather than
    simulated: sampling `want` of `n` without replacement gives a mean with
    variance `(1 - want/n) s^2 / want`.

    Carried only to show how much the day clustering matters. This one ignores
    it and is therefore anti-conservative, which is the point of printing it.
    """
    n = len(value)
    if want <= 1 or want >= n:
        return float("nan")
    return float(math.sqrt((1.0 - want / n) * value.var(ddof=1) / want))


def hour_placebo(hour: np.ndarray, value: np.ndarray, sel: np.ndarray
                 ) -> tuple[float, float, float]:
    """A placebo drawn from the same candidates with the **gate's own hour
    histogram**, and the share of the gate's firing the hour explains.

    `session-switch.md` found the hour explains 17-40% of production's switch
    at 3m and 6.7-9.5% at 15m, so a volatility gate is partly an instruction
    to trade at 14-15 UTC. The mean and standard error are the exact
    stratified-without-replacement ones, so this control is free at every
    cell: no simulation, and no sampling noise of its own.

    Returns the placebo mean, its standard error, and `eta^2` of the gate
    indicator on the hour.
    """
    n_h = np.bincount(hour, minlength=24).astype(float)
    sum_h = np.bincount(hour, weights=value, minlength=24)
    sq_h = np.bincount(hour, weights=value * value, minlength=24)
    safe = np.maximum(n_h, 1.0)
    mean_h = sum_h / safe
    var_h = np.where(n_h > 1, (sq_h / safe - mean_h**2) * n_h / np.maximum(n_h - 1, 1), 0.0)

    pick = np.zeros(len(value), bool)
    pick[sel] = True
    want_h = np.bincount(hour[sel], minlength=24).astype(float)
    want = want_h.sum()
    if want <= 0:
        return float("nan"), float("nan"), float("nan")
    mean = float((want_h * mean_h).sum() / want)
    # Finite-population correction per hour: an hour the gate takes whole
    # contributes no variance, because no other draw was available there.
    fpc = np.where(n_h > 0, 1.0 - want_h / safe, 0.0)
    varm = float((want_h * var_h * fpc).sum() / (want * want))

    share = pick.astype(float)
    grand = share.mean()
    between = float((n_h * (np.where(n_h > 0, np.bincount(
        hour[sel], minlength=24) / safe, grand) - grand) ** 2).sum())
    total = float(((share - grand) ** 2).sum())
    return mean, float(math.sqrt(max(varm, 0.0))), (between / total if total > 0 else math.nan)


def bh(p: np.ndarray, q: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg over every cell, returning the rejection mask."""
    out = np.zeros(len(p), bool)
    ok = np.isfinite(p)
    if not ok.any():
        return out
    idx = np.flatnonzero(ok)
    order = idx[np.argsort(p[idx])]
    m = len(order)
    passed = p[order] <= q * np.arange(1, m + 1) / m
    if passed.any():
        out[order[: np.flatnonzero(passed)[-1] + 1]] = True
    return out


def make_arm(base: dict[str, np.ndarray], kind: str, rng) -> dict[str, np.ndarray]:
    """`real`, `walk` (whole days permuted) or `plant<d>`."""
    if kind == "real":
        return dict(base)
    arm = dict(base)
    if kind == "walk":
        codes, inv = np.unique(base["day"], return_inverse=True)
        order = np.argsort(inv, kind="stable")
        sizes = np.bincount(inv, minlength=len(codes))
        starts = np.concatenate([[0], np.cumsum(sizes)])
        perm = rng.permutation(len(codes))
        take = np.concatenate([order[starts[j]: starts[j + 1]] for j in perm])
        for key in ("r", "up", "dn", "quoted", "stored", "hour", "dow", "mask"):
            arm[key] = base[key][take]
        # A new sequential day id, so the block bootstrap still resamples days.
        arm["day"] = np.repeat(np.arange(len(perm)), sizes[perm])
        return arm
    # A **persistent** trend in the high-volatility regime, not a one-bar
    # nudge. The first version of this planted `d x vol x sign(r[t-1])`, which
    # gives a trade exactly one aligned bar: 0.2 forecast units against a
    # 3-unit stop is 0.067R, and the sweep came back blind at every size with
    # z between -1.0 and +0.6. Aligning instead with the sign of the trailing
    # 20-bar move makes the drift hold for as long as that move does, so a
    # trade entered with it accumulates `d` units a bar - which is the shape
    # of edge this study would want to detect, and `donch` is the rule that
    # takes the same side by construction.
    drift = float(kind.removeprefix("plant"))
    vol = np.nan_to_num(_ewma_abs(base["r"], EWMA_SPAN))
    hot = np.nan_to_num(trailing_rank(vol), nan=0.0) >= 0.70
    lc = np.cumsum(np.nan_to_num(base["r"]))
    trend = np.sign(lc - np.concatenate([np.full(DONCH, lc[0]), lc[:-DONCH]]))
    arm["r"] = base["r"] + np.where(hot, drift * vol * trend, 0.0)
    return arm


def _calibration(symbol, kind, arm, x, y, fit, usable, point, n, half, seat) -> list[dict]:
    """Stage A, reported on the real arm only: the walk and the planted arms
    exist to score a book, not to be published as models."""
    rows: list[dict] = []
    qp = quantile_preds(x, y, fit, point, seed=seat)
    rv = np.exp(y)
    nxt = np.concatenate([np.abs(arm["r"][1:]), [np.nan]])
    for name in CALIB:
        pred = point[name]
        sane = np.isfinite(pred) & (pred > 0)
        seeded = usable & (np.arange(n) < half) & np.isfinite(nxt) & sane
        if seeded.sum() < 1_000:
            continue
        zfit = nxt[seeded] / pred[seeded]
        for is_conf, label in ((False, "discovery"), (True, "confirmation")):
            sel = usable & sane & ((np.arange(n) >= half) == is_conf)
            if sel.sum() < 1_000:
                continue
            ratio = rv[sel] / pred[sel]
            row = {
                "symbol": symbol, "kind": kind, "model": name, "half": label,
                "n": int(sel.sum()),
                "qlike": float(np.mean(ratio - np.log(ratio) - 1)),
                "spearman": float(pd.Series(pred[sel]).corr(
                    pd.Series(rv[sel]), method="spearman")),
                "pinball": float(np.mean([
                    np.mean(np.maximum(q * (rv[sel] - qp[(name, q)][sel]),
                                       (q - 1) * (rv[sel] - qp[(name, q)][sel])))
                    for q in QUANTILES])),
            }
            z = (nxt / pred)[sel & np.isfinite(nxt)]
            for p in NOMINAL:
                tag = int(p * 100)
                row[f"cov_gauss{tag}"] = float(
                    (z <= NORMAL_Q[p] * math.sqrt(math.pi / 2)).mean())
                row[f"cov_t4_{tag}"] = float((z <= T4_Q[p]).mean())
                row[f"cov_cal{tag}"] = float((z <= np.quantile(zfit, p)).mean())
            rows.append(row)
    return rows


def _two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2)) if np.isfinite(z) else math.nan


def _score(meta, cand, gross, net, cash_g, cash_n, cost_r, resolved, day, hour,
           rank, half, rng, twin_rng) -> list[dict]:
    """Every gate against its duty-cycle twin and its hour placebo, per unit
    traded, per half, on three measures.

    **The twin is run on `gross` as well as on `net`, and the gross one is the
    test that decides the study.** A duty-cycle twin keeps the same number of
    trades but keeps them at the book's *average* cost in R, while a
    volatility gate keeps the ones whose stop is widest and whose spread is
    therefore cheapest in R. So the twin controls for trading **less** and not
    for trading **cheaper**, and a rule with no direction content at all
    clears it: on generated bars a coin read z = +12.8 on `net` at keep 0.5
    while its gross expectancy did not move (-0.141 to -0.138) and its cost in
    R fell from 0.676 to 0.279.

    `gross` carries no cost term, so a gate that is picking better trades
    rather than cheaper ones has to show there. `cash_net` is the third
    measure, in the fixed session-blind unit, because R already absorbs the
    volatility (`crash-timing.md`).
    """
    rows: list[dict] = []
    target = meta["target"]
    for label, hm in (("all", np.ones(len(cand), bool)),
                      ("discovery", cand < half), ("confirmation", cand >= half)):
        if hm.sum() < MIN_TRADES:
            continue
        g, nt = gross[hm], net[hm]
        cn = cash_n[hm]
        c, d, hr, rk = cost_r[hm], day[hm], hour[hm], rank[hm]
        res = resolved[hm]
        measures = (("net", nt), ("gross", g), ("cash", cn))
        common = meta | {"half": label, "tail_null": 1.0 / (1.0 + target)}

        row = common | {
            "keep": 1.0, "n": int(hm.sum()), "cost_r": float(c.mean()),
            "cash_gross": float(cash_g[hm].mean()),
            "tail": float((g >= target).mean()), "resolved": float(res.mean()),
            "rank_p": np.nan,
            "twin_iid_sd": np.nan, "hour_share": np.nan,
        }
        for name, value in measures:
            mean, se = boot_mean(d, value, rng)
            row |= {name: mean, f"{name}_se": se,
                    f"twin_{name}": np.nan, f"twin_{name}_sd": np.nan,
                    f"z_{name}": np.nan, f"p_{name}": np.nan,
                    f"hour_{name}": np.nan, f"zh_{name}": np.nan,
                    f"ph_{name}": np.nan}
        rows.append(row)

        for keep in KEEPS:
            sel = np.flatnonzero(rk >= np.quantile(rk, 1.0 - keep))
            if len(sel) < MIN_TRADES or len(sel) >= len(rk):
                continue
            # The twin keeps exactly what the gate kept, ties included, so the
            # duty cycle is matched rather than approximately matched.
            want = len(sel)
            row = common | {
                "keep": keep, "n": want, "cost_r": float(c[sel].mean()),
                "cash_gross": float(cash_g[hm][sel].mean()),
                "tail": float((g[sel] >= target).mean()),
                "resolved": float(res[sel].mean()),
                "twin_iid_sd": iid_twin_sd(nt, want),
            }
            twins = twin_draws(d, dict(measures), want, twin_rng)
            for name, value in measures:
                mean, se = boot_mean(d[sel], value[sel], rng)
                twin = twins[name]
                sd = float(twin.std(ddof=1))
                z = (mean - float(twin.mean())) / sd if sd > 0 else math.nan
                h_mean, h_sd, h_share = hour_placebo(hr, value, sel)
                zh = (mean - h_mean) / h_sd if h_sd > 0 else math.nan
                row |= {
                    name: mean, f"{name}_se": se,
                    f"twin_{name}": float(twin.mean()), f"twin_{name}_sd": sd,
                    f"z_{name}": z, f"p_{name}": _two_sided(z),
                    f"hour_{name}": h_mean, f"zh_{name}": zh,
                    f"ph_{name}": _two_sided(zh),
                }
                if name == "net":
                    hits = int((np.abs(twin - twin.mean())
                                >= abs(mean - twin.mean())).sum())
                    row |= {"rank_p": (1 + hits) / (1 + NTWIN), "hour_share": h_share}
            rows.append(row)
    return rows


def _buckets(meta, gross, net, cost_r, cash_n, day, rank, rng) -> list[dict]:
    """Cost in R beside gross and net expectancy, per predicted-volatility
    quintile. This is the table that says whether a gate buys cheaper trades
    or better ones."""
    rows: list[dict] = []
    which = np.searchsorted(np.quantile(rank, [0.2, 0.4, 0.6, 0.8]), rank, side="right")
    for b in range(5):
        hit = which == b
        if hit.sum() < MIN_TRADES:
            continue
        m_net, se_net = boot_mean(day[hit], net[hit], rng)
        m_gross, se_gross = boot_mean(day[hit], gross[hit], rng)
        m_cost, se_cost = boot_mean(day[hit], cost_r[hit], rng)
        m_cash, se_cash = boot_mean(day[hit], cash_n[hit], rng)
        rows.append(meta | {
            "bucket": b, "n": int(hit.sum()),
            "gross": m_gross, "gross_se": se_gross,
            "cost_r": m_cost, "cost_se": se_cost,
            "net": m_net, "net_se": se_net,
            "cash_net": m_cash, "cash_net_se": se_cash,
            "tail": float((gross[hit] >= meta["target"]).mean()),
        })
    return rows


def one_symbol(job: tuple[str, int]) -> tuple[list[dict], list[dict], list[dict]]:
    symbol, seat = job
    rng = np.random.default_rng([SEED, seat])
    base = frame(symbol)
    if base is None:
        return [], [], []
    kind = "synth" if symbol in SYNTH else "traded"
    years = (base["ts"][-1] - base["ts"][0]) / 86_400 / 365.25
    #: The fixed session-blind unit every `cash_*` column is in. One number per
    #: series, so a cash reading is not quietly re-scaled by the regime - which
    #: is the whole difference `crash-timing.md` found between its two units.
    unit = float(np.nanmedian(_ewma_abs(base["r"], EWMA_SPAN)))
    print(f"{symbol}: {len(base['r'])} bars, {years:.1f}y, "
          f"{int(base['mask'].sum())} masked-in, cash unit {unit:.3e}",
          file=sys.stderr, flush=True)

    calib_rows: list[dict] = []
    book_rows: list[dict] = []
    bucket_rows: list[dict] = []

    for arm_kind in ("real", "walk", *(f"plant{d:g}" for d in PLANTED)):
        arm = make_arm(base, arm_kind, np.random.default_rng([SEED, seat, 7]))
        x, names = features(arm)
        y = np.log(forward_vol(arm["r"], HORIZON) + 1e-12)
        n = len(y)
        half = n // 2
        usable = np.isfinite(y) & np.isfinite(x).all(1)
        fit = usable.copy()
        fit[half:] = False
        if fit.sum() < 5_000:
            print(f"  {symbol} {arm_kind}: {int(fit.sum())} fit rows, skipped",
                  file=sys.stderr, flush=True)
            continue
        point = fit_vol_models(x, y, fit, arm, names, seed=seat)
        if arm_kind == "real":
            calib_rows += _calibration(
                symbol, kind, arm, x, y, fit, usable, point, n, half, seat)

        planted = arm_kind.startswith("plant")
        books = (PLANT_BOOK,) if planted else BOOKS
        gates = (PLANT_GATE,) if planted else GATES
        rules = (PLANT_RULE,) if planted else RULES
        targets = (PLANT_TARGET,) if planted else TARGETS
        lc = np.cumsum(np.nan_to_num(arm["r"]))
        lh, ll = lc + arm["up"], lc - arm["dn"]
        for book in books:
            pred = point[book]
            ranks = gate_ranks(pred, arm)
            risk_all = STOP_MULT * pred
            ready = (arm["mask"] & np.isfinite(pred) & (pred > 0)
                     & np.isfinite(x).all(1)
                     & np.isfinite(np.column_stack([ranks[g] for g in gates])).all(1))
            ready[-(MAXBARS + 1):] = False
            for rule in rules:
                sig = np.where(
                    ready, sides(arm, rule, np.random.default_rng([SEED, seat, 11])), 0.0)
                where = np.flatnonzero(sig)
                if len(where) < 200:
                    print(f"  {symbol} {arm_kind} {book} {rule}: {len(where)} signals",
                          file=sys.stderr, flush=True)
                    continue
                gross, dur, hit = race(lc, lh, ll, where, sig[where], risk_all[where])
                for target in targets:
                    ti = TARGETS.index(target)
                    full = np.zeros(n, int)
                    full[where] = dur[:, ti]
                    cand = sequential(sig, full)
                    if len(cand) < MIN_TRADES:
                        continue
                    at = np.searchsorted(where, cand)
                    g, res = gross[at, ti], hit[at, ti]
                    risk = risk_all[cand]
                    cost_r = arm["quoted"][cand] / risk
                    net = g - cost_r
                    # The same outcomes in a fixed, session-blind unit: a
                    # position of constant size rather than constant risk.
                    cash_g, cash_n = g * risk / unit, net * risk / unit
                    day, hour = arm["day"][cand], arm["hour"][cand]
                    for gate in gates:
                        meta = {
                            "symbol": symbol, "kind": kind, "arm": arm_kind,
                            "book": book, "gate": gate, "rule": rule, "target": target,
                        }
                        twin_rng = np.random.default_rng(
                            [SEED, seat, 23, BOOKS.index(book), GATES.index(gate),
                             RULES.index(rule), ti])
                        book_rows += _score(
                            meta, cand, g, net, cash_g, cash_n, cost_r, res, day,
                            hour, ranks[gate][cand], half, rng, twin_rng)
                        if arm_kind == "real":
                            bucket_rows += _buckets(
                                meta, g, net, cost_r, cash_n, day,
                                ranks[gate][cand], rng)
        print(f"  {symbol} {arm_kind}: done, {len(book_rows)} book rows so far",
              file=sys.stderr, flush=True)
    return calib_rows, book_rows, bucket_rows


def main() -> None:
    jobs = [(s, i) for i, s in enumerate((*TRADED, *SYNTH))]
    with Pool(min(12, len(jobs))) as pool:
        got = pool.map(one_symbol, jobs)
    calib = pd.DataFrame([r for c, _, _ in got for r in c])
    book = pd.DataFrame([r for _, b, _ in got for r in b])
    buckets = pd.DataFrame([r for _, _, k in got for r in k])
    os.makedirs(OUT, exist_ok=True)
    calib.to_csv(f"{OUT}/vol_gate_calibration.csv", index=False)
    book.to_csv(f"{OUT}/vol_gate_book.csv", index=False)
    buckets.to_csv(f"{OUT}/vol_gate_buckets.csv", index=False)

    print(f"\ncalibration rows {len(calib)}, book rows {len(book)}, "
          f"bucket rows {len(buckets)}")
    if len(book):
        cells = book[(book.arm == "real") & (book.keep < 1.0) & book.p_net.notna()]
        print(f"real-arm gate-vs-twin cells {len(cells)}")
        for name, label in (("net", "net R (carries the cost arithmetic)"),
                            ("gross", "gross R (the test that decides it)"),
                            ("cash", "fixed cash unit")):
            for control, how in ((f"p_{name}", "duty-cycle twin"),
                                 (f"ph_{name}", "hour-matched placebo")):
                hit = bh(cells[control].to_numpy())
                up = int((hit & (cells[f"z_{name}"].to_numpy() > 0)).sum())
                print(f"  {label:38s} vs {how:22s} BH rejections {int(hit.sum()):5d}"
                      f"  positive {up:5d}  negative {int(hit.sum()) - up:5d}")
        print("counts by arm:\n", book.groupby("arm").size().to_string())


if __name__ == "__main__":
    main()
