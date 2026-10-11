"""Do the neural members beat the LTI ones, across four symbols and 3m to 1d?

Asked on 2026-10-10: test the state space members across timeframes, `selective`
in particular, on eurusd, xauusd, gbpusd and usdjpy - and **report all four of
the quantities a member exposes, not just the score**, with the per-point data
written out so what happened can be looked at rather than summarised.

The prediction on record is that selection **loses**: Gu and Dao's own
limitation section says it "can impede their performance on data that LTI SSMs
excel on", that replacing S4 with S6 "significantly hampers performance" on
long-form audio, and that layers nearest a raw continuous signal "should be
LTI". A price series is a continuous-time quantity on a clock with no vocabulary
and nothing to retrieve by content.

## The four models, three of them nested

| model | what it adds |
| --- | --- |
| `linear` | three states, integrated jerk - a local Taylor expansion |
| `reverting` | two states, integrated OU - the rate pulls back |
| `selective` at `scale = 0` | **S4D-Real**: four LTI states, spectrum `-(n+1)` |
| `selective` with `scale` free | **S6**: the same, with `delta` reading the input |

The last two differ in exactly one parameter, so a gap between them is about
selection and nothing else. That is the clean experiment; `linear` and
`reverting` are the incumbents it has to beat to matter.

## What is reported, and why all four quantities

A log-likelihood says which model fits. It does not say whether the thing is
usable, and the four accessors answer different questions:

* **prediction** - `output()`. Reported as RMSE against the reading, in
  volatility units, because a likelihood can be won by being well-calibrated
  about being wrong.
* **uncertainty** - `sd` and `band()`. Reported as **coverage**: the share of
  readings inside the two-sigma band, which should be about 95%. This is the
  column that separates an *inferred* spread from a fitted one -
  `selective`'s `sd` is a parameter, not a posterior, so its band has no reason
  to be honest and this says whether it is.
* **log density** - `loglike` a point, and the standardised innovations through
  `diagnostics.residuals`: Ljung-Box for "the state equation is wrong" and
  Jarque-Bera for "the noise model is".
* **existence** - the one real probability, which decays on elapsed time alone.
  Reported as its final value, which is a check that the member was fed a
  sensible clock as much as anything.

## The data

Every held-out point of every winning fit is written to `RESULTS` as gzipped
CSV: symbol, timeframe, model, index, time, measured, prediction, sd, band,
standardised innovation, cumulative log-likelihood, existence. Fetch it with
`./.secrets/lab.sh fetch results .secrets/statespace` and the whole run can be
re-analysed without re-running it.

## What this cannot settle

**Bars are not touches.** A close moves because price moved; a level is not
supposed to. This sets the direction and none of the constants, the same caveat
every harness here carries, and the version on touches - which the episode
record's `entry` supports, 250,412 of them - is a different harness.

Runs on the lab. Production has two cores and a 2.6GB container limit, and
research on it OOM-killed the live desk three times - see `research/starving.md`.
"""

from __future__ import annotations

import csv
import gzip
import math
import os
import statistics
from collections import Counter
from pathlib import Path

from till_infinity.structures.statespace.diagnostics import residuals
from till_infinity.structures.statespace.linear import Gaussian
from till_infinity.structures.statespace.reverting import Reverting
from till_infinity.structures.statespace.selective import Selective
from till_infinity.structures.statespace.swarm import Swarm

#: The four symbols, and where each timeframe lives. `seqlab` carries 3m, 15m,
#: 1h, 4h and 1d for all four; 30m exists only as a `fine` CSV. There is no 5m
#: for any of these - `data/fine` has 5m only for the boom/crash indices - so
#: 3m and 15m bracket it.
#: `(label, seqlab stem)`. The stems are not derivable from the labels - the
#: synthetics are `Volatility_75_Index` in `seqlab` and `volatility_75_index` in
#: the journal - so they are written out rather than case-mangled.
SYMBOLS = (
    ("eurusd", "EURUSD"),
    ("xauusd", "XAUUSD"),
    ("gbpusd", "GBPUSD"),
    ("usdjpy", "USDJPY"),
    # **The Deriv synthetics are the control that matters.** Their volatility is
    # *generated* and stationary by construction, where an FX pair's is not. A
    # member that wins on both is describing something general; one that wins
    # only here is describing a simulator, and one that wins only on FX is
    # describing something the generator does not have.
    ("v25", "Volatility_25_Index"),
    ("v75", "Volatility_75_Index"),
    ("v100", "Volatility_100_Index"),
)

