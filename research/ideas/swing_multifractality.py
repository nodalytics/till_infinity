"""The symmetry index at every moment order: multifractality of the swings.

Asked on 2026-10-12, after two results that sit oddly together.

**The symmetry index is blind.** It measures how multiplicatively alike
consecutive swing sizes are - the mean of `|log(s_i / s_{i-lag})|` - and
`statespace-displacement-sequences.md` found the market gaining 0.124 over a
shuffle of its own sizes where a GARCH surrogate gains 0.131. The same number.
The index cannot tell a market from a process with clustering and no geometry.

**But the market is not GARCH.** `statespace-fractals.md` measured, on the
same instruments, that the market's returns are two to four times more
multifractal than that surrogate - `lambda^2` of 0.062 to 0.117 against 0.031
- and its log-volatility about four times rougher.

So the market has structure the surrogate lacks, and the symmetry index does
not see it. That is a statement about the **index**, and it suggests a
specific repair rather than abandoning it.

## The combination

The symmetry index is the **first absolute moment** of the log swing-size
ratio. Nothing forces it to be the first. Taking the `q`-th moment,

    m(lag, q) = mean |log(s_i / s_{i-lag})|^q  ~  lag^(xi(q))

gives a scaling exponent per moment order, exactly as `zeta(q)` does for
returns - and if the sequence is multifractal, `xi(q)` is **curved**:

    xi(q) = q H_s - lambda_s^2 q (q - 1) / 2

`lambda_s^2` is then the multifractality of the *swing sequence*, a quantity
neither note measured. The hypothesis is sharp: the index is blind at `q = 1`
because a first moment averages the intermittency away, and the curvature is
where the market's excess over a clustering surrogate should appear.

If `lambda_s^2` separates the market from GARCH where the `q = 1` level did
not, the index was asking the wrong moment. If it does not separate them
either, then the swing sequence genuinely carries nothing the clustering does
not, and that closes the question rather than leaving it open.

## The lag is in swings, and why that is allowed here

Everywhere else in this package a window in bars is a portability defect. Here
the lag counts **swings**, because the sequence's own clock is the turn - and
what is read off it is a **scaling exponent**, which is invariant to a
multiplicative change in the lag axis. A surrogate that turns at a different
rate than the market shifts the intercept of `log m` against `log lag` and
leaves the slope alone. The exponent is comparable; the level would not be.

Runs on the lab.
"""

from __future__ import annotations

import itertools
import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.statespace.displacements import sequence
from till_infinity.statespace.nulls import garch

HOUR = 3600.0

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD")
GENERATED = ("Volatility_75_Index", "Step_Index")
FRAMES = tuple(os.environ.get("FRAMES", "1h,4h").split(","))

SPAN = int(os.environ.get("SPAN", "5"))
LAGS = (1, 2, 3, 5, 8, 13, 21, 34)
ORDERS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0)

SINCE = float(os.environ.get("SINCE", "1420070400"))
LIMIT = int(os.environ.get("LIMIT", "40000"))
SEED = 20261012
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    for path in (CACHE / f"{name}.{frame}.npz", Path(f"data/seqlab/{name}.{frame}.npz")):
        if not path.exists():
            continue
        with np.load(path) as bundle:
            if not {"time", "close", "high", "low"} <= set(bundle.keys()):
                continue
            order = np.argsort(bundle["time"])
            out = {k: bundle[k][order].tolist() for k in ("time", "close", "high", "low")}
        first = 0
        while first < len(out["time"]) and out["time"][first] < SINCE:
            first += 1
        for key, series in list(out.items()):
            trimmed = series[first:]
            out[key] = trimmed[-LIMIT:] if len(trimmed) > LIMIT else trimmed
        return out if len(out["time"]) > 5000 else None
    return None


def unit(closes: list[float]) -> float:
    moves = [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i] > 0 and closes[i - 1] > 0
    ]
    return statistics.pstdev(moves) if len(moves) > 2 else 0.0


def swing_sizes(times, closes, highs, lows, *, scale: float) -> list[float]:
    moves = sequence(times, closes, highs, lows, span=SPAN, unit=scale)
    return [m.size for m in moves if m.size > 0]


def exponent(sizes: list[float], order: float) -> float:
    """Slope of `log m(lag, q)` against `log lag` for the log size ratios."""
    xs: list[float] = []
    ys: list[float] = []
    logs = [math.log(v) for v in sizes]
    for lag in LAGS:
        if lag >= len(logs) // 8:
            continue
        gaps = [abs(logs[i + lag] - logs[i]) ** order for i in range(len(logs) - lag)]
        if len(gaps) < 50:
            continue
        middle = statistics.fmean(gaps)
        if middle <= 0:
            continue
        xs.append(math.log(lag))
        ys.append(math.log(middle))
    if len(xs) < 4:
        return float("nan")
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((a - mx) ** 2 for a in xs)
    if den <= 0:
        return float("nan")
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True)) / den


