"""Is the spike switch firing on the session clock, and would a session-aware percentile do better?

Production's risk switch halves size when `tr_percentile` - the 14-bar EWMA of true range, ranked
in the instrument's own last 1,500 bars - is at or above 0.8 (`scaling.by_spike`). The state
manifold (`research/docs/manifold.md`) found the hour of day is the largest structure in these
markets' states, and the percentile has no idea what hour it is: a London open ranked against a
window that holds the Asian night will look like a spike every day.

Three switches, all parameter-free, all halving at >= 0.8:
  prod       the EWMA of true range, percentile in its last 1,500 bars (what production runs)
  samehour   the same EWMA, percentile among its own readings at the same UTC hour over the last
             20 days - only like is compared with like
  deseason   the EWMA over its 20-day mean at the same hour, then percentile in the last 1,500 bars

For each: how much the switch fires by hour (the clock), how well it anticipates a bar beyond 4x
the baseline |return| in the next H bars, and what halving does to two toy positions that know
nothing about it - always long, and the sign of the last 20 bars - held H bars, non-overlapping,
both unstopped and with a 1U stop taken by the wick. U is sqrt(H) times either the 500-bar baseline
|return| (UNIT=base, as in crash-timing.md) or the entry-time EWMA of true range (UNIT=live, the unit
production sets its stops in). Reported on the last
40% of each series by time (nothing is fit; the split keeps this comparable with crash-timing.md),
both halves, for FX, metals, crypto and the random walks, where there is no clock.

Run on the lab:
  INTERVAL=15m SEQLAB=$HOME/till_infinity/data/seqlab python research/harness/sessionswitch.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import FAMILIES

INTERVAL = os.environ.get("INTERVAL", "15m")
UNIT = os.environ.get("UNIT", "base")
H = {"3m": 10, "15m": 8, "1h": 5}[INTERVAL]
PER_HOUR = {"3m": 20, "15m": 4, "1h": 1}[INTERVAL]
WINDOW = 1_500
DAYS = 20
ABOVE, FLOOR = 0.8, 0.5
RULES = ("prod", "samehour", "deseason")
RNG = np.random.default_rng(7)


def series(sym):
    df = spikerisk.load(None, sym, "SEQLAB", INTERVAL)
    o, h, l, c = (np.log(df[k].to_numpy()) for k in ("open", "high", "low", "close"))
    prev = np.r_[np.nan, c[:-1]]
    tr = np.nanmax(np.column_stack([h - l, np.abs(h - prev), np.abs(l - prev)]), axis=1)
    ew = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean()
    hour = pd.to_datetime(df.ts.to_numpy(), unit="s").hour.to_numpy()
    n = len(c)
    same = DAYS * PER_HOUR  # readings of one hour in 20 days
    pct = {"prod": ew.rolling(WINDOW, min_periods=300).rank(pct=True).to_numpy()}
    sh, seas = np.full(n, np.nan), np.full(n, np.nan)
    for hr in range(24):
        idx = np.flatnonzero(hour == hr)
        if len(idx) < 20:
            continue
        g = ew.iloc[idx].reset_index(drop=True)
        sh[idx] = g.rolling(same, min_periods=20).rank(pct=True).to_numpy()
        seas[idx] = g.shift(1).rolling(same, min_periods=20).mean().to_numpy()  # before this reading
    pct["samehour"] = sh
    pct["deseason"] = pd.Series(ew.to_numpy() / seas).rolling(WINDOW, min_periods=300).rank(pct=True).to_numpy()

    r = np.diff(c, prepend=np.nan)
    base = pd.Series(np.abs(r)).rolling(500, min_periods=250).mean().to_numpy()
    big = np.zeros(n)
    for k in range(1, H + 1):
        big = np.maximum(big, np.r_[np.abs(r[k:]), np.full(k, np.nan)] > 4 * base)
    # Two units. `base` is a 500-bar mean |return| that knows nothing of the session; `live` is the
    # entry-time EWMA of true range, the unit production sets its stops in (`strategy.py`,
    # `sizing.price_distance`), so a position opened at a session open is already smaller.
    unit = (ew.to_numpy() if UNIT == "live" else base) * np.sqrt(H)
    t = np.arange(n)
    ok = (t + H < n) & np.isfinite(base) & np.all([np.isfinite(pct[k]) for k in RULES], axis=0)
    ok[:WINDOW + DAYS * 24 * PER_HOUR // 2] = False  # every rule warmed up
    end = np.r_[c[H:] - c[:-H], np.full(H, np.nan)] / unit
    mom = np.sign(c - np.r_[np.full(20, np.nan), c[:-20]])
    # the path relative to the entry close, for the wick stop
    rel = lambda a: np.column_stack([np.r_[a[k:], np.full(k, np.nan)] - c for k in range(1, H + 1)]) / unit[:, None]
    return dict(ok=ok, test=t >= 0.6 * n, half=t >= 0.8 * n, slot=(t % H) == 0, hour=hour, big=big,
                end=end, mom=mom, o=rel(o), h=rel(h), l=rel(l), **{f"p_{k}": pct[k] for k in RULES})


def stopped(sgn, d):
    """A 1U resting stop, filled at the level or at the open on a gap through it; else exit at H."""
    o, h, l = (d[k] * sgn[:, None] for k in ("o", "h", "l"))
    lo = np.where(sgn[:, None] > 0, l, -h)  # the adverse extreme of the bar, for either side
    out = d["end"] * sgn
    done = np.zeros(len(sgn), bool)
    for k in range(H):
        gap = ~done & (o[:, k] <= -1)
        hit = ~done & ~gap & (lo[:, k] <= -1)
        out = np.where(gap, o[:, k], np.where(hit, -1.0, out))
        done |= gap | hit
    return out


def tail(x):
    x = np.sort(x[np.isfinite(x)])
    k = max(1, int(0.01 * len(x)))
    return x.mean(), x[:k].mean(), x[0]


def main():
    rows = {}
    for fam, syms in FAMILIES.items():
        parts = []
        for s in syms:
            try:
                d = series(s)
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {s}: {str(exc)[:70]}")
                continue
            m = d["ok"] & d["test"]
            parts.append({k: v[m] for k, v in d.items()})
        rows[fam] = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}

    print(f"\n{'=' * 110}\nSESSION SWITCH {INTERVAL}, unit {UNIT}, H={H} bars, halve at >= {ABOVE}; test block (last 40% of each series)")
    for fam, d in rows.items():
        print(f"\n  {fam}: {len(d['big']):,} bars, P(4x bar within H) {d['big'].mean():.1%}")
        for rule in RULES:
            p = d[f"p_{rule}"]
            on = p >= ABOVE
            by_hr = np.array([on[d["hour"] == hr].mean() if (d["hour"] == hr).sum() > 50 else np.nan for hr in range(24)])
            # share of the switch's variance that is the hour: between-hour variance of the fire rate
            eta = np.nansum([(d["hour"] == hr).mean() * (by_hr[hr] - on.mean()) ** 2 for hr in range(24)]) / max(on.var(), 1e-12)
            lift = d["big"][on].mean() / max(d["big"][~on].mean(), 1e-9)
            auc = roc_auc_score(d["big"], p)
            print(f"    {rule:<9} fires {on.mean():5.1%} | by hour {np.nanmin(by_hr):5.1%} to {np.nanmax(by_hr):5.1%}, "
                  f"hour explains {eta:5.1%} of it | P(4x) on {d['big'][on].mean():5.1%} off {d['big'][~on].mean():5.1%} "
                  f"lift {lift:4.2f}x AUC {auc:.3f}")
        k = d["slot"]
        print(f"    {'position':<9} {'rule':<9} {'size':>5} | unstopped mean / ES1 / worst | 1U wick stop mean / ES1 | ES1 gain per unit of size given up (unstopped, stopped), halves")
        for pos, sgn in (("long", np.ones(len(d["big"]))), ("momentum", d["mom"])):
            sg = np.nan_to_num(sgn[k])
            sub = {kk: v[k] for kk, v in d.items()}
            raw, stop = sg * sub["end"], stopped(sg, sub)
            live = sg != 0
            base_u, base_s = tail(raw[live]), tail(stop[live])
            print(f"    {pos:<9} {'flat':<9} {1.0:5.2f} | {base_u[0]:+.3f} / {base_u[1]:+.2f} / {base_u[2]:+.1f} | "
                  f"{base_s[0]:+.3f} / {base_s[1]:+.2f}")
            # placebo: the production switch's own sizes dealt to random positions - same fire rate, no information
            ref = np.where(sub["p_prod"][live] >= ABOVE, FLOOR, 1.0)
            pu, ps = [], []
            for _ in range(50):
                sz = RNG.permutation(ref)
                g = 1 - sz.mean()
                pu.append((tail(sz * raw[live])[1] - base_u[1]) / g)
                ps.append((tail(sz * stop[live])[1] - base_s[1]) / g)
            print(f"    {pos:<9} {'placebo':<9} {ref.mean():5.2f} | random firing at the same rate: ES1 gain per unit "
                  f"{np.mean(pu):+.2f} (95th pct {np.quantile(pu, 0.95):+.2f}), stopped {np.mean(ps):+.2f} "
                  f"({np.quantile(ps, 0.95):+.2f})")
            for rule in RULES:
                size = np.where(sub[f"p_{rule}"] >= ABOVE, FLOOR, 1.0)
                u, s_ = tail((size * raw)[live]), tail((size * stop)[live])
                give = 1 - size[live].mean()
                halves = []
                for hm in (~sub["half"][live], sub["half"][live]):
                    fu = tail(raw[live][hm])[1]
                    ru = tail((size * raw)[live][hm])[1]
                    halves.append(f"{(ru - fu) / max(1 - size[live][hm].mean(), 1e-9):+.2f}")
                print(f"    {pos:<9} {rule:<9} {size[live].mean():5.2f} | {u[0]:+.3f} / {u[1]:+.2f} / {u[2]:+.1f} | "
                      f"{s_[0]:+.3f} / {s_[1]:+.2f} | {(u[1] - base_u[1]) / give:+.2f}, {(s_[1] - base_s[1]) / give:+.2f}  "
                      f"(unstopped halves {' / '.join(halves)})")


if __name__ == "__main__":
    main()
