"""darts' anomaly scorers on this desk's bars: do the scores carry anything, do their clusters, do the transitions.

    ./.secrets/lab.sh sync
    ./.secrets/lab.sh exec '$HOME/till_infinity/repo/research/harness/dartsad_lab.sh \
        score BARS=60000 INTERVALS=15m FEATSETS=scaled,raw WORKERS=16'
    ./.secrets/lab.sh exec '$HOME/till_infinity/repo/research/harness/dartsad_lab.sh report'
    ./.secrets/lab.sh exec '$HOME/till_infinity/repo/research/harness/dartsad_lab.sh power'
    ./.secrets/lab.sh exec '$HOME/till_infinity/repo/research/harness/dartsad_lab.sh leak'
    ./.secrets/lab.sh exec 'tail -200 $HOME/till_infinity/logs/dartsad_report.log'

`score` writes one npz a cell to `out/dartsad/` and the other three phases read
them, so a scorer pass costs nothing twice. **Not `lab.sh run`**: that uses the
repo venv, and `u8darts` brings its own numpy 2.5 and pandas 3.1 majors which
must not be installed beside the suite's. `dartsad_lab.sh` holds the venv build
and the one-thread-per-worker environment.

Data: `data/seqlab` (the broker's 15m and 1h bars, 28 FX pairs, XAU, XAG, BTC,
and four Deriv feeds) and `data/syn` (the rest of the Deriv families at 15m,
including the two positive controls). Both are rebuilt by
`research/harness/seqcache.py` from the terminal; nothing here pulls bars.

Three questions in order, from the operator's brief: get anomaly scores out of
`unit8co/darts`, cluster the scores, then treat the clusters as states and
measure the transition matrix.

## What would make the comparison a lie

1. **`window_agg=True`**, darts' own default, puts the answer in the feature.
   See below; every window scorer here is built with it off.
2. **A stride-1 transition matrix.** Two neighbouring window scores share
   `WINDOW - 1` bars, so the overlap reads as persistence. Every state sequence
   is de-overlapped at `WINDOW` before a transition is counted.
3. **A score that restates volatility.** Every AUC is printed raw and within
   deciles of the incumbent `trpct`, and only the second number is read.
4. **The sample's own drift.** Q3b reports each transition's forward mean minus
   the instrument's unconditional mean over the same observations, and Q3d
   gives every traded cell a random twin of the same size on the same bars.
5. **A spread taken as a price.** The bar file's `spread` is in points. The
   point is measured off the quoted grid, and because the field carries no
   commission every net figure is also shown at `COST_MARGIN` times it.

## The look-ahead in darts' own default, which this file turns off

Every window scorer takes `window_agg`, and it defaults to **True**. That
spreads each window's score back across every bar the window touches and
averages, so the score at bar `t` is a function of windows that *start* at `t`
and run to `t + window - 1`. On a 40-bar probe with a single spike at bar 20,
`KMeansScorer(window=5)` read 2.40, 2.29, 4.12 and 5.95 at bars 16-19 - rising
**four bars before the spike existed**. With `window_agg=False` the same
scorer reads flat 0.57 to bar 19 and 9.73 from bar 20.

Any forward-looking label scored against the default therefore reads its own
answer back out of the feature. `PHASE=leak` prints the pair, and
`SCORE_SPECS` carries `window_agg=False` on every window scorer.

## What the arms are for

`scaled` divides each bar by the trailing 500-bar mean absolute return before
the scorer sees it, so the volatility *level* is gone and whatever the scorer
finds is bar shape. `raw` leaves returns in log price. The pair exists because
an anomaly score on raw returns is a volatility detector with a new name, and
`auc-is-free-on-volatility-targets` is the standing reason that has to be shown
rather than asserted: a range estimator read AUC 0.8052 on a constant-sigma
generator and 0.5250 inside strata of current volatility.

Every AUC is printed twice, raw and within deciles of the incumbent `trpct`.
The second number is the claim.
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from research.harness import dartsad

#: The window for every window scorer, and therefore the de-overlap stride.
#: Ten 15-minute bars is two and a half hours - long enough for a distribution
#: to be worth comparing and short enough that a 60,000-bar test block still
#: holds 2,400 disjoint observations.
WINDOW = 10

#: States the score vector is clustered into. Four, so each state can hold a
#: reportable share of the bars; `k-means` with sixteen states on 2,400
#: disjoint observations would put 150 in each and the transition matrix would
#: be 256 cells of noise.
STATES = 4

#: Share of each series, by time, the scorers and the clustering are fitted on.
#: `anomalies.py`'s split, kept so the blocks are the same blocks.
TRAIN = 0.6

#: Bars kept, most recent first. 60,000 at 15m is about 21 months. The binding
#: constraint is `WassersteinScorer`, which compares each window against the
#: stored training values and so costs O(n^2): measured 3.5s at 5,000 bars,
#: 62.3s at 20,000 and about 9 minutes at 60,000, per instrument per arm.
BARS = int(os.environ.get("BARS", "60000"))

#: Maximum bars a barrier race may stay open, and the reward-to-risk. 40 bars
#: at 15m is ten hours; the race is 1:1 so the driftless null is exactly 0.5.
MAX_HOLD = 40
STOP_ATR = 2.0

#: The bar file's `spread` is the broker's quoted spread at the bar and carries
#: no commission. `scalp_cost.py` read a 0.00011 round trip on EURUSD at 15m
#: from the terminal's own bid/ask against 0.00003 from this field, so every
#: net figure is also reported at this multiple of it. A verdict uses the
#: dearer column: an edge that only survives the cheap one is not affordable.
COST_MARGIN = 4.0

OUT = Path(os.environ.get("DARTSAD_OUT", str(Path.home() / "till_infinity" / "out" / "dartsad")))
STORES = {
    "seqlab": Path.home() / "till_infinity" / "data" / "seqlab",
    "syn": Path.home() / "till_infinity" / "data" / "syn",
}

#: Grouped so no table is pooled across things with different generators.
#: `drift_switch` and `range_break` are the positive controls - a planted drift
#: regime and a range by construction - and `deriv_vol` is the hardest control
#: available: a real market whose sigma is constant by publication, where a
#: state detector that finds persistent regimes is finding them in nothing.
GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "fx": (
        "seqlab",
        (
            "EURUSD",
            "GBPUSD",
            "AUDUSD",
            "NZDUSD",
            "USDCAD",
            "USDCHF",
            "USDJPY",
            "EURJPY",
            "GBPJPY",
            "EURGBP",
        ),
    ),
    "metal": ("seqlab", ("XAUUSD", "XAGUSD")),
    "crypto": ("seqlab", ("BTCUSD",)),
    "deriv_vol (control: sigma constant)": ("seqlab", ("Volatility 25 Index", "Volatility 75 Index")),
    "step (control: bounded coin)": ("seqlab", ("Step Index",)),
    "jump (control: memoryless jumps)": ("seqlab", ("Jump 75 Index",)),
    "drift_switch (positive: planted drift regime)": (
        "syn",
        ("Drift Switch Index 10", "Drift Switch Index 20", "Drift Switch Index 30"),
    ),
    "range_break (positive: a range by construction)": (
        "syn",
        ("Range Break 100 Index", "Range Break 200 Index"),
    ),
    "boomcrash": ("syn", ("Boom 500 Index", "Crash 500 Index")),
}


#: Bars of the train block `WassersteinScorer` keeps as its reference
#: distribution. It compares every window against every stored training value,
#: so its cost is the product: 20,000 scored against 10,000 stored took 62.3s,
#: and the whole train block of 36,000 would put one instrument at 9 minutes a
#: pass and this grid at four hours. The reference is an empirical
#: distribution, so 10,000 bars of it is 10,000 draws rather than an
#: approximation of something larger.
WASS_FIT = 10_000


def score_specs():
    """The five scorers, built lazily so this module imports without darts.

    `NormScorer` is not fittable and only scores *from a prediction*, so it is
    given a zero forecast: on a return series that makes it the L1 size of the
    bar, which is the incumbent wearing a scorer's name and is why it is here.

    `PyODScorer` wraps `IForest` rather than `KNN`: KNN scores each window
    against every training point and would cost the same as Wasserstein twice
    over, and the brief's "et al." is better spent on a model that finishes.
    """
    from darts.ad.scorers import KMeansScorer, NormScorer, PyODScorer, WassersteinScorer
    from pyod.models.iforest import IForest

    built = {
        "norm": ("prediction", NormScorer(ord=1), 1, None),
        "kmeans1": ("fit", KMeansScorer(window=1, k=8, random_state=0), 1, None),
        "kmeans10": (
            "fit",
            KMeansScorer(window=WINDOW, k=8, window_agg=False, random_state=0),
            WINDOW,
            None,
        ),
        "wass10": ("fit", WassersteinScorer(window=WINDOW, window_agg=False), WINDOW, WASS_FIT),
        "iforest10": (
            "fit",
            PyODScorer(
                model=IForest(random_state=0, n_estimators=100), window=WINDOW, window_agg=False
            ),
            WINDOW,
            None,
        ),
    }
    return {name: built[name] for name in SCORERS}


#: Which scorers this run uses, in order. Settable because `wass10` is the
#: only one whose cost is quadratic in the series length, and the transition
#: study wants the deep history: the cache holds 294,499 15m bars for EURUSD
#: and 20,000 for the crosses, and 60,000 bars leaves a 20-stride state
#: sequence with 2,400 observations against 16 transition cells. Dropping
#: `wass10` makes a 200,000-bar pass cost seconds.
#:
#:     SCORERS=norm,kmeans1,kmeans10,iforest10 BARS=200000 DARTSAD_OUT=.../deep
#:
#: `report` must be given the same list as `score`, or it reads a column the
#: npz does not hold.
SCORERS = tuple(
    os.environ.get("SCORERS", "norm,kmeans1,kmeans10,wass10,iforest10").split(",")
)


#: The `Drift Switch` family is let past `spikerisk.leak_check` on purpose, and
#: this is the only place in the study where a guard is overridden.
#:
#: The guard refuses a series whose close location inside the bar correlates
#: with the next return above 0.15 - the defect that made a yahoo daily FX
#: model look like a 94% winner. Measured on this cache, the three Drift Switch
#: indices read **+0.136, +0.154 and +0.136**, against -0.012 to -0.030 on
#: EURUSD, GBPUSD, USDJPY, XAUUSD and BTCUSD. That is not a misaligned bar: on
#: a planted drift regime the close really does sit near the bar's high while
#: the drift is up, and the next return really is positive. The guard is
#: calibrated for real markets and a genuinely predictable generator trips it,
#: so `Drift Switch Index 20` at +0.154 was refused and the two either side of
#: it at +0.136 were not - which would have silently dropped a third of the
#: positive control.
#:
#: Every npz carries `clv_corr`, so the number is in the data rather than only
#: in this comment.
ALLOW_CLV = ("Drift Switch",)


def load(store: str, symbol: str, interval: str):
    """Bars oldest first, repaired to contain their own open and close, leak-checked.

    Goes through `spikerisk.load` rather than reading the npz here so the repair
    and the guard are the production-shaped ones. The `ALLOW_CLV` families are
    re-read without the guard, for the reason recorded on that constant.
    """
    import numpy as _np
    import pandas as _pd

    from research.harness import spikerisk

    z = _np.load(STORES[store] / f"{symbol}.{interval}.npz")
    was = os.environ.get("SEQLAB")
    os.environ["SEQLAB"] = str(STORES[store])
    try:
        df = spikerisk.load(None, symbol, "SEQLAB", interval)
    except ValueError:
        if not symbol.startswith(ALLOW_CLV):
            raise
        df = _pd.DataFrame(
            {
                "ts": z["time"].astype(_np.int64),
                "open": z["open"],
                "high": z["high"],
                "low": z["low"],
                "close": z["close"],
                "volume": z["volume"],
            }
        )
        df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        df["high"] = df[["open", "high", "close"]].max(axis=1)
        df["low"] = df[["open", "low", "close"]].min(axis=1)
    finally:
        if was is None:
            os.environ.pop("SEQLAB", None)
        else:
            os.environ["SEQLAB"] = was

    spread = z["spread"].astype(float) if "spread" in z.files else _np.full(len(df), _np.nan)
    keep = _np.isin(z["time"].astype(_np.int64), df["ts"].to_numpy().astype(_np.int64))
    df = df.assign(spread=spread[keep][: len(df)])
    return df.iloc[-BARS:].reset_index(drop=True)


def run_scorers(features: np.ndarray, train_end: int) -> dict[str, np.ndarray]:
    """Every scorer's score aligned to the original bar index, NaN before it exists.

    A `window`-bar scorer returns `n - window + 1` values; they are stamped at
    the window's **last** bar, which is what makes the score a function of bars
    `t - window + 1 .. t` and nothing later.
    """
    import pandas as pd
    from darts import TimeSeries

    n = len(features)
    idx = pd.date_range("2000-01-01", periods=n, freq="15min")
    series = TimeSeries.from_times_and_values(idx, features)
    zero = TimeSeries.from_times_and_values(idx, np.zeros_like(features))
    train = series[:train_end]
    out: dict[str, np.ndarray] = {}
    for name, (how, scorer, window, fit_bars) in score_specs().items():
        if how == "prediction":
            got = scorer.score_from_prediction(series, zero)
        else:
            scorer.fit(train if fit_bars is None else series[max(0, train_end - fit_bars) : train_end])
            got = scorer.score(series)
        values = np.asarray(got.values(), dtype=float).ravel()
        column = np.full(n, np.nan)
        column[window - 1 : window - 1 + len(values)] = values
        out[name] = column
    return out


def standardise(scores: dict[str, np.ndarray], train_end: int) -> np.ndarray:
    """Score columns as a (n, 5) z-scored matrix, using the train block's moments only."""
    cols = []
    for name in SCORERS:
        x = scores[name]
        block = x[:train_end]
        block = block[np.isfinite(block)]
        mu = block.mean() if len(block) else 0.0
        sd = block.std() if len(block) and block.std() > 0 else 1.0
        cols.append((x - mu) / sd)
    return np.column_stack(cols)


