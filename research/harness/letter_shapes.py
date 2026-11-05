"""Do named candle letters occur more often than a walk makes them, does one
letter follow another, and is a letter a volatility label?

    ./.secrets/lab.sh run research/harness/letter_shapes.py \
        PART=main BASE=15m SEQLAB=$HOME/till_infinity/data/seqlab \
        OUT=$HOME/till_infinity/out/letters

## The claim, and the ones it is distinct from

`fractal-twins.md` embedded 64-bar candle shapes and multi-timeframe ones,
retrieved nearest historical twins and scored direction and volatility against
random-walk controls on 20 instruments and ~1.18M moments. Its verdict:
markets remember their volatility fractally and their direction not at all.
`bos-predict.md` separately found a break of structure carries no side beyond
the geometry of two levels.

A named letter is a **lower-dimensional special case of those embeddings**, so
"the textbook trade for each letter, and its opposite" is a closed claim. It is
carried here as an arm that is **expected to be null**, with the walk as its
null, and if it comes back positive that is a finding about selection.

Three sentences those studies could not have tested:

1. **A census.** Do named shapes occur at rates a matched random walk does not
   produce? `fractal-twins` measured retrieval quality, never shape
   *frequency*. A walk makes letters too - that is the whole point.
2. **Transitions.** Does the sequence of completed shapes carry structure
   beyond a walk's - which letter follows which?
3. **A volatility label.** Does the volatility *after* a W differ from after an
   M, **controlling for the volatility at completion**? `impulse-vol.md` just
   measured that an impulse adds +0.167 to +0.355 of a forecast unit of forward
   volatility over a volatility-and-hour-matched bar on 8 of 8 traded markets.
   Letters may be another label for the same thing - that is tested here, not
   assumed.

## The matcher, frozen before the run

* **Templates** are piecewise-linear paths, z-scored. The set is **closed under
  price negation**: every letter's mirror is in it, because correlation against
  `-t` is minus correlation against `t`, so a walk - which is symmetric under
  negation - must produce a letter and its mirror at the same rate. That
  equality is a harness check that costs nothing and is reported.
* **A window is labelled by the argmax of correlation** over the 14 templates,
  and counts only if that letter passes **both** gates: `corr >= R` and
  `dtw <= D(R, W, letter)`.
* **`D` is calibrated on a walk, not on the data.** For each window length,
  letter and `R`, it is the **median** DTW among the windows of an
  independently generated Gaussian random walk that already pass the
  correlation gate. So the DTW gate rejects half of what correlation accepts
  *on a walk*, and nothing about the markets sets the strictness.
* **A shape counts only at the bar where it completes.** The window is
  `[i-W+1, i]` and the occurrence is recorded at `i`; no bar after `i` is read.
* **Occurrences are de-overlapped greedily**, across all letters at once: an
  occurrence is kept only if the last kept one was at least `W` bars earlier.
  Overlapping windows inflate permutation nulls and leak into forward windows,
  and both failures are on file here.

## The nulls, which are the study

1. **The i.i.d.-shuffled twin**, 24 draws per instrument. A permutation of that
   instrument's own returns: the exact marginal distribution - every fat tail -
   with the ordering destroyed. This is the matched random walk for the census.
2. **The day-block-shuffled twin**, 24 draws, permuting whole days among days
   of the same bar count so the timestamp alignment is exact. Intraday
   volatility clustering survives and cross-day ordering does not, which
   separates "letters are shapes" from "letters are volatility clustering".
3. **Four Deriv synthetics**, each for one named property of its published
   generator. They are real markets, not a general null - `findings.md` sets
   that rule.
4. **A label-permutation null** for the transition matrix: the same letter
   sequence reordered, so the census is preserved exactly and only the order
   dies. Mutual information is biased upward at finite `n`; this null carries
   the identical bias.
5. **A volatility-and-hour-matched placebo** for the conditional channels,
   twenty volatility bins by hour of day, drawn from non-occurrence bars.
6. **Day-block bootstrap**, because shapes cluster in days.
7. **Benjamini-Hochberg** over the full cell count: letters x windows x
   timeframes x instruments is a large surface and picking the best cell gives
   a winner every time.

## Power, before any null is believed

`PART=power` plants an effect on the generated markets, where the real answer
is null, and sweeps its strength: letters spliced into the series at a known
multiple of the observed rate (the census), forward volatility lifted after
each completion (the risk channel), and a drift added after each completion
(the direction channel). The write-up says where the test goes blind.

## The cost line does not come from the bars

The per-bar `spread` column is in points, not price, and on this feed it also
understates the terminal's quote by a factor of one to eight. Both are
computed; every cost statement is made at the quote.
"""

from __future__ import annotations

import os
import sys
import time
from multiprocessing import Pool

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

try:  # the lab has it; a laptop smoke test may not
    from scipy.signal import correlate as _xcorr

    def _dot(c: np.ndarray, t: np.ndarray) -> np.ndarray:
        return _xcorr(c, t, mode="valid", method="fft")
except Exception:  # pragma: no cover - fallback path

    def _dot(c: np.ndarray, t: np.ndarray) -> np.ndarray:
        return np.correlate(c, t, mode="valid")


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------
def _seqlab(ticker: str, interval: str) -> pd.DataFrame:
    """`$SEQLAB/<TICKER>.<interval>.npz`, oldest first, bars repaired to
    contain their own open and close."""
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
OUT = os.environ.get("OUT", "out/letters")
PART = os.environ.get("PART", "main")

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD", "XAGUSD", "BTCUSD")
SYNTH = ("Volatility 75 Index", "Volatility 25 Index", "Step Index", "Jump 75 Index")
PROPERTY = {
    "Volatility 75 Index": "constant volatility: no clustering to find",
    "Volatility 25 Index": "constant volatility: no clustering to find",
    "Step Index": "fixed step: neither clustering nor a tail",
    "Jump 75 Index": "fat tails without clustering",
}

#: `point` per symbol, read from the bridge's `GET /api/v1/symbols/info/` on
#: 2026-11-05 and written down so the cost line does not need a live terminal.
POINT: dict[str, float] = {
    "EURUSD": 1e-05, "GBPUSD": 1e-05, "USDJPY": 0.001, "AUDUSD": 1e-05,
    "USDCAD": 1e-05, "XAUUSD": 0.01, "XAGUSD": 0.001, "BTCUSD": 0.001,
    "Volatility 75 Index": 0.01, "Volatility 25 Index": 0.001,
    "Step Index": 0.1, "Jump 75 Index": 0.01,
}
#: What the terminal **quoted** on 2026-11-05, in points. The stored column
#: reads about a point on EURUSD where the live book reads nine, and a cost
#: conclusion drawn from the cheaper of the two is the one that lets a finding
#: through. Every cost statement here is made at the quote.
SPREAD_POINTS = {
    "EURUSD": 9, "GBPUSD": 11, "USDJPY": 9, "AUDUSD": 7, "USDCAD": 10,
    "XAUUSD": 16, "XAGUSD": 30, "BTCUSD": 18_424, "Volatility 75 Index": 1_343,
    "Volatility 25 Index": 331, "Step Index": 1, "Jump 75 Index": 180,
}

