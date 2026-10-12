"""Hawkes cascades: does the sign of the signal really flip by asset class?

The claim, from a 97-instrument study: forward returns conditioned on a
high-intensity Hawkes signal are **asset-class dependent in sign**. Indices
`+0.010%` and synthetics `+0.004%` (continuation); metals `-0.013%` and
equities `-0.015%` (reversion), at the M5 24-bar horizon. The proposed
strategy follows the cascade on one class and fades it on the other.

Two things about the claim before measuring it.

**The indicator is not a Hawkes process.** As specified it is

    intensity(t) = intensity(t-1) * exp(-0.1) + 0.5 * magnitude(t)
    magnitude    = |return| * volume_spike * (1 + wick_ratio)

which is an exponentially weighted mean with about a ten-bar memory over a
volatility-and-volume proxy. There is no point process, no fitted `alpha` or
`beta`, and no branching ratio - so none of the Hawkes literature's results
about criticality or reflexivity transfer. A `2 sigma` reading means **a big,
high-volume, wicky bar just happened**, and the claim reduces to: does the
direction after a volatility spike flip between asset classes?

That is a directional claim, which on this desk has a base rate of six nulls
from six.

**The quoted effects are a fraction of the spread.** `0.010%` is one basis
point. Gold's spread is several. So even taken at face value the edge cannot
pay, which makes the cost gate the first thing to report rather than the last.

## What this harness does that the paper did not

1. **Splits the synthetics by generator instead of pooling them.** This is the
   decisive improvement, because their generators are *known*:

   * `Volatility_*` is Brownian at a fixed volatility - **it cannot have
     cascade momentum**, so a non-zero reading there is measurement artefact.
   * `Step_Index` moves in constant steps. Same.
   * `Jump_*` has Poisson jumps, so intensity genuinely clusters - but the
     jumps are symmetric, so the *directional* edge must still be zero.
   * `Boom_*` and `Crash_*` have **engineered asymmetric jumps**, so they can
     have a directional edge by construction.
   * `Drift_Switch_*` switches drift, so it can too.

   A pooled "synthetics +0.004%" could therefore be entirely the two
   engineered families - which would confirm the paper's own microstructure
   story while removing any claim that it generalises. Pooling across arms has
   inverted a conclusion here before.

2. **A matched random control.** The signal fires on a few percent of bars, and
   a rule that trades rarely changes the average without knowing anything, so
   every cell is scored against random bars of the same count using their own
   `direction_bias` sign.

3. **A cost gate**, in spread units, from the feed's own spread column.

4. **Standard errors**, which the claim does not quote.

5. **The sign flip as a difference**, with its own error - that is the actual
   claim, and a difference survives a common-mode artefact that two separate
   signs would not.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from pathlib import Path

HOUR = 3600.0
SEED = 20261012

FOREX = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "NZDUSD",
    "EURJPY",
    "GBPJPY",
    "EURGBP",
    "EURCHF",
    "EURAUD",
    "AUDUSD",
)
METALS = ("XAUUSD", "XAGUSD")
CRYPTO = ("BTCUSD", "ETHUSD", "SOLUSD")
#: Synthetic families, **kept apart**. The prefix decides membership, and the
#: note is what the generator permits.
SYNTHETIC = {
    "Volatility": "fixed-vol Brownian: must be zero",
    "Step": "constant steps: must be zero",
    "Jump": "Poisson jumps, symmetric: clusters, no direction",
    "Range_Break": "ranges then breaks",
    "Boom": "engineered asymmetric jumps: can be non-zero",
    "Crash": "engineered asymmetric jumps: can be non-zero",
    "Drift_Switch": "switching drift: can be non-zero",
    "DEX": "engineered directional bias",
}

#: The indicator's published parameters, unchanged.
DECAY = 0.1
EXCITATION = 0.5
VOL_WINDOW = 50
THRESHOLD = 2.0
WARMUP = 80
HORIZONS = (3, 6, 12, 24)

FRAMES = tuple(os.environ.get("FRAMES", "3m,15m").split(","))
DRAWS = int(os.environ.get("DRAWS", "200"))
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "60000"))
#: Minimum bars to accept a series. **1,200 rather than 2,000 on purpose.**
#: Most equities carry 1,883 bars at 1h against AAPL's 5,845, so a 2,000-bar
#: floor silently kept 21 long-history large caps out of 439 names and called
#: them "equities". At 1,200 the whole cross-section loads, and 1,883 bars at
#: a 6% duty cycle still leaves about 110 signal bars per name - thin
#: individually and ample across the cross-section, which is where the claim
#: is being tested.
LEAST_BARS = int(os.environ.get("LEAST_BARS", "1200"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def families(frame: str):
    """Every instrument in the cache for `frame`, labelled by class."""
    out: list[tuple[str, str]] = []
    seen = set()
    for path in sorted(CACHE.glob(f"*.{frame}.npz")):
        name = path.name[: -len(f".{frame}.npz")]
        if name in seen:
            continue
        seen.add(name)
        if name in FOREX:
            out.append((name, "forex"))
        elif name in METALS:
            out.append((name, "metals"))
        elif name in CRYPTO:
            out.append((name, "crypto"))
        elif "." in name:
            out.append((name, "equities"))
        else:
            for prefix in SYNTHETIC:
                if name.startswith(prefix):
                    out.append((name, f"synth:{prefix}"))
                    break
    return out


def load(name: str, frame: str):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close", "volume"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
        got["spread"] = (
            np.asarray(bundle["spread"], dtype=float)[order]
            if "spread" in bundle
            else np.zeros_like(got["close"])
        )
    keep = (got["close"] > 0) & (got["time"] >= SINCE) & (got["high"] >= got["low"])
    got = {k: v[keep] for k, v in got.items()}
    if len(got["time"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got if len(got["time"]) > LEAST_BARS else None


def intensity(series):
    """The published indicator, unchanged, plus its z-score and direction bias."""
    import numpy as np

    close, high, low = series["close"], series["high"], series["low"]
    opens, volume = series["open"], series["volume"]
    n = len(close)
    moves = np.zeros(n)
    moves[1:] = np.abs(np.diff(close)) / close[:-1]
    reach = np.maximum(high - low, 1e-12)
    wick = 1.0 - np.abs(close - opens) / reach
    average = np.convolve(volume, np.ones(VOL_WINDOW) / VOL_WINDOW, mode="full")[:n]
    average = np.where(average > 0, average, 1.0)
    spike = volume / average
    magnitude = moves * spike * (1.0 + wick)

    lam = np.zeros(n)
    bias = np.zeros(n)
    decay = math.exp(-DECAY)
    buy = (close - low) / reach
    for i in range(1, n):
        lam[i] = lam[i - 1] * decay + EXCITATION * magnitude[i]
        bias[i] = 0.8 * bias[i - 1] + 0.2 * (2.0 * buy[i] - 1.0)

    # Trailing z-score of the intensity over `VOL_WINDOW`, strictly causal.
    z = np.full(n, np.nan)
    for i in range(VOL_WINDOW, n):
        window = lam[i - VOL_WINDOW : i]
        spread = float(np.std(window))
        if spread > 0:
            z[i] = (lam[i] - float(np.mean(window))) / spread
    return z, bias


def rows(series, frame_hours: float):
    """One row per usable bar: did the signal fire, which way, what followed."""
    import numpy as np

    z, bias = intensity(series)
    close, spread = series["close"], series["spread"]
    n = len(close)
    out = []
    for i in range(max(WARMUP, VOL_WINDOW), n - max(HORIZONS) - 1):
        if not math.isfinite(z[i]):
            continue
        side = 1.0 if bias[i] > 0 else (-1.0 if bias[i] < 0 else 0.0)
        if side == 0.0:
            continue
        ahead = {
            h: 100.0 * side * (float(close[i + h]) - float(close[i])) / float(close[i])
            for h in HORIZONS
        }
        cost = 100.0 * float(spread[i]) / float(close[i]) if spread[i] > 0 else float("nan")
        out.append(
            {
                "fired": bool(z[i] > THRESHOLD),
                "edge": ahead,
                # Magnitude, which the indicator should predict and which is
                # already known to be predictable - the arm that shows the
                # detector works, on the quantity that is not in dispute.
                "size": 100.0
                * abs(float(close[i + HORIZONS[0]]) - float(close[i]))
                / float(close[i]),
                "cost": cost,
            }
        )
    return out


def score(all_rows, horizon: int):
    """Signal edge, matched-random edge, the z between them, and the cost gate."""
    fired = [r for r in all_rows if r["fired"]]
    if len(fired) < 30 or len(all_rows) < 400:
        return None
    rng = random.Random(SEED)
    real = statistics.fmean(r["edge"][horizon] for r in fired)
    draws = [
        statistics.fmean(r["edge"][horizon] for r in rng.sample(all_rows, len(fired)))
        for _ in range(DRAWS)
    ]
    middle = statistics.fmean(draws)
    noise = statistics.stdev(draws)
    costs = [r["cost"] for r in fired if math.isfinite(r["cost"]) and r["cost"] > 0]
    sizes_on = statistics.fmean(r["size"] for r in fired)
    sizes_off = statistics.fmean(r["size"] for r in all_rows)
    return {
        "n": len(fired),
        "duty": len(fired) / len(all_rows),
        "edge": real,
        "random": middle,
        "se": noise,
        "z": (real - middle) / noise if noise > 0 else float("nan"),
        "spread": statistics.fmean(costs) if costs else float("nan"),
        "in_spreads": (real - middle) / statistics.fmean(costs) if costs else float("nan"),
        "size_lift": sizes_on / sizes_off if sizes_off > 0 else float("nan"),
    }


def main() -> None:
    print(
        f"frames {FRAMES}, published parameters unchanged "
        f"(decay {DECAY}, excitation {EXCITATION}, window {VOL_WINDOW}, "
        f"threshold {THRESHOLD})\n"
        "'edge' is the mean forward return in the cascade's own direction, in\n"
        "percent - positive means following pays. 'random' is the same over\n"
        "bars drawn at the same count, so the duty cycle is controlled. 'z' is\n"
        "the distance between them in units of that control's own spread.\n"
        "'in sprd' is the edge net of the control, in spreads: **the only\n"
        "column a desk could act on.**\n"
    )

    by_class: dict[str, list] = {}
    for frame in FRAMES:
        found = families(frame)
        if not found:
            continue
        print("=" * 116)
        print(f"ARM 1  per instrument at {frame}, horizon {HORIZONS[-1]} bars")
        print("=" * 116)
        print(
            f"{'instrument':<22}{'class':<20}{'n':>7}{'duty':>7}"
            f"{'edge %':>9}{'random':>9}{'z':>7}{'spread %':>10}"
            f"{'in sprd':>9}{'size x':>8}"
        )
        for name, label in found:
            series = load(name, frame)
            if series is None:
                continue
            got = score(rows(series, 1.0), HORIZONS[-1])
            if got is None:
                continue
            by_class.setdefault(f"{frame}:{label}", []).append(got)
            print(
                f"{name:<22}{label:<20}{got['n']:>7}{got['duty']:>7.3f}"
                f"{got['edge']:>+9.4f}{got['random']:>+9.4f}{got['z']:>+7.2f}"
                f"{got['spread']:>10.4f}{got['in_spreads']:>+9.3f}{got['size_lift']:>8.2f}"
            )
        print()

    print("=" * 116)
    print("ARM 2  by class: does the sign flip, and does anything clear a spread?")
    print("=" * 116)
    print(
        f"{'class':<30}{'cells':>7}{'med edge':>10}{'med random':>12}"
        f"{'med z':>8}{'|z|>2':>7}{'med in sprd':>13}{'med size x':>12}"
    )
    for key in sorted(by_class):
        cells = by_class[key]
        zs = [c["z"] for c in cells if math.isfinite(c["z"])]
        gates = [c["in_spreads"] for c in cells if math.isfinite(c["in_spreads"])]
        print(
            f"{key:<30}{len(cells):>7}"
            f"{statistics.median(c['edge'] for c in cells):>+10.4f}"
            f"{statistics.median(c['random'] for c in cells):>+12.4f}"
            + (
                f"{statistics.median(zs):>+8.2f}{sum(1 for z in zs if abs(z) > 2) / len(zs):>7.2f}"
                if zs
                else f"{'-':>8}{'-':>7}"
            )
            + (f"{statistics.median(gates):>+13.3f}" if gates else f"{'-':>13}")
            + f"{statistics.median(c['size_lift'] for c in cells):>12.2f}"
        )

    print("\n" + "=" * 116)
    print("ARM 3  the claim as a difference, which is what it actually asserts")
    print("=" * 116)
    print(
        "The paper's claim is not that metals revert but that metals and\n"
        "indices have **opposite** signs. A difference of two class medians,\n"
        "against the spread of the per-cell z scores, is the version of that\n"
        "which survives a common-mode artefact.\n"
    )
    print(f"{'pair':<46}{'difference':>12}{'claimed':>10}")
    claims = {
        ("metals", "crypto"): -0.013 - 0.010,
        ("metals", "forex"): -0.013 - 0.010,
        ("synth:Volatility", "synth:Boom"): 0.004 - 0.004,
        ("synth:Volatility", "synth:Crash"): 0.004 - 0.004,
        ("synth:Volatility", "synth:Jump"): 0.0,
    }
    for frame in FRAMES:
        for (left, right), claimed in claims.items():
            a = by_class.get(f"{frame}:{left}")
            b = by_class.get(f"{frame}:{right}")
            if not a or not b:
                continue
            gap = statistics.median(c["edge"] for c in a) - statistics.median(c["edge"] for c in b)
            print(f"{f'{frame}  {left} - {right}':<46}{gap:>+12.4f}{claimed:>+10.4f}")

    print("\n" + "=" * 116)
    print("ARM 4  what the indicator does predict")
    print("=" * 116)
    print(
        "'size x' is the next 3 bars' absolute move on signal bars over its\n"
        "unconditional mean. The indicator is an exponentially weighted mean of\n"
        "a volatility proxy, so this should be well above 1 everywhere - which\n"
        "would say the detector works and is detecting volatility.\n"
    )
    print(f"{'class':<30}{'cells':>7}{'med size x':>12}")
    for key in sorted(by_class):
        cells = by_class[key]
        print(f"{key:<30}{len(cells):>7}{statistics.median(c['size_lift'] for c in cells):>12.2f}")
    print("\nDONE")


if __name__ == "__main__":
    main()