def cluster(matrix: np.ndarray, train_end: int, k: int = STATES):
    """k-means on the standardised score vector, fitted on the train block only.

    States are relabelled by the mean of their own score vector so state 0 is
    always the quietest. Without that the state numbers are whatever k-means
    initialised to and no two instruments' tables can be read together.
    """
    from sklearn.cluster import KMeans

    good = np.all(np.isfinite(matrix), axis=1)
    fit_rows = good.copy()
    fit_rows[train_end:] = False
    if fit_rows.sum() < 100 * k:
        return np.full(len(matrix), -1), None
    model = KMeans(n_clusters=k, n_init=10, random_state=0).fit(matrix[fit_rows])
    order = np.argsort(model.cluster_centers_.mean(axis=1))
    remap = np.empty(k, dtype=int)
    remap[order] = np.arange(k)
    out = np.full(len(matrix), -1)
    out[good] = remap[model.predict(matrix[good])]
    return out, model


def one_cell(job):
    """Score one (group, symbol, interval, featureset) and its two nulls, to npz."""
    group, store, symbol, interval, featset = job
    try:
        df = load(store, symbol, interval)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        return f"skip {symbol} {interval} {featset}: {str(exc)[:70]}"
    o, h, lo, c = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    if len(c) < 5_000:
        return f"skip {symbol} {interval} {featset}: {len(c)} bars"
    g = dartsad.geometry(o, h, lo, c)
    lab = dartsad.labels(g)
    features = dartsad.scaled_features(g) if featset == "scaled" else dartsad.raw_features(g)
    n = len(c)
    train_end = int(TRAIN * n)

    store_out = {
        "ts": df["ts"].to_numpy().astype(np.int64),
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "train_end": np.int64(train_end),
        "fwd_logrv": dartsad.forward_logrv(g),
        "tick": np.float64(dartsad.tick_size(c)),
        "spread_pts": np.float64(np.nanmedian(df["spread"].to_numpy(dtype=float))),
        "clv_corr": np.float64(dartsad.clv_corr(h, lo, c)),
    }
    for key in ("r", "rng", "base", "mrng", "clv", "lvol", "trpct", "volvol", "tr"):
        store_out[key] = g[key]
    for key, value in lab.items():
        store_out[key] = value

    scores = run_scorers(features, train_end)
    for name, column in scores.items():
        store_out[f"s_{name}"] = column

    rng = np.random.default_rng(abs(hash((symbol, interval, featset))) % 2**31)
    shuffled = features[rng.permutation(n)]
    for name, column in run_scorers(shuffled, train_end).items():
        store_out[f"shuf_{name}"] = column
    blocks = np.array_split(np.arange(n), max(n // 200, 2))
    order = np.concatenate([blocks[i] for i in rng.permutation(len(blocks))])
    for name, column in run_scorers(features[order], train_end).items():
        store_out[f"block_{name}"] = column

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{symbol.replace(' ', '_')}.{interval}.{featset}.npz"
    np.savez_compressed(path, group=np.array(group), symbol=np.array(symbol), **store_out)
    return f"ok   {symbol} {interval} {featset}: {n:,} bars -> {path.name}"


def jobs(intervals, featsets):
    out = []
    for group, (store, symbols) in GROUPS.items():
        for symbol in symbols:
            for interval in intervals:
                for featset in featsets:
                    out.append((group, store, symbol, interval, featset))
    return out


def phase_score():
    intervals = tuple(os.environ.get("INTERVALS", "15m").split(","))
    featsets = tuple(os.environ.get("FEATSETS", "scaled,raw").split(","))
    plan = jobs(intervals, featsets)
    workers = int(os.environ.get("WORKERS", "24"))
    print(f"{len(plan)} cells, {workers} workers, {BARS:,} bars each, window {WINDOW}", flush=True)
    began = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one_cell, job) for job in plan]
        for i, future in enumerate(as_completed(futures), 1):
            print(f"  [{i}/{len(plan)}] {future.result()}", flush=True)
    print(f"done in {(time.time() - began) / 60:.1f}m", flush=True)


