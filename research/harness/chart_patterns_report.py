"""The tables `research/docs/chart-patterns.md` is written from.

    ./.secrets/lab.sh exec '.venv/bin/python repo/research/harness/chart_patterns_report.py'

The published column is deliberately absent: the book was not to hand on the
machine this ran on, so each pattern is reported against the walk arms alone.
See the harness docstring.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

from research.harness.chart_patterns import PATTERNS
from research.harness.letter_shapes import SYNTH, bh

OUT = os.environ.get("OUT", "out/patterns")
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 500)
ORDER = list(PATTERNS)


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def zcol(real: pd.Series, null: pd.Series, sd: pd.Series) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (real.to_numpy(float) - null.to_numpy(float)) / sd.to_numpy(float)
    return z


def main() -> None:
    df = pd.read_csv(f"{OUT}/patterns.csv")
    if df.empty:
        raise SystemExit("patterns.csv is empty")
    df["generated"] = df.symbol.isin(SYNTH)
    traded = sorted(df[~df.generated].symbol.unique())
    print(f"{len(df)} rows, {df.symbol.nunique()} symbols, "
          f"{df.pattern.nunique()} patterns, tf {sorted(df.tf.unique())}, "
          f"lookbacks {sorted(df.lookback.unique())}, "
          f"null draws {int(df.iid_draws.max())} per arm", file=sys.stderr)

    line("1. COVERAGE - how often each pattern fires, and where it was too rare")
    cov = df.groupby("pattern").agg(
        cells=("n", "size"), events=("n", "sum"), median_n=("n", "median"),
        cells_over_100=("n", lambda s: int((s >= 100).sum())),
        iid_events=("iid_n", "sum"))
    print(cov.reindex(ORDER).round(1).to_string())

    line("2. BREAK-OUT DIRECTION - measured here, and what the walk reads")
    for group, mask in (("traded", ~df.generated), ("generated", df.generated)):
        sub = df[mask & (df.n >= 100)]
        tab = sub.groupby("pattern").agg(
            cells=("n", "size"), n=("n", "sum"), up=("up_share", "mean"),
            walk_iid=("iid_up_share", "mean"),
            walk_day=("dayblock_up_share", "mean"),
            sd=("iid_up_share_sd", "mean"))
        tab["gap"] = tab.up - tab.walk_iid
        tab["z"] = tab.gap / tab.sd
        print(f"\n-- {group}, cells with n>=100 --")
        print(tab.reindex(ORDER).dropna(how="all").round(4).to_string())

    line("3. BREAK-OUT DIRECTION - per instrument, at 1h and lookback 3")
    one = df[(df.tf == "1h") & (df.lookback == 3) & (df.n >= 100)]
    piv = one.pivot_table(index="pattern", columns="symbol", values="up_share")
    print(piv.reindex(ORDER).round(3).to_string())
    print("\n-- the same cells on the i.i.d. walk --")
    print(one.pivot_table(index="pattern", columns="symbol",
                          values="iid_up_share").reindex(ORDER).round(3).to_string())

    line("4. THE REST OF THE SCHEMA - rise, failure, throwback, measure rule")
    for group, mask in (("traded", ~df.generated), ("generated", df.generated)):
        sub = df[mask & (df.n >= 100)]
        tab = sub.groupby("pattern").agg(
            n=("n", "sum"),
            # **The median, not the mean.** `rise` is a move divided by the
            # pattern's own height, and a fitted-boundary pattern can have a
            # height near zero, so the ratio has no finite mean: the walk arm
            # read 831 pattern heights for a rounding top on one cell. The
            # share of cells above 10 is printed beside it as the diagnostic.
            rise=("rise", "median"), rise_walk=("iid_rise", "median"),
            rise_wild=("iid_rise", lambda s: float((s > 10).mean())),
            fail=("fail_rate", "mean"), fail_walk=("iid_fail_rate", "mean"),
            throwback=("throwback", "mean"), tb_walk=("iid_throwback", "mean"),
            measure=("measure_met", "mean"), meas_walk=("iid_measure_met", "mean"),
            meas_day=("dayblock_measure_met", "mean"))
        print(f"\n-- {group} (rise in pattern heights) --")
        print(tab.reindex(ORDER).dropna(how="all").round(4).to_string())

    line("5. THE MEASURE RULE AS A 1:1 RACE - the walk answers 0.500 exactly")
    for group, mask in (("traded", ~df.generated), ("generated", df.generated)):
        sub = df[mask & (df.race_n >= 100)]
        tab = sub.groupby("pattern").agg(
            cells=("race", "size"), n=("race_n", "sum"), race=("race", "mean"),
            walk=("iid_race", "mean"), walk_day=("dayblock_race", "mean"),
            sd=("iid_race_sd", "mean"), cost=("cost_r", "mean"),
            net=("race_net", "mean"))
        tab["z_vs_walk"] = (tab.race - tab.walk) / tab.sd
        tab["z_vs_half"] = (tab.race - 0.5) / tab.sd
        print(f"\n-- {group} --")
        print(tab.reindex(ORDER).dropna(how="all").round(4).to_string())
    print("\n-- per instrument, pooled over patterns, cells with race_n>=100 --")
    sub = df[df.race_n >= 100]
    print(sub.groupby("symbol").agg(
        cells=("race", "size"), n=("race_n", "sum"), race=("race", "mean"),
        walk=("iid_race", "mean"), cost_r=("cost_r", "mean"),
        net=("race_net", "mean"),
        net_positive=("race_net", lambda s: float((s > 0).mean()))
    ).round(4).to_string())

    line("6. MULTIPLICITY - Benjamini-Hochberg over the whole surface")
    live = df[df.n >= 100].copy()
    print(f"cells {len(df)}; with n>=100 {len(live)} "
          f"({df.pattern.nunique()} patterns x {df.tf.nunique()} timeframes x "
          f"{df.lookback.nunique()} lookbacks x {df.symbol.nunique()} instruments)")
    for field in ("up_share", "measure_met", "race"):
        z = zcol(live[field], live[f"iid_{field}"], live[f"iid_{field}_sd"])
        p = 2.0 * norm.sf(np.abs(z))
        keep = bh(p)
        gen = int(live.generated.to_numpy()[keep].sum())
        print(f"{field:12s}: rank-p floor {live[f'iid_{field}_p'].min():.3f}; "
              f"BH on the z keeps {int(keep.sum())} of {len(live)}, "
              f"{gen} on generated markets")
        if keep.sum():
            top = live[keep].assign(z=z[keep]).reindex(
                live[keep].assign(z=np.abs(z[keep])).z.sort_values(
                    ascending=False).index).head(10)
            print(top[["symbol", "tf", "lookback", "pattern", "n", field,
                       f"iid_{field}", "z"]].round(4).to_string(index=False))

    line("7. THE COST LINE - the stored spread column against the quote")
    cost = df.groupby("symbol").agg(quoted=("quoted", "mean"),
                                    stored=("stored", "mean"))
    cost["quoted/stored"] = cost.quoted / cost.stored
    print(cost.round(6).to_string())
    live = df[df.race_n >= 100]
    for label, col in (("quoted", "cost_r"),):
        pos = (live.race * 2 - 1 - live[col] > 0)
        print(f"\ncells positive net of the {label} round trip: "
              f"{int(pos.sum())} of {len(live)}")
    print(f"traded instruments with a positive mean net: "
          f"{int((live[~live.generated].groupby('symbol').race_net.mean() > 0).sum())} "
          f"of {len(traded)}")

    power = f"{OUT.rsplit('/', 1)[0]}/patterns_power2/power.csv"
    if os.path.exists(power):
        line("8. POWER - a planted break-out bias on the generated markets")
        pw = pd.read_csv(power)
        print(pw.groupby("plant").agg(
            cells=("p", "size"), race=("race", "mean"),
            detected=("p", lambda s: float((s < 0.05).mean())),
            n=("n", "mean"), disjoint=("n_disjoint", "mean")).round(4).to_string())


if __name__ == "__main__":
    main()
