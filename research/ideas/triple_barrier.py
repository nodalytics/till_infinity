"""The triple barrier in state-space form: the vertical barrier is the only part
volatility can move.

Two bodies of work already cover most of this and neither is being rebuilt.

**`barrier-geometry-is-irrelevant.md`** proves, with 21 jump-diffusion
configurations at 40,000 paths each, that a barrier trade earns
`E[P&L] = mu E[tau]` with a market exit on both sides - **the geometry cancels
entirely.** So the triple barrier cannot produce expectancy from its shape, and
since every directional result on this desk is null against a matched control,
it cannot produce expectancy here at all.

That result **extends to the vertical barrier in one line.** `min(tau, T)` is a
bounded stopping time, so optional stopping still applies and
`E[X_min(tau,T)] = mu E[min(tau, T)]`. A time limit shortens the holding period
and changes nothing else. The third barrier is not a source of edge either.

**`trading/barriers.py`** ships the closed form - `P = (b+B)/(a+b+2B)` and
`E[bars] = (a+B)(b+B)` with the Broadie-Glasserman-Kou shift - plus
`SLOWER_ON_FEED`, a measured table of how much longer real trades take: 1.251x
at 2.5 predicted bars rising to **1.958x at 112, on 19 feeds out of 19**, while
Brownian feeds read a flat 1.047 to 1.111. Its mechanism is already named:
volatility mean-reverts, first-passage time is **convex in `1/sigma`**, so
stretches where volatility falls lengthen a trade by more than stretches where
it rises shorten it.

## What is left, and why it is a state-space question

`slowdown(bars)` is keyed on **predicted bars and nothing else**, and its own
docstring says "this is five points and an interpolation, not a law". But the
mechanism it corrects for is **conditional**: how far a trade's volatility has
to revert depends on where that volatility currently sits relative to its own
mean, not only on how long the trade lasts.

**So the prediction, written before running.**

1. **The label is invariant and the duration is not.** With zero drift,
   `P(up first)` is gambler's ruin - `b/(a+b)` - **whatever the volatility
   path**, constant or not, because the time change is a bijection. So
   volatility prediction cannot change *which* barrier is hit, only *when*.
   Anyone trying to predict the triple-barrier label from a volatility model is
   predicting a constant.
2. **The vertical barrier is the exception**, and the only one.
   `P(resolved by T)` depends entirely on how much variance accumulates by `T`,
   which is exactly what a `Q` model predicts. `groundbarrier.py` already notes
   that dropping unresolved trials is a selection concentrated in quiet
   periods - this makes that share the measurement rather than the nuisance.
3. **`slowdown` is conditionally biased.** A trade entered when volatility is
   *above* its own mean should run **longer** than the table says, and one
   entered below it **shorter**, because the table averages over both. If the
   realised-over-predicted ratio is flat across entry-volatility buckets, the
   table is right and this is a null.
4. **The clock should flatten it.** Replacing the entry volatility with the
   integrated variance `seasonal.Profile` predicts over the holding horizon
   should move the ratio toward 1.0 - and should buy **nothing** on the Deriv
   generated feeds, where volatility is constant and the Brownian form is
   already exact.

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.structures.statespace.seasonal import Profile
from till_infinity.trading.barriers import duration, shift_for, slowdown

HOUR = 3600.0
SEED = 20261012

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD")
#: Constant volatility by construction, and the feeds where `trading/barriers.py`
#: already measures its own form as exact.
GENERATED = ("Volatility_75_Index", "Volatility_25_Index", "Step_Index", "Jump_100_Index")
FRAME = os.environ.get("FRAME", "1h")
#: Geometries as `(target, stop)` in entry-volatility units. Spread to cover the
#: range `SLOWER_ON_FEED` was measured over - 2.5 to 112 predicted bars.
GEOMETRIES = ((1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (2.0, 6.0), (6.0, 2.0), (10.0, 10.0))
#: Bars of trailing returns for the entry volatility estimate, and for the mean
#: it is compared against.
SPAN = int(os.environ.get("SPAN", "48"))
LONG = int(os.environ.get("LONG", "480"))
#: The vertical barrier, in multiples of the *predicted* duration. Finite on
#: purpose: the point is what times out.
VERTICAL = float(os.environ.get("VERTICAL", "3.0"))
TICKS = float(os.environ.get("TICKS", "30.0"))
SINCE = float(os.environ.get("SINCE", "99792000"))
LIMIT = int(os.environ.get("LIMIT", "40000"))
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str = FRAME):
    import numpy as np

    path = CACHE / f"{name}.{frame}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        if not {"time", "close", "high", "low"} <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {
            k: np.asarray(bundle[k], dtype=float)[order] for k in ("time", "close", "high", "low")
        }
    keep = (got["close"] > 0) & (got["time"] >= SINCE)
    got = {k: v[keep] for k, v in got.items()}
    if len(got["time"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got if len(got["time"]) > 3000 else None


# ------------------------------------------------------------------- arm one


def invariance(n: int = 40000, seed: int = SEED):
    """Is `P(up first)` really invariant to the volatility path? Simulated.

    Three volatility paths with the **same** barriers in absolute terms: flat,
    a ramp, and a two-regime step. Zero drift. Gambler's ruin says every one of
    them gives `b/(a+b)` for the unbounded problem, while `E[tau]` differs by
    whatever the paths' integrated variances differ by.

    The arm exists because the whole contribution depends on it: if the label
    moved with volatility, volatility prediction would be a label model, and
    this says it is a *timing* model and nothing else.
    """
    rng = random.Random(seed)
    up, down = 2.0, 4.0
    out = {}
    for label, scale in (
        ("flat", lambda i: 1.0),
        ("ramp", lambda i: 0.3 + 1.4 * (i / 4000.0 if i < 4000 else 1.0)),
        ("step", lambda i: 0.4 if (i // 300) % 2 == 0 else 1.6),
    ):
        hits, durations, unresolved = 0, [], 0
        for _ in range(n):
            level, step = 0.0, 0
            while True:
                level += rng.gauss(0.0, 0.1 * scale(step))
                step += 1
                if level >= up:
                    hits += 1
                    durations.append(step)
                    break
                if level <= -down:
                    durations.append(step)
                    break
                if step > 400000:
                    unresolved += 1
                    break
        out[label] = {
            "p_up": hits / max(n - unresolved, 1),
            "bars": statistics.fmean(durations) if durations else float("nan"),
        }
    out["theory_p_up"] = down / (up + down)
    return out


# ------------------------------------------------------------------- the trials


def trials(series, target: float, stop: float, profile=None, weight: float = 1.0):
    """Walk forward, open a trade every `step` bars, record what resolved it.

    Barriers are placed in units of the **entry** volatility estimate, which is
    what `trading/barriers.py` is given in production, and the realised
    duration is counted in bars. The vertical barrier is `VERTICAL` times the
    predicted duration, so a time-out means the trade ran materially long
    rather than merely longer than average.

    Returns one row per trade with the entry volatility's position relative to
    its own longer mean - the conditioning variable the production `slowdown`
    does not have.
    """
    import numpy as np

    closes, highs, lows = series["close"], series["high"], series["low"]
    times = series["time"]
    moves = np.diff(np.log(closes))
    n = len(moves)
    predicted = duration(target, stop, ticks_per_bar=TICKS)
    cap = int(max(VERTICAL * predicted, 4.0))
    step = max(int(predicted / 2.0), 4)

    rows = []
    at = LONG
    while at + cap + 1 < n:
        window = moves[at - SPAN : at]
        longer = moves[at - LONG : at]
        sigma = float(np.std(window))
        middle = float(np.std(longer))
        if sigma <= 0.0 or middle <= 0.0:
            at += step
            continue
        # **Shrinkage toward the longer mean, geometric because volatility is
        # closer to log-normal than normal.** `weight = 1` is production: size
        # the barriers from the short estimate alone. The controls say most of
        # the conditional bias in `slowdown` is regression in this estimate
        # rather than mean reversion in the market, and if that is right then
        # shrinking it - not forecasting it - is the fix.
        used = sigma if weight >= 1.0 else sigma**weight * middle ** (1.0 - weight)
        entry = float(closes[at])
        up_at = entry * math.exp(target * used)
        down_at = entry * math.exp(-stop * used)
        took, which = 0, "none"
        for k in range(at + 1, min(at + 1 + cap, len(closes))):
            took = k - at
            if highs[k] >= up_at:
                which = "up"
                break
            if lows[k] <= down_at:
                which = "down"
                break
        else:
            took = cap
        # What the clock expects the *next* `cap` bars' variance to be,
        # relative to the trailing window the barriers were sized from. The
        # ratio is what would rescale the predicted duration.
        expected = 1.0
        if profile is not None:
            ahead = [
                float(profile.factor(float(times[min(at + j, len(times) - 1)])))
                for j in range(1, cap + 1)
            ]
            behind = [float(profile.factor(float(times[at - j]))) for j in range(1, SPAN + 1)]
            if behind and ahead and statistics.fmean(behind) > 0:
                expected = statistics.fmean(ahead) / statistics.fmean(behind)
        rows.append(
            {
                "which": which,
                "bars": took,
                "predicted": predicted,
                "sigma": sigma,
                "used": used,
                # **The conditioning variable.** Where the entry volatility sits
                # against its own longer mean, in logs so it is symmetric.
                "position": math.log(sigma / middle),
                "expected": expected,
            }
        )
        at += step
    return rows


def buckets(rows, key="position", count=5):
    """Split into `count` equal-sized bands by `key`, lowest first."""
    usable = [r for r in rows if math.isfinite(r[key])]
    if len(usable) < count * 20:
        return []
    order = sorted(usable, key=lambda r: r[key])
    size = len(order) // count
    return [order[i * size : (i + 1) * size] for i in range(count)]


def summarise(band):
    """Realised over predicted, the table's own figure, and the timed-out share."""
    if not band:
        return None
    predicted = statistics.fmean(r["predicted"] for r in band)
    resolved = [r for r in band if r["which"] != "none"]
    return {
        "n": len(band),
        "predicted": predicted,
        "ratio": statistics.fmean(r["bars"] for r in band) / predicted,
        "table": slowdown(predicted),
        "timed_out": sum(1 for r in band if r["which"] == "none") / len(band),
        "p_up": (
            sum(1 for r in resolved if r["which"] == "up") / len(resolved)
            if resolved
            else float("nan")
        ),
        "expected": statistics.fmean(r["expected"] for r in band),
    }