#: `seqlab` carries 3m, 15m, 1h, 4h and 1d for every one of these. 30m is a
#: `fine` CSV and exists only for the FX pairs, so it is skipped for the
#: synthetics with a line saying so.
PATHS = {
    "3m": "data/seqlab/{stem}.3m.npz",
    "15m": "data/seqlab/{stem}.15m.npz",
    "30m": "data/fine/{label}_30m_broker.csv.gz",
    "1h": "data/seqlab/{stem}.1h.npz",
    "4h": "data/seqlab/{stem}.4h.npz",
    "1d": "data/seqlab/{stem}.1d.npz",
}

#: Cap on bars a series. A 3m history is two orders of magnitude longer than a
#: 1d one; leaving that uncorrected compares models on 1d and sample size on 3m.
LIMIT = int(os.environ.get("LIMIT", "6000"))

#: Measurement noise in the normalised units, fixed across models so the
#: comparison is of dynamics rather than of who was handed a better `R`.
NOISE = float(os.environ.get("NOISE", "0.4"))

#: Where the per-point data lands, for fetching back and analysing.
RESULTS = Path(os.environ.get("RESULTS", "results/statespace_points.csv.gz"))


class RandomWalk:
    """The null every member here should have been scored against from the start.

    **Why it is needed now.** Every `selective` and `swarm` fit pinned `drift` at
    the top of its grid, and `drift` enters as `delta = hours * softplus(drift)`.
    As `drift` grows, retention `exp(delta * A)` goes to zero and every state
    collapses onto the current reading - so the limit of that family is exactly
    "the next value equals this one". Widening the grid without this arm in the
    table risks reporting a win for a four-state basis that is really a win for
    a random walk, and the whole point of the package's rule is that a member
    beats a *named* null.

    It carries one parameter, the predictive spread, so it is scored on the same
    likelihood as everything else. Deliberately not a library member: it is a
    null, not a model this desk would ship.
    """

    def __init__(self, noise: float = 1.0) -> None:
        self.noise = noise
        self.last: float | None = None
        self.at: float | None = None
        #: The bar length, learned as the smallest gap seen between readings,
        #: so `band` can diffuse per bar without being told the timeframe.
        self.step: float = 0.0
        self.when_last: float | None = None
        self.seen = 0
        self.loglike = 0.0
        self.last_standardised = 0.0
        self.existence = 1.0

    @property
    def value(self) -> float:
        return 0.0 if self.last is None else self.last

    def output(self) -> tuple[float, ...]:
        return (self.value,)

    @property
    def sd(self) -> float:
        return self.noise

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        return (self.value - sigmas * self.noise, self.value + sigmas * self.noise)

    def predict(self, when: float) -> None:
        self.at = when

    def at_time(self, when: float) -> float:
        """The last reading, at every horizon. **Flat is the point.**

        A random walk has no view beyond one bar, which is exactly why it is
        the right null here: a member carrying real structure has to separate
        from a flat line as `h` grows, and if it cannot then it has no
        structure.
        """
        return self.value

    def band(self, when: float, sigmas: float = 2.0) -> tuple[float, float]:
        """Widening as `sqrt(h)`, which is the other half of the null.

        A flat forecast with a *fixed* band would be a straw man - it would lose
        the coverage test at every horizon for a reason that has nothing to do
        with its forecast. The honest null diffuses: variance proportional to
        elapsed time. The bar length is learned from the intervals it has seen
        rather than passed in, so the null needs no parameter the members do not
        have.
        """
        bars = 1.0
        if self.step > 0 and self.at is not None:
            bars = max((float(when) - self.at) / self.step, 0.0)
        half = sigmas * self.noise * math.sqrt(max(bars, 1.0))
        return (self.value - half, self.value + half)

    def update(self, measured: float, noise: float, when: float | None = None) -> float:
        innovation = 0.0 if self.last is None else measured - self.last
        if self.last is not None:
            # `noise` is the measurement VARIANCE by the `Filter` contract.
            spread = math.sqrt(self.noise**2 + max(noise, 0.0))
            self.last_standardised = innovation / spread if spread > 0 else 0.0
            self.loglike += (
                -0.5 * (innovation / self.noise) ** 2
                - 0.5 * math.log(2.0 * math.pi)
                - math.log(self.noise)
            )
        if when is not None and self.when_last is not None and when > self.when_last:
            gap = when - self.when_last
            self.step = gap if self.step <= 0 else min(self.step, gap)
        if when is not None:
            self.when_last = when
        self.last = measured
        self.seen += 1
        return innovation


