"""Would inverting the trade on a high break estimate have helped?

`inverse` inverts every call unconditionally - a control, expected to lose,
built to separate "the direction is wrong" from "the execution loses it".

The informed version is to invert **selectively**: a level call says price goes
up from support, and it is wrong exactly when the level gives way. So
`break_probability` is a principled trigger for flipping a trade rather than
refusing it - and unlike a refusal, an inverted trade still produces an
outcome, which is evidence.

Testable before anything is built. Fit the break model walk-forward, bucket the
touches by what it said, and ask what actually happened in each bucket.
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics as st

JOURNAL = "file:/app/.data/journal/journal.db?mode=ro"
LOW, HIGH = 300.0, 1800.0
HELD, BROKE = ("reject", "backcheck", "trap"), ("break",)
FEATURES = ("approach_vol", "depth_vol")


def rows() -> list[dict]:
    conn = sqlite3.connect(JOURNAL, uri=True)
    out = []
    for (blob,) in conn.execute(
        "SELECT context FROM entries WHERE actor='structures' AND kind='outcome'"
        " ORDER BY time ASC LIMIT 400000"
    ):
        try:
            d = json.loads(blob or "{}")
        except (ValueError, TypeError):
            continue
        outcome, secs = str(d.get("outcome") or ""), d.get("seconds")
        if outcome not in HELD + BROKE or secs is None:
            continue
        try:
            secs, push = float(secs), abs(float(d.get("push_vol") or 0.0))
        except (TypeError, ValueError):
            continue
        if not (LOW <= secs < HIGH):
            continue
        got = {"broke": outcome in BROKE, "push": push}
        for n in FEATURES:
            try:
                got[n] = float(d.get(n) or 0.0)
            except (TypeError, ValueError):
                got[n] = 0.0
        out.append(got)
    return out


def walk(seen: list[dict], rate: float = 0.05) -> list[tuple[float, dict]]:
    """Predict-then-learn over the stream, oldest first. No look-ahead."""
    mean = dict.fromkeys(FEATURES, 0.0)
    m2 = dict.fromkeys(FEATURES, 0.0)
    w = dict.fromkeys(FEATURES, 0.0)
    bias, n = 0.0, 0.0
    out = []
    for r in seen:
        n += 1.0
        z = {}
        for f in FEATURES:
            delta = r[f] - mean[f]
            mean[f] += delta / n
            m2[f] += delta * (r[f] - mean[f])
            sd = math.sqrt(m2[f] / n) if n > 1 else 0.0
            z[f] = (r[f] - mean[f]) / sd if sd > 1e-9 else 0.0
        raw = bias + sum(w[f] * z[f] for f in FEATURES)
        p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, raw))))
        if n > 500:  # warm
            out.append((p, r))
        err = (1.0 if r["broke"] else 0.0) - p
        for f in FEATURES:
            w[f] += rate * err * z[f]
        bias += rate * err
    return out


def main() -> None:
    seen = rows()
    scored = walk(seen)
    print(f"{len(seen)} touches, {len(scored)} scored after warm-up\n")
    if len(scored) < 500:
        print("too few")
        return

    scored.sort(key=lambda kv: kv[0])
    step = len(scored) // 5
    print(f"{'break estimate':16s} {'n':>6s} {'actually broke':>15s} {'E|push|':>9s}")
    for i in range(5):
        cut = scored[i * step : (i + 1) * step] if i < 4 else scored[i * step :]
        lo, hi = cut[0][0], cut[-1][0]
        broke = sum(1 for _p, r in cut if r["broke"]) / len(cut)
        push = st.median(r["push"] for _p, r in cut)
        print(f"{lo:.2f}-{hi:.2f}      {len(cut):6d} {broke:15.1%} {push:9.2f}")

    top = scored[4 * step :]
    bottom = scored[:step]
    tb = sum(1 for _p, r in top if r["broke"]) / len(top)
    bb = sum(1 for _p, r in bottom if r["broke"]) / len(bottom)
    print(f"\ntop fifth breaks {tb:.1%}, bottom fifth {bb:.1%}, spread {tb - bb:+.1%}")
    print()
    print("what inverting in the top fifth would be worth, as directional accuracy:")
    print(f"   taking the level's call there : {1 - tb:.1%} right")
    print(f"   inverting it there            : {tb:.1%} right")
    base = sum(1 for _p, r in scored if r["broke"]) / len(scored)
    print(f"   (the level's call overall     : {1 - base:.1%} right)")


if __name__ == "__main__":
    main()
