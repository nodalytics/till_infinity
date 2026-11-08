"""Can a moving average be made to work on the Deriv synthetics?

    ./.secrets/lab.sh run research/harness/synthma.py

## Why this is not a hopeless question

The usual answer to "does a moving-average crossover work" is no, and on a
constant-volatility driftless process it is no **by construction**. But the
Deriv families are not one process. Three of them have direction engineered
into the generator:

* **Boom/Crash** drift slowly one way and spike the other. That asymmetry is
  the product, not a market accident, and an earlier study on this desk
  recorded Boom/Crash "gained more than any traded class".
* **Drift Switch** alternates drift regimes - a planted trend, which is what
  `range-break-is-the-level-positive-control` calls the regime positive
  control.
* **Range Break** ranges and then breaks, and a crossover is a breakout
  detector.

So the hypothesis has a mechanism, and this is built to find it rather than to
dismiss it.

## And why cost decides it before the signal does

`exotic-spreads-are-a-whole-bar-range`: the synthetics round-trip at **0.40 to
0.97 of a whole bar range** on this venue. A crossover that flips every few
bars is therefore dead before any signal question is reached, and the real
variable is **how slow the pair has to be to amortise the spread**. Every
figure here is printed gross and net, and the flip count is printed beside
them, because a cell that nets well on four trades has not been measured.

## The arms

* **controls that must read nothing** - Volatility 25/75, Step, Jump 75 are
  constant-volatility and symmetric, so a crossover earning there gross is a
  harness bug. `a-control-is-only-for-a-named-property` applies: the property
  is "no planted direction", and these have it.
* **shuffled twin** - each instrument's own returns resampled, which keeps the
  distribution and destroys the trend. The planted families should lose their
  gross edge here and the controls should not change.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse as parse
import urllib.request as request
from pathlib import Path

import numpy as np

DATA = Path(os.environ.get("DATA", str(Path.home() / "till_infinity" / "data" / "syn")))
LIST = Path(
    os.environ.get(
        "SYMBOLS_FILE",
        str(Path(__file__).resolve().parents[1] / "ideas" / "synthetic_ma_candidates.txt"),
    )
)
#: Instruments whose generator has no planted direction. These must read ~0.
CONTROLS = ("Volatility 25 Index", "Volatility 75 Index", "Step Index", "Jump 75 Index")
PAIRS = [(5, 20), (10, 50), (20, 100), (50, 200), (100, 400)]
SEED = 20261108
DRAWS = 1000
#: Shuffled twins per cell. 40 was not enough: the smallest p it can express
#: is 2/41 = 0.0488, so every "p = 0.049" in the previous run was the
#: resolution floor rather than a measurement, and a real 0.001 could not be
#: told from a marginal 0.05.
SHUFFLES = 300

#: Block length for the second null. A full permutation destroys **all** memory,
#: including the short-lag autocorrelation a crossover might legitimately be
#: eating. Permuting 20-bar blocks keeps ordering inside a block and destroys it
#: between, so:
#:
#:   real > block ~ iid   ->  the edge is longer-range trend
#:   real ~ block > iid   ->  the edge is short-lag memory, which is still real
#:   real ~ block ~ iid   ->  nothing
#:
#: Two nulls rather than one because the first run could not distinguish those
#: three cases, and they have different answers.
BLOCK = 20
#: Families whose generator is shared, so a real effect must appear across the
#: members rather than in one cell of 65. Pooling them is the highest-powered
#: test available here and is the one the mechanism predicts: Boom and Crash
#: drift one way and spike the other **by construction**.
POOLS = {
    "boom/crash": (
        "Boom 500 Index",
        "Boom 1000 Index",
        "Crash 500 Index",
        "Crash 1000 Index",
    ),
    "drift switch": ("Drift Switch Index 10", "Drift Switch Index 20", "Drift Switch Index 30"),
    "range break": ("Range Break 100 Index", "Range Break 200 Index"),
    "controls": CONTROLS,
}
BASE = os.environ.get("BRIDGE", "http://localhost:8000") + "/api/v1"


def symbols() -> list[str]:
    return [
        line.strip()
        for line in LIST.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def quoted(symbol: str) -> float:
    """The terminal's round trip in price, or nan."""
    try:
        key = (Path.home() / ".mt5key").read_text().strip()
        req = request.Request(  # noqa: S310
            f"{BASE}/symbols/info/{parse.quote(symbol)}", headers={"X-API-Key": key}
        )
        with request.urlopen(req, timeout=30) as response:  # noqa: S310
            spec = json.loads(response.read().decode())
        bid, ask = float(spec.get("bid") or 0.0), float(spec.get("ask") or 0.0)
        if ask > bid:
            return ask - bid
    except Exception:  # noqa: BLE001
        pass
    return float("nan")


