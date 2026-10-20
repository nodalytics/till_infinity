"""Four public BOCPD designs, each priced on the one column measured to pay.

`indicator-libraries.md` judged eight public sources on paper and named three
portable ideas and one refusal. Paper verdicts are cheap; this turns each into
a number on the metric `changepoint-increment.md` established - the
out-of-sample R2 that a change-point member's **inferred predictive standard
deviation** adds to a 48-lag ridge on forward log variance, which read +0.2253
to +0.2391 where the change-point columns themselves read nothing.

## The five claims under test

1. **An adaptive hazard beats a fixed one.** AE-SHIFT re-estimates the expected
   run length online from the spacing between detections. Ours is fixed at one
   change per ten days, per hour and portable. The hazard moves the run-length
   mixture, so it moves `sd` - the column that pays - which is why this is
   testable on the metric already in hand rather than on a detection count.

2. **AE-SHIFT learns it from the wrong spacing.** Its lambda updates only when
   a *signal* fires, which needs a detection **and** a direction **and** a side
   different from the last one. That is a direction-filtered subset, so the
   learned run length is biased long, which makes the hazard more conservative,
   which suppresses the next detection. The flaw is reproduced as its own arm
   rather than asserted.

3. **A plug-in sample variance is over-confident exactly at a reset.**
   AE-SHIFT uses `m2 / (cnt - 1)` as if known; the conjugate predictive is a
   Student-t whose scale carries `1 + 1/n` and whose tails are finite at small
   `n`. `n` is smallest at `r = 0`, which is where a break is declared.

4. **AE-BCP's observation throws the bar away.** It monitors
   `log(ret^2)`, a close-to-close estimator whose sampling variance
   `dispersion-noise.md` measures at **4.93** against **0.265** for log
   Garman-Klass - 18.6x noisier per bar. Its recursion is otherwise the
   cleanest of the four, so the estimator is separable from the design.

5. **EntropyLib's entropy is not a sequence statistic.** `H(p)` of the up-count
   over a window is a function of the count alone, so it is invariant to every
   permutation of that window. Part 0 proves that arithmetically rather than
   measuring it, and then the *sequence* versions - transition entropy and
   3-gram block entropy - are measured as dispersion features, which is the
   only form the idea was ever worth.

## The control that decides claim 1

A **sweep of fixed hazards**, from a quarter to four times the shipped rate. An
adaptive hazard that merely matches the best fixed hazard has saved a parameter
and learned nothing, and that is the likely outcome rather than the
uninteresting one: it would mean the hazard is not what limits this member.

Part A plants the effect first, per `show-power-before-reporting-a-null`: a
piecewise-constant log-variance series with a **known** regime spacing, where a
fixed hazard is wrong by construction and an adaptive one has something to
find. If the adaptive arm cannot win there it will not win on a market.
"""

from __future__ import annotations

import math
import sys
from collections import deque
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for q in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(q))

from cusum_regime import _fit  # noqa: E402
from dispersion_ml import LIMIT, SIZE, _design, parkinson  # noqa: E402
from dispersion_changepoint import _lags  # noqa: E402
from pattern_fingerprint import CACHE, classify, load  # noqa: E402

from till_infinity.statespace.changepoint import HAZARD, Changepoint  # noqa: E402

FRAMES = ("1h",)
TRADED = ("fx_major", "fx_cross", "metal")
CONTROLS = ("volatility",)
PER_CLASS = 3
HORIZONS = (1, 20)
SEED = 20261018

#: Hours a 1h bar covers, for the per-hour hazard.
STEP_HOURS = 1.0

#: The fixed sweep, as multiples of the shipped hazard. The control for claim 1.
MULTIPLES = (0.25, 1.0, 4.0)

#: Detections kept when averaging the spacing, as AE-SHIFT keeps 20.
MEMORY = 20
#: Clamp on the learned hazard, so one pathological spacing cannot make the
#: member either memoryless or permanent.
HAZARD_FLOOR = 1.0 / (100 * 24.0)
HAZARD_CEIL = 1.0 / 2.0

