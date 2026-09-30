"""Adaptive market ecology: do strategies die of overcrowding, and does alpha decay and come back?

The user's question: does profitability decline because a strategy stops working, or because its
population grows too large - and can the evolution of strategy populations explain why alpha decays
and reappears? Population ecology, evolutionary biology and epidemiology each make a testable claim.
Pre-registered, before any data was read:

PART=species  strategy "species" as daily gross returns, vol-scaled (a position of 1 is one daily
              sd), equal-weighted across a family's instruments:
                tsmom21/63/252  sign of the past L-day move            (time-series momentum)
                rev5            minus the sign of the past 5 days       (short-term reversal)
                donchian        55-day breakout, 20-day exit            (trend breakout)
                rsi2            RSI(2) < 10 long, > 90 short, one day   (Connors mean reversion)
                carry           sign of the policy-rate differential    (FX only; carry.py's rates)
                volsell         1 - (r / sigma)^2: a short straddle proxy; on the S&P the sigma is
                                VIX-implied, elsewhere the trailing EWMA
                zone            the production zone fade (indicators.py's touch trades, 1h, 20 bars)
              Families: FX (14 pairs, from 1990), metals, crypto, the S&P 500 (carry.py's daily
              closes, the only index history on the lab), and Deriv (a market, but with no
              participant ecology by construction).
    1a decay and recovery   the ecology prediction is that profitability MEAN-REVERTS: a species
                            that has done well attracts capital and then does badly, and recovers
                            once the crowd leaves. Test: future 6-month species return on the past
                            12 months (monthly, Newey-West). Pass: slope < 0 with t <= -3 in both
                            halves, outside the walks' 95% band.
    1b density dependence   a species' "population" is proxied by (i) consensus - how aligned its
                            positions are across instruments, |mean position|; (ii) FX: CFTC
                            speculators' net positioning on the species' side; (iii) crypto:
                            funding on the species' side. Pass: the next 21 days' species return
                            falls with population, t <= -3 in both halves, beyond a circular-shift
                            null of the proxy and beyond the walks.
    1c predator and prey    Lotka-Volterra style lagged interactions between momentum, reversal and
                            breakout (a monthly VAR(1)), reported against the walks' band.

PART=ga       an evolving population of rule variants (tsmom / reversal / breakout / RSI and their
              parameters, plus a holding-smoothing gene), fitness = net Sharpe on the first 60%,
              80 genomes x 30 generations. Out of sample: the fittest against 500 random rules
              (percentile), its probabilistic and deflated Sharpe (the trials are the
              evaluations), and whether selection with costs evolves slower strategies than
              selection without them. Pass: the fittest's out-of-sample Sharpe beats 95% of random
              rules and its DSR > 0.95, and not on walks.

PART=contagion  liquidation-style cascades in crypto (10 Binance perpetuals, hourly, crowding.py's
              data). A shock is |r| > 4x the trailing 500-hour mean |r| (shocks.py's rule). Target:
              a shock in the next 4 hours. Baseline: the shock forecaster's features (vol state,
              vol-of-vol, own shocks in the last 20 and 100 hours, the hour). Added, as epidemiology
              would have it: a Cori-style reproduction ratio R(t) of market-wide shock incidence, a
              Hawkes intensity fitted on the training block, other coins' shocks in the last 6
              hours, and the susceptible pool (funding and open-interest crowding). Pass:
              incremental AUC >= 0.01 with a day-bootstrap CI above 0, both halves of the test
              block, and larger than the same gain on walks with a common GARCH factor. Measurement
              only.

Controls throughout: walks we generate (GARCH(1,1), t(5) innovations: volatility clustering but no
ecology), circular shifts of every population proxy, BH across the tests in each part.

Run on the lab:
  PART=species SEQLAB=$HOME/till_infinity/data/seqlab CARRY=$HOME/till_infinity/data/carry \\
    CROWD=$HOME/till_infinity/data/crowding IND=$HOME/till_infinity/data/indicators python ecology.py
  PART=ga ... ; PART=contagion ...
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

PART = os.environ.get("PART", "species")
CARRY = Path(os.environ.get("CARRY", ".data/carry"))
CROWD = Path(os.environ.get("CROWD", ".data/crowding"))
IND = Path(os.environ.get("IND", ".data/indicators"))
START = pd.Timestamp(os.environ.get("START", "1990-01-01"))
WALKS = int(os.environ.get("WALKS", "40"))
RNG = np.random.default_rng(29)

FAMILIES = {
    "fx": ["AUDJPY", "AUDUSD", "CHFJPY", "EURAUD", "EURCHF", "EURGBP", "EURJPY", "EURUSD", "GBPJPY",
           "GBPUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY"],
    "metals": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "index": ["SPX"],
    "deriv": ["Volatility_75_Index", "Boom_1000_Index", "Crash_1000_Index", "Jump_50_Index",
              "Step_Index", "Range_Break_100_Index"],
}
#: Round-trip cost per unit of position turnover, in daily-sd units: the lab's COST_V (5-minute sd
#: units) scaled by sqrt(5 / 1440). The S&P uses 0.3 as a liquid index CFD.
COST_V = {"fx": 0.8, "metals": 0.16, "crypto": 0.5, "index": 0.3, "deriv": 0.15}
DAILY_COST = {k: v * math.sqrt(5 / 1440) for k, v in COST_V.items()}
SPECIES = ["tsmom21", "tsmom63", "tsmom252", "rev5", "donchian", "rsi2", "carry", "volsell", "zone"]
CFTC_FX = {"EURUSD": ("EURO FX - ", 1), "USDJPY": ("JAPANESE YEN - ", -1),
           "GBPUSD": ("BRITISH POUND", 1), "AUDUSD": ("AUSTRALIAN DOLLAR - ", 1),
           "USDCAD": ("CANADIAN DOLLAR - ", -1), "USDCHF": ("SWISS FRANC - ", -1),
           "NZDUSD": ("NEW ZEALAND DOLLAR - ", 1)}
CRYPTO_PERP = {"BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "SOLUSD": "SOLUSDT"}


# ---------------------------------------------------------------------------------------- data

def closes(sym: str) -> pd.Series:
    if sym == "SPX":
        d = pd.read_csv(CARRY / "spx.csv")
        s = pd.Series(d.iloc[:, 1].to_numpy(float), index=pd.to_datetime(d.iloc[:, 0]))
    else:
        df = spikerisk.load(None, sym, "SEQLAB", "1d")
        s = pd.Series(df["close"].to_numpy(float), index=pd.to_datetime(df["ts"].to_numpy(), unit="s"))
        s.index = s.index.normalize()
    s = s[~s.index.duplicated()].sort_index()
    return s[(s.index >= START) & (s > 0)]


def vix() -> pd.Series:
    d = pd.read_csv(CARRY / "vix.csv")
    return pd.Series(d.iloc[:, 1].to_numpy(float), index=pd.to_datetime(d.iloc[:, 0]))


def rates() -> pd.DataFrame | None:
    p = CARRY / "rates.json"
    if not p.exists():
        return None
    raw = json.loads(p.read_text())
    out = {}
    for ccy, got in raw.items():
        s = pd.Series(got, dtype=float)
        s.index = pd.to_datetime(s.index) + pd.offsets.MonthBegin(2)  # published with a lag
        out[ccy] = s
    days = pd.date_range("1960-01-01", pd.Timestamp.today().normalize(), freq="D")
    return pd.DataFrame(out).reindex(days).ffill()


def garch_walk(n: int, seed: int) -> np.ndarray:
    """Daily closes from GARCH(1,1) with t(5) innovations: clustering, no ecology."""
    rng = np.random.default_rng(seed)
    omega, alpha, beta = 0.006**2 * (1 - 0.06 - 0.92), 0.06, 0.92
    z = rng.standard_t(5, n) / math.sqrt(5 / 3)
    r = np.empty(n)
    var = 0.006**2
    for t in range(n):
        r[t] = math.sqrt(var) * z[t]
        var = omega + alpha * r[t] ** 2 + beta * var
    return 100 * np.exp(np.cumsum(r))


# ---------------------------------------------------------------------------------------- species

def rsi(c: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c, prepend=np.nan)
    up = pd.Series(np.clip(d, 0, None)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    dn = pd.Series(np.clip(-d, 0, None)).ewm(alpha=1 / n, adjust=False).mean().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return 100 - 100 / (1 + up / dn)


def donchian(c: np.ndarray, n: int, m: int) -> np.ndarray:
    hi = pd.Series(c).rolling(n).max().shift(1).to_numpy()
    lo = pd.Series(c).rolling(n).min().shift(1).to_numpy()
    xhi = pd.Series(c).rolling(m).max().shift(1).to_numpy()
    xlo = pd.Series(c).rolling(m).min().shift(1).to_numpy()
    pos = np.zeros(len(c))
    state = 0.0
    for t in range(len(c)):
        if np.isnan(hi[t]):
            continue
        if c[t] >= hi[t]:
            state = 1.0
        elif c[t] <= lo[t]:
            state = -1.0
        elif state > 0 and c[t] <= xlo[t]:
            state = 0.0
        elif state < 0 and c[t] >= xhi[t]:
            state = 0.0
        pos[t] = state
    return pos


def position(kind: str, c: np.ndarray, p: dict) -> np.ndarray:
    """The position held from close t to close t+1, decided at close t."""
    lc = np.log(c)
    if kind == "tsmom":
        L = int(p["L"])
        out = np.zeros(len(c))
        out[L:] = np.sign(lc[L:] - lc[:-L])
    elif kind == "rev":
        L = int(p["L"])
        out = np.zeros(len(c))
        out[L:] = -np.sign(lc[L:] - lc[:-L])
    elif kind == "donchian":
        n = int(p["N"])
        out = donchian(c, n, max(2, int(n * p.get("exit", 0.36))))
    elif kind == "rsi":
        r = rsi(c, int(p["n"]))
        lo = p["lo"]
        out = np.where(r < lo, 1.0, np.where(r > 100 - lo, -1.0, 0.0))
    else:
        raise ValueError(kind)
    k = int(p.get("smooth", 1))
    if k > 1:
        out = pd.Series(out).rolling(k, min_periods=1).mean().to_numpy()
    return out


def scaled(c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Next-day return in units of the trailing daily sd known at t, and that sd."""
    r = np.diff(np.log(c), prepend=np.nan)
    sd = pd.Series(np.abs(r)).ewm(span=20, adjust=False).mean().to_numpy() * math.sqrt(math.pi / 2)
    nxt = np.r_[r[1:], np.nan]
    with np.errstate(divide="ignore", invalid="ignore"):
        return nxt / sd, sd


