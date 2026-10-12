"""Fractals in state space: roughness and multifractality, in the variance.

Asked on 2026-10-12: research fractals and how to add them to the state-space
models.

Most of what "fractal" names in trading has already been measured here and is
null. The geometry papers' fractal decomposition claimed each swing holds 3.2
sub-swings and it measures 1.92 to 2.35, set by the detector's reach rather
than any market clock. Counted pivots were null over 1,020 cells. A Hurst
exponent on the level has been in `inputs.py` for a long time.

And `fractional.py` already builds the standard long-memory device - a power
law as a sum of geometrically spaced Ornstein-Uhlenbeck modes - then says in
its own docstring where it fell short:

> **Long memory in the level is not long memory in the variance.** The modes
> here give the *mean* a kernel.

That is the gap, and it is also where the last decade of the actual literature
went. Two measurable claims live there.

## 1. Rough volatility

Gatheral, Jaisson and Rosenbaum report that log-volatility behaves like
fractional Brownian motion with **`H` near 0.1** - far rougher than a random
walk's 0.5, and on the opposite side of it from the long-memory models that
assume 0.7 to 0.9. The estimator is simple: the `q`-th absolute moment of
log-volatility increments over a lag scales as

    m(lag, q) = mean |logvol(t + lag) - logvol(t)|^q  ~  lag^(q H)

so a straight line through `log m` against `log lag` has slope `q H`.

**The counter-argument is the reason this needs a control.** Cont and Das
argue the small `H` is largely an artefact: log-volatility is never observed,
only estimated from a finite window of returns, and the estimation noise is
roughly independent between windows - which looks exactly like extreme
roughness. An estimator fed a noisy proxy returns a small `H` whatever the
truth.

So this harness simulates a series whose log-volatility is an **OU process
with `H` of exactly 0.5 by construction**, measures it through the same proxy
with the same estimator, and reports that number beside the market's. If the
estimator returns 0.1 on data built with 0.5, it is measuring the proxy.

## 2. Multifractality

A monofractal has `zeta(q) = q H` - the scaling exponent linear in the moment
order. The multifractal random walk of Bacry, Muzy and Delour gives

    zeta(q) = q H - lambda^2 q (q - 1) / 2

with `lambda^2` the intermittency, reported around 0.02 to 0.03 for equity
indices. The curvature **is** the multifractality, so fitting a parabola to
`zeta(q)` and reading its second coefficient is the whole test.

A plain random walk has `lambda^2 = 0` exactly. A GARCH surrogate has
clustering with an exponential decay and so some curvature, which is the
control that matters: if a market cannot be told from GARCH here, the
multifractality is clustering under another name.

## 3. What it would mean for the package

If log-volatility is rough or long-memoried, the state-space form is
`fractional`'s geometric OU ladder applied to **log-volatility** rather than
to the level - which is the one thing its docstring says it did not do. The
third arm tests exactly that: a ladder of modes against a single OU, on the
log-volatility series, scored out of sample.

Runs on the lab.
"""

from __future__ import annotations

import itertools
import math
import os
import random
import statistics
from pathlib import Path

HOUR = 3600.0

TRADED = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD")
GENERATED = ("Volatility_75_Index", "Step_Index")
FRAMES = tuple(
    os.environ.get(
        "FRAMES",
        "1h",
    ).split(",")
)

#: Bars per volatility window. Realised variance over this many returns, then
#: its logarithm. Six hours at 1h bars: short enough to leave thousands of
#: points and long enough that the estimate is not one squared return.
WINDOW = int(os.environ.get("WINDOW", "6"))

#: Lags for the scaling fit, in windows. Geometric, because the fit is of a
#: power law and evenly spaced lags would weight the long end by sheer count.
LAGS = (1, 2, 3, 5, 8, 13, 21, 34, 55)

#: Moment orders for `zeta(q)`. Below 2 as well as above, because the
#: curvature is what is being measured and a one-sided range would read a
#: curve as a line.
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


def returns(closes: list[float]) -> list[float]:
    return [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i] > 0 and closes[i - 1] > 0
    ]