def closes(path: Path) -> list[tuple[float, float]]:
    """`(unix seconds, close)`, oldest first. Two shapes on this machine.

    `data/fine` and `data/candles` are gzipped CSV with
    `ts,open,high,low,close,volume`, and older extracts carry a `venue` column
    that has to be filtered to FOREXCOM. `data/seqlab` is an npz with `time` and
    `close` arrays; numpy is imported only on that branch, which is the one
    that needs it.
    """
    if path.suffix == ".npz":
        import numpy as np

        with np.load(path) as bundle:
            stamps = bundle["time"].tolist()
            prices = bundle["close"].tolist()
        return sorted(
            (float(t), float(c))
            for t, c in zip(stamps, prices, strict=True)
            if math.isfinite(t) and math.isfinite(c) and c > 0
        )

    opener = gzip.open if path.suffix == ".gz" else open
    out: list[tuple[float, float]] = []
    with opener(path, "rt") as fh:  # type: ignore[operator]
        for row in csv.DictReader(fh):
            if "venue" in row and row["venue"] not in ("FOREXCOM", "", None):
                continue
            stamp, close = row.get("ts"), row.get("close")
            if not stamp or not close:
                continue
            try:
                price = float(close)
            except ValueError:
                continue
            if price > 0:
                out.append((float(stamp), price))
    out.sort()
    return out


