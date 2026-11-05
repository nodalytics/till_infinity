"""The tables `research/docs/letter-shapes.md` is written from.

    ./.secrets/lab.sh exec '.venv/bin/python repo/research/harness/letter_report.py'

**Why a z and not the rank p.** The census null has 24 draws, so a rank p
cannot go below 1/25 = 0.040 and 5,376 cells are tied at that floor;
Benjamini-Hochberg over a family that size needs 1.9e-5 to reject anything and
therefore rejects **nothing**, whatever the data say. The rate is a count over
200,000-300,000 windows with hundreds of events, so its sampling distribution
is close to normal and a z against the 24 surrogate draws has no floor. Both
are printed; BH runs on the z.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import norm

from research.harness.letter_shapes import HEADLINE, LETTERS, MIRROR, SYNTH, bh

OUT = os.environ.get("OUT", "out/letters")
TF, WIN, GATE, K = HEADLINE
pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 400)


def zp(z: pd.Series) -> np.ndarray:
    return 2.0 * norm.sf(np.abs(z.to_numpy(float)))


def line(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def main() -> None:
    census = pd.read_csv(f"{OUT}/census.csv")
    trans = pd.read_csv(f"{OUT}/trans.csv")
    vol = pd.read_csv(f"{OUT}/vol.csv")
    dirs = pd.read_csv(f"{OUT}/dir.csv")
    for name, frame in (("census", census), ("trans", trans), ("vol", vol),
                        ("dir", dirs)):
        if frame.empty:
            raise SystemExit(f"{name}.csv is empty")
        print(f"{name}: {len(frame)} rows, {frame.symbol.nunique()} symbols",
              file=sys.stderr)
    traded = [s for s in census.symbol.unique() if s not in SYNTH]

    line("1. CENSUS - the headline cell, per instrument, letters pooled")
    head = census[(census.tf == TF) & (census.window == WIN) & (census.gate == "strict")]
    for arm in ("iid", "dayblock"):
        head = head.assign(**{f"{arm}_pz": zp(head[f"{arm}_z"])})
    agg = head.groupby("symbol").apply(
        lambda g: pd.Series({
            "events": g.n.sum(), "nwin": g.nwin.iloc[0],
            "rate_x1e4": g.n.sum() / g.nwin.iloc[0] * 1e4,
            "iid_x1e4": g.iid_rate.sum() * 1e4,
            "iid_ratio": g.n.sum() / g.nwin.iloc[0] / max(g.iid_rate.sum(), 1e-12),
            "dayblock_x1e4": g.dayblock_rate.sum() * 1e4,
            "dayblock_ratio": g.n.sum() / g.nwin.iloc[0]
            / max(g.dayblock_rate.sum(), 1e-12),
        }), include_groups=False)
    print(agg.round(4).to_string())

    line("2. CENSUS - per letter at the headline cell, traded panel vs synthetics")
    for group, names in (("traded", traded), ("generated", list(SYNTH))):
        sub = head[head.symbol.isin(names)]
        tab = sub.groupby("letter").agg(
            n=("n", "sum"), rate=("rate", "mean"), iid=("iid_rate", "mean"),
            iid_ratio=("iid_ratio", "mean"), iid_z=("iid_z", "mean"),
            day=("dayblock_rate", "mean"), day_ratio=("dayblock_ratio", "mean"),
            day_z=("dayblock_z", "mean"))
        tab["rate_x1e4"] = tab.pop("rate") * 1e4
        tab["iid_x1e4"] = tab.pop("iid") * 1e4
        tab["day_x1e4"] = tab.pop("day") * 1e4
        print(f"\n-- {group} --")
        print(tab.reindex(list(LETTERS)).round(4).to_string())

    line("3. CENSUS - the negation check: a letter and its mirror on a walk")
    mir = head.set_index(["symbol", "letter"])
    rows = []
    for sym in head.symbol.unique():
        for a in LETTERS:
            b = MIRROR[a]
            if a >= b:
                continue
            na, nb = mir.loc[(sym, a), "n"], mir.loc[(sym, b), "n"]
            ia = mir.loc[(sym, a), "iid_rate"]
            ib = mir.loc[(sym, b), "iid_rate"]
            rows.append({"pair": f"{a}/{b}", "real_ratio": na / max(nb, 1),
                         "walk_ratio": ia / max(ib, 1e-12),
                         "n": int(na + nb)})
    pairs = pd.DataFrame(rows).groupby("pair").agg(
        real_ratio=("real_ratio", "mean"), walk_ratio=("walk_ratio", "mean"),
        n=("n", "sum"))
    print(pairs.round(3).to_string())

    line("4. CENSUS - the whole surface, and BH on the z")
    full = census.copy()
    for arm in ("iid", "dayblock"):
        full[f"{arm}_pz"] = zp(full[f"{arm}_z"])
        full[f"{arm}_bhz"] = bh(full[f"{arm}_pz"].to_numpy())
    print(f"cells: {len(full)}  (letters {census.letter.nunique()} x windows "
          f"{census.window.nunique()} x timeframes {census.tf.nunique()} x "
          f"instruments {census.symbol.nunique()} x gates {census.gate.nunique()})")
    for arm in ("iid", "dayblock"):
        keep = full[full[f"{arm}_bhz"]]
        syn = keep[keep.symbol.isin(SYNTH)]
        print(f"{arm}: BH q<0.10 keeps {len(keep)} of {len(full)}, "
              f"{len(syn)} of them on generated markets; "
              f"rank-p floor {full[arm + '_p'].min():.3f}")
        if len(keep):
            top = keep.reindex(keep[f"{arm}_z"].abs().sort_values(
                ascending=False).index).head(12)
            print(top[["symbol", "tf", "window", "gate", "letter", "n",
                       f"{arm}_ratio", f"{arm}_z"]].round(3).to_string(index=False))

    line("5. CENSUS - how the i.i.d. gap survives the day-block shuffle")
    for gate in ("strict", "loose"):
        sub = census[census.gate == gate]
        both = sub.groupby(sub.symbol.isin(SYNTH)).apply(
            lambda g: pd.Series({
                "cells": len(g),
                "median iid ratio": g.iid_ratio.median(),
                "median dayblock ratio": g.dayblock_ratio.median(),
                "mean |iid z|": g.iid_z.abs().mean(),
                "mean |dayblock z|": g.dayblock_z.abs().mean(),
            }), include_groups=False)
        both.index = ["traded", "generated"]
        print(f"\n-- gate {gate} --")
        print(both.round(3).to_string())

    line("6. TRANSITIONS - mutual information against its own label permutation")
    tr = trans[trans.gate == "strict"].copy()
    tr["excess"] = tr.mi - tr.mi_perm
    print(tr.groupby(["tf", "window"]).agg(
        cells=("mi", "size"), n=("n", "mean"), mi=("mi", "mean"),
        mi_perm=("mi_perm", "mean"), excess=("excess", "mean"),
        p_lt_05=("perm_p", lambda s: float((s < 0.05).mean())),
        mi_iid=("mi_iid", "mean")).round(4).to_string())
    print(f"\ncells with perm p<0.05: {int((trans.perm_p < 0.05).sum())} of "
          f"{len(trans)}, chance gives {0.05 * len(trans):.1f}")
    print(f"BH q<0.10 on the permutation p: {int(trans.perm_bh.sum())}")
    print("\n-- per instrument at the headline cell --")
    one = trans[(trans.tf == TF) & (trans.window == WIN) & (trans.gate == "strict")]
    print(one[["symbol", "n", "mi", "mi_perm", "perm_p", "mi_iid", "iid_p",
               "mi_dayblock"]].round(4).to_string(index=False))

    line("7. VOLATILITY - the headline cell, per instrument and letter")
    v = vol[(vol.tf == TF) & (vol.window == WIN) & (vol.gate == GATE) & (vol.k == K)]
    print("-- pooled by letter, traded panel --")
    tp = v[v.symbol.isin(traded)].groupby("letter").agg(
        n=("n", "sum"), rv=("rv", "mean"), placebo=("rv_placebo", "mean"),
        d_rv=("d_rv", "mean"), d_twin=("d_rv_twin", "mean"),
        d_quiet=("d_rv_quiet", "mean"), impulse=("impulse_share", "mean"))
    print(tp.reindex(list(LETTERS)).round(4).to_string())
    print("\n-- pooled by letter, generated markets --")
    sp = v[v.symbol.isin(SYNTH)].groupby("letter").agg(
        n=("n", "sum"), d_rv=("d_rv", "mean"), d_twin=("d_rv_twin", "mean"))
    print(sp.reindex(list(LETTERS)).round(4).to_string())
    print("\n-- W against M, per instrument --")
    wm = v[v.letter.isin(["W", "M"])].pivot_table(
        index="symbol", columns="letter",
        values=["n", "rv", "rv_placebo", "d_rv", "d_lo", "d_hi"])
    wm[("gap", "W-M")] = wm[("d_rv", "W")] - wm[("d_rv", "M")]
    print(wm.round(4).to_string())
    print("\n-- every letter, per instrument, d_rv and its interval --")
    print(v[["symbol", "letter", "n", "placebo_n", "rv", "rv_placebo", "d_rv",
             "d_lo", "d_hi", "p", "d_rv_twin"]].round(4).to_string(index=False))

    line("8. VOLATILITY - BH over the whole conditional surface")
    vv = vol.copy()
    print(f"cells: {len(vv)}  gates {sorted(vv.gate.unique())}  k {sorted(vv.k.unique())}")
    keep = vv[vv.bh]
    print(f"BH q<0.10 keeps {len(keep)}, {int(keep.symbol.isin(SYNTH).sum())} on "
          f"generated markets; of those kept, {int((keep.n < 100).sum())} have n<100")
    big = keep[keep.n >= 100]
    if len(big):
        print(big.reindex(big.d_rv.abs().sort_values(ascending=False).index).head(15)[
            ["symbol", "tf", "window", "gate", "letter", "k", "n", "d_rv", "d_lo",
             "d_hi", "p", "d_rv_twin"]].round(4).to_string(index=False))
    line("8b. VOLATILITY - the spread of d_rv across letters, per instrument")
    for gate in sorted(vol.gate.unique()):
        sub = vol[(vol.tf == TF) & (vol.window == WIN) & (vol.gate == gate)
                  & (vol.k == K) & (vol.n >= 100)]
        if sub.empty:
            continue
        rng = sub.groupby("symbol").agg(
            letters=("letter", "size"), min_d=("d_rv", "min"),
            max_d=("d_rv", "max"), sd_d=("d_rv", "std"),
            mean_twin_sd=("d_rv_twin", "std"))
        print(f"\n-- gate {gate} --")
        print(rng.round(4).to_string())

    line("9. DIRECTION - the trade arm, expected null, at the headline cell")
    d = dirs[(dirs.tf == TF) & (dirs.window == WIN) & (dirs.gate == GATE)
             & (dirs.k == K)]
    print(d[["symbol", "letter", "n", "side", "cont", "lo", "hi", "p", "cont_twin",
             "round_trip_quoted", "round_trip_stored", "net_quoted"]].round(4)
          .to_string(index=False))
    print("\n-- pooled by letter, traded panel --")
    print(d[d.symbol.isin(traded)].groupby("letter").agg(
        n=("n", "sum"), cont=("cont", "mean"), twin=("cont_twin", "mean"),
        cost=("round_trip_quoted", "mean"), net=("net_quoted", "mean")
    ).reindex(list(LETTERS)).round(4).to_string())

    line("10. DIRECTION - the barrier arm: P(+2R before -1R) against 1/3")
    b = dirs[dirs.k == -1]
    print(b.groupby(b.symbol.isin(SYNTH)).agg(
        cells=("cont", "size"), n=("n", "sum"), hit=("cont", "mean"),
        twin=("cont_twin", "mean"), cost_r=("round_trip_quoted", "mean"),
        net=("net_quoted", "mean")).round(4).to_string())
    print("\n-- per instrument, pooled over letters --")
    print(b.groupby("symbol").agg(
        n=("n", "sum"), hit=("cont", "mean"), twin=("cont_twin", "mean"),
        cost_r=("round_trip_quoted", "mean"), net=("net_quoted", "mean")
    ).round(4).to_string())
    print("\n-- per letter, traded panel --")
    print(b[b.symbol.isin(traded)].groupby("letter").agg(
        n=("n", "sum"), hit=("cont", "mean"), twin=("cont_twin", "mean"),
        net=("net_quoted", "mean")).reindex(list(LETTERS)).round(4).to_string())

    line("11. DIRECTION - BH over the whole surface, and the cost line")
    print(f"cells: {len(dirs)}; BH q<0.10 keeps {int(dirs.bh.sum())}, "
          f"{int(dirs[dirs.bh].symbol.isin(SYNTH).sum())} on generated markets")
    live = dirs[(dirs.k > 0) & (dirs.n >= 100)]
    print(f"cells with n>=100: {len(live)}; positive net of the quoted round trip: "
          f"{int((live.net_quoted > 0).sum())}; positive net of the stored column: "
          f"{int((live.cont - live.round_trip_stored > 0).sum())}")
    print(live.groupby(live.symbol.isin(SYNTH)).agg(
        cells=("cont", "size"), quoted=("round_trip_quoted", "mean"),
        stored=("round_trip_stored", "mean"),
        pos_quoted=("net_quoted", lambda s: float((s > 0).mean()))).round(4).to_string())


if __name__ == "__main__":
    main()
