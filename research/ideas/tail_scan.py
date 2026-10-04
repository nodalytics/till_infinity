"""The tail scan: which MCFL patterns reach high R multiples more often than randomness allows?

Frozen in `tail_rule.json` before the discovery run; the selected cells frozen in `tail_selected.json`
before the confirmation run. On a martingale P(+N R before -1 R) = 1/(N+1) for any rule, so a rule's
expected value is zero before costs whatever its reward:risk. The scan looks for patterns whose
P(>= N R) at large N exceeds both 1/(N+1) and the same pattern traded identically on matched iid and
GARCH walks - rare is fine.

Every directional MCFL event (v1 productions, v2 alphabets, the 64-row candlestick vocabulary, the
time core, changepoints) is traded at the next open after its known_at, in its own direction and
faded, with the stop beyond the pattern's own bars (or the 3-bar extreme) plus 0.1 ATR. Per trade:
the most R reached before the initial stop within 20 days (so P(>= N R) is a barrier probability),
and a 2-ATR trail exit net of costs.

  OUT=... CACHE=... MT5BT_DB=... MODE=discover|confirm|plot python research/ideas/tail_scan.py
  MODE=smoke SMOKE=venue,sym,iv,source   one series, events and trades counted (plumbing only)
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

OUT = Path(os.environ.get("OUT", ".data/tail"))
EVC = Path(os.environ.get("EVCACHE", str(OUT / "events")))
BIN = Path(os.environ.get("BINANCE", os.path.expanduser("~/till_infinity/data/binance")))
FRESH_DIR = Path(os.environ.get("CACHE", os.path.expanduser("~/till_infinity/data/binance_fresh")))
RULE = HERE / "tail_rule.json"
SELECTED = Path(os.environ.get("SELECTED", str(HERE / "tail_selected.json")))
WORKERS = int(os.environ.get("WORKERS", 12))

SEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
SPLIT = pd.Timestamp("2024-01-01", tz="UTC").timestamp()
HORIZON_DAYS = 20
DISC_END = SPLIT - HORIZON_DAYS * 86400  # no discovery trade's 20-day window reaches 2024
NS = (0.5, 1, 2, 3, 4, 5, 10, 20)
NNET = (4, 5, 10)
FEE = 0.0007
PAD, SLIP, TRAIL = 0.1, 0.05, 2.0
PATTERN_MAX_SPAN = 5  # the pattern's own bars set the stop if they start at most this many bars before known_at
WARMUP = 50
WALK_STEPS = 256
SOURCES = ("real", "iid", "garch")
MIN_N, MIN_WALK_N, K, Q = 300, 100, 15, 0.05
VARIANTS = ("ALL", "X12", "RZ")
EXCLUDE = {"CANDLE", "BAR_RELATION", "EPISODE"}
SEG_MAX, SEG_LEN, SEG_WARM = 60_000, 50_000, 5_000  # longer series are parsed in segments (memory)

COINS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX")
MT5_DISC = ("EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD EURJPY GBPJPY EURGBP AUDJPY USDCNH "
            "XAUUSD XAGUSD XPTUSD XPDUSD BTCUSD ETHUSD SOLUSD").split()
MT5_NEW = (["US SP 500", "US Tech 100", "Wall Street 30", "Germany 40", "UK 100", "Japan 225", "Australia 200",
            "US Oil", "UK Brent Oil", "XCUUSD"] +
           ("AAVUSD,ADAUSD,ALGUSD,APEUSD,APTUSD,AVAUSD,BATUSD,BCHUSD,BNBUSD,COMUSD,DOGUSD,DOTUSD,DSHUSD,"
            "ETCUSD,FILUSD,IMXUSD,IOTUSD,LNKUSD,LTCUSD,MLNUSD,NEOUSD,NERUSD,SANUSD,SHBUSD,TRUUSD,TRXUSD,"
            "UNIUSD,XLMUSD,XMRUSD,XRPUSD,XTZUSD,ZECUSD").split(","))
DERIV = ("Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index", "Volatility 75 Index",
         "Volatility 100 Index", "Step Index", "Step Index 200", "Step Index 500", "Drift Switch Index 10",
         "Drift Switch Index 20", "Drift Switch Index 30", "Jump 50 Index", "Boom 1000 Index", "Crash 1000 Index",
         "Range Break 100 Index")
_A = ("BTC ETH SOL AAVE ADA ALGO APE APT AVAX BAT BCH BNB COMP DOGE DOT DASH ETC FIL IMX IOTA LINK "
      "LTC NEO NEAR SAND 1000SHIB TRU TRX UNI XLM XMR XRP XTZ ZEC").split()
_B = ("ATOM EOS RUNE KAVA AXS MANA GALA CRV SNX MKR LDO GRT EGLD HBAR ICP THETA VET KSM ZIL CHZ ENJ "
      "1INCH SUSHI YFI OP ARB INJ FTM MATIC QTUM ONT OMG WAVES ICX ZRX COTI").split()
_C = ("1000LUNC 1000XEC ALICE ALPHA ANKR API3 ARPA AR ATA BAKE BAL BAND BEL BLZ BNX C98 CELO CELR CHR CTK CTSI CVC "
      "CVX DAR DENT DGB DUSK DYDX ENS FLM FLOW FTT GMT GTC HOT IOST IOTX JASMY KLAY KNC LINA LIT LPT LRC LUNA2 MASK "
      "MTL NKN OCEAN OGN ONE PEOPLE QNT RAY REEF REN RLC ROSE RSR RVN SC SFP SKL SPELL STG STMX STORJ TLM TRB UNFI "
      "WOO XEM ZEN").split()
FRESH = tuple(c for c in _A + _B if c not in COINS) + tuple(_C)  # turn_confirm's FRESH (58) and SET_C (73)


# ---------------------------------------------------------------- data

def load(venue, sym, iv):
    """The real series and its cost per bar in price (a round trip)."""
    if venue == "binance":
        try:
            z = np.load(BIN / f"{sym}USDT.klines.{iv}.npz")
        except OSError:
            return None, None
        df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close", "volume")}).rename(columns={"time": "ts"})
        df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        return df, FEE * df["close"].to_numpy(float)
    if venue == "fresh":
        path = FRESH_DIR / f"{sym}USDT.{iv}.npz"
        if not path.exists():
            return None, None
        z = np.load(path)
        df = pd.DataFrame({k: z[k] for k in ("ts", "open", "high", "low", "close", "volume")})
        df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        return df, FEE * df["close"].to_numpy(float)
    import run as R
    from mt5bt import load_specs
    R.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, iv)
    if df is None:
        return None, None
    df = df.reset_index(drop=True)[["ts", "open", "high", "low", "close", "volume"]]
    spec = load_specs(R.DB).get(sym)
    return df, np.full(len(df), R.spread_floor(sym, spec) * spec.point if spec is not None else 0.0)


def atr_of(df):
    from mcfl import candles
    return np.asarray(candles.table(df)["atr"], float)


def series(venue, sym, iv, source):
    """Bars and each bar's cost in ATR units; a walk keeps the real series' clock and its cost in ATR."""
    from mcfl import synth
    df, fee_px = load(venue, sym, iv)
    if df is None or len(df) < 300:
        return None, None
    cost_atr = fee_px / np.maximum(atr_of(df), 1e-12)
    cost_atr = np.where(np.isfinite(cost_atr), cost_atr, np.nanmedian(cost_atr))
    if source != "real":
        ts, n = df["ts"].to_numpy(), len(df)
        sigma = float(np.std(np.diff(df["close"].to_numpy(float))))
        seed = zlib.crc32(f"{venue}{sym}{iv}{source}".encode()) % 100000
        gen = synth.walk if source == "iid" else synth.garch
        df = gen(n, sigma=sigma, seed=seed, steps=WALK_STEPS).reset_index(drop=True).iloc[:n]
        df["ts"] = ts[:len(df)]
        df["volume"] = 0.0
        df = df[["ts", "open", "high", "low", "close", "volume"]]
        cost_atr = cost_atr[:len(df)]
    return df.reset_index(drop=True), cost_atr


def key_of(e):
    """The cell name of a directional entity, or None."""
    t = e.type
    if t in EXCLUDE or e.dir.value == "NONE":
        return None
    if t == "PATTERN":
        return f"PATTERN:{e.get('name')}"
    if t == "SWING":
        return f"SWING:{e.get('label')}"
    if t == "BREAK":
        return f"BREAK:{e.get('vs_structure')}"
    if t == "POOL_TAKEN":
        return "POOL_TAKEN:" + ("SWEEP" if e.get("closed_back") else "TAKE")
    if t in ("IN_WINDOW", "LATE", "EARLY"):
        return f"{t}:{e.get('of_type')}"
    if t == "TIMEOUT":
        return f"TIMEOUT:{e.get('kind')}"
    return t


def parse_events(df):
    """Every directional event: its cell name, direction, known_at and its first CANDLE part's bar.
    A series longer than SEG_MAX bars is parsed in SEG_LEN-bar segments, each read with the SEG_WARM
    bars before it as warm-up; an event is kept from the segment in which it became known."""
    from mcfl.parse import parse
    n = len(df)
    segs = [(0, n)] if n <= SEG_MAX else [(a, min(n, a + SEG_LEN)) for a in range(0, n, SEG_LEN)]
    rows = []
    for a, b in segs:
        w = max(0, a - SEG_WARM)
        ch = parse(df.iloc[w:b].reset_index(drop=True), changepoints=True)
        for e in ch.entities:
            k = key_of(e)
            t = int(e.known_at) + w
            if k is None or not a <= t < b:
                continue
            bars = [int(p.split(".")[2]) + w for p in e.parts if p.startswith("CANDLE.")]
            rows.append((k, 1 if e.dir.value == "UP" else -1, t, min(bars) if bars else -1))
        del ch
    ev = pd.DataFrame(rows, columns=["key", "d", "t", "p0"])
    return ev.sort_values(["key", "d", "t", "p0"]).drop_duplicates(["key", "d", "t"]).reset_index(drop=True)


def cached(job):
    """(df, cost_atr, events) of one series, parsed once and kept. The pickles are this script's own
    output on the lab's disk, read back only by it."""
    venue, sym, iv, source = job
    EVC.mkdir(parents=True, exist_ok=True)
    path = EVC / f"{venue}_{sym.replace(' ', '_')}_{iv}_{source}.pkl"
    if path.exists():
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except (EOFError, pickle.UnpicklingError):
            pass
    df, cost_atr = series(venue, sym, iv, source)
    if df is None:
        out = (None, None, None)
    else:
        t0 = time.time()
        ev = parse_events(df)
        print(f"  parsed {venue} {sym} {iv} {source}: {len(df)} bars, {len(ev)} events, {time.time() - t0:.0f}s", flush=True)
        out = (df, cost_atr, ev)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(out, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.rename(path)
    return out


# ---------------------------------------------------------------- trades

def frame_arrays(df, f):
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    return (o, h, l, c) if f > 0 else (-o, -l, -h, -c)


def outcomes(o, h, l, c, a, cost_px, t, stop, H, chunk=None):
    """Longs (in this frame) entered at the open of t+1 with initial stop `stop`: the most R reached
    before the initial stop within H bars (a bar that reaches the stop counts as stopped first), and E1
    (a 2-ATR(t) trail behind completed bars' best high, 0.05 ATR slippage on stop fills, out at the
    close of t+H at most) net of the round-trip cost. R against the initial risk."""
    n = len(c)
    chunk = chunk or max(500, 4_000_000 // H)
    pad = lambda x: np.r_[x, np.full(H + 2, np.nan)]  # noqa: E731
    op, hp, lp = pad(o), pad(h), pad(l)
    m = len(t)
    mfe, e1 = np.empty(m), np.empty(m)
    cols = np.arange(H)
    for s in range(0, m, chunk):
        tt, st = t[s:s + chunk], stop[s:s + chunk]
        entry = o[tt + 1]
        risk = entry - st
        at = a[tt]
        idx = tt[:, None] + 1 + cols
        L, Hh, O = lp[idx], hp[idx], op[idx]
        hit = L <= st[:, None]
        first = np.where(hit.any(1), hit.argmax(1), H)
        best = np.where(cols < first[:, None], Hh, -np.inf)
        mx = np.max(np.nan_to_num(best, nan=-np.inf), axis=1)
        with np.errstate(over="ignore", invalid="ignore"):
            mfe[s:s + chunk] = np.maximum(0.0, (mx - entry) / risk)
        cm = np.maximum.accumulate(np.nan_to_num(Hh, nan=-np.inf), axis=1)
        prior = np.concatenate([np.full((len(tt), 1), -np.inf), cm[:, :-1]], axis=1)
        trail = np.maximum(st[:, None], np.maximum(entry[:, None], prior) - TRAIL * at[:, None])
        trail[:, 0] = st
        ex = L <= trail
        fx = np.where(ex.any(1), ex.argmax(1), -1)
        rr = np.arange(len(tt))
        px = np.where(fx > 0, np.minimum(O[rr, np.maximum(fx, 0)], trail[rr, np.maximum(fx, 0)]), st) - SLIP * at
        px = np.where(fx >= 0, px, c[np.minimum(n - 1, tt + H)])
        e1[s:s + chunk] = (px - entry) / risk - cost_px[s:s + chunk] / risk
    return mfe, e1


def flags(df):
    """Per bar and frame: at a 12-bar low of the frame (the 3-bar low at or under the 9 bars before),
    and the bar's range z (against the 10 bars before) in the top decile of its last 1,000 bars' z."""
    h, l = df["high"].to_numpy(float), df["low"].to_numpy(float)
    out = {}
    for f in (1, -1):
        lo = l if f > 0 else -h
        low3 = pd.Series(lo).rolling(3).min().to_numpy()
        prior = pd.Series(lo).shift(3).rolling(9).min().to_numpy()
        out[f] = low3 <= prior
    rng_ = pd.Series(h - l)
    rz = (rng_ - rng_.rolling(10).mean().shift(1)) / rng_.rolling(10).std().shift(1)
    q = rz.rolling(1000, min_periods=200).quantile(0.9).shift(1)
    out["RZ"] = (rz >= q).to_numpy()
    return out


def trades(df, cost_atr, ev, iv, lo_ts=None, hi_ts=None, cells=None):
    """Every event traded with its direction (W) and faded (F). One row per trade, with the event's
    variant flags. `cells`: restrict to these (key, mode) pairs. Signal bars with lo_ts <= ts < hi_ts."""
    n = len(df)
    ts = df["ts"].to_numpy()
    a = atr_of(df)
    H = int(HORIZON_DAYS * 86400 / SEC[iv])
    fl = flags(df)
    ev = ev[(ev["t"] >= WARMUP) & (ev["t"] + 1 < n)]
    if lo_ts is not None:
        ev = ev[ts[ev["t"].to_numpy()] >= lo_ts]
    if hi_ts is not None:
        ev = ev[ts[ev["t"].to_numpy()] < hi_ts]
    if cells is not None:
        keys = {k for k, _ in cells}
        ev = ev[ev["key"].isin(keys)]
    if not len(ev):
        return pd.DataFrame()
    t = ev["t"].to_numpy()
    d = ev["d"].to_numpy()
    p0 = ev["p0"].to_numpy()
    span = np.where((p0 >= 0) & (t - p0 <= PATTERN_MAX_SPAN), t - np.maximum(p0, 0), 2)
    x12 = np.where(d > 0, fl[1][t], fl[-1][t])
    rz = fl["RZ"][t]
    parts = []
    for mode, sgn in (("W", 1), ("F", -1)):
        fr = d * sgn
        part = pd.DataFrame({"key": ev["key"].to_numpy(), "mode": mode, "f": fr, "t": t, "span": span,
                             "X12": x12, "RZ": rz})
        if cells is not None:
            ok = [(k, mode) in cells for k in part["key"]]
            part = part[np.asarray(ok, bool)]
        parts.append(part)
    tr = pd.concat(parts, ignore_index=True)
    tr = tr[np.isfinite(a[tr["t"].to_numpy()]) & (a[tr["t"].to_numpy()] > 0)]
    res = []
    for f in (1, -1):
        o, h, l, c = frame_arrays(df, f)
        u = tr.loc[tr["f"] == f, ["t", "span"]].drop_duplicates()
        if not len(u):
            continue
        ut, us = u["t"].to_numpy(), u["span"].to_numpy()
        rmin = {k: pd.Series(l).rolling(k + 1).min().to_numpy() for k in range(PATTERN_MAX_SPAN + 1)}
        ext = np.array([rmin[k][i] for i, k in zip(ut, us)])
        stop = ext - PAD * a[ut]
        ok = o[ut + 1] - stop > 0
        ut, us, stop = ut[ok], us[ok], stop[ok]
        cost_px = cost_atr[ut] * a[ut]
        mfe, e1 = outcomes(o, h, l, c, a, cost_px, ut, stop, H)
        res.append(pd.DataFrame({"f": f, "t": ut, "span": us, "mfe": mfe, "E1": e1,
                                 "costR": cost_px / (o[ut + 1] - stop), "risk_atr": (o[ut + 1] - stop) / a[ut]}))
    if not res:
        return pd.DataFrame()
    tr = tr.merge(pd.concat(res, ignore_index=True), on=["f", "t", "span"], how="inner")
    tr["ts"] = ts[tr["t"].to_numpy()]
    tr["day"] = (tr["ts"] // 86400).astype(np.int64)
    return tr


HIT = [f"k{N}" for N in NS] + [f"kn{N}" for N in NNET]


def aggregate(tr):
    """Per (key, mode, variant, day): the trade count, hits at each N (gross; net for NNET) and E1 sums."""
    if not len(tr):
        return pd.DataFrame()
    base = tr[["key", "mode", "day"]].copy()
    base["n"] = 1
    for N in NS:
        base[f"k{N}"] = (tr["mfe"].to_numpy() >= N).astype(np.int32)
    for N in NNET:
        base[f"kn{N}"] = (tr["mfe"].to_numpy() >= N + tr["costR"].to_numpy()).astype(np.int32)
    base["e1"] = tr["E1"].to_numpy()
    out = []
    for v in VARIANTS:
        x = base if v == "ALL" else base[tr[v].to_numpy()]
        g = x.groupby(["key", "mode", "day"], sort=False).sum(numeric_only=True).reset_index()
        g["variant"] = v
        out.append(g)
    return pd.concat(out, ignore_index=True)


# ---------------------------------------------------------------- stats

def cell_stats(g):
    """g: one cell's (day) rows already summed across series. p at each N with its day-clustered variance."""
    n = g["n"].to_numpy(float)
    N_ = n.sum()
    r = {"n": int(N_), "days": len(g)}
    for col in HIT:
        k = g[col].to_numpy(float)
        p = k.sum() / N_ if N_ else np.nan
        r[f"p{col[1:]}"] = p
        r[f"v{col[1:]}"] = float(((k - p * n) ** 2).sum() / N_ ** 2) if N_ else np.nan
    e = g["e1"].to_numpy(float)
    m = e.sum() / N_ if N_ else np.nan
    r["R"] = m
    r["vR"] = float(((e - m * n) ** 2).sum() / N_ ** 2) if N_ else np.nan
    return r


def stats(agg):
    """agg: rows of (key, mode, variant, day, n, k..., e1) for one source and timeframe, from many series."""
    if not len(agg):
        return pd.DataFrame()
    s = agg.groupby(["key", "mode", "variant", "day"], sort=False).sum(numeric_only=True).reset_index()
    rows = []
    for (key, mode, var), g in s.groupby(["key", "mode", "variant"], sort=False):
        rows.append({"key": key, "mode": mode, "variant": var, **cell_stats(g)})
    return pd.DataFrame(rows)


def compare(real, iid, garch):
    """One row per cell: real against both walks, the tail excess at each N, z and one-sided p at N = 5."""
    from scipy.stats import norm
    on = ["key", "mode", "variant"]
    m = real.merge(iid, on=on, how="left", suffixes=("", "_iid")).merge(
        garch.add_suffix("_garch").rename(columns={f"{c}_garch": c for c in on}), on=on, how="left")
    for N in NS + tuple(f"n{x}" for x in NNET):
        pw = np.fmax(m[f"p{N}_iid"], m[f"p{N}_garch"])
        m[f"pw{N}"] = pw
        m[f"ex{N}"] = m[f"p{N}"] - pw
    for N in (4, 5, 10):
        use_iid = m[f"p{N}_iid"] >= m[f"p{N}_garch"]
        vw = np.where(use_iid, m[f"v{N}_iid"], m[f"v{N}_garch"])
        se = np.sqrt(m[f"v{N}"] + vw)
        z = np.where(se > 0, m[f"ex{N}"] / se, 0.0)
        m[f"z{N}"] = z
        m[f"pv{N}"] = 1 - norm.cdf(z)
    m["inv5"] = 1 / 6
    return m


def bh(p, q=Q):
    p = np.asarray(p, float)
    order = np.argsort(p)
    ranked = p[order] * len(p) / np.arange(1, len(p) + 1)
    passed = np.zeros(len(p), bool)
    below = np.flatnonzero(ranked <= q)
    if len(below):
        passed[order[:below.max() + 1]] = True
    return passed


# ---------------------------------------------------------------- jobs

def disc_jobs():
    """MT5 holds no 15m bars before 2024: its 15m is confirmation only."""
    return [("binance", c, iv) for c in COINS for iv in SEC] + \
        [("mt5", m, iv) for m in MT5_DISC for iv in SEC if iv != "15m"]


def deriv_jobs():
    return [("mt5", m, iv) for m in DERIV for iv in SEC]


def conf_jobs():
    """(venue, sym, iv, lo_ts): fresh coins and the MT5 markets discovery never used, all of them;
    the discovery markets from 2024-01-01."""
    return ([("fresh", c, iv, None) for c in FRESH for iv in ("4h", "1d")] +
            [("mt5", m, iv, None) for m in MT5_NEW for iv in SEC] +
            [("binance", c, iv, SPLIT) for c in COINS for iv in SEC] +
            [("mt5", m, iv, SPLIT) for m in MT5_DISC for iv in SEC])


def _size(job):
    venue, sym, iv = job[:3]
    return {"15m": 0, "1h": 1, "4h": 2, "1d": 3}[iv]


def scan_one(job):
    """Parse (cached) and trade one series; aggregated rows by (cell, day)."""
    venue, sym, iv, source, lo, hi, tag = job
    df, cost_atr, ev = cached((venue, sym, iv, source))
    if df is None:
        return None
    tr = trades(df, cost_atr, ev, iv, lo, hi)
    agg = aggregate(tr)
    if len(agg):
        agg["set"], agg["iv"], agg["source"] = tag, iv, source
    return agg


def run_pool(fn, jobs):
    out = []
    with ProcessPoolExecutor(WORKERS) as pool:
        for i, g in enumerate(pool.map(fn, jobs, chunksize=1)):
            if g is not None and len(g):
                out.append(g)
            if (i + 1) % 20 == 0:
                print(f"  {i + 1}/{len(jobs)} done", flush=True)
    return out


CELL_DAY = ["key", "mode", "variant", "day"]


def run_merge(fn, jobs):
    """Like run_pool for aggregated rows, merged as they arrive: per (set, iv, source), the (cell, day)
    rows of all series summed, so markets trading on the same day share a row (the day cluster)."""
    acc: dict = {}
    with ProcessPoolExecutor(WORKERS) as pool:
        for i, g in enumerate(pool.map(fn, jobs, chunksize=1)):
            if g is not None and len(g):
                for grp, x in g.groupby(["set", "iv", "source"]):
                    lst = acc.setdefault(grp, [])
                    lst.append(x.drop(columns=["set", "iv", "source"]))
                    if len(lst) >= 6:
                        acc[grp] = [pd.concat(lst, ignore_index=True).groupby(CELL_DAY, sort=False).sum().reset_index()]
            if (i + 1) % 20 == 0:
                print(f"  {i + 1}/{len(jobs)} done", flush=True)
    return {k: pd.concat(v, ignore_index=True) for k, v in acc.items()}


def scan_table(acc):
    """Per (set, iv): the compare table over cells."""
    tabs = []
    for tag, iv in sorted({(a, b) for a, b, _ in acc}):
        if any((tag, iv, s) not in acc for s in SOURCES):
            continue
        st = {s: stats(acc[(tag, iv, s)]) for s in SOURCES}
        if any(not len(x) for x in st.values()):
            continue
        c = compare(st["real"], st["iid"], st["garch"])
        c["set"], c["iv"] = tag, iv
        tabs.append(c)
    return pd.concat(tabs, ignore_index=True)


def discover():
    OUT.mkdir(parents=True, exist_ok=True)
    rule = json.loads(RULE.read_text())
    print(f"rule frozen {rule['frozen']}; discovery run", flush=True)
    jobs = [(v, s, iv, src, None, DISC_END, "DISC") for v, s, iv in disc_jobs() for src in SOURCES] + \
           [(v, s, iv, src, None, None, "DERIV") for v, s, iv in deriv_jobs() for src in SOURCES]
    jobs.sort(key=_size)
    t = scan_table(run_merge(scan_one, jobs))
    t["eligible"] = (t["n"] >= MIN_N) & (t["n_iid"] >= MIN_WALK_N) & (t["n_garch"] >= MIN_WALK_N)
    t["bh"] = False
    for tag in ("DISC", "DERIV"):
        m = (t["set"] == tag) & t["eligible"]
        t.loc[m, "bh"] = bh(t.loc[m, "pv5"].to_numpy())
    t.to_csv(OUT / "tail_discovery.csv", index=False)
    d = t[(t["set"] == "DISC") & t["eligible"]].copy()
    surv = d[d["bh"]].sort_values("ex5", ascending=False)
    rest = d[~d["bh"]].sort_values("ex5", ascending=False)
    pick = pd.concat([surv.head(K), rest.head(max(0, K - len(surv)))])
    cols = ["key", "mode", "variant", "iv", "n", "p4", "pw4", "ex4", "p5", "pw5", "ex5", "p10", "pw10", "ex10",
            "p20", "pw20", "pn5", "pwn5", "R", "R_iid", "R_garch", "z5", "pv5", "bh"]
    sel = {"frozen_after": "the discovery run, before any confirmation trade was computed",
           "rule": "tail_rule.json", "cells_scanned": int(len(t[t["set"] == "DISC"])),
           "cells_eligible": int(len(d)), "bh_survivors": int(d["bh"].sum()),
           "selected": [{k: (v.item() if hasattr(v, "item") else v) for k, v in r.items()}
                        for r in pick[cols].to_dict("records")]}
    (OUT / "tail_selected.json").write_text(json.dumps(sel, indent=1, default=float))
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 400)
    for tag in ("DISC", "DERIV"):
        x = t[t["set"] == tag]
        e = x[x["eligible"]]
        print(f"\n== {tag}: {len(x)} cells, {len(e)} eligible (n >= {MIN_N}), {int(e['bh'].sum())} survive BH (q {Q}) at N = 5")
        print(f"   mean excess among eligible: N=4 {e['ex4'].mean():+.4f}, N=5 {e['ex5'].mean():+.4f}, N=10 {e['ex10'].mean():+.4f}; "
              f"share with ex5 > 0: {(e['ex5'] > 0).mean():.2f}")
        print(e.sort_values("ex5", ascending=False)[["key", "mode", "variant", "iv", "n", "p5", "pw5", "ex5", "p10", "pw10",
                                                     "ex10", "R", "z5", "pv5", "bh"]].head(30).round(4).to_string(index=False))
        for iv in SEC:
            f = e[e["iv"] == iv]
            if len(f):
                print(f"   {iv}: {len(f)} eligible, {int(f['bh'].sum())} survive BH; mean ex4 {f['ex4'].mean():+.4f}, "
                      f"ex5 {f['ex5'].mean():+.4f}, ex10 {f['ex10'].mean():+.4f}; share ex5 > 0 {(f['ex5'] > 0).mean():.2f}")
    print("\nSELECTED:")
    print(pick[cols].round(4).to_string(index=False))


# ---------------------------------------------------------------- confirmation

def conf_one(job):
    """Per-trade rows of the selected cells on one series (confirmation, or the discovery period with tag DISC)."""
    venue, sym, iv, source, lo, hi, tag, cells = job
    df, cost_atr, ev = cached((venue, sym, iv, source))
    if df is None:
        return None
    tr = trades(df, cost_atr, ev, iv, lo, hi, cells=cells)
    if not len(tr):
        return None
    tr["venue"], tr["sym"], tr["iv"], tr["source"], tr["set"] = venue, sym, iv, source, tag
    return tr


def selected_cells():
    sel = json.loads(SELECTED.read_text())["selected"]
    return sel, {(s["key"], s["mode"], s["variant"], s["iv"]) for s in sel}


def in_cell(tr, key, mode, variant, iv):
    m = (tr["key"] == key) & (tr["mode"] == mode) & (tr["iv"] == iv)
    if variant != "ALL":
        m &= tr[variant]
    return tr[m]


def pcurve(x, net=False):
    return {N: float((x["mfe"] >= N + (x["costR"] if net else 0)).mean()) if len(x) else np.nan for N in NS}


def boot_excess(real, walks, rng, N=5, draws=2000):
    """Day bootstrap of P_real(>= N) - max over walks of P_walk(>= N): each source's days resampled apart."""
    def prep(x):
        g = x.assign(k=(x["mfe"] >= N).astype(float), one=1.0).groupby("day")[["k", "one"]].sum()
        return g["k"].to_numpy(), g["one"].to_numpy()
    kr, nr = prep(real)
    ws = [prep(w) for w in walks if len(w)]
    out = np.empty(draws)
    for b in range(draws):
        i = rng.integers(0, len(kr), len(kr))
        pr = kr[i].sum() / nr[i].sum()
        pw = max(kw[j].sum() / nw[j].sum() for kw, nw in ws for j in [rng.integers(0, len(kw), len(kw))])
        out[b] = pr - pw
    return out


def confirm():
    OUT.mkdir(parents=True, exist_ok=True)
    sel, cells4 = selected_cells()
    cells = {(k, m) for k, m, _, _ in cells4}
    ivs = {iv for *_, iv in cells4}
    print(f"confirming {len(sel)} cells: {sorted(cells4)}", flush=True)
    jobs = [(v, s, iv, src, lo, None, "CONF", cells) for v, s, iv, lo in conf_jobs() if iv in ivs for src in SOURCES]
    jobs += [(v, s, iv, src, None, DISC_END, "DISC", cells) for v, s, iv in disc_jobs() if iv in ivs for src in SOURCES]
    jobs += [(v, s, iv, src, None, None, "DERIV", cells) for v, s, iv in deriv_jobs() if iv in ivs for src in SOURCES]
    jobs.sort(key=_size)
    got = run_pool(conf_one, jobs)
    d = pd.concat(got, ignore_index=True)
    d["sub"] = np.select([d["venue"] == "fresh", d["sym"].isin(MT5_NEW), d["venue"] == "binance"],
                         ["fresh coins", "MT5 unseen markets", "Binance 12 from 2024"], "MT5 from 2024")
    d.to_pickle(OUT / "tail_confirm_trades.pkl.gz")
    evaluate(d, sel)


def evaluate(d, sel):
    rng = np.random.default_rng(71)
    rows = []
    for s in sel:
        key, mode, var, iv = s["key"], s["mode"], s["variant"], s["iv"]
        x = in_cell(d, key, mode, var, iv)
        for tag in ("DISC", "CONF", "DERIV"):
            subs = [("all", x[x["set"] == tag])]
            if tag == "CONF":
                subs += [(u, x[(x["set"] == tag) & (x["sub"] == u)]) for u in sorted(x.loc[x["set"] == tag, "sub"].unique())]
            for sub, y in subs:
                R, I, G = (y[y["source"] == src] for src in SOURCES)
                if len(R) < 30 or not len(I) or not len(G):
                    continue
                r = {"key": key, "mode": mode, "variant": var, "iv": iv, "set": tag, "sub": sub,
                     "n": len(R), "n_iid": len(I), "n_garch": len(G)}
                for N in NS:
                    r[f"p{N}"], r[f"p{N}_iid"], r[f"p{N}_garch"] = ((z["mfe"] >= N).mean() for z in (R, I, G))
                    r[f"ex{N}"] = r[f"p{N}"] - max(r[f"p{N}_iid"], r[f"p{N}_garch"])
                for N in NNET:
                    r[f"pn{N}"] = (R["mfe"] >= N + R["costR"]).mean()
                    r[f"pn{N}_walk"] = max((z["mfe"] >= N + z["costR"]).mean() for z in (I, G))
                r["R"], r["R_iid"], r["R_garch"] = R["E1"].mean(), I["E1"].mean(), G["E1"].mean()
                r["R_before"] = R.loc[R["ts"] < SPLIT, "E1"].mean()
                r["R_after"] = R.loc[R["ts"] >= SPLIT, "E1"].mean()
                if sub == "all":
                    b = boot_excess(R, (I, G), rng)
                    r["ex5_lo"], r["ex5_hi"] = np.quantile(b, [0.05, 0.95])
                    r["pv5"] = max(float((b <= 0).mean()), 1 / (len(b) + 1))
                    yy = R.assign(R=R["E1"])
                    g = yy.groupby("day")["R"].agg(["sum", "count"])
                    bs = [g["sum"].values[i].sum() / g["count"].values[i].sum()
                          for i in (rng.integers(0, len(g), len(g)) for _ in range(2000))]
                    r["R_lo"], r["R_hi"] = np.quantile(bs, [0.05, 0.95])
                rows.append(r)
    t = pd.DataFrame(rows)
    c = t[(t["set"] == "CONF") & (t["sub"] == "all")].copy()
    c["bh"] = bh(c["pv5"].to_numpy())
    c["passes"] = ((c["ex5"] > 0) & (c["ex5_lo"] > 0) & (c["p5"] > 1 / 6) & (c["p5"] > c[["p5_iid", "p5_garch"]].max(axis=1))
                   & (c["R"] > 0) & c["bh"])
    t = t.merge(c[["key", "mode", "variant", "iv", "set", "sub", "bh", "passes"]], how="left",
                on=["key", "mode", "variant", "iv", "set", "sub"])
    t.to_csv(OUT / "tail_confirm.csv", index=False)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_rows", 400)
    show = ["key", "mode", "variant", "iv", "set", "sub", "n", "p5", "p5_iid", "p5_garch", "ex5", "p10", "p10_iid", "p10_garch",
            "ex10", "pn5", "R", "R_iid", "R_garch"]
    print(t[show].round(4).to_string(index=False))
    print("\nVERDICTS (pooled confirmation set, cell's timeframe):")
    for _, r in c.iterrows():
        print(f"  {r['key']:32s} {r['mode']} {r['variant']:3s} {r['iv']}: n {r['n']}, P5 {r['p5']:.4f} vs walk "
              f"{max(r['p5_iid'], r['p5_garch']):.4f} (1/6 = 0.1667), excess {r['ex5']:+.4f} [{r['ex5_lo']:+.4f}, {r['ex5_hi']:+.4f}] "
              f"p {r['pv5']:.4f}; P10 {r['p10']:.4f} vs {max(r['p10_iid'], r['p10_garch']):.4f}; "
              f"R {r['R']:+.3f} [{r['R_lo']:+.3f}, {r['R_hi']:+.3f}]; BH {'yes' if r['bh'] else 'no'} -> "
              f"{'CONFIRMED' if r['passes'] else 'fails'}")


# ---------------------------------------------------------------- plots

def label(key, mode, variant, iv):
    return f"{key} {'with' if mode == 'W' else 'fade'} {variant} {iv}"


def plot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm
    t = pd.read_csv(OUT / "tail_discovery.csv")
    # heatmaps: variant ALL, rows the patterns, columns timeframe x with/fade; DISC at N = 5 and 10, DERIV at 5
    cols = [(iv, m) for m in ("W", "F") for iv in SEC]
    keys = sorted(t.loc[t["variant"] == "ALL", "key"].unique())

    def grid(tag, N, variant="ALL"):
        x = t[(t["set"] == tag) & (t["variant"] == variant)]
        M = np.full((len(keys), len(cols)), np.nan)
        for j, (iv, m) in enumerate(cols):
            y = x[(x["iv"] == iv) & (x["mode"] == m) & (x["n"] >= MIN_N)].set_index("key")[f"ex{N}"]
            for i, k in enumerate(keys):
                if k in y.index:
                    M[i, j] = y[k]
        return M
    panels = [("DISC", 5), ("DISC", 10), ("DERIV", 5)]
    fig, axes = plt.subplots(1, 3, figsize=(20, max(12, len(keys) * 0.16)))
    for ax, (tag, N) in zip(axes, panels):
        M = grid(tag, N)
        lim = 0.04 if N == 5 else 0.02
        im = ax.imshow(np.clip(M, -lim, lim), aspect="auto", cmap="RdBu_r", norm=TwoSlopeNorm(0, -lim, lim))
        ax.set_xticks(range(len(cols)), [f"{iv} {'with' if m == 'W' else 'fade'}" for iv, m in cols], rotation=45, fontsize=8)
        ax.set_yticks(range(len(keys)), keys if ax is axes[0] else [""] * len(keys), fontsize=6)
        ax.set_title(f"{'discovery (Binance 12 + MT5, before 2024)' if tag == 'DISC' else 'Deriv synthetics'}: "
                     f"P(>= {N}R) real - max(iid, GARCH)", fontsize=9)
        plt.colorbar(im, ax=ax, fraction=0.04)
    fig.suptitle(f"tail excess per pattern (variant ALL, cells with n >= {MIN_N}; blank = too few trades)", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "tail_heatmap.png", dpi=80)
    plt.close(fig)
    # the conditioned variants, discovery, N = 5
    fig, axes = plt.subplots(1, 2, figsize=(14, max(12, len(keys) * 0.16)))
    for ax, v in zip(axes, ("X12", "RZ")):
        M = grid("DISC", 5, v)
        im = ax.imshow(np.clip(M, -0.06, 0.06), aspect="auto", cmap="RdBu_r", norm=TwoSlopeNorm(0, -0.06, 0.06))
        ax.set_xticks(range(len(cols)), [f"{iv} {'with' if m == 'W' else 'fade'}" for iv, m in cols], rotation=45, fontsize=8)
        ax.set_yticks(range(len(keys)), keys if ax is axes[0] else [""] * len(keys), fontsize=6)
        ax.set_title(f"discovery, variant {v}: P(>= 5R) excess over walks", fontsize=9)
        plt.colorbar(im, ax=ax, fraction=0.04)
    fig.tight_layout()
    fig.savefig(OUT / "tail_heatmap_variants.png", dpi=80)
    plt.close(fig)
    if not (OUT / "tail_confirm.csv").exists():
        print("plots written (discovery only)", flush=True)
        return
    c = pd.read_csv(OUT / "tail_confirm.csv")
    d = pd.read_pickle(OUT / "tail_confirm_trades.pkl.gz")
    sel, _ = selected_cells()
    # discovery vs confirmation excess
    fig, axes = plt.subplots(1, 2, figsize=(15, 7))
    for ax, N in zip(axes, (5, 10)):
        for s in sel:
            q = {tag: c[(c["key"] == s["key"]) & (c["mode"] == s["mode"]) & (c["variant"] == s["variant"]) & (c["iv"] == s["iv"])
                        & (c["set"] == tag) & (c["sub"] == "all")] for tag in ("DISC", "CONF")}
            if not len(q["DISC"]) or not len(q["CONF"]):
                continue
            x, y = q["DISC"][f"ex{N}"].iloc[0], q["CONF"][f"ex{N}"].iloc[0]
            ok = bool(q["CONF"]["passes"].iloc[0]) if "passes" in q["CONF"] and q["CONF"]["passes"].notna().iloc[0] else False
            ax.scatter(x, y, s=40, color="#2a9d8f" if ok else "#e76f51")
            ax.annotate(label(s["key"].replace("PATTERN:", ""), s["mode"], s["variant"], s["iv"]), (x, y), fontsize=6)
        lim = ax.get_xlim()
        ax.axhline(0, color="grey", lw=0.8)
        ax.axvline(0, color="grey", lw=0.8)
        ax.plot(lim, lim, color="grey", lw=0.6, ls=":")
        ax.set_xlabel(f"discovery: P(>= {N}R) real - max(walks)")
        ax.set_ylabel(f"confirmation: P(>= {N}R) real - max(walks)")
        ax.set_title(f"the selected {len(sel)} cells, N = {N} (green: confirmed)")
    fig.tight_layout()
    fig.savefig(OUT / "tail_scatter.png", dpi=80)
    plt.close(fig)
    # P(N R) curves
    ncol = 4
    nrow = int(np.ceil(len(sel) / ncol))
    fig, axes = plt.subplots(nrow, ncol * 2, figsize=(30, 3.6 * nrow), squeeze=False)
    for i, s in enumerate(sel):
        x = in_cell(d, s["key"], s["mode"], s["variant"], s["iv"])
        for j, tag in enumerate(("DISC", "CONF")):
            ax = axes[i // ncol, (i % ncol) * 2 + j]
            y = x[x["set"] == tag]
            for src, st in (("real", "-o"), ("iid", "--s"), ("garch", ":^")):
                z = y[y["source"] == src]
                if len(z):
                    pc = pcurve(z)
                    ax.plot(NS, [max(pc[N], 1e-5) for N in NS], st, ms=3, label=f"{src} n={len(z)} R={z['E1'].mean():+.3f}")
            ax.plot(NS, [1 / (N + 1) for N in NS], color="grey", lw=0.8, label="1/(N+1)")
            ax.set_xscale("log")
            ax.set_yscale("log")
            ax.set_title(f"{label(s['key'].replace('PATTERN:', ''), s['mode'], s['variant'], s['iv'])}: {tag.lower()}", fontsize=7)
            ax.legend(fontsize=5)
    fig.suptitle("P(trade reaches N R before its stop, 20 days) - real vs iid and GARCH walks vs 1/(N+1); discovery | confirmation")
    fig.tight_layout()
    fig.savefig(OUT / "tail_curves.png", dpi=70)
    plt.close(fig)
    # gallery: the top cells by confirmation excess, real trades that reached 5R and typical losers
    cc = c[(c["set"] == "CONF") & (c["sub"] == "all")].sort_values("ex5", ascending=False).head(3)
    rng = np.random.default_rng(9)
    for rank, (_, s) in enumerate(cc.iterrows()):
        x = in_cell(d, s["key"], s["mode"], s["variant"], s["iv"])
        x = x[x["source"] == "real"]
        win = x[x["mfe"] >= 5]
        lose = x[x["mfe"] < 1]
        pick = pd.concat([win.iloc[rng.choice(len(win), min(4, len(win)), replace=False)] if len(win) else win,
                          lose.iloc[rng.choice(len(lose), min(2, len(lose)), replace=False)] if len(lose) else lose])
        fig, axes = plt.subplots(2, 3, figsize=(21, 10))
        for ax, (_, r) in zip(axes.flat, pick.iterrows()):
            df, _, ev = cached((r["venue"], r["sym"], r["iv"], "real"))
            draw_trade(ax, df, r, s)
        fig.suptitle(f"{label(s['key'], s['mode'], s['variant'], s['iv'])}: four trades that reached 5R, two that never "
                     "reached 1R. Purple: the signal bar (known_at); entry the next open (black), stop (red), 5R (green)", fontsize=10)
        fig.tight_layout()
        fig.savefig(OUT / f"tail_gallery_{rank + 1}.png", dpi=75)
        plt.close(fig)
    print("plots written", flush=True)


def draw_trade(ax, df, r, s):
    t = int(r["t"])
    H = int(HORIZON_DAYS * 86400 / SEC[r["iv"]])
    a = atr_of(df)
    f = int(r["f"])
    o, h, l, c = frame_arrays(df, f)
    i0, i1 = max(0, t - 30), min(len(df) - 1, t + min(H, 80))
    w = df.iloc[i0:i1 + 1]
    x = np.arange(i0, i1 + 1)
    up = (w["close"] >= w["open"]).to_numpy()
    ax.vlines(x, w["low"], w["high"], color="#555", lw=0.6)
    ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
    ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
    span = int(r["span"]) if "span" in r else 2
    entry = o[t + 1]
    stop = entry - r["risk_atr"] * a[t]
    risk = entry - stop
    for lvl, col in ((stop, "red"), (entry, "k"), (entry + 5 * risk, "green")):
        ax.hlines(f * lvl, t + 1, i1, colors=col, lw=1)
    ax.axvline(t, color="purple", lw=1, ls=":")
    ax.axvspan(t - span - 0.5, t + 0.5, color="purple", alpha=0.08)  # the bars that set the stop
    ax.set_title(f"{r['sym']} {r['iv']} {'long' if f > 0 else 'short'}  MFE {r['mfe']:.1f}R, trail {r['E1']:+.2f}R  "
                 f"{pd.Timestamp(int(r['ts']), unit='s'):%Y-%m-%d %H:%M}", fontsize=8)


# ---------------------------------------------------------------- smoke

def smoke():
    venue, sym, iv, source = os.environ["SMOKE"].split(",")
    t0 = time.time()
    df, cost_atr, ev = cached((venue, sym, iv, source))
    print(f"{venue} {sym} {iv} {source}: {len(df)} bars, ts {df['ts'].iloc[0]}..{df['ts'].iloc[-1]}, "
          f"{len(ev)} events, {ev['key'].nunique()} keys, cost_atr median {np.median(cost_atr):.4f}, {time.time() - t0:.0f}s")
    t0 = time.time()
    tr = trades(df, cost_atr, ev, iv, None, None)
    agg = aggregate(tr)
    print(f"trades {len(tr)}, agg rows {len(agg)}, {time.time() - t0:.0f}s; risk_atr median {tr['risk_atr'].median():.2f}; "
          f"costR median {tr['costR'].median():.3f}")
    print(sorted(ev["key"].unique()))


def main():
    {"discover": discover, "confirm": confirm, "plot": plot, "smoke": smoke}[os.environ.get("MODE", "discover")]()


if __name__ == "__main__":
    main()
