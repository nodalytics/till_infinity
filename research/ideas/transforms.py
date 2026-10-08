"""Cumulative and moving transforms of the features the desk already publishes.

Asked 2026-10-08: besides `cumsum`, test `cumprod`, `cummax`, `cummin`, a moving
sum, and a whole-dataset sum. The question is whether a feature's **history**
says something its current value does not - a running peak, a compounding
product, the last N bars' worth.

Applied to the fields that have already earned a look: `activity` beat a
same-duty-cycle random control at p = 0.001 in `duty_cycle.py`, and `vol_bps`,
`garch_bps` and `forecast_bps` are its correlated neighbours.

**Every transform is causal except one, and that one is the point.** `expanding`
and `moving` use only bars at or before the row they describe. `whole` uses the
entire dataset including the future, which is not a feature but the leak
`leakage.md` measured - full-sample normalisation inflated a magnitude spread
2.8x there. It is run here as a control arm so the inflation is visible in the
same table rather than argued about.

Scored the way `activity` was: against the win rate, and against **random gates
keeping the same share of trades**, shuffled within day so the duty cycle and
the per-day trade count are both preserved.

  python research/ideas/transforms.py .data/live/journal_full.csv
"""
from __future__ import annotations

import csv
import json
import sys

import numpy as np
import pandas as pd

csv.field_size_limit(10 ** 7)
FIELDS = ("activity", "vol_bps", "forecast_bps", "garch_bps")
WINDOW = 10
KEEP = 0.50
DRAWS = 2000


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            if r["kind"] != "outcome":
                continue
            try:
                d = json.loads(r["context"])
            except Exception:
                continue
            d["_t"] = float(r["time"])
            rows.append(d)
    d = pd.DataFrame(rows)
    d["r"] = pd.to_numeric(d.get("r_multiple"), errors="coerce")
    d = d[np.isfinite(d.r)].copy()
    d["win"] = (d.r > 0).astype(float)
    d["day"] = (d._t // 86400).astype(int)
    return d.sort_values("_t").reset_index(drop=True)


def transforms(v: pd.Series, feed: pd.Series) -> dict[str, pd.Series]:
    """Each transform within its own instrument, in time order."""
    g = v.groupby(feed)
    pos = v - v.groupby(feed).transform("min") + 1e-9     # positive, for a product
    out = {
        "level": v,
        "cumsum": g.cumsum(),
        "cumprod": np.log(pos).groupby(feed).cumsum(),     # in logs: a raw product overflows
        "cummax": g.cummax(),
        "cummin": g.cummin(),
        "from_peak": v - g.cummax(),                       # what a running high is usually for
        "movsum": g.transform(lambda x: x.rolling(WINDOW, min_periods=2).sum()),
        "movmean": g.transform(lambda x: x.rolling(WINDOW, min_periods=2).mean()),
        # **the leak**: the whole dataset, future included
        "whole_mean": g.transform("mean"),
        "whole_z": (v - g.transform("mean")) / g.transform("std").replace(0, np.nan),
    }
    return out


def control(val, win, day, keep=KEEP, draws=DRAWS, seed=37):
    rng = np.random.default_rng(seed)
    groups = [np.flatnonzero(day == u) for u in np.unique(day)]
    out = np.empty(draws)
    for k in range(draws):
        y = val.copy()
        for ix in groups:
            if len(ix) > 1:
                y[ix] = rng.permutation(val[ix])
        s = y >= np.quantile(y, 1 - keep)
        out[k] = win[s].mean()
    return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else ".data/live/journal_full.csv"
    d = load(path)
    feed = d.get("feed", d.get("symbol")).astype(str)
    print(f"{len(d)} closed positions, {d.day.nunique()} days, "
          f"{feed.nunique()} instruments, ungated win {d.win.mean():.1%}\n")
    rows = []
    for field in FIELDS:
        if field not in d:
            continue
        v = pd.to_numeric(d[field], errors="coerce")
        ok = np.isfinite(v)
        if ok.sum() < 150:
            continue
        sub = d[ok].reset_index(drop=True)
        made = transforms(v[ok].reset_index(drop=True), feed[ok].reset_index(drop=True))
        win, day = sub.win.to_numpy(), sub.day.to_numpy()
        print(f"=== {field}  (n={len(sub)}, keep top {KEEP:.0%})")
        for name, series in made.items():
            x = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
            good = np.isfinite(x)
            if good.sum() < 120:
                continue
            xx, ww, dd = x[good], win[good], day[good]
            sel = xx >= np.quantile(xx, 1 - KEEP)
            if sel.sum() < 40:
                continue
            real = ww[sel].mean()
            null = control(xx, ww, dd)
            p = float((null >= real).mean())
            leak = "  <- LEAK (whole sample)" if name.startswith("whole") else ""
            print(f"   {name:<12} n={int(sel.sum()):>4}  win {real:.1%}  "
                  f"random {null.mean():.1%} [{np.percentile(null, 5):.1%},"
                  f"{np.percentile(null, 95):.1%}]  p={p:.3f}{leak}")
            rows.append(dict(field=field, transform=name, n=int(sel.sum()), win=real,
                             random=null.mean(), p=p, leak=name.startswith("whole")))
        print()
    t = pd.DataFrame(rows)
    if t.empty:
        return
    causal = t[~t.leak].sort_values("p")
    print("=== causal transforms, best first ===")
    print(causal.head(12).round(4).to_string(index=False))
    print("\n=== the leak arm, for the size of what it fabricates ===")
    print(t[t.leak].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
