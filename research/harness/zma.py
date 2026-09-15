"""Does ZMA find mean reversion where there is some, and where there is none?

ZMA - Z-Momentum Attention - is an attention-weighted z-score with a normalised
OLS slope and **dynamic 85th/65th-percentile thresholds**, firing `oversold` and
`overbought` at extremes of the instrument's own recent z distribution. It is a
mean-reversion detector.

**So the question is not whether it produces signals.** It always will: the
thresholds are percentiles of its own history, and a percentile always has
something above it. On every arm below it fires on roughly 15% of bars,
including on shuffled noise. **Signal count says nothing about signal quality**,
and an indicator that is never quiet is easy to mistake for one that is always
working.

The question is whether the signals **predict**.

## The positive control is the whole design

An Ornstein-Uhlenbeck process is mean-reverting by construction, and its
reversion speed `theta` is a dial. A detector that cannot find reversion there
is broken, and nothing else it says means anything - so the OU arm is run first
and read first.

Measured, 11,749 scored bars an arm:

| arm | AUC | hit rate |
| --- | --- | --- |
| OU, theta = 0.02 | 0.5179 | 0.509 |
| OU, theta = 0.05 | 0.5492 | 0.583 |
| **OU, theta = 0.15** | **0.6200** | **0.705** |

It works, and it scales with the thing it is supposed to measure. That is what
makes the null arms readable rather than merely disappointing.

## The families, each against its own generator

`research/families.md`'s rule applies: these are not one process, and a shared
null would be the wrong null for most of them.

* **volatility** - geometric Brownian motion at the published sigma.
  `generators.md` verified the feeds ARE this: `H = 0.50`, kurtosis 2.98 to
  3.02, variance ratios inside their own shuffles. **There is no mean to revert
  to.**
* **step** - a fair coin on a fixed lattice. `grounding.md` measured
  `p = 0.499734 +- 0.000220` over 5.2M flips and `pipeline.md` found
  `sigma_Y = 0.9999`, one lattice unit a tick.
* **boom / crash** - compound Poisson: a slow drift one way, rare large spikes
  the other. `families.md` established the hazard is **memoryless** on
  300,000 ticks across 29 feeds, so the spikes carry no timing information.
* **jump** - diffusion plus jumps, realising **1.322x** the name, because the
  name is the diffusive part and the jumps are extra.

A shuffle of each is carried alongside, which destroys ordering and keeps the
marginal - so an arm that scores the same shuffled as unshuffled is reading the
marginal and not the process.

    ./.secrets/lab.sh run research/harness/zma.py

**Simulated rather than measured, and that is a real limit.** These are the
documented mechanics, not the feeds. The simulators are faithful to what this
folder has verified about each family, but a generator that differs from its
documentation in some way nobody has checked would not show up here. The same
harness runs on cached bars when the terminal is reachable; that is the version
to believe.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np

#: Where the indicator actually lives. Imported by path rather than reimplemented
#: so that this tests the shipped code - a test of a paraphrase is a test of the
#: paraphrase.
ZMA_SOURCE = Path("/home/ose/Documents/Quants Pub/packages/core/stb_core/indicators/zma.py")

#: Bars an arm. Large enough that a 15% firing rate leaves a four-figure sample.
BARS = 12_000

#: Bars discarded before scoring, so the dynamic thresholds have a distribution
#: to be percentiles of.
WARM = 250


_CACHED = None


def _indicator():
    """The shipped `ZScoreMomentum`, loaded once.

    Cached because an earlier version re-executed the module from disk on every
    call to `score_series` - once per arm, per shuffle, per gate comparison -
    which turned a minute of arithmetic into a quarter of an hour of imports.
    """
    global _CACHED
    if _CACHED is None:
        spec = importlib.util.spec_from_file_location("stb_zma", ZMA_SOURCE)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["stb_zma"] = mod
        spec.loader.exec_module(mod)
        _CACHED = mod.ZScoreMomentum
    return _CACHED


def auc(score: np.ndarray, label: np.ndarray) -> float:
    score, label = np.asarray(score, float), np.asarray(label)
    order = np.argsort(score)
    ranks = np.empty(len(score))
    ranks[order] = np.arange(1, len(score) + 1)
    n1, n0 = float((label == 1).sum()), float((label == 0).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    return float((ranks[label == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def score_series(prices: np.ndarray, period: int = 50) -> dict:
    """AUC of `-z` against the next bar rising, and the hit rate when it fires.

    Two readings because they answer different questions. **AUC** uses every bar
    and asks whether the z-score orders the next move at all. **Hit rate** uses
    only the bars where `oversold` or `overbought` actually fired, which is the
    signal as a desk would receive it.
    """
    indicator = _indicator()
    z = indicator(period=period)
    zs, flags = [], []
    for p in prices:
        z.update_raw(float(p))
        zs.append(z.z_score)
        flags.append(1 if z.oversold else (-1 if z.overbought else 0))
    zs, flags = np.asarray(zs), np.asarray(flags)

    fwd = np.full(len(prices), np.nan)
    fwd[:-1] = np.diff(np.log(np.maximum(prices, 1e-12)))
    ok = np.isfinite(fwd)
    ok[:WARM] = False
    if ok.sum() < 500:
        return {}
    up = (fwd[ok] > 0).astype(int)
    if up.min() == up.max():
        return {}
    out = {"n": int(ok.sum()), "auc": auc(-zs[ok], up)}
    fired = ok & (flags != 0)
    if fired.sum() >= 100:
        out["fired"] = int(fired.sum())
        out["hit"] = float(((flags[fired] == 1) == (fwd[fired] > 0)).mean())
    return out


# ---------------------------------------------------------------- generators


def ou(n: int, theta: float, sigma: float, rng, start: float = 100.0) -> np.ndarray:
    """The positive control. Mean-reverting by construction, at a chosen speed."""
    x = np.empty(n)
    x[0] = start
    for i in range(1, n):
        x[i] = x[i - 1] + theta * (start - x[i - 1]) + rng.normal(0.0, sigma)
    return x


def gbm(n: int, sigma_bar: float, rng, start: float = 100.0) -> np.ndarray:
    return start * np.exp(np.cumsum(rng.normal(0.0, sigma_bar, n)))


def step(n: int, rng, grid: float = 0.1, p_up: float = 0.499734, start: float = 7500.0):
    """A fair coin on a fixed lattice - the Step family's documented mechanics."""
    moves = np.where(rng.random(n) < p_up, grid, -grid)
    return start + np.cumsum(moves)