def cells(featset: str, interval: str):
    for path in sorted(OUT.glob(f"*.{interval}.{featset}.npz")):
        z = np.load(path, allow_pickle=False)
        yield str(z["symbol"]), str(z["group"]), z


def test_mask(z, need_window: int = WINDOW):
    """Rows in the scored block that every column is finite on, past the warmup."""
    n = len(z["r"])
    keep = np.zeros(n, bool)
    keep[int(z["train_end"]) :] = True
    keep[: 1500 + need_window] = False
    keep[n - 25 :] = False
    for name in SCORERS:
        keep &= np.isfinite(z[f"s_{name}"])
    for name in ("lvol", "trpct", "base", "mrng"):
        keep &= np.isfinite(z[name])
    return keep


def phase_report():
    interval = os.environ.get("INTERVAL", "15m")
    rng = np.random.default_rng(7)
    first = os.environ.get("FEATSETS", "scaled,raw").split(",")[0]
    print(f"\n{'=' * 118}\nQ0  THE DATA, PER INSTRUMENT")
    print(
        "    clv corr is `spikerisk.leak_check`'s own statistic - how much the close's location in\n"
        "    the bar predicts the next return. It refuses above 0.15. Real markets read -0.03 to\n"
        "    -0.01; the planted-drift control reads +0.14, which is the control working."
    )
    print(
        f"    {'instrument':<24}{'family':<46}{'bars':>9}{'test rows':>11}"
        f"{'clv corr':>10}{'shock rate':>12}"
    )
    for symbol, group, z in cells(first, interval):
        keep = test_mask(z)
        print(
            f"    {symbol:<24}{group:<46}{len(z['r']):>9,}{keep.sum():>11,}"
            f"{dartsad.clv_corr(z['high'], z['low'], z['close']):>10.3f}"
            f"{z['y_shock'][keep].mean() if keep.sum() else float('nan'):>11.2%}"
        )

    for featset in os.environ.get("FEATSETS", "scaled,raw").split(","):
        print(f"\n{'=' * 118}\nQ1  DO THE SCORES CARRY ANYTHING - {featset} features, {interval}")
        print(
            "    AUC for an anomaly in the next 4 bars, raw / within deciles of trpct. "
            "The second number is the claim."
        )
        columns = ("lvol", "trpct", *SCORERS)
        for kind in ("shock", "range"):
            print(f"\n  target: {kind} in the next 4 bars")
            header = f"    {'instrument':<24}{'rate':>7}{'n':>9}"
            for name in columns:
                header += f"{name:>19}"
            print(header)
            inside_by_group: dict[str, list[tuple[str, np.ndarray]]] = {}
            for symbol, group, z in cells(featset, interval):
                keep = test_mask(z)
                y = z[f"y_{kind}"][keep]
                if keep.sum() < 2_000 or y.mean() < 0.002:
                    print(f"    {symbol:<24}{'too rare or thin':>16}")
                    continue
                strata = z["trpct"][keep]
                line = f"    {symbol:<24}{y.mean():>6.2%}{keep.sum():>9,}"
                oriented = []
                for name in columns:
                    x = z[name][keep] if name in ("lvol", "trpct") else z[f"s_{name}"][keep]
                    raw = dartsad.auc(y, x)
                    inside = dartsad.strata_auc(y, x, strata)
                    # Each column is oriented by its own raw sign, so a column
                    # that ranks the label downwards is not reported as 0.3.
                    inside = inside if raw > 0.5 else 1 - inside
                    oriented.append(inside)
                    line += f"{max(raw, 1 - raw):>9.3f}/{inside:>8.3f}"
                print(line, flush=True)
                inside_by_group.setdefault(group, []).append((symbol, np.array(oriented)))
            print(
                "\n    within-strata AUC by family, and how many instruments the column beats\n"
                "    the incumbent `lvol` on - the only comparison that is not free:"
            )
            head = f"    {'family':<46}{'feeds':>6}"
            for name in columns:
                head += f"{name:>12}"
            print(head)
            for group, got in inside_by_group.items():
                mat = np.array([row[1] for row in got])
                line = f"    {group:<46}{len(got):>6}"
                for j, name in enumerate(columns):
                    beat = int((mat[:, j] > mat[:, 0]).sum())
                    line += f"{np.nanmean(mat[:, j]):>8.3f}/{beat:<3}"
                print(line)

        print(f"\n{'-' * 118}\n  Q1b  forward log realised variance over 20 bars: out-of-sample R2")
        print(
            "    the regression frame statespace-anomaly.md left open: forecasting the LEVEL of\n"
            "    log variance, where a better filter was worth +0.21 to +0.24 R2 and classifying a\n"
            "    4x bar was worth nothing. Baseline is llevel+lvol+trpct+volvol - the level is in\n"
            "    it because lvol and trpct are both scale-free and a baseline of those two alone\n"
            "    read 0.0221 against 0.4 or more with the level."
        )
        print(
            f"    {'instrument':<24}{'n test':>9}{'base R2':>10}{'+scores':>10}{'delta':>9}"
            f"{'scores only':>13}{'+shuffled':>11}"
        )
        for symbol, group, z in cells(featset, interval):
            keep = test_mask(z) & np.isfinite(z["fwd_logrv"])
            tr = np.zeros(len(keep), bool)
            tr[1500 + WINDOW : int(z["train_end"])] = True
            for name in SCORERS:
                tr &= np.isfinite(z[f"s_{name}"]) & np.isfinite(z[f"shuf_{name}"])
                keep &= np.isfinite(z[f"shuf_{name}"])
            # Rebuilt from the stored true range through `dartsad.log_level`,
            # the same function `geometry` uses, rather than stored twice.
            llevel = dartsad.log_level(z["tr"])
            tr &= np.isfinite(z["fwd_logrv"]) & np.isfinite(llevel) & np.isfinite(z["volvol"])
            if keep.sum() < 2_000 or tr.sum() < 2_000:
                continue
            y = z["fwd_logrv"]
            base = np.column_stack([llevel, z["lvol"], z["trpct"], z["volvol"]])
            scores = np.column_stack([z[f"s_{name}"] for name in SCORERS])
            shuf = np.column_stack([z[f"shuf_{name}"] for name in SCORERS])
            r2_base = dartsad.ols_r2(base[tr], y[tr], base[keep], y[keep])
            r2_both = dartsad.ols_r2(
                np.column_stack([base, scores])[tr], y[tr], np.column_stack([base, scores])[keep], y[keep]
            )
            r2_only = dartsad.ols_r2(scores[tr], y[tr], scores[keep], y[keep])
            r2_shuf = dartsad.ols_r2(
                np.column_stack([base, shuf])[tr], y[tr], np.column_stack([base, shuf])[keep], y[keep]
            )
            print(
                f"    {symbol:<24}{keep.sum():>9,}{r2_base:>10.4f}{r2_both:>10.4f}"
                f"{r2_both - r2_base:>+9.4f}{r2_only:>13.4f}{r2_shuf - r2_base:>+11.4f}",
                flush=True,
            )

        print(f"\n{'=' * 118}\nQ2  CLUSTERING THE SCORES - {featset}, k={STATES}")
        print(
            "    NMI against deciles of trpct says whether the states are volatility bins with\n"
            "    new names. 'shuffled' is the same clustering on whole-bar-shuffled features:\n"
            "    NMI is biased upward by the cell count, so that column is the baseline."
        )
        print(
            "    The last four columns are the decisive ones: the state label's own AUC for the\n"
            "    two risk targets, raw and inside trpct deciles. A state that is a volatility bin\n"
            "    ranks well raw and at 0.5 inside the strata of the bin it is a copy of."
        )
        print(
            f"    {'instrument':<24}{'shares':>26}{'mean trpct by state':>26}"
            f"{'NMI':>7}{'shuf':>7}{'shock':>16}{'vol top third':>16}"
        )
        labelled = {}
        for symbol, group, z in cells(featset, interval):
            matrix = standardise({n: z[f"s_{n}"] for n in SCORERS}, int(z["train_end"]))
            states, _ = cluster(matrix, int(z["train_end"]))
            labelled[symbol] = (group, states, z)
            keep = test_mask(z) & (states >= 0)
            if keep.sum() < 2_000:
                continue
            trdec = np.clip((z["trpct"][keep] * 10).astype(int), 0, 9)
            shares = "/".join(f"{(states[keep] == s).mean():.2f}" for s in range(STATES))
            means = "/".join(
                f"{z['trpct'][keep][states[keep] == s].mean():.2f}" for s in range(STATES)
            )
            shuf_matrix = standardise({n: z[f"shuf_{n}"] for n in SCORERS}, int(z["train_end"]))
            shuf_states, _ = cluster(shuf_matrix, int(z["train_end"]))
            sk = keep & (shuf_states >= 0)
            shuf_nmi = dartsad.nmi(
                shuf_states[sk], np.clip((z["trpct"][sk] * 10).astype(int), 0, 9)
            )
            # The state label is categorical, so it is scored as the forward
            # rate it implies on the TRAIN block - a monotone score with no
            # future in it - rather than as its own integer, which would make
            # the AUC depend on the arbitrary ordering of the states.
            scored = []
            for target in ("shock", "vol"):
                if target == "shock":
                    y = z["y_shock"]
                else:
                    cut = np.nanquantile(z["fwd_logrv"][keep], 2 / 3)
                    y = z["fwd_logrv"] > cut
                fit = np.zeros(len(states), bool)
                fit[1500 + WINDOW : int(z["train_end"])] = True
                fit &= states >= 0
                rate = np.array(
                    [
                        y[fit & (states == s)].mean() if (fit & (states == s)).sum() > 50 else np.nan
                        for s in range(STATES)
                    ]
                )
                proxy = np.where(states[keep] >= 0, rate[np.maximum(states[keep], 0)], np.nan)
                raw = dartsad.auc(y[keep], proxy)
                inside = dartsad.strata_auc(y[keep], proxy, z["trpct"][keep])
                scored.append(f"{max(raw, 1 - raw):.3f}/{(inside if raw > 0.5 else 1 - inside):.3f}")
            print(
                f"    {symbol:<24}{shares:>26}{means:>26}"
                f"{dartsad.nmi(states[keep], trdec):>7.3f}{shuf_nmi:>7.3f}"
                f"{scored[0]:>16}{scored[1]:>16}",
                flush=True,
            )

        print(f"\n{'=' * 118}\nQ3  STATE TRANSITIONS - {featset}, de-overlapped at stride {WINDOW}")
        print(
            "    stay = share of consecutive disjoint observations in the same state; indep = what\n"
            "    the same marginals give. p is a label permutation (marginals held exactly).\n"
            "    Three nulls, each through the SAME clustering on the SAME bar geometry.\n"
            "    'shuf' shuffles whole bars: the marginals are exact and all order is gone, so it\n"
            "    is the i.i.d. control. 'block' shuffles 200-bar blocks: volatility clustering\n"
            "    survives inside a block and the long-range order does not, so it is the\n"
            "    volatility-matched control - the one that says whether a persistent state is more\n"
            "    than volatility clustering. 'trpct' is QUARTILES OF THE INCUMBENT through the same\n"
            "    machinery with no darts in it at all: if it reads the same excess, the scorers\n"
            "    added nothing. And the Deriv Volatility rows hold sigma constant by publication."
        )
        print(
            f"    {'instrument':<24}{'obs':>7}{'stay':>8}{'indep':>8}{'excess':>9}"
            f"{'chi2':>10}{'p':>8}{'shuf':>8}{'block':>8}{'trpct':>8}{'trpct p':>9}"
        )
        for symbol, (group, states, z) in labelled.items():
            keep = test_mask(z) & (states >= 0)
            if keep.sum() < 2_000:
                continue
            idx = dartsad.deoverlap(len(states), WINDOW, int(np.flatnonzero(keep)[0]))
            idx = idx[keep[idx]]
            seq = states[idx]
            counts = dartsad.transition_counts(seq, STATES)
            stay, indep = dartsad.stay_share(counts)
            chi2 = dartsad.chi2_independence(counts)
            null = dartsad.label_permutation_chi2(seq, STATES, 500, rng)
            p = float((null >= chi2).mean())
            nulls = []
            for prefix in ("shuf", "block"):
                if f"{prefix}_{SCORERS[0]}" not in z.files:
                    nulls.append(float("nan"))
                    continue
                null_matrix = standardise(
                    {n: z[f"{prefix}_{n}"] for n in SCORERS}, int(z["train_end"])
                )
                null_states, _ = cluster(null_matrix, int(z["train_end"]))
                nidx = idx[null_states[idx] >= 0]
                nstay, nindep = dartsad.stay_share(
                    dartsad.transition_counts(null_states[nidx], STATES)
                )
                nulls.append(nstay - nindep)
            vol_seq = np.digitize(z["trpct"][idx], [0.25, 0.5, 0.75])
            vcounts = dartsad.transition_counts(vol_seq, STATES)
            vstay, vindep = dartsad.stay_share(vcounts)
            vnull = dartsad.label_permutation_chi2(vol_seq, STATES, 500, rng)
            vp = float((vnull >= dartsad.chi2_independence(vcounts)).mean())
            print(
                f"    {symbol:<24}{len(seq):>7,}{stay:>8.3f}{indep:>8.3f}{stay - indep:>+9.3f}"
                f"{chi2:>10.1f}{p:>8.3f}{nulls[0]:>+8.3f}{nulls[1]:>+8.3f}"
                f"{vstay - vindep:>+8.3f}{vp:>9.3f}",
                flush=True,
            )

        print(f"\n{'-' * 118}\n  Q3b  does a transition precede anything? forward {WINDOW} bars, in trailing mean |r| units")
        print(
            "    signed = sum of returns over the next disjoint window / (base * sqrt(window));\n"
            "    size = sum |r| / (base * window). 90% day-block intervals, BH over every cell."
        )
        print(
            "    EXCESS is the cell's mean minus the instrument's own unconditional mean over the\n"
            "    same observations. Without it the table measures the sample's drift: the most\n"
            "    populous state inherits whichever way the pair went, and reads as a signal."
        )
        rows = []
        for symbol, (group, states, z) in labelled.items():
            keep = test_mask(z) & (states >= 0)
            if keep.sum() < 2_000:
                continue
            idx = dartsad.deoverlap(len(states), WINDOW, int(np.flatnonzero(keep)[0]))
            idx = idx[keep[idx]]
            r = np.nan_to_num(z["r"])
            fwd_signed = np.array([r[t + 1 : t + 1 + WINDOW].sum() for t in idx]) / (
                z["base"][idx] * np.sqrt(WINDOW)
            )
            fwd_size = np.array([np.abs(r[t + 1 : t + 1 + WINDOW]).sum() for t in idx]) / (
                z["base"][idx] * WINDOW
            )
            day = z["ts"][idx] // 86_400
            seq = states[idx]
            drift = float(fwd_signed.mean())
            for a in range(STATES):
                for b in range(STATES):
                    pick = np.zeros(len(seq), bool)
                    pick[1:] = (seq[:-1] == a) & (seq[1:] == b)
                    if pick.sum() < 60:
                        continue
                    mean, low, high, p = dartsad.day_block_ci(
                        fwd_signed[pick] - drift, day[pick], 600, rng
                    )
                    rows.append(
                        (
                            symbol,
                            group,
                            a,
                            b,
                            int(pick.sum()),
                            float(fwd_signed[pick].mean()),
                            mean,
                            low,
                            high,
                            float(fwd_size[pick].mean() - fwd_size.mean()),
                            p,
                        )
                    )
        if rows:
            clear = sum(1 for row in rows if row[7] > 0 or row[8] < 0)
            survive = dartsad.bh(np.array([row[10] for row in rows]), 0.05)
            print(
                f"    {len(rows)} (instrument, from, to) cells; {clear} have a 90% interval on the\n"
                f"    excess clear of zero ({0.1 * len(rows):.1f} expected by chance); "
                f"{int(survive.sum())} survive Benjamini-Hochberg at q=0.05"
            )
            print(
                f"    {'instrument':<24}{'from->to':>10}{'n':>7}{'signed':>9}{'excess':>9}"
                f"{'90% low':>10}{'90% high':>10}{'size excess':>13}{'BH':>5}"
            )
            order = sorted(range(len(rows)), key=lambda i: -abs(rows[i][6]))[:20]
            for i in order:
                row = rows[i]
                print(
                    f"    {row[0]:<24}{f'{row[2]}->{row[3]}':>10}{row[4]:>7,}{row[5]:>+9.3f}"
                    f"{row[6]:>+9.3f}{row[7]:>+10.3f}{row[8]:>+10.3f}{row[9]:>+13.3f}"
                    f"{('yes' if survive[i] else '-'):>5}"
                )

        print(f"\n{'-' * 118}\n  Q3c  the cost that any of this would have to clear")
        print(
            f"    cost in R is round_trip / stop at a {STOP_ATR:.0f}xATR(14) stop. spread is in "
            "POINTS in the bar file;\n    the point is measured as the quoted price grid. The bar "
            "field is the BROKER'S QUOTED SPREAD\n    and carries no commission: scalp_cost.py read "
            "0.00011 of round trip on EURUSD at 15m from\n    the terminal against 0.00003 here, so "
            f"the dearer column below ({COST_MARGIN:.0f}x) is the one a verdict uses."
        )
        print(
            f"    {'instrument':<24}{'tick':>12}{'spread pts':>12}{'round trip':>13}"
            f"{'ATR14':>12}{'cost/R':>9}{f'x{COST_MARGIN:.0f}':>9}"
        )
        for symbol, (group, states, z) in labelled.items():
            keep = test_mask(z)
            if keep.sum() < 2_000:
                continue
            # Recomputed from the stored closes rather than read back: the
            # estimator was the median gap when these npz files were written,
            # which read BTCUSD's grid as 0.601 against a true 0.01.
            tick = dartsad.tick_size(z["close"])
            pts = float(z["spread_pts"])
            atr = float(np.nanmedian(_atr_px(z)[keep]))
            trip = pts * tick
            print(
                f"    {symbol:<24}{tick:>12.8f}{pts:>12.1f}{trip:>13.8f}{atr:>12.6f}"
                f"{trip / (STOP_ATR * atr):>9.3f}{COST_MARGIN * trip / (STOP_ATR * atr):>9.3f}"
            )

        print(f"\n{'-' * 118}\n  Q3d  the barrier race from each transition, net of that cost")
        print(
            f"    1:1 at a {STOP_ATR:.0f}xATR stop, {MAX_HOLD}-bar cap, stop wins ties, one position\n"
            "    at a time. The driftless null is 0.500 of races won; break-even is (1+cost)/2.\n"
            "    TWIN is the same number of entries drawn at random from the same de-overlapped\n"
            "    observations, same side: it carries the sample's drift and the duty cycle, and a\n"
            "    cell that does not beat its own twin has shown nothing. Net is at the dearer cost."
        )
        print(
            f"    {'instrument':<24}{'from->to':>10}{'side':>6}{'n':>6}{'won':>8}"
            f"{'gross R':>10}{'net R':>9}{'90% low':>10}{'90% high':>10}{'twin net':>10}"
        )
        traded = []
        for symbol, (group, states, z) in labelled.items():
            if not group.startswith(("fx", "metal", "crypto")):
                continue
            keep = test_mask(z) & (states >= 0)
            if keep.sum() < 2_000:
                continue
            atr = _atr_px(z)
            cost = (
                COST_MARGIN
                * float(z["spread_pts"])
                * dartsad.tick_size(z["close"])
                / (STOP_ATR * np.nanmedian(atr[keep]))
            )
            idx = dartsad.deoverlap(len(states), WINDOW, int(np.flatnonzero(keep)[0]))
            idx = idx[keep[idx]]
            seq = states[idx]
            for a in range(STATES):
                for b in range(STATES):
                    pick = np.zeros(len(seq), bool)
                    pick[1:] = (seq[:-1] == a) & (seq[1:] == b)
                    if pick.sum() < 60:
                        continue
                    for side, tag in ((1, "long"), (-1, "short")):
                        took, got = dartsad.race(
                            z["high"],
                            z["low"],
                            z["open"],
                            z["close"],
                            STOP_ATR * atr,
                            idx[pick],
                            side,
                            MAX_HOLD,
                        )
                        if len(got) < 60:
                            continue
                        mean, low, high, _ = dartsad.day_block_ci(
                            got - cost, z["ts"][took] // 86_400, 600, rng
                        )
                        twins = []
                        for seed in range(5):
                            draw = np.random.default_rng(seed).choice(
                                idx, size=int(pick.sum()), replace=False
                            )
                            _, tw = dartsad.race(
                                z["high"],
                                z["low"],
                                z["open"],
                                z["close"],
                                STOP_ATR * atr,
                                np.sort(draw),
                                side,
                                MAX_HOLD,
                            )
                            if len(tw):
                                twins.append(tw.mean() - cost)
                        traded.append(
                            (
                                symbol,
                                a,
                                b,
                                tag,
                                len(got),
                                float((got > 0).mean()),
                                float(got.mean()),
                                mean,
                                low,
                                high,
                                float(np.mean(twins)) if twins else float("nan"),
                            )
                        )
        for row in sorted(traded, key=lambda r: -r[7])[:16]:
            print(
                f"    {row[0]:<24}{f'{row[1]}->{row[2]}':>10}{row[3]:>6}{row[4]:>6,}"
                f"{row[5]:>8.3f}{row[6]:>+10.3f}{row[7]:>+9.3f}{row[8]:>+10.3f}"
                f"{row[9]:>+10.3f}{row[10]:>+10.3f}"
            )
        if traded:
            net = np.array([r[7] for r in traded])
            clear = sum(1 for r in traded if r[8] > 0)
            beat = sum(1 for r in traded if r[7] > r[10])
            print(
                f"    {len(traded)} (instrument, transition, side) cells: "
                f"{int((net > 0).sum())} positive net, {clear} with a 90% lower bound above zero "
                f"({0.05 * len(traded):.1f} expected at 5%),\n    {beat} beat their own random "
                f"twin ({0.5 * len(traded):.0f} expected by chance)"
            )