def curvature(sizes: list[float]) -> tuple[float, float, float]:
    """`H_s` and `lambda_s^2` from `xi(q)`, plus the first-moment index.

    The third return value is the plain symmetry index at `q = 1` - the thing
    that was blind - so the two are always read side by side.
    """
    rows: list[tuple[float, float, float]] = []
    for order in ORDERS:
        got = exponent(sizes, order)
        if math.isnan(got):
            continue
        rows.append((order, -order * (order - 1.0) / 2.0, got))
    if len(rows) < 3:
        return float("nan"), float("nan"), float("nan")

    s11 = sum(a * a for a, _b, _z in rows)
    s12 = sum(a * b for a, b, _z in rows)
    s22 = sum(b * b for _a, b, _z in rows)
    t1 = sum(a * z for a, _b, z in rows)
    t2 = sum(b * z for _a, b, z in rows)
    det = s11 * s22 - s12 * s12
    if abs(det) < 1e-18:
        return float("nan"), float("nan"), float("nan")

    logs = [math.log(v) for v in sizes]
    first = statistics.fmean([abs(b - a) for a, b in itertools.pairwise(logs)])
    return (
        (s22 * t1 - s12 * t2) / det,
        (s11 * t2 - s12 * t1) / det,
        first,
    )


def surrogate_sizes(data: dict, kind: str, seed: int) -> list[float]:
    """Swing sizes from a surrogate built to the same length and spread."""
    scale = unit(data["close"]) or 1e-6
    n = len(data["close"]) - 1
    if kind == "garch":
        steps = garch(n, seed=seed, sigma=scale)
    else:
        rng = random.Random(seed)
        steps = [rng.gauss(0.0, scale) for _ in range(n)]
    made = [data["close"][0]]
    for step in steps:
        made.append(made[-1] * math.exp(step))
    return swing_sizes(data["time"], made, made, made, scale=unit(made) or 1e-6)


def main() -> None:
    print(
        f"frames {FRAMES}  span {SPAN}  lags in swings {LAGS}  orders {ORDERS}\n"
        "index is the plain symmetry index at q=1, the reading that was blind.\n"
        "lambda_s^2 is the curvature of xi(q): the swing sequence's own\n"
        "multifractality, which nothing here had measured.\n"
    )
    print(f"{'series':<24}{'frame':<6}{'swings':>7}{'index':>8}{'H_s':>8}{'lambda_s2':>11}")

    rows: list[dict] = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            data = load(name, frame)
            if data is None:
                continue
            scale = unit(data["close"])
            if scale <= 0:
                continue
            sizes = swing_sizes(data["time"], data["close"], data["high"], data["low"], scale=scale)
            if len(sizes) < 300:
                continue
            label = f"*{name}" if name in GENERATED else name

            arms = {"real": sizes}
            shuffled = list(sizes)
            random.Random(SEED).shuffle(shuffled)
            arms["shuffled"] = shuffled
            if not name.startswith("Volatility") and name not in GENERATED:
                arms["garch"] = surrogate_sizes(data, "garch", SEED + 1)
                arms["walk"] = surrogate_sizes(data, "walk", SEED + 2)

            for arm, pool in arms.items():
                if len(pool) < 300:
                    continue
                h_s, lam, first = curvature(pool)
                if math.isnan(lam):
                    continue
                rows.append(
                    {
                        "label": label,
                        "frame": frame,
                        "arm": arm,
                        "swings": len(pool),
                        "index": first,
                        "h_s": h_s,
                        "lambda": lam,
                    }
                )
                shown = label if arm == "real" else f"  {arm}"
                print(f"{shown:<24}{frame:<6}{len(pool):>7}{first:>8.3f}{h_s:>8.3f}{lam:>11.4f}")

    print("\n== medians by arm, traded instruments only")
    print(f"{'arm':<12}{'cells':>6}{'index':>9}{'H_s':>8}{'lambda_s2':>11}")
    traded = [r for r in rows if not r["label"].startswith("*")]
    for arm in ("real", "shuffled", "garch", "walk"):
        got = [r for r in traded if r["arm"] == arm]
        if not got:
            continue
        print(
            f"{arm:<12}{len(got):>6}"
            f"{statistics.median([r['index'] for r in got]):>9.3f}"
            f"{statistics.median([r['h_s'] for r in got]):>8.3f}"
            f"{statistics.median([r['lambda'] for r in got]):>11.4f}"
        )
    made = [r for r in rows if r["label"].startswith("*") and r["arm"] == "real"]
    if made:
        print(
            f"{'generated':<12}{len(made):>6}"
            f"{statistics.median([r['index'] for r in made]):>9.3f}"
            f"{statistics.median([r['h_s'] for r in made]):>8.3f}"
            f"{statistics.median([r['lambda'] for r in made]):>11.4f}"
        )

    print(
        "\n   The question is whether `lambda_s2` separates real from garch where\n"
        "   the index at q=1 did not. If both columns agree between those two\n"
        "   arms, the swing sequence carries nothing the clustering does not,\n"
        "   and that closes the question rather than leaving it open."
    )


if __name__ == "__main__":
    main()