SPEC = {
    "tsmom21": ("tsmom", {"L": 21}), "tsmom63": ("tsmom", {"L": 63}), "tsmom252": ("tsmom", {"L": 252}),
    "rev5": ("rev", {"L": 5}), "donchian": ("donchian", {"N": 55, "exit": 20 / 55}),
    "rsi2": ("rsi", {"n": 2, "lo": 10}),
}


def instrument_species(sym: str, c: pd.Series, family: str, rt: pd.DataFrame | None,
                       vx: pd.Series | None) -> dict[str, pd.DataFrame]:
    """{species: DataFrame(date -> gross, turnover, pos)} for one instrument."""
    arr = c.to_numpy()
    y, sd = scaled(arr)
    out = {}
    for name, (kind, p) in SPEC.items():
        pos = position(kind, arr, p)
        out[name] = pd.DataFrame({"gross": pos * y, "turn": np.abs(np.diff(pos, prepend=0.0)),
                                  "pos": pos}, index=c.index)
    if family == "fx" and rt is not None and len(sym) == 6 and sym[:3] in rt and sym[3:] in rt:
        diff = (rt[sym[:3]] - rt[sym[3:]]).reindex(c.index).to_numpy()
        pos = np.sign(np.nan_to_num(diff))
        out["carry"] = pd.DataFrame({"gross": pos * y, "turn": np.abs(np.diff(pos, prepend=0.0)),
                                     "pos": pos}, index=c.index)
    if vx is not None and sym == "SPX":
        imp = (vx.reindex(c.index).ffill() / 100 / math.sqrt(252)).to_numpy()
        nxt = np.r_[np.diff(np.log(arr)), np.nan]
        with np.errstate(divide="ignore", invalid="ignore"):
            g = 1 - np.clip((nxt / imp) ** 2, 0, 25)
    else:
        g = 1 - np.clip(y**2, 0, 25)
    out["volsell"] = pd.DataFrame({"gross": g, "turn": np.zeros(len(arr)), "pos": np.ones(len(arr))},
                                  index=c.index)
    return out


