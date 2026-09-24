"""The three leads from `directional-questions.md`, on instruments they have never seen.

Each lead survived its own test at two to three standard errors, among dozens of cells, on
14 instruments at 15m/1h and 9 daily. That is exactly the profile of something chance
produces, and the cheapest decisive test is the same procedure on instruments the search
never touched. The lab's broker bars hold seven FX crosses that were in no earlier study,
with far more history than the original sample: 15m back to 2024, 1h to 2018, daily to 1993.

  lead 1  intraday short models at 1-5 hours      `horizons.run` at 15m and 1h
  lead 2  daily +3:-1 longs from the model's top  `questions.q4_asymmetric` on daily
  lead 3  daily pair-spread reversion at |z| > 2  `questions.q2_relative` on daily cross pairs

Unchanged code, unchanged thresholds, unchanged split (fit on each series' first 60% by
time, score on the last 40%, the two halves reported separately). A lead survives if it has
the same sign, a comparable size and both halves agreeing here. Anything else closes it.

Run on the lab (bars at $SEQLAB, the prices database only for the contagion join):
  ./.secrets/lab.sh run research/harness/oos.py SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=8
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import horizons
import questions
import spikerisk

# On the lab the prices database is data/prices.db; the loader reads SEQLAB and never opens it,
# but the harnesses open a connection first.
DB = os.environ.get("PRICES_DB", "data/prices.db")
for mod in (spikerisk, horizons, questions):
    mod.DB = DB
if not Path(DB).exists():
    sqlite3.connect(":memory:").close()
    for mod in (spikerisk, horizons, questions):
        mod.DB = ":memory:"

CROSSES = ["AUDJPY", "CHFJPY", "EURAUD", "EURCHF", "EURGBP", "EURJPY", "GBPJPY"]
UNSEEN = {"fx": [(c, "SEQLAB") for c in CROSSES]}
PAIRS = [("EURJPY", "GBPJPY", "fx"), ("AUDJPY", "CHFJPY", "fx"), ("EURCHF", "EURGBP", "fx")]


def main():
    print("=" * 110 + "\nLEAD 1 - intraday short models (original: +0.12 to +0.16R gross at 1-5h, both halves)")
    for interval in ("15m", "1h"):
        horizons.run(interval, UNSEEN)

    print("\n" + "=" * 110 + "\nLEAD 2 - daily +3:-1 longs (original: +0.10R net, t=2.9, model top 20%)")
    d, cols = horizons.build("1d", UNSEEN)
    d = d.drop(columns=[c for c in d.columns if "@" in c])
    X = d[cols].to_numpy(float)
    fut = questions.paths(d, 5)
    questions.q4_asymmetric(d, X, "1d", 5, fut, questions.event_masks(d, "1d"))

    print("\n" + "=" * 110 + "\nLEAD 3 - daily pair-spread reversion (original: +0.11R net, t=2.0)")
    questions.PAIRS["1d"] = PAIRS
    questions.VENUE["1d"].update({c: "SEQLAB" for c in CROSSES})
    questions.q2_relative("1d", 5)


if __name__ == "__main__":
    main()