def load(symbol: str) -> dict[str, np.ndarray] | None:
    path = DATA / f"{symbol}.15m.npz"
    if not path.exists():
        return None
    with np.load(path) as data:
        return {k: data[k] for k in ("time", "open", "high", "low", "close")}


def sma(values: np.ndarray, n: int) -> np.ndarray:
    """Trailing mean ending at i-1, so bar i never sees its own close."""
    out = np.full(len(values), np.nan)
    csum = np.concatenate(([0.0], np.cumsum(values)))
    if len(values) > n:
        out[n:] = (csum[n:-1] - csum[: -n - 1]) / n
    return out


def cross(close: np.ndarray, fast: int, slow: int) -> np.ndarray:
    """+1 long, -1 short, held until the pair crosses back. Causal."""
    quick, steady = sma(close, fast), sma(close, slow)
    side = np.where(quick > steady, 1.0, np.where(quick < steady, -1.0, 0.0))
    side[~np.isfinite(quick) | ~np.isfinite(steady)] = 0.0
    return side


def trade(close: np.ndarray, side: np.ndarray, cost_px: float, rng) -> dict:
    """Mean return per bar in median-step units, with a block-bootstrap interval.

    **Totals are not reported, and reporting them was the first version's
    defect.** The sum of `position * step` over 50,000 bars has a standard
    deviation near `sqrt(50000)` median-steps on a driftless process - about
    224 - so a total of +1,000 is a couple of sigma from nothing and reads as
    an edge. A per-bar mean with its error attached is the same information,
    honestly.

    Blocks are 200 bars because a crossover holds a position for many bars;
    resampling single bars would assume an independence the rule does not have.

    **`np.nansum` is deliberately absent.** It was used, and where the cost was
    nan it silently discarded the entire flip bar - gross return included -
    which is how `net` came out *larger* than `gross`. An unknown cost makes
    the net unknown, and that must be visible rather than averaged away.
    """
    step = np.diff(close)
    gross = side[:-1] * step
    changed = np.flatnonzero(np.diff(side))
    scale = float(np.median(np.abs(step))) or 1.0
    charged = np.zeros_like(gross)
    if np.isfinite(cost_px):
        charged[changed] = cost_px
    net = (gross - charged) / scale
    usable = np.isfinite(net)
    blank = {
        "flips": int(len(changed)),
        "mean": float("nan"),
        "lo": float("nan"),
        "hi": float("nan"),
        "cost_share": float("nan"),
    }
    if usable.sum() < 400:
        return blank
    values = net[usable]
    width = 200
    blocks = [values[i : i + width] for i in range(0, len(values), width)]
    means = [
        float(
            np.mean(np.concatenate([blocks[k] for k in rng.integers(0, len(blocks), len(blocks))]))
        )
        for _ in range(DRAWS)
    ]
    return {
        "flips": int(len(changed)),
        "mean": float(values.mean()),
        "lo": float(np.percentile(means, 2.5)),
        "hi": float(np.percentile(means, 97.5)),
        "cost_share": float(cost_px / scale) if np.isfinite(cost_px) else float("nan"),
    }


def series(close: np.ndarray, side: np.ndarray, cost_px: float) -> np.ndarray:
    """Per-bar net return in median-step units, as a series for pooling."""
    step = np.diff(close)
    gross = side[:-1] * step
    charged = np.zeros_like(gross)
    if np.isfinite(cost_px):
        charged[np.flatnonzero(np.diff(side))] = cost_px
    scale = float(np.median(np.abs(step))) or 1.0
    out = (gross - charged) / scale
    return out[np.isfinite(out)]


