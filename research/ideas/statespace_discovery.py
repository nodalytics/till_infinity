"""Run statespace discovery on real bars, with every arm, and report the nulls.

    uv run python research/ideas/statespace_discovery.py shapes
    uv run python research/ideas/statespace_discovery.py words
    uv run python research/ideas/statespace_discovery.py detectors
    uv run python research/ideas/statespace_discovery.py transitions
    uv run python research/ideas/statespace_discovery.py power

Four passes rather than one, because the readers differ in cost by two orders
of magnitude - the line-pair scan is 0.31s per 4,000 bars and `changepoint`'s
run-length posterior is 49.8s at the shipped hazard - and a sweep re-runs every
reader on every null draw of every series arm. Each pass declares its own
budget in `BUDGET` below.

## The series, and what each one is a control for

| series | what it is | what it is a control for |
| --- | --- | --- |
| eurusd 1h, btc 1h, gold 1h | traded | the subject |
| `walk` | gaussian walk, matched sigma | nothing is there by construction |
| `garch` | `nulls.garch`, matched sigma | clustering and fat tails, nothing else |
| `range` | reflected inside a band | **a range by construction**: a channel or rectangle reader that misses it is broken |
| `drift` | a two-state planted drift | **a planted regime**: a transition model that misses it is broken |

`walk` and `garch` are the **placebo pool**: they go through the identical code
path and `Sweep.blocked()` refuses the whole run if either produces a survivor.
A block of 8 found structure in 27 of 36 placebo pools on this desk, so a run
without that refusal is a run that has not been checked.

`range` and `drift` are **constructed stand-ins**. The real positive controls
are `Range_Break` and `Drift_Switch` in the lab's sequence cache, which is not
reachable from here; these are a reflected band and a planted two-state drift,
labelled as constructed so nobody quotes them as the Deriv feeds.
"""

from __future__ import annotations

import csv
import math
import random
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from till_infinity.statespace import searching, shaping, transitions  # noqa: E402
from till_infinity.statespace.actor import READINGS, detector_reader  # noqa: E402
from till_infinity.statespace.nulls import garch  # noqa: E402

PRICES = ROOT / ".data" / "prices" / "prices.db"
BINANCE = ROOT / ".data" / "binance2023"

#: Per pass: bars, draws and the candidate count it implies. Declared because
#: a null reported at 40 draws is a weaker statement than one at 200, and the
#: reader has to be able to tell which was run.
BUDGET = {
    "shapes": {"bars": 4000, "draws": 40},
    "words": {"bars": 6000, "draws": 30},
    "detectors": {"bars": 2500, "draws": 30},
    "transitions": {"bars": 4000, "draws": 200},
    "power": {"bars": 4000, "draws": 40},
    "confirm": {"bars": 4000, "draws": 200},
}


# ──────────────────────────────── the series ────────────────────────────────


def from_prices(feed: str, interval: str, bars: int) -> list[tuple[float, float, float, float]]:
    """The most recent `bars` closed bars for one feed, oldest first."""
    con = sqlite3.connect(PRICES)
    rows = con.execute(
        "SELECT open, high, low, close FROM bars WHERE feed = ? AND interval = ? "
        "AND source = 'tradingview' AND closed = 1 ORDER BY ts DESC LIMIT ?",
        (feed, interval, bars),
    ).fetchall()
    con.close()
    out = [(float(o), float(h), float(low), float(c)) for o, h, low, c in reversed(rows)]
    # A close outside [low, high] appears on about 1,200 daily and weekly bars
    # in this store and on none intraday. Dropped rather than clamped: a
    # clamped bar is a bar whose range the detector reads wrong.
    return [c for c in out if c[2] <= c[3] <= c[1] and c[2] <= c[0] <= c[1]]


def from_binance(symbol: str, bars: int) -> list[tuple[float, float, float, float]]:
    with (BINANCE / f"{symbol}.15m.csv").open() as handle:
        rows = list(csv.DictReader(handle))[-bars:]
    return [
        (float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])) for r in rows
    ]


def _sigma(candles: list[tuple[float, float, float, float]]) -> tuple[float, float]:
    """`(start price, per-bar log-return sd)` of a real series, for matching."""
    closes = [c[3] for c in candles]
    steps = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    mean = sum(steps) / len(steps)
    var = sum((s - mean) ** 2 for s in steps) / len(steps)
    return closes[0], math.sqrt(max(var, 1e-18))