def spiky(n: int, rng, rate: int = 500, up: bool = True, start: float = 5000.0):
    """Boom or Crash: a slow grind one way, rare large spikes the other.

    Built so the drift and the spikes **cancel** - `E[jump] = lambda * E[grind]`
    - because `rebuilding.md` found the published parameters miss their own
    closure by 6-12% and a simulator built from them is not a martingale until
    that is imposed. A drifting null would let a mean-reversion detector score
    on the drift.

    **`up` is the direction of the SPIKE**, which is the direction the family is
    named for: a Boom spikes up and grinds down, a Crash spikes down and grinds
    up. The first version of this had both backwards.

    **And the AUC of a symmetric detector is not comparable across these arms.**
    With one spike in `rate` ticks, `499` of `500` bars move the same way, so
    "the next bar rose" has a base rate near 0 or 1 and an AUC computed against
    it is measuring the base rate more than the signal. The hit rate on fired
    signals is the reading here; the AUC column is reported but should not be
    compared with the symmetric families.
    """
    grind = 1.0
    jump = grind * rate
    hits = rng.random(n) < (1.0 / rate)
    moves = np.where(hits, jump if up else -jump, -grind if up else grind)
    return start + np.cumsum(moves)


def jumpy(n: int, sigma_bar: float, rng, rate: int = 25, start: float = 100.0):
    """Diffusion plus jumps. The name is the diffusive part; the jumps are extra."""
    steps = rng.normal(0.0, sigma_bar, n)
    hits = rng.random(n) < (1.0 / rate)
    sizes = rng.normal(0.0, sigma_bar * 6.0, n)
    return start * np.exp(np.cumsum(steps + hits * sizes))


def shuffled(prices: np.ndarray, rng) -> np.ndarray:
    steps = np.diff(np.log(np.maximum(prices, 1e-12)))
    rng.shuffle(steps)
    base = math.log(max(prices[0], 1e-12))
    return np.exp(np.concatenate(([base], base + np.cumsum(steps))))