def family_panel(family: str, series: dict[str, pd.Series], rt, vx) -> dict[str, pd.DataFrame]:
    """{species: DataFrame(date -> gross, net, consensus, pos_<sym>...)} equal-weighted."""
    per = {sym: instrument_species(sym, c, family, rt, vx) for sym, c in series.items()}
    out = {}
    for sp in SPECIES:
        frames = {sym: d[sp] for sym, d in per.items() if sp in d}
        if not frames:
            continue
        g = pd.DataFrame({s: f["gross"] for s, f in frames.items()})
        t = pd.DataFrame({s: f["turn"] for s, f in frames.items()})
        p = pd.DataFrame({s: f["pos"] for s, f in frames.items()})
        live = g.notna()
        gross = g.mean(axis=1)
        net = gross - (t.where(live).mean(axis=1) * DAILY_COST[family])
        consensus = p.where(live).mean(axis=1).abs() if sp != "volsell" else pd.Series(np.nan, index=g.index)
        df = pd.DataFrame({"gross": gross, "net": net, "consensus": consensus})
        for s in p:
            df[f"pos_{s}"] = p[s]
        out[sp] = df.dropna(subset=["gross"])
    return out


def zone_species() -> dict[str, pd.Series]:
    p = IND / "real.pkl.gz"
    if not p.exists():
        return {}
    d = pd.read_pickle(p)  # our own lab output (indicators.py), not an untrusted source
    d = d[(d["kind"] == "zone") & (d["rule"] == "touch") & (d["interval"] == "1h") & (d["h"] == 20)]
    d["day"] = pd.to_datetime(d["time"], unit="s").dt.normalize()
    return {fam: g.groupby("day")["gross"].mean() for fam, g in d.groupby("family")}


# ---------------------------------------------------------------------------------------- statistics

def nw_slope(x: np.ndarray, y: np.ndarray, lag: int) -> tuple[float, float]:
    """OLS slope of y on x with a Newey-West t."""
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    if len(x) < 30 or np.std(x) == 0:
        return float("nan"), float("nan")
    xc = x - x.mean()
    b = (xc @ (y - y.mean())) / (xc @ xc)
    e = (y - y.mean()) - b * xc
    u = xc * e
    s = u @ u
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        s += 2 * w * (u[k:] @ u[:-k])
    se = math.sqrt(max(s, 1e-18)) / (xc @ xc)
    return float(b), float(b / se)


def decay_stat(gross: pd.Series) -> tuple[float, float, float, float, int]:
    """Future 6-month return on the past 12 months, monthly: (slope, t, t first half, t second, n)."""
    m = gross.resample("ME").sum(min_count=5).dropna()
    if len(m) < 60:
        return (float("nan"),) * 4 + (len(m),)
    past = m.rolling(12).sum()
    fut = m[::-1].rolling(6).sum()[::-1].shift(-1)
    x, y = past.to_numpy(), fut.to_numpy()
    b, t = nw_slope(x, y, 12)
    h = len(m) // 2
    _, t1 = nw_slope(x[:h], y[:h], 12)
    _, t2 = nw_slope(x[h:], y[h:], 12)
    return b, t, t1, t2, len(m)


def density_stat(df: pd.DataFrame, proxy: pd.Series) -> tuple[float, float, float, float, int]:
    """Next 21 days' species return on the standardised population proxy."""
    g = df["gross"]
    fut = g[::-1].rolling(21, min_periods=15).sum()[::-1].shift(-1)
    x = proxy.reindex(g.index)
    x = (x - x.mean()) / x.std()
    xs, ys = x.to_numpy(), fut.to_numpy()
    b, t = nw_slope(xs, ys, 21)
    h = len(xs) // 2
    _, t1 = nw_slope(xs[:h], ys[:h], 21)
    _, t2 = nw_slope(xs[h:], ys[h:], 21)
    return b, t, t1, t2, int(np.isfinite(xs).sum())


