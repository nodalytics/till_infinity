"""Does an impulse carry anything beyond the volatility state it is part of?

    ./.secrets/lab.sh run research/harness/impulse_vol.py \
        BASE=15m SEQLAB=$HOME/till_infinity/data/seqlab OUT=$HOME/till_infinity/out/impulse_vol.csv

## The claim, and the ones it is distinct from

An impulse is a bar whose move is large **relative to the volatility forecast
made before it**. The directional reading of that - continue, or fade - is
closed here three times over: `fractal-twins.md` found shapes call volatility
and not direction, `bos-predict.md` found a break of structure carries no side
beyond the geometry of the two levels, and `findings.md` records a direction
gate that finds a *planted* drift at z +2.90 and still earns 2% of a spread.

So the claim tested is not "impulses predict direction". It is:

> **Conditional on the volatility state at the time, does an impulse say
> anything the volatility state does not already say?**

That is a question the closed studies could not answer: they compared a shape
against a walk, never an impulse against a *volatility-and-hour-matched bar of
the same instrument*.

It is asked of two channels, and the distinction is the point:

* **the risk channel** - forward realised volatility. This desk already
  forecasts risk, so a reading here confirms the known rather than opening
  anything. Its job in this study is to be the **positive control**: it is
  measured on the same events, through the same estimator, with the same
  bootstrap, so a null on direction beside a strong reading on volatility is a
  null with demonstrated power rather than a blind test.
* **the direction channel** - the forward move signed by the impulse. This is
  the open question, and the sign-flip arm decides it.

## Four sub-questions, each a band of cells

| band | the question |
|---|---|
| `all` | an impulse, wherever it lands |
| `lo` | a **squeeze** followed by an impulse - the state was in its lowest trailing third |
| `hi` | an impulse arriving in **already-high** volatility |
| `slow_lo` / `slow_hi` | the **multi-timeframe** version: a 4-hour squeeze (or expansion) with a 15-minute impulse |

Whether volatility rises or falls afterwards is read from the same rows at
four horizons: `rv` is forward volatility in units of the forecast made before
the event, so `rv = 1` is "exactly what the forecast said" and the slope across
`k` is the decay.

## The nulls, which are the study

1. **The sign-flip surrogate.** Keep every `|return|` in its original order
   and randomise the signs. The volatility path - the clustering, the squeeze,
   the expansion - survives **exactly**; direction does not. Any directional
   effect that appears here is volatility, not skill.

   It is applied analytically rather than by re-running the harness on a
   flipped series, which makes it cheap enough to run 200 times per cell
   instead of once. With `r'[t] = |r[t]| * s[t]`, the forecast volatility, the
   state and the event set are **identical** to the real arm, because all
   three are functions of `|r|` alone; the continuation of event `i` is
   `s[i] * sum_{t in (i, i+k]} |r[t]| s[t] / vol[i]`. So the surrogate is not
   an approximation of the arm - it is the arm, 200 draws of it, and the real
   mean is reported as its rank inside that null.

2. **The volatility-and-hour-matched placebo.** Non-impulse bars from the same
   instrument, the same volatility decile, the same hour of day and the same
   band. If the impulse reads like its own stratum, the impulse is a label for
   the stratum.

3. **The iid-shuffle arm**, which is the sign-flip's opposite number for the
   risk channel. A permutation of the returns keeps the marginal distribution
   - the fat tails, every `|return|` - and destroys the clustering. The
   sign-flip arm is silent about volatility by construction, so without this
   there is no null for the risk channel at all.

4. **Deriv synthetics, for one named property each.** They are real markets
   here, not a general control - `findings.md` sets that rule - so each is
   carried for the property its published generator fixes and nothing else:
   `Volatility 25/75 Index` are generated at **constant volatility**, so there
   is no clustering in them to find; `Step Index` is a fixed step; and
   `Jump 75 Index` has **fat tails without clustering**, which is the one
   control that separates "the harness found volatility memory" from "the
   harness manufactured a reading out of a heavy tail".

5. **Day-block bootstrap**, because impulses cluster in days and an ordinary
   standard error is far too narrow.

6. **A discovery / confirmation split** by time, reported for every cell.

## Power, before any null is believed

A drift of known size is planted on the bar after each impulse and swept over
four sizes, so the write-up can say where the test goes blind rather than
claiming a null it cannot support. The planted arm is scored against the same
sign-flip null as the real arm, so "detected" means the same thing in both.

## What is deliberately held fixed

The event set does not change with the horizon: every cell requires the
longest forward window to exist, so the four horizons are read off **the same
events** and their differences are about the horizon rather than about which
bars survived.
"""

