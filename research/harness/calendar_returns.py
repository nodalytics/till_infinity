"""Returns by weekday and hour: the whole distribution, every family, and what survives.

The desk asked for the return distribution by day of the week and hour of the day. `fxtod.md`
already tested one hour theory (Ranaldo's home-hours depreciation: it fails, and the FX hours that
persist are the 20-23 UTC rollover); `rollover.md`, `vetoes.md`, `fridayflag.md` and `gaptrade.md`
cover the rollover, the Sunday open and the weekend gap. This is the full weekday x hour picture,
168 buckets per family, and not only the mean.

Data: seqlab 1h bars from START, per family - FX (15 pairs), metals, crypto, and Deriv's families
(Volatility, Boom/Crash, Jump, Step, Range Break) as markets. Controls are walks we generate: an
FX-calendar walk (Sunday 22:00 to Friday 21:00 UTC, as `fridayflag.walk_frame`) and a 24/7 walk
for crypto and Deriv, both iid Student-t(3).

The hour's own move is r = log(close / open), so a weekend gap is not smeared into Monday's first
hour (the gap is `gaptrade.md`'s subject). In volatility units it is y = r / sigma, sigma the
production unit - the EWMA of true range, alpha 1/14 - as of the previous bar, so known before the
hour. Buckets are UTC weekday x hour, and for FX and metals also New York local weekday x hour, so
daylight saving does not smear the rollover across two UTC hours.

Per bucket and family: mean (vol units and bps), sd, mean |y|, skew, excess kurtosis, the share of
|y| beyond 3 of the family's sd, the up-share, and the range (high - low) in vol units. Printed as
weekday x hour heatmaps of the volatility ratio (bucket mean |y| over the family's), the drift
(mean y in hundredths of a vol unit) and the tail ratio.

Out of sample, 60/40 by time:
  drift     per-bucket t on discovery, day-clustered (a bucket has one bar per series per day, and
            series on one day are averaged first), Benjamini-Hochberg at q = 0.05 across the 168;
            how many survive, and how many of those have the same sign with p < 0.05 in
            verification. And the correlation of the two halves' 168-bucket drift profiles.
  vol       the discovery profile of mean |y| by bucket as a forecast of verification |y|: R^2
            against the constant, and whether multiplying the production sigma by the profile's
            ratio beats sigma alone at forecasting the next hour's |r| (relative MSE, fitted scale)
  trade     pre-registered: the 5 most positive and 5 most negative drift buckets by discovery t,
            held for their hour in verification (long / short), net of COST_V x sqrt(5/60) per
            round trip in hourly-vol units. Mean net per trade, day-clustered t, verification's two
            halves, and the same rule on the walks
  weekday   the day's summed y by weekday, discovery and verification, day-clustered; crypto's
            weekend against weekdays, drift and vol
  deriv     Deriv's generators are published as time-invariant, but it is a market: any weekday x
            hour structure there is a finding about the feed. The vol profile's ANOVA F and its
            out-of-sample R^2, against the 24/7 walk's

Pre-registered: a drift bucket counts only if it survives BH on discovery and holds its sign with
p < 0.05 in verification. The trade passes only if its verification net mean is positive with
t >= 3 in both of verification's halves and the walks' rule does not. A vol profile is worth
production if its out-of-sample relative MSE against sigma alone is below 0.97 in both halves.

Run on the lab:
  SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/calendar_returns.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

START = pd.Timestamp(os.environ.get("START", "2019-01-01"), tz="UTC").timestamp()
END = os.environ.get("END", "2026-09-01")
SPLIT = 0.6
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

FAMILIES = {
    "fx": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
           "EURGBP", "AUDJPY", "EURAUD", "CHFJPY", "EURCHF", "USDCNH"],
    "metals": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "deriv volatility": ["Volatility_10_Index", "Volatility_25_Index", "Volatility_50_Index",
                         "Volatility_75_Index", "Volatility_100_Index"],
    "deriv boom/crash": ["Boom_1000_Index", "Boom_500_Index", "Crash_1000_Index", "Crash_500_Index"],
    "deriv jump": ["Jump_10_Index", "Jump_25_Index", "Jump_50_Index", "Jump_75_Index", "Jump_100_Index"],
    "deriv step": ["Step_Index", "Step_Index_200"],
    "deriv range break": ["Range_Break_100_Index", "Range_Break_200_Index"],
    "walks fx-calendar": [f"walkfx_{i}" for i in range(6)],
    "walks 24/7": [f"walk247_{i}" for i in range(5)],
}
NEW_YORK_TOO = ("fx", "metals", "walks fx-calendar")
COST_V = {"fx": 0.8, "metals": 0.16, "crypto": 0.5}  # M5-vol units; Deriv and walks 0.15
COST_SCALE = np.sqrt(5 / 60)  # into hourly-vol units


def walk(kind: str, i: int) -> pd.DataFrame:
    """Our controls: iid Student-t(3) hourly moves, on the FX calendar or around the clock."""
    rng = np.random.default_rng((1000 if kind == "fx" else 2000) + i)
    hours = pd.date_range(pd.Timestamp(START, unit="s", tz="UTC"), pd.Timestamp(END, tz="UTC"), freq="1h")
    if kind == "fx":
        wd, hr = hours.weekday, hours.hour
        hours = hours[~((wd == 5) | ((wd == 4) & (hr >= 21)) | ((wd == 6) & (hr < 22)))]
    sd = 0.001 / np.sqrt(3.0)
    moves = rng.standard_t(3, len(hours)) * sd
    close = 1.1 * np.exp(np.cumsum(moves))
    open_ = np.r_[1.1, close[:-1]]
    wick = np.abs(rng.standard_t(3, (len(close), 2))) * sd * 0.5
    return pd.DataFrame({"ts": (hours.asi8 // 10**9).astype(np.int64), "open": open_,
                         "high": np.maximum(open_, close) * np.exp(wick[:, 0]),
                         "low": np.minimum(open_, close) * np.exp(-wick[:, 1]), "close": close})


def frame(sym: str, family: str) -> pd.DataFrame | None:
    if sym.startswith("walkfx_"):
        df = walk("fx", int(sym.split("_")[1]))
    elif sym.startswith("walk247_"):
        df = walk("247", int(sym.split("_")[1]))
    else:
        try:
            df = spikerisk.load(None, sym, "SEQLAB", "1h")
        except (ValueError, FileNotFoundError) as exc:
            print(f"  skip {sym}: {str(exc)[:60]}", flush=True)
            return None
        df = df[df["ts"] >= START]
    if len(df) < 2000:
        return None
    o, h, lo, c = (np.log(df[k].to_numpy(float)) for k in ("open", "high", "low", "close"))
    prev = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.column_stack([h - lo, np.abs(h - prev), np.abs(lo - prev)]), axis=1)
    sig = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().shift(1).to_numpy()
    r = c - o
    t = pd.to_datetime(df["ts"].to_numpy(), unit="s", utc=True)
    out = pd.DataFrame({
        "sym": sym, "family": family, "ts": df["ts"].to_numpy(), "r": r, "sig": sig,
        "y": r / sig, "rng": (h - lo) / sig, "wd": t.weekday, "hr": t.hour,
        "day": (df["ts"].to_numpy() // 86_400).astype(np.int64),
    })
    ny = t.tz_convert("America/New_York")
    out["wd_ny"], out["hr_ny"] = ny.weekday, ny.hour
    out = out[np.isfinite(out["y"]) & (out["sig"] > 0)]
    return out[out["y"].abs() < 50]  # a bad print, not a market move


def cost(family: str) -> float:
    return COST_V.get(family, 0.15) * COST_SCALE


# --------------------------------------------------------------------------------------------- stats

def day_t(values: np.ndarray, days: np.ndarray) -> tuple[float, float, int]:
    """Mean over days (series on one day averaged first) and its t."""
    s = pd.Series(values).groupby(days).mean()
    n = len(s)
    if n < 5 or s.std(ddof=1) == 0:
        return float(s.mean()) if n else float("nan"), float("nan"), n
    return float(s.mean()), float(s.mean() / (s.std(ddof=1) / np.sqrt(n))), n


def pvalue(t: float) -> float:
    from math import erf, sqrt
    return float(2 * (1 - 0.5 * (1 + erf(abs(t) / sqrt(2))))) if np.isfinite(t) else 1.0


def bh(p: np.ndarray, q: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg: which hypotheses survive at false-discovery rate q."""
    order = np.argsort(p)
    m = len(p)
    ok = p[order] <= q * np.arange(1, m + 1) / m
    k = np.max(np.flatnonzero(ok)) + 1 if ok.any() else 0
    out = np.zeros(m, bool)
    out[order[:k]] = True
    return out