def _wrap(closes: list[float], rng: random.Random, wick: float) -> list[tuple[float, float, float, float]]:
    """Hang plausible bars on a close path. `wick` is the range in sigmas."""
    out = []
    for i, close in enumerate(closes):
        span = abs(rng.gauss(0.0, wick)) * close + 1e-12
        low = close - rng.random() * span
        out.append((low + rng.random() * span, low + span, low, close))
        if i == 0:
            out[0] = (close, close + span, close - span, close)
    return out


def walk_like(candles, seed: int):
    """A gaussian walk at the same start and sigma. **Placebo pool.**"""
    start, sigma = _sigma(candles)
    rng = random.Random(seed)
    price, closes = start, []
    for _ in candles:
        price *= math.exp(rng.gauss(0.0, sigma))
        closes.append(price)
    return _wrap(closes, random.Random(seed + 1), sigma)


def garch_like(candles, seed: int):
    """Clustering and fat tails and nothing else. **Placebo pool.**"""
    start, sigma = _sigma(candles)
    steps = garch(len(candles), seed=seed, sigma=sigma)
    price, closes = start, []
    for step in steps:
        price *= math.exp(step)
        closes.append(price)
    return _wrap(closes, random.Random(seed + 2), sigma)


def range_like(candles, seed: int):
    """A reflected band: **a range by construction. Positive control.**

    `Range_Break` is the level and range positive control on this desk because
    it is a range by construction. This is the same property built locally: a
    walk reflected off two fixed edges, so a rectangle or channel reader that
    does not fire on it is broken rather than honest.
    """
    start, sigma = _sigma(candles)
    rng = random.Random(seed)
    width = 20.0 * sigma
    price, closes = start, []
    for _ in candles:
        price += rng.gauss(0.0, sigma) * start
        if price > start * (1 + width):
            price = start * (1 + width) - (price - start * (1 + width))
        if price < start * (1 - width):
            price = start * (1 - width) + (start * (1 - width) - price)
        closes.append(price)
    return _wrap(closes, random.Random(seed + 3), sigma)


def drift_like(candles, seed: int, regime: int = 250):
    """A two-state planted drift. **Positive control for a regime model.**

    `Drift_Switch` is the regime positive control. Here: the drift flips sign
    every `regime` bars at a magnitude of one sigma per bar, so a transition
    model that cannot find this one has no power to report a null with.
    """
    start, sigma = _sigma(candles)
    rng = random.Random(seed)
    price, closes, drift = start, [], 1.0
    for i, _ in enumerate(candles):
        if i % regime == 0:
            drift = -drift
        price *= math.exp(drift * sigma + rng.gauss(0.0, sigma))
        closes.append(price)
    return _wrap(closes, random.Random(seed + 4), sigma)


# ──────────────────────────────── the passes ────────────────────────────────


def _report(name: str, got: searching.Sweep, started: float) -> None:
    print(f"\n=== {name} ({time.time() - started:.0f}s) ===")
    print(got.verdict())
    # **Ranked by evidence, not by percentile**, because the test is two-sided:
    # a candidate below every draw of its hardest arm carries as much evidence
    # as one above, and a percentile sort would print it last.
    scored = sorted(
        (t for t in got.trials if t.scored and t.hardest is not None),
        key=lambda t: -t.hardest.evidence,
    )
    print(f"-- top 8 of {len(scored)} scored, by hardest-arm evidence")
    for trial in scored[:8]:
        print("  " + trial.line())
    refused: dict[str, int] = {}
    for trial in got.trials:
        if trial.refused:
            why = trial.refused.split(":")[0]
            refused[why] = refused.get(why, 0) + 1
    if refused:
        print(f"-- refused: {refused}")
    if got.placebo:
        kept = got.placebo_survivors()
        print(f"-- placebo pool: {len(got.placebo)} trials, {len(kept)} survived")
    stop = got.blocked()
    if stop:
        print(f"-- blocked: {stop}")
    print(f"-- trial sharpes for DSR: n={len(got.sharpes())}", end=" ")
    if got.sharpes():
        print(f"min {min(got.sharpes()):+.3f} max {max(got.sharpes()):+.3f}")
    else:
        print()


