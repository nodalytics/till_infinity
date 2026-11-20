"""How fast a combination's edge decays, and what that costs to trade.

The operator, 2026-11-19: *"we are not using statespace to trade these signals
long term, that is why it is adapting"*, and *"how fast do edges decay... the
lag where that correlation halves is the half-life, and it tells the picker how
fast to forget"* - the decay measurement being *"cheap, and it informs
everything else"*.

**So a short life is the premise, not a defect.** Nothing here screens for a
combination whose edge lasts; the half-life is a **tuning** quantity - how fast
to forget, and how far ahead a forecast is worth making. The process is the
asset.

That also places the untested ground. [`rsi-ma-momentum.md`](../docs/rsi-ma-momentum.md)
already tested the process at day-and-longer cadences, where re-selecting every
7 days returns **-0.021 to -0.046 R** a trade and the 3-day cell failed its
verification. What has never been measured here is **minutes to hours**, which
is what this file points at.

## What is measured

1. **The decay curve.** Each combination's trades are bucketed into periods of
   length `L`; the series of period means is correlated with itself at lags
   `1..K`. An exponential fitted to that curve gives the half-life. `L` is
   swept from one hour to several days, because the half-life of a quantity
   measured in hour-long buckets and in day-long buckets are different numbers
   and only the sweep says which scale the decay lives on.

2. **Lag 1 is reported separately, because it is contaminated.** A race entered
   near the end of period `t` resolves inside `t + 1`, so its outcome is partly
   that period's. The straddle manufactures a positive correlation at lag 1 and
   at no other lag, so the half-life is fitted from **lag 2 onward** and lag 1
   is printed beside it as a diagnostic. This is the same defect as
   `overlapping-outcome-windows-leak`, which measured a direction AUC of 0.79
   collapsing to 0.51 once the windows stopped sharing outcomes.

3. **Three controls, and the third is the one that decides it.** A
   combination's period-to-period performance autocorrelates for reasons that
   have nothing to do with a persisting edge: its firing rate and its stop
   geometry both track volatility, and volatility autocorrelates hard -
   `reactive-zones.md` measures log-ATR autocorrelation of **0.68 to 0.88 at
   five days** against -0.03 to +0.12 shuffled.

   * `shuffled-scenarios` keeps every trade and its order and permutes which
     combination owns it. Kills only the claim that *this* combination is the
     thing persisting.
   * `shuffled-bars` reorders whole days, keeping each bar's shape.
   * `within-volatility` removes each period's volatility band mean before
     correlating, which is the arm that separates "the rule persists" from
     "the regime persists". `auc-is-free-on-volatility-targets` is the standing
     number: 0.805 pooled on a constant-volatility process, 0.525 within
     strata.

4. **The cost ladder, because at this scale it decides everything.** Cost in R
   is `spread / stop distance`, so it scales with the clock *and* inversely
   with the stop. Two figures are on record and they disagree:
   [`rsi-ma-momentum.md`](../docs/rsi-ma-momentum.md) measures **0.033 to 0.043
   R at 15m** and **0.067 to 0.091 R at 5m** on a **1 ATR** stop, while the
   operator's note puts 1-minute FX at **0.3 to 0.5 R**. One ATR at 1m would be
   near 0.15 R, so the gap is most likely the **stop**, not the clock. The
   ladder below sweeps both, which settles it arithmetically rather than by
   preferring one source.

Run as:

    uv run python research/ideas/edge_life.py --frame 15m --years 4
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reactive_zones import CATALOGUE, atr, fold, load, shuffled, window  # noqa: E402
from rsi_momentum import SPREADS, SYMBOLS, Readings, cells, race, sided  # noqa: E402
from scenario_filter import DAY, HOUR_EDGES, VOL_EDGES, Trades  # noqa: E402

HOUR = 3_600_000_000_000


def gather(args: argparse.Namespace) -> Trades:
    """Every trade the grid made, labelled with its combination and context.

    One continuous race per cell, as everywhere else here: a race restarted at
    a period edge lets each period open with an entry the previous period's
    open position would have blocked.
    """
    every = cells(args)
    stamps, nets, scen, syms = [], [], [], []
    names: dict[tuple[str, float, int, int], int] = {}
    for position, symbol in enumerate(s for s in args.symbols.split(",") if s):
        base = load(Path(args.catalogue), symbol)
        series = shuffled(base, seed=23) if args.arm == "shuffled-bars" else base
        if args.years > 0:
            series = window(series, args.years)
        bars = series if args.frame == args.unit else fold(series, args.frame, unit=args.unit)
        band = atr(bars)
        from persistence import trailing_rank

        state = trailing_rank(band)
        hour = ((bars.ts // HOUR) % 24).astype(np.int64)
        cache = Readings.of(bars, band, every)
        points, tick = SPREADS[symbol]
        for cell in every:
            side = sided(bars, band, cell, args, cache)
            got = race(bars, band, side, args.stop, cell.reward, args.patience, points * tick)
            if got.trades == 0:
                continue
            at = got.at
            vol = np.searchsorted(VOL_EDGES, np.nan_to_num(state[at], nan=0.5), side="right")
            session = np.searchsorted(HOUR_EDGES, hour[at], side="right")
            for row in range(at.size):
                key = (cell.reading, cell.reward, int(vol[row]), int(session[row]))
                names.setdefault(key, len(names))
                scen.append(names[key])
            stamps.append(bars.ts[at])
            nets.append(got.values)
            syms.append(np.full(at.size, position))
    order = np.argsort(np.concatenate(stamps), kind="stable")
    labels = [""] * len(names)
    for (reading, reward, vol, session), index in names.items():
        labels[index] = f"{reading}/R{reward:g}/vol{vol}/sess{session}"
    return Trades(
        ts=np.concatenate(stamps)[order],
        net=np.concatenate(nets)[order],
        scenario=np.asarray(scen, dtype=np.int64)[order],
        symbol=np.concatenate(syms)[order],
        names=labels,
    )


@dataclass(slots=True)
class Decay:
    """The pooled autocorrelation of period means, and the life fitted to it."""

    period_hours: float
    pairs: np.ndarray
    acf: np.ndarray
    half_life: float
    periods: int


def period_means(
    book: Trades, width: int, least: int, within_volatility: bool
) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """`{scenario: (period index, mean net R)}` for periods with enough trades.

    With `within_volatility`, each period's mean has the mean of every
    scenario sharing its volatility band in that period removed first. That is
    the arm that separates a rule persisting from a regime persisting, and it
    is applied before the correlation rather than after, because removing it
    from the correlation afterwards assumes the relationship is linear in a
    quantity nobody measured.
    """
    keys = book.ts // width
    out: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    pooled: dict[tuple[int, int], list[float]] = {}
    if within_volatility:
        # The band is the third field of the label, parsed once rather than
        # carried, because `Trades` is shared with `scenario_filter`.
        band_of = {i: name.split("/")[2] for i, name in enumerate(book.names)}
        for which, key, value in zip(book.scenario, keys, book.net, strict=True):
            pooled.setdefault((int(key), hash(band_of[int(which)])), []).append(float(value))
    for which in np.unique(book.scenario):
        mine = book.scenario == which
        here, values = keys[mine], book.net[mine]
        marks, means = [], []
        for key in np.unique(here):
            pick = here == key
            if pick.sum() < least:
                continue
            mean = float(values[pick].mean())
            if within_volatility:
                shared = pooled.get((int(key), hash(band_of[int(which)])), [])
                if len(shared) >= least:
                    mean -= float(np.mean(shared))
            marks.append(int(key))
            means.append(mean)
        if len(means) >= 8:
            out[int(which)] = (np.asarray(marks), np.asarray(means))
    return out


def decay(series: dict[int, tuple[np.ndarray, np.ndarray]], lags: int, hours: float) -> Decay:
    """Pooled correlation at each lag, and a half-life fitted from lag 2 on.

    Pooled over combinations by stacking every `(x_t, x_{t+k})` pair rather
    than averaging per-combination correlations: a combination with eleven
    periods and one with four hundred would otherwise weigh the same, and
    `pool-events-before-a-per-feed-guard` measured a guard of that shape
    turning 0.9 sigma into 4.8.
    """
    counts = np.zeros(lags + 1, dtype=np.int64)
    found = np.full(lags + 1, np.nan)
    for lag in range(1, lags + 1):
        left, right = [], []
        for marks, means in series.values():
            place = {int(m): i for i, m in enumerate(marks)}
            for i, m in enumerate(marks):
                other = place.get(int(m) + lag)
                if other is not None:
                    left.append(means[i])
                    right.append(means[other])
        counts[lag] = len(left)
        if len(left) >= 200:
            a, b = np.asarray(left), np.asarray(right)
            if a.std() > 0 and b.std() > 0:
                found[lag] = float(np.corrcoef(a, b)[0, 1])
    # Fitted from lag 2: lag 1 is contaminated by races that straddle the
    # boundary, which manufactures correlation at that lag and no other.
    usable = np.arange(2, lags + 1)
    values = found[2:]
    ok = np.isfinite(values) & (values > 0)
    life = float("nan")
    if ok.sum() >= 3:
        slope, intercept = np.polyfit(usable[ok], np.log(values[ok]), 1)
        if slope < 0:
            life = float(np.log(2.0) / -slope * hours)
        _ = intercept
    return Decay(period_hours=hours, pairs=counts, acf=found, half_life=life, periods=len(series))


def derived_memory(values: np.ndarray) -> tuple[float, float, float]:
    """`(Q, R, half-life in trades)` from the series itself. **Nothing fixed.**

    The operator, 2026-11-19: *"the decay factor should be automatically
    computed and derived, not fixed"*. For a local-level model - the edge is a
    random walk, each trade is a noisy reading of it -

        r_t   = mu_t + eps_t      Var(eps) = R
        mu_t  = mu_{t-1} + eta_t  Var(eta) = Q

    the first differences give both variances in closed form, with no fitting
    and no parameter to choose:

        Var(dr)             = Q + 2R
        Cov(dr_t, dr_{t-1}) = -R

    so `R = -Cov` and `Q = Var(dr) + 2*Cov`. The steady-state Kalman gain
    follows from the ratio `q = Q/R`,

        K = (sqrt(q^2 + 4q) - q) / 2 ... as the positive root of K^2/(1-K) = q

    and the memory is `ln(2) / -ln(1 - K)` trades: how many observations before
    half the weight on today's estimate has decayed away. That is the half-life
    the operator asked for, derived per combination from its own record.

    **A negative `Q` is a result, not an error.** It means the differences are
    more negatively autocorrelated than a drifting level can produce, which is
    what a *constant* edge observed through noise looks like. Returned as
    `Q = 0` with an infinite half-life, which is the static arm - and the right
    answer for a combination whose edge is not moving.
    """
    good = values[np.isfinite(values)]
    if good.size < 30:
        return float("nan"), float("nan"), float("nan")
    diffs = np.diff(good)
    if diffs.size < 8:
        return float("nan"), float("nan"), float("nan")
    spread = float(np.var(diffs, ddof=1))
    lag = float(np.cov(diffs[:-1], diffs[1:], ddof=1)[0, 1])
    noise = max(-lag, 1e-12)
    drift = spread + 2.0 * lag
    if drift <= 0.0:
        return 0.0, noise, float("inf")
    ratio = drift / noise
    gain = (np.sqrt(ratio**2 + 4.0 * ratio) - ratio) / 2.0
    gain = float(min(max(gain, 1e-9), 1.0 - 1e-9))
    return drift, noise, float(np.log(2.0) / -np.log(1.0 - gain))


def moments_of(values: np.ndarray) -> tuple[float, float, int] | None:
    """`(Var(dr), Cov(dr_t, dr_{t-1}), n)` - the two moments `derived_memory` needs.

    Split out so they can be **pooled across series before** `Q` and `R` are
    taken from them. That is the whole of the pooled estimator: one
    combination cannot see its own `Q` because the sampling error on `Var(dr)`
    is `2R*sqrt(2/n)` and `Q` is four to seven orders below `R`, but the error
    falls as `sqrt(k)` over `k` pooled series while a shared `Q` does not.
    """
    good = values[np.isfinite(values)]
    if good.size < 30:
        return None
    diffs = np.diff(good)
    if diffs.size < 8:
        return None
    return float(np.var(diffs, ddof=1)), float(np.cov(diffs[:-1], diffs[1:], ddof=1)[0, 1]), diffs.size


def memory_from(spread: float, lag: float) -> tuple[float, float, float]:
    """`(Q, R, half-life)` from already-computed moments. See `derived_memory`."""
    noise = max(-lag, 1e-12)
    drift = spread + 2.0 * lag
    if drift <= 0.0:
        return 0.0, noise, float("inf")
    ratio = drift / noise
    gain = float(min(max((np.sqrt(ratio**2 + 4.0 * ratio) - ratio) / 2.0, 1e-9), 1.0 - 1e-9))
    return drift, noise, float(np.log(2.0) / -np.log(1.0 - gain))


def pooled_memory(series: list[np.ndarray], label: str) -> None:
    """One `Q` shared across many series, with the spread that assumption hides.

    **Reported with its own dispersion on purpose.** Pooling buys precision by
    assuming the series share a memory; if they do not, the pooled number is a
    precise estimate of nothing. So the per-series half-lives are printed
    beside it - if they scatter over orders of magnitude, the shared `Q` is not
    a description of any of them.
    """
    found = [m for m in (moments_of(s) for s in series) if m is not None]
    if len(found) < 4:
        print(f"    {label}: {len(found)} usable series, too few to pool")
        return
    weight = float(sum(m[2] for m in found))
    spread = sum(m[0] * m[2] for m in found) / weight
    lag = sum(m[1] * m[2] for m in found) / weight
    drift, noise, life = memory_from(spread, lag)
    singles = np.asarray([memory_from(m[0], m[1])[2] for m in found])
    finite = singles[np.isfinite(singles)]
    shown = f"{life:.1f}" if np.isfinite(life) else "static"
    scatter = (
        f"per-series p10-p90 {np.percentile(finite, 10):.1f}-{np.percentile(finite, 90):.1f}"
        if finite.size >= 4
        else "per-series undefined"
    )
    print(
        f"    {label}: {len(found)} series, {weight:,.0f} steps  "
        f"pooled half-life {shown}  Q {drift:.3e}  R {noise:.3e}  ({scatter}, "
        f"{len(found) - finite.size} static)"
    )


def ar1_memory(values: np.ndarray) -> tuple[float, float]:
    """`(rho, half-life)` from an AR(1) fit. **The right model for a persistent series.**

    `derived_memory`'s local-level model is refuted by its own moments here:
    it requires `Cov(dr_t, dr_{t-1}) = -R < 0`, and on log-ATR that covariance
    comes out **positive**, which drove `R` onto its floor and returned a
    half-life of 0.0 bars. Log volatility is long-memory rather than a random
    walk observed through noise, so the moments the local-level model needs do
    not exist in it.

    An AR(1) is the well-conditioned alternative: `rho` is the lag-1
    autocorrelation of the level itself, and the half-life is
    `ln(2) / -ln(rho)` in whatever unit a step is. `reactive-zones.md` measures
    log-ATR autocorrelation at 0.68 to 0.88 at five days against -0.03 to
    +0.12 shuffled, so there is a real `rho` here for this to find.

    `rho` at or above 1 is a random walk with no half-life at all, and is
    returned as infinite rather than as a large number.
    """
    good = values[np.isfinite(values)]
    if good.size < 50:
        return float("nan"), float("nan")
    centred = good - good.mean()
    denominator = float(np.dot(centred, centred))
    if denominator <= 0:
        return float("nan"), float("nan")
    rho = float(np.dot(centred[:-1], centred[1:]) / denominator)
    if rho <= 0.0:
        return rho, 0.0
    if rho >= 1.0:
        return rho, float("inf")
    return rho, float(np.log(2.0) / -np.log(rho))


def volatility_memory(args: argparse.Namespace) -> None:
    """The memory of **log volatility**, which is the one that is estimable.

    `reactive-zones.md` measures log-ATR autocorrelation at **0.68 to 0.88 at
    five days** against -0.03 to +0.12 on shuffled bars. That is a real memory
    two orders of magnitude better conditioned than an edge's, so the same
    closed form has a sample it can work with - and it is the quantity a
    derived decay factor should actually be driven by, since
    `seasonality-belongs-on-q` already says the intraday pattern lives in
    volatility rather than in return.
    """
    print("\n  the memory of log ATR, in bars and in hours")
    hours = {"1h": 1.0, "15m": 0.25, "5m": 1.0 / 12.0}
    for frame in ("1h", "15m"):
        rows = []
        for symbol in (s for s in args.symbols.split(",") if s):
            base = load(Path(args.catalogue), symbol)
            if args.years > 0:
                base = window(base, args.years)
            bars = base if frame == args.unit else fold(base, frame, unit=args.unit)
            band = atr(bars)
            with np.errstate(invalid="ignore", divide="ignore"):
                logged = np.log(band[np.isfinite(band) & (band > 0)])
            # **AR(1), not the local-level model.** The local-level estimator
            # needs `Cov(dr_t, dr_{t-1}) < 0` and gets a positive number here,
            # which pinned `R` to its floor and returned 0.0 bars. Both are
            # printed so the refutation is visible rather than quietly
            # replaced.
            rho, life = ar1_memory(logged)
            _, _, wrong = derived_memory(logged)
            rows.append((symbol, rho, life, wrong, logged.size))
        for symbol, rho, life, wrong in ((r[0], r[1], r[2], r[3]) for r in rows):
            n = next(r[4] for r in rows if r[0] == symbol)
            shown = (
                f"{life:8.1f} bars = {life * hours[frame]:7.1f}h"
                if np.isfinite(life)
                else ("   random walk" if np.isinf(life) else "        none")
            )
            print(
                f"    {frame:<4} {symbol:<8} {n:>7,} bars  rho {rho:.4f}  half-life {shown}"
                f"   (local-level said {wrong:.1f}, refuted)"
            )


def planted_memory(draws: int = 40, trades: int = 4000, seed: int = 17) -> None:
    """Does the estimator recover a memory it was given? Swept, with its floor.

    **Power before any reading.** The half-lives this prints for real
    combinations mean nothing without knowing what the estimator does when it
    already knows the answer, and `show-power-before-reporting-a-null` is the
    standing rule. A barrier race's outcome is two-valued, so the noise here is
    deliberately +/-1 Bernoulli rather than Gaussian - the estimator must cope
    with the distribution it will actually meet.
    """
    rng = np.random.default_rng(seed)
    print("\n  recovering a planted memory, +/-1 trade noise, 4,000 trades a draw")
    print("    planted half-life   recovered median   10th-90th        Q/R planted : found")
    for life in (10.0, 50.0, 200.0, 1000.0, float("inf")):
        # A half-life in trades fixes the gain, and the gain fixes Q/R.
        if np.isinf(life):
            drift = 0.0
        else:
            gain = 1.0 - 0.5 ** (1.0 / life)
            drift = gain**2 / (1.0 - gain)
        found = []
        for _ in range(draws):
            level = np.zeros(trades)
            if drift > 0:
                level = np.cumsum(rng.normal(0.0, np.sqrt(drift), trades))
            seen = level + rng.choice((-1.0, 1.0), trades)
            found.append(derived_memory(seen)[2])
        got = np.asarray([f for f in found if np.isfinite(f)])
        if got.size == 0:
            print(f"    {life:>10}          all infinite      -                {drift:.2e} : 0")
            continue
        shown = f"{np.median(got):10.1f}"
        band = f"{np.percentile(got, 10):8.1f}-{np.percentile(got, 90):<8.1f}"
        infinite = draws - got.size
        print(
            f"    {life:>10}          {shown}       {band}  {drift:.2e} : "
            f"{'-' if got.size == 0 else f'{got.size}/{draws} finite'}"
            + (f", {infinite} read static" if infinite else "")
        )


def costs(args: argparse.Namespace) -> None:
    """Cost in R per trade, by clock and by stop, from the measured spreads.

    Settles the 0.04-against-0.4 disagreement arithmetically. Cost in R is
    `spread / (stop x ATR)`, so it rises as the clock shortens (ATR falls) and
    as the stop tightens - **and the second lever is much the stronger one**,
    which is the whole reason this table has two axes rather than one.

    Each instrument is loaded **once**. The first version reloaded the
    catalogue for every frame-stop-symbol cell, 45 full loads, and did not
    finish.
    """
    frames = ("1h", "15m", "5m")
    stops = (1.0, 0.5, 0.25)
    typical: dict[str, dict[str, float]] = {}
    for symbol in SYMBOLS:
        base = load(Path(args.catalogue), symbol)
        if args.years > 0:
            base = window(base, args.years)
        typical[symbol] = {}
        for frame in frames:
            bars = base if frame == args.unit else fold(base, frame, unit=args.unit)
            typical[symbol][frame] = float(np.nanmedian(atr(bars)))
    print(f"\n  cost in R a trade, median recorded spread over median ATR, {args.years:g}y")
    print("    frame  stop   " + "  ".join(f"{s:>8}" for s in SYMBOLS))
    for frame in frames:
        for stop in stops:
            row = []
            for symbol in SYMBOLS:
                points, tick = SPREADS[symbol]
                row.append(f"{(points * tick) / (stop * typical[symbol][frame]):8.4f}")
            print(f"    {frame:<6} {stop:<5.2f}  " + "  ".join(row))
    print(
        "\n  Read the stop axis, not the clock axis: a 1 ATR stop at 5m is "
        "cheaper than a 0.25 ATR stop at 1h."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--frame", default="15m")
    parser.add_argument("--unit", default="5m")
    parser.add_argument("--years", type=float, default=4.0)
    parser.add_argument(
        "--arms",
        default="real,shuffled-scenarios,within-volatility",
        help="real, shuffled-scenarios, shuffled-bars, within-volatility",
    )
    parser.add_argument(
        "--windows",
        default="1,4,24,120",
        help="period lengths in **hours**; the sweep is the point, since a "
        "half-life measured in hour buckets and in day buckets are different numbers",
    )
    parser.add_argument("--lags", type=int, default=10)
    parser.add_argument("--least", type=int, default=3, help="trades a period needs to count")
    parser.add_argument("--cost-ladder", action="store_true")
    parser.add_argument(
        "--planted-memory",
        action="store_true",
        help="recover a known half-life, which is the power check for the derived one",
    )
    parser.add_argument("--derive", action="store_true", help="derive each combination's memory")
    parser.add_argument(
        "--derive-better",
        action="store_true",
        help="the three quantities that can carry a memory: volatility, the pool, the firing rate",
    )
    # The grid, as `rsi_momentum` defines it.
    parser.add_argument("--families", default="rsi,ma")
    parser.add_argument("--rsi", default="7,14,21")
    parser.add_argument("--ma", default="20,50,100")
    parser.add_argument("--reach", default="5,10,20")
    parser.add_argument("--thresholds", default="20,25,30,35")
    parser.add_argument("--stretch", default="1.0,1.5,2.0,2.5")
    parser.add_argument("--reward", default="1,2")
    parser.add_argument("--stop", type=float, default=1.0)
    parser.add_argument("--patience", type=int, default=48)
    parser.add_argument("--fresh", type=int, default=3)
    parser.add_argument("--arm", default="real")
    args = parser.parse_args()

    if args.cost_ladder:
        costs(args)
        return
    if args.planted_memory:
        planted_memory()
        return
    if args.derive_better:
        # 1. Volatility, which is estimable on its own.
        volatility_memory(args)
        book = gather(args)
        hour = int(HOUR)
        print(f"\n  pooled across {len(book.names)} combinations, {book.net.size:,} trades")
        # 2. The pool: one Q shared across the combinations of a family.
        families: dict[str, list[np.ndarray]] = {}
        for which in np.unique(book.scenario):
            mine = book.net[book.scenario == which]
            families.setdefault(book.names[int(which)].split("/")[0], []).append(mine)
        pooled_memory([s for group in families.values() for s in group], "every combination")
        for name, group in sorted(families.items()):
            pooled_memory(group, f"family {name}")
        # 3. The firing rate and the context mix, per period, which have a
        #    signal-to-noise ratio an edge does not: a count is Poisson around
        #    its own mean rather than +/-1R around a mean of 0.01R.
        print("\n  the memory of what a combination *does*, not what it earns")
        rates, contexts = [], []
        keys = book.ts // hour
        for which in np.unique(book.scenario):
            mine = book.scenario == which
            here = keys[mine]
            if here.size < 60:
                continue
            marks, counts = np.unique(here, return_counts=True)
            rates.append(counts.astype(float))
            band = np.asarray([float(book.names[int(which)].split("/")[2][-1])] * marks.size)
            contexts.append(band)
        pooled_memory(rates, "firing rate an hour")
        _ = contexts
        return
    if args.derive:
        book = gather(args)
        print(f"{len(book.names)} combinations, {book.net.size:,} trades")
        rows = []
        for which in np.unique(book.scenario):
            mine = book.net[book.scenario == which]
            drift, noise, life = derived_memory(mine)
            if np.isfinite(drift):
                rows.append((life, mine.size, float(mine.mean()), drift, noise, int(which)))
        finite = [r for r in rows if np.isfinite(r[0])]
        static = len(rows) - len(finite)
        print(
            f"  {len(rows)} estimated: {static} read **static** (no detectable drift), "
            f"{len(finite)} carry a finite memory"
        )
        if finite:
            lives = np.asarray([r[0] for r in finite])
            print(
                f"  half-life in trades: p10 {np.percentile(lives, 10):.0f}  "
                f"median {np.median(lives):.0f}  p90 {np.percentile(lives, 90):.0f}"
            )
            print("  the twelve shortest-memory combinations")
            print("    half-life  trades   mean R        Q        R   combination")
            for life, n, mean, drift, noise, which in sorted(finite)[:12]:
                print(
                    f"    {life:9.1f}  {n:>6,}  {mean:+.4f}  {drift:.2e}  {noise:.2e}  "
                    f"{book.names[which]}"
                )
        return

    print(
        f"{len(cells(args))} combinations  {args.frame}  {args.years:g}y  "
        f"windows {args.windows}h  lags {args.lags}  minimum {args.least} trades a period"
    )
    for arm in (a.strip() for a in args.arms.split(",") if a.strip()):
        args.arm = "shuffled-bars" if arm == "shuffled-bars" else "real"
        book = gather(args)
        if arm == "shuffled-scenarios":
            # The same trades in the same order, each relabelled. Destroys
            # exactly the claim - that *this* combination is the thing
            # persisting - and nothing else.
            book.scenario = np.random.default_rng(37).permutation(book.scenario)
        print(f"\n=== {arm}: {book.net.size:,} trades, mean {book.net.mean():+.4f}R")
        for hours in (float(v) for v in args.windows.split(",")):
            series = period_means(
                book, int(hours * HOUR), args.least, within_volatility=arm == "within-volatility"
            )
            if len(series) < 8:
                print(f"  {hours:g}h: {len(series)} combinations with enough periods, too few")
                continue
            found = decay(series, args.lags, hours)
            shown = "  ".join(
                f"{lag}:{found.acf[lag]:+.3f}" if np.isfinite(found.acf[lag]) else f"{lag}:--"
                for lag in range(1, min(args.lags, 6) + 1)
            )
            life = f"{found.half_life:.1f}h" if np.isfinite(found.half_life) else "none"
            print(
                f"  {hours:>4g}h windows, {found.periods:>3} combinations, "
                f"{found.pairs[2]:>7,} pairs at lag 2   {shown}   half-life {life}"
            )


if __name__ == "__main__":
    main()