def main() -> int:
    rng = np.random.default_rng(11)
    minute = math.sqrt(1.0 / (365 * 24 * 60))
    print("Does ZMA find mean reversion where there is some, and where there is none?\n")
    print("It fires on ~15% of bars on every arm, including shuffled noise, because its")
    print("thresholds are percentiles of its own history. Read the hit rate, not the count.\n")
    print(f"{'arm':30} {'n':>7} {'AUC':>8} {'fired':>7} {'hit':>8}   shuffled AUC")

    arms: list[tuple[str, np.ndarray]] = [
        ("OU theta=0.02  (control)", ou(BARS, 0.02, 0.5, rng)),
        ("OU theta=0.05  (control)", ou(BARS, 0.05, 0.5, rng)),
        ("OU theta=0.15  (control)", ou(BARS, 0.15, 0.5, rng)),
        ("volatility 25", gbm(BARS, 0.25 * minute, rng)),
        ("volatility 75", gbm(BARS, 0.75 * minute, rng)),
        ("volatility 100", gbm(BARS, 1.00 * minute, rng)),
        ("step index", step(BARS, rng)),
        ("boom 500", spiky(BARS, rng, rate=500, up=True)),
        ("boom 1000", spiky(BARS, rng, rate=1000, up=True)),
        ("crash 500", spiky(BARS, rng, rate=500, up=False)),
        ("crash 1000", spiky(BARS, rng, rate=1000, up=False)),
        ("jump 25", jumpy(BARS, 0.25 * 1.322 * minute, rng, rate=25)),
        ("jump 10", jumpy(BARS, 0.10 * 1.322 * minute, rng, rate=10)),
    ]
    for name, series in arms:
        got = score_series(series)
        if not got:
            print(f"{name:30}  nothing scored")
            continue
        control = score_series(shuffled(series, rng))
        print(
            f"{name:30} {got['n']:>7,} {got['auc']:>8.4f} {got.get('fired', 0):>7} "
            f"{got.get('hit', float('nan')):>8.4f}   {control.get('auc', float('nan')):>8.4f}"
        )

    print("\nReading it: the OU arms are the proof the detector works, and they scale with")
    print("theta. An arm at its own shuffled AUC is an arm where the detector found the")
    print("marginal and nothing else.")
    part_two()
    return 0


# ---------------------------------------------------------------------------
# Part two: the two things worth trying, given that part one found nothing.
# ---------------------------------------------------------------------------


def spreads_from(db: str) -> dict[str, np.ndarray]:
    """Constructed spreads, which are the only series in reach with a real theta.

    **A cross-venue spread reverts by arbitrage**, not by hope: the same asset
    at two venues cannot drift apart without somebody closing it. That makes it
    the cleanest real-market mean-reverting series available here, and it needs
    no model - only an inner join on the timestamp.

    Returned in log terms, because a spread of logs is the quantity that reverts
    to a constant while a ratio of prices drifts with the level.
    """
    import sqlite3

    c = sqlite3.connect(db)
    cells = c.execute(
        "SELECT feed, interval, venue, COUNT(*) n FROM bars "
        # Bounded deliberately: the pair search is quadratic in cells, and every
        # cross-venue spread worth having lives in the few feeds that several
        # venues actually quote.
        "GROUP BY feed, interval, venue HAVING n > 4000 ORDER BY n DESC LIMIT 12"
    ).fetchall()
    series: dict[tuple[str, str, str], dict[int, float]] = {}
    for feed, interval, venue, _ in cells:
        rows = c.execute(
            "SELECT ts, close FROM bars WHERE feed=? AND interval=? AND venue=? ORDER BY ts",
            (feed, interval, venue),
        ).fetchall()
        series[(feed, interval, venue)] = {int(t): float(p) for t, p in rows if p and p > 0}

    out: dict[str, np.ndarray] = {}
    keys = sorted(series)
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            if a[0] != b[0] or a[1] != b[1] or a[2] == b[2]:
                continue
            shared = sorted(set(series[a]) & set(series[b]))
            if len(shared) < 4000:
                continue
            gap = np.array([math.log(series[a][t]) - math.log(series[b][t]) for t in shared])
            # Recentred to a positive level so the indicator's own price
            # arithmetic - which divides by a price - stays well conditioned.
            out[f"{a[0]} {a[1]} {a[2]}-{b[2]}"] = 100.0 + (gap - gap.mean()) * 100.0
            if len(out) >= 6:
                return out
    return out