def shapes_pass() -> None:
    """The 19 line cells and 5 bar shapes, on traded bars and both controls.

    The placebo pool is scored **once per candidate set** and shared across the
    series, rather than re-scored per series. The pool's job is "nothing is
    there by construction", and the statistic is scale-free, so one pool
    answers for every series in the pass - which is what makes a placebo pool
    affordable on a family whose reader costs 0.31s per 4,000 bars per draw.
    """
    budget = BUDGET["shapes"]
    battery = searching.arms()
    scoring = {"draws": budget["draws"], "least_events": 30}
    cands = [c for c in shaping.candidates(window=60) if c.source in {"lines", "bar"}]
    print(f"{len(cands)} candidates: {len(shaping.cells())} line cells + bar shapes")

    base = from_prices("eurusd", "1h", budget["bars"])
    started = time.time()
    pool = searching.run(cands, walk_like(base, 21), battery, **scoring) + searching.run(
        cands, garch_like(base, 31), battery, **scoring
    )
    print(f"placebo pool: {len(pool)} trials on a matched walk and a matched GARCH "
          f"({time.time() - started:.0f}s)")

    for name, candles in (
        ("eurusd 1h", base),
        ("btc 1h", from_prices("btc", "1h", budget["bars"])),
        ("range (positive control)", range_like(base, 11)),
    ):
        started = time.time()
        got = searching.Sweep(
            trials=searching.run(cands, candles, battery, **scoring), placebo=pool
        )
        _report(f"shapes on {name} ({len(candles)} bars, {budget['draws']} draws)", got, started)

    # **The reach, swept.** `null-structure-claims-on-the-same-detector` asks
    # for both sides *and* a reach sweep, because a fixed reach is a parameter
    # that was chosen - `indicators.trend.REACH` is 3 and nothing here measured
    # it. Swept over the named cells only, not the whole grid: 19 cells at
    # three reaches is 57 trials, and the sample does not carry 19.
    named = [c for c in shaping.cells() if c in shaping.NAMED]
    across = [
        searching.Candidate(
            family="shape",
            name=shaping.NAMED[cell],
            question="dispersion",
            threshold=1.0,
            reader=shaping.reader(cell, window=60, reach=reach),
            source="lines",
            params=(("reach", float(reach)),),
        )
        for reach in (2, 3, 5)
        for cell in named
    ]
    started = time.time()
    got = searching.Sweep(
        trials=searching.run(across, base, battery, **scoring),
        placebo=searching.run(across, walk_like(base, 21), battery, **scoring),
    )
    _report(f"the named cells at reach 2, 3 and 5 on eurusd 1h ({len(across)} trials)", got, started)


def words_pass() -> None:
    """Every two-letter word over the HH/LH/HL/LL alphabet. 16 candidates."""
    budget = BUDGET["words"]
    # **A 30-bar window and 6 points, not 60 and 8.** The first run took 60/8
    # at stride 3 on 3,000 bars and every one of the 16 words was refused for
    # too few events: 70 confirmations in total, about 4 per word against a
    # floor of 25. That is `node.metrics.MinimumTrackRecord`'s case - the
    # family was unmeasurable rather than null - and a shorter window raises
    # the swing rate instead of lowering the floor.
    cands = [
        c
        for c in shaping.candidates(window=30, word_stride=1, word_count=6)
        if c.source == "structure"
    ]
    print(f"{len(cands)} structure words over a 30-bar window, 6 points, stride 1")
    base = from_prices("eurusd", "1h", budget["bars"])
    started = time.time()
    got = searching.sweep(
        cands,
        base,
        searching.arms(),
        placebo=[walk_like(base, 21)],
        draws=budget["draws"],
        least_events=25,
    )
    _report(f"structure words on eurusd 1h ({len(base)} bars)", got, started)


