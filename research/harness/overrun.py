"""Why a stop costs more than the risk it was sized for, and whether placement helps.

Stopped trades cost about 1.05R against the 1.00R they were sized for, and the
decomposition puts most of it on the way out: entry slippage averages +0.025R,
exit slippage +0.062R. The exit half has been treated as unfixable - a broker
stop is a market order once triggered, so it fills through the spread and any
gap, and that is what a stop is.

That is true about *mechanism* and does not settle whether **placement**
matters. Two things could:

* **Width.** Slippage is a distance in price. The same distance is a smaller
  share of a wide stop than a narrow one, so the overrun in R should fall as
  the stop widens - which would make `stop_hold_scaling` a fix for this and
  not only for being stopped by noise.
* **Position relative to the level's own liquidity.** A stop resting where
  other stops rest gets filled into whatever runs them. `sweep_high` and
  `sweep_low` are where the level's zone ends, and a stop inside that band is
  in the crowd; one beyond it is not.

Both are measurable from what the journal already holds.

Usage: python -m research.harness.overrun [journal.db]
"""

import json
import sqlite3
import sys


def load(db):
    con = sqlite3.connect(db)
    q = "select context from entries where actor='trading' and kind='outcome'"
    out = []
    for (ctx,) in con.execute(q):
        d = json.loads(ctx or "{}")
        if d.get("exit_kind") != "stop":
            continue
        risk = d.get("risk_price")
        entry, stop, exit_at = d.get("entry"), d.get("stop"), d.get("exit")
        if not risk or None in (entry, stop, exit_at):
            continue
        sign = 1.0 if d.get("side") == "buy" else -1.0
        row = {
            # How far past the placed stop it actually filled, in units of the
            # trade's own risk.
            "past": (float(stop) - float(exit_at)) * sign / float(risk),
            "risk_price": float(risk),
            "vol_bps": d.get("vol_bps"),
            "entry": float(entry),
            "stop": float(stop),
            "sweep_high": d.get("sweep_high"),
            "sweep_low": d.get("sweep_low"),
            "side": d.get("side"),
            "feed": d.get("feed"),
        }
        # The stop's width in volatility units, which is the comparable figure
        # across instruments.
        if row["vol_bps"]:
            unit = float(entry) * float(row["vol_bps"]) / 10_000.0
            row["stop_vol"] = float(risk) / unit if unit else None
        else:
            row["stop_vol"] = None
        out.append(row)
    return out


def beyond_the_crowd(row):
    """True when the stop sits outside the level's own sweep band."""
    high, low = row.get("sweep_high"), row.get("sweep_low")
    if not isinstance(high, int | float) or not isinstance(low, int | float):
        return None
    return not (float(low) <= row["stop"] <= float(high))


def mean(values):
    return sum(values) / len(values) if values else 0.0


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    print(f"{len(rows)} stopped trades with a placed stop and an exit\n")
    if len(rows) < 12:
        print("not enough to say anything")
        return

    print(f"mean overrun past the stop: {mean([r['past'] for r in rows]):+.3f}R\n")

    wide = [r for r in rows if r["stop_vol"] is not None]
    if len(wide) >= 12:
        wide.sort(key=lambda r: r["stop_vol"])
        half = len(wide) // 2
        narrow, broad = wide[:half], wide[half:]
        print("does a wider stop overrun less, in R?")
        at = wide[half]["stop_vol"]
        print(
            f"  narrower than {at:.2f}v: {mean([r['past'] for r in narrow]):+.3f}R"
            f"  (n={len(narrow)})"
        )
        print(f"  wider:                {mean([r['past'] for r in broad]):+.3f}R  (n={len(broad)})")
        print("  a fixed price slippage is a smaller share of a wider stop, so")
        print("  this falling would make stop_hold_scaling a fix for the overrun too")

    placed = [(beyond_the_crowd(r), r["past"]) for r in rows]
    inside = [p for out, p in placed if out is False]
    outside = [p for out, p in placed if out is True]
    if min(len(inside), len(outside)) >= 5:
        print("\ndoes a stop beyond the level's sweep band fill better?")
        print(f"  inside the band:  {mean(inside):+.3f}R  (n={len(inside)})")
        print(f"  beyond it:        {mean(outside):+.3f}R  (n={len(outside)})")
    else:
        print(f"\nsweep band: too few on one side (inside {len(inside)}, beyond {len(outside)})")


if __name__ == "__main__":
    main()