def score_hybrid(
    prices: np.ndarray, period: int = 50, gate: float = 1.0, want: str = "quiet"
) -> dict:
    """ZMA alone against ZMA gated by a changepoint, on identical bars.

    **The idea is that the two detectors answer different questions.** ZMA fires
    on the *magnitude of displacement* - price is far from its weighted mean.
    `Focus` fires on *accumulated evidence that the mean itself moved*. A
    displacement without a changepoint is a stretched rubber band; a
    displacement with one is a step to a new level, and those want opposite
    trades.

    **Both directions of the gate are run, because the first reasoning was
    backwards.** It said an extreme z with no changepoint behind it is the
    reverting case, so it kept the signals raised while `Focus` was *quiet*.
    That made precision worse on every arm where it could be measured - OU at
    theta = 0.15 fell from 0.666 to 0.628 while discarding four fifths of the
    sample - and the reason is plain in hindsight: on a genuinely reverting
    series the excursion **is** the evidence, so demanding that Focus stay quiet
    filters out exactly the displacements worth trading.

    So `quiet` keeps signals while the changepoint statistic is below `gate`,
    and `active` keeps them while it is above. Both are scored on the same bars
    as ungated ZMA, so the comparisons are paired and any difference is the gate.
    """
    from till_infinity.structures.learning.focus import Focus

    indicator = _indicator()
    z = indicator(period=period)
    up, down = Focus(up=True), Focus(up=False)

    zs, flags, quiet = [], [], []
    previous = None
    window: list[float] = []
    for p in prices:
        p = float(p)
        z.update_raw(p)
        zs.append(z.z_score)
        flags.append(1 if z.oversold else (-1 if z.overbought else 0))
        if previous is not None and previous != 0:
            r = (p - previous) / abs(previous)
            window.append(r)
            if len(window) > period:
                window.pop(0)
            scale = float(np.std(window, ddof=1)) if len(window) > 5 else 0.0
            if scale > 0:
                up.update(r, scale)
                down.update(r, scale)
            statistic = max(up.statistic, down.statistic)
        else:
            statistic = 0.0
        quiet.append(statistic <= gate if want == "quiet" else statistic > gate)
        previous = p

    zs, flags, quiet = np.asarray(zs), np.asarray(flags), np.asarray(quiet)
    fwd = np.full(len(prices), np.nan)
    fwd[:-1] = np.diff(np.log(np.maximum(prices, 1e-12)))
    ok = np.isfinite(fwd)
    ok[:WARM] = False

    def hit(mask: np.ndarray) -> tuple[int, float]:
        if mask.sum() < 60:
            return int(mask.sum()), float("nan")
        return int(mask.sum()), float(((flags[mask] == 1) == (fwd[mask] > 0)).mean())

    plain = ok & (flags != 0)
    gated = plain & quiet
    n_plain, h_plain = hit(plain)
    n_gated, h_gated = hit(gated)
    return {
        "fired": n_plain,
        "hit": h_plain,
        "gated": n_gated,
        "gated_hit": h_gated,
        "kept": n_gated / n_plain if n_plain else float("nan"),
    }


def part_two() -> None:
    rng = np.random.default_rng(5)
    minute = math.sqrt(1.0 / (365 * 24 * 60))

    print("\n" + "=" * 92)
    print("A. CONSTRUCTED SPREADS - the only real series here with a genuine theta")
    print("=" * 92)
    db = "/home/ose/Documents/Quants Pub/till_infinity/.data/prices/prices.db"
    try:
        found = spreads_from(db)
    except Exception as exc:
        found = {}
        print(f"  no spreads built: {exc}")
    print(f"{'spread':44} {'n':>7} {'AUC':>8} {'fired':>7} {'hit':>8}")
    for name, series in found.items():
        got = score_series(series)
        if got:
            print(
                f"{name:44} {got['n']:>7,} {got['auc']:>8.4f} "
                f"{got.get('fired', 0):>7} {got.get('hit', float('nan')):>8.4f}"
            )

    print("\n" + "=" * 92)
    print("B. THE CHANGEPOINT GATE - quiet against active, on identical bars")
    print("=" * 92)
    print(
        f"{'arm':24} {'gate':7} {'fired':>6} {'hit':>8}  {'gated':>6} {'gated hit':>10} {'kept':>7}"
    )
    arms: list[tuple[str, np.ndarray]] = [
        ("OU theta=0.05  (control)", ou(BARS, 0.05, 0.5, rng)),
        ("OU theta=0.15  (control)", ou(BARS, 0.15, 0.5, rng)),
        ("volatility 75", gbm(BARS, 0.75 * minute, rng)),
        ("step index", step(BARS, rng)),
        ("boom 500", spiky(BARS, rng, rate=500, up=True)),
        ("crash 500", spiky(BARS, rng, rate=500, up=False)),
        ("jump 25", jumpy(BARS, 0.25 * 1.322 * minute, rng, rate=25)),
    ]
    for name, series in list(found.items())[:2]:
        arms.append((f"spread {name[:22]}", series))
    for name, series in arms:
        for want in ("quiet", "active"):
            try:
                got = score_hybrid(series, want=want)
            except Exception as exc:  # noqa: BLE001
                print(f"{name:24} {want:7}  failed: {str(exc)[:40]}")
                continue
            print(
                f"{name:24} {want:7} {got['fired']:>6} {got['hit']:>8.4f}  "
                f"{got['gated']:>6} {got['gated_hit']:>10.4f} {got['kept']:>7.1%}"
            )
    print("\nThe gate earns its place only if `gated hit` beats `hit` by more than the")
    print("sample it gives up - a filter that keeps 20% and gains nothing has cost 80%.")


if __name__ == "__main__":
    sys.exit(main())