def _atr_px(z) -> np.ndarray:
    """ATR(14) in price, from the bar's own true range rather than scaled from a shorter clock.

    `scalping.md` reads ATR off bars aggregated at the clock being traded for
    exactly this reason: volatility clusters, so sqrt-scaling a 1-minute ATR
    makes short clocks look dearer than they are.
    """
    import pandas as pd

    high, low, close = z["high"], z["low"], z["close"]
    prev = np.r_[np.nan, close[:-1]]
    tr = np.nanmax(
        np.column_stack([high - low, np.abs(high - prev), np.abs(low - prev)]), axis=1
    )
    return pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()


def phase_power():
    """Plant a two-state regime, sweep its strength, and say where the test stops seeing it.

    Two sweeps. The volatility sweep multiplies state 1's sigma by `lam`; the
    drift sweep gives state 1 a drift of `mu` sigmas a bar at equal volatility.
    A null arrives at `lam = 1.0, mu = 0.0` in both, which is the row that says
    whether the harness invents states out of an i.i.d. series.
    """
    n = int(os.environ.get("POWER_BARS", "20000"))
    rng = np.random.default_rng(11)
    plan = []
    for lam in (1.0, 1.05, 1.1, 1.25, 1.5, 2.0, 3.0):
        plan.append(("vol", lam, 0.0, 0.95))
    for mu in (0.0, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0):
        plan.append(("drift", 1.0, mu, 0.95))
    for stay in (0.5, 0.8, 0.9, 0.98, 0.998):
        plan.append(("stay", 2.0, 0.0, stay))
    workers = int(os.environ.get("WORKERS", "21"))
    print(
        f"planted two-state regimes, {n:,} bars, k=2 on the score vector, "
        f"de-overlapped at {WINDOW}\n"
    )
    print(
        f"  {'sweep':>7}{'lam':>6}{'mu':>6}{'stay':>7}{'obs':>7}{'ARI vs truth':>14}"
        f"{'stay':>8}{'indep':>8}{'excess':>9}{'perm p':>9}{'signed gap':>12}{'gap 90%':>22}"
        f"{'gap in R':>10}"
    )
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_power_cell, n, *cell): cell for cell in plan}
        done = {}
        for future in as_completed(futures):
            done[futures[future]] = future.result()
    for cell in plan:
        got = done.get(cell)
        if got is None:
            continue
        sweep, lam, mu, stay = cell
        print(
            f"  {sweep:>7}{lam:>6.2f}{mu:>6.2f}{stay:>7.3f}{got['obs']:>7,}"
            f"{got['ari']:>14.3f}{got['stay']:>8.3f}{got['indep']:>8.3f}"
            f"{got['stay'] - got['indep']:>+9.3f}{got['p']:>9.3f}{got['gap']:>+12.3f}"
            f"   [{got['low']:+.3f}, {got['high']:+.3f}]{got['gap_r']:>+10.3f}",
            flush=True,
        )
    _ = rng