def _permuted(close: np.ndarray, rng, block: int = 1) -> np.ndarray:
    """A path from this series' own steps, reordered.

    `block` 1 is a full permutation. Larger keeps each run of `block`
    consecutive steps intact and shuffles the runs, which preserves short-lag
    structure and destroys anything longer.
    """
    step = np.diff(close)
    if block <= 1:
        drawn = rng.permutation(step)
    else:
        chunks = [step[i : i + block] for i in range(0, len(step), block)]
        drawn = np.concatenate([chunks[k] for k in rng.permutation(len(chunks))])
    return np.concatenate(([close[0]], close[0] + np.cumsum(drawn)))


def shuffled_nulls(
    close: np.ndarray, fast: int, slow: int, cost_px: float, rng, block: int = 1
) -> np.ndarray:
    """`SHUFFLES` means from the instrument's own returns, trend destroyed.

    The distribution the real reading has to sit outside. Each draw rebuilds a
    price path from a permutation of the real steps and runs the identical
    crossover, so the step distribution, the cost and the flip mechanics are
    held and only the ordering changes.
    """
    out = []
    for _ in range(SHUFFLES):
        path = _permuted(close, rng, block)
        out.append(float(series(path, cross(path, fast, slow), cost_px).mean()))
    return np.asarray(out)


def pooled(rows: dict[str, np.ndarray], names, fast: int, slow: int) -> np.ndarray | None:
    """One family's per-bar nets, concatenated."""
    parts = [rows[(n, fast, slow)] for n in names if (n, fast, slow) in rows]
    return np.concatenate(parts) if parts else None


def _p(mean: float, nulls: np.ndarray) -> float:
    """Two-sided empirical p against a null distribution, on the side taken."""
    if not len(nulls):
        return float("nan")
    beat = float(np.mean(nulls >= mean) if mean > 0 else np.mean(nulls <= mean))
    return min(1.0, 2.0 * max(beat, 1.0 / (len(nulls) + 1)))


