"""Does a regime-aware exit beat the constant hold clock, out of sample?

The question is the first entry of docs/todo.md: the desk's trades close on a fixed
`hold_seconds` far more often than at a stop or target, and every hold is a constant
somebody chose. Bayesian online changepoint detection (Adams & MacKay 2007) infers how
long the current regime has run; Agudelo-Espana et al. (UAI 2020) extend it to how long
it has *left* - residual time. If the regime the trade was entered in can be seen to end,
or to be about to end, an exit on that should beat a clock that knows nothing.

## Populations

* **live** - the desk's own closed trades (journal `trading/outcome`), joined to the
  `trading/decision` that opened them for `hold_seconds`. Side, stop distance and target
  distance are the trade's own; the path is re-run on 3m bars. `snap` (a 120s clock,
  under one bar) and trades on feeds with no bars (cash indices, oil) drop out.
* **signals** - every `structures/decision` of shape `level` with a direction, on the
  1m-30m intervals the desk trades, turned into a trade with one of three geometries
  read off the book (`trading/strategies/opportunity.py` and the live decisions):

      thesis   stop max(risk_vol, 4)v, target |push|v,  clock 1800s  (as it ran: ~0.37 R:R)
      scalp    stop max(risk_vol, 1)v, target |push|v,  clock 1800s  (level-scalp)
      runner   stop max(risk_vol, 1)v, target 3|push|v, clock 14400s (runner)

  v = the decision's own `vol_bps` x price, which reproduces the live `risk_price`
  exactly. Entries are thinned per symbol so no two overlap even under the longest
  exit compared (the cap), so every exit is scored on the same, independent trades.

## Exits compared, all on the same trades

  const     the trade's own clock (the constant hold)
  none      stop / target only, closed at the cap (4 x the clock, at most 16h)
  median    exit after the median bars-to-exit of *winning* training trades (the dumb
            re-tuned constant the brief asked for)
  best_k    the constant hold that scored best on the training block (a fairer dumb
            control: any tuned rule has to beat the best tuned constant)
  cp        exit when P(a changepoint since entry | bars so far) > theta   (BOCPD)
  resid     exit when the posterior expected residual time drops below rho x its
            pre-test median                                                 (residual time)
  rclock    at entry, set the clock to alpha x the posterior expected residual time
  random    exit each bar with the probability `cp` fired per bar on the training block
            (the MQL5 article's control: timing must beat matched-frequency noise)

Thresholds (theta, rho, alpha, best_k) are chosen on the first 60% of each population
by time and frozen; everything reported is the last 40%, with its two halves separately.

## The regime model

BOCPD with a Normal-Gamma observation model (unknown mean and variance) on 3m log
returns divided by a slow, lagged EWMA of |r| (half-life two days) and clipped at 8,
so a threshold means the same on EURUSD and Boom. The run-length prior is a discrete
Weibull duration with mean-scale lambda and shape k: k = 1 is the constant hazard of
plain BOCPD - memoryless, residual time a constant - and k != 1 is the case in which
residual time carries information. (lambda, k) is chosen per symbol by the one-step
predictive log-likelihood on bars before the test block. Residual time given run
length r is the Weibull's mean residual life, averaged over the run-length posterior.
**That is the residual-time quantity of Agudelo-Espana et al. with the duration
parameters fitted offline by likelihood rather than inferred online** - the online
hyper-parameter learning of their paper is not implemented.

## Guards

* Look-ahead: the posterior at bar t uses bars <= t, and every rule that fires at the
  close of bar t fills at the **open of bar t+1**. Entry is the open of the first bar
  opening at least one bar after the decision time, whatever the bar-time convention.
* Barrier booking: stops and targets resolve on wicks through `bars.race` - fill at the
  level or at the open on a gap, a bar spanning both levels is the stop.
* Clock alignment between the journal and the bars is checked against the live trades'
  own fill prices before anything is scored (see `align`).
* Costs: one round-trip spread per trade in R, at questions.py's COST_V in M5
  volatility units (synthetics 0.17v from catalogue.md), with M5 volatility taken from
  the trailing 500 3m bars before entry. Every exit pays exactly the same spread on the same trade, so the
  *comparison* between exits is cost-free by construction; costs only move levels.

Run on the lab (bars and journal live there):

    ./.secrets/lab.sh run research/harness/holdclock.py [PROCS=12]

Stages are cached under HOLDCLOCK_CACHE (default ~/till_infinity/data/holdclock).
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import gammaln

sys.path.insert(0, str(Path(__file__).parent))
from bars import Bars, race  # noqa: E402

HOME = Path(os.path.expanduser("~")) / "till_infinity" / "data"
JOURNAL = HOME / "journal.db"
SEQLAB = HOME / "seqlab"
CACHE = Path(os.environ.get("HOLDCLOCK_CACHE", HOME / "holdclock"))
PROCS = int(os.environ.get("PROCS", "12"))
BAR = 180  # 3m bars, the finest the lab holds for the journal's weeks
KMAX = 320  # 16h: the longest cap, and the widest run-length CDF kept per bar
RMAX = 1200  # run-length truncation for BOCPD (2.5 days of 3m bars)
TRAIN = 0.6

GEOMETRY = {  # stop floor v, target multiple of |push|, clock seconds
    "thesis": (4.0, 1.0, 1800),
    "scalp": (1.0, 1.0, 1800),
    "runner": (1.0, 3.0, 14400),
}
ALIAS = {"gold": "XAUUSD", "silver": "XAGUSD", "btc": "BTCUSD", "eth": "ETHUSD", "sol": "SOLUSD"}
LAM = [5, 15, 30, 60, 240, 960]  # mean-scale of the Weibull duration, in bars (15m to 2 days)
SHAPE = [0.25, 0.4, 0.6, 1.0, 1.6, 3.0]  # k = 1 is the flat hazard
#: Round-trip spread in M5 volatility units: questions.py's COST_V, and the synthetics'
#: measured median from catalogue.md. The bars' own `spread` column is not used for the
#: cost: its ETHUSD value is 58,000 points (2.3% of price at any plausible point size),
#: so it cannot be trusted per symbol. It only moves levels - see the docstring.
COST_V = {"fx": 0.8, "metal": 0.16, "crypto": 0.5, "index": 0.5, "synthetic": 0.17}
THETA = [0.3, 0.5, 0.7, 0.9]
RHO = [0.5, 0.7, 0.85, 1.0, 1.2]
ALPHA = [0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
KGRID = [1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 60, 80, 120, 160, 240, 320]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- bars and symbols

def symbols():
    return sorted(p.name[: -len(".3m.npz")] for p in SEQLAB.glob("*.3m.npz"))


def symbol_of(feed, known):
    if not isinstance(feed, str):
        return None
    f = feed.strip().lower().replace(" ", "_")
    if f in ALIAS:
        return ALIAS[f]
    return known.get(f)


def family(sym):
    if sym in ("XAUUSD", "XAGUSD"):
        return "metal"
    if sym in ("BTCUSD", "ETHUSD", "SOLUSD"):
        return "crypto"
    if len(sym) == 6 and sym.isupper():
        return "fx"
    return "synthetic"


def subfamily(sym):
    s = sym.lower()
    for key, name in (("volatility", "volatility"), ("boom", "boom/crash"), ("crash", "boom/crash"),
                      ("jump", "jump"), ("step", "step"), ("range_break", "range break")):
        if key in s:
            return name
    return family(sym) if family(sym) != "synthetic" else "other synthetic"


def load_bars(sym):
    z = np.load(SEQLAB / f"{sym}.3m.npz")  # never allow_pickle
    d = {k: np.asarray(z[k], float) for k in ("time", "open", "high", "low", "close", "spread")}
    o = np.argsort(d["time"], kind="stable")
    d = {k: v[o] for k, v in d.items()}
    keep = np.r_[True, np.diff(d["time"]) > 0]
    d = {k: v[keep] for k, v in d.items()}
    c = np.unique(np.round(d["close"], 8))
    step = np.diff(c)
    step = step[step > 0]
    d["point"] = float(np.round(step.min(), 8)) if len(step) else 0.0
    # trailing M5 volatility in price units, known before each bar opens
    a = np.abs(np.diff(d["close"], prepend=d["close"][0]))
    d["v5"] = pd.Series(a).rolling(500, min_periods=100).mean().shift(1).to_numpy() * np.sqrt(5 / 3)
    return d


# ---------------------------------------------------------------- populations

def journal():
    return sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True)


def live_trades(known):
    c = journal()
    out = [dict(json.loads(ctx), _t=t) for t, ctx in
           c.execute("select time, context from entries where actor='trading' and kind='outcome'")]
    dec = [dict(json.loads(ctx), _t=t) for t, ctx in
           c.execute("select time, context from entries where actor='trading' and kind='decision'")]
    o, d = pd.DataFrame(out), pd.DataFrame(dec)
    o["t_entry"] = o["_t"] - o["seconds"].astype(float)
    # The decision that opened it: same strategy, feed, side and level, latest before entry.
    hold = []
    for _, r in o.iterrows():
        m = d[(d.strategy == r.strategy) & (d.feed == r.feed) & (d.side == r.side)
              & (d._t <= r.t_entry + 5)]
        if isinstance(r.get("level_id"), str):
            m2 = m[m.level_id == r.level_id]
            m = m2 if len(m2) else m
        hold.append(float(m.sort_values("_t").hold_seconds.iloc[-1]) if len(m) else np.nan)
    o["hold_s"] = hold
    o["symbol"] = [symbol_of(f, known) for f in o.feed]
    o["side_s"] = np.where(o.side == "buy", 1.0, -1.0)
    o["stop_d"] = (o.entry - o.stop).abs()
    o["target_d"] = (o.target - o.entry).abs()
    o["geometry"] = o.strategy.replace("", "(none)")
    o["population"] = "live"
    o["t_decision"] = o.t_entry
    keep = o.symbol.notna() & o.hold_s.notna() & (o.hold_s >= 2 * BAR) & (o.stop_d > 0) & (o.target_d > 0)
    log(f"live: {len(o)} closed, {keep.sum()} with bars, a clock of >= 2 bars and a stop and target")
    cols = ["population", "geometry", "symbol", "t_decision", "side_s", "stop_d", "target_d", "hold_s",
            "exit_kind", "r_multiple", "strategy", "entry", "t_entry"]
    return o.loc[keep, cols].reset_index(drop=True)


def signal_trades(known):
    c = journal()
    q = """select time, json_extract(context,'$.feed'), json_extract(context,'$.interval'),
                  json_extract(context,'$.direction'), json_extract(context,'$.vol_bps'),
                  json_extract(context,'$.risk_vol'), json_extract(context,'$.expected_push_vol')
           from entries where actor='structures' and kind='decision'
             and json_extract(context,'$.shape')='level'"""
    s = pd.DataFrame(c.execute(q).fetchall(),
                     columns=["t_decision", "feed", "interval", "direction", "vol_bps", "risk_vol", "push"])
    s = s[s.interval.isin(["1m", "3m", "5m", "15m", "30m"]) & s.direction.isin(["up", "down"])]
    s["symbol"] = [symbol_of(f, known) for f in s.feed]
    s = s[s.symbol.notna()].copy()
    for k in ("vol_bps", "risk_vol", "push"):
        s[k] = pd.to_numeric(s[k], errors="coerce")
    s = s[(s.vol_bps > 0) & (s.risk_vol > 0) & (s.push.abs() > 0)]
    s["side_s"] = np.where(s.direction == "up", 1.0, -1.0)
    log(f"signals: {len(s)} level decisions on {s.symbol.nunique()} symbols with bars")
    return s.sort_values("t_decision").reset_index(drop=True)


# ---------------------------------------------------------------- BOCPD with a Weibull run-length prior

def weibull(lam, k, n):
    """Hazard h[r] and mean residual life m[r] for r = 0..n-1, discrete Weibull survival."""
    J = int(max(n + 2, 60 * lam))
    j = np.arange(J + 1, dtype=float)
    logS = -((j / lam) ** k)
    h = 1.0 - np.exp(logS[1: n + 1] - logS[:n])
    L = np.logaddexp.accumulate(logS[::-1])[::-1]  # log sum_{i>=r} S(i)
    m = np.exp(L[:n] - logS[:n])
    return np.clip(h, 1e-12, 1 - 1e-12), m


def standardise(close):
    r = np.diff(np.log(close), prepend=np.log(close[0]))
    a = np.abs(r)
    s = pd.Series(a).ewm(halflife=960, min_periods=200).mean().shift(1).to_numpy() * np.sqrt(np.pi / 2)
    s[~np.isfinite(s) | (s <= 0)] = np.nan
    z = np.clip(r / s, -8, 8)
    return np.nan_to_num(z, nan=0.0), np.isfinite(s)


def bocpd(z, valid, lam, k, split_t, times, window=None):
    """One causal pass. Returns log-evidence before `split_t`, and if `window` (lo, hi) is
    given the expected residual time for every bar and the run-length CDF (first KMAX) for
    bars inside the window."""
    n = len(z)
    h, mrl = weibull(lam, k, RMAX)
    mu0, k0, a0, b0 = 0.0, 1.0, 2.0, 1.5
    r = np.arange(RMAX, dtype=float)
    kap = k0 + r
    alp = a0 + r / 2
    cst = gammaln(alp + 0.5) - gammaln(alp) - 0.5 * np.log(np.pi * 2 * alp)
    mu = np.full(RMAX, mu0)
    beta = np.full(RMAX, b0)
    p = np.zeros(RMAX)
    p[0] = 1.0
    ll = 0.0
    ER = np.full(n, np.nan, np.float32)
    ERL = np.full(n, np.nan, np.float32)
    lo, hi = window if window else (n, n)
    cdf = np.zeros((max(hi - lo, 0), KMAX), np.float16)
    for t in range(n):
        x = z[t]
        if valid[t]:
            s2 = beta * (kap + 1) / (alp * kap)
            # Student-t predictive, 2*alpha degrees of freedom
            lp = cst - 0.5 * np.log(s2) - (alp + 0.5) * np.log1p((x - mu) ** 2 / (2 * alp * s2))
            m = lp.max()
            w = p * np.exp(lp - m)
            ev = w.sum()
            if times[t] < split_t:
                ll += m + np.log(ev)
            cp = (w * h).sum()
            g = w * (1 - h)
            new = np.empty(RMAX)
            new[0] = cp
            new[1:] = g[:-1]
            new[-1] += g[-1]
            p = new / new.sum()
            # sufficient statistics shift by one run-length; the last bin keeps its own
            mun = (kap * mu + x) / (kap + 1)
            bn = beta + kap * (x - mu) ** 2 / (2 * (kap + 1))
            mu[1:], beta[1:] = mun[:-1], bn[:-1]
            mu[-1], beta[-1] = mun[-1], bn[-1]
            mu[0], beta[0] = mu0, b0
        ER[t] = p @ mrl
        ERL[t] = p @ r
        if lo <= t < hi:
            cdf[t - lo] = np.cumsum(p[:KMAX])
    return ll, ER, ERL, cdf


def fit_symbol(args):
    sym, split_t, window_t = args
    b = load_bars(sym)
    z, valid = standardise(b["close"])
    t = b["time"]
    lls = {}
    for lam in LAM:
        for k in SHAPE:
            lls[(lam, k)] = bocpd(z, valid, lam, k, split_t, t)[0]
    best = max(lls, key=lls.get)
    flat = max((c for c in lls if c[1] == 1.0), key=lls.get)
    lo, hi = np.searchsorted(t, window_t[0]), np.searchsorted(t, window_t[1])
    out = {}
    for name, (lam, k) in (("fit", best), ("flat", flat)):
        _, ER, ERL, cdf = bocpd(z, valid, lam, k, split_t, t, (lo, hi))
        pre = t < split_t
        out[name] = dict(lam=lam, k=k, ER=ER, ERL=ERL, cdf=cdf, er_med=float(np.nanmedian(ER[pre])))
    np.savez(CACHE / f"{sym}.npz", lo=lo, hi=hi,
             **{f"{n}_{f}": v[f] for n, v in out.items() for f in ("ER", "ERL", "cdf")},
             **{f"{n}_meta": np.array([v["lam"], v["k"], v["er_med"]]) for n, v in out.items()})
    grid = {f"{lam}/{k}": v for (lam, k), v in lls.items()}
    return sym, grid, best, flat


# ---------------------------------------------------------------- trades on bars

def entry_bars(df, bars):
    """First bar opening at least one bar after the decision - safe whether a bar's
    stamp is its open or its close."""
    e = np.full(len(df), -1)
    for sym, idx in df.groupby("symbol").groups.items():
        t = bars[sym]["time"]
        e[df.index.get_indexer(idx)] = np.searchsorted(t, df.loc[idx, "t_decision"].to_numpy() + BAR)
    return e


def align(live, bars):
    """Is the journal's clock the bars' clock? The live fill price should sit inside the
    range of the bar holding the entry time; count how often, at offsets of whole hours."""
    res = {}
    for off in range(-4, 5):
        hit = tot = 0
        for _, r in live.iterrows():
            b = bars[r.symbol]
            i = np.searchsorted(b["time"], r.t_entry + off * 3600, side="right") - 1
            if 0 <= i < len(b["time"]) and r.t_entry + off * 3600 - b["time"][i] < BAR:
                tot += 1
                pt = b["point"] * b["spread"][i]
                hit += (b["low"][i] - pt <= r.entry <= b["high"][i] + pt)
        res[off] = hit / tot if tot else np.nan
    return res


def matrices(df, bars, cap):
    """Side-adjusted o/h/l/c relative to the entry open for bars e .. e+cap, NaN past the data."""
    n = len(df)
    O, Hh, Ll, C = (np.full((n, cap + 1), np.nan) for _ in range(4))
    entry = np.full(n, np.nan)
    spread = np.full(n, np.nan)
    for sym, g in df.groupby("symbol"):
        b = bars[sym]
        rows = df.index.get_indexer(g.index)
        for i, e in zip(rows, g.e.to_numpy()):
            j = min(len(b["time"]), e + cap + 1)
            if e >= len(b["time"]):
                continue
            m = j - e
            entry[i] = b["open"][e]
            spread[i] = COST_V[family(sym)] * b["v5"][e]
            for M, key in ((O, "open"), (Hh, "high"), (Ll, "low"), (C, "close")):
                M[i, :m] = b[key][e:j] - entry[i]
    s = df.side_s.to_numpy()
    P = Bars(O, Hh, Ll, C) * s
    return P, entry, spread


def resolve(P, up, dn, last):
    """R in stop units when the trade is closed by time at the open of bar last+1 unless the
    stop or target is touched on bars 0..last first. last = index of the deciding bar."""
    n, K = P.c.shape
    cols = np.arange(K)[None, :]
    live = cols <= last[:, None]
    Q = Bars(np.where(live, P.o, np.nan), np.where(live, P.h, np.nan), np.where(live, P.l, np.nan), P.c)
    w, fill = race(Q, up, dn)
    nxt = np.take_along_axis(P.o, np.minimum(last + 1, K - 1)[:, None], 1)[:, 0]
    R = np.where(w != 0, fill / dn, nxt / dn)
    return R, w


def first_fire(mask, cap_last):
    """Index of the first True per row, else the cap."""
    any_ = mask.any(1)
    return np.where(any_, mask.argmax(1), cap_last)


# ---------------------------------------------------------------- scoring

def stats(x):
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return n, np.nan, np.nan, np.nan
    se = x.std(ddof=1) / np.sqrt(n)
    return n, x.mean(), se, x.mean() / se if se > 0 else np.nan


def run():
    CACHE.mkdir(parents=True, exist_ok=True)
    syms = symbols()
    known = {s.lower(): s for s in syms}
    live = live_trades(known)
    sig = signal_trades(known)
    need = sorted(set(live.symbol) | set(sig.symbol))
    bars = {s: load_bars(s) for s in need}
    log("points:", {s: bars[s]["point"] for s in need})

    # ---- clock alignment before anything is scored
    al = align(live, bars)
    log("alignment, share of live fills inside the entry bar by hour offset:",
        {k: round(v, 3) for k, v in al.items()})
    if max(al, key=al.get) != 0:
        raise SystemExit("journal and bar clocks disagree - fix the offset before scoring")

    t_all = np.r_[sig.t_decision.to_numpy(), live.t_decision.to_numpy()]
    window_t = (t_all.min() - 2 * 86400, t_all.max() + 2 * 86400)
    split_sig = float(np.quantile(sig.t_decision, TRAIN))
    split_live = float(np.quantile(live.t_decision, TRAIN))
    split_t = min(split_sig, split_live)  # the duration model sees nothing of either test block
    log(f"split: signals {pd.to_datetime(split_sig, unit='s')}, live {pd.to_datetime(split_live, unit='s')}")

    # ---- the regime model, per symbol, in parallel
    todo = [s for s in need if not (CACHE / f"{s}.npz").exists()]
    log(f"BOCPD on {len(todo)} symbols ({len(need) - len(todo)} cached), {PROCS} processes")
    fits = {}
    if todo:
        with Pool(PROCS) as pool:
            for sym, grid, best, flat in pool.imap_unordered(fit_symbol, [(s, split_t, window_t) for s in todo]):
                fits[sym] = (grid, best, flat)
                log(f"  {sym:28s} best lambda={best[0]} k={best[1]}  flat lambda={flat[0]}  "
                    f"dLL(best-flat)={grid[f'{best[0]}/{best[1]}'] - grid[f'{flat[0]}/{flat[1]}']:.1f}")
        json.dump({s: {"grid": g, "best": b, "flat": f} for s, (g, b, f) in fits.items()},
                  open(CACHE / "fits.json", "w"))
    reg = {s: dict(np.load(CACHE / f"{s}.npz")) for s in need}

    print("\n## Is the hazard flat? (duration prior chosen by pre-test predictive likelihood)\n")
    ks = pd.DataFrame([(s, family(s), subfamily(s), *reg[s]["fit_meta"]) for s in need],
                      columns=["symbol", "family", "sub", "lambda", "k", "er_med"])
    print(ks.groupby("sub").agg(n=("k", "size"), k_flat=("k", lambda k: (k == 1).sum()),
                                k_below=("k", lambda k: (k < 1).sum()), k_above=("k", lambda k: (k > 1).sum()),
                                lam=("lambda", "median"), er_med=("er_med", "median")).to_string())
    if (CACHE / "fits.json").exists():
        fj = json.load(open(CACHE / "fits.json"))
        d = [(s, v["grid"][f"{v['best'][0]}/{v['best'][1]}"] - v["grid"][f"{v['flat'][0]}/{v['flat'][1]}"])
             for s, v in fj.items()]
        print("\nlog-likelihood gain of the best shape over the best flat hazard, per symbol:",
              ", ".join(f"{s} {g:.0f}" for s, g in sorted(d, key=lambda x: -x[1])))

    # ---- build the trade sets
    sets = []
    live = live.copy()
    live["e"] = entry_bars(live, bars)
    live["hold_b"] = np.ceil(live.hold_s / BAR).astype(int)
    live["cap"] = np.minimum(4 * live.hold_b, KMAX)
    live["hold_b"] = np.minimum(live.hold_b, live.cap)
    live["split"] = np.where(live.t_decision < split_live, "train", "test")
    sets.append(("live", live))
    for gname, (floor, tmult, clock) in GEOMETRY.items():
        s = sig.copy()
        s["e"] = entry_bars(s, bars)
        hold_b = int(np.ceil(clock / BAR))
        cap = min(4 * hold_b, KMAX)
        # thin: a new trade only once the previous one on the symbol is past the cap
        keep = np.zeros(len(s), bool)
        for sym, g in s.groupby("symbol"):
            last = -10**9
            for i, e in zip(df_rows(s, g), g.e.to_numpy()):
                if e >= last + cap + 1:
                    keep[i], last = True, e
        s = s[keep].reset_index(drop=True)
        s["population"], s["geometry"], s["strategy"] = "signals", gname, gname
        s["hold_b"], s["cap"] = hold_b, cap
        s["split"] = np.where(s.t_decision < split_sig, "train", "test")
        s["_floor"], s["_tmult"] = floor, tmult
        sets.append((gname, s))

    for name, df in sets:
        score(name, df, bars, reg)


def df_rows(df, g):
    return df.index.get_indexer(g.index)


def score(name, df, bars, reg):
    df = df[df.e < np.array([len(bars[s]["time"]) for s in df.symbol])].reset_index(drop=True)
    cap = int(df.cap.max())
    P, entry, spread = matrices(df, bars, cap)
    if name == "live":
        dn = df.stop_d.to_numpy()
        up = df.target_d.to_numpy()
    else:
        v = df.vol_bps.to_numpy() * entry / 1e4
        dn = np.maximum(df.risk_vol.to_numpy(), df._floor.to_numpy()) * v
        up = df._tmult.to_numpy() * df.push.abs().to_numpy() * v
    ok = np.isfinite(entry) & (dn > 0) & (up > 0) & np.isfinite(P.o[np.arange(len(df)), df.cap.to_numpy()])
    df, P = df[ok].reset_index(drop=True), Bars(P.o[ok], P.h[ok], P.l[ok], P.c[ok])
    dn, up, spread = dn[ok], up[ok], spread[ok]
    cost = spread / dn
    n = len(df)
    capl = df.cap.to_numpy() - 1  # deciding-bar index for "closed at the cap"
    holdl = df.hold_b.to_numpy() - 1
    tr = (df.split == "train").to_numpy()
    te = ~tr
    tmid = np.median(df.t_decision[te])
    half = np.where(df.t_decision < tmid, "A", "B")

    # regime series along each trade: P(r_t <= k) and E[residual] at bar e+k, k = 0..cap-1
    K = cap
    cpP = {m: np.full((n, K), np.nan) for m in ("fit", "flat")}
    ER = {m: np.full((n, K), np.nan) for m in ("fit", "flat")}
    ER0 = {m: np.full(n, np.nan) for m in ("fit", "flat")}
    ERmed = {m: np.full(n, np.nan) for m in ("fit", "flat")}
    for sym, g in df.groupby("symbol"):
        rg = reg[sym]
        lo = int(rg["lo"])
        rows = df.index.get_indexer(g.index)
        for m in ("fit", "flat"):
            cdf, er = rg[f"{m}_cdf"], rg[f"{m}_ER"]
            ERmed[m][rows] = rg[f"{m}_meta"][2]
            for i, e in zip(rows, g.e.to_numpy()):
                t = e + np.arange(K)
                ok_t = (t - lo >= 0) & (t - lo < len(cdf))
                kk = np.arange(K)
                cpP[m][i, ok_t] = cdf[t[ok_t] - lo, np.minimum(kk[ok_t], KMAX - 1)]
                tt = t[t < len(er)]
                ER[m][i, : len(tt)] = er[tt]
                ER0[m][i] = er[e - 1] if e >= 1 else np.nan
    cols = np.arange(K)[None, :]
    within = cols <= capl[:, None]

    def rule(last):
        last = np.minimum(last, capl)
        R, w = resolve(P, up, dn, last)
        return R - cost, w, last

    rules = {}
    base_R, base_w, _ = rule(holdl)
    rules["const"] = (base_R, base_w)
    none_R, none_w, _ = rule(capl)
    rules["none"] = (none_R, none_w)
    # bars-to-exit under no clock, for the winners' median
    none_bars = np.where(none_w != 0, first_touch(P, up, dn, capl), capl + 1)
    med = int(np.median(none_bars[tr & (none_R > 0)])) if (tr & (none_R > 0)).any() else int(np.median(holdl + 1))
    rules["median"] = rule(np.full(n, max(med, 1) - 1))[:2]
    trainmean = lambda R: np.nanmean(R[tr])
    cands = {k: rule(np.full(n, k - 1)) for k in KGRID if k <= cap}
    kbest = max(cands, key=lambda k: trainmean(cands[k][0]))
    rules["best_k"] = cands[kbest][:2]
    chosen = {"median": med, "best_k": kbest}
    fire_rate = {}
    cps_all = {}
    for m in ("fit", "flat"):
        cps = cps_all[m] = {}
        for th in THETA:
            last = first_fire((cpP[m] > th) & within, capl)
            cps[th] = (*rule(last)[:2], last)
        th = max(cps, key=lambda x: trainmean(cps[x][0]))
        rules[f"cp:{m}"] = cps[th][:2]
        chosen[f"cp:{m}"] = th
        lastc = cps[th][2]
        fire_rate[m] = np.nansum((lastc < capl)[tr]) / np.nansum((lastc + 1)[tr])
        rs = {}
        for rho in RHO:
            last = first_fire((ER[m] < rho * ERmed[m][:, None]) & within, capl)
            rs[rho] = rule(last)[:2]
        rho = max(rs, key=lambda x: trainmean(rs[x][0]))
        rules[f"resid:{m}"] = rs[rho]
        chosen[f"resid:{m}"] = rho
        if m == "fit":
            ac = {}
            for a in ALPHA:
                hb = np.clip(np.round(a * ER0[m]).astype(float), 1, capl + 1)
                hb = np.where(np.isfinite(hb), hb, holdl + 1).astype(int)
                ac[a] = rule(hb - 1)[:2]
            a = max(ac, key=lambda x: trainmean(ac[x][0]))
            rules["rclock"] = ac[a]
            chosen["rclock"] = a
    # the randomised control at the matched per-bar firing rate of cp:flat
    q = fire_rate["flat"]
    rng = np.random.default_rng(7)
    Rr = []
    for _ in range(20):
        last = first_fire((rng.random((n, K)) < q) & within, capl)
        Rr.append(rule(last)[0])
    rules["random"] = (np.mean(Rr, 0), np.zeros(n))
    chosen["random"] = round(q, 4)

    print(f"\n{name}: constant hold of k bars, mean net R on train / test (the whole hold curve)")
    print("  " + "  ".join(f"k={k}: {trainmean(v[0]):+.3f}/{np.nanmean(v[0][te]):+.3f}" for k, v in cands.items()))
    for m in ("fit", "flat"):
        print(f"  cp:{m} by theta, paired test difference over the clock: " + "  ".join(
            f"{th}: {np.nanmean((cps_all[m][th][0] - base_R)[te]):+.3f}" for th in THETA))
    real_clock = (df.exit_kind == "hold").to_numpy() if name == "live" else (base_w == 0)
    print(f"\n## {name}: {n} trades ({tr.sum()} train / {te.sum()} test), clock {int(df.hold_b.median())} bars, "
          f"cap {int(df.cap.median())} bars, median cost {np.nanmedian(cost):.3f}R")
    print("chosen on train:", chosen)
    if name == "live":
        sim_kind = np.where(base_w == 1, "target", np.where(base_w == -1, "stop", "hold"))
        rk = df.exit_kind.to_numpy()
        agree = np.mean(sim_kind[np.isin(rk, ["hold", "stop", "target"])] == rk[np.isin(rk, ["hold", "stop", "target"])])
        rr = df.r_multiple.astype(float).to_numpy()
        good = np.isfinite(rr) & (rr != 0)
        cor = np.corrcoef(rr[good], base_R[good] + cost[good])[0, 1] if good.sum() > 5 else np.nan
        print(f"fidelity: simulated constant-clock exit kind matches the real one on {agree:.1%}; "
              f"corr(real R, simulated gross R) = {cor:.2f} over {good.sum()} trades with a recorded R")
    rows = []
    for rn, (R, w) in rules.items():
        for sub, mask in (("all", te), ("clock-closed", te & real_clock)):
            nn, mean, se, t = stats(R[mask])
            dd = R[mask] - base_R[mask]
            _, dm, dse, dt = stats(dd)
            a = np.nanmean(R[mask & (half == "A")])
            b = np.nanmean(R[mask & (half == "B")])
            da = np.nanmean((R - base_R)[mask & (half == "A")])
            db = np.nanmean((R - base_R)[mask & (half == "B")])
            _, bm, _, bt = stats(R[mask] - rules["best_k"][0][mask])
            rows.append(dict(set=name, sub=sub, exit=rn, n=nn, net=mean, se=se, t=t, A=a, B=b,
                             d_const=dm, d_t=dt, dA=da, dB=db, d_bestk=bm, db_t=bt, train=trainmean(R),
                             clock=np.mean(w[mask] == 0) if rn != "random" else np.nan))
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(out.drop(columns="set").to_string(index=False, float_format=lambda x: f"{x:+.3f}"))
    # per family, per strategy: every rule's paired edge over the constant clock on the test block
    by = "strategy" if name == "live" else "sub"
    df["sub"] = [subfamily(s) for s in df.symbol]
    df["family"] = [family(s) for s in df.symbol]
    for grp in (["family", by] if by != "sub" else ["family", "sub"]):
        rows = []
        for gv, g in df[te].groupby(grp):
            idx = g.index.to_numpy()
            if len(idx) < 5:
                continue
            row = dict(group=gv, n=len(idx), const=np.nanmean(base_R[idx]))
            for rn in ("none", "median", "best_k", "cp:flat", "cp:fit", "resid:fit", "rclock", "random"):
                d = rules[rn][0][idx] - base_R[idx]
                _, dm, _, dt = stats(d)
                row[rn] = f"{dm:+.3f} ({dt:+.1f})"
            rows.append(row)
        if rows:
            print(f"\n{name}, test block by {grp}: net R under the clock, and each exit's paired difference (t)")
            print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:+.3f}"))
    out.to_csv(CACHE / f"result_{name}.csv", index=False)


def first_touch(P, up, dn, last):
    """Bars until the stop or target is touched (1-based), for trades that touch one."""
    n, K = P.c.shape
    upb, dnb = np.asarray(up, float)[:, None], np.asarray(dn, float)[:, None]
    hit = (P.h >= upb) | (P.l <= -dnb) | (P.o >= upb) | (P.o <= -dnb)
    hit &= np.arange(K)[None, :] <= last[:, None]
    return np.where(hit.any(1), hit.argmax(1) + 1, last + 1)


if __name__ == "__main__":
    run()