def measurements(rows: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    """Normalise to volatility units of the series' own bar.

    Cumulative return in basis points over an exponential average of absolute
    bar moves, so a 3m bar and a 1d bar arrive on one scale and a single `noise`
    and a single grid cover both. Without it, comparing across timeframes is
    comparing units. **And across symbols** - xauusd moves in different
    absolute terms from usdjpy, and this is what makes one table legitimate.
    """
    prices = [c for _t, c in rows]
    alpha = 1.0 - 0.5 ** (1.0 / 60.0)
    average = 0.0
    for i in range(1, len(prices)):
        move = abs(prices[i] - prices[i - 1]) / prices[i - 1] * 10_000
        average = move if i == 1 else average + alpha * (move - average)
    bps = max(average, 0.25)
    times = [t for t, _c in rows]
    values = [(c / prices[0] - 1.0) * 10_000 / bps for c in prices]
    return times, values


def drive(build, times: list[float], values: list[float], record: bool = False):
    """One pass. Returns `(loglike, seen, rows)`; `rows` only when recording.

    Everything is read **before** the reading is folded in, so `prediction`,
    `sd` and the band are what the member said in advance - the only order in
    which a coverage number means anything.
    """
    engine = build()
    rows: list[dict] = []
    for i, (when, value) in enumerate(zip(times, values, strict=True)):
        engine.predict(when)
        before = engine.loglike
        if record:
            prediction = engine.output()[0]
            spread = engine.sd
            exists = engine.existence
            # **A predictive band, not the state band.** `band()` returns the
            # interval for the *state*; a reading also carries measurement
            # noise, so coverage against the state band is coverage of the
            # wrong thing. Worse, it is not even wrong uniformly: `sd` is a
            # state spread on `linear`, `reverting` and `swarm` and a fitted
            # *predictive* spread on `selective`, so the first run of this
            # harness reported 50.3% for `linear` against 98.0% for
            # `selective` and that gap was two different quantities rather
            # than a calibration difference. Adding `R` back puts all of them
            # on the scale a reading actually lands on.
            predictive = math.sqrt(spread * spread + NOISE * NOISE)
            low, high = prediction - 2.0 * predictive, prediction + 2.0 * predictive
        engine.update(value, NOISE, when)
        if record:
            rows.append(
                {
                    "i": i,
                    "time": f"{when:.0f}",
                    "measured": f"{value:.6f}",
                    "prediction": f"{prediction:.6f}",
                    "sd": f"{spread:.6f}",
                    "sd_predictive": f"{predictive:.6f}",
                    "band_low": f"{low:.6f}",
                    "band_high": f"{high:.6f}",
                    "z": f"{engine.last_standardised:.6f}",
                    "loglike_step": f"{engine.loglike - before:.6f}",
                    "loglike_cum": f"{engine.loglike:.6f}",
                    "existence": f"{exists:.6f}",
                    "inside_band": int(low <= value <= high),
                }
            )
    return engine.loglike, engine.seen, rows


#: The horizons the h-step arm scores. One is kept so the new arm can be checked
#: against the old one; fifty is where a random walk has nothing left to say.
HORIZONS = (1, 5, 20, 50)


def ahead(build, times: list[float], values: list[float]) -> dict[int, tuple]:
    """Score each member `h` bars ahead, not one. `{h: (loglike/pt, rmse, cover)}`

    **Why this arm exists.** Every other number in this harness is a one-step
    predictive likelihood, and that is the objective a random walk is best at -
    it was always going to win there, and it did, 16 of 39 series. The desk does
    not trade one bar ahead. A random walk has **no view at all** beyond one
    bar: its forecast is flat and its band grows as `sqrt(h)`, so a member with
    any real structure should separate from it as `h` grows, and nowhere else.

    This is also the only arm where `swarm`'s anchor can show anything. The
    anchor exists so that extrapolation far ahead returns the level rather than
    decaying to zero, and at `h = 1` it has barely moved - the member was
    measured on the one horizon where its distinguishing feature does nothing.

    `at_time` and `band` are **side-effect free on every member**, checked
    rather than assumed, so the filter can be asked about the future without
    being advanced into it. That is what makes this honest: the member sees data
    up to `k` and nothing after it.
    """
    engine = build()
    out: dict[int, list] = {h: [[], [], []] for h in HORIZONS}
    biggest = max(HORIZONS)
    for k, (when, value) in enumerate(zip(times, values, strict=True)):
        engine.predict(when)
        engine.update(value, NOISE, when)
        if k < 30 or k + biggest >= len(values):
            continue
        for h in HORIZONS:
            future = times[k + h]
            truth = values[k + h]
            guess = engine.at_time(future)
            low, high = engine.band(future)
            # The band is +/- two sigma, so this recovers the member's own
            # h-step spread - which is the quantity being tested as much as the
            # point forecast is.
            spread = max((high - low) / 4.0, 1e-9)
            total = math.sqrt(spread * spread + NOISE)
            error = truth - guess
            out[h][0].append(
                -0.5 * (error / total) ** 2
                - 0.5 * math.log(2.0 * math.pi)
                - math.log(total)
            )
            out[h][1].append(error * error)
            out[h][2].append(1.0 if low <= truth <= high else 0.0)
    return {
        h: (
            statistics.fmean(v[0]) if v[0] else float("nan"),
            math.sqrt(statistics.fmean(v[1])) if v[1] else float("nan"),
            statistics.fmean(v[2]) if v[2] else float("nan"),
        )
        for h, v in out.items()
    }


def grids():
    """The four models as `(name, {label: factory})`.

    `read` is pinned at 1.0 throughout: `read` and `gain` are not jointly
    identifiable - one scales the state, the other scales the read-out of it -
    so a grid over both searches a ridge rather than a surface.

    **`drift` goes to 4.0 now.** The first run pinned at the top of a grid that
    stopped at 1.5 on all six timeframes, which made both selective columns
    lower bounds. `theta` and `jerk` are widened at both ends for the same
    reason: `theta` hit 0.1 at 15m and 2.0 at 1d, and both were edges.
    """
    jerks = [10.0**e for e in (-7, -6, -5, -4, -3, -2, -1, 0, 1)]
    thetas = (0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 12.0, 30.0)
    sigmas = (0.02, 0.05, 0.18, 0.5, 1.0, 2.0, 5.0)
    # **Widened to 16 after every fit pinned at 4.0.** `softplus(16) = 16`, so
    # `delta` reaches sixteen hours of decay per hour of clock, which drives
    # retention to `exp(-16) = 1e-7` at an hourly step - effectively the random
    # walk limit. If the fits still pin here, the answer is the `RandomWalk`
    # arm rather than a wider grid.
    drifts = (-2.0, -1.0, 0.0, 0.5413, 1.5, 2.5, 4.0, 8.0, 16.0)
    gains = (0.25, 0.5, 1.0)
    noises = (0.2, 0.4, 1.0, 2.0, 4.0, 8.0)
    scales = (0.1, 0.25, 0.5, 1.0)
    wanders = (0.005, 0.02, 0.1, 0.5, 2.0, 8.0)

    walk = {f"noise={n}": (lambda n=n: RandomWalk(noise=n)) for n in noises}
    linear = {f"jerk={j:.0e}": (lambda j=j: Gaussian(jerk=j)) for j in jerks}
    reverting = {
        f"theta={t} sigma2={s}": (lambda t=t, s=s: Reverting(theta=t, sigma2=s))
        for t in thetas
        for s in sigmas
    }
    lti = {
        f"drift={d} gain={g} noise={n}": (
            lambda d=d, g=g, n=n: Selective(drift=d, scale=0.0, gain=g, noise=n)
        )
        for d in drifts
        for g in gains
        for n in noises
    }
    live = {
        f"drift={d} scale={c} gain={g} noise={n}": (
            lambda d=d, c=c, g=g, n=n: Selective(drift=d, scale=c, gain=g, noise=n)
        )
        for d in drifts
        for c in scales
        for g in (1.0,)
        for n in noises
    }
    # `count = 1` is dropped: it scored -71 to -101,256 a point and the reason
    # is structural rather than a tuning failure - a zero eigenvalue cannot be
    # driven by the recurrence, so with one particle the anchor is never
    # corrected. Recorded in README.md; the budget goes to the wider grids.
    swarm = {
        f"drift={d} wander={w} noise={n}": (
            lambda d=d, w=w, n=n: Swarm(drift=d, scale=0.0, wander=w, noise=n)
        )
        for d in (0.0, 0.5413, 1.5, 4.0, 8.0, 16.0)
        for w in wanders
        for n in (0.4, 1.0, 2.0, 4.0)
    }
    return [
        ("random walk", walk),
        ("linear", linear),
        ("reverting", reverting),
        ("S4D-Real LTI", lti),
        ("S6 selective", live),
        ("swarm (anchored+particles)", swarm),
    ]


def main() -> None:
    print("state space members, fitted on the first half and scored on the second")
    print(f"noise={NOISE}, up to {LIMIT} bars a series, four symbols, 3m to 1d")
    print(f"per-point data -> {RESULTS}\n")

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "symbol",
        "timeframe",
        "model",
        "params",
        "i",
        "time",
        "measured",
        "prediction",
        "sd",
        "sd_predictive",
        "band_low",
        "band_high",
        "z",
        "loglike_step",
        "loglike_cum",
        "existence",
        "inside_band",
    ]
    table: dict[tuple[str, str], dict[str, float]] = {}
    multi_table: dict[tuple[str, str], dict[str, dict]] = {}
    edges: list[str] = []

    with gzip.open(RESULTS, "wt", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()

        for symbol, stem in SYMBOLS:
            for timeframe, template in PATHS.items():
                path = Path(template.format(stem=stem, label=symbol))
                if not path.exists():
                    print(f"  {symbol} {timeframe:<4} no file at {path}")
                    continue
                rows = closes(path)
                if len(rows) > LIMIT:
                    rows = rows[-LIMIT:]
                if len(rows) < 400:
                    print(f"  {symbol} {timeframe:<4} only {len(rows)} bars, skipped")
                    continue
                times, values = measurements(rows)
                half = len(values) // 2

                print(f"=== {symbol} {timeframe}: {len(values)} bars ===")
                scores: dict[str, float] = {}
                horizons: dict[str, dict] = {}
                for name, builds in grids():
                    best = (-math.inf, None)
                    for label, build in builds.items():
                        total, seen, _ = drive(build, times[:half], values[:half])
                        if math.isfinite(total) and seen and total > best[0]:
                            best = (total, label)
                    if best[1] is None:
                        print(f"  {name:<26} no fit")
                        continue
                    params = best[1]
                    # Held out, from a fresh state, recording every point.
                    total, seen, points = drive(
                        builds[params], times[half:], values[half:], record=True
                    )
                    per = total / seen if seen else float("nan")
                    scores[name] = per

                    zs = [float(p["z"]) for p in points]
                    errs = [float(p["measured"]) - float(p["prediction"]) for p in points]
                    inside = statistics.fmean(float(p["inside_band"]) for p in points)
                    rmse = math.sqrt(statistics.fmean(e * e for e in errs))
                    diag = residuals(zs)
                    lb = f"{diag.ljung_box_p:.3f}" if diag else "  -  "
                    jb = f"{diag.jarque_bera_p:.3f}" if diag else "  -  "
                    print(
                        f"  {name:<26} loglike {per:+8.3f}/pt  rmse {rmse:7.3f}  "
                        f"cover {inside:5.1%}  LB p {lb}  JB p {jb}  "
                        f"exists {float(points[-1]['existence']):.3f}"
                    )
                    if any(
                        e in params
                        for e in ("drift=16.0", "theta=30.0", "theta=0.01", "wander=8.0")
                    ):
                        edges.append(f"{symbol} {timeframe} {name}: {params}")

                    multi = ahead(builds[params], times[half:], values[half:])
                    horizons[name] = multi
                    cells = "".join(
                        f"{multi[h][0]:>9.3f}" for h in HORIZONS if h in multi
                    )
                    print(f"    {'h-step loglike/pt':<24}{cells}")

                    for point in points:
                        writer.writerow(
                            {
                                "symbol": symbol,
                                "timeframe": timeframe,
                                "model": name,
                                "params": params,
                                **point,
                            }
                        )
                table[(symbol, timeframe)] = scores
                multi_table[(symbol, timeframe)] = horizons
                if scores:
                    print(f"  -> best: {max(scores, key=lambda k: scores[k])}\n")

    names = [name for name, _ in grids()]
    print("=== held-out log-likelihood a point (higher is better) ===")
    print(f"  {'symbol':<8}{'tf':<5}" + "".join(f"{n[:13]:>15}" for n in names) + "   best")
    for (symbol, timeframe), scores in table.items():
        cells = "".join(f"{scores.get(n, float('nan')):>15.3f}" for n in names)
        best = max(scores, key=lambda k: scores[k]) if scores else "-"
        print(f"  {symbol:<8}{timeframe:<5}{cells}   {best}")

    print("\n=== h-step ahead: where a random walk has nothing left to say ===")
    print("  held-out log-likelihood a point at each horizon. A random walk's")
    print("  forecast is flat beyond one bar, so a member with real structure")
    print("  should separate from it as h grows - and nowhere else.\n")
    names_h = [n for n, _ in grids()]
    print(f"  {'series':<14}{'member':<28}" + "".join(f"{f'h={h}':>9}" for h in HORIZONS))
    wins = {h: Counter() for h in HORIZONS}
    for (symbol, timeframe), per in multi_table.items():
        for name in names_h:
            if name not in per:
                continue
            cells = "".join(f"{per[name][h][0]:>9.3f}" for h in HORIZONS)
            print(f"  {symbol + ' ' + timeframe:<14}{name:<28}{cells}")
        for h in HORIZONS:
            ranked = [(per[n][h][0], n) for n in names_h if n in per]
            if ranked:
                wins[h][max(ranked)[1]] += 1
        print()
    print("  wins by horizon:")
    for h in HORIZONS:
        tally = ", ".join(f"{n} {c}" for n, c in wins[h].most_common())
        print(f"    h={h:<4} {tally}")

    print("\n=== and the h-step coverage, which is the band's own test ===")
    print(f"  {'member':<28}" + "".join(f"{f'h={h}':>9}" for h in HORIZONS))
    for name in names_h:
        cells = []
        for h in HORIZONS:
            vals = [
                per[name][h][2]
                for per in multi_table.values()
                if name in per and not math.isnan(per[name][h][2])
            ]
            cells.append(f"{statistics.fmean(vals):>9.1%}" if vals else f"{'-':>9}")
        print(f"  {name:<28}" + "".join(cells))
    print("  (nominal 95%. A member whose band is honest at h=1 and not at h=50")
    print("   is one whose widening rate is wrong, which is a different fault")
    print("   from a bad point forecast.)")

    print("\n=== selection, the one clean experiment ===")
    print("  `S4D-Real LTI` against `S6 selective`: the same model, one parameter apart.")
    helped = 0
    for (symbol, timeframe), scores in table.items():
        if "S4D-Real LTI" in scores and "S6 selective" in scores:
            gap = scores["S6 selective"] - scores["S4D-Real LTI"]
            helped += gap > 1e-9
            verdict = "selection helps" if gap > 1e-9 else ("tie" if abs(gap) <= 1e-9 else "LTI wins")
            print(f"  {symbol:<8}{timeframe:<5} {gap:+9.4f}/pt  {verdict}")
    print(f"\n  selection helped on {helped} of {len(table)} series")

    if edges:
        print("\n=== fits that pinned at a grid edge, so these are bounds ===")
        for line in edges:
            print(f"  {line}")


if __name__ == "__main__":
    main()