from __future__ import annotations

import os
import sys
from multiprocessing import Pool

import numpy as np
import pandas as pd

#: **The cache is read here rather than through `spikerisk`.** That module
#: imports scikit-learn at module scope and this harness needs none of it, so
#: importing it makes the run depend on an ML stack it never calls - which is
#: how it failed on the lab the first time.
def _seqlab(ticker: str, interval: str) -> pd.DataFrame:
    """`$SEQLAB/<TICKER>.<interval>.npz`, oldest first, bars repaired to
    contain their own open and close - the same contract `spikerisk.load`
    gives for this venue."""
    root = os.environ.get("SEQLAB", ".data/seqlab")
    z = np.load(f"{root}/{ticker}.{interval}.npz")
    df = pd.DataFrame({
        "ts": z["time"].astype(np.int64),
        "open": z["open"], "high": z["high"], "low": z["low"], "close": z["close"],
        # Points, not price. Misreading this column as price once put a 476%
        # round trip on EURUSD and reordered every instrument by cost.
        "spread": z["spread"] if "spread" in z.files else np.zeros(len(z["time"])),
    })
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["high"] = df[["open", "high", "close"]].max(axis=1)
    df["low"] = df[["open", "low", "close"]].min(axis=1)
    return df


BASE = os.environ.get("BASE", "15m")
#: Traded markets.
TRADED = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD", "XAGUSD", "BTCUSD")
#: Deriv synthetics, each carried for one named property of its generator.
#: They are real markets, not a general null - see the docstring.
SYNTH = ("Volatility 75 Index", "Volatility 25 Index", "Step Index", "Jump 75 Index")
#: The property each is here to control for, written down so a reading cannot
#: later be credited to a property nobody claimed.
PROPERTY = {
    "Volatility 75 Index": "constant volatility: no clustering to find",
    "Volatility 25 Index": "constant volatility: no clustering to find",
    "Step Index": "fixed step: neither clustering nor a tail",
    "Jump 75 Index": "fat tails without clustering",
}

#: `point` for each symbol, read once from the bridge's
#: `GET /api/v1/symbols/info/{symbol}` on 2026-11-05 and written down, so the
#: cost line does not need a live terminal to re-run.
#:
#: **The spread column is in points, not price**: `price = points * point`.
#: Reading it as price once put a 476% round trip on EURUSD and reordered
#: every instrument by cost, so the conversion is spelled out here rather than
#: assumed anywhere downstream.
POINT: dict[str, float] = {
    "EURUSD": 1e-05, "GBPUSD": 1e-05, "USDJPY": 0.001, "AUDUSD": 1e-05,
    "USDCAD": 1e-05, "XAUUSD": 0.01, "XAGUSD": 0.001, "BTCUSD": 0.001,
    "Volatility 75 Index": 0.01, "Volatility 25 Index": 0.001,
    "Step Index": 0.1, "Jump 75 Index": 0.01,
}

#: The spread the terminal **quoted** for each symbol on 2026-11-05, in
#: points. It is carried beside the per-bar `spread` column because the two
#: disagree by nearly an order of magnitude on FX - the stored column reads
#: about a point on EURUSD where the live book reads nine - and a cost
#: conclusion drawn from the cheaper of the two is the one that lets a
#: finding through. Every cost statement here is made at the quoted spread.
SPREAD_POINTS = {
    "EURUSD": 9, "GBPUSD": 11, "USDJPY": 9, "AUDUSD": 7, "USDCAD": 10,
    "XAUUSD": 16, "XAGUSD": 30, "BTCUSD": 18_424, "Volatility 75 Index": 1_343,
    "Volatility 25 Index": 331, "Step Index": 1, "Jump 75 Index": 180,
}