def detectors_pass() -> None:
    """The indicator panel: every catalogued reading, swept on the mean."""
    budget = BUDGET["detectors"]
    from till_infinity.indicators import BAR_DETECTORS

    # **The 75th, 90th and 95th percentile of each reading on eurusd 1h**, not
    # round numbers. A grid of round numbers lands in a different part of every
    # detector's distribution, so the event counts differ by two orders of
    # magnitude across the panel and the comparison is between sample sizes.
    # Measured on 2,500 bars, `research/ideas/statespace_discovery.py` with the
    # distribution probe.
    grid = {
        "changepoint": (0.37, 0.75, 0.93),
        "cusum": (1.16, 1.58, 1.73),
        "focus": (0.12, 0.19, 0.25),
        "trend": (0.72, 0.88, 0.92),
        "efficiency": (0.72, 0.88, 0.92),
        "variance_ratio": (1.2, 1.67, 2.25),
        "slope": (0.65, 0.93, 1.16),
        "trendlines": (3.37, 5.92, 8.11),
        # Small integers: `provisional` counts unconfirmed swings and `count`
        # counts open gaps, so there is no percentile to take - the reading is
        # 0, 1 or 2 and a threshold between them would be a fiction.
        "pips": (1.0, 2.0),
        "displacement": (1.67, 2.61, 3.25),
        "gaps": (1.0,),
        # Nautilus's own, bounded readings. Same percentiles, same series.
        "rsi": (0.67, 0.81, 0.87),
        "aroon": (78.6, 92.9, 100.0),
        "stochastics": (76.2, 91.5, 96.3),
    }
    cands: list[searching.Candidate] = []
    for name in sorted(READINGS):
        # **The first catalogued source only, and that is a budget decision.**
        # `BAR_DETECTORS` lists three sources for `changepoint` and `focus` and
        # two for five others, so sweeping them all would take the panel from
        # 39 candidates to about 70 - and at a target Sharpe of 1.5 one month of
        # data supports about one trial. The panel is already far over what the
        # sample carries; a source sweep would spend the rest of the budget on
        # the same question asked three ways.
        sources = BAR_DETECTORS.get(name, (None, ()))[1]
        source = str(sources[0]) if sources else ""
        # A shorter expected regime for `changepoint`, which sets its own
        # posterior cap from the hazard: at the shipped ten-day hazard the cap
        # is 720 components on hourly bars and one reader call is 49.8s.
        extra = {"hazard": 1.0 / 24.0} if name == "changepoint" else {}
        reader = detector_reader(name, source or None, **extra)
        for level in grid[name]:
            cands.append(
                searching.Candidate(
                    family="detector",
                    name=name,
                    question="dispersion",
                    threshold=level,
                    reader=reader,
                    source=source,
                    params=tuple(sorted((k, float(v)) for k, v in extra.items())),
                )
            )
    print(f"{len(cands)} detector candidates over {len(READINGS)} readings")
    base = from_prices("eurusd", "1h", budget["bars"])
    started = time.time()
    got = searching.sweep(
        cands,
        base,
        searching.arms(),
        placebo=[walk_like(base, 21)],
        draws=budget["draws"],
        least_events=25,
    )
    _report(f"detector panel on eurusd 1h ({len(base)} bars)", got, started)

    print("\n-- thresholds on the MEAN, not on z")
    for name in ("cusum", "trendlines", "variance_ratio", "displacement", "efficiency"):
        pick = next(c for c in cands if c.name == name)
        rows = searching.thresholds(pick, base, grid[name])
        shown = " | ".join(f"{r.threshold:g}: {r.mean:+.4f} ({r.events})" for r in rows)
        print(f"  {name}: {shown} - monotone {searching.monotone(rows)}")


def transitions_pass() -> None:
    """Two alphabets, each against its own labeller run over matched walks.

    **The structure alphabet is primary** and the regime one is secondary,
    which is the opposite of what the todo's ordering suggests - and the dry
    run is why. `VarianceRatio.z` crosses +/-2 on 47 of 700 hourly eurusd bars,
    so the regime sequence is 99.6% `walk` in one censored run of 543 hours:
    a matrix fitted to it has one informative row and `forecast_skill` reads
    hits 1.0000 against a control of 0.9947, which is a measurement of the
    label's degeneracy rather than of any transition. Reported, because that
    degeneracy *is* a reading - the traded variance ratio runs 0.980 falling to
    0.924 against 1.000 on an i.i.d. control, so the middle state is where the
    data mostly is.
    """
    budget = BUDGET["transitions"]
    base = from_prices("eurusd", "1h", budget["bars"])
    series = (
        ("eurusd 1h", base),
        ("range (positive control)", range_like(base, 11)),
        ("drift (positive control)", drift_like(base, 41)),
        ("walk (placebo)", walk_like(base, 21)),
    )
    for title, label, alphabet, draws in (
        ("structure HH/LH/HL/LL", _structure_labeller(), shaping.LETTERS, 30),
        ("regime by VarianceRatio.z", _regime_labeller(), ("reverting", "walk", "trending"), 30),
    ):
        readings = {}
        for name, candles in series:
            readings[name] = _one_transition(
                f"{title} on {name}", label, alphabet, candles, draws
            )
        _placebo_gate(title, readings)


