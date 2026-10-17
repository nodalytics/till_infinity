"""How big an ordering would have to be before we could find it.

Asked on 2026-10-12. `paths.simulate` is used for parameter recovery and
nothing else, and the question it could answer is the one behind most of this
session's results: when a harness returns null, is that because **the market
has no ordering** or because **the method cannot find one**?

Those are different claims and a null does not distinguish them. What does is
**power**: plant an ordering of known size, run the same harness, and find the
smallest size it detects. Then the null stops being "nothing is there" and
becomes "anything there is smaller than this", which is a quantity.

## The ordering planted, and why this one

An AR(1) in the returns: `r(t) = phi * r(t-1) + noise`. One parameter, and it
is the ordering this desk has actually looked for - `research/harness/statespace_fx.py`
reports a Kalman AR(1) drift with `phi` of -0.02 to -0.04 on EURUSD, 13 of 96
cells past Benjamini-Hochberg at AUC 0.510 to 0.523. So the planted sizes
bracket the one claim in the repository that survived a multiple-comparison
correction.

`phi` also converts straight into money, which is what makes the curve
readable. Trading the sign of the last return earns `|phi|` of a typical move
per trade, so against a round trip of `COST_SPREADS` spreads the edge pays
only when

    |phi| * (move in spreads) > COST_SPREADS

and the move in spreads is the table `statespace-seconds.md` measured: about 8
at 1m on XAUUSD, 16 at 3m, 38 at 15m on BTCUSD. **So the cost floor is a
`phi` threshold too**, and the interesting question is which threshold is
higher - the one detection needs or the one cost needs.

If cost binds first, then every directional null in this package is not a
detection failure and not an absence: it is a statement that whatever is
there is too small to pay for. That is a different conclusion from either.

## Two bases

* a **random walk**, which is what the market looks like on every measurement
  here - `H` of 0.489 to 0.506;
* and a diagnostic on **`paths.simulate`** itself, which began as a second
  base and became something better. Planting an ordering in it detected one at
  `phi = 0` in 90% of seeds, because the base already had one: the increments
  of a triple integrator driven by white jerk have a lag-1 autocorrelation of
  about **+0.999**, where every real series here sits at about **0.00**.

That second result is the more useful of the two. It says the process this
package's model *assumes* is nothing like the data, which is the session's
central finding stated from the generator's side rather than the fit's - and
it explains why `kalman` drives its jerk to the floor and why its residuals
come back at -0.45.

Runs anywhere - it is generated data - but kept with the lab harnesses for
consistency.
"""

from __future__ import annotations

import itertools
import math
import os
import random
import statistics

HOUR = 3600.0

#: Planted AR(1) coefficients. Signed, because the one real claim is
#: *negative* - the next bar partly undoes this one - and a detector could be
#: better at one sign than the other.
PHIS = (0.0, -0.01, -0.02, -0.04, -0.08, -0.16, 0.02, 0.04, 0.08)

#: Series length and how many seeds per cell. Twenty seeds, because the
#: reading is a detection *rate* and a single seed cannot give one.
LENGTH = int(os.environ.get("LENGTH", "8000"))
SEEDS = int(os.environ.get("SEEDS", "20"))

#: The move over one bar in spreads, for the cost arm. Taken from
#: `statespace-seconds.md`'s measured table rather than assumed: 8.0 is
#: XAUUSD at 1m.
MOVE_IN_SPREADS = float(os.environ.get("MOVE_IN_SPREADS", "8.0"))
COST_SPREADS = 1.5

#: What counts as a detection. The rotated control is the honest baseline, so
#: a cell is detected when the raw reading beats its own control by this much.
MARGIN = 0.05


def ar_one(n: int, phi: float, seed: int) -> list[float]:
    """Returns with a planted AR(1), standardised so `phi` is the only change.

    The innovation's spread is scaled by `sqrt(1 - phi^2)` so the series'
    unconditional variance is the same at every `phi`. Without that, a larger
    `phi` would also mean a larger series and the curve would confound
    predictability with volatility.
    """
    rng = random.Random(seed)
    drive = math.sqrt(max(1.0 - phi * phi, 1e-12))
    out: list[float] = []
    previous = 0.0
    for _ in range(n):
        previous = phi * previous + rng.gauss(0.0, drive)
        out.append(previous)
    return out


