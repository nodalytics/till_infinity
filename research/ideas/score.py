"""Score the imported ideas: every cell against its coin twin and the walks, deflated.

A cell is (setup, tag, exit, family, interval). It passes when, with n >= 30:
  - its net R a trade is above zero in both halves of its period,
  - it beats its coin twin (same fills, random side) with a day-bootstrap p < 0.05 after
    Benjamini-Hochberg across every cell scored,
  - the same rule on the walks earns less than half of it.
Reported alongside: hit rate, P(R >= 4) and P(R >= 10) - how often a trade pays 4R or 10R - and
the same for the coin and the walks, so a fat right tail is seen whether or not it pays on average.

  OUT=... python research/ideas/score.py
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(os.environ.get("OUT", ".data/ideas"))
KEYS = ["setup", "tag", "exit", "family", "interval"]
JUMPY = ("Boom", "Crash", "Jump", "Range Break")  # bar fills miss their jumps: ticks or nothing


def boot_p(a: pd.DataFrame, b: pd.DataFrame, rng, n=400) -> float:
    """P(mean(a) - mean(b) <= 0) over a bootstrap of days."""
    da = {d: g["R"].to_numpy() for d, g in a.groupby("day")}
    db = {d: g["R"].to_numpy() for d, g in b.groupby("day")}
    days = np.array(sorted(set(da) | set(db)))
    if len(days) < 10:
        return 1.0
    diffs = np.empty(n)
    for k in range(n):
        pick = rng.choice(days, len(days))
        x = np.concatenate([da[d] for d in pick if d in da] or [np.zeros(1)])
        y = np.concatenate([db[d] for d in pick if d in db] or [np.zeros(1)])
        diffs[k] = x.mean() - y.mean()
    return float((diffs <= 0).mean())


def bh(p: np.ndarray) -> np.ndarray:
    m = len(p)
    order = np.argsort(p)
    q = np.empty(m)
    q[order] = np.minimum.accumulate((p[order] * m / np.arange(1, m + 1))[::-1])[::-1]
    return np.minimum(q, 1.0)


def main():
    df = pd.read_pickle(OUT / "trades.pkl.gz")  # our own run's output, written by run.py
    df["tag"] = df["tag"].fillna("").replace("nan", "")
    df["day"] = (df["entry_ts"] // 86400).astype(int)
    # Deriv's jump instruments are scored apart: bar fills miss their jumps, so they cannot pass
    # here, and pooled with the smooth indices they would decide the Deriv cells.
    jumpy = df["sym"].str.contains("|".join(JUMPY))
    df.loc[jumpy & (df["family"] == "deriv"), "family"] = "deriv_jump"
    real, coin, walk = (df[df["kind"] == k] for k in ("real", "coin", "walk"))
    wk = walk.groupby(["setup", "tag", "exit", "interval"])["R"].agg(["mean", "size"])
    w4 = walk.groupby(["setup", "tag", "exit", "interval"])["R"].apply(lambda r: (r >= 4).mean())
    rng = np.random.default_rng(11)
    cells = []
    cg = dict(tuple(coin.groupby(KEYS)))
    for key, g in real.groupby(KEYS):
        if len(g) < 30:
            continue
        g = g.sort_values("entry_ts")
        mid = g["entry_ts"].median()
        c = cg.get(key)
        wkey = (key[0], key[1], key[2], key[4])
        jumpy = g["sym"].str.contains("|".join(JUMPY)).mean()
        cells.append(dict(
            **dict(zip(KEYS, key)), n=len(g), syms=g["sym"].nunique(), R=g["R"].mean(),
            first=g.loc[g["entry_ts"] < mid, "R"].mean(), second=g.loc[g["entry_ts"] >= mid, "R"].mean(),
            hit=(g["R"] > 0).mean(), p4=(g["R"] >= 4).mean(), p10=(g["R"] >= 10).mean(),
            avg_win=g.loc[g["R"] > 0, "R"].mean(), coin_R=c["R"].mean() if c is not None else np.nan,
            coin_p4=(c["R"] >= 4).mean() if c is not None else np.nan,
            walk_R=wk["mean"].get(wkey, np.nan) if wk["size"].get(wkey, 0) >= 30 else np.nan,
            walk_n=wk["size"].get(wkey, 0),
            walk_p4=w4.get(wkey, np.nan), jumpy_share=jumpy,
            p=boot_p(g, c, rng) if c is not None and len(c) >= 30 else 1.0))
    cells = pd.DataFrame(cells)
    cells["q"] = bh(cells["p"].to_numpy())
    cells["beats_coin"] = cells["q"] < 0.05
    cells["passes"] = (cells["beats_coin"] & (cells["first"] > 0) & (cells["second"] > 0) & (cells["R"] > 0)
                       & ~(cells["walk_R"] >= 0.5 * cells["R"]) & (cells["jumpy_share"] < 0.5))
    cells = cells.sort_values(["passes", "q", "R"], ascending=[False, True, False])
    cells.to_csv(OUT / "cells.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    show = ["setup", "tag", "exit", "family", "interval", "n", "R", "first", "second", "hit", "p4", "p10",
            "coin_R", "coin_p4", "walk_R", "walk_p4", "q", "passes", "jumpy_share"]
    print(f"{len(cells)} cells, {int(cells['passes'].sum())} pass, "
          f"{int(cells['beats_coin'].sum())} beat their coin, {int((cells['R'] > 0).sum())} net positive")
    print(cells[show].head(40).round(3).to_string(index=False))
    by = cells.groupby("setup").agg(cells=("n", "size"), trades=("n", "sum"), mean_R=("R", "mean"),
                                    best_R=("R", "max"), coin_R=("coin_R", "mean"), walk_R=("walk_R", "mean"),
                                    p4=("p4", "mean"), coin_p4=("coin_p4", "mean"), walk_p4=("walk_p4", "mean"),
                                    passes=("passes", "sum"))
    print(by.sort_values("mean_R", ascending=False).round(3).to_string())
    by.to_csv(OUT / "by_setup.csv")


if __name__ == "__main__":
    main()
