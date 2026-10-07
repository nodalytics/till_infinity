"""Sweep the zone rule's parameters, one at a time around the desk's setting.

Asked for 2026-10-07: "test different parameters". The point is **not** to pick
the best cell - a best-of-K on the data the rule was built on is worth nothing,
and this sweep has twenty-odd arms. The point is the shape:

  * a result that holds across a parameter's whole range is a property of the
    market; one that lives at a single value is a property of this sample
  * a parameter that changes the population by an order of magnitude without
    changing the result is not a filter on anything
  * a parameter the desk *gave* - the strong push, the full-range band, the
    body-edge line - is reported at its given value whatever the sweep says,
    with the alternative beside it rather than in place of it

Every arm is printed, nothing is selected, and the confirmation of whichever
setting the desk keeps happens once, on instruments the rule never saw.

  MT5BT_DB=... OUT=.data/zonesweep SYMBOLS=... python research/ideas/zone_sweep.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

OUT = Path(os.environ.get("OUT", ".data/zonesweep"))
DRAWS = 4000

#: The desk's setting as of 2026-10-07, after an afternoon of refinements. Every
#: value here was *given*, not fitted, which is why the sweep runs around it
#: rather than through it.
BASE = dict(ZONES="ob", PUSH_N="2", PUSH_BODY="0.70", PUSH_STRONG="1",
            ORIGIN_BODY="0.45", ORIGIN_COLOUR="0", ORIGIN_MAX="1.0", OB_BACK="0",
            OB_BAND="range", OB_LOOKBACK="20", OB_MINLEG="1.5", OB_CLIP="1.5", FRESH="1", QUIET="0", QUIET_SKIP="2",
            WICK_MIN="0.40", WINDOW="36", HOLD_DAYS="15")

#: One at a time, each with the reason it is in the sweep at all.
ARMS: list[tuple[str, dict[str, str], str]] = [
    ("base", {}, "the desk's setting"),
    ("push_weak", dict(PUSH_STRONG="0"), "close past the previous close, not its high"),
    ("push_n3", dict(PUSH_N="3"), "three impulsive candles"),
    ("push_n4", dict(PUSH_N="4"), "four"),
    ("push_body_60", dict(PUSH_BODY="0.60"), "a looser impulse"),
    ("push_body_80", dict(PUSH_BODY="0.80"), "a stricter one"),
    ("origin_colour", dict(ORIGIN_COLOUR="1"), "the order-block reading: the last candle against"),
    ("origin_body_0", dict(ORIGIN_BODY="0.0"), "any candle before the impulse, doji included"),
    ("origin_body_60", dict(ORIGIN_BODY="0.60"), "a solid-bodied zone candle"),
    ("origin_small", dict(ORIGIN_MAX="0.7"), "'normally a small candle', read strictly"),
    ("origin_any_size", dict(ORIGIN_MAX="9.9"), "no size test at all"),
    ("back_1", dict(OB_BACK="1"), "the origin may sit one bar behind the impulse"),
    ("back_2", dict(OB_BACK="2"), "or two"),
    ("back_3", dict(OB_BACK="3"), "or three"),
    ("back_5", dict(OB_BACK="5"), "or five - 'check backward too for more info'"),
    ("fresh_off", dict(FRESH="0"), "allow a zone already tested before it was known"),
    ("quiet_20", dict(QUIET="20"), "and nothing closed in the band for 20 bars before it"),
    ("quiet_40", dict(QUIET="40", QUIET_SKIP="5"), "40 bars, five of delivery ignored"),
    ("wick_30", dict(WICK_MIN="0.30"), "a shorter wick confirms"),
    ("wick_50", dict(WICK_MIN="0.50"), "a longer one"),
    ("window_12", dict(WINDOW="12"), "two days at 4h to react"),
    ("hold_5", dict(HOLD_DAYS="5"), "the desk's own holding period"),
    ("expire_100", dict(EXPIRE="100"), "the return must come sooner"),
]

#: The cell read out of each arm. `touch` is the zone with no confirmation at
#: all, `pin` the strict candlestick, `wick` the desk's looser one - so the
#: three rows price the confirmation itself.
TRIGGERS = ("touch", "pin", "wick")
FILTER, EXIT = "none", "opp"


def block_ci(values, days, draws=DRAWS, seed=5):
    """Mean with a day-block bootstrap interval. Trades share a day and a
    regime, so an IID interval here is far too narrow to mean anything."""
    values = np.asarray(values, float)
    if len(values) < 20:
        return (float(values.mean()) if len(values) else np.nan), np.nan, np.nan
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(np.asarray(days), return_inverse=True)
    sums = np.bincount(inv, weights=values, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    pick = rng.integers(0, len(uniq), size=(draws, len(uniq)))
    got = sums[pick].sum(axis=1) / np.maximum(cnts[pick].sum(axis=1), 1.0)
    return float(values.mean()), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def one(tag: str, over: dict[str, str]) -> pd.DataFrame | None:
    """Run `zones.py` once under `BASE | over` and read back its trades."""
    out = OUT / tag
    out.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(BASE)
    env.update(over)
    env.update(MODE="run", OUT=str(out),
               PYTHONPATH=os.pathsep.join([str(HERE), str(HERE.parent), str(HERE.parents[1])]))
    log = out / "run.log"
    with log.open("w") as fh:
        rc = subprocess.run([sys.executable, "-u", str(HERE / "zones.py")],
                            env=env, stdout=fh, stderr=subprocess.STDOUT).returncode
    path = out / "zone_trades.pkl.gz"
    if not path.exists():
        print(f"  {tag}: no trades at all (rc={rc}, see {log})", flush=True)
        return None
    if rc != 0:
        # The trades are written before the scoring, and a setting strict enough
        # to leave no cell with 30 trades used to take the scoring down with it.
        # The arm is still worth reading: "too rare to measure" is its result.
        print(f"  {tag}: scoring failed (rc={rc}) - reading the trades anyway", flush=True)
    return pd.read_pickle(path)


def summarise(tag: str, why: str, df: pd.DataFrame) -> list[dict]:
    """Per interval and trigger: the real arm, its flip, and the population."""
    rows = []
    real = df[~df["family"].str.startswith("deriv")]
    for iv in sorted(real["iv"].unique()):
        for trig in TRIGGERS:
            g = real[(real["iv"] == iv) & (real["trigger"] == trig)
                     & (real["filter"] == FILTER) & (real["exit"] == EXIT)]
            r = g[g["kind"] == "real"]
            if r.empty:
                continue
            m, lo, hi = block_ci(r["R"], r["day"])
            fl = g[g["kind"] == "flip"]
            fm, flo, fhi = block_ci(fl["R"], fl["day"]) if len(fl) else (np.nan,) * 3
            st = g[g["kind"] == "straight"]
            co = g[g["kind"] == "coin"]
            rows.append(dict(arm=tag, why=why, iv=iv, trigger=trig, n=len(r),
                             zones=int(r["sid"].nunique()) if "sid" in r else len(r),
                             long=float((r["side"] > 0).mean()), win=float((r["R"] > 0).mean()),
                             R=m, lo=lo, hi=hi,
                             coin=float(co["R"].mean()) if len(co) else np.nan,
                             straight=float(st["R"].mean()) if len(st) else np.nan,
                             flip=fm, flip_lo=flo, flip_hi=fhi))
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    only = os.environ.get("ARMS")
    arms = [a for a in ARMS if not only or a[0] in only.split(",")]
    rows: list[dict] = []
    for tag, over, why in arms:
        print(f"[{tag}] {why}  {over or '-'}", flush=True)
        df = one(tag, over)
        if df is None:
            continue
        got = summarise(tag, why, df)
        rows += got
        for r in got:
            print(f"    {r['iv']:>3} {r['trigger']:<6} n={r['n']:>5} long={r['long']:.0%} "
                  f"R={r['R']:+.3f} [{r['lo']:+.3f}, {r['hi']:+.3f}]  "
                  f"straight={r['straight']:+.3f} flip={r['flip']:+.3f}", flush=True)
    if not rows:
        print("nothing ran")
        return
    tab = pd.DataFrame(rows)
    tab.to_csv(OUT / "sweep.csv", index=False)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print("\n=== every arm, no selection ===")
    print(tab.drop(columns=["why"]).round(3).to_string(index=False))
    print(f"\n{len(tab)} cells over {tab['arm'].nunique()} arms. A best-of-{len(tab)} is not a "
          "result; read the columns for a plateau, not the maximum.")
    print(f"\nwritten: {OUT / 'sweep.csv'}")


if __name__ == "__main__":
    main()
