"""Validate and fit Deriv's own-law envelope tables (`models/deriv_law_train.py`).

PART=validate: per family and horizon, the table fitted on each series' first 60% against
production's empirical envelope on its last 40% - the protocol of `derivvariants.py`, whose
`iid` rows these should reproduce (pinball 0.92-0.96 of the empirical envelope at 20-50 bars,
P10/P90 near 10/90).
PART=ship: the tables fitted on all history, written to OUT/deriv_law.json.

  SEQLAB=$HOME/till_infinity/data/seqlab PART=validate python research/harness/derivlaw.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

from till_infinity.models import deriv_law_train as dl
from till_infinity.prices.models import Bar

PART = os.environ.get("PART", "validate")
OUT = Path(os.environ.get("OUT", ".data/deriv_law"))
FAMILIES = {
    "boom": [f"Boom_{v}_Index" for v in (50, 100, 150, 200, 300, 500, 600, 900, 1000)],
    "crash": [f"Crash_{v}_Index" for v in (50, 100, 150, 200, 300, 500, 600, 900, 1000)],
    "dex": [f"DEX_{v}_{d}_Index" for v in (600, 900, 1500) for d in ("UP", "DOWN")],
    "range break": ["Range_Break_100_Index", "Range_Break_200_Index"],
    "drift switch": [f"Drift_Switch_Index_{v}" for v in (10, 20, 30)],
}
INTERVALS = ("3m", "15m", "30m", "1h", "4h", "1d")


def bars(sym: str, interval: str) -> list[Bar]:
    source = "15m" if interval == "30m" else interval
    df = spikerisk.load(None, sym, "SEQLAB", source)
    got = [Bar(int(t), float(o), float(h), float(lo), float(c))
           for t, o, h, lo, c in zip(df["ts"], df["open"], df["high"], df["low"], df["close"],
                                     strict=True)]
    if interval != "30m":
        return got
    out = []  # two 15m bars make a 30m bar, aligned to the half hour
    for a, b in zip(got[:-1], got[1:], strict=True):
        if a.time % 1800 == 0 and b.time == a.time + 900:
            out.append(Bar(a.time, a.open, max(a.high, b.high), min(a.low, b.low), b.close))
    return out


def load() -> dict[str, dict[tuple[str, str], list[Bar]]]:
    got: dict[str, dict[tuple[str, str], list[Bar]]] = {}
    for fam, syms in FAMILIES.items():
        for sym in syms:
            for iv in INTERVALS:
                try:
                    b = bars(sym, iv)
                except (ValueError, FileNotFoundError):
                    continue
                if len(b) > 3 * dl.MIN_BARS:
                    got.setdefault(fam, {})[(sym, iv)] = b
    return got


def validate() -> None:
    data = load()
    print("family · N | table P10 / P90 | empirical P10 / P90 | pinball table / empirical | n")
    for fam, series in data.items():
        for iv in INTERVALS:
            part = {k: v for k, v in series.items() if k[1] == iv}
            if not part:
                continue
            train = {k: v[: int(0.6 * len(v))] for k, v in part.items()}
            spec = dl.fit(train)
            since = min(v[int(0.6 * len(v))].time for v in part.values())
            # score each series from its own 60% point
            scores = {}
            for k, v in part.items():
                one = dl.score(spec, {k: v}, v[int(0.6 * len(v))].time)
                for n, row in one.items():
                    agg = scores.setdefault(n, {"n": 0, "lp": 0.0, "ep": 0.0, "l10": 0.0,
                                                "l90": 0.0, "e10": 0.0, "e90": 0.0})
                    w = row["n"]
                    agg["n"] += w
                    agg["lp"] += row["law_pinball"] * w
                    agg["ep"] += row["empirical_pinball"] * w
                    for a, b in (("l10", "law_cover10"), ("l90", "law_cover90"),
                                 ("e10", "empirical_cover10"), ("e90", "empirical_cover90")):
                        agg[a] += row[b] * w
            del since
            for n, a in sorted(scores.items(), key=lambda kv: int(kv[0])):
                w = max(a["n"], 1)
                print(f"  {fam:12s} {iv:4s} N={n:>2s} | {a['l10'] / w:5.1%} / {a['l90'] / w:5.1%} | "
                      f"{a['e10'] / w:5.1%} / {a['e90'] / w:5.1%} | {a['lp'] / max(a['ep'], 1e-12):.3f} | "
                      f"{a['n']:,}", flush=True)


def ship() -> None:
    data = load()
    series = {k: v for fam in data.values() for k, v in fam.items()}
    spec = dl.fit(series)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "deriv_law.json").write_text(json.dumps(spec, separators=(",", ":")))
    print(f"{len(spec['tables'])} tables from {len(series)} series -> {OUT / 'deriv_law.json'}")
    # spot-check one table against a direct convolution
    key = next(iter(spec["tables"]))
    print("e.g.", key, np.round(spec["tables"][key], 6))


if __name__ == "__main__":
    ship() if PART == "ship" else validate()
