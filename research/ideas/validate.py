"""Score the frozen candidates (candidates.json) on their fresh instruments, one shot.

Reads the trades run.py wrote for the fresh symbols and judges each candidate cell by the rule
frozen in candidates.json: net R > 0 in both halves and beating its coin twin with a day-bootstrap
p < 0.05 after Benjamini-Hochberg across the candidates. Also reports P(R >= 4) and P(R >= 10).

  OUT=... python research/ideas/validate.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from score import boot_p, bh

HERE = Path(__file__).resolve().parent
OUT = Path(os.environ.get("OUT", ".data/ideas_fresh"))


def main():
    spec = json.loads((HERE / "candidates.json").read_text())
    df = pd.read_pickle(OUT / "trades.pkl.gz")  # our own run's output, written by run.py
    df["day"] = (df["entry_ts"] // 86400).astype(int)
    rng = np.random.default_rng(31)
    rows = []
    for c in spec["trade_candidates"]:
        m = ((df["setup"] == c["setup"]) & (df["exit"] == c["exit"]) & (df["interval"] == c["interval"])
             & (df["family"] == c["family"]))
        real, coin = df[m & (df["kind"] == "real")], df[m & (df["kind"] == "coin")]
        if len(real) < 20:
            rows.append(dict(**c, n=len(real), note="too few trades"))
            continue
        mid = real["entry_ts"].median()
        rows.append(dict(
            **c, n=len(real), syms=real["sym"].nunique(), R=real["R"].mean(),
            first=real.loc[real["entry_ts"] < mid, "R"].mean(), second=real.loc[real["entry_ts"] >= mid, "R"].mean(),
            hit=(real["R"] > 0).mean(), p4=(real["R"] >= 4).mean(), p10=(real["R"] >= 10).mean(),
            coin_R=coin["R"].mean(), positive_syms=float((real.groupby("sym")["R"].mean() > 0).mean()),
            p=boot_p(real, coin, rng) if len(coin) >= 20 else 1.0))
    out = pd.DataFrame(rows)
    ok = out["p"].notna() if "p" in out else pd.Series(False, index=out.index)
    out.loc[ok, "q"] = bh(out.loc[ok, "p"].to_numpy())
    out["survives"] = ok & (out.get("q", 1) < 0.05) & (out.get("first", 0) > 0) & (out.get("second", 0) > 0) \
        & (out.get("R", 0) > 0)
    out.to_csv(OUT / "validation.csv", index=False)
    pd.set_option("display.width", 250)
    print(out.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