def main() -> None:
    print(
        f"frame {FRAME}, span {SPAN}, long {LONG}, vertical {VERTICAL}x predicted,\n"
        f"ticks per bar {TICKS}, geometries {GEOMETRIES}\n"
        "'ratio' is realised over predicted bars; 'table' is what production's\n"
        "`slowdown` says for that predicted duration. The question is whether\n"
        "the ratio is flat across entry-volatility buckets, which is what a\n"
        "table keyed on predicted bars alone assumes.\n"
    )

    print("=" * 108)
    print("ARM 1  is the label invariant to the volatility path? Simulated, zero drift.")
    print("=" * 108)
    got = invariance()
    print(f"barriers +2.0 / -4.0, so gambler's ruin says P(up) = {got['theory_p_up']:.4f}\n")
    print(f"{'vol path':<12}{'P(up first)':>13}{'vs theory':>11}{'mean bars':>12}")
    for label in ("flat", "ramp", "step"):
        row = got[label]
        print(
            f"{label:<12}{row['p_up']:>13.4f}{row['p_up'] - got['theory_p_up']:>+11.4f}"
            f"{row['bars']:>12.0f}"
        )
    print(
        "\nIf the three P(up) agree and the bar counts do not, volatility is a\n"
        "timing model for the barrier problem and not a label model."
    )

    print("\n" + "=" * 108)
    print("ARM 2  is production's slowdown conditionally biased? By entry-volatility bucket")
    print("=" * 108)
    collected: dict[str, list] = {}
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        print(f"\n--- {group} ---")
        print(
            f"{'instrument':<22}{'geom':<10}{'pred':>7}{'table':>7}"
            f"{'lowest vol':>12}{'q2':>8}{'q3':>8}{'q4':>8}{'highest':>9}{'spread':>8}"
        )
        for name in names:
            series = load(name)
            if series is None:
                continue
            for target, stop in GEOMETRIES:
                rows = trials(series, target, stop)
                bands = buckets(rows)
                if not bands:
                    continue
                parts = [summarise(b) for b in bands]
                if any(p is None for p in parts):
                    continue
                ratios = [p["ratio"] for p in parts]
                print(
                    f"{name:<22}{f'{target:g}/{stop:g}':<10}{parts[0]['predicted']:>7.1f}"
                    f"{parts[0]['table']:>7.2f}"
                    + "".join(f"{r:>8.2f}" if i else f"{r:>12.2f}" for i, r in enumerate(ratios))
                    + f"{ratios[-1] - ratios[0]:>+8.2f}"
                )
                collected.setdefault(group, []).append(
                    {"ratios": ratios, "table": parts[0]["table"], "parts": parts}
                )

    print("\n" + "=" * 108)
    print("ARM 3  the verdict, and the vertical barrier")
    print("=" * 108)
    print(
        f"{'group':<12}{'cells':>7}{'med lowest':>12}{'med highest':>13}"
        f"{'med spread':>12}{'med table':>11}{'timed out low':>15}{'high':>8}"
    )
    for group in ("traded", "generated"):
        cells = collected.get(group, [])
        if not cells:
            continue
        print(
            f"{group:<12}{len(cells):>7}"
            f"{statistics.median(c['ratios'][0] for c in cells):>12.2f}"
            f"{statistics.median(c['ratios'][-1] for c in cells):>13.2f}"
            f"{statistics.median(c['ratios'][-1] - c['ratios'][0] for c in cells):>+12.2f}"
            f"{statistics.median(c['table'] for c in cells):>11.2f}"
            f"{statistics.median(c['parts'][0]['timed_out'] for c in cells):>15.2f}"
            f"{statistics.median(c['parts'][-1]['timed_out'] for c in cells):>8.2f}"
        )
    print("\nP(up) by bucket - should be flat if arm 1's invariance holds on real data:")
    print(f"{'group':<12}{'lowest vol':>12}{'highest':>10}{'spread':>9}")
    for group in ("traded", "generated"):
        cells = collected.get(group, [])
        if not cells:
            continue
        low = statistics.median(c["parts"][0]["p_up"] for c in cells)
        high = statistics.median(c["parts"][-1]["p_up"] for c in cells)
        print(f"{group:<12}{low:>12.3f}{high:>10.3f}{high - low:>+9.3f}")
    print("\n" + "=" * 108)
    print("ARM 4  does shrinking the entry estimate flatten it? Sweeping the weight")
    print("=" * 108)
    print(
        "The controls say most of the conditional bias is regression in the\n"
        "volatility *estimate*, not mean reversion in the market - a constant-\n"
        "volatility feed cannot have the latter and shows +0.43 of the +0.61.\n"
        "If that is right, the fix is to shrink the estimate toward its longer\n"
        "mean, geometrically. weight 1.0 is production. The spread should\n"
        "collapse; the level should stay near the table's own figure.\n"
    )
    print(
        f"{'group':<12}{'weight':>8}{'cells':>7}{'med lowest':>12}{'med highest':>13}"
        f"{'med spread':>12}{'med level':>11}{'timed out':>11}"
    )
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        for weight in (1.0, 0.7, 0.5, 0.3, 0.0):
            cells = []
            for name in names:
                series = load(name)
                if series is None:
                    continue
                for target, stop in GEOMETRIES:
                    rows = trials(series, target, stop, weight=weight)
                    bands = buckets(rows)
                    if not bands:
                        continue
                    parts = [summarise(b) for b in bands]
                    if any(p is None for p in parts):
                        continue
                    cells.append(parts)
            if not cells:
                continue
            lows = [c[0]["ratio"] for c in cells]
            highs = [c[-1]["ratio"] for c in cells]
            print(
                f"{group:<12}{weight:>8.1f}{len(cells):>7}"
                f"{statistics.median(lows):>12.2f}{statistics.median(highs):>13.2f}"
                f"{statistics.median(h - l for l, h in zip(lows, highs, strict=True)):>+12.2f}"
                f"{statistics.median(statistics.fmean(p['ratio'] for p in c) for c in cells):>11.2f}"
                f"{statistics.median(statistics.fmean(p['timed_out'] for p in c) for c in cells):>11.3f}"
            )
        print()

    print("\n" + "=" * 108)
    print("ARM 5  the derived correction, and whether it matches the buckets")
    print("=" * 108)
    print(
        "Barriers are placed at `k * sigma_e` in absolute terms, so in units of\n"
        "the *realised* volatility they sit at `k * sigma_e / sigma_r`, and\n"
        "E[tau] = (a+B)(b+B) scales as `(sigma_e / sigma_r)^2`. With\n"
        "`sigma_r = sigma_e^w * middle^(1-w)` that is\n\n"
        "    correction = (sigma_e / middle) ** (2 * (1 - w))\n\n"
        "so the exponent is **1.0 at the measured w = 0.5** on traded feeds and\n"
        "**2.0 at w = 0.0** on the generated ones. This leaves the trade alone\n"
        "and corrects only the duration, which is the less invasive fix: the\n"
        "label is invariant, so `probability` needs nothing.\n"
    )
    print(
        f"{'group':<12}{'bucket':<9}{'sigma_e/mid':>13}{'observed':>10}{'exp 1.0':>9}{'exp 2.0':>9}"
    )
    for group, names, exponent in (("traded", TRADED, 1.0), ("generated", GENERATED, 2.0)):
        gathered: list[list] = []
        for name in names:
            series = load(name)
            if series is None:
                continue
            for target, stop in GEOMETRIES:
                rows = trials(series, target, stop)
                bands = buckets(rows)
                if not bands:
                    continue
                parts = []
                for band in bands:
                    got = summarise(band)
                    if got is None:
                        parts = []
                        break
                    got["position"] = statistics.median(r["position"] for r in band)
                    parts.append(got)
                if parts:
                    gathered.append(parts)
        if not gathered:
            continue
        # Normalise both the observation and the prediction to the middle
        # bucket, because the overall level carries the truncation from the
        # vertical barrier and only the *shape* across buckets is being tested.
        for i, label in enumerate(("lowest", "q2", "q3", "q4", "highest")):
            ratios = [c[i]["ratio"] / c[2]["ratio"] for c in gathered]
            scales = [math.exp(c[i]["position"] - c[2]["position"]) for c in gathered]
            middle = statistics.median(scales)
            print(
                f"{group if not i else '':<12}{label:<9}{middle:>13.3f}"
                f"{statistics.median(ratios):>10.3f}"
                f"{middle**1.0:>9.3f}{middle**2.0:>9.3f}"
            )
        print()
    print(
        "The column matching 'observed' is the exponent the data wants, and it\n"
        "should be 1.0 for traded and 2.0 for generated if arm 4's weights are\n"
        "the right ones. Normalised to the middle bucket throughout."
    )

    print("\nDONE")


if __name__ == "__main__":
    main()
