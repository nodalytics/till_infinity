"""Read `vol_gate.py`'s three CSVs and print the tables the write-up quotes.

    OUT=.secrets/vol_gate uv run python research/harness/vol_gate_report.py

Nothing is computed here that the harness did not already measure, with two
exceptions, both stated where they are printed: the Benjamini-Hochberg pass
over the full real-arm cell count, and Stouffer's pooled z across instruments.
Pooling is reported **beside** the per-instrument rows and never instead of
them - a pooled median on this desk once agreed with a claim every subgroup
refuted.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

OUT = os.environ.get("OUT", ".")
#: The headline cell, fixed before the run: the best volatility model drives
#: both the stop and the gate, and the target is the 2R the book is built for.
HEAD_BOOK, HEAD_GATE, HEAD_TARGET = "gbm", "model", 2.0
MEASURES = (("net", "net R"), ("gross", "gross R"), ("cash", "fixed cash unit"))


def bh(p: np.ndarray, q: float = 0.05) -> np.ndarray:
    out = np.zeros(len(p), bool)
    ok = np.isfinite(p)
    if not ok.any():
        return out
    idx = np.flatnonzero(ok)
    order = idx[np.argsort(p[idx])]
    passed = p[order] <= q * np.arange(1, len(order) + 1) / len(order)
    if passed.any():
        out[order[: np.flatnonzero(passed)[-1] + 1]] = True
    return out


def stouffer(z: np.ndarray) -> float:
    """Pooled z over instruments. Equal weights, because the instruments are
    different markets rather than more of the same one."""
    z = z[np.isfinite(z)]
    return float(z.sum() / np.sqrt(len(z))) if len(z) else float("nan")


def show(df: pd.DataFrame, cols: list[str], title: str, fmt: str = "%.3f") -> None:
    print(f"\n### {title}\n")
    if df.empty:
        print("(no rows)")
        return
    print(df[cols].to_string(index=False, float_format=lambda v: fmt % v))


def main() -> None:
    cal = pd.read_csv(f"{OUT}/vol_gate_calibration.csv")
    book = pd.read_csv(f"{OUT}/vol_gate_book.csv")
    buckets = pd.read_csv(f"{OUT}/vol_gate_buckets.csv")
    pd.set_option("display.width", 250)

    print("=" * 78)
    print("STAGE A - the volatility model, and its calibration")
    print("=" * 78)
    conf = cal[cal.half == "confirmation"]
    show(conf.groupby("model", as_index=False).agg(
        n=("n", "sum"), qlike=("qlike", "mean"), spearman=("spearman", "mean"),
        cov_g90=("cov_gauss90", "mean"), cov_t4_90=("cov_t4_90", "mean"),
        cov_cal90=("cov_cal90", "mean"), cov_g99=("cov_gauss99", "mean"),
        cov_t4_99=("cov_t4_99", "mean")),
        ["model", "n", "qlike", "spearman", "cov_g90", "cov_t4_90", "cov_cal90",
         "cov_g99", "cov_t4_99"],
        "pooled over 12 instruments, confirmation half (nominal 0.90 / 0.99)", "%.4f")
    for kind in ("traded", "synth"):
        show(conf[conf.kind == kind].pivot_table(
            index="symbol", columns="model", values="qlike").reset_index(),
            ["symbol", "ewma", "har", "gbm"], f"QLIKE per instrument, {kind} (lower better)",
            "%.4f")
    show(conf[conf.kind == "traded"].pivot_table(
        index="symbol", columns="model", values="spearman").reset_index(),
        ["symbol", "ewma", "har", "gbm"], "Spearman rank corr, traded", "%.4f")

    print("\n" + "=" * 78)
    print("THE QUESTION - every gate against its duty-cycle twin")
    print("=" * 78)
    real = book[(book.arm == "real") & (book.keep < 1.0)]
    print(f"\nreal-arm gate-vs-twin cells: {len(real)}")
    rows = []
    for name, label in MEASURES:
        for control, how in ((f"p_{name}", "duty-cycle twin"),
                             (f"ph_{name}", "hour placebo")):
            hit = bh(real[control].to_numpy())
            up = int((hit & (real[f"z_{name}"].to_numpy() > 0)).sum())
            rows.append({"measure": label, "control": how, "cells": len(real),
                         "BH rejections": int(hit.sum()), "positive": up,
                         "negative": int(hit.sum()) - up,
                         "median z": float(np.nanmedian(real[f"z_{name}"]))})
    show(pd.DataFrame(rows),
         ["measure", "control", "cells", "BH rejections", "positive", "negative",
          "median z"], "Benjamini-Hochberg q=0.05 over the full cell count")

    head = real[(real.book == HEAD_BOOK) & (real.gate == HEAD_GATE)
                & (real.target == HEAD_TARGET) & (real.half == "confirmation")]
    for rule in sorted(head.rule.unique()):
        cut = head[(head.rule == rule) & (head.kind == "traded")]
        show(cut.sort_values(["symbol", "keep"]),
             ["symbol", "keep", "n", "gross", "gross_se", "cost_r", "net", "net_se",
              "twin_net", "z_net", "z_gross", "z_cash", "zh_gross"],
             f"headline cell, rule={rule}, traded, confirmation half")
        for keep in sorted(cut.keep.unique()):
            k = cut[cut.keep == keep]
            print(f"    keep {keep:.2f}: pooled Stouffer z  net {stouffer(k.z_net.to_numpy()):+.2f}"
                  f"   gross {stouffer(k.z_gross.to_numpy()):+.2f}"
                  f"   cash {stouffer(k.z_cash.to_numpy()):+.2f}"
                  f"   gross-vs-hour {stouffer(k.zh_gross.to_numpy()):+.2f}")

    print("\n" + "=" * 78)
    print("THE COST ARITHMETIC - how much of the net improvement is cheaper trades")
    print("=" * 78)
    base = real_base = book[(book.arm == "real") & (book.keep == 1.0)]
    key = ["symbol", "book", "gate", "rule", "target", "half"]
    merged = real.merge(base[key + ["gross", "cost_r", "net", "cash"]], on=key,
                        suffixes=("", "_all"))
    merged["d_net"] = merged.net - merged.net_all
    merged["d_gross"] = merged.gross - merged.gross_all
    merged["d_cost"] = merged.cost_r_all - merged.cost_r
    merged["cost_share"] = merged.d_cost / merged.d_net.replace(0, np.nan)
    agg = merged[(merged.kind == "traded") & (merged.half == "confirmation")
                 & (merged.book == HEAD_BOOK) & (merged.gate == HEAD_GATE)]
    show(agg.groupby(["rule", "keep"], as_index=False).agg(
        n=("n", "sum"), d_net=("d_net", "mean"), d_gross=("d_gross", "mean"),
        d_cost=("d_cost", "mean"), cost_share=("cost_share", "median")),
        ["rule", "keep", "n", "d_net", "d_gross", "d_cost", "cost_share"],
        "d_net = d_gross + d_cost, traded, confirmation. cost_share is d_cost/d_net")

    bu = buckets[(buckets.book == HEAD_BOOK) & (buckets.gate == HEAD_GATE)
                 & (buckets.target == HEAD_TARGET)]
    show(bu[bu.kind == "traded"].groupby(["rule", "bucket"], as_index=False).agg(
        n=("n", "sum"), gross=("gross", "mean"), cost_r=("cost_r", "mean"),
        net=("net", "mean"), cash_net=("cash_net", "mean"), tail=("tail", "mean")),
        ["rule", "bucket", "n", "gross", "cost_r", "net", "cash_net", "tail"],
        "per predicted-volatility quintile, traded (bucket 4 is the highest)")

    print("\n" + "=" * 78)
    print("THE TAIL - P(>= N R) against the walk and against 1/(1+N)")
    print("=" * 78)
    tails = book[(book.book == HEAD_BOOK) & (book.gate == HEAD_GATE)
                 & (book.half == "confirmation") & (book.kind == "traded")
                 & book.arm.isin(("real", "walk"))]
    piv = tails.pivot_table(index=["rule", "target", "keep"], columns="arm",
                            values=["tail", "resolved"]).reset_index()
    piv.columns = ["_".join(c).strip("_") for c in piv.columns]
    piv["null"] = 1.0 / (1.0 + piv.target)
    piv["excess"] = piv.get("tail_real", np.nan) - piv.get("tail_walk", np.nan)
    show(piv, [c for c in ["rule", "target", "keep", "tail_real", "tail_walk", "null",
                           "excess", "resolved_real"] if c in piv],
         "traded, confirmation. `excess` is real minus the day-shuffled walk")

    print("\n" + "=" * 78)
    print("THE CONTROLS")
    print("=" * 78)
    show(real[(real.book == HEAD_BOOK) & (real.target == HEAD_TARGET)
              & (real.half == "confirmation") & (real.kind == "traded")].groupby(
        ["gate", "keep"], as_index=False).agg(
        hour_share=("hour_share", "mean"), z_net=("z_net", "median"),
        z_gross=("z_gross", "median"), zh_gross=("zh_gross", "median"),
        cost_r=("cost_r", "mean")),
        ["gate", "keep", "hour_share", "cost_r", "z_net", "z_gross", "zh_gross"],
        "the three gate statistics. hour_share is how much of firing the hour explains")

    synth = real[(real.kind == "synth") & (real.book == HEAD_BOOK)
                 & (real.gate == HEAD_GATE) & (real.target == HEAD_TARGET)
                 & (real.half == "confirmation") & (real.rule == "coin")]
    show(synth.sort_values(["symbol", "keep"]),
         ["symbol", "keep", "n", "gross", "cost_r", "net", "z_net", "z_gross", "z_cash"],
         "Deriv synthetics, coin rule: the constant-volatility generators must "
         "show nothing beyond the cost arithmetic")

    walk = book[(book.arm == "walk") & (book.keep < 1.0) & (book.kind == "traded")]
    rows = []
    for name, label in MEASURES:
        hit = bh(walk[f"p_{name}"].to_numpy())
        rows.append({"measure": label, "cells": len(walk),
                     "BH rejections": int(hit.sum()),
                     "positive": int((hit & (walk[f"z_{name}"] > 0)).sum()),
                     "median z": float(np.nanmedian(walk[f"z_{name}"]))})
    show(pd.DataFrame(rows), ["measure", "cells", "BH rejections", "positive", "median z"],
         "the day-shuffled walk arm, scored the same way")

    print("\n" + "=" * 78)
    print("POWER - a trend planted in the high-volatility regime only")
    print("=" * 78)
    plant = book[book.arm.str.startswith("plant") & (book.kind == "traded")]
    if plant.empty:
        print("(no planted arms in this run)")
        return
    base_rule = book[(book.arm == "real") & (book.rule == plant.rule.iloc[0])
                     & (book.book == plant.book.iloc[0])
                     & (book.gate == plant.gate.iloc[0])
                     & (book.target == plant.target.iloc[0])
                     & (book.kind == "traded") & (book.half == "all")]
    show(pd.concat([base_rule.assign(arm="real"), plant[plant.half == "all"]]).groupby(
        ["arm", "keep"], as_index=False).agg(
        n=("n", "sum"), gross=("gross", "mean"), net=("net", "mean"),
        z_net=("z_net", "median"), z_gross=("z_gross", "median")),
        ["arm", "keep", "n", "gross", "net", "z_net", "z_gross"],
        "planted sweep, traded, pooled. keep 1.00 is the ungated book")
    for arm in sorted(plant.arm.unique()):
        for keep in sorted(plant[plant.keep < 1.0].keep.unique()):
            k = plant[(plant.arm == arm) & (plant.keep == keep) & (plant.half == "all")]
            print(f"    {arm} keep {keep:.2f}: pooled Stouffer z  "
                  f"gross {stouffer(k.z_gross.to_numpy()):+.2f}  "
                  f"net {stouffer(k.z_net.to_numpy()):+.2f}  ({len(k)} instruments)")

    print("\n" + "=" * 78)
    print("SAMPLE")
    print("=" * 78)
    print(real_base[real_base.half == "all"].groupby(["kind", "rule"], as_index=False)
          .agg(instruments=("symbol", "nunique"), trades=("n", "sum"))
          .to_string(index=False))


if __name__ == "__main__":
    main()