def buckets(df: pd.DataFrame, wd: str, hr: str) -> pd.DataFrame:
    sd = df["y"].std()
    g = df.groupby([wd, hr])
    stat = g["y"].agg(n="size", mean="mean", sd="std", skew="skew")
    stat["kurt"] = g["y"].apply(lambda v: v.kurt())
    stat["absm"] = g["y"].apply(lambda v: v.abs().mean())
    stat["tail"] = g["y"].apply(lambda v: (v.abs() > 3 * sd).mean())
    stat["up"] = g["y"].apply(lambda v: (v > 0).mean())
    stat["rng"] = g["rng"].mean()
    stat["bps"] = g["r"].mean() * 1e4
    stat["absbps"] = g["r"].apply(lambda v: v.abs().mean() * 1e4)
    return stat


def heat(stat: pd.DataFrame, col: str, scale: float, fmt: str, title: str, days: list[int]) -> None:
    print(f"    {title}")
    print("         " + "".join(f"{h:>5d}" for h in range(24)))
    for d in days:
        cells = []
        for h in range(24):
            v = stat[col].get((d, h), np.nan) if (d, h) in stat.index else np.nan
            cells.append(f"{'':>5s}" if not np.isfinite(v) else f"{v * scale:{fmt}}")
        print(f"    {DAYS[d]:>4s} " + "".join(cells))