def log_volatility(moves: list[float], window: int) -> list[float]:
    """Realised volatility over non-overlapping windows, logged.

    **Non-overlapping**, which costs points and is not optional: overlapping
    windows share returns, so their estimation errors are correlated, and a
    correlated error is exactly the thing that would masquerade as memory in
    the series being tested.
    """
    out: list[float] = []
    for start in range(0, len(moves) - window + 1, window):
        chunk = moves[start : start + window]
        total = sum(v * v for v in chunk)
        if total > 0:
            out.append(0.5 * math.log(total / window))
    return out


def scaling(series: list[float], order: float) -> tuple[float, int]:
    """Slope of `log m(lag, q)` against `log lag`, which is `q H`.

    Returns the slope and how many lags it was fitted over, because a slope
    from three points is not the same claim as one from nine.
    """
    xs: list[float] = []
    ys: list[float] = []
    for lag in LAGS:
        if lag >= len(series) // 8:
            continue
        gaps = [abs(series[i + lag] - series[i]) ** order for i in range(len(series) - lag)]
        if len(gaps) < 50:
            continue
        middle = statistics.fmean(gaps)
        if middle <= 0:
            continue
        xs.append(math.log(lag))
        ys.append(math.log(middle))
    if len(xs) < 4:
        return float("nan"), len(xs)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((a - mx) ** 2 for a in xs)
    if den <= 0:
        return float("nan"), len(xs)
    return sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True)) / den, len(xs)


def hurst(series: list[float]) -> tuple[float, int]:
    """`H` from the second moment, which is the usual estimator."""
    slope, count = scaling(series, 2.0)
    return (slope / 2.0 if not math.isnan(slope) else float("nan")), count


def intermittency(series: list[float]) -> tuple[float, float]:
    """Fit `zeta(q) = q H - lambda^2 q (q-1) / 2` and return `H` and `lambda^2`.

    Linear least squares in the two unknowns, because the model is linear in
    them once the `q` terms are treated as the design: `zeta(q)` against
    `[q, -q(q-1)/2]`.
    """
    rows: list[tuple[float, float, float]] = []
    for order in ORDERS:
        slope, count = scaling(series, order)
        if math.isnan(slope) or count < 4:
            continue
        rows.append((order, -order * (order - 1.0) / 2.0, slope))
    if len(rows) < 3:
        return float("nan"), float("nan")

    s11 = sum(a * a for a, _b, _z in rows)
    s12 = sum(a * b for a, b, _z in rows)
    s22 = sum(b * b for _a, b, _z in rows)
    t1 = sum(a * z for a, _b, z in rows)
    t2 = sum(b * z for _a, b, z in rows)
    det = s11 * s22 - s12 * s12
    if abs(det) < 1e-18:
        return float("nan"), float("nan")
    return (s22 * t1 - s12 * t2) / det, (s11 * t2 - s12 * t1) / det


def walk_returns(n: int, sigma: float, seed: int) -> list[float]:
    """Constant volatility. Its log-volatility is pure estimation noise."""
    rng = random.Random(seed)
    return [rng.gauss(0.0, sigma) for _ in range(n)]


def ou_volatility_returns(
    n: int, sigma: float, seed: int, *, half_life: float = 120.0, swing: float = 0.5
) -> list[float]:
    """**The control the rough-volatility claim needs.**

    Returns whose log-volatility is an Ornstein-Uhlenbeck process, which is a
    smooth short-memory process with `H = 0.5` for its increments at short
    lags **by construction**. Measured through the same realised-volatility
    proxy with the same estimator, whatever `H` comes back is the estimator's
    answer to a known truth of 0.5.

    If the market reads 0.1 and this reads 0.1 too, the small exponent is the
    proxy's estimation noise and not the market's roughness - which is
    precisely what Cont and Das argue. If this reads near 0.5 and the market
    reads 0.1, the roughness is in the market.

    `half_life` is in bars and `swing` the stationary standard deviation of
    log-volatility, chosen at 0.5 because that is the order seen in equity
    and FX data.
    """
    rng = random.Random(seed)
    keep = math.exp(-math.log(2.0) / half_life)
    drive = swing * math.sqrt(1.0 - keep * keep)
    level = rng.gauss(0.0, swing)
    out: list[float] = []
    for _ in range(n):
        level = keep * level + rng.gauss(0.0, drive)
        out.append(rng.gauss(0.0, sigma * math.exp(level)))
    return out