# --------------------------------------------------------------------------
# the rules, as frozen before the run
# --------------------------------------------------------------------------
#: M5 is not in this cache and could not be pulled from here, so the grid runs
#: from the 15-minute base upwards. Each timeframe is a **calendar bin** of the
#: base: the slow return is the sum of the fast returns inside the bin, never a
#: difference of aligned closes, which would make every session gap a
#: fabricated one-bar return.
TIMEFRAMES = {"15m": 900, "1h": 3_600, "4h": 14_400, "1d": 86_400}
WINDOWS = (12, 24, 48, 96)
GATES = {"strict": 0.90, "loose": 0.80}
#: Sakoe-Chiba band, as a fraction of the window.
BAND_DIV = 10
#: Known before the bar: the forecast never sees its own bar.
VOL_SPAN = 60
STATE_WIN, STATE_MIN = 500, 200
STATE_BINS = 20
HORIZONS = (4, 12, 48)
#: An impulse, as `impulse-vol.md` defines one, used here only to ask whether a
#: letter is a relabelled impulse.
IMPULSE_Z = 2.0
#: The barrier arm: stop at `STOP_MULT` forecast units, target at `RR` times
#: the stop, so the walk's answer is exactly `1 / (1 + RR)`.
STOP_MULT, RR, BARRIER_K = 3.0, 2.0, 96
#: The per-letter gate's rate on the reference walk. 2% of windows before the
#: DTW median halves it and de-overlap thins it again, which leaves 300-800
#: events per letter per instrument at the 15-minute base - enough to compare
#: one letter's forward volatility with another's, which the absolute gate
#: cannot do for a four-leg shape.
RANK_Q = 0.02
NSHUF = int(os.environ.get("NSHUF", "24"))
NPERM = 200
BOOT = 500
#: Under this many events a cell is noise; it is reported with its `n`, never
#: dropped, because a dropped cell is invisible.
MIN_EVENTS = 100
#: The gates the conditional channels are read on.
COND_GATES = ("strict", "rank")
#: Named before the grid was read.
HEADLINE = ("15m", 48, "rank", 12)
SEED = 20261105
#: The reference walk the DTW gate is calibrated on. Nothing about the markets
#: enters it.
CAL_STEPS, CAL_SAMPLE, CAL_SEED = 400_000, 4_000, 777

# --------------------------------------------------------------------------
# templates
# --------------------------------------------------------------------------
#: Control points, as (fraction of the window, level). The levels are
#: arbitrary up to an affine map because both template and window are z-scored
#: before they meet; what matters is the shape.
SHAPES: dict[str, list[tuple[float, float]]] = {
    # the sharp reversals
    "V": [(0.0, 1.0), (0.5, -1.0), (1.0, 1.0)],
    "A": [(0.0, -1.0), (0.5, 1.0), (1.0, -1.0)],
    # the rounded ones
    "U": [(0.0, 1.0), (0.15, -0.28), (0.5, -1.0), (0.85, -0.28), (1.0, 1.0)],
    "U'": [(0.0, -1.0), (0.15, 0.28), (0.5, 1.0), (0.85, 0.28), (1.0, -1.0)],
    # the doubles
    "W": [(0.0, 1.0), (0.25, -1.0), (0.5, 0.2), (0.75, -1.0), (1.0, 1.0)],
    "M": [(0.0, -1.0), (0.25, 1.0), (0.5, -0.2), (0.75, 1.0), (1.0, -1.0)],
    # the trend-with-a-pullback
    "N": [(0.0, -1.0), (0.35, 0.3), (0.65, -0.2), (1.0, 1.0)],
    "N'": [(0.0, 1.0), (0.35, -0.3), (0.65, 0.2), (1.0, -1.0)],
    # the shelf-step-shelf
    "Z": [(0.0, 1.0), (0.35, 1.0), (0.65, -1.0), (1.0, -1.0)],
    "S": [(0.0, -1.0), (0.35, -1.0), (0.65, 1.0), (1.0, 1.0)],
    # the drop-then-base
    "L": [(0.0, 1.0), (0.3, -1.0), (1.0, -1.0)],
    "L'": [(0.0, -1.0), (0.3, 1.0), (1.0, 1.0)],
    # the J-curve: a long decline, a base, a sharp finish
    "J": [(0.0, 0.3), (0.55, -1.0), (0.8, -0.85), (1.0, 1.0)],
    "J'": [(0.0, -0.3), (0.55, 1.0), (0.8, 0.85), (1.0, -1.0)],
}
LETTERS = tuple(SHAPES)
#: Every letter's mirror, so the negation symmetry can be checked rather than
#: assumed.
MIRROR = {"V": "A", "A": "V", "U": "U'", "U'": "U", "W": "M", "M": "W",
          "N": "N'", "N'": "N", "Z": "S", "S": "Z", "L": "L'", "L'": "L",
          "J": "J'", "J'": "J"}
#: The textbook side, frozen. The **opposite** arm is this negated, so it is
#: exactly minus the reading and is not measured separately.
SIDE = {"V": +1, "A": -1, "U": +1, "U'": -1, "W": +1, "M": -1, "N": +1,
        "N'": -1, "Z": -1, "S": +1, "L": +1, "L'": -1, "J": +1, "J'": -1}


def template(name: str, width: int) -> np.ndarray:
    """The letter as a z-scored path of `width` points."""
    pts = SHAPES[name]
    xs = np.array([p[0] for p in pts]) * (width - 1)
    ys = np.array([p[1] for p in pts])
    path = np.interp(np.arange(width), xs, ys)
    sd = path.std()
    return (path - path.mean()) / sd if sd > 0 else path * 0.0


def bank(width: int) -> np.ndarray:
    return np.stack([template(name, width) for name in LETTERS])


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------
def sliding_corr(path: np.ndarray, temp: np.ndarray) -> np.ndarray:
    """Correlation of every length-`W` window of `path` with a z-scored
    template, as one cross-correlation plus two cumulative sums."""
    width = len(temp)
    n = len(path)
    if n < width:
        return np.empty(0)
    cs = np.concatenate([[0.0], np.cumsum(path)])
    cs2 = np.concatenate([[0.0], np.cumsum(path * path)])
    total = cs[width:] - cs[:-width]
    total2 = cs2[width:] - cs2[:-width]
    mean = total / width
    var = np.maximum(total2 / width - mean * mean, 0.0)
    sd = np.sqrt(var)
    dot = _dot(path, temp)
    out = np.full(len(sd), np.nan)
    live = sd > 0
    out[live] = (dot[live] / width) / sd[live]
    return out