#: The hours of the day the event set drops in the `masked` arm, and the bars
#: dropped after a session gap. Both are `fx-reversal.md`'s mask, reused
#: rather than invented: the daily rollover is a quote artefact this desk has
#: already measured, and a bar that spans a gap is not a 15-minute bar.
ROLLOVER_HOURS = (20, 21, 22, 23)
GAP_SECONDS = 3_600
GAP_BARS = 4

#: Known before the bar: the forecast is shifted, so an impulse is large
#: against what could have been said beforehand and not against itself.
VOL_SPAN = 60
#: The trailing window the state is ranked in. A global quantile would use the
#: future to label the past.
STATE_WIN, STATE_MIN = 500, 200
#: Bins of the volatility state the placebo is matched inside, alongside the
#: hour. Twenty rather than ten because the matching is the only thing holding
#: back a bias with a known direction: selecting on `|r| / vol` tilts towards
#: a **small denominator**, so an impulse sits at the low end of whatever
#: bucket it is matched in and its forward volatility reads high for that
#: reason alone. On generated iid returns the residual is +0.01 to +0.03 at
#: ten bins. It does not vanish at twenty, which is why the shuffle arm is
#: reported beside every real reading as the floor rather than assumed away.
STATE_BINS = 20
#: The slow leg of the multi-timeframe arm: 4-hour calendar bins, so a session
#: gap is a short bin rather than a fabricated return.
SLOW_SECONDS = 4 * 3_600
SLOW_SPAN = 60
HORIZONS = (1, 4, 12, 48)
TRIGGERS = (2.0, 3.0, 4.0)
BANDS = ("all", "lo", "hi", "slow_lo", "slow_hi")
HALVES = (0, 1, 2)
#: Planted drift sizes, in units of the forecast volatility.
PLANTED = (0.02, 0.05, 0.10, 0.20)
#: Sign-flip surrogates per cell, and day-block bootstrap draws per statistic.
NFLIP = 200
BOOT = 1_000
#: Under this many events the prior is noise and the row is reported as such
#: rather than dropped - a dropped cell is invisible, and an earlier run of
#: this harness wrote 0 cells and still exited 0.
MIN_EVENTS = 100
SEED = 20261105