def shift_null(df: pd.DataFrame, proxy: pd.Series, draws: int = 100) -> np.ndarray:
    g = df["gross"]
    x = proxy.reindex(g.index).to_numpy()
    n = len(x)
    out = []
    for _ in range(draws):
        k = int(RNG.integers(n // 10, n - n // 10))
        out.append(density_stat(df, pd.Series(np.roll(x, k), index=g.index))[1])
    return np.array(out)


def bh(pvals: list[float], q: float = 0.05) -> list[bool]:
    p = np.array(pvals, dtype=float)
    ok = np.isfinite(p)
    out = np.zeros(len(p), dtype=bool)
    if not ok.any():
        return list(out)
    idx = np.where(ok)[0]
    order = idx[np.argsort(p[idx])]
    m = len(order)
    thresh = 0
    for rank, i in enumerate(order, 1):
        if p[i] <= q * rank / m:
            thresh = rank
    out[order[:thresh]] = True
    return list(out)


def p_two(t: float) -> float:
    return float(math.erfc(abs(t) / math.sqrt(2))) if math.isfinite(t) else float("nan")


# ---------------------------------------------------------------------------------------- PART species

def load_families() -> dict[str, dict[str, pd.Series]]:
    fams = {}
    for fam, syms in FAMILIES.items():
        got = {}
        for s in syms:
            try:
                c = closes(s)
            except (FileNotFoundError, ValueError, KeyError) as exc:
                print(f"  skip {s}: {str(exc)[:60]}", flush=True)
                continue
            if len(c) > 500:
                got[s] = c
        if got:
            fams[fam] = got
    return fams


def walk_family(real: dict[str, pd.Series], seed: int) -> dict[str, pd.Series]:
    return {s: pd.Series(garch_walk(len(c), seed * 100 + i), index=c.index)
            for i, (s, c) in enumerate(real.items())}


def cftc_proxy(panel: pd.DataFrame) -> pd.Series | None:
    p = CROWD / "cftc.csv.gz"
    if not p.exists():
        return None
    c = pd.read_csv(p)
    c = c[c["report"] == "legacy"]
    c["date"] = pd.to_datetime(c["date"])
    parts = []
    for pair, (key, sign) in CFTC_FX.items():
        col = f"pos_{pair}"
        if col not in panel:
            continue
        m = c[c["market"].str.upper().str.contains(key.upper(), regex=False)
              & ~c["market"].str.upper().str.contains("XRATE|/", regex=True)]
        m = m.sort_values("date").drop_duplicates("date")
        if len(m) < 200:
            continue
        net = ((m["long"] - m["short"]) / m["oi"]).to_numpy() * sign
        z = pd.Series(net).rolling(156, min_periods=52).apply(
            lambda a: (a[-1] - a.mean()) / (a.std() + 1e-12), raw=True).to_numpy()
        public = pd.Series(z, index=m["date"] + pd.Timedelta(days=3))
        daily = public.reindex(panel.index, method="ffill")
        parts.append(panel[col] * daily)  # the crowd on the species' side
    return pd.concat(parts, axis=1).mean(axis=1) if parts else None


def funding_proxy(panel: pd.DataFrame) -> pd.Series | None:
    parts = []
    for sym, perp in CRYPTO_PERP.items():
        p = CROWD / f"{perp}.npz"
        col = f"pos_{sym}"
        if not p.exists() or col not in panel:
            continue
        z = dict(np.load(p))
        f = pd.Series(z["funding"], index=pd.to_datetime(z["t"], unit="s"))
        daily = f.resample("D").mean()
        daily = (daily - daily.rolling(30, min_periods=10).mean()) / daily.rolling(30, min_periods=10).std()
        parts.append(panel[col] * daily.reindex(panel.index))
    return pd.concat(parts, axis=1).mean(axis=1) if parts else None


def species_part() -> None:
    fams = load_families()
    rt, vx = rates(), (vix() if (CARRY / "vix.csv").exists() else None)
    zones = zone_species()
    print(f"families: {', '.join(f'{k} {len(v)}' for k, v in fams.items())}; zone days "
          f"{ {k: len(v) for k, v in zones.items()} }", flush=True)
    decay_rows, dens_rows = [], []
    panels = {}
    for fam, series in fams.items():
        panel = family_panel(fam, series, rt, vx)
        if fam in zones:
            z = zones[fam]
            panel["zone"] = pd.DataFrame({"gross": z, "net": z, "consensus": np.nan})
        panels[fam] = panel
        # walks: species on GARCH walks of the same shape
        wstats: dict[str, list[float]] = {}
        wdens: dict[str, list[float]] = {}
        for w in range(WALKS):
            wp = family_panel(fam, walk_family(series, w + 1), rt if fam == "fx" else None, None)
            for sp, df in wp.items():
                wstats.setdefault(sp, []).append(decay_stat(df["gross"])[1])
                if df["consensus"].notna().any():
                    wdens.setdefault(sp, []).append(density_stat(df, df["consensus"])[1])
        print(f"\n== {fam}: {len(series)} instruments", flush=True)
        for sp, df in panel.items():
            g = df["gross"]
            ann = g.mean() / (g.std() + 1e-12) * math.sqrt(252)
            netann = df["net"].mean() / (df["net"].std() + 1e-12) * math.sqrt(252)
            b, t, t1, t2, n = decay_stat(g)
            band = np.nanpercentile(wstats.get(sp, [np.nan]), [2.5, 97.5]) if sp in wstats else [np.nan, np.nan]
            decay_rows.append(dict(fam=fam, sp=sp, b=b, t=t, t1=t1, t2=t2, n=n, lo=band[0], hi=band[1]))
            print(f"  {sp:9s} days {len(g):6,} gross Sharpe {ann:+.2f} net {netann:+.2f} | decay slope "
                  f"{b:+.3f} t {t:+.2f} (halves {t1:+.2f} / {t2:+.2f}, {n} months) walks t 95% "
                  f"[{band[0]:+.2f}, {band[1]:+.2f}]", flush=True)
            proxies = {}
            if df["consensus"].notna().any():
                proxies["consensus"] = df["consensus"]
            if fam == "fx" and sp != "volsell":
                cp = cftc_proxy(df)
                if cp is not None:
                    proxies["cftc"] = cp
            if fam == "crypto" and sp != "volsell":
                fp = funding_proxy(df)
                if fp is not None:
                    proxies["funding"] = fp
            for pname, proxy in proxies.items():
                b, t, t1, t2, n = density_stat(df, proxy)
                null = shift_null(df, proxy, 60)
                wband = (np.nanpercentile(wdens[sp], [2.5, 97.5]) if pname == "consensus" and sp in wdens
                         else [np.nan, np.nan])
                pshift = float(np.mean(null <= t)) if np.isfinite(t) else float("nan")
                dens_rows.append(dict(fam=fam, sp=sp, proxy=pname, b=b, t=t, t1=t1, t2=t2, n=n,
                                      pshift=pshift, wlo=wband[0], whi=wband[1]))
                print(f"      density {pname:9s} slope {b:+.4f} t {t:+.2f} (halves {t1:+.2f} / {t2:+.2f},"
                      f" n {n:,}) | shift-null P(t <= this) {pshift:.2f} | walks t 95% "
                      f"[{wband[0]:+.2f}, {wband[1]:+.2f}]", flush=True)
        # predator-prey: monthly VAR(1) among tsmom63, rev5, donchian
        keys = [k for k in ("tsmom63", "rev5", "donchian") if k in panel]
        m = pd.DataFrame({k: panel[k]["gross"].resample("ME").sum(min_count=5) for k in keys}).dropna()
        if len(m) > 60:
            print("    predator-prey (monthly VAR(1), row = next month, column = this month; t):", flush=True)
            for a in keys:
                cells = []
                for bk in keys:
                    bb, tt = nw_slope(m[bk].to_numpy()[:-1], m[a].to_numpy()[1:], 3)
                    cells.append(f"{bk} {bb:+.3f} (t {tt:+.1f})")
                print(f"      {a:9s} <- " + " | ".join(cells), flush=True)
    # verdicts
    print("\n== VERDICTS (pre-registered)", flush=True)
    dr = pd.DataFrame(decay_rows)
    dr["p"] = [p_two(t) for t in dr["t"]]
    dr["bh"] = bh(dr["p"].tolist())
    dr["pass"] = (dr["t"] <= -3) & (dr["t1"] < 0) & (dr["t2"] < 0) & dr["bh"] & (dr["t"] < dr["lo"])
    print(f"  decay-and-recovery passes: {int(dr['pass'].sum())} of {len(dr)} species-families "
          f"(negative slope, t <= -3, both halves, BH, outside walks)", flush=True)
    for _, r in dr[dr["pass"]].iterrows():
        print(f"    {r['fam']} {r['sp']} t {r['t']:+.2f}", flush=True)
    ds = pd.DataFrame(dens_rows)
    if len(ds):
        ds["p"] = [p_two(t) for t in ds["t"]]
        ds["bh"] = bh(ds["p"].tolist())
        beyond_walks = ds["wlo"].isna() | (ds["t"] < ds["wlo"])
        ds["pass"] = (ds["t"] <= -3) & (ds["t1"] < 0) & (ds["t2"] < 0) & ds["bh"] & (ds["pshift"] <= 0.05) & beyond_walks
        print(f"  density dependence passes: {int(ds['pass'].sum())} of {len(ds)} (species x proxy)", flush=True)
        for _, r in ds[ds["pass"]].iterrows():
            print(f"    {r['fam']} {r['sp']} {r['proxy']} t {r['t']:+.2f}", flush=True)
        print(f"  signs: {int((ds['t'] < 0).sum())} of {len(ds)} density slopes negative; "
              f"{int((ds['t'] <= -2).sum())} at t <= -2, {int((ds['t'] >= 2).sum())} at t >= 2", flush=True)
    print(f"  decay slopes: {int((dr['t'] < 0).sum())} of {len(dr)} negative; {int((dr['t'] <= -2).sum())} "
          f"at t <= -2, {int((dr['t'] >= 2).sum())} at t >= 2", flush=True)


# ---------------------------------------------------------------------------------------- PART ga

KINDS = ["tsmom", "rev", "donchian", "rsi"]
BOUNDS = {"tsmom": {"L": (5, 300)}, "rev": {"L": (1, 20)}, "donchian": {"N": (10, 150), "exit": (0.2, 1.0)},
          "rsi": {"n": (2, 14), "lo": (5, 35)}}


def random_genome(rng) -> dict:
    kind = KINDS[int(rng.integers(len(KINDS)))]
    g = {"kind": kind, "smooth": int(rng.integers(1, 11))}
    for k, (lo, hi) in BOUNDS[kind].items():
        g[k] = float(rng.uniform(lo, hi))
    return g


def mutate(g: dict, rng) -> dict:
    if rng.random() < 0.1:
        return random_genome(rng)
    h = dict(g)
    for k, (lo, hi) in BOUNDS[h["kind"]].items():
        h[k] = float(np.clip(h[k] + rng.normal(0, 0.15 * (hi - lo)), lo, hi))
    if rng.random() < 0.3:
        h["smooth"] = int(np.clip(h["smooth"] + rng.integers(-2, 3), 1, 10))
    return h


def evaluate(g: dict, data: list[tuple[np.ndarray, np.ndarray]], cost: float) -> np.ndarray:
    """Daily net return series, equal-weighted across instruments (aligned by position)."""
    rets = []
    for c, y in data:
        pos = position(g["kind"], c, g)
        r = pos * y - np.abs(np.diff(pos, prepend=0.0)) * cost
        rets.append(r)
    n = min(len(r) for r in rets)
    return np.nanmean(np.vstack([r[-n:] for r in rets]), axis=0)


def sharpe(r: np.ndarray) -> float:
    r = r[np.isfinite(r)]
    return float(r.mean() / (r.std() + 1e-12) * math.sqrt(252)) if len(r) > 50 else float("nan")


def turnover(g: dict, data) -> float:
    return float(np.mean([np.nanmean(np.abs(np.diff(position(g["kind"], c, g)))) for c, _ in data]))


def psr(r: np.ndarray, bench: float = 0.0) -> float:
    """Probabilistic Sharpe ratio (daily), against a daily benchmark Sharpe."""
    r = r[np.isfinite(r)]
    n = len(r)
    sr = r.mean() / (r.std() + 1e-12)
    g3 = float(pd.Series(r).skew())
    g4 = float(pd.Series(r).kurt()) + 3
    den = math.sqrt(max(1 - g3 * sr + (g4 - 1) / 4 * sr**2, 1e-12))
    z = (sr - bench) * math.sqrt(n - 1) / den
    return 0.5 * math.erfc(-z / math.sqrt(2))


def evolve(train, cost: float, rng, pop: int = 80, gens: int = 30) -> tuple[list[dict], list[float]]:
    genomes = [random_genome(rng) for _ in range(pop)]
    fits = [sharpe(evaluate(g, train, cost)) for g in genomes]
    all_fits = list(fits)
    for _ in range(gens):
        order = np.argsort(np.nan_to_num(fits, nan=-9))[::-1]
        elite = [genomes[i] for i in order[:4]]
        new = list(elite)
        while len(new) < pop:
            a, b = rng.integers(pop, size=2)
            parent = genomes[a] if np.nan_to_num(fits[a], nan=-9) >= np.nan_to_num(fits[b], nan=-9) else genomes[b]
            new.append(mutate(parent, rng))
        genomes = new
        fits = [sharpe(evaluate(g, train, cost)) for g in genomes]
        all_fits.extend(fits)
    order = np.argsort(np.nan_to_num(fits, nan=-9))[::-1]
    return [genomes[i] for i in order], all_fits


def split(series: dict[str, pd.Series]):
    train, test = [], []
    for c in series.values():
        arr = c.to_numpy()
        y, _ = scaled(arr)
        cut = int(len(arr) * 0.6)
        train.append((arr[:cut], y[:cut]))
        test.append((arr[cut:], y[cut:]))
    return train, test


def ga_part() -> None:
    fams = load_families()
    rows = []
    for fam, series in list(fams.items()) + [("walks-" + f, None) for f in ("fx", "crypto")]:
        if series is None:
            base = fams[fam.split("-")[1]]
            series = walk_family(base, 7)
            cost_fam = fam.split("-")[1]
        else:
            cost_fam = fam
        rng = np.random.default_rng(11)
        train, test = split(series)
        cost = DAILY_COST[cost_fam]
        ranked, all_fits = evolve(train, cost, rng)
        best = ranked[0]
        oos_best = evaluate(best, test, cost)
        top = [sharpe(evaluate(g, test, cost)) for g in ranked[:10]]
        rand = np.array([sharpe(evaluate(random_genome(rng), test, cost)) for _ in range(500)])
        pct = float(np.mean(rand < sharpe(oos_best)))
        # the deflation benchmark: the expected maximum train Sharpe among the evaluations, in daily units
        sd_sr = np.nanstd(all_fits) / math.sqrt(252)
        n_eff = len(all_fits) / 5  # evaluations are highly correlated across generations
        emax = sd_sr * ((1 - 0.5772) * _ninv(1 - 1 / n_eff) + 0.5772 * _ninv(1 - 1 / (n_eff * math.e)))
        dsr = psr(oos_best, emax)
        p0 = psr(oos_best, 0.0)
        # cost pressure: evolve without costs and compare turnover of the final populations
        ranked0, _ = evolve(train, 0.0, np.random.default_rng(11))
        t_cost = np.mean([turnover(g, train) for g in ranked[:20]])
        t_free = np.mean([turnover(g, train) for g in ranked0[:20]])
        kinds = pd.Series([g["kind"] for g in ranked[:20]]).value_counts().to_dict()
        kinds0 = pd.Series([g["kind"] for g in ranked0[:20]]).value_counts().to_dict()
        rows.append(dict(fam=fam, train=sharpe(evaluate(best, train, cost)), oos=sharpe(oos_best), pct=pct,
                         psr=p0, dsr=dsr))
        print(f"\n== {fam}: best {best}", flush=True)
        print(f"  train Sharpe {rows[-1]['train']:+.2f} -> out of sample {rows[-1]['oos']:+.2f} (decay "
              f"{rows[-1]['train'] - rows[-1]['oos']:+.2f}) | top-10 OOS median {np.nanmedian(top):+.2f}", flush=True)
        print(f"  random rules OOS: median {np.nanmedian(rand):+.2f}, 95th {np.nanpercentile(rand, 95):+.2f}; "
              f"fittest beats {pct:.0%} | PSR(>0) {p0:.3f} | DSR {dsr:.3f} (trials {len(all_fits)}, "
              f"effective {n_eff:.0f})", flush=True)
        print(f"  selection with costs: top-20 turnover {t_cost:.3f}/day {kinds} | without costs "
              f"{t_free:.3f}/day {kinds0}", flush=True)
    print("\n== VERDICT: fittest beats 95% of random rules and DSR > 0.95", flush=True)
    for r in rows:
        ok = r["pct"] >= 0.95 and r["dsr"] > 0.95
        print(f"  {r['fam']:14s} {'PASS' if ok else 'fail'} (OOS {r['oos']:+.2f}, beats {r['pct']:.0%}, "
              f"DSR {r['dsr']:.3f})", flush=True)


def _ninv(p: float) -> float:
    from statistics import NormalDist

    return NormalDist().inv_cdf(min(max(p, 1e-12), 1 - 1e-12))


# ---------------------------------------------------------------------------------------- PART contagion

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
         "LINKUSDT", "LTCUSDT"]


def hourly(real: bool = True, seed: int = 0) -> pd.DataFrame:
    frames = {}
    if real:
        for sym in COINS:
            p = CROWD / f"{sym}.npz"
            if not p.exists():
                continue
            z = dict(np.load(p))
            idx = pd.to_datetime(z["t"], unit="s")
            frames[sym] = pd.DataFrame({"close": z["close"], "funding": z["funding"], "oi": z["oi"]}, index=idx)
    else:
        rng = np.random.default_rng(seed)
        n = 40_000
        idx = pd.date_range("2022-01-01", periods=n, freq="h")
        # a common GARCH factor plus idiosyncratic GARCH: co-shocks with no contagion structure
        f = np.diff(np.log(garch_walk(n + 1, seed + 1000)))
        for i, sym in enumerate(COINS):
            e = np.diff(np.log(garch_walk(n + 1, seed * 50 + i)))
            r = 0.7 * f + 0.7 * e
            frames[sym] = pd.DataFrame({"close": 100 * np.exp(np.cumsum(r)), "funding": np.nan, "oi": np.nan},
                                       index=idx)
    return pd.concat(frames, names=["sym"]).reset_index(level=0)


def contagion_features(h: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    rows = []
    shocks = {}
    for sym, g in h.groupby("sym"):
        g = g[~g.index.duplicated()].sort_index()
        r = np.log(g["close"]).diff()
        a = r.abs()
        norm = a.rolling(500, min_periods=250).mean().shift(1)
        shock = (a > 4 * norm).astype(float).where(norm.notna())
        shocks[sym] = shock
        ew = a.ewm(span=14, adjust=False).mean()
        lvol = np.log(ew / norm)
        vov = lvol.rolling(50, min_periods=20).std()
        fut = shock[::-1].rolling(4, min_periods=4).max()[::-1].shift(-1)
        fz = ((g["funding"] - g["funding"].rolling(720, min_periods=240).mean())
              / g["funding"].rolling(720, min_periods=240).std())
        oi = np.log(g["oi"]).diff(24)
        oiz = (oi - oi.rolling(720, min_periods=240).mean()) / oi.rolling(720, min_periods=240).std()
        rows.append(pd.DataFrame({
            "sym": sym, "y": fut, "lvol": lvol, "vov": vov,
            "own20": shock.rolling(20, min_periods=1).sum(), "own100": shock.rolling(100, min_periods=1).sum(),
            "hs": np.sin(2 * np.pi * g.index.hour / 24), "hc": np.cos(2 * np.pi * g.index.hour / 24),
            "fundz": fz, "oiz": oiz, "shock": shock}, index=g.index))
    d = pd.concat(rows)
    inc = pd.DataFrame(shocks).sum(axis=1)  # market-wide incidence per hour
    recent = inc.rolling(6, min_periods=1).mean()
    prior = inc.shift(6).rolling(24, min_periods=6).mean()
    rt = (recent + 0.05) / (prior + 0.05)
    d["R"] = rt.reindex(d.index).to_numpy()
    d["inc6"] = inc.rolling(6, min_periods=1).sum().reindex(d.index).to_numpy()
    d["cross6"] = d["inc6"] - d["shock"].groupby(d["sym"]).transform(lambda s: s.rolling(6, min_periods=1).sum())
    return d, inc


def fit_hawkes(times: np.ndarray, T: float) -> tuple[float, float, float]:
    """Exponential-kernel Hawkes MLE: (mu, alpha, beta) in events per hour."""
    from scipy.optimize import minimize

    t = np.sort(times)

    def nll(theta):
        mu, al, be = np.exp(theta)
        a = np.zeros(len(t))
        for i in range(1, len(t)):
            a[i] = math.exp(-be * (t[i] - t[i - 1])) * (1 + a[i - 1])
        lam = mu + al * a
        comp = mu * T + (al / be) * np.sum(1 - np.exp(-be * (T - t)))
        return comp - np.sum(np.log(lam + 1e-12))

    res = minimize(nll, np.log([len(t) / T * 0.5, 0.5, 1.0]), method="Nelder-Mead",
                   options={"maxiter": 400, "xatol": 1e-3, "fatol": 1e-2})
    return tuple(float(v) for v in np.exp(res.x))


def hawkes_intensity(inc: pd.Series, mu: float, al: float, be: float) -> pd.Series:
    lam = np.empty(len(inc))
    a = 0.0
    vals = inc.to_numpy()
    for i in range(len(vals)):
        lam[i] = mu + al * a  # intensity for this hour, from past events only
        a = a * math.exp(-be) + vals[i]
    return pd.Series(lam / mu, index=inc.index)


def contagion_run(h: pd.DataFrame, label: str) -> dict:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    d, inc = contagion_features(h)
    times = np.sort(np.unique(d.index))
    cut_t = times[int(len(times) * 0.6)]
    tr_inc = inc[inc.index < cut_t]
    ev = np.repeat(np.arange(len(tr_inc), dtype=float), tr_inc.fillna(0).astype(int).to_numpy())
    mu, al, be = fit_hawkes(ev + 0.5, float(len(tr_inc)))
    d["hawkes"] = hawkes_intensity(inc.fillna(0), mu, al, be).reindex(d.index).to_numpy()
    base = ["lvol", "vov", "own20", "own100", "hs", "hc"]
    sets = {"base": base, "+R": base + ["R"], "+hawkes": base + ["hawkes"], "+cross": base + ["cross6"],
            "+susceptible": base + ["fundz", "oiz"], "+all": base + ["R", "hawkes", "cross6", "fundz", "oiz"]}
    d = d.dropna(subset=["y"] + base)
    tr, te = d[d.index < cut_t], d[d.index >= cut_t]
    preds = {}
    for name, cols in sets.items():
        m = HistGradientBoostingClassifier(max_depth=4, max_iter=150, learning_rate=0.05, min_samples_leaf=300)
        m.fit(tr[cols], tr["y"])
        preds[name] = m.predict_proba(te[cols])[:, 1]
    y = te["y"].to_numpy()
    days = te.index.asi8 // 86_400_000_000_000
    uniq = np.unique(days)
    by = {u: np.flatnonzero(days == u) for u in uniq}
    base_auc = roc_auc_score(y, preds["base"])
    out = {"label": label, "branching": al / be, "mu": mu, "base": base_auc}
    print(f"\n== {label}: {len(d):,} coin-hours, shock rate {d['y'].mean():.3f} | Hawkes on training "
          f"incidence: mu {mu:.3f}/h, alpha {al:.3f}, beta {be:.3f}, branching n = {al / be:.2f}", flush=True)
    print(f"  base (shock-forecaster features) AUC {base_auc:.4f}", flush=True)
    half = len(te) // 2
    for name in sets:
        if name == "base":
            continue
        gain = roc_auc_score(y, preds[name]) - base_auc
        draws = []
        for _ in range(200):
            idx = np.concatenate([by[u] for u in RNG.choice(uniq, len(uniq))])
            if y[idx].min() == y[idx].max():
                continue
            draws.append(roc_auc_score(y[idx], preds[name][idx]) - roc_auc_score(y[idx], preds["base"][idx]))
        lo, hi = np.percentile(draws, [2.5, 97.5])
        g1 = roc_auc_score(y[:half], preds[name][:half]) - roc_auc_score(y[:half], preds["base"][:half])
        g2 = roc_auc_score(y[half:], preds[name][half:]) - roc_auc_score(y[half:], preds["base"][half:])
        out[name] = (gain, lo, hi, g1, g2)
        print(f"  {name:13s} AUC gain {gain:+.4f} [{lo:+.4f}, {hi:+.4f}] halves {g1:+.4f} / {g2:+.4f}", flush=True)
    # does R(t) > 1 precede cascades (>= 3 coins shocking within the next 4 hours)?
    fut_inc = inc[::-1].rolling(4, min_periods=4).sum()[::-1].shift(-1)
    rt = d.groupby(level=0)["R"].first()
    test_t = rt.index >= cut_t
    cascade = (fut_inc.reindex(rt.index) >= 3)[test_t]
    above = (rt > 1)[test_t]
    if cascade.notna().any() and above.any():
        p1 = cascade[above].mean()
        p0 = cascade[~above].mean()
        print(f"  cascade (>= 3 coin-shocks in 4h) after R(t) > 1: {p1:.3f} against {p0:.3f} otherwise "
              f"(lift {p1 / max(p0, 1e-9):.2f}x; R > 1 on {above.mean():.0%} of hours)", flush=True)
    return out


def contagion_part() -> None:
    real = contagion_run(hourly(True), "crypto, real")
    walks = [contagion_run(hourly(False, s), f"walks (common GARCH factor) #{s}") for s in (1, 2)]
    print("\n== VERDICT: incremental AUC >= 0.01, CI above 0, both halves, and above the walks' gain", flush=True)
    for name in ("+R", "+hawkes", "+cross", "+susceptible", "+all"):
        if name not in real:
            continue
        gain, lo, hi, g1, g2 = real[name]
        wg = max(w.get(name, (0,))[0] for w in walks)
        ok = gain >= 0.01 and lo > 0 and g1 > 0 and g2 > 0 and gain > wg
        print(f"  {name:13s} {'PASS' if ok else 'fail'}: gain {gain:+.4f} [{lo:+.4f}, {hi:+.4f}], walks up to "
              f"{wg:+.4f}", flush=True)


if __name__ == "__main__":
    {"species": species_part, "ga": ga_part, "contagion": contagion_part}[PART]()