def dtw_banded(rows: np.ndarray, temp: np.ndarray, band: int) -> np.ndarray:
    """Banded DTW of many z-scored windows against one z-scored template.

    Vectorised across windows rather than across the DP, because the obvious
    per-window implementation is `O(W * band)` in Python and does not finish on
    eleven years of 15-minute bars. The distance is divided by `W`, the
    diagonal length, so it is in standard deviations per step.
    """
    m, width = rows.shape
    span = 2 * band + 1
    big = np.float64(1e18)
    prev = np.full((m, span), big)
    cur = np.empty((m, span))
    for i in range(width):
        lo = i - band
        cur[:] = big
        for off in range(span):
            j = lo + off
            if j < 0 or j >= width:
                continue
            cost = np.abs(rows[:, i] - temp[j])
            if i == 0:
                if j == 0:
                    cur[:, off] = cost
                elif off > 0:
                    cur[:, off] = cost + cur[:, off - 1]
                continue
            best = prev[:, off]                       # (i-1, j-1)
            if off + 1 < span:
                best = np.minimum(best, prev[:, off + 1])   # (i-1, j)
            if off > 0:
                best = np.minimum(best, cur[:, off - 1])    # (i, j-1)
            cur[:, off] = cost + best
        prev, cur = cur, prev
    return prev[:, band] / width


def zrows(path: np.ndarray, width: int, starts: np.ndarray) -> np.ndarray:
    rows = sliding_window_view(path, width)[starts].astype(np.float64)
    mean = rows.mean(axis=1, keepdims=True)
    sd = rows.std(axis=1, keepdims=True)
    sd[sd == 0] = 1.0
    return (rows - mean) / sd


def scan(path: np.ndarray, width: int) -> tuple[np.ndarray, np.ndarray]:
    """Correlation of every window with every template, and the templates."""
    temps = bank(width)
    scores = np.stack([sliding_corr(path, t) for t in temps])  # (letter, window)
    return np.nan_to_num(scores, nan=-2.0), temps


