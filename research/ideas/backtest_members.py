"""The members on real markets: calibration, sharpness, and a P&L arm.

Asked on 2026-10-12: test and backtest the state-space members against real
markets.

Two things already exist and are not repeated. `research/harness/statespace_fx.py`
ran the **directional** question - a Kalman AR(1) drift, 13 of 96 cells past
Benjamini-Hochberg at AUC 0.510 to 0.523 against walks at 0.49 to 0.51, found
on EURUSD so EURUSD cannot confirm it. And `statespace-measured.md` has a
coverage table, on **one cell**, with `linear` at 68.6% against a nominal 95%.

## Why the coverage table needs redoing

That 68.6% is not a verdict on `linear`; it is a verdict on `linear` with its
`jerk` left at the default. `statespace-clock-levers.md` has just measured
that a fitted jerk lands at **1e-10 to 1e-6 times** the dimensionally natural
value, so a default of `1e-6` is orders of magnitude too large - which makes
the state wander far more than the series does, which makes the band far too
narrow relative to the residual, which is exactly what 68.6% coverage with
`+0.32` residual autocorrelation looks like.

So every member here gets its process noise **fitted on the first half** of
each series by a sweep over fourteen decades, and everything is scored on the
second half. A calibration number from an unfitted member measures the
default, not the model.

## Four readings, in the order they decide things

* **coverage** at one and two sigma against the nominal 68.3% and 95.4%. This
  is the claim the desk would actually use, because a stop is a band.
* **sharpness** - the median band width in volatility units - read **only**
  for members whose coverage is honest. A tight band that does not cover is
  not sharp, it is wrong, and ranking on width alone rewards exactly that.
* **whiteness** - the lag-1 autocorrelation of the standardised residual.
  Scale-free, so comparable across members whose units differ, and it is the
  diagnostic that says whether the state equation is wrong rather than merely
  imprecise.
* **a P&L arm**, because the ask was a backtest. The member's own rate as the
  signal, entry on the next bar, cost in spread units, against **random
  entries at the same rate and the same holding time** - which is the control
  that matters, since any rule that trades more in volatile stretches looks
  different from a constant-rate one for reasons that are not signal.

## The prior, which is unkind and specific

Direction is close to unforecastable here: at most 6 of 45 bin pairs were
orderable in `statespace-informatory-pairs.md`, the up/down edge died at -98%
with good fills, and a plain level walk beats `kalman` and `reverting` by
about forty thousand nats. A P&L arm is run because it was asked for and
because the number is worth having written down, not because it is expected
to clear cost.

Runs on the lab.
"""

from __future__ import annotations

import itertools
import math
import os
import random
import statistics
from pathlib import Path

from till_infinity.statespace.linear import Gaussian
from till_infinity.statespace.nulls import Walk
from till_infinity.statespace.reverting import Reverting
from till_infinity.statespace.switching import Switching

HOUR = 3600.0

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "SPX500")
GENERATED = ("Volatility_75_Index", "Step_Index", "Boom_500_Index")
FRAMES = tuple(os.environ.get("FRAMES", "1h,4h").split(","))

#: The sweep for each member's process noise, as multiples of a dimensionally
#: natural base. Fourteen decades, because `jerk` needs them.
GRID = tuple(10.0**k for k in range(-12, 3, 2))

#: Nominal coverage of the one- and two-sigma bands for a Gaussian.
NOMINAL = {1.0: 0.6827, 2.0: 0.9545}

#: Holding time for the P&L arm, in hours, and the round-trip cost in spreads.
HOLD_HOURS = 24
COST_SPREADS = 1.5

SINCE = float(os.environ.get("SINCE", "1420070400"))
LIMIT = int(os.environ.get("LIMIT", "30000"))
SEED = 20261012
CACHE = Path.home() / "till_infinity" / "data" / "seqlab"


def load(name: str, frame: str):
    import numpy as np

    for path in (CACHE / f"{name}.{frame}.npz", Path(f"data/seqlab/{name}.{frame}.npz")):
        if not path.exists():
            continue
        with np.load(path) as bundle:
            if not {"time", "close"} <= set(bundle.keys()):
                continue
            order = np.argsort(bundle["time"])
            times = bundle["time"][order].tolist()
            closes = bundle["close"][order].tolist()
        first = 0
        while first < len(times) and times[first] < SINCE:
            first += 1
        times, closes = times[first:], closes[first:]
        if len(times) > LIMIT:
            times, closes = times[-LIMIT:], closes[-LIMIT:]
        return (times, closes) if len(times) > 5000 else None
    return None


#: name, builder taking the noise, the lever's name, and the natural base from
#: a one-step spread `s` over `dt` hours. The exponent is the integration
#: order: a level's variance grows like `q dt`, a reverting rate's
#: contribution like `q dt^3`, an integrated jerk's like `q dt^5`.
MEMBERS = (
    ("walk", lambda q: Walk(noise=math.sqrt(q)), "noise", lambda s, dt: s * s / dt),
    ("kalman", lambda q: Gaussian(jerk=q), "jerk", lambda s, dt: s * s / dt**5),
    ("reverting", lambda q: Reverting(sigma2=q), "sigma2", lambda s, dt: s * s / dt**3),
    (
        "switching",
        lambda q: Switching(balance_wander=q, imbalance_wander=q * 100.0),
        "balance_wander",
        lambda s, dt: s * s / dt,
    ),
)


