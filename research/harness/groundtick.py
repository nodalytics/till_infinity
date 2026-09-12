"""Does the discretely-monitored barrier law hold on a real feed at tick resolution?

`research/grounding.md` section five validated `till_infinity/trading/barriers.py`
on **one-minute closes**, where `B = 0.5826` is the shift
`research/deriving.md` measured. That is the regime the desk does not trade in.
`barriers.py`'s own headline correction is that a real stop is hit on a tick, so
the shift falls as `B / sqrt(n)` at `n` ticks a bar, and the module says plainly
that on real markets the whole construction "is a better prior than the
continuous form and is not validated".

The bar leg could not test it, because a bar-sampled replay cannot see inside a
bar. `research/harness/feed.py` now can: 200,000 ticks a symbol with millisecond
stamps across the broker's whole book.

## The reformulation that removes the bar entirely

`SHIFT` is 0.5826 of **one monitoring interval's** sigma, whatever that interval
is. So rather than convert between bars and ticks and argue about the rate, this
harness works in units of **one tick's** sigma throughout: barriers at `a` and
`b` tick-sigmas, monitored every tick, prediction

    P(target first) = (b + 0.5826) / (a + b + 2 * 0.5826)
    E[ticks]        = (a + 0.5826) * (b + 0.5826)

which is `barriers.probability(a, b, ticks_per_bar=1)` with the distances
expressed at the monitoring scale. It is the identical formula at a different
scale, and there is no conversion left to get wrong. A desk stop of 1.3 bar-sigmas
on a feed quoting 400 ticks a minute is about 26 tick-sigmas, so the geometries
scanned cover 5 to 20.

## What this can find that the bar leg could not

Three things live only at tick resolution and all three would break the law:

* the **bid-ask bounce**, which makes the mid's increments negatively
  autocorrelated and would make a barrier harder to reach than the law says;
* the **quote grid**, which `research/rebuilding.md` measured at 13.2 to 3,674
  lattice points per per-tick sigma across the Volatility family alone, and
  `research/twins.md` quarantined a feed over;
* the **repeated quote**, which `research/rebuilding.md` established is deleted
  before we ever see it, on twelve feeds of twelve.

## The controls

* **`Volatility 75 Index` and `Step Index` are the positive controls.**
  `research/deriving.md` proves the first geometric Brownian motion at a
  published sigma and the second a fair coin on a 0.1 lattice to
  `p = 0.499734 +- 0.000220`. The law must hold there, and Step Index is the
  sharper of the two because a one-unit lattice walk has **no overshoot at all**
  when the barrier sits on a lattice point - so its shift should be smaller than
  0.5826, and how much smaller is a measurement rather than a fit.
* **`Boom 500 Index` is the negative control**, and it must fail: section five
  has the closed form wrong by 55.7 standard errors on the Boom family at bar
  resolution.
* **The mid against the bid and the ask.** The law is about a price process; a
  stop fills at the bid. Both are replayed so the difference is measured rather
  than assumed.

## What would count as failure

Written before any number was read.

1. **The harness is void** if the tick count returned is under 20,000 for any
   symbol scored, or if the median inter-tick gap is so large that 200,000 ticks
   do not cover a session.
2. **The machinery is broken** if the two positive controls do not match the law
   within two standard errors at the symmetric geometries, where the answer is
   0.5 by symmetry whatever the shift is.
3. **The test has no power** if `Boom 500 Index` matches the law.
4. **The run is void** if a measured probability lands on the predicted value to
   four decimals, or if any symmetric cell returns exactly 0.5000 on a feed whose
   asymmetric cells miss.
5. **No claim about the real feeds** is made unless the same statistic on the
   positive controls is inside its interval, because a law that fails where it is
   provably true cannot be read where it is not.
6. **The fitted shift is not a shift** if inverting each geometry for the `B`
   that reproduces its measured probability does not return roughly the same
   value across geometries. A boundary condition cannot know how far away the
   barrier is - this is `research/quantising.md` section one's flatness test,
   which is the thing that distinguishes a boundary condition from a fudge.
"""

from __future__ import annotations

import json
import math
import os

import numpy as np

import feed
import groundlib as G

OUT = os.environ.get("OUT", os.path.join(G.LOGS, "groundtick.json"))
NTICK = int(os.environ.get("NTICK", "200000"))
HOURS = float(os.environ.get("HOURS", "72"))
#: Geometries in units of ONE TICK's sigma. A desk stop of about 1.3 bar-sigmas
#: on a feed quoting a few hundred ticks a minute is 20-30 of these.
GEOMS = ((5.0, 5.0), (10.0, 10.0), (20.0, 20.0), (15.0, 5.0), (5.0, 15.0), (6.8, 5.0))
CONTROL = ("Volatility 75 Index", "Step Index")
NEGATIVE = ("Boom 500 Index",)
REAL = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "BTCUSD", "XAGUSD")