def _placebo_gate(title: str, readings: dict) -> None:
    """Refuse any reading the placebo series also produced.

    **The gate, applied rather than left for a reader to notice.** A block of 8
    found structure in 27 of 36 placebo pools on this desk, and the first run
    of this pass put the duration gain on eurusd 1h at +1.3754 over its null
    at p 0.0323 - with the gaussian walk reading **+2.9144** on the identical
    statistic at the identical p. A finding the placebo beats is not a weak
    finding, it is the harness.
    """
    placebo = readings.get("walk (placebo)")
    print(f"\n--- placebo gate on {title}")
    if placebo is None:
        print("  no placebo reading: nothing here can be read")
        return
    for name, got in readings.items():
        if name == "walk (placebo)" or got is None:
            continue
        for key, mine in got.items():
            theirs = placebo.get(key)
            if theirs is None:
                continue
            verdict = "BLOCKED" if theirs >= mine else "clear"
            print(f"  {name} {key}: {mine:+.4f} against the placebo's {theirs:+.4f} - {verdict}")


def _one_transition(title, label, alphabet, candles, draws: int) -> dict | None:
    """One series, and the inflations a placebo gate has to compare."""
    started = time.time()
    sequence = label(candles)
    if len(sequence) < 8:
        print(f"\n=== {title} ===\n  {len(sequence)} labels: nothing to fit")
        return None
    fitted = transitions.fit(sequence, alphabet)
    print(f"\n=== {title} ({len(sequence)} labels) ===")
    print("\n".join(fitted.lines()))
    nulls = []
    for draw in range(draws):
        rng = random.Random(7_919 + draw)
        null = searching.walk_with_bar_geometry(candles, rng)
        got = label(null)
        if len(got) >= 8:
            nulls.append(transitions.fit(got, alphabet))
    removes = "the path structure, bar geometry kept"
    inflations: dict[str, float] = {}
    if nulls:
        diagonal = transitions.against(fitted, nulls, removes=removes)
        gain = transitions.against(
            fitted,
            nulls,
            removes=removes,
            of=transitions.mean_duration_gain,
            statistic="mean duration gain (nats)",
        )
        print(diagonal.line())
        print("  " + gain.line())
        inflations["diagonal inflation"] = diagonal.inflation
        inflations["duration gain inflation"] = gain.inflation
    for state in alphabet:
        got = fitted.durations(state)
        if not got.hours:
            print(f"  {state}: no completed dwell")
            continue
        print(
            f"  {state}: {len(got.hours)} dwells, mean {got.mean:.2f}h, Weibull shape "
            f"{got.shape():.3f}, duration gain {got.duration_gain():+.2f} nats (bar 1.92)"
        )
    skill = transitions.forecast_skill(sequence, alphabet, draws=draws)
    print(
        f"  forecast: hits {skill.hits:.4f} against duty-cycle control "
        f"{skill.control:.4f} on {skill.attempts} steps, stay rate "
        f"{skill.stay_rate:.4f} - excess {skill.excess:+.4f}"
    )
    if not math.isnan(skill.excess):
        inflations["forecast excess"] = skill.excess
    print(f"  ({time.time() - started:.0f}s)")
    return inflations


def _structure_labeller(window: int = 30, count: int = 6):
    """`Pips`' HH / LH / HL / LL at each swing's **confirmation** index.

    An event sequence rather than a per-bar state, because the question is
    which shape follows which shape - and `hours` is then the gap to the next
    confirmation, so a dwell is the time a label held. A per-bar expansion
    would make the diagonal the share of bars between swings, which is a
    measurement of the swing rate.
    """

    def label(candles):
        found = shaping.labels(candles, window=window, count=count)
        out = []
        for i, (at, name) in enumerate(found):
            nxt = found[i + 1][0] if i + 1 < len(found) else at + 1
            out.append((name, float(max(1, nxt - at))))
        return out

    return label


