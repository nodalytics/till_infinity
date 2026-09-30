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


def cells(data) -> dict[tuple[str, str, int], dict]:
    """Per (family, interval, horizon): each series' table fitted on its first 60% and scored,
    with production's empirical envelope, on its last 40%, pooled over the cell's series."""
    out: dict[tuple[str, str, int], dict] = {}
    for fam, series in data.items():
        for key, v in series.items():
            cut = int(0.6 * len(v))
            spec = dl.fit({key: v[:cut]})
            for n, row in dl.score(spec, {key: v}, v[cut].time).items():
                a = out.setdefault((fam, key[1], int(n)), {"n": 0, "law_pinball": 0.0,
                                                         "empirical_pinball": 0.0})
                w = row["n"]
                a["n"] += w
                a["law_pinball"] += row["law_pinball"] * w
                a["empirical_pinball"] += row["empirical_pinball"] * w
                for k in ("law_cover10", "law_cover90", "empirical_cover10", "empirical_cover90"):
                    a[k] = a.get(k, 0.0) + row[k] * w
    for a in out.values():
        w = max(a["n"], 1)
        for k in ("law_cover10", "law_cover90", "empirical_cover10", "empirical_cover90"):
            a[k] /= w
    return out


def validate() -> None:
    got = cells(load())
    print("family · interval · N | table P10 / P90 | empirical P10 / P90 | pinball ratio | n | ships")
    for (fam, iv, n), a in sorted(got.items()):
        print(f"  {fam:12s} {iv:4s} N={n:>2d} | {a['law_cover10']:5.1%} / {a['law_cover90']:5.1%} | "
              f"{a['empirical_cover10']:5.1%} / {a['empirical_cover90']:5.1%} | "
              f"{a['law_pinball'] / max(a['empirical_pinball'], 1e-12):.3f} | {a['n']:,} | "
              f"{'yes' if dl.cell_passes(a) else 'no'}", flush=True)


def ship() -> None:
    """Tables fitted on all history, kept only in cells whose pooled 60/40 validation passes."""
    data = load()
    got = cells(data)
    passing = {cell for cell, a in got.items() if dl.cell_passes(a)}
    everything = {k: v for fam in data.values() for k, v in fam.items()}
    spec = dl.fit(everything)
    spec["tables"] = {
        k: t
        for k, t in spec["tables"].items()
        if (FAMILY_OF[dl.family_of(k.split("|")[0])], k.split("|")[1], int(k.split("|")[2]))
        in passing
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "deriv_law.json").write_text(json.dumps(spec, separators=(",", ":")))
    print(f"{len(spec['tables'])} tables from {len(everything)} series; "
          f"{len(passing)} of {len(got)} cells pass")
    for c in sorted(passing):
        print("  pass", c)


#: The trainer's family prefix -> this harness's family name.
FAMILY_OF = {"boom_": "boom", "crash_": "crash", "dex_": "dex", "range_break_": "range break",
             "drift_switch_": "drift switch"}


if __name__ == "__main__":
    ship() if PART == "ship" else validate()