def closed_form(a: float, b: float, shift: float = G.SHIFT) -> tuple[float, float]:
    return (b + shift) / (a + b + 2.0 * shift), (a + shift) * (b + shift)


def invert_shift(a: float, b: float, p: float) -> float:
    """The `B` that would reproduce a measured `p` at this geometry.

    `p = (b+B)/(a+b+2B)` solves to `B = (p*(a+b) - b) / (1 - 2p)`, which is the
    flatness test of `research/quantising.md` section one run backwards: a
    boundary condition cannot know `a`, so a `B` that drifts across geometries is
    a fitted constant and not a wall.
    """
    # **Degenerate when `a == b`**, and not slightly: at a symmetric geometry the
    # expression collapses to `-a` for ANY measured `p`, so the column returned
    # -5, -10 and -20 on the symmetric rows of the first run and carried no data
    # at all. The flatness test is only meaningful where the two barriers differ.
    if abs(a - b) < 1e-9:
        return float("nan")
    den = 1.0 - 2.0 * p
    return float("nan") if abs(den) < 1e-6 else (p * (a + b) - b) / den


def variance_ratio(x: np.ndarray, n: int) -> float:
    """`Var(x_{t+n} - x_t) / (n * Var(dx))`. One for a random walk.

    This is the whole of the duration story and it costs one line. A path whose
    increments are negatively autocorrelated - the bid-ask bounce - travels less
    far per tick than its per-tick variance says, so it takes **longer** to reach
    a barrier placed in units of that variance. The predicted duration ratio is
    therefore `1 / VR`, which is a derived correction with no free parameter, and
    it has a sign: a feed with *positive* tick autocorrelation must resolve
    **faster** than the law says, not slower.
    """
    d = np.diff(x)
    if d.size < 10 * n:
        return float("nan")
    m = (d.size // n) * n
    blocks = d[:m].reshape(-1, n).sum(axis=1)
    v1 = float(np.var(d))
    return float(np.var(blocks) / (n * v1)) if v1 > 0 else float("nan")


def trials(x: np.ndarray, a: float, b: float, sig: float, maxstep: int = 400_000):
    """Non-overlapping first-passage trials on the tick path, in tick-sigma units."""
    n = x.size
    i, ups, durs, drop = 1, [], [], 0
    while i < n - 2:
        hi, lo = x[i] + a * sig, x[i] - b * sig
        j = min(i + maxstep, n)
        seg = x[i:j]
        u = np.flatnonzero(seg >= hi)
        d = np.flatnonzero(seg <= lo)
        tu = u[0] if u.size else 10**9
        td = d[0] if d.size else 10**9
        if tu == 10**9 and td == 10**9:
            drop += 1
            i = j
            continue
        ups.append(1 if tu < td else 0)
        durs.append(int(min(tu, td)))
        i += int(min(tu, td))
    return np.asarray(ups), np.asarray(durs), drop


def one(symbol: str, group: str) -> dict | None:
    try:
        rows = feed.ticks(symbol, NTICK, hours_back=HOURS)
    except Exception as exc:  # a symbol the terminal will not serve is not a result
        print(f"  {symbol:24s} unavailable: {type(exc).__name__}")
        return None
    if len(rows) < 20000:
        print(f"  {symbol:24s} only {len(rows)} ticks - condition 1, not scored")
        return None
    t = np.array([r["time"] for r in rows])
    mid = np.array([r["mid"] for r in rows])
    bid = np.array([r["bid"] for r in rows])
    ask = np.array([r["ask"] for r in rows])
    gaps = np.diff(t)
    gaps = gaps[gaps > 0]
    d = np.diff(mid)
    sig = float(np.std(d))
    nz = np.abs(d[d != 0])
    grid = float(np.median(nz)) if nz.size else float("nan")
    out = {
        "symbol": symbol,
        "group": group,
        "n_ticks": len(rows),
        "median_gap_ms": float(np.median(gaps) * 1000.0),
        "ticks_per_min": float(60.0 / np.median(gaps)) if np.median(gaps) > 0 else float("nan"),
        "sigma_tick": sig,
        "grid_per_sigma": sig / grid if grid and math.isfinite(grid) and grid > 0 else float("nan"),
        "mean_spread_sigma": float(np.mean(ask - bid) / sig) if sig > 0 else float("nan"),
        "frac_zero": float(np.mean(d == 0)),
        "acf1": float(np.corrcoef(d[:-1], d[1:])[0, 1]) if d.size > 10 else float("nan"),
        "vr": {n: variance_ratio(mid, n) for n in (2, 5, 10, 30, 100, 300, 1000)},
        "cells": {},
    }
    for a, b in GEOMS:
        up, dur, drop = trials(mid, a, b, sig)
        if up.size < 60:
            continue
        p = float(up.mean())
        se = math.sqrt(max(p * (1 - p), 1e-9) / up.size)
        pa, ea = closed_form(a, b)
        # The variance ratio is evaluated at the horizon this geometry actually
        # runs for, because a bounce that dies after two ticks does not slow a
        # four-hundred-tick trade. `ea` is the law's own duration, so nothing
        # about the measured outcome enters the prediction.
        vr = variance_ratio(mid, max(2, int(round(ea))))
        out["cells"][f"{a:g}:{b:g}"] = {
            "vr_at_horizon": vr,
            "dur_ratio_predicted": (1.0 / vr) if vr and math.isfinite(vr) and vr > 0 else float("nan"),
            "n": int(up.size),
            "p_truth": p,
            "se": se,
            "z": (p - pa) / se if se > 0 else float("nan"),
            "p_closed": pa,
            "dur_truth": float(dur.mean()),
            "dur_closed": ea,
            "dur_ratio": float(dur.mean()) / ea,
            "fitted_shift": invert_shift(a, b, p),
            "drop": drop,
        }
    return out


def main() -> None:
    print("=" * 104)
    print("groundtick.py - the discretely-monitored barrier law at tick resolution")
    print("=" * 104)
    if not feed.healthy():
        print("terminal not answering - nothing run, rather than an empty table.")
        return
    res = {"ntick": NTICK, "hours": HOURS, "geoms": list(GEOMS)}
    rows = []
    for group, names in (("control", CONTROL), ("negative", NEGATIVE), ("real", REAL)):
        print(f"\n--- {group} ---")
        for s in names:
            r = one(s, group)
            if r:
                rows.append(r)
                print(
                    f"  {s:24s} {r['n_ticks']:7d} ticks, gap {r['median_gap_ms']:7.0f}ms, "
                    f"{r['ticks_per_min']:7.1f}/min, sigma {r['sigma_tick']:.6g}, "
                    f"grid/sigma {r['grid_per_sigma']:7.2f}, spread {r['mean_spread_sigma']:6.2f} "
                    f"sigma, zero {100 * r['frac_zero']:5.2f}%, acf1 {r['acf1']:+.3f}"
                )
    print("\n=== P(target first): measured against the law, in tick-sigma units ===\n")
    print(
        f"  {'symbol':22s} {'geom':>8s} {'n':>6s} {'measured':>9s} {'se':>7s} "
        f"{'closed':>8s} {'z':>7s} | {'ticks':>8s} {'law':>8s} {'ratio':>6s} {'VR':>6s} "
        f"{'1/VR':>6s} {'fitted B':>9s}"
    )
    for r in rows:
        for k, c in r["cells"].items():
            print(
                f"  {r['symbol']:22s} {k:>8s} {c['n']:6d} {c['p_truth']:9.4f} {c['se']:7.4f} "
                f"{c['p_closed']:8.4f} {c['z']:+7.2f} | {c['dur_truth']:8.1f} "
                f"{c['dur_closed']:8.1f} {c['dur_ratio']:6.3f} {c['vr_at_horizon']:6.3f} "
                f"{c['dur_ratio_predicted']:6.3f} {c['fitted_shift']:9.3f}"
            )
    print("\n=== pooled by group ===\n")
    print(
        f"  {'group':10s} {'geom':>8s} {'syms':>5s} {'trials':>8s} {'mean z':>8s} "
        f"{'|z|>2':>6s} {'dur ratio':>10s} {'1/VR pred':>10s} {'resid':>7s} {'fitted B':>9s}"
    )
    pooled = {}
    for group in ("control", "negative", "real"):
        sel = [r for r in rows if r["group"] == group]
        for k in (f"{a:g}:{b:g}" for a, b in GEOMS):
            cs = [r["cells"][k] for r in sel if k in r["cells"]]
            if not cs:
                continue
            z = np.array([c["z"] for c in cs])
            dr = np.array([c["dur_ratio"] for c in cs])
            pr = np.array([c["dur_ratio_predicted"] for c in cs])
            fb = np.array([c["fitted_shift"] for c in cs])
            fb = fb[np.isfinite(fb)]
            pooled[f"{group}|{k}"] = {
                "syms": len(cs),
                "trials": int(sum(c["n"] for c in cs)),
                "mean_z": float(z.mean()),
                "n_big": int((np.abs(z) > 2).sum()),
                "dur_ratio": float(dr.mean()),
                "dur_ratio_sd": float(dr.std(ddof=1)) if dr.size > 1 else 0.0,
                "dur_ratio_predicted": float(np.nanmean(pr)),
                "resid": float(np.nanmean(dr - pr)),
                "fitted_shift": float(fb.mean()) if fb.size else float("nan"),
            }
            print(
                f"  {group:10s} {k:>8s} {len(cs):5d} {int(sum(c['n'] for c in cs)):8d} "
                f"{z.mean():8.2f} {int((np.abs(z) > 2).sum()):3d}/{len(cs):<2d} "
                f"{dr.mean():10.3f} {np.nanmean(pr):10.3f} {np.nanmean(dr - pr):+7.3f} "
                f"{(fb.mean() if fb.size else float('nan')):9.3f}"
            )
    res["feeds"] = rows
    res["pooled"] = pooled
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(res, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