def _regime_labeller():
    """`VarianceRatio.regime` per bar, as the inference a matrix is fitted to.

    The regime name comes from the statistic that defines it - VR = 1 under a
    walk by construction - so it is the one label here with its own reference
    point. The same callable runs on the nulls, which is what makes the
    comparison a matrix fitted to a walk *through the same inference*.

    The thresholds are `VarianceRatio.regime`'s own, +/-2 on the homoscedastic
    z. Reproduced here rather than read off the property because the sweep
    reader returns a float per bar and the property is on the indicator; the
    two are asserted equal in `tests/test_statespace_searching.py`.
    """
    read = detector_reader("variance_ratio", "log_return", read=lambda i: i.z, signed=True)

    def label(candles):
        out = []
        for value in read(candles):
            if math.isnan(value):
                name = "walk"
            elif value > 2.0:
                name = "trending"
            elif value < -2.0:
                name = "reverting"
            else:
                name = "walk"
            out.append((name, 1.0))
        return out

    return label


def power_pass() -> None:
    """Plant a dispersion effect and sweep its strength until the test sees it."""
    budget = BUDGET["power"]
    base = from_prices("eurusd", "1h", budget["bars"])
    pick = next(c for c in shaping.candidates(window=60) if c.source == "bar")
    grid = (0.0, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0)
    started = time.time()
    rows = searching.power(pick, base, searching.arms(), grid, draws=budget["draws"])
    print(f"\n=== power of {pick.label} on eurusd 1h ({time.time() - started:.0f}s) ===")
    for row in rows:
        print(
            f"  plant {row.strength:>4.2f} sigma: lift {row.observed:+.4f} "
            f"hardest percentile {row.percentile:.3f} found {row.found}"
        )


def confirm_pass() -> None:
    """The one closest candidate, at 200 draws on four traded feeds.

    **The only trial worth spending.** At a target Sharpe of 1.5 one month of
    data supports about one trial, and the 30-candidate panel already spent
    more than the sample can carry - so a second look goes to the single
    candidate whose *mean* grid was monotone rather than to the whole panel
    again. `variance_ratio` at |z| 1.67 and 2.25 read -0.0930, +0.1238, +0.2897
    across the grid, the only monotone one of five, and it is also the only
    statistic in the panel with a null of its own: VR = 1 under a random walk
    by construction.

    Four feeds rather than one, and the two placebo series on each, because a
    reading that holds on one feed and not the others is a reading about that
    feed. Carrying an independent placebo pair in every harness caught two
    leaks in one run here.
    """
    budget = BUDGET["confirm"]
    reader = detector_reader("variance_ratio", "log_return")
    cands = [
        searching.Candidate(
            family="detector",
            name="variance_ratio",
            question="dispersion",
            threshold=level,
            reader=reader,
            source="log_return",
        )
        for level in (1.2, 1.67, 2.25)
    ]
    for feed, interval in (("eurusd", "1h"), ("gold", "1h"), ("spx500", "1h"), ("btc", "1h")):
        candles = from_prices(feed, interval, budget["bars"])
        started = time.time()
        got = searching.sweep(
            cands,
            candles,
            searching.arms(),
            placebo=[walk_like(candles, 21), garch_like(candles, 31)],
            draws=budget["draws"],
            least_events=25,
        )
        _report(f"variance_ratio on {feed} {interval} ({len(candles)} bars)", got, started)
        for pick in cands:
            rows = searching.thresholds(pick, candles, (1.2, 1.67, 2.25))
            shown = " | ".join(f"{r.threshold:g}: {r.mean:+.4f} ({r.events})" for r in rows)
            print(f"  mean grid: {shown} - monotone {searching.monotone(rows)}")
            break


PASSES = {
    "confirm": confirm_pass,
    "shapes": shapes_pass,
    "words": words_pass,
    "detectors": detectors_pass,
    "transitions": transitions_pass,
    "power": power_pass,
}


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "shapes"
    if which not in PASSES:
        raise SystemExit(f"{which!r} is not a pass. Known: {sorted(PASSES)}")
    PASSES[which]()