def fit_base(times, values, *, build, natural, variance) -> tuple[float, float]:
    """Sweep the process noise on the **first half**, score it there.

    Fitting on the half that will be scored is the mistake this avoids, and
    the grid edge is reported because a parameter pinned at an edge is not a
    fitted parameter.
    """
    half = len(times) // 2
    found = []
    for multiple in GRID:
        base = natural * multiple
        if base <= 0:
            continue
        got = run(
            times[:half],
            values[:half],
            build=build,
            base=base,
            variance=variance,
            score_from=0,
        )["loglike"]
        if math.isfinite(got):
            found.append((got, base, multiple))
    if not found:
        return 0.0, float("nan")
    got, base, multiple = max(found)
    return base, multiple


def run(times, values, *, build, base, variance, score_from: int):
    """One pass. Returns the likelihood, the coverage, the band width and the
    residual autocorrelation, all measured from `score_from` onward.

    The band is asked for at the **next** reading's time and checked against
    the **next** value, which is the one-step-ahead question a stop actually
    asks. Asking for the band at the current time and checking the current
    value would be scoring the member on what it has already seen.
    """
    member = build(base)
    inside = {1.0: 0, 2.0: 0}
    widths: list[float] = []
    residuals: list[float] = []
    counted = 0

    for i, (when, value) in enumerate(zip(times, values, strict=True)):
        member.predict(when)
        member.update(value, variance, when)
        if i + 1 >= len(times):
            break
        nxt_when, nxt_value = times[i + 1], values[i + 1]
        if i < score_from:
            continue
        counted += 1
        for sigmas in (1.0, 2.0):
            low, high = member.band(nxt_when, sigmas)
            if low <= nxt_value <= high:
                inside[sigmas] += 1
            if sigmas == 2.0:
                widths.append((high - low) / 2.0)
        residuals.append(member.last_standardised)

    if counted < 100:
        return {"loglike": float("-inf")}

    lag = float("nan")
    if len(residuals) > 30:
        middle = statistics.fmean(residuals)
        num = sum((a - middle) * (b - middle) for a, b in itertools.pairwise(residuals))
        den = sum((a - middle) ** 2 for a in residuals)
        lag = num / den if den > 0 else float("nan")

    return {
        "loglike": member.loglike,
        "cover1": inside[1.0] / counted,
        "cover2": inside[2.0] / counted,
        "width": statistics.median(widths) if widths else float("nan"),
        "lag1": lag,
        "member": member,
    }


def pnl(times, values, *, build, base, variance, bar_hours, cost, seed):
    """The member's own one-step view as a signal, against random entries.

    Long when the member expects the next reading above the current price,
    short when below, held for `HOLD_HOURS`, one position at a time. The
    control takes the **same number of entries at the same holding time**
    placed at random, because a rule that trades more in volatile stretches
    differs from a constant-rate one for reasons that are not signal.
    """
    hold = max(round(HOLD_HOURS / bar_hours), 1)
    half = len(times) // 2
    member = build(base)
    entries: list[tuple[int, int]] = []
    for i, (when, value) in enumerate(zip(times, values, strict=True)):
        member.predict(when)
        member.update(value, variance, when)
        if i < half or i + 1 >= len(times) or i + hold >= len(values):
            continue
        if entries and i < entries[-1][0] + hold:
            continue
        view = member.at_time(times[i + 1]) - value
        if view == 0.0:
            continue
        entries.append((i, 1 if view > 0 else -1))

    def total(picks: list[tuple[int, int]]) -> tuple[float, int]:
        got = 0.0
        for i, side in picks:
            got += side * (values[i + hold] - values[i]) - cost
        return got, len(picks)

    taken, count = total(entries)
    rng = random.Random(seed)
    spun = []
    for _ in range(20):
        places = sorted(rng.sample(range(half, len(values) - hold - 1), count)) if count else []
        picks = [(i, rng.choice((1, -1))) for i in places]
        spun.append(total(picks)[0])
    return taken, count, statistics.fmean(spun) if spun else float("nan")