def generator_shape(n: int, seed: int, seeds: int = 8) -> list[tuple[float, float, float, float]]:
    """What `paths.simulate`'s own path looks like, as a function of `jerk`.

    **This replaced an attempt to plant an ordering in it, which was
    confounded.** The planted curve detected an ordering at `phi = 0` in 90%
    of seeds, because the base already had one: the increments of a triple
    integrator are not close to independent, so a lag-1 detector fires on them
    whatever is planted.

    That is not a defect in the harness, it is the finding. The process this
    package's model assumes - a triple integrator driven by white jerk - has
    increments with a lag-1 autocorrelation of about **+0.999**, and every
    real series measured here sits at about **0.00**. So the comparison worth
    reporting is the generator's own shape against the market's, not a power
    curve on a base that does not resemble one.
    """
    from till_infinity.statespace.paths import simulate

    times = [i * HOUR for i in range(n + 1)]
    out = []
    for power in (-9, -6, -3, 0):
        jerk = 10.0**power
        got, truths = [], []
        for offset in range(seeds):
            path = simulate(times, jerk=jerk, noise=1.0, seed=seed + offset)
            measured = [
                path.measured[i] - path.measured[i - 1] for i in range(1, len(path.measured))
            ]
            truth = [path.truth[i] - path.truth[i - 1] for i in range(1, len(path.truth))]
            got.append(_lag_one(measured))
            truths.append(_lag_one(truth))
        # Averaged over seeds and reported with its spread, because at the
        # smallest jerk the reading is **unstable**: one seed gave -0.060 and
        # another +0.646, since the truth is nearly frozen and whether noise
        # or residual drift dominates varies. The rows above 1e-9 are stable,
        # and they are the whole range a member would use.
        out.append(
            (
                jerk,
                statistics.fmean(got),
                statistics.pstdev(got) if len(got) > 1 else 0.0,
                statistics.fmean(truths),
            )
        )
    return out


def _lag_one(values: list[float]) -> float:
    if len(values) < 10:
        return float("nan")
    middle = statistics.fmean(values)
    num = sum((a - middle) * (b - middle) for a, b in itertools.pairwise(values))
    den = sum((a - middle) ** 2 for a in values)
    return num / den if den > 0 else float("nan")


def spearman(xs: list[float], ys: list[float], shift: int = 0) -> float:
    n = min(len(xs), len(ys))
    if n < 30:
        return float("nan")
    xs, ys = list(xs[:n]), list(ys[:n])
    if shift:
        xs = [xs[(i + shift) % n] for i in range(n)]

    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        for rank, i in enumerate(order):
            out[i] = float(rank)
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den > 0 else float("nan")


def control(xs: list[float], ys: list[float]) -> float:
    got = [spearman(xs, ys, shift=max(int(len(xs) * f), 1)) for f in (0.25, 0.5, 0.75)]
    usable = [v for v in got if not math.isnan(v)]
    return statistics.fmean(usable) if usable else float("nan")


def detect(moves: list[float]) -> tuple[float, float]:
    """The harness: this return against the next, with the rotated control.

    Deliberately the simplest thing that could find an AR(1), because the
    question is the **floor** on what is findable. A cleverer detector would
    move the floor down and the cost threshold would not move at all, which is
    the comparison that matters.
    """
    raw = spearman(moves[:-1], moves[1:])
    return raw, control(moves[:-1], moves[1:])


def traded(moves: list[float], phi_sign: float) -> float:
    """Per-trade profit in spreads from trading the sign of the last move.

    The position is the sign the planted ordering implies - negative `phi`
    means fade the last move - so this is the **best case**: a trader who
    knows the sign of the effect and has only to pay for it. The cost is
    subtracted per round trip.
    """
    if not moves:
        return float("nan")
    side = -1.0 if phi_sign < 0 else 1.0
    spread = statistics.pstdev(moves) or 1.0
    got = [
        side * math.copysign(1.0, moves[i]) * moves[i + 1] / spread * MOVE_IN_SPREADS
        for i in range(len(moves) - 1)
    ]
    return statistics.fmean(got) - COST_SPREADS


