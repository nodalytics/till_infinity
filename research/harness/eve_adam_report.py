"""The tables `research/docs/eve-and-adam.md` is written from.

    ./.secrets/lab.sh exec '.venv/bin/python repo/research/harness/eve_adam_report.py'

**The day-block arm is the one that decides this rule.** `chart-patterns.md`
found the measure rule beats the i.i.d. walk by up to 2.5x and that the
day-block shuffle reproduces it almost exactly, and this rule's target *is*
the measure rule - so a hit rate above the i.i.d. walk is already explained
and only the day-block comparison is news. Both are printed, in that order.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

from research.harness.eve_adam import VARIANTS, fair_rate
from research.harness.letter_shapes import SYNTH, bh

OUT = os.environ.get("OUT", "out/eve_adam")
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 500)
CELLS = ["all", *VARIANTS, "unclassified"]
FAIR = fair_rate()


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    cells = pd.read_csv(f"{OUT}/cells.csv")
    seps = pd.read_csv(f"{OUT}/separability.csv")
    if cells.empty or seps.empty:
        raise SystemExit("empty output")
    cells["generated"] = cells.symbol.isin(SYNTH)
    seps["generated"] = seps.symbol.isin(SYNTH)
    print(f"{len(cells)} cells, {cells.symbol.nunique()} symbols, "
          f"fair rate {FAIR:.4f}, null draws {int(cells.iid_draws.max())} per arm",
          file=sys.stderr)

    line("0. SEPARABILITY - are the four variants anything, before they are traded?")
    print("width labels the bottom; duration is never used to label, so their "
          "agreement is a test\nand not a restatement. Roundedness was tried and "
          "rejected - its kappa is printed beside.\n")
    for group, mask in (("traded", ~seps.generated), ("generated", seps.generated)):
        sub = seps[mask]
        tab = sub.groupby("lookback").agg(
            cells=("bottoms", "size"), bottoms=("bottoms", "sum"),
            spearman=("spearman_w_d", "mean"), kappa=("kappa", "mean"),
            kappa_round=("kappa_roundedness", "mean"),
            d_adam=("d_adam", "mean"), d_eve=("d_eve", "mean"),
            gap_sd=("d_gap_sd", "mean"), adam=("share_adam", "mean"),
            eve=("share_eve", "mean"), mid=("share_mid", "mean"))
        print(f"-- {group} --")
        print(tab.round(4).to_string())
    print("\n-- per instrument, 15m, lookback 3 --")
    one = seps[(seps.tf == "15m") & (seps.lookback == 3)]
    print(one[["symbol", "bottoms", "spearman_w_d", "kappa", "kappa_roundedness",
               "d_adam", "d_eve", "d_gap_sd", "share_adam", "share_eve",
               "share_mid"]].round(4).to_string(index=False))
    print("\n-- the variant mix, pooled --")
    mix = seps.groupby(["generated", "lookback"])[
        [f"mix_{n}" for n in (*VARIANTS, "unclassified")]].mean()
    print(mix.round(4).to_string())

    line("1. THE RULE - P(target before stop) against 1/(1+2) = 0.3333, per variant")
    live = cells[cells.races >= 100]
    for group, mask in (("traded", ~live.generated), ("generated", live.generated)):
        sub = live[mask]
        tab = sub.groupby("cell").agg(
            cells=("hit", "size"), races=("races", "sum"), hit=("hit", "mean"),
            lo=("hit_lo", "mean"), hi=("hit_hi", "mean"),
            iid=("iid_hit", "mean"), dayblock=("dayblock_hit", "mean"),
            cost_r=("cost_r", "mean"), net_r=("net_r", "mean"),
            one_to_one=("race_1to1", "mean"),
            unresolved=("unresolved", "mean"))
        tab["edge"] = tab.hit - FAIR
        tab["vs_dayblock"] = tab.hit - tab.dayblock
        print(f"\n-- {group}, cells with 100+ races --")
        print(tab.reindex(CELLS).dropna(how="all").round(4).to_string())

    line("2. THE RULE - per instrument, pooled over variants and cells")
    print(live.groupby("symbol").agg(
        cells=("hit", "size"), races=("races", "sum"), hit=("hit", "mean"),
        iid=("iid_hit", "mean"), dayblock=("dayblock_hit", "mean"),
        cost_r=("cost_r", "mean"), net_r=("net_r", "mean"),
        one_to_one=("race_1to1", "mean"),
        net_positive=("net_r", lambda s: float((s > 0).mean()))
    ).round(4).to_string())

    line("3. THE RULE - per instrument x variant at 15m, lookback 3")
    head = cells[(cells.tf == "15m") & (cells.lookback == 3)]
    print(head[["symbol", "cell", "n", "races", "hit", "hit_lo", "hit_hi",
                "p_vs_fair", "iid_hit", "dayblock_hit", "cost_r", "net_r",
                "race_1to1"]].round(4).to_string(index=False))

    line("4. THE 1:1 CONTROL ON THE SAME EVENTS")
    tab = live.groupby(["generated", "cell"]).agg(
        races=("n_1to1", "sum"), one_to_one=("race_1to1", "mean"),
        iid=("iid_race_1to1", "mean"), dayblock=("dayblock_race_1to1", "mean"),
        two_to_one=("hit", "mean"))
    print(tab.round(4).to_string())
    print("\nIf the 2:1 race sits on 0.3333 and the 1:1 on 0.5000 over the same "
          "patterns,\nthe geometry changes nothing and 1/(1+N) is doing what it does.")

    line("5. COST - what halving the stop did")
    cost = cells.groupby("symbol").agg(
        quoted=("quoted", "mean"), stored=("stored", "mean"),
        cost_r=("cost_r", "mean"))
    cost["stop_is_half_height"] = cost.cost_r
    cost["cost_r_at_1to1"] = cost.cost_r / 2.0
    cost["quoted/stored"] = cost.quoted / cost.stored
    print(cost[["quoted", "stored", "quoted/stored", "cost_r_at_1to1",
                "stop_is_half_height"]].round(5).to_string())
    print(f"\nhit rate needed to break even at 2:1, per instrument "
          f"(= (1 + cost) / 3):")
    print(((1 + cost.cost_r) / 3).round(4).to_string())

    line("6. MULTIPLICITY - Benjamini-Hochberg over the full cell count")
    for arm in ("dayblock", "iid"):
        z = (live.hit - live[f"{arm}_hit"]) / live[f"{arm}_hit_sd"]
        p = 2.0 * norm.sf(np.abs(z.to_numpy(float)))
        keep = bh(p)
        print(f"{arm:9s}: rank-p floor {live[f'{arm}_hit_p'].min():.3f}; "
              f"BH on the z keeps {int(keep.sum())} of {len(live)}, "
              f"{int(live.generated.to_numpy()[keep].sum())} on generated markets")
        if keep.sum():
            top = live[keep].assign(z=z[keep])
            print(top.reindex(top.z.abs().sort_values(ascending=False).index).head(10)[
                ["symbol", "tf", "lookback", "cell", "races", "hit",
                 f"{arm}_hit", "z", "net_r"]].round(4).to_string(index=False))
    print(f"\ncells below 100 races: {int((cells.races < 100).sum())} of {len(cells)} "
          f"(reported with their n, never dropped)")
    print("direction of the break-out: "
          f"{cells.up_break.mean():.4f} of double bottoms broke upward")

    power = f"{OUT.rsplit('/', 1)[0]}/eve_adam_power/power.csv"
    if os.path.exists(power):
        line("7. POWER - a planted drift on the generated markets")
        pw = pd.read_csv(power)
        print(pw.groupby("plant").agg(
            cells=("p", "size"), hit=("hit", "mean"),
            detected=("p", lambda s: float((s < 0.05).mean())),
            races=("n", "mean"), disjoint=("disjoint", "mean")).round(4).to_string())
        print("\n-- by cell --")
        print(pw.pivot_table(index="cell", columns="plant", values="hit")
              .round(4).to_string())


if __name__ == "__main__":
    main()