# --------------------------------------------------------------------------------------------- study

def describe(df: pd.DataFrame, fam: str, wd: str, hr: str, clock: str) -> None:
    stat = buckets(df, wd, hr)
    stat = stat[stat["n"] >= 30]
    days = sorted({d for d, _ in stat.index})
    overall_abs = df["y"].abs().mean()
    overall_tail = (df["y"].abs() > 3 * df["y"].std()).mean()
    stat["volr"] = stat["absm"] / overall_abs
    stat["tailr"] = stat["tail"] / max(overall_tail, 1e-9)
    print(f"\n  -- {fam} · {clock} · {len(df):,} bars · mean |y| {overall_abs:.3f} · "
          f"mean |r| {df['r'].abs().mean() * 1e4:.2f} bps · tail rate {overall_tail:.2%}")
    heat(stat, "volr", 1.0, "5.2f", "volatility ratio: bucket mean |y| / the family's", days)
    heat(stat, "mean", 100.0, "5.0f", "drift: mean y, hundredths of a vol unit", days)
    heat(stat, "tailr", 1.0, "5.1f", "tail ratio: share of |y| > 3 sd / the family's", days)
    top = stat.sort_values("volr", ascending=False).head(5)
    low = stat.sort_values("volr").head(5)
    fmt = lambda s: ", ".join(f"{DAYS[d]} {h:02d}h {v:.2f}x ({b:.1f}bps)" for (d, h), v, b in
                              zip(s.index, s["volr"], s["absbps"], strict=True))
    print(f"    most volatile: {fmt(top)}")
    print(f"    quietest:      {fmt(low)}")
    sk = stat.sort_values("skew")
    print(f"    skew range {stat['skew'].min():+.2f} to {stat['skew'].max():+.2f} "
          f"(most negative {DAYS[sk.index[0][0]]} {sk.index[0][1]:02d}h, most positive "
          f"{DAYS[sk.index[-1][0]]} {sk.index[-1][1]:02d}h) | excess kurtosis {stat['kurt'].median():.1f} "
          f"median, {stat['kurt'].max():.1f} max | up-share {stat['up'].min():.1%}-{stat['up'].max():.1%}")