def _power_cell(n, sweep, lam, mu, stay):
    o, h, lo, c, truth = dartsad.plant(n, lam, stay, mu=mu, seed=hash((sweep, lam, mu, stay)) % 2**31)
    g = dartsad.geometry(o, h, lo, c)
    features = dartsad.scaled_features(g)
    train_end = int(TRAIN * n)
    scores = run_scorers(features, train_end)
    matrix = standardise(scores, train_end)
    states, _ = cluster(matrix, train_end, k=2)
    keep = np.zeros(n, bool)
    keep[max(train_end, 1500 + WINDOW) :] = True
    keep[n - 25 :] = False
    keep &= states >= 0
    for name in SCORERS:
        keep &= np.isfinite(scores[name])
    idx = dartsad.deoverlap(n, WINDOW, int(np.flatnonzero(keep)[0]))
    idx = idx[keep[idx]]
    seq = states[idx]
    counts = dartsad.transition_counts(seq, 2)
    share, indep = dartsad.stay_share(counts)
    chi2 = dartsad.chi2_independence(counts)
    rng = np.random.default_rng(3)
    null = dartsad.label_permutation_chi2(seq, 2, 500, rng)
    r = np.nan_to_num(g["r"])
    fwd = np.array([r[t + 1 : t + 1 + WINDOW].sum() for t in idx]) / (
        g["base"][idx] * np.sqrt(WINDOW)
    )
    day = idx // 96
    # The same gap in R, so the power curve can be read against a cost rather
    # than against a unit nobody trades: the forward price move over the window
    # divided by the 2xATR stop a trade would use.
    prev = np.r_[np.nan, c[:-1]]
    true_range = np.nanmax(
        np.column_stack([h - lo, np.abs(h - prev), np.abs(lo - prev)]), axis=1
    )
    import pandas as pd

    atr = pd.Series(true_range).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    fwd_r = (c[idx] * fwd * g["base"][idx] * np.sqrt(WINDOW)) / (STOP_ATR * atr[idx])

    gap, low, high, gap_r = float("nan"), float("nan"), float("nan"), float("nan")
    if (seq == 1).sum() > 30 and (seq == 0).sum() > 30:
        # The gap is a difference of two means, so it is bootstrapped as one
        # quantity: an unbiased estimator of mean(hot) - mean(cold) that can be
        # resampled by day is fwd weighted by +1/share(hot) or -1/share(cold).
        hot, cold = max((seq == 1).mean(), 1e-9), max((seq == 0).mean(), 1e-9)
        gap, low, high, _ = dartsad.day_block_ci(
            np.where(seq == 1, fwd / hot, -fwd / cold), day, 400, rng
        )
        gap_r = float(fwd_r[seq == 1].mean() - fwd_r[seq == 0].mean())
    return {
        "obs": len(seq),
        "ari": dartsad.ari(truth[idx], np.maximum(seq, 0)),
        "stay": share,
        "indep": indep,
        "p": float((null >= chi2).mean()),
        "gap": gap,
        "low": low,
        "high": high,
        "gap_r": gap_r,
    }