#: AE-SHIFT's published defaults.
RMAX = 60
PRIOR_VAR = 1.0
OBS_VAR = 0.5
MIN_VAR = 0.05
#: AE-BCP's.
ZLEN = 200
AE_RMAX = 100

#: Window for the entropy features, matched to the lag count so no arm sees
#: more history than another.
ENT_WINDOW = SIZE
FLAT_PCT = 55.0

#: Regime amplitude in the planted series, in log-variance units. Chosen so
#: the 48-lag baseline lands in the range real 1h FX gives (+0.09 to +0.20)
#: rather than at 0.98, where nothing can add anything.
AMPLITUDE = 0.35

#: Published cells this harness must reproduce before any arm is read.
#: `changepoint-increment.md`, 1h, median across instruments.
KNOWN = {("fx_cross", 20): (0.15, 0.35), ("fx_major", 1): (0.05, 0.25)}


# ----------------------------------------------------------------- part zero


def binary_entropy(sign: np.ndarray, window: int) -> np.ndarray:
    """`EntropyLib.f_binary_entropy`: `H(p)` of the up-count. As published."""
    up = (sign > 0).astype(float)
    out = np.full(len(up), np.nan)
    rolling = np.convolve(up, np.ones(window), mode="valid") / window
    p = np.clip(rolling, 1e-6, 1 - 1e-6)
    out[window - 1 :] = -(p * np.log(p) + (1 - p) * np.log1p(-p)) / math.log(2.0)
    return out


def ternary_entropy(values: np.ndarray, window: int, flat_pct: float = FLAT_PCT) -> np.ndarray:
    """`EntropyLib.f_ternary_entropy`, with its percentile flat zone."""
    out = np.full(len(values), np.nan)
    size = np.abs(values)
    for i in range(window - 1, len(values)):
        block = size[i - window + 1 : i + 1]
        thr = float(np.percentile(block, flat_pct))
        window_values = values[i - window + 1 : i + 1]
        pu = max(float((window_values > thr).mean()), 1e-6)
        pd = max(float((window_values < -thr).mean()), 1e-6)
        pf = max(float((size[i - window + 1 : i + 1] <= thr).mean()), 1e-6)
        total = pu + pd + pf
        pu, pd, pf = pu / total, pd / total, pf / total
        out[i] = -(pu * math.log(pu) + pd * math.log(pd) + pf * math.log(pf)) / math.log(3.0)
    return out


def transition_entropy(sign: np.ndarray, window: int) -> np.ndarray:
    """Entropy of the 2x2 transition table. **Not** permutation-invariant."""
    up = (sign > 0).astype(int)
    out = np.full(len(up), np.nan)
    for i in range(window, len(up)):
        a, b = up[i - window : i], up[i - window + 1 : i + 1]
        counts = np.zeros(4)
        for first, second in zip(a, b, strict=True):
            counts[first * 2 + second] += 1
        p = counts / max(counts.sum(), 1.0)
        p = p[p > 0]
        out[i] = float(-(p * np.log(p)).sum() / math.log(4.0))
    return out


def block_entropy(sign: np.ndarray, window: int, size: int = 3) -> np.ndarray:
    """Entropy over `size`-gram blocks of the sign. Low means persistent runs."""
    up = (sign > 0).astype(int)
    codes = np.full(len(up), -1)
    for k in range(size):
        codes[size - 1 :] = np.where(codes[size - 1 :] < 0, 0, codes[size - 1 :]) + up[
            size - 1 - k : len(up) - k
        ] * (2**k)
    out = np.full(len(up), np.nan)
    for i in range(window + size, len(up)):
        block = codes[i - window : i + 1]
        counts = np.bincount(block[block >= 0], minlength=2**size).astype(float)
        p = counts / max(counts.sum(), 1.0)
        p = p[p > 0]
        out[i] = float(-(p * np.log(p)).sum() / math.log(2.0**size))
    return out


