"""Can order flow be reverse-engineered from bars, and is any of it directional?

A bar is a summary of the order flow that happened inside it, so the question
is how much of that flow a summary retains. Three things make this worth
asking here rather than taking a published proxy on faith.

**There is already a measurement that says flow is recoverable.**
`statespace-activity-on-q.md` swept the exponent relating a bar's variance to
its tick count and found **2**, not 1, with a turn on both sides on every
traded instrument. Exponent 1 is what independent increments give - a bar sums
`n` of them so its variance scales with `n`. Exponent 2 means the **standard
deviation** scales with `n`, so the bar's move grows linearly in ticks. Linear
growth is a directional **run**; the square root is independence. That is an
order-flow statement, and it came out of OHLCV alone.

**Most OHLC flow proxies would read the same on a random walk**, because they
are functions of path geometry rather than of flow. `(C - O) / (H - L)`,
wick ratios and range-per-tick all take perfectly ordinary values on a
driftless walk, and a study that reports them without that comparison is
reporting the shape of Brownian motion.

**The Deriv synthetics are the control almost nobody has, and what they
control for needs stating precisely.** They are **not** a zero-flow control.
Deriv generates their tick process as well as their prices, so they have a
flow - it is simply a *specified* one, posted at a near-fixed rate by a
generator with no participants, no queue and no inventory behind it. Measured
at 1h their activity extent is **1.001 to 1.016** against 2.7 to 9.4 for traded
instruments, so their tick count is nearly constant by construction.

That makes the contrast **informative flow against uninformative flow**, which
is a sharper control than present against absent. On a synthetic, a bar's tick
count carries almost nothing because the generator fixed it in advance; on
EURUSD it varies sixfold and is set by what participants did. So any statistic
that varies with tick count on traded instruments and not on synthetics is
reading participant behaviour rather than the arithmetic of OHLC - and any
statistic that behaves the same on both is path geometry.

So the design is: every statistic computed three ways - on the traded
instrument, on a **matched walk** built with that instrument's own per-bar tick
counts and volatility, and on the **generated feeds** - and nothing is reported
that the walk also produces.

## The statistics

* **`range ~ ticks` slope**, on logs. Independence gives 0.5 and a perfectly
  directional bar gives 1.0, so the slope *is* a flow-persistence measure with
  two known anchors rather than an arbitrary index;
* **imbalance**, `(C - O) / (H - L)`: where in its own range the bar closed;
* **absorption**, `ticks / range`: Kyle's lambda inverted - how many price
  changes the bar took to travel its range. High means flow was absorbed
  without moving price, which is what passive liquidity does;
* **wick asymmetry**, `((H - C) - (C - L)) / (H - L)`: which side got rejected.

## Then, and only then, the directional question

If any statistic separates traded from walk, the next question is whether it
predicts the **next** bar's sign. That is tested with AUC against a block
shuffle, and costed: this desk has measured that a directional gate can be
real at `z + 2.90` and still earn two per cent of a spread, so an AUC without
a cost line attached is not a result.

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
#: Matched-walk repetitions. The walk is cheap and its spread matters.
WALKS = int(os.environ.get("WALKS", "8"))

TRADED = tuple(
    os.environ.get(
        "TRADED", "EURUSD,GBPUSD,USDJPY,USDCAD,AUDUSD,XAUUSD,XAGUSD,US_Oil"
    ).split(",")
)
GENERATED = tuple(
    os.environ.get(
        "GENERATED",
        "Boom_500_Index,Crash_500_Index,DEX_900_UP_Index,Step_Index_200,Drift_Switch_Index_10",
    ).split(",")
)


def load(name: str):
    """`(open, high, low, close, ticks, spread or None)`, or `None`."""
    import numpy as np

    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close", "volume"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        keys = set(need)
        if "spread" in bundle:
            keys.add("spread")
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in keys}
    if len(got["time"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    keep = (
        (got["high"] > got["low"])
        & (got["volume"] > 0)
        & (got["low"] > 0)
        & np.isfinite(got["close"])
    )
    if keep.sum() < 2000:
        return None
    out = [got[k][keep] for k in ("open", "high", "low", "close", "volume")]
    out.append(got["spread"][keep] if "spread" in got else None)
    return tuple(out)


def matched_walk(ticks, sigma: float, rng):
    """OHLC from a walk with the **same per-bar tick counts** and volatility.

    The null that matters. Each bar is `n` independent increments, so its range
    carries the `sqrt(n)` scaling that independence implies and its OHLC has
    the geometry any path has. Anything the real bars share with this is the
    shape of a random walk and not order flow.

    Built by sampling the within-bar path rather than by a closed form, because
    the high and low of a discrete walk are not the continuous expressions and
    the difference is exactly the regime this study works in.
    """
    import numpy as np

    counts = np.asarray(ticks, dtype=int)
    counts = np.clip(counts, 1, 4000)
    opens = np.empty(len(counts))
    highs = np.empty(len(counts))
    lows = np.empty(len(counts))
    closes = np.empty(len(counts))
    level = 0.0
    for i, n in enumerate(counts):
        steps = rng.normal(0.0, sigma, size=n)
        path = level + np.cumsum(steps)
        opens[i] = level
        highs[i] = max(path.max(), level)
        lows[i] = min(path.min(), level)
        closes[i] = path[-1]
        level = path[-1]
    return opens, highs, lows, closes, counts.astype(float)


def slope(ticks, ranges) -> float:
    """`d log(range) / d log(ticks)`. 0.5 is independence, 1.0 a pure run."""
    import numpy as np

    x = np.log(np.asarray(ticks, dtype=float))
    y = np.log(np.asarray(ranges, dtype=float))
    keep = np.isfinite(x) & np.isfinite(y)
    x, y = x[keep], y[keep]
    if len(x) < 500:
        return float("nan")
    # **A slope needs variation in its regressor, and the synthetics have
    # none.** Their tick count is fixed by the generator, so `var(log ticks)`
    # is near zero and `cov / var` explodes: the first run of this harness
    # reported slopes of 9.2, 13.5 and 21.8 for Boom, Crash and DEX, which are
    # not steep relationships but a division by almost nothing. The guard is
    # on the regressor's own spread, which is the quantity at fault.
    if x.std() < 0.05:
        return float("nan")
    return float(np.polyfit(x, y, 1)[0])


def statistics_for(bars) -> dict[str, float]:
    """The four proxies, each a median over bars."""
    import numpy as np

    opens, highs, lows, closes, ticks = bars[:5]
    span = highs - lows
    keep = span > 0
    opens, highs, lows, closes, ticks, span = (
        v[keep] for v in (opens, highs, lows, closes, ticks, span)
    )
    if len(span) < 500:
        return {}
    imbalance = (closes - opens) / span
    wick = ((highs - closes) - (closes - lows)) / span
    return {
        "slope": slope(ticks, span),
        "|imbalance|": float(np.median(np.abs(imbalance))),
        "|wick|": float(np.median(np.abs(wick))),
        # Scale-free: ticks per range, divided by its own median, then the
        # spread of that. An absolute lambda is in price units and cannot be
        # compared between a walk and an instrument.
        "absorption cv": float(
            np.std(ticks / span) / np.mean(ticks / span) if np.mean(ticks / span) > 0 else np.nan
        ),
        "run share": float(np.mean(np.abs(imbalance) > 0.5)),
    }


def main() -> None:
    import numpy as np

    print(f"frame {FRAME}  walks {WALKS}\n")
    print(
        "Every statistic is computed on the instrument and on a matched walk\n"
        "built from its own per-bar tick counts. The walk column is what a\n"
        "driftless random path with the same activity produces, and nothing\n"
        "that matches it is order flow.\n"
    )
    keys = ("slope", "|imbalance|", "|wick|", "absorption cv", "run share")
    header = f"{'instrument':<22}{'bars':>8}"
    for k in keys:
        header += f"{k:>15}{'walk':>9}"
    print(header)

    rng = np.random.default_rng(SEED)
    rows = []
    for name in TRADED + GENERATED:
        bars = load(name)
        if bars is None:
            print(f"{name:<22}  no usable bars at {FRAME}")
            continue
        opens, highs, lows, closes, ticks = bars[:5]
        real = statistics_for(bars)
        if not real:
            continue
        steps = np.diff(np.log(closes))
        sigma_bar = float(np.std(steps)) or 1e-9
        # Per-tick sigma under independence, so the walk matches this
        # instrument's bar volatility at its own activity level.
        sigma_tick = sigma_bar / math.sqrt(max(float(np.mean(ticks)), 1.0))

        drawn: dict[str, list[float]] = {k: [] for k in keys}
        for _ in range(WALKS):
            walk = matched_walk(ticks, sigma_tick, rng)
            got = statistics_for(walk)
            for k in keys:
                if k in got and math.isfinite(got[k]):
                    drawn[k].append(got[k])
        line = f"{('*' + name if name in GENERATED else name):<22}{len(closes):>8,}"
        cell = {}
        for k in keys:
            null = statistics.median(drawn[k]) if drawn[k] else float("nan")
            cell[k] = (real[k], null)
            line += f"{real[k]:>15.4f}{null:>9.4f}"
        print(line)
        rows.append((name, name in GENERATED, cell, drawn))

    if not rows:
        print("nothing loaded")
        return

    print("\n" + "=" * 118)
    print("ARM 0  each statistic against its own walk draws, per instrument")
    print("=" * 118)
    print(
        "The median hides the statistic that matters, which is **sign\n"
        "consistency**: a 5% departure on 8 of 8 instruments is a different\n"
        "claim from a 40% departure on 4 of 8. `z` is the departure in units of\n"
        "the walk draws' own spread.\n"
    )
    print(f"{'statistic':<16}{'traded':>8}{'below':>7}{'above':>7}{'median z':>10}{'generated':>11}{'median z':>10}")
    for k in keys:
        out = {}
        for label, made in (("traded", False), ("generated", True)):
            zs, below, above = [], 0, 0
            for _name, flag, cell, drawn in rows:
                if flag != made:
                    continue
                real, _null = cell[k]
                got = [v for v in drawn[k] if math.isfinite(v)]
                if not math.isfinite(real) or len(got) < 3:
                    continue
                spread = statistics.pstdev(got) or 1e-12
                z = (real - statistics.median(got)) / spread
                zs.append(z)
                below += z < 0
                above += z > 0
            out[label] = (zs, below, above)
        tz, tb, ta = out["traded"]
        gz, _gb, _ga = out["generated"]
        print(
            f"{k:<16}{len(tz):>8}{tb:>7}{ta:>7}"
            f"{statistics.median(tz) if tz else float('nan'):>10.1f}"
            f"{len(gz):>11}{statistics.median(gz) if gz else float('nan'):>10.1f}"
        )
    print(
        "\nThe walk draws differ only in their random seed, so their spread is\n"
        "small and these z values are large by construction. Read the **sign\n"
        "counts** as the evidence and z only as a direction and a rough size."
    )

    print("\n" + "=" * 118)
    print("ARM 1  the range-against-ticks slope, which has two known anchors")
    print("=" * 118)
    print(
        "0.5 is what independent increments give and 1.0 a bar that moved in\n"
        "one direction throughout. The walk column is the harness checking\n"
        "itself: it must land on 0.5.\n"
    )
    print(f"{'group':<14}{'cells':>7}{'measured':>11}{'matched walk':>14}{'excess':>9}")
    for label, made in (("traded", False), ("generated", True)):
        here = [r for r in rows if r[1] == made]
        if not here:
            continue
        got = statistics.median([r[2]["slope"][0] for r in here])
        null = statistics.median([r[2]["slope"][1] for r in here])
        print(f"{label:<14}{len(here):>7}{got:>11.4f}{null:>14.4f}{got - null:>+9.4f}")
    print(
        "\nThe generated feeds are **absent from this arm by design**: their\n"
        "tick count is fixed by the generator, so there is no regressor to\n"
        "regress on and the guard in `slope` drops them.\n"
    )
    got = [r[2]["slope"][0] for r in rows if not r[1] and math.isfinite(r[2]["slope"][0])]
    nulls = [r[2]["slope"][1] for r in rows if not r[1] and math.isfinite(r[2]["slope"][1])]
    if got and nulls:
        over = sum(1 for a, b in zip(got, nulls, strict=False) if a > b)
        print(
            f"{over} of {len(got)} traded instruments sit above their walk, "
            f"range {min(got):.2f} to {max(got):.2f}.\n"
            "**This is weaker than the activity-on-Q exponent of 2 and the two\n"
            "are not the same quantity.** That exponent related a bar's\n"
            "variance to its activity *share* - volume against its own recent\n"
            "mean - inside a filter that tracks the level. This slope is a\n"
            "cross-sectional regression carrying every long-run change in\n"
            "volatility that had nothing to do with activity, and volatility\n"
            "clustering attenuates it toward 0.5. The filter is the better\n"
            "measurement; this is the cruder view of the same question."
        )

    print("\n" + "=" * 118)
    print("ARM 2  which proxies survive the walk, and which are just geometry")
    print("=" * 118)
    print(f"{'statistic':<16}{'traded':>10}{'walk':>10}{'ratio':>8}{'generated':>12}{'its walk':>10}{'ratio':>8}")
    for k in keys:
        cells = {}
        for label, made in (("traded", False), ("generated", True)):
            here = [r for r in rows if r[1] == made]
            if not here:
                cells[label] = (float("nan"), float("nan"))
                continue
            cells[label] = (
                statistics.median([r[2][k][0] for r in here]),
                statistics.median([r[2][k][1] for r in here]),
            )
        tr, trn = cells["traded"]
        ge, gen = cells["generated"]
        print(
            f"{k:<16}{tr:>10.4f}{trn:>10.4f}{tr / trn if trn else float('nan'):>8.2f}"
            f"{ge:>12.4f}{gen:>10.4f}{ge / gen if gen else float('nan'):>8.2f}"
        )
    print(
        "\n**Read the two ratio columns against each other, not the levels.**\n"
        "A proxy whose traded ratio and generated ratio are both near one is\n"
        "path geometry. A proxy that departs from one on traded and stays\n"
        "there on a specified generator with no participants in it is\n"
        "measuring something the generator does not contain."
    )


    print("\n" + "=" * 118)
    print("ARM 3  does the reconstructed flow predict the NEXT bar's sign")
    print("=" * 118)
    print(
        "Arm 0 says real markets absorb within the bar: they close nearer the\n"
        "middle of their range than a walk does, on 8 of 8. The directional\n"
        "question is whether that absorption continues into the next bar - a\n"
        "bar that closed near its high being followed by a down bar.\n"
        "\n"
        "AUC against a **block shuffle** of the feature, which keeps its own\n"
        "serial structure and breaks only its alignment to the target. And a\n"
        "cost line, because this desk has measured a directional gate that was\n"
        "real at z+2.90 and earned two per cent of a spread: an AUC without a\n"
        "cost attached is not a result.\n"
    )
    print(
        f"{'instrument':<22}{'feature':<14}{'AUC':>8}{'null hi':>9}"
        f"{'beats':>7}{'edge bp':>9}{'room bp':>9}{'cost bp':>9}{'net bp':>9}"
    )
    picker = np.random.default_rng(SEED + 7)
    tally = []
    for name in TRADED + GENERATED:
        bars = load(name)
        if bars is None:
            continue
        opens, highs, lows, closes, ticks, spreads = bars
        span = highs - lows
        keep = span > 0
        pieces = [opens, highs, lows, closes, ticks, span]
        if spreads is not None:
            pieces.append(spreads)
        trimmed = [v[keep] for v in pieces]
        opens, highs, lows, closes, ticks, span = trimmed[:6]
        spreads = trimmed[6] if spreads is not None else None
        forward = np.diff(np.log(closes))
        if len(forward) < 2000:
            continue
        # Features of bar `i`, target the sign of bar `i+1`'s return.
        features = {
            "imbalance": ((closes - opens) / span)[:-1],
            "wick": (((highs - closes) - (closes - lows)) / span)[:-1],
            "absorption": (ticks / span)[:-1],
        }
        target = (forward > 0).astype(float)
        target = target[: len(features["imbalance"])]
        # How much there is to win: the bar's own range in basis points, which
        # bounds what any single-bar reversal can earn.
        room_bp = 1e4 * float(np.median(span[:-1] / closes[:-1])) if len(closes) > 2 else 0.0
        # And what it costs. **The cache's `spread` is in integer points, not
        # price** - reading it as price put a 476% round trip on EURUSD once
        # and reordered every instrument by cost - so it is multiplied by the
        # instrument's own point size, inferred as the smallest non-zero gap
        # between closes rounded to a power of ten. Doubled for a round trip.
        cost_bp = float("nan")
        if spreads is not None and len(spreads) > 2:
            gaps = np.abs(np.diff(np.unique(closes)))
            gaps = gaps[gaps > 0]
            if len(gaps):
                point = 10.0 ** round(math.log10(float(gaps.min())))
                cost_bp = (
                    2.0 * 1e4 * float(np.median(spreads[:-1])) * point / float(np.median(closes))
                )
        for label, feature in features.items():
            use = np.isfinite(feature) & np.isfinite(target)
            x, y = feature[use], target[use]
            if len(x) < 2000 or y.std() == 0:
                continue
            auc = roc(x, y)
            draws = []
            for _ in range(24):
                draws.append(roc(block_shuffled(x, picker), y))
            top = max(abs(d - 0.5) for d in draws) + 0.5
            beats = abs(auc - 0.5) > (top - 0.5)
            # An AUC of `a` on a balanced sign target earns, per bar and before
            # costs, about `(2a - 1)` of the move it is betting on.
            edge_bp = abs(2.0 * auc - 1.0) * room_bp
            net = edge_bp - cost_bp if math.isfinite(cost_bp) else float("nan")
            print(
                f"{('*' + name if name in GENERATED else name):<22}{label:<14}"
                f"{auc:>8.4f}{top:>9.4f}{'yes' if beats else 'no':>7}"
                f"{edge_bp:>9.2f}{room_bp:>9.2f}{cost_bp:>9.2f}{net:>+9.2f}"
            )
            tally.append((name, name in GENERATED, label, auc, beats, edge_bp, net))
    if tally:
        traded = [t for t in tally if not t[1]]
        made = [t for t in tally if t[1]]
        print(
            f"\n{sum(1 for t in traded if t[4])} of {len(traded)} traded cells "
            f"beat their block-shuffle null; "
            f"{sum(1 for t in made if t[4])} of {len(made)} generated cells do."
        )
        for label in ("imbalance", "wick", "absorption"):
            here = [t[3] for t in traded if t[2] == label]
            nets = [t[6] for t in traded if t[2] == label and math.isfinite(t[6])]
            if here:
                print(
                    f"  {label:<12} median AUC {statistics.median(here):.4f}, "
                    f"best {max(here, key=lambda a: abs(a - 0.5)):.4f}"
                    + (f", median net {statistics.median(nets):+.2f} bp" if nets else "")
                )
        print(
            "\n**An AUC near 0.5 here closes the single-bar reversal question\n"
            "rather than leaving it open.** Absorption is real within the bar -\n"
            "arm 0 is unanimous on it - and that is not the same as absorption\n"
            "continuing across the bar boundary, which is where a bet would\n"
            "have to live."
        )


def roc(scores, labels) -> float:
    """AUC by rank, which needs no threshold and no calibration."""
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
    return float((ranks[labels > 0].sum() - positives * (positives + 1) / 2) / (positives * negatives))


def block_shuffled(values, rng, blocks: int = 24):
    """Shuffle in contiguous blocks, keeping the feature's own persistence."""
    import numpy as np

    values = np.asarray(values, dtype=float)
    size = max(len(values) // blocks, 1)
    pieces = [values[i : i + size] for i in range(0, len(values), size)]
    order = rng.permutation(len(pieces))
    return np.concatenate([pieces[i] for i in order])[: len(values)]


if __name__ == "__main__":
    main()