def persistence(df: pd.DataFrame, fam: str, wd: str, hr: str, clock: str) -> dict:
    cut = df["ts"].quantile(SPLIT)
    disc, ver = df[df["ts"] < cut], df[df["ts"] >= cut]
    keys = sorted(set(zip(df[wd], df[hr], strict=True)))
    rows = []
    for key in keys:
        md = (disc[wd] == key[0]) & (disc[hr] == key[1])
        mv = (ver[wd] == key[0]) & (ver[hr] == key[1])
        if md.sum() < 30 or mv.sum() < 30:
            continue
        m1, t1, _ = day_t(disc.loc[md, "y"].to_numpy(), disc.loc[md, "day"].to_numpy())
        m2, t2, _ = day_t(ver.loc[mv, "y"].to_numpy(), ver.loc[mv, "day"].to_numpy())
        rows.append({"key": key, "m1": m1, "t1": t1, "p1": pvalue(t1), "m2": m2, "t2": t2,
                     "p2": pvalue(t2), "a1": disc.loc[md, "y"].abs().mean(),
                     "a2": ver.loc[mv, "y"].abs().mean()})
    tab = pd.DataFrame(rows)
    survive = bh(tab["p1"].to_numpy())
    held = survive & (np.sign(tab["m1"]) == np.sign(tab["m2"])) & (tab["p2"] < 0.05)
    corr_drift = float(np.corrcoef(tab["m1"], tab["m2"])[0, 1])
    corr_vol = float(np.corrcoef(tab["a1"], tab["a2"])[0, 1])
    print(f"\n  -- {fam} · {clock} · persistence, 60/40: {len(tab)} buckets")
    print(f"    drift: {survive.sum()} survive BH (q 0.05) on discovery, {held.sum()} hold sign with "
          f"p < 0.05 in verification | discovery-verification profile corr {corr_drift:+.2f}")
    for _, row in tab[survive].sort_values("t1").iterrows():
        d, h = row["key"]
        print(f"      {DAYS[d]} {h:02d}h  disc {row['m1'] * 100:+.1f} (t {row['t1']:+.1f})  "
              f"ver {row['m2'] * 100:+.1f} (t {row['t2']:+.1f})")
    # vol profile as a forecast of |y| in verification
    prof = {row["key"]: row["a1"] for _, row in tab.iterrows()}
    k = list(zip(ver[wd], ver[hr], strict=True))
    pred = np.array([prof.get(x, np.nan) for x in k])
    ok = np.isfinite(pred)
    a = ver["y"].abs().to_numpy()[ok]
    r2 = 1 - np.sum((a - pred[ok]) ** 2) / np.sum((a - disc["y"].abs().mean()) ** 2)
    # does the profile improve the production sigma's forecast of the next hour's |r|?
    base = disc["y"].abs().mean()
    ratio = np.array([prof.get(x, base) / base for x in k])
    absr = ver["r"].abs().to_numpy()
    s = ver["sig"].to_numpy()
    halves = []
    vt = ver["ts"].to_numpy()
    mid = np.quantile(vt, 0.5)
    for part in (vt < mid, vt >= mid):
        c1 = np.sum(absr[part] * s[part]) / np.sum(s[part] ** 2)
        c2 = np.sum(absr[part] * s[part] * ratio[part]) / np.sum((s[part] * ratio[part]) ** 2)
        mse1 = np.mean((absr[part] - c1 * s[part]) ** 2)
        mse2 = np.mean((absr[part] - c2 * s[part] * ratio[part]) ** 2)
        halves.append(mse2 / mse1)
    print(f"    vol: discovery-verification profile corr {corr_vol:+.2f} | profile R^2 on "
          f"verification |y| {r2:+.3f} | sigma x profile vs sigma alone, relative MSE of next-hour "
          f"|r|: {halves[0]:.3f} / {halves[1]:.3f} (halves)")
    return {"tab": tab, "disc": disc, "ver": ver, "corr_vol": corr_vol, "rel_mse": halves}