def phase_leak():
    """darts' `window_agg=True` default against `False`, on one planted spike.

    The probe that justifies `window_agg=False` everywhere else in this file:
    the default raises the score **before** the spike, which is a look-ahead of
    `window - 1` bars into any forward-looking label.
    """
    import pandas as pd
    from darts import TimeSeries
    from darts.ad.scorers import KMeansScorer, WassersteinScorer

    n, spike, window = 40, 20, 5
    values = np.zeros(n)
    values[spike] = 10.0
    idx = pd.date_range("2024-01-01", periods=n, freq="15min")
    series = TimeSeries.from_times_and_values(idx, values)
    print(f"one spike at bar {spike}, window {window}; bars {spike - 5}..{spike + 4}\n")
    for name, build in (
        ("KMeansScorer", lambda agg: KMeansScorer(window=window, k=2, window_agg=agg, random_state=0)),
        ("WassersteinScorer", lambda agg: WassersteinScorer(window=window, window_agg=agg)),
    ):
        for agg in (True, False):
            scorer = build(agg)
            scorer.fit(series)
            got = scorer.score(series)
            column = np.full(n, np.nan)
            column[window - 1 : window - 1 + len(got)] = np.asarray(got.values()).ravel()
            cut = column[spike - 5 : spike + 5]
            before = np.nanmax(column[spike - 4 : spike]) - np.nanmin(column[: spike - 4])
            print(
                f"  {name:<20} window_agg={str(agg):<6} "
                + " ".join(f"{v:6.2f}" for v in cut)
                + f"   rise before the spike: {before:+.2f}"
            )
    print(
        "\n  A positive rise before the spike is a look-ahead of window-1 bars. darts'\n"
        "  default is True, so a forward label scored against it reads its own answer."
    )


def main() -> int:
    phase = os.environ.get("PHASE", "report")
    {"score": phase_score, "report": phase_report, "power": phase_power, "leak": phase_leak}[phase]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