def garch_returns(n: int, sigma: float, seed: int) -> list[float]:
    """Clustered volatility with an exponential decay, t(5) innovations.

    The control for the multifractality arm: clustering alone produces some
    curvature in `zeta(q)`, so a market that cannot be told from this has
    multifractality that is clustering under another name.
    """
    rng = random.Random(seed)
    variance, previous = 1.0, 0.0
    out: list[float] = []
    for _ in range(n):
        variance = 0.02 + 0.10 * previous * previous + 0.88 * variance
        chi = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(5))
        previous = rng.gauss(0.0, math.sqrt(variance)) * math.sqrt(5.0 / max(chi, 0.05))
        out.append(max(min(previous, 12.0), -12.0) * sigma / 1.6)
    return out


def ladder_against_one(series: list[float], *, seed: int) -> dict[str, float]:
    """A geometric ladder of modes against a single OU, on log-volatility.

    This is the state-space question: `fractional.py` builds the ladder for
    the **level** and says so; the claim worth testing is whether
    log-volatility needs it.

    Both members' process noise is swept on the first half and scored on the
    second, because comparing a fitted model with an unfitted one is the
    mistake `statespace-clock-levers.md` records three instances of. The
    measurement variance is shared and comes from the proxy's own noise: a
    realised volatility over `WINDOW` returns has a log-variance of about
    `1/(2 * WINDOW)`, which is a quantity this harness knows rather than
    guesses.
    """
    from till_infinity.structures.statespace.fractional import Fractional
    from till_infinity.structures.statespace.reverting import Reverting

    if len(series) < 400:
        return {}
    half = len(series) // 2
    variance = 1.0 / (2.0 * WINDOW)
    stamps = [float(i) * WINDOW * HOUR for i in range(len(series))]

    def score(build, noise: float, *, upto: int | None = None) -> float:
        member = build(noise)
        stop = upto if upto is not None else len(series)
        for i in range(stop):
            member.predict(stamps[i])
            member.update(series[i], variance, stamps[i])
            if upto is None and i == half:
                member.loglike = 0.0
        return member.loglike

    out: dict[str, float] = {}
    for tag, build in (
        ("ladder", lambda q: Fractional(modes=5, wander=q)),
        ("one_ou", lambda q: Reverting(sigma2=q)),
    ):
        best, chosen = float("-inf"), 0.0
        for power in range(-10, 3):
            noise = 10.0**power
            got = score(build, noise, upto=half)
            if math.isfinite(got) and got > best:
                best, chosen = got, noise
        if chosen <= 0:
            continue
        out[tag] = score(build, chosen)
        out[f"{tag}_base"] = chosen
    _ = seed
    return out


def report_series(label: str, moves: list[float]) -> dict[str, float]:
    series = log_volatility(moves, WINDOW)
    if len(series) < 400:
        return {}
    got_h, lags = hurst(series)
    level = list(itertools.accumulate(moves))
    level_h, _ = hurst(level)

    # **`zeta(q)` belongs on the returns, not on log-volatility.** The
    # multifractal random walk defines it as `E|r_D|^q ~ D^zeta(q)` for
    # returns aggregated over `D`, which is the increments of the *level*. A
    # first version of this harness fitted it to log-volatility increments
    # instead - a different and much less standard quantity, and one whose
    # curvature is not what the published 0.02 to 0.03 refers to.
    fitted_h, lam = intermittency(level)

    # The amplitude of the log-volatility variation, which has to be reported
    # beside `H`. The estimator conflates **roughness** with a **weak
    # signal**: a constant-volatility series reads `H = 0`, and a smooth OU
    # log-volatility with a large swing reads much higher, so a reading in
    # between is uninterpretable without knowing how much log-volatility
    # actually moves.
    swing = statistics.pstdev(series) if len(series) > 2 else float("nan")
    return {
        "label": label,
        "points": float(len(series)),
        "lags": float(lags),
        "logvol_h": got_h,
        "logvol_swing": swing,
        "level_h": level_h,
        "zeta_h": fitted_h,
        "lambda2": lam,
    }


