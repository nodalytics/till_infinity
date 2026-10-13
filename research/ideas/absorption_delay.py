"""How long does intra-bar absorption last, and does any horizon pay?

`statespace-orderflow-from-bars.md` found a real directional signal and closed
it on cost. Real markets close **nearer the middle of their range** than a
matched walk does, on 8 of 8 instruments, and that absorption continues one bar
into the future: imbalance gives a median AUC of **0.4843** and wick
**0.5181**, with 21 of 24 traded cells beating a block-shuffle null against 2
of 15 generated. It earns about **a quarter of a spread**.

Two independent arguments say the horizon is the lever rather than the
classifier.

**The cost arithmetic.** An AUC of 0.52 is a 4% edge on a move, so the edge is
4% of whatever room the horizon offers. Room grows with the horizon - roughly
as its square root for a diffusion - and **the spread does not grow at all**.
One round trip costs the same whether it is held an hour or a day.

**The loop framing.** `statespace-reading-into-tests.md` notes that absorbing
markets are a **balancing loop**, and a balancing loop has exactly two
parameters: a **gain** and a **delay**. This desk has measured the gain at a
delay of one bar and never swept the delay, which leaves the loop half
characterised.

So: the same features, against the sign of the return over 1, 2, 3, 4, 6, 8,
12, 24 and 48 bars.

## What would count

`edge x room` has to clear **two spreads**, not one, because entering and
leaving are both crossings. The quantity to watch is `net`, and the shape of
`AUC` against horizon is the more interesting output either way:

* if AUC decays as `1/sqrt(h)`, the edge is **flat** in basis points and no
  horizon pays - absorption is a one-bar mechanism and the room it opens is
  exactly offset by the signal it loses;
* if AUC decays more slowly, there is a horizon where it pays;
* if AUC decays faster, the one-bar result was the best case and the line is
  closed.

**The null has to be swept too.** A block shuffle at `h = 48` is not the same
test as at `h = 1`, because overlapping targets at a long horizon are strongly
serially correlated and inflate any AUC's spread. The null is recomputed per
horizon, and non-overlapping sampling is reported beside the overlapping one -
this desk has read a `z` of -3.2 off a driftless walk once already by letting
windows overlap 98%.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "40000"))
SEED = 20261013
DRAWS = int(os.environ.get("DRAWS", "24"))
HORIZONS = tuple(int(x) for x in os.environ.get("HORIZONS", "1,2,3,4,6,8,12,24,48").split(","))
TRADED = tuple(
    os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,USDCAD,AUDUSD,XAUUSD,XAGUSD,US_Oil").split(",")
)
GENERATED = tuple(
    os.environ.get("GENERATED", "Boom_500_Index,Step_Index_200,DEX_900_UP_Index").split(",")
)
#: A realistic round-trip cost in basis points where the cache reports zero.
#: The demo feed posts a zero spread for the majors, and reading that as free
#: is how a quarter-of-a-spread edge becomes a trade on paper.
ASSUMED_BP = {
    "EURUSD": 0.93,
    "GBPUSD": 1.20,
    "USDJPY": 1.00,
    "USDCAD": 1.50,
    "AUDUSD": 1.50,
    "XAUUSD": 1.20,
    "XAGUSD": 5.00,
    "US_Oil": 5.00,
}


def load(name: str):
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
        spread = (
            np.asarray(bundle["spread"], dtype=float)[order] if "spread" in bundle else None
        )
    keep = (got["high"] > got["low"]) & (got["low"] > 0)
    if keep.sum() < 4000:
        return None
    out = {k: v[keep] for k, v in got.items()}
    if len(out["close"]) > LIMIT:
        out = {k: v[-LIMIT:] for k, v in out.items()}
        spread = spread[keep][-LIMIT:] if spread is not None else None
    elif spread is not None:
        spread = spread[keep]
    return out, spread


def roc(scores, labels) -> float:
    import numpy as np

    scores = np.asarray(scores, dtype=float)
    labels = np.asarray(labels, dtype=float)
    positives = labels.sum()
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return float("nan")
    order = np.argsort(scores)
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    return float(
        (ranks[labels > 0].sum() - positives * (positives + 1) / 2) / (positives * negatives)
    )


def block_shuffled(values, rng, blocks: int = 24):
    import numpy as np

    values = np.asarray(values, dtype=float)
    size = max(len(values) // blocks, 1)
    pieces = [values[i : i + size] for i in range(0, len(values), size)]
    order = rng.permutation(len(pieces))
    return np.concatenate([pieces[i] for i in order])[: len(values)]


def cost_bp(name: str, closes, spreads) -> float:
    """One **round trip** in basis points, never zero for a traded market."""
    import numpy as np

    if spreads is not None and len(spreads) > 2 and float(np.median(spreads)) > 0:
        gaps = np.abs(np.diff(np.unique(closes)))
        gaps = gaps[gaps > 0]
        if len(gaps):
            point = 10.0 ** round(math.log10(float(gaps.min())))
            return 2.0 * 1e4 * float(np.median(spreads)) * point / float(np.median(closes))
    return ASSUMED_BP.get(name, 2.0)


def main() -> None:
    import numpy as np

    print(f"frame {FRAME}  horizons {HORIZONS}  draws {DRAWS}\n")
    print(
        "`room` is the median absolute return over the horizon in basis points,\n"
        "which is what there is to win. `edge` is |2 AUC - 1| of it. `cost` is\n"
        "one round trip, and it does **not** grow with the horizon - which is\n"
        "the whole reason to sweep it.\n"
    )
    picker = np.random.default_rng(SEED)
    rows = []
    for name in TRADED + GENERATED:
        got = load(name)
        if got is None:
            print(f"{name}: no usable bars")
            continue
        bars, spreads = got
        opens, highs, lows, closes = (bars[k] for k in ("open", "high", "low", "close"))
        span = highs - lows
        logs = np.log(closes)
        cost = cost_bp(name, closes, spreads)
        features = {
            "imbalance": (closes - opens) / span,
            "wick": ((highs - closes) - (closes - lows)) / span,
        }
        made = name in GENERATED
        print(f"\n{'*' + name if made else name}   round trip {cost:.2f} bp")
        print(
            f"  {'feature':<11}{'h':>4}{'AUC':>9}{'null hi':>9}{'beats':>7}"
            f"{'room bp':>9}{'edge bp':>9}{'net bp':>9}{'non-ov AUC':>12}"
        )
        for label, raw in features.items():
            for horizon in HORIZONS:
                ahead = logs[horizon:] - logs[:-horizon]
                feature = raw[: len(ahead)]
                use = np.isfinite(feature) & np.isfinite(ahead)
                x, y = feature[use], (ahead[use] > 0).astype(float)
                if len(x) < 2000 or y.std() == 0:
                    continue
                auc = roc(x, y)
                # **Recomputed per horizon**: overlapping targets at h=48 are
                # strongly serially correlated and inflate any AUC's spread,
                # so a null built at h=1 would be far too tight here.
                draws = [roc(block_shuffled(x, picker), y) for _ in range(DRAWS)]
                top = max(abs(d - 0.5) for d in draws) + 0.5
                beats = abs(auc - 0.5) > (top - 0.5)
                # Non-overlapping: one observation per horizon, which is the
                # honest sample size and the arm that caught a z of -3.2 on a
                # driftless walk when windows were allowed to overlap 98%.
                thin_x, thin_y = x[::horizon], y[::horizon]
                thin = roc(thin_x, thin_y) if len(thin_x) > 500 and thin_y.std() > 0 else float("nan")
                room = 1e4 * float(np.median(np.abs(ahead[use])))
                edge = abs(2.0 * auc - 1.0) * room
                print(
                    f"  {label:<11}{horizon:>4}{auc:>9.4f}{top:>9.4f}"
                    f"{'yes' if beats else 'no':>7}{room:>9.2f}{edge:>9.2f}"
                    f"{edge - cost:>+9.2f}{thin:>12.4f}"
                )
                rows.append(
                    {
                        "name": name,
                        "made": made,
                        "feature": label,
                        "h": horizon,
                        "auc": auc,
                        "thin": thin,
                        "beats": beats,
                        "room": room,
                        "edge": edge,
                        "net": edge - cost,
                    }
                )

    if not rows:
        return
    live = [r for r in rows if not r["made"]]
    print("\n" + "=" * 110)
    print("does AUC decay faster or slower than the room grows")
    print("=" * 110)
    print(
        "If AUC's distance from 0.5 decays as 1/sqrt(h) the edge is flat in\n"
        "basis points and no horizon can pay. Slower, and one can.\n"
    )
    print(f"{'feature':<11}{'h':>4}{'median AUC':>12}{'|2A-1|':>9}{'vs h=1':>9}{'sqrt(h) says':>14}{'median room':>13}{'median edge':>13}{'median net':>12}{'beats':>7}")
    for label in ("imbalance", "wick"):
        first = None
        for horizon in HORIZONS:
            here = [r for r in live if r["feature"] == label and r["h"] == horizon]
            if not here:
                continue
            auc = statistics.median(r["auc"] for r in here)
            strength = abs(2 * auc - 1)
            if first is None:
                first = strength
            print(
                f"{label:<11}{horizon:>4}{auc:>12.4f}{strength:>9.4f}"
                f"{strength / first if first else float('nan'):>9.2f}"
                f"{1 / math.sqrt(horizon):>14.2f}"
                f"{statistics.median(r['room'] for r in here):>13.2f}"
                f"{statistics.median(r['edge'] for r in here):>13.2f}"
                f"{statistics.median(r['net'] for r in here):>12.2f}"
                f"{sum(1 for r in here if r['beats'])}/{len(here):<6}"
            )
    best = max(live, key=lambda r: r["net"])
    paying = [r for r in live if r["net"] > 0 and r["beats"]]
    print(
        f"\nbest single cell: {best['name']} {best['feature']} at h={best['h']}, "
        f"net {best['net']:+.2f} bp\n"
        f"cells that both beat their null and clear their cost: "
        f"{len(paying)} of {len(live)}"
    )
    made = [r for r in rows if r["made"]]
    if made:
        print(
            f"generated feeds clearing both: "
            f"{sum(1 for r in made if r['net'] > 0 and r['beats'])} of {len(made)}"
        )


if __name__ == "__main__":
    main()
