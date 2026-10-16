"""Sweep, then break of structure, then a one-candle push that engulfs.

Asked for on 2026-10-16: "test our own definition of engulfing with the
sweep+bos idea, the push_n=1 engulf".

## Why this is a different claim from the single shape

`one_push.py` measured the one-candle push on its own and the honest reading is
that its edge over a distance-matched placebo is small and may be mechanical -
a displacement origin's line is a price the path **just traded through**, and
price returning to a price it recently left needs no participant and no intent.
The placebo's line is a fresh price at the same distance, so it cannot imitate
that.

This is a **sequence** rather than a shape, and the ordering is the content:

1. **the sweep** - price runs a prior swing extreme and closes back inside it.
   Not a shape but an intention: taking the stops resting beyond a level is how
   size gets filled, and `structures/drawing/sweeps.py` is the same idea stated
   over the live level set ("a level with liquidity resting close beyond it is a
   level price has a reason to run through").
2. **the break of structure** - a close back through the last swing of the
   other kind that was known *before* the sweep. The flip is confirmed by a
   close rather than by a wick.
3. **the trigger** - that bar is a one-candle push, and under the strict arm it
   also **engulfs** the previous body.

The engulf is carried as an arm rather than as part of the definition, because
the two conditions carry opposite inferences and that is worth measuring rather
than assuming: an engulfing needs the previous bar's **opposite colour** and
its body **contained**, which is a reversal statement, while a push needs its
own body one-sided in its own range, which is an initiation statement.

## The observable is the barrier, not the return rate

`one_push.py`'s power section is the reason. At a 100-bar horizon the return
rate sits at 0.85 for the real arm and 0.85 for the placebo, and planting a
real magnet of 0.1 volatility units a bar for 100 bars moved the edge from
+0.0025 to +0.0080 - a huge planted effect barely visible, because the statistic
is saturated against its own ceiling. A saturated statistic cannot report an
absence.

So this scores the barrier: from the trigger's close, did `R` times the risk
arrive before the risk did. That is centred near `1/(1+R)` rather than near 1,
it is the quantity a trade is actually paid on, and the geometric requirement is
known in closed form so the null is not optional guesswork.

## Three arms, and the twin is the one that matters

* **real**
* **twin** - the same bars' geometry in a block-shuffled order, through the
  identical detector. Each bar is reduced to its gap in, its reach above and
  below the open, and its body, then rebuilt by chaining opens onto closes, so
  every bar's own shape survives and only the order changes. This is the arm
  that separates "the sequence means something" from "these bar shapes in any
  order produce this number".
* **coin** - the same triggers, side drawn at random. `origin-zones.md` used
  the same pair, and it catches a geometry that pays whichever way it is taken.

The real arm is also rebuilt through `rebuild` at the identity order, so the
real and twin arms differ in the permutation and in nothing else.

  python research/ideas/sweep_bos_engulf.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from inside_clock import geometry, rebuild  # noqa: E402
from pattern_fingerprint import CACHE, classify, load  # noqa: E402
from prims import pivots  # noqa: E402

from till_infinity.trading.candles import Bar, engulfing  # noqa: E402

FRAME = "1h"
SEED = 20261016
PER_CLASS = 10
#: Bars in a shuffled block. **Much longer than a whole trade**, which the
#: first run got wrong: at 48 bars against a 60-bar hold every twin trade
#: spanned a join, so the shuffled arm was racing barriers across artificial
#: jumps and read 0.462 where 0.500 was required. A block has to carry the
#: sweep, the break, the trigger and the full race - 78 bars - with room to
#: spare, or the null is measuring its own seams.
BLOCK = 1024
TWINS = 3
#: Fewest trades a cell needs before its numbers are printed.
LEAST = 120

TRADED = ("fx_major", "fx_cross", "metal", "index", "energy", "soft", "basket")
GENERATED = ("volatility", "step", "boom", "jump")

#: Pivot half-widths. A wider pivot is a more significant swing and a rarer one.
WINGS = (3, 5)
#: How long after the sweep the break may arrive.
PATIENCE = 12
#: How long after the break the entry candle may arrive.
TRIGGER = 6
#: Body share for the one-candle push at the trigger.
BODIES = (0.50, 0.65)
#: Reward to risk on the barrier.
REWARDS = (1.0, 2.0, 3.0)
#: Bars allowed for the barrier race.
HOLD = 60
#: Stop beyond the swept extreme, in volatility units.
BUFFER = 0.25


def prices(bars: dict[str, np.ndarray], order: np.ndarray) -> dict[str, np.ndarray]:
    """Bar geometry rebuilt in `order`, back in price space.

    The real arm passes the identity order through this too, so real and twin
    differ in the permutation and in nothing else.
    """
    rebuilt = rebuild(geometry(bars), order)
    return {k: np.exp(v) for k, v in rebuilt.items()}


def blocks(count: int, rng) -> np.ndarray:
    """A block-shuffled index, blocks kept whole and in internal order."""
    edges = np.arange(0, count, BLOCK)
    pieces = [np.arange(a, min(a + BLOCK, count)) for a in edges]
    rng.shuffle(pieces)
    return np.concatenate(pieces)


def vol_units(closes: np.ndarray) -> np.ndarray:
    """Per-bar volatility in basis points, mean-absolute, half-life 60."""
    moves = np.zeros(len(closes))
    moves[1:] = np.abs(np.diff(closes)) / closes[:-1] * 10_000.0
    alpha = 1.0 - 2.0 ** (-1.0 / 60.0)
    out = np.empty(len(closes))
    running = 0.0
    for i, move in enumerate(moves):
        running = running + alpha * (move - running) if i else move
        out[i] = running
    return np.maximum(out, 0.25)


def one_sided(series: dict[str, np.ndarray], body: float) -> np.ndarray:
    """+1, -1 or 0 per bar: a one-candle push and which way it went.

    The same predicate as `pushed(..., run=1, body)` in
    `structures/drawing/displacement.py`, vectorised over the series. `checks`
    asserts the two agree.
    """
    span = series["high"] - series["low"]
    reach = series["close"] - series["open"]
    out = np.zeros(len(span), dtype=int)
    ok = span > 0
    out[ok & (reach > 0) & (reach >= body * span)] = 1
    out[ok & (reach < 0) & (-reach >= body * span)] = -1
    return out


def engulfs(series: dict[str, np.ndarray]) -> np.ndarray:
    """Per bar: does it engulf the previous body, by the shipped predicate?

    Vectorised, and `checks` asserts it against `trading.candles.engulfing`
    over a sample rather than trusting the translation.
    """
    opens, highs = series["open"], series["high"]
    lows, closes = series["low"], series["close"]
    top = np.maximum(opens, closes)
    bottom = np.minimum(opens, closes)
    span = highs - lows
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(span > 0, (top - bottom) / span, 0.0)
    doji = share < 0.1
    up = closes > opens
    out = np.zeros(len(opens), dtype=bool)
    out[1:] = (
        (bottom[1:] < bottom[:-1])
        & (top[1:] > top[:-1])
        & (up[1:] != up[:-1])
        & ~doji[1:]
        & ~doji[:-1]
    )
    return out


def checks(series: dict[str, np.ndarray]) -> None:
    """Both vectorised predicates against the shipped ones, on a sample."""
    from till_infinity.structures.drawing.displacement import pushed

    opens, highs = series["open"], series["high"]
    lows, closes = series["low"], series["close"]
    for body in BODIES:
        mine = one_sided(series, body)
        for i in range(1, min(400, len(closes) - 1)):
            theirs = pushed(opens, highs, lows, closes, i, 1, body)
            assert mine[i] == theirs, f"push at {i} body={body}: {mine[i]} vs {theirs}"
    mine = engulfs(series)
    for i in range(1, min(400, len(closes))):
        before = Bar(opens[i - 1], highs[i - 1], lows[i - 1], closes[i - 1])
        after = Bar(opens[i], highs[i], lows[i], closes[i])
        assert mine[i] == bool(engulfing(before, after)), f"engulf at {i}"


def sequences(
    series: dict[str, np.ndarray],
    *,
    wing: int,
    body: float,
    strict: bool,
) -> list[tuple[int, int, float]]:
    """Every sweep -> break -> push trigger, as (trigger bar, side, risk price).

    Nothing is used before the bar it is known on: a pivot is known `wing` bars
    after it printed, and the break must be a **close** beyond the prior swing.
    """
    highs, lows, closes = series["high"], series["low"], series["close"]
    n = len(closes)
    ph, pl = pivots(highs, lows, left=wing, right=wing)
    pushes = one_sided(series, body)
    engulfed = engulfs(series)
    out: list[tuple[int, int, float]] = []
    for side, runs, breaks in ((1, pl, ph), (-1, ph, pl)):
        # `runs` are the extremes a sweep takes out; `breaks` are the swings a
        # break of structure closes through.
        for known, where, price in runs:
            # The sweep: a later bar's extreme goes beyond this swing and the
            # bar closes back inside it.
            start = max(int(known), int(where) + 1)
            swept = -1
            for i in range(start, min(start + PATIENCE, n)):
                through = lows[i] < price if side > 0 else highs[i] > price
                back = closes[i] > price if side > 0 else closes[i] < price
                if through and back:
                    swept = i
                    break
            if swept < 0:
                continue
            # The structure to break: the last opposite swing known before the
            # sweep, so nothing after the sweep informs the level.
            prior = [p for k, _w, p in breaks if k <= swept]
            if not prior:
                continue
            target = prior[-1]
            broke_at = -1
            for i in range(swept, min(swept + PATIENCE, n)):
                if closes[i] > target if side > 0 else closes[i] < target:
                    broke_at = i
                    break
            if broke_at < 0:
                continue
            # **The trigger is not required to be the breaking bar.** It was,
            # and that found almost nothing - a break of structure is usually
            # made by a bar whose predecessor was the same colour, so an
            # engulfing there is close to a contradiction in terms. The idea as
            # traded is that structure breaks and *then* an entry candle is
            # waited for, so that is what this scans for.
            for i in range(broke_at, min(broke_at + TRIGGER, n)):
                if pushes[i] != side:
                    continue
                if strict and not engulfed[i]:
                    continue
                extreme = lows[swept] if side > 0 else highs[swept]
                risk = abs(closes[i] - extreme)
                if risk > 0:
                    out.append((i, side, risk))
                break
    return out


def raced(
    series: dict[str, np.ndarray],
    found: list[tuple[int, int, float]],
    vols: np.ndarray,
    reward: float,
    sides: np.ndarray | None = None,
) -> dict[str, float]:
    """The barrier race from each trigger's close, and what it paid."""
    highs, lows, closes = series["high"], series["low"], series["close"]
    n = len(closes)
    won = lost = 0
    paid = 0.0
    for k, (at, side, risk) in enumerate(found):
        if sides is not None:
            side = int(sides[k])
        entry = closes[at]
        wide = risk + vols[at] / 10_000.0 * entry * BUFFER
        stop = entry - side * wide
        goal = entry + side * reward * wide
        a, b = at + 1, min(at + 1 + HOLD, n)
        if a >= b:
            continue
        hit = stop_at = -1
        for i in range(a, b):
            if side > 0:
                if lows[i] <= stop:
                    stop_at = i
                if highs[i] >= goal:
                    hit = i
            else:
                if highs[i] >= stop:
                    stop_at = i
                if lows[i] <= goal:
                    hit = i
            if hit >= 0 or stop_at >= 0:
                break
        # Both inside one bar is unknowable from a bar; counted as the stop,
        # which is the conservative reading and the one the desk would live.
        if stop_at >= 0:
            lost += 1
            paid -= 1.0
        elif hit >= 0:
            won += 1
            paid += reward
    decided = won + lost
    return {
        "n": float(len(found)),
        "decided": float(decided),
        "hit": won / decided if decided else float("nan"),
        "needs": 1.0 / (1.0 + reward),
        "r": paid / len(found) if found else float("nan"),
    }


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"Sweep -> break of structure -> one-candle push. {FRAME} bars, barrier\n"
        f"race over {HOLD} bars, stop {BUFFER} vol beyond the swept extreme.\n"
        f"`strict` additionally requires the trigger to engulf the previous body.\n"
        f"twin = {TWINS} geometry-preserving block shuffles at {BLOCK} bars.\n"
    )

    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob(f"*.{FRAME}.npz")):
        name = path.name[: -len(f".{FRAME}.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = [c for c in (*TRADED, *GENERATED) if c in groups]
    if not wanted:
        print(f"no bars under {CACHE}")
        return

    loaded: dict[str, list[dict]] = {}
    verified = False
    for label in wanted:
        for name in sorted(groups[label])[:PER_CLASS]:
            bars = load(name, FRAME)
            if bars is None:
                continue
            series = prices(bars, np.arange(len(bars["close"])))
            if not verified:
                checks(series)
                print("both predicates agree with the shipped ones\n")
                verified = True
            loaded.setdefault(label, []).append(series)

    print(f"{'class':<16}{'wing':>5}{'body':>6}{'R':>4}{'arm':<8}{'n':>7}{'hit':>7}"
          f"{'needs':>7}{'edge':>8}{'R/trade':>9}")
    for label in wanted:
        got = loaded.get(label, [])
        if not got:
            continue
        for wing in WINGS:
            for body in BODIES:
                for strict in (False, True):
                    real = [sequences(s, wing=wing, body=body, strict=strict) for s in got]
                    # Built once per definition, not once per reward: the
                    # permutation and the detector do not depend on R, and
                    # rebuilding them inside that loop tripled the run.
                    shuffled = []
                    for _s in got:
                        for _ in range(TWINS):
                            order = blocks(len(_s["close"]), rng)
                            twin = {k: v[order] for k, v in _s.items()}
                            tf = sequences(twin, wing=wing, body=body, strict=strict)
                            if tf:
                                shuffled.append((twin, tf, vol_units(twin["close"])))
                    tossed = [
                        (_s, f, vol_units(_s["close"]), rng.choice([-1, 1], size=len(f)))
                        for _s, f in zip(got, real, strict=True)
                        if f
                    ]
                    for reward in REWARDS:
                        rows = [
                            raced(s, f, vol_units(s["close"]), reward)
                            for s, f in zip(got, real, strict=True)
                            if f
                        ]
                        if not rows or sum(r["n"] for r in rows) < LEAST:
                            continue

                        def pool(cells, key):
                            vals = [c[key] for c in cells if c[key] == c[key]]
                            return float(np.mean(vals)) if vals else float("nan")

                        twins = [raced(t, f, v, reward) for t, f, v in shuffled]
                        coins = [
                            raced(_s, f, v, reward, sides=sides)
                            for _s, f, v, sides in tossed
                        ]
                        arms = (
                            ("real", rows),
                            ("twin", twins),
                            ("coin", coins),
                        )
                        base = pool(rows, "hit")
                        for name, cells in arms:
                            if not cells:
                                continue
                            hit = pool(cells, "hit")
                            tag = f"{name}{'+eng' if strict else ''}"
                            gap = hit - pool(cells, "needs")
                            print(
                                f"{label:<16}{wing:>5}{body:>6.2f}{reward:>4.0f}{tag:<8}"
                                f"{sum(c['n'] for c in cells):>7.0f}{hit:>7.3f}"
                                f"{pool(cells, 'needs'):>7.3f}{gap:>+8.4f}"
                                f"{pool(cells, 'r'):>+9.3f}"
                                + ("" if name == "real" else f"   vs real {hit - base:+.4f}")
                            )


if __name__ == "__main__":
    main()