def main() -> None:
    print(
        f"frames {FRAMES}  volatility window {WINDOW} bars  lags {LAGS}\n"
        "H of 0.5 is a random walk; rough volatility claims about 0.1 for\n"
        "log-volatility. lambda^2 is the curvature of zeta(q): 0 is monofractal,\n"
        "and the published range for equity indices is 0.02 to 0.03.\n"
    )
    print(
        f"{'series':<26}{'points':>7}"
        f"{'H logvol':>10}{'swing':>8}{'H level':>9}{'zeta H':>8}{'lambda2':>9}"
    )

    rows: list[dict] = []
    for name in TRADED + GENERATED:
        for frame in FRAMES:
            found = load(name, frame)
            if found is None:
                continue
            moves = returns(found[1])
            sigma = statistics.pstdev(moves) or 1e-9
            label = f"*{name}" if name in GENERATED else name
            got = report_series(f"{label} {frame}", moves)
            if got:
                got["moves"] = moves
                got["sigma"] = sigma
                rows.append(got)
                print(
                    f"{got['label']:<26}{got['points']:>7.0f}"
                    f"{got['logvol_h']:>10.3f}{got['logvol_swing']:>8.3f}"
                    f"{got['level_h']:>9.3f}{got['zeta_h']:>8.3f}"
                    f"{got['lambda2']:>9.4f}"
                )

    if not rows:
        return

    # The controls, built to the length and volatility of the first real cell
    # so the estimator sees the same sample size it saw on the market.
    n = len(rows[0]["moves"])
    sigma = rows[0]["sigma"]
    print()
    controls = (
        ("walk, constant vol", walk_returns(n, sigma, SEED)),
        ("OU log-vol, true H 0.5", ou_volatility_returns(n, sigma, SEED + 1)),
        ("GARCH(1,1) t(5)", garch_returns(n, sigma, SEED + 2)),
    )
    made = []
    for label, moves in controls:
        got = report_series(label, moves)
        if not got:
            continue
        made.append(got)
        print(
            f"{got['label']:<26}{got['points']:>7.0f}"
            f"{got['logvol_h']:>10.3f}{got['logvol_swing']:>8.3f}"
            f"{got['level_h']:>9.3f}{got['zeta_h']:>8.3f}"
            f"{got['lambda2']:>9.4f}"
        )

    traded = [r for r in rows if not r["label"].startswith("*")]
    generated = [r for r in rows if r["label"].startswith("*")]
    print("\n== the readings, as medians")
    for tag, pool in (("traded", traded), ("generated", generated)):
        if not pool:
            continue
        print(
            f"{tag:<26}H logvol {statistics.median([r['logvol_h'] for r in pool]):>7.3f}"
            f"   swing {statistics.median([r['logvol_swing'] for r in pool]):>6.3f}"
            f"   lambda2 {statistics.median([r['lambda2'] for r in pool]):>8.4f}"
        )
    for got in made:
        print(
            f"{got['label']:<26}H logvol {got['logvol_h']:>7.3f}"
            f"   swing {got['logvol_swing']:>6.3f}   lambda2 {got['lambda2']:>8.4f}"
        )

    print(
        "\n   The line that decides the first claim is 'OU log-vol, true H 0.5'.\n"
        "   Its log-volatility is smooth and short-memoried by construction, so\n"
        "   whatever H the estimator returns for it is the estimator's answer to\n"
        "   a known 0.5. If the market and that control agree, the small exponent\n"
        "   is the proxy's estimation noise rather than the market's roughness.\n"
        "   And `swing` is why both have to be read together: the estimator cannot\n"
        "   tell a rough log-volatility from a weak one, because a series with no\n"
        "   volatility variation at all reads H = 0."
    )

    print("\n== does log-volatility need a ladder of modes, or one OU?")
    print(f"{'series':<26}{'ladder':>12}{'one OU':>12}{'gain':>9}{'base ratio':>12}")
    for got in rows + made:
        if "moves" not in got:
            series = log_volatility(dict(controls).get(got["label"], []), WINDOW)
        else:
            series = log_volatility(got["moves"], WINDOW)
        if len(series) < 400:
            continue
        scored = ladder_against_one(series, seed=SEED)
        if "ladder" not in scored or "one_ou" not in scored:
            continue
        ratio = scored["ladder_base"] / max(scored["one_ou_base"], 1e-30)
        print(
            f"{got['label']:<26}{scored['ladder']:>12.1f}{scored['one_ou']:>12.1f}"
            f"{scored['ladder'] - scored['one_ou']:>9.1f}{ratio:>12.1e}"
        )


if __name__ == "__main__":
    main()