def part_zero(rng: np.random.Generator) -> None:
    """The claim that needs no market: two of these cannot see order at all.

    Each statistic is evaluated on **one window of exactly the length it
    needs**, and then on 200 permutations of that same window. Permuting
    inside the window is the whole test: it holds every count fixed and
    changes only the order, which is exactly what a sequence statistic is
    supposed to notice.
    """
    print("## Part 0: which of the four entropies can see the order of a window\n")
    #: Signed moves with varying magnitudes, in runs of 24. Varying magnitudes
    #: matter: on a series of plus and minus one the ternary arm's percentile
    #: threshold sits on the only value there is, every bar reads flat, and it
    #: is degenerate rather than blind.
    rows = (
        ("binary (as published)", ENT_WINDOW, lambda v: binary_entropy(v, ENT_WINDOW)),
        ("ternary (as published)", ENT_WINDOW, lambda v: ternary_entropy(v, ENT_WINDOW)),
        ("transition", ENT_WINDOW + 1, lambda v: transition_entropy(v, ENT_WINDOW)),
        ("block, 3-gram", ENT_WINDOW + 4, lambda v: block_entropy(v, ENT_WINDOW)),
    )
    print(
        f"{'statistic':>24}{'runs of 24':>13}{'shuffled mean':>15}"
        f"{'shuffled sd':>13}{'sees order':>12}"
    )
    for name, length, made in rows:
        size = np.abs(rng.normal(0.0, 1.0, length)) + 0.05
        signs = np.where((np.arange(length) // 24) % 2 == 0, 1.0, -1.0)
        window = signs * size
        ordered = float(made(window)[-1])
        draws = []
        for _ in range(200):
            shuffled = window.copy()
            rng.shuffle(shuffled)
            draws.append(float(made(shuffled)[-1]))
        spread = float(np.std(draws))
        print(
            f"{name:>24}{ordered:>13.4f}{float(np.mean(draws)):>15.4f}"
            f"{spread:>13.6f}{('yes' if spread > 1e-9 else 'NO'):>12}"
        )
    print(
        "\nOne window, every count held fixed, only the order changed. A statistic"
        "\nwith zero spread across 200 permutations is a function of the counts"
        "\nalone - the up-rate folded about its centre, and the up-rate is"
        "\ndirection. This is arithmetic, not a measurement: it needs no instrument"
        "\nand admits no sampling error.\n"
    )


# ------------------------------------------------------------------- part one


def planted(
    rng: np.random.Generator, spacing: int, rows: int = 6_000, amplitude: float = AMPLITUDE
) -> np.ndarray:
    """Log variance that is piecewise constant with a **known** regime spacing.

    The level switches between `-amplitude` and `+amplitude` with probability
    `1/spacing` per bar, under measurement noise at the variance
    `dispersion-noise.md` measured for a log range estimator (0.265). The
    shipped hazard is one change per 240 bars at 1h, so a spacing of 20 makes
    it twelve times too slow and 200 makes it about right.

    **Two states rather than a random walk in the level, and that is the
    calibration.** A walking level is recovered almost exactly by its own
    lags - the first version read `lin48` at 0.98 and left every arm with
    nothing to add, which measures the plant rather than the member.
    `AMPLITUDE` is set so the baseline lands near what real 1h FX gives.
    """
    side = 1.0
    out = np.zeros(rows)
    for i in range(rows):
        if rng.random() < 1.0 / spacing:
            side = -side
        out[i] = side * amplitude + float(rng.normal(0.0, math.sqrt(0.265)))
    return out


def part_a(rng: np.random.Generator) -> None:
    """Plant the effect before reporting on it, and say where the test is blind."""
    print("## Part A: a planted regime spacing, where a fixed hazard is wrong by construction\n")
    print(
        f"{'true spacing':>14}{'lin48':>10}{'+fixed':>10}"
        f"{'+haz x0.25':>12}{'+haz x4':>10}{'+adaptive':>11}{'learned':>12}"
    )
    for spacing in (20, 60, 200):
        series = planted(rng, spacing)
        _, y, start = _design(series, 1)
        skip = max(0, SIZE - 1 - start)
        y = y[skip:]
        first = start + skip
        cut = len(y) // 2
        base = float(y[:cut].mean())
        rows = slice(first, first + len(y))
        design = _lags(series, first, len(y))
        floor = _fit(design, y, cut, base)
        row = f"{spacing:>14}{floor:>10.4f}"
        learned = 0.0
        extra = ""
        for name, multiple in (("fixed", 1.0), ("x0.25", 0.25), ("x4", 4.0), ("adaptive", 1.0)):
            if name == "adaptive":
                column, learned = ours(series, adaptive="posterior")
                _, loose = ours(series, adaptive="posterior", rule="any")
                extra = f"   (any-fall rule: 1/{1.0 / loose:.0f}h)"
            else:
                column, _ = ours(series, multiple=multiple)
            got = _fit(
                np.hstack([design, np.asarray(column[rows], dtype=float).reshape(-1, 1)]),
                y,
                cut,
                base,
            )
            width = {"fixed": 10, "x0.25": 12, "x4": 10, "adaptive": 11}[name]
            row += f"{got - floor:>+{width}.4f}"
        row += f"   1/{1.0 / learned:>6.0f}h{extra}"
        print(row, flush=True)
    print(
        f"\nThe shipped hazard is one change per {1.0 / HAZARD:.0f}h. An adaptive arm"
        "\nthat recovers the planted spacing and beats the fixed one here has a"
        "\nmechanism; one that does not cannot be expected to find anything on a"
        "\nmarket, and the null that follows would be a null about this test.\n"
    )


# --------------------------------------------------------- the member's hazard


def fired(run_length: float, previous: float, rule: str) -> bool:
    """Whether a reset happened, by one of two readings of the posterior.

    **The learned hazard turns out to be a property of this function rather
    than of the series**, which is why both are arms. On planted spacings of
    20, 60 and 200 bars, `any` learns one change per five hours on all three -
    it is reporting its own trigger rate - while `halved` returns 62, 105 and
    168, monotone in the truth and compressed toward the middle.
    """
    if rule == "any":
        return run_length < previous - 0.5
    return previous > 2.0 and run_length < 0.5 * previous


def ours(
    series: np.ndarray,
    *,
    multiple: float = 1.0,
    adaptive: str = "",
    rule: str = "halved",
    observation: np.ndarray | None = None,
) -> tuple[np.ndarray, float]:
    """Our member's predictive sd per bar, and the hazard it ended on.

    `adaptive` is "" for a fixed hazard, "posterior" to learn the spacing from
    resets, or "signal" to learn it the way AE-SHIFT does - from detections
    that also flip a three-bar momentum and alternate side.
    """
    feed = series if observation is None else observation
    model = Changepoint(hazard=HAZARD * multiple)
    out = np.zeros(len(feed))
    gaps: deque[float] = deque(maxlen=MEMORY)
    previous = 0.0
    last_at = 0.0
    side = 0
    when = 0.0
    for i, value in enumerate(feed):
        when += STEP_HOURS
        model.update(float(value), 1.0, when * 3600.0)
        out[i] = float(model.sd)
        if not adaptive:
            continue
        length = float(model.run_length)
        detected = fired(length, previous, rule)
        previous = length
        if detected and adaptive == "signal":
            # AE-SHIFT's gate: a direction, and not the same side as last time.
            move = float(series[i] - series[max(i - 3, 0)])
            now = 1 if move > 0 else -1 if move < 0 else 0
            detected = now != 0 and now != side
            if detected:
                side = now
        if not detected:
            continue
        gap = when - last_at
        last_at = when
        if 1.0 < gap < 2_000.0:
            gaps.append(gap)
        if gaps:
            learned = 1.0 / (sum(gaps) / len(gaps))
            model.hazard = min(max(learned, HAZARD_FLOOR), HAZARD_CEIL)
    return out, float(model.hazard)


# ------------------------------------------------------- their two recursions


def theirs(
    series: np.ndarray,
    *,
    plugin: bool = True,
    rmax: int = RMAX,
    hazard: float = 1.0 / 50.0,
    score_driven: bool = False,
    omega: float = 1e-4,
    alpha: float = 0.05,
    beta: float = 0.94,
) -> np.ndarray:
    """AE-SHIFT's recursion, faithfully: Welford stats that travel with `r`.

    `plugin=False` swaps the plug-in sample variance for the conjugate
    Normal-Inverse-Gamma predictive scale, which is the only difference being
    priced. `score_driven` replaces the segment variance with the recursion
    Tsaknaki, Lillo and Mazzarisi 2023 give - **linear in the score**, which is
    the form `RegimeLib` squares.
    """
    probability = np.zeros(rmax + 1)
    probability[0] = 1.0
    count = np.zeros(rmax + 1)
    mean = np.zeros(rmax + 1)
    m2 = np.zeros(rmax + 1)
    variance = np.full(rmax + 1, PRIOR_VAR)
    out = np.zeros(len(series))
    for i, value in enumerate(series):
        fresh_p = np.zeros(rmax + 1)
        fresh_c = np.zeros(rmax + 1)
        fresh_m = np.zeros(rmax + 1)
        fresh_s = np.zeros(rmax + 1)
        fresh_v = np.full(rmax + 1, PRIOR_VAR)
        change = 0.0
        spread = 0.0
        for r in range(rmax + 1):
            weight = probability[r]
            if weight <= 1e-12:
                continue
            if score_driven:
                scale = max(variance[r], MIN_VAR)
            elif count[r] > 1.0:
                scale = max(m2[r] / (count[r] - 1.0), MIN_VAR)
            else:
                scale = max(PRIOR_VAR, MIN_VAR)
            if not plugin:
                # The conjugate inflation the Student-t carries and a plug-in
                # does not: the mean is itself uncertain by `scale / n`.
                scale *= 1.0 + 1.0 / max(count[r], 1.0)
            predictive = scale + OBS_VAR
            delta = value - mean[r]
            like = math.exp(-0.5 * delta * delta / predictive) / math.sqrt(
                2.0 * math.pi * predictive
            )
            spread += weight * predictive
            change += weight * like * hazard
            if r < rmax:
                fresh_p[r + 1] += weight * like * (1.0 - hazard)
                number = count[r] + 1.0
                shift = delta / number
                fresh_c[r + 1] = number
                fresh_m[r + 1] = mean[r] + shift
                fresh_s[r + 1] = m2[r] + delta * (value - (mean[r] + shift))
                if score_driven:
                    old = max(variance[r], MIN_VAR)
                    fresh_v[r + 1] = max(
                        omega + beta * old + alpha * (delta * delta - old), MIN_VAR
                    )
        fresh_p[0] = change
        fresh_c[0] = 1.0
        fresh_m[0] = value
        fresh_s[0] = 0.0
        total = fresh_p.sum()
        if total > 1e-12:
            probability = fresh_p / total
            count, mean, m2, variance = fresh_c, fresh_m, fresh_s, fresh_v
        out[i] = math.sqrt(max(spread, 1e-12))
    return out


def ae_bcp(series: np.ndarray, *, rmax: int = AE_RMAX, hazard: float = 1.0 / 60.0) -> np.ndarray:
    """AE-BCP's recursion: standardised observation, unit-variance conjugate.

    Its predictive variance `1 + 1/r` is the correct conjugate form for a known
    unit variance, which is why this arm prices its *observation* rather than
    its algebra - the standardisation pins the measurement variance at one, so
    there is nothing for it to infer.
    """
    out = np.zeros(len(series))
    probability = np.zeros(rmax + 1)
    probability[0] = 1.0
    sums = np.zeros(rmax + 1)
    for i, raw in enumerate(series):
        start = max(0, i - ZLEN + 1)
        block = series[start : i + 1]
        if len(block) < 20:
            out[i] = 1.0
            continue
        obs = float(np.clip((raw - block.mean()) / (block.std() + 1e-12), -6.0, 6.0))
        ranks = np.arange(rmax + 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            centres = np.where(ranks > 0, sums / np.maximum(ranks, 1), 0.0)
        spreads = np.where(ranks > 0, 1.0 + 1.0 / np.maximum(ranks, 1), 2.0)
        like = np.exp(-0.5 * (obs - centres) ** 2 / spreads) / np.sqrt(2.0 * math.pi * spreads)
        out[i] = math.sqrt(max(float((probability * spreads).sum()), 1e-12))
        change = float((probability * like * hazard).sum())
        grown = np.zeros(rmax + 1)
        grown[1:] = probability[:-1] * like[:-1] * (1.0 - hazard)
        fresh_sums = np.zeros(rmax + 1)
        fresh_sums[1:] = sums[:-1] + obs
        grown[0] = change
        total = grown.sum()
        if total > 1e-12:
            probability = grown / total
            sums = fresh_sums
            sums[0] = 0.0
    return out


# ------------------------------------------------------------------ the arms


def columns(bars: dict, logvar: np.ndarray) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    """Every arm's feature column for one instrument, and the hazards learned."""
    closes = bars["close"]
    returns = np.zeros(len(closes))
    returns[1:] = np.diff(np.log(closes))
    close_close = np.log(np.maximum(returns * returns, 1e-12))
    sign = returns

    made: dict[str, np.ndarray] = {}
    learned: dict[str, float] = {}

    for multiple in MULTIPLES:
        name = "ours.fixed" if multiple == 1.0 else f"ours.haz x{multiple:g}"
        made[name], _ = ours(logvar, multiple=multiple)
    made["ours.adaptive"], learned["adaptive"] = ours(logvar, adaptive="posterior")
    made["ours.adaptive.any"], learned["adaptive.any"] = ours(
        logvar, adaptive="posterior", rule="any"
    )
    made["ours.adaptive.signal"], learned["adaptive.signal"] = ours(logvar, adaptive="signal")
    made["ours.on close-close"], _ = ours(logvar, observation=close_close)

    made["theirs.aeshift plugin"] = theirs(logvar, plugin=True)
    made["theirs.aeshift conjugate"] = theirs(logvar, plugin=False)
    made["theirs.score-driven"] = theirs(logvar, plugin=False, score_driven=True)
    made["theirs.aebcp"] = ae_bcp(logvar)

    made["ent.binary"] = binary_entropy(sign, ENT_WINDOW)
    made["ent.ternary"] = ternary_entropy(sign, ENT_WINDOW)
    made["ent.transition"] = transition_entropy(sign, ENT_WINDOW)
    made["ent.block"] = block_entropy(sign, ENT_WINDOW)
    return made, learned


def score(bars: dict, frame: str) -> tuple[dict[tuple[int, str], float], dict[str, float]]:
    """Every arm at every horizon for one instrument, on identical rows."""
    bars = {k: v[-LIMIT:] for k, v in bars.items()}
    logvar = parkinson(bars["high"], bars["low"])
    if len(logvar) < 600 + SIZE:
        return {}, {}
    made, learned = columns(bars, logvar)

    out: dict[tuple[int, str], float] = {}
    for horizon in HORIZONS:
        x, y, start = _design(logvar, horizon)
        if len(y) < 600:
            continue
        skip = max(0, SIZE - 1 - start)
        y = y[skip:]
        first = start + skip
        cut = len(y) // 2
        base = float(y[:cut].mean())
        rows = slice(first, first + len(y))
        design = _lags(logvar, first, len(y))
        out[(horizon, "lin48")] = _fit(design, y, cut, base)
        for name, series in made.items():
            column = np.asarray(series[rows], dtype=float).reshape(-1, 1)
            if not np.isfinite(column).all():
                column = np.nan_to_num(column, nan=float(np.nanmedian(column)))
            out[(horizon, name)] = _fit(np.hstack([design, column]), y, cut, base)
    return out, learned


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        "Four public BOCPD designs, priced on the column measured to pay.\n"
        "Metric: out-of-sample R2 added to a 48-lag ridge forecasting forward log\n"
        "variance, median across instruments, fitted on each series' first half.\n"
        "Every arm contributes exactly one column, so they are comparable.\n",
        flush=True,
    )
    part_zero(rng)
    part_a(rng)

    groups: dict[str, list[str]] = {}
    for path in sorted(CACHE.glob("*.1h.npz")):
        name = path.name[: -len(".1h.npz")]
        groups.setdefault(classify(name), []).append(name)
    wanted = {k: v[:PER_CLASS] for k, v in groups.items() if k in TRADED + CONTROLS}
    print("classes:", ", ".join(f"{k} ({len(v)})" for k, v in sorted(wanted.items())), flush=True)

    for frame in FRAMES:
        per_class: dict[str, list[dict]] = {}
        hazards: dict[str, list[float]] = {}
        for klass, names in sorted(wanted.items()):
            for name in names:
                bars = load(name, frame)
                if bars is None:
                    continue
                got, learned = score(bars, frame)
                if got:
                    per_class.setdefault(klass, []).append(got)
                    for key, value in learned.items():
                        hazards.setdefault(f"{klass}.{key}", []).append(value)

        for horizon in HORIZONS:
            print(f"\n=== {frame}, h={horizon}: R2 of lin48, then each arm's increment")
            classes = sorted(per_class)
            print(f"{'arm':>26}" + "".join(f"{k:>13}" for k in classes))
            floors = {}
            for klass in classes:
                values = [
                    g[(horizon, "lin48")] for g in per_class[klass] if (horizon, "lin48") in g
                ]
                floors[klass] = float(np.median(values)) if values else float("nan")
            print(f"{'lin48 (baseline)':>26}" + "".join(f"{floors[k]:>13.4f}" for k in classes))
            names = [n for (h, n) in per_class[classes[0]][0] if h == horizon and n != "lin48"]
            for name in names:
                row = f"{name:>26}"
                for klass in classes:
                    values = [
                        g[(horizon, name)] - g[(horizon, "lin48")]
                        for g in per_class[klass]
                        if (horizon, name) in g
                    ]
                    row += f"{float(np.median(values)):>+13.4f}" if values else f"{'-':>13}"
                print(row, flush=True)
            for (klass, want), (floor, lifted) in (
                ((k, h), v) for (k, h), v in KNOWN.items() if h == horizon
            ):
                got = floors.get(klass, float("nan"))
                if got < floor:
                    print(f"  WARN {klass} h={horizon} lin48 {got:.4f} below the published {floor}")
                fixed = [
                    g[(horizon, "ours.fixed")]
                    for g in per_class.get(klass, [])
                    if (horizon, "ours.fixed") in g
                ]
                if fixed and float(np.median(fixed)) < lifted:
                    print(
                        f"  WARN {klass} h={horizon} lin48+sd {float(np.median(fixed)):.4f} "
                        f"below the published {lifted} - do not read the arms"
                    )

        print("\n=== hazards learned, as one change per N hours")
        for key in sorted(hazards):
            values = hazards[key]
            print(
                f"{key:>26}  median 1/{1.0 / float(np.median(values)):>9.1f}h"
                f"   fixed is 1/{1.0 / HAZARD:.0f}h"
            )
    print(
        "\n\nRead the fixed sweep first. An adaptive hazard that only matches the best\n"
        "fixed multiple has saved a parameter and found nothing, which would say the\n"
        "hazard is not what limits this member. Then `aeshift plugin` against\n"
        "`aeshift conjugate`, which differ in one term, and `ours.on close-close`\n"
        "against `ours.fixed`, which differ only in the estimator feeding them.",
        flush=True,
    )


if __name__ == "__main__":
    main()
