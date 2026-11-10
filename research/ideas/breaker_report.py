"""Every table in `breaker-blocks.md`, from the CSVs `breaker_blocks.py` writes.

    ./.secrets/lab.sh run research/ideas/breaker_report.py
    OUT=.data/breaker uv run python research/ideas/breaker_report.py   # after a fetch

Reads `$OUT/trades.csv.gz` (real trades), `$OUT/cells.csv` (every arm and every
walk series summarised) and `$OUT/zones.csv` (firing rates), and prints the
report in the order the write-up uses:

1. **the leak check** - what the walk arms read, which must be at or below zero
   and at or below `1/(1+N)`;
2. **the headline** - `P(>= 2R)` for the real breaker against the arithmetic
   rate and against the hardest walk arm, then mean R with a **day-block**
   confidence interval, because trades cluster in days and an ordinary standard
   error is far too narrow;
3. **the arms side by side**, the refuted fade among them. If the fade also
   beats its null the finding belongs to the old claim;
4. **per instrument**, never only pooled - a pooled median here once agreed
   with a claim every subgroup refuted;
5. the **non-overlapping** subsample, since `HOLD` and `EXPIRE` overlap by
   construction and overlap inflates a permutation null;
6. the **split halves**, reported as a gating condition rather than a verdict;
7. **Benjamini-Hochberg** over every (instrument, interval) cell.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(os.environ.get("OUT", ".data/breaker"))
DRAWS = int(os.environ.get("DRAWS", "2000"))
TARGET = float(os.environ.get("TARGET", "2"))
SEED = 11
WALK_ARMS = ("iid", "garch", "shipped", "contopen", "contdrift")


def day_block(x: np.ndarray, day: np.ndarray, draws: int = DRAWS,
              seed: int = SEED) -> tuple[float, float, float]:
    """`(mean, lo, hi)` with whole days resampled.

    Regime labels persist for hours and trades cluster in days, so an ordinary
    standard error is far too narrow. Resample the days, not the rows.
    """
    if not len(x):
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    days, inv = np.unique(day, return_inverse=True)
    buckets = [x[inv == k] for k in range(len(days))]
    sums = np.array([b.sum() for b in buckets])
    counts = np.array([len(b) for b in buckets], float)
    pick = rng.integers(0, len(days), (draws, len(days)))
    num = sums[pick].sum(axis=1)
    den = counts[pick].sum(axis=1)
    boot = num / np.maximum(den, 1)
    return float(x.mean()), float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))


def block_p(x: np.ndarray, day: np.ndarray, floor: float = 0.0, draws: int = DRAWS,
            seed: int = SEED) -> float:
    """One-sided day-block p for `mean(x) > floor`."""
    if len(x) < 2:
        return float("nan")
    rng = np.random.default_rng(seed + 1)
    days, inv = np.unique(day, return_inverse=True)
    sums = np.array([x[inv == k].sum() for k in range(len(days))])
    counts = np.array([int((inv == k).sum()) for k in range(len(days))], float)
    pick = rng.integers(0, len(days), (draws, len(days)))
    boot = sums[pick].sum(axis=1) / np.maximum(counts[pick].sum(axis=1), 1)
    return float((boot <= floor).mean())


def bh(p: np.ndarray, q: float = 0.05) -> np.ndarray:
    """Benjamini-Hochberg at `q`; `True` where the cell survives."""
    ok = np.isfinite(p)
    out = np.zeros(len(p), bool)
    idx = np.flatnonzero(ok)
    if not len(idx):
        return out
    order = idx[np.argsort(p[idx])]
    m = len(order)
    thresh = q * (np.arange(1, m + 1) / m)
    under = p[order] <= thresh
    if under.any():
        out[order[: np.flatnonzero(under)[-1] + 1]] = True
    return out


def non_overlapping(df: pd.DataFrame) -> pd.DataFrame:
    """One trade at a time per instrument, interval and arm.

    `EXPIRE` is 300 bars and `HOLD` is 60, so trades overlap by construction and
    overlapping outcome windows have faked a result here before - a short skip
    rule with a long forward window read direction AUC 0.79 and collapsed to
    0.51. The greedy pass keeps the earliest fill, then the first fill at or
    after its exit.
    """
    keep = []
    for _key, g in df.sort_values("fill").groupby(["sym", "iv", "arm", "side"], sort=False):
        free = -1
        for row in g.itertuples():
            if row.fill >= free:
                keep.append(row.Index)
                free = row.exit
    return df.loc[keep]


def paired_gap(df: pd.DataFrame, a: str, b: str, draws: int = DRAWS,
               seed: int = SEED) -> tuple[float, float, float]:
    """`mean(a) - mean(b)` with the **same days** resampled for both arms.

    The gap, not either level, is the finding: a paired day-block bootstrap
    keeps the two arms on the same days, so the common market conditions cancel
    instead of being counted twice in the width.
    """
    xa = df[df["arm"] == a]
    xb = df[df["arm"] == b]
    if xa.empty or xb.empty:
        return float("nan"), float("nan"), float("nan")
    days = np.union1d(xa["day"].unique(), xb["day"].unique())
    ia = {d: g["R_gross"].to_numpy() for d, g in xa.groupby("day")}
    ib = {d: g["R_gross"].to_numpy() for d, g in xb.groupby("day")}
    sa = np.array([ia.get(d, np.zeros(0)).sum() for d in days])
    na = np.array([len(ia.get(d, ())) for d in days], float)
    sb = np.array([ib.get(d, np.zeros(0)).sum() for d in days])
    nb = np.array([len(ib.get(d, ())) for d in days], float)
    rng = np.random.default_rng(seed + 2)
    pick = rng.integers(0, len(days), (draws, len(days)))
    boot = (sa[pick].sum(axis=1) / np.maximum(na[pick].sum(axis=1), 1)
            - sb[pick].sum(axis=1) / np.maximum(nb[pick].sum(axis=1), 1))
    return (float(xa["R_gross"].mean() - xb["R_gross"].mean()),
            float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975)))


def line(name: str, x: np.ndarray, day: np.ndarray, reach: np.ndarray, cost: np.ndarray,
         resolved: np.ndarray, arith: float) -> str:
    mean, lo, hi = day_block(x, day)
    res = resolved.sum()
    cond = reach.sum() / res if res else float("nan")
    return (f"  {name:<30} n {len(x):7,d}  P(>={TARGET:.0f}R) {reach.mean():.4f}  "
            f"P|res {cond:.4f} (arith {arith:.4f})  meanR {mean:+.4f} "
            f"[{lo:+.4f}, {hi:+.4f}]  cost {cost.mean():.4f}  net {(x - cost).mean():+.4f}")


def arm_table(trades: pd.DataFrame, cells: pd.DataFrame, title: str) -> None:
    print(f"\n== {title} ==")
    arith = 1.0 / (1.0 + TARGET)
    for arm in ("flip", "flip_confirmed", "fade", "placebo"):
        g = trades[trades["arm"] == arm]
        if g.empty:
            continue
        print(line(f"real {arm}", g["R_gross"].to_numpy(), g["day"].to_numpy(),
                   g["reach"].to_numpy(float), g["cost_r"].to_numpy(),
                   g["resolved"].to_numpy(float), arith))
        for series in WALK_ARMS:
            c = cells[(cells["arm"] == arm) & (cells["series"] == series)]
            if c.empty:
                continue
            w = np.average(c["mean_R"], weights=c["n"])
            r = np.average(c["reach"], weights=c["n"])
            cr = np.average(c["reach_given_resolved"], weights=c["n"])
            print(f"    {series:<26} n {int(c['n'].sum()):7,d}  P(>={TARGET:.0f}R) {r:.4f}  "
                  f"P|res {cr:.4f}                   meanR {w:+.4f}")


def main() -> None:
    trades = pd.read_csv(OUT / "trades.csv.gz")
    cells = pd.read_csv(OUT / "cells.csv")
    zones = pd.read_csv(OUT / "zones.csv")
    trades = trades[trades["target"] == TARGET].copy()
    trades["day"] = trades["ts"] // 86400
    cells = cells[(cells["target"] == TARGET) & (cells["leg"] == "both")].copy()
    traded = cells["family"] != "deriv"
    print(f"{len(trades):,} real trades at {TARGET:.0f}R, {len(cells):,} cell rows, "
          f"{zones['sym'].nunique()} instruments, intervals {sorted(trades['iv'].unique())}")

    # ───────────────────── 1. the leak check, first ─────────────────────
    print("\n== the leak check: a walk cannot pay, so these must sit at or below zero ==")
    for series in WALK_ARMS:
        for arm in ("flip", "fade", "placebo"):
            c = cells[(cells["series"] == series) & (cells["arm"] == arm)]
            if c.empty:
                continue
            w = np.average(c["mean_R"], weights=c["n"])
            sd = np.sqrt(np.average(c["sd_R"] ** 2, weights=c["n"]))
            n = int(c["n"].sum())
            print(f"  {series:<8}{arm:<16} n {n:8,d}  meanR {w:+.4f} +-{sd / np.sqrt(n):.4f}  "
                  f"P(>={TARGET:.0f}R) {np.average(c['reach'], weights=c['n']):.4f}  "
                  f"P|res {np.average(c['reach_given_resolved'], weights=c['n']):.4f}")

    # ───────────────────── 2-3. the arms, pooled and by clock ─────────────────────
    real = trades[trades["family"] != "deriv"]
    arm_table(real, cells[traded], "every arm, traded instruments, pooled")
    for iv in sorted(real["iv"].unique()):
        arm_table(real[real["iv"] == iv], cells[traded & (cells["iv"] == iv)],
                  f"every arm at {iv}")
    arm_table(trades[trades["family"] == "deriv"], cells[~traded],
              "Deriv synthetics: no participant leaves unfilled interest, so no block to flip")

    # ──────────── 3a. is any mean one row, and are the records consistent ────────────
    print("\n== every mean with its median beside it, and the arithmetic the rows must obey ==")
    for arm in ("flip", "fade", "placebo"):
        g = real[real["arm"] == arm]
        if g.empty:
            continue
        x = g["R_gross"]
        nogap = g[~g["reason"].isin(["stop_gap", "target_gap"])]["R_gross"]
        print(f"  {arm:<10} n {len(x):7,d}  mean {x.mean():+.4f}  median {x.median():+.2f}  "
              f"range [{x.min():+.2f}, {x.max():+.2f}]  winsorised to [-1.5, {TARGET + 0.5:.1f}] "
              f"{x.clip(-1.5, TARGET + 0.5).mean():+.4f}  without gap exits ({len(x) - len(nogap)} "
              f"rows) {nogap.mean():+.4f}")
    bad = {
        "reach without the R": int(((trades["reach"] == 1)
                                    & (trades["R_gross"] < trades["target"] - 1e-9)).sum()),
        "the R without the reach": int(((trades["reach"] == 0)
                                        & (trades["R_gross"] >= trades["target"] - 1e-9)).sum()),
        "unresolved but not timed out": int(((trades["resolved"] == 0)
                                             & (trades["reason"] != "time")).sum()),
        "a stop that did not pay -1R": int(((trades["reason"] == "stop")
                                            & ((trades["R_gross"] + 1).abs() > 1e-9)).sum()),
    }
    print("  record consistency over every row: " + ", ".join(f"{k} {v}" for k, v in bad.items()))

    # ───────────────── 3b. the gaps, which are the finding ─────────────────
    print("\n== the gaps: the breaker against each control, paired on days ==")
    for iv in [None, *sorted(real["iv"].unique())]:
        sel = real if iv is None else real[real["iv"] == iv]
        for other in ("placebo", "fade", "flip_confirmed"):
            g, lo, hi = paired_gap(sel, "flip", other)
            print(f"  {(iv or 'pooled'):>6}  flip - {other:<15} {g:+.4f} [{lo:+.4f}, {hi:+.4f}]")
        f = sel[sel["arm"] == "flip"]
        for series in WALK_ARMS:
            # Unpaired by construction: a walk is a different series, so there
            # are no shared days to pair on and the width is the two arms' added.
            c = cells[traded & (cells["arm"] == "flip") & (cells["series"] == series)
                      & ((cells["iv"] == iv) if iv else True)]
            if c.empty or f.empty:
                continue
            w = np.average(c["mean_R"], weights=c["n"])
            sdw = np.sqrt(np.average(c["sd_R"] ** 2, weights=c["n"]))
            se = np.sqrt(f["R_gross"].var(ddof=1) / len(f) + sdw**2 / c["n"].sum())
            print(f"  {(iv or 'pooled'):>6}  flip - walk({series:<9}) {f['R_gross'].mean() - w:+.4f} "
                  f"+-{se:.4f}  (unpaired; separate series)")
        if not f.empty:
            print(f"  {(iv or 'pooled'):>6}  the measured round trip it must clear: "
                  f"{f['cost_r'].mean():.4f}R")

    # ───────────────────── 4. per instrument ─────────────────────
    # **The per-cell p is against zero, not against a walk.** Both geometry
    # surrogates assemble the inside of a bar differently from the market and
    # from each other, and a resting-limit arm moves 0.171R between them, so a
    # per-cell test against one of them would rest on an assembly choice. Zero
    # is the floor that needs no surrogate, and it is the harder one anyway:
    # every walk arm reads negative, so `max(walk, 0)` was already zero on
    # nearly every cell when this test was written that way.
    print("\n== per instrument, breaker at 2R (never only pooled) ==")
    print(f"  {'sym':<22}{'iv':>3} {'n':>6} {'P>=2R':>7} {'meanR':>9} {'lo':>9} {'hi':>9} "
          f"{'fade':>9} {'placebo':>9} {'shipped':>9} {'contopen':>9} {'net':>9}")
    rows = []
    for (sym, iv), g in trades.groupby(["sym", "iv"]):
        f = g[g["arm"] == "flip"]
        if f.empty:
            continue
        mean, lo, hi = day_block(f["R_gross"].to_numpy(), f["day"].to_numpy())
        fade = g[g["arm"] == "fade"]["R_gross"].mean()
        plc = g[g["arm"] == "placebo"]["R_gross"].mean()
        walk = {}
        for series in ("shipped", "contopen"):
            gw = cells[(cells["sym"] == sym) & (cells["iv"] == iv)
                       & (cells["series"] == series) & (cells["arm"] == "flip")]
            walk[series] = np.average(gw["mean_R"], weights=gw["n"]) if len(gw) else float("nan")
        p = block_p(f["R_gross"].to_numpy(), f["day"].to_numpy(), floor=0.0)
        net = (f["R_gross"] - f["cost_r"]).mean()
        rows.append({"sym": sym, "iv": iv, "family": g["family"].iat[0], "n": len(f),
                     "reach": f["reach"].mean(), "mean_R": mean, "lo": lo, "hi": hi,
                     "fade": fade, "placebo": plc, "shipped": walk["shipped"],
                     "contopen": walk["contopen"], "net_R": net, "p": p})
        print(f"  {sym:<22}{iv:>3} {len(f):6,d} {f['reach'].mean():7.4f} {mean:+9.4f} "
              f"{lo:+9.4f} {hi:+9.4f} {fade:+9.4f} {plc:+9.4f} {walk['shipped']:+9.4f} "
              f"{walk['contopen']:+9.4f} {net:+9.4f}")
    per = pd.DataFrame(rows)
    per.to_csv(OUT / "per_instrument.csv", index=False)

    # ───────────────────── 5. non-overlapping ─────────────────────
    print("\n== the non-overlapping subsample (one live trade at a time) ==")
    nov = non_overlapping(real)
    for arm in ("flip", "fade", "placebo"):
        g = nov[nov["arm"] == arm]
        if g.empty:
            continue
        print(line(f"non-overlapping {arm}", g["R_gross"].to_numpy(), g["day"].to_numpy(),
                   g["reach"].to_numpy(float), g["cost_r"].to_numpy(),
                   g["resolved"].to_numpy(float), 1.0 / (1.0 + TARGET)))

    # ───────────────────── 6. the halves and the legs ─────────────────────
    print("\n== split halves and the two legs, as a gating condition, not a verdict ==")
    for iv in sorted(real["iv"].unique()):
        for arm in ("flip", "fade", "placebo"):
            g = real[(real["iv"] == iv) & (real["arm"] == arm)].sort_values("ts")
            if len(g) < 40:
                continue
            half = len(g) // 2
            a, b = g.iloc[:half], g.iloc[half:]
            ma = day_block(a["R_gross"].to_numpy(), a["day"].to_numpy())
            mb = day_block(b["R_gross"].to_numpy(), b["day"].to_numpy())
            lg = g[g["side"] > 0]["R_gross"]
            sh = g[g["side"] < 0]["R_gross"]
            print(f"  {iv:>3} {arm:<16} first {ma[0]:+.4f} [{ma[1]:+.4f}, {ma[2]:+.4f}]  "
                  f"second {mb[0]:+.4f} [{mb[1]:+.4f}, {mb[2]:+.4f}]  "
                  f"long {lg.mean():+.4f} (n {len(lg):,}) short {sh.mean():+.4f} (n {len(sh):,})")
    print("\n  deep store (2015 on) against the wide one (2024 on), breaker at 2R:")
    for store in sorted(real["store"].unique()):
        g = real[(real["store"] == store) & (real["arm"] == "flip")]
        if g.empty:
            continue
        m = day_block(g["R_gross"].to_numpy(), g["day"].to_numpy())
        print(f"    {store:<8} n {len(g):7,d}  meanR {m[0]:+.4f} [{m[1]:+.4f}, {m[2]:+.4f}]")

    # ───────────────────── 7. Benjamini-Hochberg ─────────────────────
    if len(per):
        surv = bh(per["p"].to_numpy())
        print(f"\n== Benjamini-Hochberg over {len(per)} (instrument, interval) cells, q 0.05 ==")
        print(f"  nominally positive: {(per['mean_R'] > 0).sum()} of {len(per)}; "
              f"lower bound above zero: {(per['lo'] > 0).sum()}; "
              f"beating zero at p<0.05: {(per['p'] < 0.05).sum()}; "
              f"surviving BH: {int(surv.sum())}")
        if surv.any():
            print(per[surv][["sym", "iv", "n", "mean_R", "lo", "hi", "shipped", "contopen",
                             "p"]].to_string(index=False))

    # ───────────────────── firing rates and the drops ─────────────────────
    z = zones[zones["series"] == "real"]
    print("\n== firing rates, per 1,000 bars, real series ==")
    for iv in sorted(z["iv"].unique()):
        g = z[z["iv"] == iv]
        bars = g["bars"].sum()
        print(f"  {iv:>3} bars {bars:9,d}  zones {g['zones'].sum() / bars * 1000:6.2f}  "
              f"flipped {g['flipped'].sum() / bars * 1000:6.2f}  "
              f"confirmed {g['confirmed'].sum() / bars * 1000:6.2f}  "
              f"placebo pool {g['placebo_pool'].sum() / bars * 1000:6.2f}  "
              f"wrong-side drops {int(g['wrong_side'].sum()):,}  "
              f"duplicate bars dropped {int(g['dupes'].sum()):,}")
    print(f"  flip rate: {z['flipped'].sum() / max(1, z['zones'].sum()):.4f} of zones flip; "
          f"{z['confirmed'].sum() / max(1, z['flipped'].sum()):.4f} of flips are confirmed")

    # ───────────────────── the holding window and the reasons ─────────────────────
    print("\n== how the breaker trades end ==")
    for iv in sorted(real["iv"].unique()):
        g = real[(real["iv"] == iv) & (real["arm"] == "flip")]
        counts = g["reason"].value_counts(normalize=True)
        print(f"  {iv:>3} " + "  ".join(f"{k} {v:.4f}" for k, v in counts.items())
              + f"   median bars held {g['bars'].median():.0f}"
              + f"   median stop {g['stop_d'].div(g['unit']).median():.2f} ATR")


if __name__ == "__main__":
    main()
