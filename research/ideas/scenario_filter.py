"""A filter per scenario, and a Monte Carlo band per horizon.

The design is written up in
[`fundamental-law.md`](../docs/fundamental-law.md); this is the measurement.
The operator's position, 2026-11-19: *"we are not looking for the rules to
carry from week to week or even from one period to the other, we acknowledge
the rules change and we are trying to adapt to the changing rules"*, and
*"if statespace can look for what worked in the last 1 day to 1 week and
applies it to the exact same scenario using monte carlo to gauge the deviation
rate"*.

So the thing on trial is **an estimator, not a rule**. What
[`rsi-ma-momentum.md`](../docs/rsi-ma-momentum.md) closed is one way of
adapting - rank the grid on the last window and take the leaders - which is a
sample mean with no memory model and no uncertainty attached. A filter is a
different estimator and gets its own forward test.

    scenario    the rule and its context, known at the decision bar: the
                reading, its reward multiple, the volatility band and the
                session band. Coarse on purpose - each one has to fire often
                enough to be estimated.
    edge        mu_t = mu_{t-1} + eta, var Q a day, observed through trades
                r = mu + eps, var R. A Kalman filter gives (m, P) after every
                trade. **Q is the memory**, swept from a one-day half-life to
                a one-week one rather than chosen.
    horizon     at a period boundary the uncertainty is grown to P + H*Q
                *before* the trades are drawn, so a one-week forecast is wider
                than a one-day one by the amount the edge can drift inside it.
    deviation   how often the realised period lands outside the band the
                simulation predicted. **Calibration is checked before any
                P&L**: a band that is too narrow understates the deviation and
                every decision built on it is overconfident.

Three controls, and the first is the one that matters:

* **shuffled scenario labels** - the same trades, the same filter, the scenario
  each trade belongs to permuted. If the filter scores the same, the scenario
  carries no information and the machinery is reading its own smoothing.
* **static** - the same filter with `Q = 0`, which is a mean over all history.
  Adapting has to beat not adapting.
* **last window's leaders** - the raw sample mean, already measured as a coin
  in `rsi-ma-momentum.md`, carried here so the two sit in one table.

Run as:

    uv run python research/ideas/scenario_filter.py --years 8 --frame 15m
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from persistence import trailing_rank  # noqa: E402
from reactive_zones import CATALOGUE, atr, fold, load, shuffled, window  # noqa: E402
from rsi_momentum import SPREADS, SYMBOLS, Readings, cells, race, sided  # noqa: E402

DAY = 86_400_000_000_000

#: Volatility and session bands. Three each, which keeps a scenario firing
#: every day or two; finer bands estimate better states of a market nobody
#: trades, which is `definitions-cannot-be-states` in another costume.
VOL_EDGES = (0.33, 0.67)
HOUR_EDGES = (8, 16)


@dataclass(slots=True)
class Trades:
    """Every trade the grid made, pooled, with its scenario and its context."""

    ts: np.ndarray
    net: np.ndarray
    scenario: np.ndarray
    symbol: np.ndarray
    names: list[str]


def collect(args: argparse.Namespace) -> Trades:
    """Run the grid once per instrument and label every trade's scenario.

    One continuous race per cell, as in `rsi_walkforward.py`: a race restarted
    at a period edge lets each period open with an entry the previous period's
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
        state = trailing_rank(band)
        hour = ((bars.ts // 3_600_000_000_000) % 24).astype(np.int64)
        cache = Readings.of(bars, band, every)
        points, tick = SPREADS[symbol]
        cost = points * tick
        for cell in every:
            side = sided(bars, band, cell, args, cache)
            got = race(bars, band, side, args.stop, cell.reward, args.patience, cost)
            if got.trades == 0:
                continue
            at = got.at
            vol = np.searchsorted(VOL_EDGES, np.nan_to_num(state[at], nan=0.5), side="right")
            session = np.searchsorted(HOUR_EDGES, hour[at], side="right")
            for row in range(at.size):
                key = (cell.reading, cell.reward, int(vol[row]), int(session[row]))
                if key not in names:
                    names[key] = len(names)
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


def filtered(
    stamps: np.ndarray, values: np.ndarray, noise: float, drift: float, seed: float
) -> tuple[np.ndarray, np.ndarray]:
    """One scenario's `(m, P)` after each of its trades, in time order.

    A random walk on the edge observed through single trades. `drift` is `Q`
    per **day**, so the prediction step grows `P` by the real elapsed time and
    a scenario that has not fired for a week arrives at the next period as
    uncertain as that gap deserves - which is the whole point of using a filter
    rather than a trailing mean.
    """
    m = np.zeros(values.size)
    p = np.zeros(values.size)
    estimate, spread = 0.0, seed
    previous = stamps[0] if stamps.size else 0
    for i in range(values.size):
        gap = max(float(stamps[i] - previous) / DAY, 0.0)
        spread += drift * gap
        gain = spread / (spread + noise)
        estimate += gain * (values[i] - estimate)
        spread *= 1.0 - gain
        m[i], p[i] = estimate, spread
        previous = stamps[i]
    return m, p


@dataclass(slots=True)
class Forecast:
    """What the simulation said, and what happened."""

    horizon: float
    mean: np.ndarray
    low: np.ndarray
    high: np.ndarray
    below: np.ndarray
    realised: np.ndarray
    count: np.ndarray


def simulate(
    estimate: float,
    spread: float,
    periods: np.ndarray,
    cost: float,
    draws: int,
    rng: np.random.Generator,
) -> tuple[float, float, float, float]:
    """The predicted mean, 5th and 95th, and `P(mean R below cost)`.

    The edge is drawn from the posterior **already widened to the horizon**;
    the noise is drawn by **resampling whole past periods of the same length**,
    centred.

    That last choice is the whole of the calibration, and it took three goes:

    * drawing `n` residuals independently gives the variance of a mean of
      i.i.d. draws, `sigma^2 / n`. Coverage **0.431** against a target of 0.90.
    * resampling residuals in blocks of eight carries some clustering.
      Coverage **0.660**.
    * resampling *periods* carries the clustering, the within-period shape and
      - the part the first two both missed - **the variation in how many trades
      a period holds at all**. A period with three trades has a mean 2.6 times
      noisier than one with twenty, and a point estimate of the firing rate
      gives every period the band of an average one.

    Nothing is assumed about the shape of a period's distribution, which is
    the point: a barrier race's outcome is two-valued and a period of them is
    not remotely Gaussian.
    """
    edges = rng.normal(estimate, np.sqrt(max(spread, 1e-12)), draws)
    noise = periods[rng.integers(0, periods.size, draws)] if periods.size >= 4 else 0.0
    outcome = edges + noise
    return (
        float(outcome.mean()),
        float(np.percentile(outcome, 5)),
        float(np.percentile(outcome, 95)),
        float((outcome < cost).mean()),
    )


@dataclass(slots=True)
class Tracked:
    """One scenario's trades with the filter already run along them.

    **Run once, indexed many times.** The first version re-filtered a
    scenario's whole history at every period boundary, which is
    `O(periods x trades)` and did not finish on two years of one instrument.
    The filter is causal, so its state after trade `i` is the state any
    boundary after trade `i` needs.
    """

    ts: np.ndarray
    net: np.ndarray
    m: np.ndarray
    p: np.ndarray


def track(book: Trades, noise: float, drift: float, seed: float) -> dict[int, Tracked]:
    out: dict[int, Tracked] = {}
    for which in np.unique(book.scenario):
        mine = book.scenario == which
        stamps, values = book.ts[mine], book.net[mine]
        if values.size < 2:
            continue
        m, p = filtered(stamps, values, noise, drift, seed)
        out[int(which)] = Tracked(ts=stamps, net=values, m=m, p=p)
    return out


def forward(
    book: Trades,
    horizon: float,
    drift: float,
    noise: float,
    args: argparse.Namespace,
    rng: np.random.Generator,
    tracks: dict[int, Tracked] | None = None,
) -> Forecast:
    """Estimate to `t`, forecast `t + horizon`, step by `horizon`, repeat.

    **Stepped by the horizon and not by a day**, so successive one-week
    forecasts do not share six of their seven days - overlapping windows
    inflate a calibration count as surely as they inflate a permutation null.
    """
    if tracks is None:
        tracks = track(book, noise, drift, args.seed_var)
    width = int(horizon * DAY)
    start, finish = int(book.ts[0]), int(book.ts[-1])
    mean, low, high, below, got, counted = [], [], [], [], [], []
    edge = int(args.warm * DAY)
    for opens in range(start + edge, finish - width, width):
        closes = opens + width
        for seen in tracks.values():
            cut = int(np.searchsorted(seen.ts, opens, side="left"))
            if cut < args.least:
                continue
            ahead = slice(cut, int(np.searchsorted(seen.ts, closes, side="left")))
            if ahead.stop <= ahead.start:
                continue
            waited = max(float(opens - seen.ts[cut - 1]) / DAY, 0.0)
            spread = seen.p[cut - 1] + drift * (waited + horizon)
            estimate = float(seen.m[cut - 1])
            # The scenario's own past, cut into windows of exactly this
            # horizon, as period means centred on the current estimate.
            since = opens - int(args.lookback * DAY)
            first = int(np.searchsorted(seen.ts[:cut], since, side="left"))
            if cut - first < args.block:
                first = 0
            keys = seen.ts[first:cut] // width
            values = seen.net[first:cut]
            edges_at = np.flatnonzero(np.diff(keys)) + 1
            periods = np.asarray([part.mean() for part in np.split(values, edges_at) if part.size])
            predicted, lo, hi, risk = simulate(
                estimate, spread, periods - estimate, args.cost, args.draws, rng
            )
            mean.append(predicted)
            low.append(lo)
            high.append(hi)
            below.append(risk)
            got.append(float(seen.net[ahead].mean()))
            counted.append(int(ahead.stop - ahead.start))
    return Forecast(
        horizon=horizon,
        mean=np.asarray(mean),
        low=np.asarray(low),
        high=np.asarray(high),
        below=np.asarray(below),
        realised=np.asarray(got),
        count=np.asarray(counted, dtype=np.int64),
    )


def calibration(shot: Forecast) -> str:
    """Coverage of the 90% band, and the deviation rate, weighted by trades.

    **Before any P&L.** A band covering 70% of outcomes understates the
    deviation by a third, and every "trade it only if the chance of beating
    costs is high" decision built on it is overconfident by that much.
    """
    if shot.mean.size < 20:
        return f"{shot.horizon:g}d: {shot.mean.size} forecasts, too few"
    inside = (shot.realised >= shot.low) & (shot.realised <= shot.high)
    weight = shot.count / shot.count.sum()
    width = float(np.mean(shot.high - shot.low))
    return (
        f"{shot.horizon:g}d: {shot.mean.size:>4} forecasts  covered {inside.mean():.3f} "
        f"(trade-weighted {float((inside * weight).sum() / weight.sum()):.3f})  "
        f"deviation {1 - inside.mean():.3f}  band {width:.3f}R  "
        f"predicted {shot.mean.mean():+.4f} against {shot.realised.mean():+.4f}"
    )


def decided(shot: Forecast, confidence: float, cost: float) -> str:
    """What acting on the forecast would have returned, against two baselines.

    `below` is the simulated chance the scenario's next-period mean lands under
    `cost`, so `1 - below` is the chance it clears it. Taking everything is the
    duty-cycle twin that matters: on a book whose average is negative, any rule
    that trades less looks better, so the comparison is **per trade** and the
    row prints how many trades each arm kept.
    """
    if shot.mean.size < 20:
        return "too few forecasts"
    take = (1.0 - shot.below) >= confidence
    kept = shot.count[take].sum()
    whole = shot.count.sum()
    if kept < 50:
        return f"confidence {confidence:.2f}: kept {kept} trades, too few"
    mine = float(np.average(shot.realised[take], weights=shot.count[take]))
    everything = float(np.average(shot.realised, weights=shot.count))
    rng = np.random.default_rng(71)
    rows = np.flatnonzero(take)
    draws = [
        float(
            np.average(
                shot.realised[rows[pick]],
                weights=shot.count[rows[pick]],
            )
        )
        for pick in rng.integers(0, rows.size, (400, rows.size))
    ]
    # A random arm keeping the same share of forecasts: the duty-cycle twin.
    share = rows.size / shot.mean.size
    twins = []
    for _ in range(400):
        coin = rng.random(shot.mean.size) < share
        if shot.count[coin].sum() > 0:
            twins.append(float(np.average(shot.realised[coin], weights=shot.count[coin])))
    return (
        f"confidence {confidence:.2f}: kept {rows.size}/{shot.mean.size} forecasts "
        f"({kept:,}/{whole:,} trades)  {mine:+.4f}R "
        f"90% [{np.percentile(draws, 5):+.4f}, {np.percentile(draws, 95):+.4f}]  "
        f"against everything {everything:+.4f}R and a same-rate coin {np.mean(twins):+.4f}R"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--frame", default="15m")
    parser.add_argument("--unit", default="5m")
    parser.add_argument("--years", type=float, default=8.0)
    parser.add_argument(
        "--arm",
        default="real",
        choices=("real", "shuffled-bars", "shuffled-scenarios"),
        help="shuffled-scenarios permutes which scenario each trade belongs to",
    )
    parser.add_argument("--horizons", default="1,3,7")
    parser.add_argument(
        "--wander",
        default="0,0.002,0.005,0.01,0.02,0.05",
        help="daily standard deviation of the edge in R; Q is its square, 0 is static",
    )
    parser.add_argument("--block", type=int, default=8, help="past trades a scenario needs to resample")
    parser.add_argument("--confidence", default="0.5,0.6,0.7")
    parser.add_argument("--draws", type=int, default=2000)
    parser.add_argument("--warm", type=float, default=180.0, help="days before the first forecast")
    parser.add_argument("--least", type=int, default=20, help="past trades a scenario needs")
    parser.add_argument(
        "--lookback", type=float, default=180.0, help="days of past periods to resample from"
    )
    parser.add_argument("--cost", type=float, default=0.0, help="the bar a scenario has to clear, in R")
    parser.add_argument(
        "--seed-var",
        type=float,
        default=0.01,
        help="the filter's starting P; 0.01 is a +/-0.2R prior on a per-trade edge, not +/-0.5R",
    )
    parser.add_argument("--noise", type=float, default=0.0, help="observation variance, 0 measures it")
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
    args = parser.parse_args()

    book = collect(args)
    if args.arm == "shuffled-scenarios":
        # The same trades in the same order, each relabelled. Destroys exactly
        # the claim - that the scenario says something about the edge - and
        # nothing else, which is what `a-control-is-only-for-a-named-property`
        # asks of an arm.
        book.scenario = np.random.default_rng(37).permutation(book.scenario)
    noise = args.noise if args.noise > 0 else float(book.net.var(ddof=1))
    print(
        f"{len(book.names)} scenarios  {book.net.size:,} trades  {args.frame}  {args.years:g}y  "
        f"arm {args.arm}  observation variance {noise:.4f}  mean net {book.net.mean():+.4f}R"
    )

    for wander in (float(v) for v in args.wander.split(",")):
        # **Q is set on the scale of the thing it describes.** The first
        # version read `Q = P_seed / halflife`, with `P_seed = 0.25` - a prior
        # that says the edge could be anywhere in +/-0.5R. At a 3-day
        # half-life that is `Q = 0.0833` a day, so over a 7-day horizon the
        # edge was allowed to wander `sqrt(7 * 0.0833) = 0.76R`, and the band
        # came out **3.17R wide with 0.978 coverage**. For a per-trade edge
        # whose plausible range is a few hundredths of an R, that is wrong by
        # about two orders of magnitude - which is why one arm was far too
        # wide and the other, at Q = 0, far too narrow.
        #
        # `--wander` is therefore the daily standard deviation of the edge in
        # R, the quantity a person can actually reason about, and `Q` is its
        # square. 0 is the static arm.
        drift = wander**2
        label = "static (Q=0)" if wander <= 0 else f"edge wanders {wander:g}R a day (Q={drift:.2e})"
        print(f"\n  {label}")
        rng = np.random.default_rng(11)
        tracks = track(book, noise, drift, args.seed_var)
        for horizon in (float(v) for v in args.horizons.split(",")):
            shot = forward(book, horizon, drift, noise, args, rng, tracks)
            print(f"    {calibration(shot)}")
            for confidence in (float(v) for v in args.confidence.split(",")):
                line = decided(shot, confidence, args.cost)
                print(f"      {horizon:g}d {line}")


if __name__ == "__main__":
    main()