def frame(symbol: str) -> pd.DataFrame | None:
    try:
        df = _seqlab(symbol, BASE)
    except Exception as exc:  # a symbol the cache does not hold
        print(f"  {symbol}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    if df is None or len(df) < 20_000:
        print(f"  {symbol}: {0 if df is None else len(df)} bars, too few", file=sys.stderr)
        return None
    close = df.close.to_numpy(float)
    out = pd.DataFrame({"ts": df.ts.to_numpy(), "close": np.log(close)})
    out["r"] = out.close.diff()
    out["cost"] = df.spread.to_numpy(float) * POINT.get(symbol, np.nan) / close
    out["quoted"] = SPREAD_POINTS.get(symbol, np.nan) * POINT.get(symbol, np.nan) / close
    return out.dropna(subset=["r"]).reset_index(drop=True)


def ewma_abs(r: np.ndarray, span: int) -> np.ndarray:
    """EWMA of `|r|`, shifted by one: a forecast that saw its own bar is not a
    forecast."""
    s = pd.Series(np.abs(r))
    return s.ewm(span=span, min_periods=span).mean().shift(1).to_numpy()


def slow_state(r: np.ndarray, ts: np.ndarray) -> np.ndarray:
    """The 4-hour leg's volatility state, carried back onto the 15-minute bars.

    The slow return is the **sum of the fast returns inside a calendar bin**,
    never a difference of aligned closes: aligning first and differencing after
    turns every session gap into a fabricated one-bar return.

    No lag is needed on top. `slow_vol` is already shifted by one bin, so the
    rank at bin `j` is a function of bins up to `j-1` only, and a bar inside
    bin `j` may read it.
    """
    _, inv = np.unique(ts // SLOW_SECONDS, return_inverse=True)
    agg = np.bincount(inv, weights=r)
    vol = ewma_abs(agg, SLOW_SPAN)
    rank = pd.Series(vol).rolling(STATE_WIN, min_periods=STATE_MIN).rank(pct=True).to_numpy()
    return rank[inv]


def deseasoned(r: np.ndarray, ts: np.ndarray) -> np.ndarray:
    """Returns with the weekday x hour-of-day mean removed.

    The attribution arm for the direction channel. The sign-flip surrogate is
    a **generated** null and so has no daily cycle in it at all, which is the
    one thing it cannot rule out: if impulses at a given hour are
    systematically signed and that hour is systematically followed by drift -
    the rollover quote artefact being the known case here - then `side x
    forward move` is non-zero with nothing conditional about it. Subtracting
    the cell mean kills everything the calendar can do and leaves whatever is
    conditional on the impulse.

    It is an attribution, not a trading rule: the cell means are read from the
    whole sample, so this arm may only ever remove a reading, never create one.
    """
    when = pd.to_datetime(ts, unit="s", utc=True)
    cell = (when.dayofweek * 24 + when.hour).to_numpy()
    mean = np.bincount(cell, weights=r, minlength=7 * 24) / np.maximum(
        np.bincount(cell, minlength=7 * 24), 1)
    return r - mean[cell]


def tradable(ts: np.ndarray, hour: np.ndarray) -> np.ndarray:
    """The `masked` arm's event set: no rollover hour, and no bar close
    behind a session gap. `fx-reversal.md`'s mask, reused."""
    keep = ~np.isin(hour, ROLLOVER_HOURS)
    gap = np.flatnonzero(np.diff(ts, prepend=ts[0]) > GAP_SECONDS)
    for step in range(GAP_BARS):
        hit = gap + step
        keep[hit[hit < len(keep)]] = False
    return keep


def dress(r: np.ndarray, ts: np.ndarray) -> dict[str, np.ndarray]:
    vol = ewma_abs(r, VOL_SPAN)
    state = pd.Series(vol).rolling(STATE_WIN, min_periods=STATE_MIN).rank(pct=True).to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        z = r / vol
    return {
        "vol": vol,
        "z": z,
        "state": state,
        "slow": slow_state(r, ts),
        "hour": (pd.to_datetime(ts, unit="s", utc=True).hour).to_numpy(),
    }


def outcomes(r: np.ndarray, vol: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Forward signed move and forward volatility, both in units of the
    forecast made before the event, so they are comparable across instruments
    and across volatility states.

    Forward volatility is the **mean `|return|`** over the window, which is the
    unit the forecast itself is in. An RMS would be a different estimator
    divided by a MAD one, and their ratio moves with the shape of the tail -
    so the null would not be 1.
    """
    n = len(r)
    fwd = np.full(n, np.nan)
    rv = np.full(n, np.nan)
    cum = np.concatenate([[0.0], np.cumsum(np.nan_to_num(r))])
    cua = np.concatenate([[0.0], np.cumsum(np.abs(np.nan_to_num(r)))])
    i = np.arange(n - k)
    fwd[i] = (cum[i + 1 + k] - cum[i + 1]) / vol[i]
    rv[i] = (cua[i + 1 + k] - cua[i + 1]) / k / vol[i]
    return fwd, rv


def boot(day: np.ndarray, value: np.ndarray, rng) -> tuple[float, float, float, float]:
    """Day-block bootstrap: the mean, a 90% interval, and a two-sided p
    against zero. Resamples whole days because impulses cluster in them."""
    if len(value) == 0:
        return (np.nan,) * 4
    codes, inv = np.unique(day, return_inverse=True)
    tot = np.bincount(inv, weights=value, minlength=len(codes))
    num = np.bincount(inv, minlength=len(codes)).astype(float)
    picks = rng.integers(0, len(codes), size=(BOOT, len(codes)))
    means = tot[picks].sum(1) / num[picks].sum(1)
    side = min((means <= 0).mean(), (means >= 0).mean())
    return (
        float(value.mean()),
        float(np.quantile(means, 0.05)),
        float(np.quantile(means, 0.95)),
        float(min(1.0, max(2 * side, 1.0 / BOOT))),
    )


def boot_gap(day_a, val_a, day_b, val_b, rng) -> tuple[float, float, float, float]:
    """The same for a difference of two means over different bars.

    The two arms are resampled **independently** by day. They come from the
    same series and are positively dependent, so an independent resample
    overstates the variance of the difference: the interval is conservative,
    which is the direction a null wants to be wrong in.
    """
    if len(val_a) == 0 or len(val_b) == 0:
        return (np.nan,) * 4

    def draw(day, val):
        codes, inv = np.unique(day, return_inverse=True)
        tot = np.bincount(inv, weights=val, minlength=len(codes))
        num = np.bincount(inv, minlength=len(codes)).astype(float)
        picks = rng.integers(0, len(codes), size=(BOOT, len(codes)))
        return tot[picks].sum(1) / num[picks].sum(1)

    means = draw(day_a, val_a) - draw(day_b, val_b)
    side = min((means <= 0).mean(), (means >= 0).mean())
    return (
        float(val_a.mean() - val_b.mean()),
        float(np.quantile(means, 0.05)),
        float(np.quantile(means, 0.95)),
        float(min(1.0, max(2 * side, 1.0 / BOOT))),
    )


def matched(ok: np.ndarray, pool: np.ndarray, cell: np.ndarray, rng) -> np.ndarray:
    """Draw, for every impulse, a non-impulse bar from the same volatility
    bin, hour of day and band.

    Vectorised by shuffling the pool once and then sorting it stably by cell,
    so each cell's members arrive in random order and the first `need` of them
    is a draw without replacement. The obvious loop over pool members is
    `O(bars)` **per cell** and does not finish on eleven years of 15-minute
    bars.
    """
    want = np.bincount(cell[ok], minlength=cell.max() + 1)
    idx = np.flatnonzero(pool)
    if len(idx) == 0:
        return np.array([], dtype=int)
    idx = rng.permutation(idx)
    order = np.argsort(cell[idx], kind="stable")
    idx = idx[order]
    keys = cell[idx]
    starts = np.searchsorted(keys, np.arange(len(want)), side="left")
    ends = np.searchsorted(keys, np.arange(len(want)), side="right")
    take = [idx[s : s + min(int(w), e - s)] for w, s, e in zip(want, starts, ends, strict=True)
            if w > 0 and e > s]
    return np.concatenate(take) if take else np.array([], dtype=int)


def flip_null(absr, vol, cells, rng) -> dict[tuple, np.ndarray]:
    """200 sign-flip surrogates, as means per cell.

    `cells` maps a cell key to the event indices in it. The surrogate's
    continuation for event `i` is `s[i] * sum_{t in (i,i+k]} |r[t]| s[t] /
    vol[i]`, so the whole arm is two cumulative sums and a gather - the event
    set and the volatility path are unchanged by construction.
    """
    n = len(absr)
    out = {key: np.empty(NFLIP) for key in cells}
    a = np.nan_to_num(absr)
    for rep in range(NFLIP):
        s = rng.choice((-1.0, 1.0), size=n)
        cum = np.concatenate([[0.0], np.cumsum(a * s)])
        per_k = {}
        for k in HORIZONS:
            i = np.arange(n - k)
            cont = np.full(n, np.nan)
            cont[i] = s[i] * (cum[i + 1 + k] - cum[i + 1]) / vol[i]
            per_k[k] = cont
        for key, idx in cells.items():
            out[key][rep] = per_k[key[-1]][idx].mean()
    return out


def rank_p(real: float, null: np.ndarray) -> float:
    """Two-sided rank of the real mean inside its own sign-flip null."""
    if not np.isfinite(real) or len(null) == 0:
        return float("nan")
    centre = float(np.mean(null))
    hits = int(np.sum(np.abs(null - centre) >= abs(real - centre)))
    return (1 + hits) / (1 + len(null))


def one_symbol(job: tuple[str, int]) -> tuple[list[dict], list[dict]]:
    symbol, seat = job
    rng = np.random.default_rng([SEED, seat])
    df = frame(symbol)
    if df is None:
        return [], []
    r = df.r.to_numpy(float)
    ts = df.ts.to_numpy()
    cost = float(np.nanmedian(df.cost.to_numpy()))
    quoted = float(np.nanmedian(df.quoted.to_numpy()))
    n = len(r)
    kmax = max(HORIZONS)
    day = (ts // 86_400).astype(np.int64)
    mid = ts[n // 2]
    base = dress(r, ts)
    # The cost of a round trip in the same unit every reading below is in.
    unit = float(np.nanmedian(base["vol"]))
    cost_vol = float(cost / unit) if np.isfinite(cost) else float("nan")
    cost_quoted = float(quoted / unit) if np.isfinite(quoted) else float("nan")
    # Counted at every stage, because a count of zero reads exactly like a
    # decline to trade and an earlier run of this harness reported one.
    usable = int((np.isfinite(base["vol"]) & np.isfinite(base["state"])).sum())
    events = {t: int((np.abs(base["z"]) >= t).sum()) for t in TRIGGERS}
    print(f"{symbol}: {n} bars, {(ts[-1] - ts[0]) / 86400 / 365.25:.1f}y, "
          f"{usable} with a state, events {events}, round trip {cost_vol:.3f} stored "
          f"/ {cost_quoted:.3f} quoted vol",
          file=sys.stderr, flush=True)

    keep = tradable(ts, base["hour"])
    season = deseasoned(r, ts)
    perm = rng.permutation(r)
    # (name, planted drift, outcome series, its dressing, extra event mask)
    arms: list[tuple[str, float, np.ndarray, dict, np.ndarray | None]] = [
        ("real", 0.0, r, base, None),
        ("shuffle", 0.0, perm, dress(perm, ts), None),
        ("deseason", 0.0, season, dress(season, ts), None),
        ("masked", 0.0, r, base, keep),
    ]
    arms += [(f"plant{plant:g}", plant, r, base, None) for plant in PLANTED]

    rows: list[dict] = []
    nulls: dict[str, dict] = {}
    for arm, plant, series, d, extra in arms:
        vol, z, state, slow, hour = (d["vol"], d["z"], d["state"], d["slow"], d["hour"])
        binned = np.clip(
            np.floor(np.nan_to_num(state, nan=-1) * STATE_BINS), -1, STATE_BINS - 1
        ).astype(int)
        cell_code = (binned + 1) * 24 + hour  # -1 (no state) folds into its own block
        side = np.sign(z)
        finite = np.isfinite(vol) & np.isfinite(state) & np.isfinite(z)
        finite[n - kmax :] = False  # one event set for every horizon
        if extra is not None:
            finite = finite & extra
        band_mask = {
            "all": np.ones(n, bool),
            "lo": state <= 1 / 3,
            "hi": state >= 2 / 3,
            "slow_lo": slow <= 1 / 3,
            "slow_hi": slow >= 2 / 3,
        }
        half_mask = {0: np.ones(n, bool), 1: ts < mid, 2: ts >= mid}

        for trigger in TRIGGERS:
            hit = (np.abs(z) >= trigger) & finite
            work = series
            if plant:
                work = series.copy()
                where = np.flatnonzero(hit)
                where = where[where + 1 < n]
                work[where + 1] += plant * vol[where] * side[where]
            fwd_rv = {k: outcomes(work, vol, k) for k in HORIZONS}
            halves = (0,) if plant else HALVES
            for band in BANDS:
                bm = np.nan_to_num(band_mask[band], nan=False).astype(bool)
                for half in halves:
                    ok = hit & bm & half_mask[half]
                    idx = np.flatnonzero(ok)
                    pool_mask = (~hit) & finite & bm & half_mask[half]
                    plc = np.array([], dtype=int) if plant else matched(
                        ok, pool_mask, cell_code, rng)
                    for k in HORIZONS:
                        fwd, rv = fwd_rv[k]
                        cont = fwd * side
                        row = {
                            "symbol": symbol, "kind": "synth" if symbol in SYNTH else "traded",
                            "arm": arm, "plant": plant, "trigger": trigger, "band": band,
                            "half": half, "k": k, "n": len(idx), "placebo_n": len(plc),
                            "cost_vol": cost_vol, "cost_quoted": cost_quoted,
                            "years": (ts[-1] - ts[0]) / 86400 / 365.25,
                        }
                        if len(idx) >= MIN_EVENTS:
                            m, lo, hi, p = boot(day[idx], cont[idx], rng)
                            row |= {"cont": m, "cont_lo": lo, "cont_hi": hi, "cont_p": p}
                            m, lo, hi, _ = boot(day[idx], rv[idx], rng)
                            row |= {"rv": m, "rv_lo": lo, "rv_hi": hi}
                            if len(plc) >= MIN_EVENTS:
                                g, glo, ghi, gp = boot_gap(
                                    day[idx], rv[idx], day[plc], rv[plc], rng)
                                row |= {
                                    "rv_plc": float(rv[plc].mean()), "d_rv": g,
                                    "d_rv_lo": glo, "d_rv_hi": ghi, "d_rv_p": gp,
                                }
                                c, clo, chi, cp = boot_gap(
                                    day[idx], cont[idx], day[plc], cont[plc], rng)
                                row |= {
                                    "cont_plc": float(cont[plc].mean()), "d_cont": c,
                                    "d_cont_lo": clo, "d_cont_hi": chi, "d_cont_p": cp,
                                }
                        rows.append(row)

        # The sign-flip null, once per detector series and reused by every arm
        # that shares it: `plant` changes the outcome, never the detector.
        if not plant:
            cells = {
                (trigger, band, half, k): np.flatnonzero(
                    (np.abs(z) >= trigger) & finite
                    & np.nan_to_num(band_mask[band], nan=False).astype(bool)
                    & half_mask[half])
                for trigger in TRIGGERS for band in BANDS for half in HALVES
                for k in HORIZONS
            }
            cells = {key: idx for key, idx in cells.items() if len(idx) >= MIN_EVENTS}
            nulls[arm] = flip_null(np.abs(series), vol, cells, rng) if cells else {}

    # The hour-of-day profile of the headline cell: if a directional reading
    # lives in one or two hours it is the calendar, not the impulse.
    hourly: list[dict] = []
    vol, z, hour = base["vol"], base["z"], base["hour"]
    ok = (np.abs(z) >= 3.0) & np.isfinite(vol) & np.isfinite(base["state"])
    ok[n - kmax :] = False
    fwd, _ = outcomes(r, vol, 12)
    cont = fwd * np.sign(z)
    for h in range(24):
        pick = np.flatnonzero(ok & (hour == h))
        hourly.append({
            "symbol": symbol, "hour": h, "n": len(pick),
            "cont": float(cont[pick].mean()) if len(pick) else float("nan"),
            "up_share": float((np.sign(z)[pick] > 0).mean()) if len(pick) else float("nan"),
            "drift": float(fwd[np.flatnonzero(np.isfinite(fwd) & (hour == h))].mean()),
        })

    for row in rows:
        null = nulls.get("real" if row["arm"].startswith("plant") else row["arm"], {})
        key = (row["trigger"], row["band"], row["half"], row["k"])
        draws = null.get(key)
        if draws is None or "cont" not in row:
            continue
        row |= {
            "flip_mean": float(np.mean(draws)),
            "flip_sd": float(np.std(draws, ddof=1)),
            "flip_p": rank_p(row["cont"], draws),
        }
    return rows, hourly


def bh(p: pd.Series) -> pd.Series:
    """Benjamini-Hochberg, because picking the best of a grid gives a winner
    every time."""
    good = p.dropna().sort_values()
    m = len(good)
    if not m:
        return pd.Series(index=p.index, dtype=float)
    q = (good.to_numpy() * m / np.arange(1, m + 1))[::-1]
    q = np.minimum.accumulate(q)[::-1].clip(0, 1)
    return pd.Series(q, index=good.index).reindex(p.index)


def main() -> None:
    symbols = [*TRADED, *SYNTH]
    with Pool(min(len(symbols), os.cpu_count() or 1)) as pool:
        batches = pool.map(one_symbol, [(s, i) for i, s in enumerate(symbols)])
    rows = [row for batch, _ in batches for row in batch]
    hours = pd.DataFrame([row for _, batch in batches for row in batch])
    out = pd.DataFrame(rows)
    where = os.environ.get("OUT", ".data/out/impulse_vol.csv")
    os.makedirs(os.path.dirname(where) or ".", exist_ok=True)
    out.to_csv(where, index=False)
    if len(hours):
        hours.to_csv(where.replace(".csv", "_hours.csv"), index=False)
    print(f"wrote {where}: {len(out)} cells, {out.symbol.nunique() if len(out) else 0} symbols")
    if out.empty:
        # A zero is a reading, and a reading can be of nothing. An earlier run
        # of this harness wrote 0 cells and exited 0; it will not do so again.
        raise SystemExit("no cells: the chain was never exercised")

    report(out)


def report(out: pd.DataFrame) -> None:
    """Never only pooled: every table here is printed per instrument as well,
    because a pooled median has inverted a subgroup on this desk before."""
    live = out[(out.arm == "real") & (out.half == 0) & out.cont.notna()]
    print(f"\nreal arm, full sample: {len(live)} cells, "
          f"{int(live.n.sum())} events, median n {live.n.median():.0f}")
    if len(live):
        q = bh(live.flip_p)
        print(f"BH over the direction family: {(q < 0.10).sum()} of {q.notna().sum()} "
              f"cells at q<0.10; smallest q {q.min():.3f}")
        print("\ndirection, by band and trigger (mean over symbols, in forecast-vol units)")
        print(live.groupby(["band", "trigger"])[
            ["cont", "flip_mean", "flip_sd", "flip_p", "d_cont", "cost_vol"]].mean().round(4))
        print("\nvolatility, by band and horizon")
        print(live.groupby(["band", "k"])[["rv", "rv_plc", "d_rv", "d_rv_p"]].mean().round(4))

        # Per instrument, at the headline cell, with the shuffle twin of the
        # same cell beside it: the twin keeps every |return| and destroys the
        # clustering, so whatever it reads is the floor this estimator cannot
        # go below and the real reading has to clear it.
        head = (out.half == 0) & (out.band == "all") & (out.trigger == 3.0) & (out.k == 12)
        real = out[head & (out.arm == "real")].set_index("symbol")
        shuf = out[head & (out.arm == "shuffle")].set_index("symbol")
        season = out[head & (out.arm == "deseason")].set_index("symbol")
        masked = out[head & (out.arm == "masked")].set_index("symbol")
        table = pd.DataFrame({
            "kind": real.kind, "n": real.n, "years": real.years.round(1),
            "stored": real.cost_vol.round(3), "quoted": real.cost_quoted.round(3),
            "cont": real.cont.round(4), "flip_sd": real.flip_sd.round(4),
            "flip_p": real.flip_p.round(3), "d_cont": real.d_cont.round(4),
            "cont_deseason": season.cont.round(4), "p_deseason": season.flip_p.round(3),
            "cont_masked": masked.cont.round(4), "p_masked": masked.flip_p.round(3),
            "rv": real.rv.round(3), "d_rv": real.d_rv.round(4),
            "d_rv_p": real.d_rv_p.round(3), "d_rv_shuffled": shuf.d_rv.round(4),
        })
        print("\nper instrument at trigger 3.0, k=12, full sample")
        print(table.to_string())

        # How much of the direction reading each attribution arm removes,
        # across every real cell rather than only the headline one.
        keys = ["symbol", "trigger", "band", "half", "k"]
        wide = out[out.arm.isin(["real", "deseason", "masked"])].pivot_table(
            index=keys, columns="arm", values="cont")
        wide = wide.dropna()
        print(f"\nattribution over {len(wide)} real cells, |cont| in forecast-vol units")
        print(pd.DataFrame({
            "mean |cont|": [wide.real.abs().mean(), wide.deseason.abs().mean(),
                            wide.masked.abs().mean()],
            "share of real kept": [
                1.0,
                float((wide.deseason * np.sign(wide.real)).mean() / wide.real.abs().mean()),
                float((wide.masked * np.sign(wide.real)).mean() / wide.real.abs().mean())],
        }, index=["real", "deseason", "masked"]).round(4))

        print("\ndiscovery / confirmation, direction at trigger 3.0, k=12")
        halves = out[(out.arm == "real") & (out.band == "all")
                     & (out.trigger == 3.0) & (out.k == 12)]
        print(halves.pivot_table(index="symbol", columns="half",
                                 values=["cont", "flip_p"]).round(4).to_string())
    power = out[out.arm.str.startswith("plant") & (out.band == "all")]
    if len(power):
        print("\nplanted-drift power (share of symbol cells with flip_p < 0.05)")
        print(power.groupby(["plant", "trigger", "k"]).flip_p.apply(
            lambda s: (s < 0.05).mean()).unstack().round(2))


if __name__ == "__main__":
    main()