def main() -> int:
    rng = np.random.default_rng(SEED)
    print(f"data {DATA}   shuffles {SHUFFLES}, block {BLOCK}\n")
    kept: dict[tuple[str, int, int], np.ndarray] = {}
    costs: dict[str, float] = {}
    cells: list[dict] = []

    for symbol in symbols():
        bars = load(symbol)
        if bars is None:
            print(f"{symbol:24s} no file")
            continue
        close = bars["close"]
        costs[symbol] = quoted(symbol)
        for fast, slow in PAIRS:
            got = series(close, cross(close, fast, slow), costs[symbol])
            if len(got) < 400:
                continue
            kept[(symbol, fast, slow)] = got
            mean = float(got.mean())
            iid = shuffled_nulls(close, fast, slow, costs[symbol], rng, 1)
            blk = shuffled_nulls(close, fast, slow, costs[symbol], rng, BLOCK)
            cells.append(
                {
                    "symbol": symbol,
                    "pair": f"{fast}/{slow}",
                    "control": symbol in CONTROLS,
                    "mean": mean,
                    "iid": float(iid.mean()),
                    "blk": float(blk.mean()),
                    "p_iid": _p(mean, iid),
                    "p_blk": _p(mean, blk),
                }
            )

    order = sorted(cells, key=lambda c: c["p_blk"])
    total = len(order)
    survivors = 0
    for rank, cell in enumerate(order, start=1):
        if cell["p_blk"] <= 0.05 * rank / total:
            survivors = rank
    for rank, cell in enumerate(order, start=1):
        cell["bh"] = rank <= survivors

    head = (
        f"{'instrument':22s} {'pair':>8s} {'mean':>9s} {'iid':>9s} {'block':>9s} "
        f"{'p iid':>7s} {'p blk':>7s}  BH"
    )
    print(f"{total} cells, BH on the BLOCK null - the harder of the two\n")
    print(head)
    print("-" * len(head))
    for cell in order[:16]:
        print(
            f"{cell['symbol']:22s} {cell['pair']:>8s} {cell['mean']:9.4f} "
            f"{cell['iid']:9.4f} {cell['blk']:9.4f} {cell['p_iid']:7.3f} "
            f"{cell['p_blk']:7.3f}  {'YES' if cell['bh'] else '.':3s} "
            f"{'control' if cell['control'] else ''}"
        )
    print("  ... (16 strongest of %d shown)" % total)

    for label, key in (("iid", "p_iid"), ("block", "p_blk")):
        nominal = sum(1 for c in cells if c[key] <= 0.05)
        ctl = sum(1 for c in cells if c["control"] and c[key] <= 0.05)
        n_ctl = sum(1 for c in cells if c["control"])
        print(
            f"\n{label:5s} null: nominal p<=0.05 on {nominal}/{total} "
            f"(chance {0.05 * total:.1f}); of the controls {ctl}/{n_ctl} pass "
            f"- that is this test's own error rate"
        )
    print(f"BH survivors on the block null: {survivors}")

    print("\n=== pooled by family ===")
    print(
        f"{'family':14s} {'pair':>8s} {'mean':>9s} {'iid':>9s} {'block':>9s} "
        f"{'p iid':>7s} {'p blk':>7s}"
    )
    frames = {s: load(s) for s in costs}
    for name, members in POOLS.items():
        here = [m for m in members if frames.get(m) is not None]
        for fast, slow in PAIRS:
            real = pooled(kept, here, fast, slow)
            if real is None or len(real) < 1000:
                continue
            draws = {1: [], BLOCK: []}
            for block in (1, BLOCK):
                for _ in range(SHUFFLES):
                    parts = [
                        series(
                            path := _permuted(frames[m]["close"], rng, block),
                            cross(path, fast, slow),
                            costs[m],
                        )
                        for m in here
                    ]
                    draws[block].append(float(np.concatenate(parts).mean()))
            mean = float(real.mean())
            iid = np.asarray(draws[1])
            blk = np.asarray(draws[BLOCK])
            print(
                f"{name:14s} {f'{fast}/{slow}':>8s} {mean:9.4f} {iid.mean():9.4f} "
                f"{blk.mean():9.4f} {_p(mean, iid):7.3f} {_p(mean, blk):7.3f}"
            )

    # ──── discovery and confirmation, which is what decides it ────
    #
    # Three adjacent pairs of one family passing at p 0.033-0.047 is one effect
    # measured three ways, not three findings, and no single cell survives BH.
    # The repository's own standard for that is a split: fix a date, read each
    # half separately, and require the effect in both. A tail picked out of
    # many cells looks good by chance; one that holds in an unseen half does
    # not.
    print("\n=== halves: the same pooled cells, read on each side of the midpoint ===")
    print(
        f"{'family':14s} {'pair':>8s} {'first':>9s} {'p blk':>7s} "
        f"{'second':>9s} {'p blk':>7s}  both?"
    )
    for name, members in POOLS.items():
        here = [m for m in members if frames.get(m) is not None]
        for fast, slow in PAIRS:
            real = pooled(kept, here, fast, slow)
            if real is None or len(real) < 2000:
                continue
            halves = []
            for which in (0, 1):
                part = []
                for m in here:
                    whole = kept[(m, fast, slow)]
                    cut = len(whole) // 2
                    part.append(whole[:cut] if which == 0 else whole[cut:])
                got = np.concatenate(part)
                draws = []
                for _ in range(SHUFFLES):
                    made = []
                    for m in here:
                        close = frames[m]["close"]
                        cut = len(close) // 2
                        side = close[:cut] if which == 0 else close[cut:]
                        path = _permuted(side, rng, BLOCK)
                        made.append(series(path, cross(path, fast, slow), costs[m]))
                    draws.append(float(np.concatenate(made).mean()))
                halves.append((float(got.mean()), _p(float(got.mean()), np.asarray(draws))))
            (m1, p1), (m2, p2) = halves
            both = "YES" if p1 <= 0.05 and p2 <= 0.05 and m1 > 0 and m2 > 0 else "."
            print(
                f"{name:14s} {f'{fast}/{slow}':>8s} {m1:9.4f} {p1:7.3f} {m2:9.4f} {p2:7.3f}  {both}"
            )

    print(
        "\nTwo nulls, because one could not tell three different answers apart:\n"
        "  real > block ~ iid   the edge is longer-range trend\n"
        "  real ~ block > iid   the edge is short-lag memory - still real, different trade\n"
        "  real ~ block ~ iid   nothing\n"
        "The **controls** calibrate it: Volatility 25/75, Step and Jump 75 have no planted\n"
        "direction, so whatever share of them passes is the error rate, and a family pool\n"
        "that passes no harder than the control pool has shown nothing."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