def main() -> None:
    from till_infinity.statespace.driven import Driven
    from till_infinity.statespace.seasonal import Profile

    print(
        f"frames {FRAMES}  hold {HOLD_HOURS}h  cost {COST_SPREADS} spreads\n"
        "coverage is one-step-ahead: the band asked at the next reading's time,\n"
        "checked against the next value. nominal 68.3% and 95.4%.\n"
    )
    print(
        f"{'instrument':<22}{'frame':<6}{'member':<12}{'base x':>8}"
        f"{'cover1':>8}{'cover2':>8}{'width':>9}{'lag1':>8}{'loglike':>11}"
    )

    rows: list[dict] = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            found = load(name, frame)
            if found is None:
                continue
            times, closes = found
            values = [math.log(c) for c in closes if c > 0]
            if len(values) != len(times):
                continue

            gaps = [times[i] - times[i - 1] for i in range(1, min(len(times), 500))]
            dt = statistics.median(gaps) / HOUR if gaps else 1.0
            spread = (
                statistics.pstdev([values[i] - values[i - 1] for i in range(1, len(values))])
                or 1e-9
            )
            # One shared measurement variance for every member, so the
            # comparison is of dynamics rather than of calibration. A quarter
            # of a typical bar move, which is the order of a spread.
            variance = (spread * 0.25) ** 2
            half = len(times) // 2
            label = f"*{name}" if name in GENERATED else name

            profile = Profile.fit(times[:half], values[:half])
            builds = list(MEMBERS)
            if profile is not None:
                # The one lever that measured positive, carried through.
                builds.append(
                    (
                        "kalman+clock",
                        lambda q, p=profile: Driven(
                            build=lambda: Gaussian(jerk=q), lever="jerk", clock=p.factor
                        ),
                        "jerk",
                        lambda s, d: s * s / d**5,
                    )
                )

            for tag, build, _lever, natural in builds:
                base, multiple = fit_base(
                    times,
                    values,
                    build=build,
                    natural=natural(spread, dt),
                    variance=variance,
                )
                if base <= 0:
                    continue
                got = run(
                    times,
                    values,
                    build=build,
                    base=base,
                    variance=variance,
                    score_from=half,
                )
                if not math.isfinite(got["loglike"]):
                    continue
                print(
                    f"{label:<22}{frame:<6}{tag:<12}{multiple:>8.0e}"
                    f"{got['cover1']:>8.3f}{got['cover2']:>8.3f}"
                    f"{got['width'] / spread:>9.2f}{got['lag1']:>8.3f}"
                    f"{got['loglike']:>11.0f}"
                )
                taken, count, control = pnl(
                    times,
                    values,
                    build=build,
                    base=base,
                    variance=variance,
                    bar_hours=dt,
                    cost=COST_SPREADS * spread,
                    seed=SEED + len(rows),
                )
                rows.append(
                    {
                        "label": label,
                        "frame": frame,
                        "member": tag,
                        **{k: v for k, v in got.items() if k != "member"},
                        "pnl": taken,
                        "trades": count,
                        "control": control,
                        "spread": spread,
                    }
                )

    _calibration(rows)
    _pnl(rows)


def _calibration(rows: list[dict]) -> None:
    print("\n== calibration: how far each member's two-sigma band is from 95.4%")
    print(
        f"{'member':<14}{'cells':>6}{'cover1':>9}{'cover2':>9}{'|error|':>9}{'width':>8}{'lag1':>8}"
    )
    names = []
    for row in rows:
        if row["member"] not in names:
            names.append(row["member"])
    for tag in names:
        got = [r for r in rows if r["member"] == tag and not r["label"].startswith("*")]
        if not got:
            continue
        one = statistics.median([r["cover1"] for r in got])
        two = statistics.median([r["cover2"] for r in got])
        print(
            f"{tag:<14}{len(got):>6}{one:>9.3f}{two:>9.3f}"
            f"{abs(two - NOMINAL[2.0]):>9.3f}"
            f"{statistics.median([r['width'] / r['spread'] for r in got]):>8.2f}"
            f"{statistics.median([r['lag1'] for r in got]):>8.3f}"
        )
    print(
        "\n   width is the two-sigma half-width in one-bar volatility units, and is\n"
        "   only a ranking among members whose coverage is honest: a narrow band\n"
        "   that does not cover is wrong rather than sharp."
    )


def _pnl(rows: list[dict]) -> None:
    print("\n== the P&L arm, in one-bar volatility units, net of cost")
    print(f"{'member':<14}{'cells':>6}{'trades':>8}{'total':>10}{'random':>10}{'beat random':>13}")
    names = []
    for row in rows:
        if row["member"] not in names:
            names.append(row["member"])
    for tag in names:
        got = [
            r
            for r in rows
            if r["member"] == tag and not r["label"].startswith("*") and r["trades"] > 0
        ]
        if not got:
            continue
        ours = statistics.median([r["pnl"] / r["spread"] for r in got])
        theirs = statistics.median([r["control"] / r["spread"] for r in got])
        wins = sum(1 for r in got if r["pnl"] > r["control"])
        print(
            f"{tag:<14}{len(got):>6}"
            f"{statistics.median([r['trades'] for r in got]):>8.0f}"
            f"{ours:>10.1f}{theirs:>10.1f}{f'{wins} of {len(got)}':>13}"
        )
    positive = [
        r for r in rows if not r["label"].startswith("*") and r["trades"] > 0 and r["pnl"] > 0
    ]
    print(
        f"\n   {len(positive)} of "
        f"{len([r for r in rows if not r['label'].startswith('*') and r['trades'] > 0])}"
        " cells are profitable after cost."
    )


if __name__ == "__main__":
    main()
