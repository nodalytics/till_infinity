"""Does production do worse in the 20-23 UTC rollover hours?

`fxtod.md` found that the one hour-of-day pattern that persists in FX is at 20-23 UTC, the New York
close and the broker's daily rollover, and that it is most likely quote artefacts: wide spreads and
stale prints, not order flow. This asks what that window does to production itself, from the
journal (read only):

  trades   every closed desk trade (`outcome` by `trading`): R multiple, hit rate and slippage
           (filled against wanted entry, in bps), by the UTC hour it was entered - close time less
           the hold
  hours    FX call outcomes by the UTC hour they resolved, with the trap and break shares, and
           the share landing in 21-22 UTC per timeframe
  calls    every resolved structure call (`outcome` by `structures`): how many land in the window,
           the outcome mix, how far price went against the call (adverse, in vol) and whether it
           resolved the way the call leaned (probability_up against the push)

20-23 UTC against every other hour, FX separately, with bootstrap intervals over days. Families
from the feed's name; Deriv is a market of its own (it has no rollover, so it is the comparison for
"is it the hour or the market").

Run on the lab: JOURNAL=$HOME/till_infinity/data/journal.db python research/harness/rollover.py
"""
from __future__ import annotations

import json
import os
import sqlite3

import numpy as np
import pandas as pd

JOURNAL = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
WINDOW = (20, 21, 22, 23)
DERIV = ("volatility", "boom", "crash", "jump", "step", "range", "dex", "drift")


def family(feed: str) -> str:
    f = feed.lower().replace("_", " ")
    if any(w in f for w in DERIV):
        return "deriv"
    if f.startswith(("xau", "xag", "xpt", "xpd")):
        return "metals"
    if f.startswith(("btc", "eth", "sol", "xrp", "ltc")):
        return "crypto"
    return "fx" if len(f.replace(" ", "")) == 6 else "other"


def load(kind: str, actor: str, fields: tuple[str, ...]) -> pd.DataFrame:
    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    rows = []
    for t, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE kind=? AND actor=?", (kind, actor)
    ):
        c = json.loads(ctx)
        rows.append({"time": t, **{k: c.get(k) for k in fields}})
    df = pd.DataFrame(rows)
    df["feed"] = df["feed"].astype(str)
    df["family"] = df["feed"].map(family)
    return df


def boot(values: np.ndarray, days: np.ndarray, n: int = 2000, seed: int = 0):
    """Mean and a 95% interval, resampling whole days."""
    ok = np.isfinite(values)
    values, days = values[ok], days[ok]
    if len(values) < 5:
        return float("nan"), (float("nan"), float("nan"))
    uniq = np.unique(days)
    by = {d: values[days == d] for d in uniq}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(n):
        pick = rng.choice(uniq, len(uniq))
        means.append(np.concatenate([by[d] for d in pick]).mean())
    return float(values.mean()), tuple(np.quantile(means, [0.025, 0.975]))


def fmt(m, ci):
    return f"{m:+.3f} [{ci[0]:+.3f}, {ci[1]:+.3f}]"