def main() -> None:
    print(
        f"length {LENGTH}  seeds {SEEDS}  margin {MARGIN}  "
        f"move {MOVE_IN_SPREADS} spreads  cost {COST_SPREADS}\n"
        "detected = the raw lag-1 reading beats its own rotated control by the\n"
        "margin. paid = the best-case trade, knowing the sign, clears the cost.\n"
    )
    print(
        f"{'base':<12}{'phi':>7}{'raw':>8}{'control':>9}"
        f"{'detected':>10}{'per trade':>11}{'paid':>7}"
    )

    rows = []
    for name, build in (("walk", ar_one),):
        for phi in PHIS:
            raws, controls, hits, profits, pays = [], [], 0, [], 0
            for seed in range(SEEDS):
                moves = build(LENGTH, phi, 20261012 + seed)
                raw, ctrl = detect(moves)
                if math.isnan(raw):
                    continue
                raws.append(raw)
                controls.append(ctrl)
                if abs(raw) > abs(ctrl) + MARGIN:
                    hits += 1
                got = traded(moves, phi if phi != 0 else -1.0)
                profits.append(got)
                if got > 0:
                    pays += 1
            if not raws:
                continue
            rate = hits / len(raws)
            paid = pays / len(profits)
            print(
                f"{name:<12}{phi:>7.2f}{statistics.median(raws):>8.3f}"
                f"{statistics.median(controls):>9.3f}{rate:>10.2f}"
                f"{statistics.median(profits):>11.2f}{paid:>7.2f}"
            )
            rows.append(
                {
                    "base": name,
                    "phi": phi,
                    "rate": rate,
                    "paid": paid,
                    "profit": statistics.median(profits),
                }
            )

    _verdict(rows)
    _generator()


def _verdict(rows: list[dict]) -> None:
    print("\n== the two thresholds")
    for name in ("walk",):
        pool = [r for r in rows if r["base"] == name and r["phi"] < 0]
        if not pool:
            continue
        found = [r for r in pool if r["rate"] >= 0.8]
        payable = [r for r in pool if r["paid"] >= 0.8]
        smallest_found = min((abs(r["phi"]) for r in found), default=float("nan"))
        smallest_paid = min((abs(r["phi"]) for r in payable), default=float("nan"))
        print(
            f"{name:<12}detected at |phi| >= {smallest_found:.2f}"
            f"   pays at |phi| >= {smallest_paid:.2f}"
        )
    print(
        "\n   A null from this harness means 'any ordering present is smaller\n"
        "   than the detection threshold'. If the paying threshold is the\n"
        "   larger of the two, then every directional null in this package is\n"
        "   neither a detection failure nor an absence: it is a statement that\n"
        "   whatever is there cannot pay for the spread."
    )
    print(
        "\n   For reference the one surviving claim in the repository is a phi of\n"
        "   -0.02 to -0.04 on EURUSD at 15m to 4h, from"
        " `research/harness/statespace_fx.py`."
    )

    # The paying threshold is `cost / move`, and the move in spreads is the
    # table `statespace-seconds.md` measured - so the threshold is a different
    # number at every horizon, and the ordering of the two thresholds flips.
    print("\n== what phi would have to be to pay, by horizon")
    print(f"{'horizon':<10}{'move/spread':>12}{'phi to pay':>12}{'vs detection':>14}")
    for horizon, move in (
        ("10s", 2.87),
        ("30s", 5.27),
        ("1m", 8.00),
        ("3m", 16.13),
        ("15m", 37.92),
    ):
        need = COST_SPREADS / move
        verdict = "cost binds" if need > 0.08 else "detection binds"
        print(f"{horizon:<10}{move:>12.2f}{need:>12.3f}  {verdict:<16}")
    print(
        "\n   Below about three minutes the cost threshold is the higher of the\n"
        "   two, so a directional null there says nothing is *payable*. Above\n"
        "   it the detection threshold is higher, so a null says nothing is\n"
        "   *findable* - and those are different sentences."
    )


def _generator() -> None:
    """The generator diagnostic, printed after the power curve."""
    print("\n== what `paths.simulate`'s own path looks like")
    print(f"{'jerk':>10}{'measured lag-1':>16}{'+/-':>8}{'truth lag-1':>14}")
    for jerk, measured, spread, truth in generator_shape(4000, 20261012):
        print(f"{jerk:>10.0e}{measured:>16.3f}{spread:>8.3f}{truth:>14.3f}")
    print(
        "\n   A real series' increments sit at about 0.00 - the walk arm above\n"
        "   reads -0.001 at phi = 0, and every instrument measured in this\n"
        "   package has a level Hurst of 0.489 to 0.506.\n"
        "   This generator's sit at +0.98 to +0.999 across every jerk from\n"
        "   1e-6 upward, the whole range a member would use. At 1e-9 the\n"
        "   reading falls but is **unstable** - 0.076 with a spread of 0.412\n"
        "   across seeds - because the truth is nearly frozen there and\n"
        "   whether noise or residual drift dominates varies run to run.\n"
        "   So the only setting at which the assumed process resembles the data\n"
        "   is the one where its own dynamics are switched off - which is\n"
        "   exactly where `statespace-clock-levers.md` found a fitted jerk\n"
        "   landing, and why `statespace-backtest.md` reads kalman's residual\n"
        "   autocorrelation at -0.45."
    )


if __name__ == "__main__":
    main()