def _dtw_for(path, width, temps, band, picks: dict[int, np.ndarray]) -> dict:
    """DTW for a candidate set per letter, chunked so the window matrix never
    exceeds a few hundred megabytes."""
    out = {}
    for li, idx in picks.items():
        if len(idx) == 0:
            out[li] = np.empty(0)
            continue
        parts = [dtw_banded(zrows(path, width, chunk), temps[li], band)
                 for chunk in np.array_split(idx, max(1, len(idx) // 20_000))]
        out[li] = np.concatenate(parts)
    return out


def deoverlap(hits: np.ndarray, width: int) -> np.ndarray:
    """Greedy left-to-right: keep an occurrence only if the last kept one was
    at least `width` windows earlier."""
    keep = []
    last = -10**9
    for h in hits:
        if h - last >= width:
            keep.append(h)
            last = h
    return np.array(keep, dtype=np.int64)


def occurrences(path: np.ndarray, width: int, cal: dict,
                want_rank: bool = False) -> dict[str, tuple]:
    """`{gate: (completion bar index, letter index)}` for one series, one
    timeframe, one window length.

    Two kinds of gate, because two questions need different things:

    * `strict` and `loose` are **absolute**: a window is labelled by the argmax
      of correlation and counts only if that letter clears `corr >= R` and the
      walk-calibrated DTW median. The rate is then a measurement, which is what
      a census and a transition matrix need.
    * `rank` is **per letter and balanced**: a window counts for letter `L` if
      its correlation to `L` is at or above the reference walk's `1 - RANK_Q`
      quantile for `L`, and its DTW clears that threshold's own walk median. No
      argmax, so the letters' streams overlap each other and a census on this
      gate would be fixed by construction and meaningless. It exists because a
      four-leg template such as `W` reaches `corr >= 0.90` on about one window
      in 100,000 - roughly three events in eleven years - so the absolute gate
      cannot compare the volatility after a W with the volatility after an M at
      all. The price is that a `rank` W is a weaker W: the walk's top 2% of
      correlation to the W template starts at about 0.66.
    """
    scores, temps = scan(path, width)
    out: dict[str, tuple] = {}
    if scores.size == 0:
        for gate in list(GATES) + (["rank"] if want_rank else []):
            out[gate] = (np.empty(0, np.int64), np.empty(0, int))
        return out
    band = max(2, width // BAND_DIV)
    nwin = scores.shape[1]
    who = scores.argmax(axis=0)
    best = scores[who, np.arange(nwin)]
    cand = np.flatnonzero(best >= min(GATES.values()))
    dist = np.full(nwin, np.inf)
    picks = {int(li): cand[who[cand] == li] for li in np.unique(who[cand])}
    for li, got in _dtw_for(path, width, temps, band, picks).items():
        dist[picks[li]] = got
    for gate, rmin in GATES.items():
        ok = best >= rmin
        if ok.any():
            ok &= dist <= np.array(
                [cal["dtw"][(gate, width, name)] for name in LETTERS])[who]
        hits = deoverlap(np.flatnonzero(ok), width)
        out[gate] = (hits + width - 1, who[hits] if len(hits) else np.empty(0, int))
    if want_rank:
        picks, keep = {}, {}
        for li, name in enumerate(LETTERS):
            thr = cal["corr"][(width, name)]
            picks[li] = np.flatnonzero(scores[li] >= thr)
        got = _dtw_for(path, width, temps, band, picks)
        for li, name in enumerate(LETTERS):
            idx = picks[li]
            if len(idx) == 0:
                keep[li] = np.empty(0, np.int64)
                continue
            keep[li] = deoverlap(idx[got[li] <= cal["dtw"][("rank", width, name)]], width)
        hits = np.concatenate([keep[li] for li in range(len(LETTERS))]) \
            if any(len(v) for v in keep.values()) else np.empty(0, np.int64)
        tags = np.concatenate([np.full(len(keep[li]), li) for li in range(len(LETTERS))]) \
            if len(hits) else np.empty(0, int)
        order = np.argsort(hits, kind="stable")
        out["rank"] = (hits[order] + width - 1, tags[order])
    return out


def best_of(scores: np.ndarray, who: np.ndarray) -> np.ndarray:
    return scores[who, np.arange(scores.shape[1])]


def _median_dtw(walk, width, temp, band, mine, rng) -> float:
    """The median DTW of a sampled candidate set, or NaN when the walk makes
    too few of that shape to calibrate on."""
    if len(mine) > CAL_SAMPLE:
        mine = np.sort(rng.choice(mine, CAL_SAMPLE, replace=False))
    if len(mine) < 50:
        return float("nan")
    return float(np.median(dtw_banded(zrows(walk, width, mine), temp, band)))


def _fill(store: dict, gate: str, width: int, got: dict) -> None:
    """A letter the walk never makes borrows the other letters' median, so a
    missing calibration is a stated fallback and not an infinite gate."""
    fallback = float(np.nanmedian(list(got.values())))
    for name in LETTERS:
        value = got[name]
        store[(gate, width, name)] = fallback if not np.isfinite(value) else value
    print(f"  calibrate {gate} W={width}: "
          + " ".join(f"{k}={store[(gate, width, k)]:.3f}" for k in LETTERS),
          file=sys.stderr, flush=True)


def calibrate() -> dict:
    """`D(gate, W, letter)`: the median DTW among the windows of an
    independently generated Gaussian random walk that already pass the
    correlation gate.

    Calibrating on a walk rather than on the data is the point. It makes the
    two gates equally strict *by construction* on a process with no shapes in
    it, so the conjunction means something, and nothing about the markets sets
    where it sits.
    """
    rng = np.random.default_rng(CAL_SEED)
    walk = np.cumsum(rng.standard_normal(CAL_STEPS))
    out: dict = {"dtw": {}, "corr": {}}
    for width in WINDOWS:
        temps = bank(width)
        scores, _ = scan(walk, width)
        who = scores.argmax(axis=0)
        best = scores[who, np.arange(scores.shape[1])]
        band = max(2, width // BAND_DIV)
        for gate, rmin in GATES.items():
            got = {}
            for li, name in enumerate(LETTERS):
                mine = np.flatnonzero((who == li) & (best_of(scores, who) >= rmin))
                got[name] = _median_dtw(walk, width, temps[li], band, mine, rng)
            _fill(out["dtw"], gate, width, got)
        got = {}
        for li, name in enumerate(LETTERS):
            thr = float(np.quantile(scores[li], 1 - RANK_Q))
            out["corr"][(width, name)] = thr
            mine = np.flatnonzero(scores[li] >= thr)
            got[name] = _median_dtw(walk, width, temps[li], band, mine, rng)
        _fill(out["dtw"], "rank", width, got)
        print(f"  calibrate rank W={width}: "
              + " ".join(f"{k}>={out['corr'][(width, k)]:.2f}"
                         f"/{out['dtw'][('rank', width, k)]:.3f}" for k in LETTERS),
              file=sys.stderr, flush=True)
    return out


# --------------------------------------------------------------------------
# series, timeframes and surrogates
# --------------------------------------------------------------------------
def frame(symbol: str) -> pd.DataFrame | None:
    try:
        df = _seqlab(symbol, BASE)
    except Exception as exc:
        print(f"  {symbol}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    if df is None or len(df) < 20_000:
        print(f"  {symbol}: {0 if df is None else len(df)} bars, too few", file=sys.stderr)
        return None
    close = df.close.to_numpy(float)
    out = pd.DataFrame({"ts": df.ts.to_numpy(), "logc": np.log(close)})
    out["r"] = out.logc.diff()
    out["cost"] = df.spread.to_numpy(float) * POINT.get(symbol, np.nan) / close
    out["quoted"] = SPREAD_POINTS.get(symbol, np.nan) * POINT.get(symbol, np.nan) / close
    return out.dropna(subset=["r"]).reset_index(drop=True)


def bins(ts: np.ndarray, seconds: int) -> tuple[np.ndarray, np.ndarray]:
    codes, inv = np.unique(ts // seconds, return_inverse=True)
    return codes * seconds, inv


def regrid(r: np.ndarray, inv: np.ndarray, nbin: int) -> np.ndarray:
    """The timeframe's returns: the **sum of the base returns in the bin**."""
    return np.bincount(inv, weights=np.nan_to_num(r), minlength=nbin)


def iid_shuffle(r: np.ndarray, rng) -> np.ndarray:
    return rng.permutation(r)


def day_shuffle(r: np.ndarray, day: np.ndarray, rng) -> np.ndarray:
    """Permute whole days among days of the **same bar count**, so each block
    lands on a slot of exactly its own length and the timestamp alignment stays
    exact. Intraday clustering survives; cross-day ordering does not."""
    out = r.copy()
    _, inv = np.unique(day, return_inverse=True)
    counts = np.bincount(inv)
    starts = np.concatenate([[0], np.cumsum(counts)])
    order = np.argsort(inv, kind="stable")
    for size in np.unique(counts):
        which = np.flatnonzero(counts == size)
        if len(which) < 2:
            continue
        src = rng.permutation(which)
        for a, b in zip(which, src, strict=True):
            out[order[starts[a]:starts[a] + size]] = r[order[starts[b]:starts[b] + size]]
    return out


def ewma_abs(r: np.ndarray, span: int) -> np.ndarray:
    s = pd.Series(np.abs(r))
    return s.ewm(span=span, min_periods=span).mean().shift(1).to_numpy()


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------
def boot_mean(day: np.ndarray, value: np.ndarray, rng) -> tuple[float, float, float, float]:
    """Day-block bootstrap of a mean: the mean, a 90% interval and a two-sided
    p against zero. Resamples whole days because shapes cluster in them."""
    if len(value) == 0:
        return (np.nan,) * 4
    codes, inv = np.unique(day, return_inverse=True)
    tot = np.bincount(inv, weights=value, minlength=len(codes))
    num = np.bincount(inv, minlength=len(codes)).astype(float)
    picks = rng.integers(0, len(codes), size=(BOOT, len(codes)))
    means = tot[picks].sum(1) / num[picks].sum(1)
    side = min((means <= 0).mean(), (means >= 0).mean())
    return (float(value.mean()), float(np.quantile(means, 0.05)),
            float(np.quantile(means, 0.95)), float(min(1.0, max(2 * side, 1.0 / BOOT))))


def _draws(day, value, rng) -> np.ndarray:
    codes, inv = np.unique(day, return_inverse=True)
    tot = np.bincount(inv, weights=value, minlength=len(codes))
    num = np.bincount(inv, minlength=len(codes)).astype(float)
    picks = rng.integers(0, len(codes), size=(BOOT, len(codes)))
    return tot[picks].sum(1) / num[picks].sum(1)


def boot_gap(day_a, val_a, day_b, val_b, rng) -> tuple[float, float, float, float]:
    """A difference of two means over different bars. The arms are resampled
    independently although they come from the same series and are positively
    dependent, so the interval is **conservative** - the direction a null wants
    to be wrong in."""
    if len(val_a) == 0 or len(val_b) == 0:
        return (np.nan,) * 4
    means = _draws(day_a, val_a, rng) - _draws(day_b, val_b, rng)
    side = min((means <= 0).mean(), (means >= 0).mean())
    return (float(val_a.mean() - val_b.mean()), float(np.quantile(means, 0.05)),
            float(np.quantile(means, 0.95)), float(min(1.0, max(2 * side, 1.0 / BOOT))))


def matched(ok: np.ndarray, pool: np.ndarray, cell: np.ndarray, rng) -> np.ndarray:
    """For every occurrence, a non-occurrence bar from the same volatility bin
    and hour of day. Vectorised by shuffling the pool once and sorting it
    stably by cell, so each cell's members arrive in random order."""
    if cell.size == 0 or not ok.any():
        return np.array([], dtype=int)
    want = np.bincount(cell[ok], minlength=int(cell.max()) + 1)
    idx = np.flatnonzero(pool)
    if len(idx) == 0:
        return np.array([], dtype=int)
    idx = rng.permutation(idx)
    idx = idx[np.argsort(cell[idx], kind="stable")]
    keys = cell[idx]
    starts = np.searchsorted(keys, np.arange(len(want)), side="left")
    ends = np.searchsorted(keys, np.arange(len(want)), side="right")
    take = [idx[s:s + min(int(w), e - s)] for w, s, e in zip(want, starts, ends, strict=True)
            if w > 0 and e > s]
    return np.concatenate(take) if take else np.array([], dtype=int)


def rank_p(real: float, null: np.ndarray) -> float:
    """Two-sided rank of a real statistic inside its own null."""
    null = np.asarray(null, dtype=float)
    null = null[np.isfinite(null)]
    if not np.isfinite(real) or len(null) == 0:
        return float("nan")
    centre = float(np.mean(null))
    hits = int(np.sum(np.abs(null - centre) >= abs(real - centre)))
    return (1 + hits) / (1 + len(null))


def upper_p(real: float, null: np.ndarray) -> float:
    """One-sided rank, for a statistic that can only be inflated - mutual
    information is non-negative and biased upward, so a two-sided test of it
    is the wrong test."""
    null = np.asarray(null, dtype=float)
    null = null[np.isfinite(null)]
    if not np.isfinite(real) or len(null) == 0:
        return float("nan")
    return (1 + int(np.sum(null >= real))) / (1 + len(null))


def bh(p: np.ndarray, q: float = 0.10) -> np.ndarray:
    """Benjamini-Hochberg over a family of p-values."""
    p = np.asarray(p, float)
    live = np.isfinite(p)
    out = np.zeros(len(p), dtype=bool)
    vals = p[live]
    if len(vals) == 0:
        return out
    order = np.argsort(vals)
    ranked = vals[order]
    thresh = q * (np.arange(1, len(ranked) + 1) / len(ranked))
    passed = ranked <= thresh
    if passed.any():
        cut = ranked[np.flatnonzero(passed).max()]
        keep = np.zeros(len(vals), dtype=bool)
        keep[vals <= cut] = True
        out[live] = keep
    return out


def mi_bits(prev: np.ndarray, nxt: np.ndarray, k: int) -> float:
    """Mutual information of consecutive letters, in bits."""
    if len(prev) == 0:
        return float("nan")
    joint = np.zeros((k, k))
    np.add.at(joint, (prev, nxt), 1.0)
    p = joint / joint.sum()
    pi = p.sum(1)[:, None]
    pj = p.sum(0)[None, :]
    nz = p > 0
    return float(np.sum(p[nz] * np.log2(p[nz] / (pi * pj)[nz])))


# --------------------------------------------------------------------------
# outcomes
# --------------------------------------------------------------------------
def outcomes(r: np.ndarray, vol: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Forward signed move and forward volatility, both in units of the
    forecast made **before** the event, so the null for `rv` is exactly 1.0."""
    n = len(r)
    fwd = np.full(n, np.nan)
    rv = np.full(n, np.nan)
    cum = np.concatenate([[0.0], np.cumsum(np.nan_to_num(r))])
    cua = np.concatenate([[0.0], np.cumsum(np.abs(np.nan_to_num(r)))])
    i = np.arange(n - k)
    fwd[i] = (cum[i + 1 + k] - cum[i + 1]) / vol[i]
    rv[i] = (cua[i + 1 + k] - cua[i + 1]) / k / vol[i]
    return fwd, rv


def barrier(r: np.ndarray, vol: np.ndarray, idx: np.ndarray, side: np.ndarray
            ) -> tuple[np.ndarray, np.ndarray]:
    """First passage: does the target come before the stop?

    Stop at `STOP_MULT` forecast units, target at `RR` times that, so a
    driftless walk answers exactly `1 / (1 + RR)`. When both barriers fall in
    the same bar the **stop** is taken, which is the conservative reading and
    the one a real fill gives more often than not.
    """
    n = len(r)
    live = idx[idx + BARRIER_K < n]
    if len(live) == 0:
        return np.empty(0), np.empty(0)
    sign = side[idx + BARRIER_K < n].astype(float)
    stop = STOP_MULT * vol[live]
    out = np.full(len(live), -1.0)
    run = np.zeros(len(live))
    for k in range(1, BARRIER_K + 1):
        run += sign * np.nan_to_num(r[live + k])
        open_ = out < 0
        lost = open_ & (run <= -stop)
        won = open_ & (run >= RR * stop) & ~lost
        out[lost] = 0.0
        out[won] = 1.0
    return out, stop


# --------------------------------------------------------------------------
# one instrument
# --------------------------------------------------------------------------
def census_rows(path: np.ndarray, ts: np.ndarray, width: int, cal: dict,
                want_rank: bool = False) -> dict:
    """Occurrence counts and the de-overlapped sequence, per gate."""
    got = occurrences(path, width, cal, want_rank)
    nwin = max(0, len(path) - width + 1)
    out = {}
    for gate, (hits, who) in got.items():
        out[gate] = {"hits": hits, "who": who, "nwin": nwin,
                     "day": (ts[hits] // 86_400).astype(np.int64) if len(hits) else
                     np.empty(0, np.int64)}
    return out


def one_symbol(job: tuple[str, int, dict]) -> dict[str, list[dict]]:
    symbol, seat, cal = job
    rng = np.random.default_rng([SEED, seat])
    started = time.time()
    df = frame(symbol)
    if df is None:
        raise SystemExit(f"{symbol}: no usable bars - refusing to write a cell for it")
    r15 = df.r.to_numpy(float)
    ts15 = df.ts.to_numpy()
    day15 = (ts15 // 86_400).astype(np.int64)
    cost = float(np.nanmedian(df.cost.to_numpy()))
    quoted = float(np.nanmedian(df.quoted.to_numpy()))

    surr = {"iid": [iid_shuffle(r15, rng) for _ in range(NSHUF)],
            "dayblock": [day_shuffle(r15, day15, rng) for _ in range(NSHUF)]}

    census, trans, vol_rows, dir_rows = [], [], [], []
    for tf, seconds in TIMEFRAMES.items():
        tsb, inv = bins(ts15, seconds)
        nbin = len(tsb)
        if nbin < 1_000:
            print(f"  {symbol} {tf}: {nbin} bars, skipped", file=sys.stderr, flush=True)
            continue
        hour = pd.to_datetime(tsb, unit="s", utc=True).hour.to_numpy()
        dayb = (tsb // 86_400).astype(np.int64)
        real_r = regrid(r15, inv, nbin)
        # **Every surrogate is regridded onto this timeframe's bins too.**
        # Shuffling at the base and then reading the result as if it were
        # already on the slow grid compares a 294,498-bar path with a
        # 73,644-bar one; it raised at 1h and would have gone unnoticed at
        # 15m, where the two lengths coincide.
        surr_tf = {arm: [regrid(x, inv, nbin) for x in surr[arm]] for arm in surr}
        real_path = np.cumsum(real_r)
        vol = ewma_abs(real_r, VOL_SPAN)
        state = pd.Series(vol).rolling(STATE_WIN, min_periods=STATE_MIN).rank(
            pct=True).to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            zbar = real_r / vol
        unit = float(np.nanmedian(vol))
        cost_vol = float(cost / unit) if np.isfinite(cost) else float("nan")
        cost_quoted = float(quoted / unit) if np.isfinite(quoted) else float("nan")
        bin_ok = np.isfinite(vol) & np.isfinite(state)
        cell = np.where(bin_ok, np.clip(
            (np.nan_to_num(state) * STATE_BINS).astype(int), 0, STATE_BINS - 1) * 24
            + hour, 0)
        # One length check for the whole timeframe, because the failure it
        # catches - a base-length array read against a binned one - is
        # invisible at 15m, where the two happen to be equal.
        widths = {len(x) for x in (real_r, vol, state, hour, dayb, tsb,
                                   *surr_tf['iid'], *surr_tf['dayblock'])}
        if widths != {nbin}:
            raise SystemExit(f"{symbol} {tf}: lengths {sorted(widths)} != {nbin}")
        fwd = {k: outcomes(real_r, vol, k) for k in HORIZONS}
        twin_r = surr_tf["iid"][0]
        twin_vol = ewma_abs(twin_r, VOL_SPAN)
        twin_fwd = {k: outcomes(twin_r, twin_vol, k) for k in HORIZONS}
        twin_path = np.cumsum(twin_r)
        # The twin's placebo is matched inside the **twin's** volatility bins,
        # not the real series'. Matching a shuffled series against the real
        # one's strata would compare two different stratifications and the
        # floor would stop being a floor.
        twin_state = pd.Series(twin_vol).rolling(
            STATE_WIN, min_periods=STATE_MIN).rank(pct=True).to_numpy()
        twin_ok = np.isfinite(twin_vol) & np.isfinite(twin_state)
        twin_cell = np.where(twin_ok, np.clip(
            (np.nan_to_num(twin_state) * STATE_BINS).astype(int), 0,
            STATE_BINS - 1) * 24 + hour, 0)

        for width in WINDOWS:
            if nbin - width + 1 < 500:
                continue
            real = census_rows(real_path, tsb, width, cal, want_rank=True)
            twin = census_rows(twin_path, tsb, width, cal, want_rank=True)
            # The surrogate draws never need the `rank` gate: it feeds the
            # conditional channels, whose null is the matched placebo and the
            # one shuffled twin, not the 48 census draws.
            nulls = {arm: [census_rows(np.cumsum(x), tsb, width, cal)
                           for x in surr_tf[arm]] for arm in surr_tf}

            for gate in GATES:
                nwin = real[gate]["nwin"]
                hits, who = real[gate]["hits"], real[gate]["who"]
                # ---- the census -------------------------------------------
                counts = np.bincount(who, minlength=len(LETTERS)) if len(who) else \
                    np.zeros(len(LETTERS), int)
                per_arm = {}
                for arm, draws in nulls.items():
                    rates = np.stack([
                        (np.bincount(d[gate]["who"], minlength=len(LETTERS))
                         if len(d[gate]["who"]) else np.zeros(len(LETTERS), int))
                        / max(d[gate]["nwin"], 1) for d in draws])
                    per_arm[arm] = rates
                dayw = (tsb[width - 1:] // 86_400).astype(np.int64)
                for li, name in enumerate(LETTERS):
                    rate = counts[li] / max(nwin, 1)
                    flag = np.zeros(nwin)
                    if counts[li]:
                        flag[hits[who == li] - (width - 1)] = 1.0
                    _, lo, hi, _ = boot_mean(dayw, flag, rng)
                    row = {"symbol": symbol, "tf": tf, "window": width, "gate": gate,
                           "letter": name, "mirror": MIRROR[name], "n": int(counts[li]),
                           "nwin": int(nwin), "rate": rate, "rate_lo": lo, "rate_hi": hi,
                           "events_total": len(hits)}
                    for arm, rates in per_arm.items():
                        col = rates[:, li]
                        row[f"{arm}_rate"] = float(col.mean())
                        row[f"{arm}_sd"] = float(col.std(ddof=1)) if len(col) > 1 else np.nan
                        row[f"{arm}_p"] = rank_p(rate, col)
                        row[f"{arm}_z"] = float(
                            (rate - col.mean()) / col.std(ddof=1)) if (
                            len(col) > 1 and col.std(ddof=1) > 0) else np.nan
                        row[f"{arm}_ratio"] = float(rate / col.mean()) if col.mean() > 0 \
                            else np.nan
                    census.append(row)

                # ---- transitions -------------------------------------------
                if len(who) >= 3:
                    real_mi = mi_bits(who[:-1], who[1:], len(LETTERS))
                    perm = np.empty(NPERM)
                    for rep in range(NPERM):
                        q = rng.permutation(who)
                        perm[rep] = mi_bits(q[:-1], q[1:], len(LETTERS))
                    arm_mi = {}
                    for arm, draws in nulls.items():
                        got = [mi_bits(d[gate]["who"][:-1], d[gate]["who"][1:],
                                       len(LETTERS))
                               for d in draws if len(d[gate]["who"]) >= 3]
                        arm_mi[arm] = np.array(got) if got else np.array([np.nan])
                    trans.append({
                        "symbol": symbol, "tf": tf, "window": width, "gate": gate,
                        "n": len(who), "mi": real_mi,
                        "mi_perm": float(np.mean(perm)), "perm_p": upper_p(real_mi, perm),
                        "mi_iid": float(np.nanmean(arm_mi["iid"])),
                        "iid_p": upper_p(real_mi, arm_mi["iid"]),
                        "mi_dayblock": float(np.nanmean(arm_mi["dayblock"])),
                        "dayblock_p": upper_p(real_mi, arm_mi["dayblock"]),
                    })

            # ---- the conditional channels -----------------------------
            # Read on two gates. `strict` is the absolute one the census uses;
            # `rank` is the balanced one, and it is the only gate on which a W
            # and an M have comparable samples.
            for gate in COND_GATES:
                hits, who = real[gate]["hits"], real[gate]["who"]
                if len(hits) == 0:
                    continue
                occ = np.zeros(nbin, dtype=bool)
                occ[hits] = True
                twin_hits, twin_who = twin[gate]["hits"], twin[gate]["who"]
                twin_occ = np.zeros(nbin, dtype=bool)
                twin_occ[twin_hits] = True
                for li, name in enumerate(LETTERS):
                    mine = hits[who == li] if len(who) else np.empty(0, int)
                    mine = mine[bin_ok[mine]] if len(mine) else mine
                    if len(mine) == 0:
                        continue
                    picked = np.zeros(nbin, dtype=bool)
                    picked[mine] = True
                    plc = matched(picked, bin_ok & ~occ, cell, rng)
                    tmine = twin_hits[twin_who == li] if len(twin_who) else np.empty(0, int)
                    tmine = tmine[twin_ok[tmine]] if len(tmine) else tmine
                    tpicked = np.zeros(nbin, dtype=bool)
                    if len(tmine):
                        tpicked[tmine] = True
                    tplc = matched(tpicked, twin_ok & ~twin_occ, twin_cell, rng)
                    for k in HORIZONS:
                        mv, rv = fwd[k]
                        ev = mine[np.isfinite(rv[mine])]
                        pv = plc[np.isfinite(rv[plc])] if len(plc) else plc
                        if len(ev) == 0:
                            continue
                        d_rv, lo, hi, p = boot_gap(dayb[ev], rv[ev],
                                                   dayb[pv], rv[pv], rng) if len(pv) \
                            else (np.nan,) * 4
                        tmv, trv = twin_fwd[k]
                        tev = tmine[np.isfinite(trv[tmine])] if len(tmine) else tmine
                        tpv = tplc[np.isfinite(trv[tplc])] if len(tplc) else tplc
                        t_drv = float(trv[tev].mean() - trv[tpv].mean()) if (
                            len(tev) and len(tpv)) else np.nan
                        quiet = ev[np.abs(zbar[ev]) < IMPULSE_Z]
                        qpv = pv[np.abs(zbar[pv]) < IMPULSE_Z] if len(pv) else pv
                        d_quiet = float(rv[quiet].mean() - rv[qpv].mean()) if (
                            len(quiet) and len(qpv)) else np.nan
                        vol_rows.append({
                            "symbol": symbol, "tf": tf, "window": width, "gate": gate,
                            "letter": name, "k": k, "n": len(ev), "placebo_n": len(pv),
                            "rv": float(rv[ev].mean()),
                            "rv_placebo": float(rv[pv].mean()) if len(pv) else np.nan,
                            "d_rv": d_rv, "d_lo": lo, "d_hi": hi, "p": p,
                            "d_rv_twin": t_drv, "d_rv_quiet": d_quiet,
                            "impulse_share": float(np.mean(np.abs(zbar[ev]) >= IMPULSE_Z)),
                            "n_quiet": len(quiet),
                        })
                        # ---- the trade arm, expected null ------------------
                        # The **opposite** arm is exactly minus this reading,
                        # so it is not measured separately.
                        side = SIDE[name]
                        cont = side * mv[ev]
                        cmean, clo, chi, cp = boot_mean(dayb[ev], cont, rng)
                        tcont = side * tmv[tev] if len(tev) else np.empty(0)
                        dir_rows.append({
                            "symbol": symbol, "tf": tf, "window": width, "gate": gate,
                            "letter": name, "k": k, "n": len(ev), "side": side,
                            "cont": cmean, "lo": clo, "hi": chi, "p": cp,
                            "cont_twin": float(tcont.mean()) if len(tcont) else np.nan,
                            "n_twin": len(tev),
                            "round_trip_quoted": cost_quoted,
                            "round_trip_stored": cost_vol,
                            "net_quoted": cmean - cost_quoted,
                        })
                    # ---- the barrier arm, at the headline cell only --------
                    if (tf, width, gate) == HEADLINE[:3]:
                        res, stop = barrier(real_r, vol, mine,
                                            np.full(len(mine), SIDE[name]))
                        done = res >= 0
                        if done.sum() >= 1:
                            win = float(res[done].mean())
                            cost_r = float(np.nanmedian(quoted / stop[done]))
                            tres, _ = barrier(twin_r, twin_vol, tmine,
                                              np.full(len(tmine), SIDE[name])) \
                                if len(tmine) else (np.empty(0), np.empty(0))
                            tdone = tres >= 0 if len(tres) else np.empty(0, bool)
                            dir_rows.append({
                                "symbol": symbol, "tf": tf, "window": width,
                                "gate": gate, "letter": name, "k": -1,
                                "n": int(done.sum()), "side": SIDE[name],
                                "cont": win, "lo": np.nan, "hi": np.nan, "p": np.nan,
                                "cont_twin": float(tres[tdone].mean())
                                if tdone.sum() else np.nan,
                                "n_twin": int(tdone.sum()),
                                "round_trip_quoted": cost_r,
                                "round_trip_stored": np.nan,
                                "net_quoted": win * RR - (1 - win) - cost_r,
                            })
        print(f"  {symbol} {tf}: {nbin} bars done", file=sys.stderr, flush=True)
    print(f"{symbol}: {len(df)} base bars, "
          f"{(ts15[-1] - ts15[0]) / 86400 / 365.25:.1f}y, "
          f"{len(census)} census rows, {len(trans)} transition rows, "
          f"{len(vol_rows)} vol rows, {time.time() - started:.0f}s",
          file=sys.stderr, flush=True)
    return {"census": census, "trans": trans, "vol": vol_rows, "dir": dir_rows}


# --------------------------------------------------------------------------
# power
# --------------------------------------------------------------------------
PLANT_RATE = (0.0, 0.10, 0.25, 0.50, 1.00, 2.00)
PLANT_VOL = (0.0, 0.02, 0.05, 0.10, 0.20)
PLANT_DRIFT = (0.0, 0.02, 0.05, 0.10, 0.20)
POWER_LETTERS = ("V", "A", "W", "M")
POWER_WINDOWS = (24, 48)
POWER_TF = "15m"


def splice(r: np.ndarray, width: int, name: str, count: int, scale: float, rng
           ) -> np.ndarray:
    """Overwrite `count` disjoint stretches of `width` returns with the
    letter's own increments, scaled to the series' typical move. This is the
    census plant: it adds shapes and nothing else."""
    out = r.copy()
    temp = template(name, width)
    step = np.diff(temp, prepend=temp[0])
    step = step / (np.abs(step).mean() or 1.0) * scale
    n = len(r)
    if count <= 0:
        return out
    spots = rng.choice(np.arange(0, n - width - 1), size=min(count, (n - width) // width),
                       replace=False)
    spots = np.sort(spots)
    last = -10**9
    for s in spots:
        if s - last < width:
            continue
        out[s:s + width] = step
        last = s
    return out


def one_power(job: tuple[str, int, dict]) -> list[dict]:
    symbol, seat, cal = job
    rng = np.random.default_rng([SEED, 9_000 + seat])
    df = frame(symbol)
    if df is None:
        raise SystemExit(f"{symbol}: no usable bars")
    r15 = df.r.to_numpy(float)
    ts15 = df.ts.to_numpy()
    seconds = TIMEFRAMES[POWER_TF]
    tsb, inv = bins(ts15, seconds)
    nbin = len(tsb)
    base_r = regrid(r15, inv, nbin)
    dayb = (tsb // 86_400).astype(np.int64)
    scale = float(np.abs(base_r).mean())
    rows: list[dict] = []
    for width in POWER_WINDOWS:
        nulls = [census_rows(np.cumsum(rng.permutation(base_r)), tsb, width, cal)
                 for _ in range(NSHUF)]
        base = census_rows(np.cumsum(base_r), tsb, width, cal, want_rank=True)
        for name in POWER_LETTERS:
            li = LETTERS.index(name)
            seen = int((base["strict"]["who"] == li).sum())
            null_rates = np.array([
                (np.bincount(d["strict"]["who"], minlength=len(LETTERS))[li]
                 if len(d["strict"]["who"]) else 0) / max(d["strict"]["nwin"], 1)
                for d in nulls])
            # ---- the census plant --------------------------------------
            for mult in PLANT_RATE:
                planted = splice(base_r, width, name, round(seen * mult), scale, rng)
                got = census_rows(np.cumsum(planted), tsb, width, cal)
                who = got["strict"]["who"]
                rate = ((np.bincount(who, minlength=len(LETTERS))[li] if len(who) else 0)
                        / max(got["strict"]["nwin"], 1))
                rows.append({"kind": "census", "symbol": symbol, "window": width,
                             "letter": name, "plant": mult, "rate": rate,
                             "null_rate": float(null_rates.mean()),
                             "p": rank_p(rate, null_rates),
                             "n": int(round(rate * got["strict"]["nwin"]))})
            # ---- the risk and direction plants --------------------------
            vol = ewma_abs(base_r, VOL_SPAN)
            state = pd.Series(vol).rolling(STATE_WIN, min_periods=STATE_MIN).rank(
                pct=True).to_numpy()
            hour = pd.to_datetime(tsb, unit="s", utc=True).hour.to_numpy()
            bin_ok = np.isfinite(vol) & np.isfinite(state)
            cell = np.where(bin_ok, np.clip((state * STATE_BINS).astype(int), 0,
                                            STATE_BINS - 1) * 24 + hour, 0)
            # The risk and direction plants run on the `rank` gate, because
            # that is the gate the conditional channels are read on and a
            # four-leg letter has about three events on the absolute one.
            hits = base["rank"]["hits"]
            who = base["rank"]["who"]
            mine = hits[who == li] if len(who) else np.empty(0, int)
            mine = mine[bin_ok[mine]] if len(mine) else mine
            if len(mine) < 30:
                continue
            occ = np.zeros(nbin, dtype=bool)
            occ[hits] = True
            picked = np.zeros(nbin, dtype=bool)
            picked[mine] = True
            plc = matched(picked, bin_ok & ~occ, cell, rng)
            k = HEADLINE[3]
            for lift in PLANT_VOL:
                rr = base_r.copy()
                for off in range(1, k + 1):
                    live = mine[mine + off < nbin]
                    hit = live + off
                    rr[hit] = np.sign(rr[hit]) * (np.abs(rr[hit]) + lift * vol[live])
                _, rv = outcomes(rr, vol, k)
                ev = mine[np.isfinite(rv[mine])]
                pv = plc[np.isfinite(rv[plc])]
                d, _, _, p = boot_gap(dayb[ev], rv[ev], dayb[pv], rv[pv], rng)
                rows.append({"kind": "risk", "symbol": symbol, "window": width,
                             "letter": name, "plant": lift, "rate": d,
                             "null_rate": np.nan, "p": p, "n": len(ev)})
            for drift in PLANT_DRIFT:
                rr = base_r.copy()
                live = mine[mine + 1 < nbin]
                rr[live + 1] = rr[live + 1] + SIDE[name] * drift * vol[live]
                mv, _ = outcomes(rr, vol, k)
                ev = mine[np.isfinite(mv[mine])]
                cont = SIDE[name] * mv[ev]
                m, _, _, p = boot_mean(dayb[ev], cont, rng)
                rows.append({"kind": "direction", "symbol": symbol, "window": width,
                             "letter": name, "plant": drift, "rate": m,
                             "null_rate": np.nan, "p": p, "n": len(ev)})
    print(f"{symbol}: {len(rows)} power rows", file=sys.stderr, flush=True)
    return rows


# --------------------------------------------------------------------------
def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    print(f"part={PART} base={BASE} nshuf={NSHUF} boot={BOOT}", file=sys.stderr)
    cal = calibrate()
    symbols = list(TRADED + SYNTH) if PART == "main" else list(SYNTH)
    if PART == "pilot":
        symbols = ["EURUSD"]
    jobs = [(s, i, cal) for i, s in enumerate(symbols)]
    work = one_power if PART == "power" else one_symbol
    with Pool(min(len(jobs), int(os.environ.get("WORKERS", "12")))) as pool:
        got = pool.map(work, jobs)
    if PART == "power":
        rows = [r for part in got for r in part]
        if not rows:
            raise SystemExit("power: 0 rows - refusing to exit 0 on an empty run")
        pd.DataFrame(rows).to_csv(f"{OUT}/power.csv", index=False)
        print(f"power.csv: {len(rows)} rows", file=sys.stderr)
        return
    merged = {key: [r for part in got for r in part[key]]
              for key in ("census", "trans", "vol", "dir")}
    for key, rows in merged.items():
        if not rows:
            raise SystemExit(f"{key}: 0 rows - refusing to exit 0 on an empty run")
        frame_ = pd.DataFrame(rows)
        if key == "census":
            for arm in ("iid", "dayblock"):
                frame_[f"{arm}_bh"] = bh(frame_[f"{arm}_p"].to_numpy())
        if key == "trans":
            frame_["perm_bh"] = bh(frame_["perm_p"].to_numpy())
        if key == "vol":
            frame_["bh"] = bh(frame_["p"].to_numpy())
        if key == "dir":
            frame_["bh"] = bh(frame_["p"].to_numpy())
        frame_.to_csv(f"{OUT}/{key}.csv", index=False)
        print(f"{key}.csv: {len(frame_)} rows", file=sys.stderr)


if __name__ == "__main__":
    main()