def trades() -> None:
    df = load("outcome", "trading", ("feed", "strategy", "r_multiple", "seconds", "entry_wanted",
                                     "entry_filled", "slippage", "side"))
    df = df[pd.to_numeric(df["r_multiple"], errors="coerce").notna()].copy()
    df["r"] = df["r_multiple"].astype(float)
    df["entered"] = df["time"] - pd.to_numeric(df["seconds"], errors="coerce").fillna(0)
    df["hour"] = pd.to_datetime(df["entered"], unit="s").dt.hour
    df["day"] = (df["entered"] // 86_400).astype(int)
    wanted = pd.to_numeric(df["entry_wanted"], errors="coerce")
    filled = pd.to_numeric(df["entry_filled"], errors="coerce")
    df["slip_bps"] = ((filled - wanted).abs() / wanted * 1e4).where(wanted > 0)
    df["window"] = df["hour"].isin(WINDOW)
    span = pd.to_datetime([df["entered"].min(), df["entered"].max()], unit="s")
    print(f"TRADES: {len(df)} closed desk trades with an R, {span[0]:%Y-%m-%d} to {span[1]:%Y-%m-%d}")
    for fam in ("all", "fx", "deriv", "metals", "crypto"):
        g = df if fam == "all" else df[df["family"] == fam]
        if len(g) < 5:
            continue
        print(f"\n  {fam}: n={len(g)}, in 20-23 UTC {int(g['window'].sum())} ({g['window'].mean():.0%})")
        for label, part in (("20-23 UTC", g[g["window"]]), ("other hours", g[~g["window"]])):
            if len(part) < 3:
                print(f"    {label:12s} n={len(part):4d} (too few)")
                continue
            m, ci = boot(part["r"].to_numpy(), part["day"].to_numpy())
            sm = part["slip_bps"].median()
            print(f"    {label:12s} n={len(part):4d} mean R {fmt(m, ci)} | median R {part['r'].median():+.2f}"
                  f" | hit {np.mean(part['r'] > 0):.0%} | median slippage {sm:.2f} bps")
    print("\n  by strategy, fx only (n in window / n)")
    fx = df[df["family"] == "fx"]
    for s, g in fx.groupby("strategy"):
        w = g[g["window"]]
        print(f"    {str(s):16s} {len(w):3d} / {len(g):3d} | R in window {w['r'].mean() if len(w) else float('nan'):+.2f}"
              f" | R otherwise {g[~g['window']]['r'].mean():+.2f}")
    print("\n  every hour, all trades: n / mean R")
    print("   " + " ".join(f"{h:02d}:{int((df['hour'] == h).sum()):>3d}/{df.loc[df['hour'] == h, 'r'].mean():+.2f}"
                           if (df["hour"] == h).any() else f"{h:02d}:  -" for h in range(24)))


def calls() -> None:
    df = load("outcome", "structures", ("feed", "outcome", "push_vol", "adverse_vol", "probability_up",
                                        "actionable", "interval"))
    df["hour"] = pd.to_datetime(df["time"], unit="s").dt.hour
    df["day"] = (df["time"] // 86_400).astype(int)
    df["window"] = df["hour"].isin(WINDOW)
    push = pd.to_numeric(df["push_vol"], errors="coerce")
    pu = pd.to_numeric(df["probability_up"], errors="coerce")
    lean = np.sign(pu - 0.5)
    df["right"] = np.where((lean != 0) & (push != 0) & push.notna() & pu.notna(),
                           (np.sign(push) == lean).astype(float), np.nan)
    df["adverse"] = pd.to_numeric(df["adverse_vol"], errors="coerce").abs()
    print(f"\n\nCALLS: {len(df):,} resolved structure calls (outcomes stamped when resolved)")
    for fam in ("fx", "deriv", "metals", "crypto"):
        g = df[df["family"] == fam]
        if len(g) < 50:
            continue
        print(f"\n  {fam}: n={len(g):,}, resolved in 20-23 UTC {g['window'].mean():.1%} (4 of 24 hours = 16.7%)")
        for label, part in (("20-23 UTC", g[g["window"]]), ("other hours", g[~g["window"]])):
            r, rci = boot(part["right"].to_numpy(), part["day"].to_numpy(), n=500)
            a, aci = boot(part["adverse"].to_numpy(), part["day"].to_numpy(), n=500)
            mix = part["outcome"].astype(str).value_counts(normalize=True).head(4)
            mixs = ", ".join(f"{k} {v:.0%}" for k, v in mix.items())
            print(f"    {label:12s} n={len(part):7,} | resolved as leaned {fmt(r, rci)} | adverse vol "
                  f"{fmt(a, aci)} | {mixs}")


def hours() -> None:
    """FX calls by the hour they resolved: the share of calls, and the trap and break shares.
    A spread spike at the rollover prints a wick through the level and back, which the label
    reads as a trap - so a spike there shows as a bulge in the call count and the trap share."""
    df = load("outcome", "structures", ("feed", "outcome", "interval"))
    df = df[df["family"] == "fx"].copy()
    df["hour"] = pd.to_datetime(df["time"], unit="s").dt.hour
    df["weekday"] = pd.to_datetime(df["time"], unit="s").dt.weekday
    print("\n\nFX CALLS BY UTC HOUR RESOLVED: share of calls | trap | break | reject (weekdays only)")
    wk = df[df["weekday"] < 5]
    for h in range(24):
        g = wk[wk["hour"] == h]
        o = g["outcome"].astype(str)
        print(f"  {h:02d}  {len(g) / len(wk):6.1%}  n={len(g):6,}  trap {np.mean(o == 'trap'):5.1%}"
              f"  break {np.mean(o == 'break'):5.1%}  reject {np.mean(o == 'reject'):5.1%}")
    print("\n  by interval, share resolved in 21-22 UTC:")
    for iv, g in wk.groupby("interval"):
        if len(g) > 500:
            print(f"    {iv:6s} n={len(g):6,}  {g['hour'].isin((21, 22)).mean():.1%} (2 of 24 hours = 8.3%)")


if __name__ == "__main__":
    trades()
    calls()
    hours()