def trade(fam: str, p: dict, wd: str, hr: str) -> None:
    tab = p["tab"].sort_values("t1")
    shorts = [tuple(x) for x in tab.head(5)["key"]]
    longs = [tuple(x) for x in tab.tail(5)["key"]]
    ver = p["ver"]
    key = list(zip(ver[wd], ver[hr], strict=True))
    side = np.array([1.0 if k in longs else -1.0 if k in shorts else 0.0 for k in key])
    m = side != 0
    net = side[m] * ver["y"].to_numpy()[m] - cost(fam)
    days = ver["day"].to_numpy()[m]
    mean, t, n = day_t(net, days)
    vt = ver["ts"].to_numpy()[m]
    mid = np.quantile(vt, 0.5) if len(vt) else 0
    h = [day_t(net[part], days[part])[:2] for part in (vt < mid, vt >= mid)]
    fmt = lambda ks: ", ".join(f"{DAYS[d]} {hh:02d}h" for d, hh in ks)
    print(f"    trade (pre-registered top/bottom 5 by discovery t): long {fmt(longs)} | short "
          f"{fmt(shorts)}")
    print(f"      verification net {mean:+.3f} vol per trade (t {t:+.1f}, {n} days) | halves "
          f"{h[0][0]:+.3f} (t {h[0][1]:+.1f}) / {h[1][0]:+.3f} (t {h[1][1]:+.1f}) | cost "
          f"{cost(fam):.3f} per round trip")


def weekday(df: pd.DataFrame, fam: str) -> None:
    daily = df.groupby(["sym", "day"]).agg(y=("y", "sum"), wd=("wd", "first"), ts=("ts", "first"),
                                           a=("y", lambda v: v.abs().mean()))
    cut = daily["ts"].quantile(SPLIT)
    print(f"\n  -- {fam} · weekday (the day's summed y, UTC days), discovery | verification")
    for d in sorted(daily["wd"].unique()):
        cells = []
        for part in (daily["ts"] < cut, daily["ts"] >= cut):
            g = daily[part & (daily["wd"] == d)]
            mean, t, n = day_t(g["y"].to_numpy(), g.index.get_level_values("day").to_numpy())
            cells.append(f"{mean:+.3f} (t {t:+.1f}, n {n})")
        vol = daily[daily["wd"] == d]["a"].mean() / daily["a"].mean()
        print(f"    {DAYS[d]}  {cells[0]}  |  {cells[1]}  | vol {vol:.2f}x")
    if fam in ("crypto", "walks 24/7") or fam.startswith("deriv"):
        wk = daily["wd"] >= 5
        a, ta, _ = day_t(daily[wk]["y"].to_numpy(), daily[wk].index.get_level_values("day").to_numpy())
        b, tb, _ = day_t(daily[~wk]["y"].to_numpy(), daily[~wk].index.get_level_values("day").to_numpy())
        print(f"    weekend {a:+.3f} (t {ta:+.1f}) vs weekdays {b:+.3f} (t {tb:+.1f}) | weekend vol "
              f"{daily[wk]['a'].mean() / daily[~wk]['a'].mean():.2f}x weekdays")


def anova(df: pd.DataFrame, fam: str) -> None:
    """Is |y| the same in every weekday x hour bucket? One-way F on |y|."""
    a = df["y"].abs()
    g = df.groupby(["wd", "hr"])
    k, n = g.ngroups, len(df)
    grand = a.mean()
    between = (g.size() * (a.groupby([df["wd"], df["hr"]]).mean() - grand) ** 2).sum() / (k - 1)
    within = ((a - a.groupby([df["wd"], df["hr"]]).transform("mean")) ** 2).sum() / (n - k)
    print(f"    |y| across {k} buckets: F {between / within:.2f} (1.0 = no structure; df {k - 1}, {n - k})")


def main() -> None:
    only = os.environ.get("ONLY", "")
    for fam, syms in FAMILIES.items():
        if only and only not in fam:
            continue
        frames = [f for f in (frame(s, fam) for s in syms) if f is not None]
        if not frames:
            print(f"\n{fam}: no data", flush=True)
            continue
        df = pd.concat(frames, ignore_index=True)
        print(f"\n{'=' * 130}\n{fam.upper()}: {len(frames)} series, {len(df):,} hourly bars, "
              f"{pd.Timestamp(df['ts'].min(), unit='s'):%Y-%m-%d} to "
              f"{pd.Timestamp(df['ts'].max(), unit='s'):%Y-%m-%d}", flush=True)
        clocks = [("wd", "hr", "UTC")] + ([("wd_ny", "hr_ny", "New York")] if fam in NEW_YORK_TOO else [])
        for wd, hr, clock in clocks:
            describe(df, fam, wd, hr, clock)
            p = persistence(df, fam, wd, hr, clock)
            trade(fam, p, wd, hr)
            sys.stdout.flush()
        weekday(df, fam)
        anova(df, fam)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
