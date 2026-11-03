"""The next N bars as a distribution: P10 / P50 / P90, with percentiles that correct themselves.

`volatility.py` says how big a move is now; this says **where price can be N bars from now, and at
what probability** - a ceiling (P90), a median (P50) and a floor (P10) - on every series the engine
sees, not only the synthetics `projection.py` derives exactly.

## How the quantiles are formed

In units of the production volatility (`Volatility.ewma_tr_bps`, the 14-bar EWMA of true range), the
N-bar move `log(close[t+N] / close[t]) / sigma[t]` has a distribution a series carries with it: fat
tails and, on some instruments, skew. The envelope keeps the last `WINDOW` resolved values of it and
reads the quantiles off that history (the **empirical** envelope). Until the history is deep enough
it falls back to a normal with the random-walk scale.

## Why the percentiles correct themselves

A stated P90 is only worth quoting if it is hit 90% of the time, and a market that changes character
moves that silently: the same number can start behaving like a P80. So each level is corrected
online by **aggregated adaptive conformal inference**, AgACI (Zaffran et al. 2022, arXiv
2202.07282).

One ACI corrector (Gibbs & Candes, 2021) moves the level read off the history, `a`, after every
resolved outcome by `a <- a + gamma * (target - hit)`, where `hit` is whether the outcome fell below
what that corrector quoted. A P90 being hit 80% of the time is read from further up the tail until
it covers 90% again. Its weakness is `gamma`: a small step is too slow when feedback arrives N bars
late, and a large one chases noise.

AgACI runs twelve correctors at once, with `GAMMAS` from 0.0005 to 0.1, and combines their quotes by
**Bernstein Online Aggregation**. Each corrector is weighted by the pinball loss it would have
scored at its own level. P10 and P90 are aggregated separately; P50 is the median of the
correctors. There is no step to choose. Feedback arrives N bars late, exactly as it would to anyone
quoting it live, so nothing here sees the future.

AgACI needs a run-in. Over its first few hundred outcomes the fast correctors swing, the weights
have not yet learned to discount them, and a quoted P10 wandered between the 2nd and 30th
percentile on random walks. So until it has learned from `WARM` outcomes, the envelope quotes from
the single corrector it used before (`STEADY_GAMMA`, whose state an existing series keeps across
the change), while AgACI learns from its own aggregate beside it.

The run-in need not be waited out live. `Book.teach` replays stored bars walk-forward - each quote
settled only by bars after it, in the same volatility unit the engine uses - through a fresh
envelope, and hands the correction state it learned to any envelope that has learned less.

Measured in `research/harness/envelope.py` on the last 40% of two years of 15m and 1h bars: the
empirical envelope under one-step ACI held 10.0% / 50.0% / 90.0% at 5 and 10 bars, where a plain
Gaussian band read 7% / 49% / 93%. It slipped to 87.8% at 50 bars.

`research/docs/conformal.md` compared the correctors on 15m bars at 5, 20 and 50 bars, across FX,
metals, crypto and Deriv. At 50 bars AgACI held 89.1-89.6% in every family, against 87.8-88.1% for
one-step ACI. It was also 2-9% narrower and had better pinball loss in every cell. A
quantile-boosted model gives coverage that is flat across volatility regimes, which neither
corrector does; it needs offline training and is the next step, not this one.

## Deriv's published laws

On Deriv's Volatility, Jump and Step indices the forward law is published, and
`research/docs/deriv-variants.md` measured the feed matching it:
- Volatility realises 0.992-1.010 of its named sigma, with Gaussian kurtosis;
- Jump realises 0.987-1.014 of 1.32 x its name;
- Step reproduces its +-0.1 coin.

Quoting that law beat this module's empirical, AgACI-corrected envelope:
- pinball 3-7% lower and the band 3-7% narrower at 20-50 bars;
- coverage flat by regime (90/90 against 88/92);
- calibrated from the first bar, where the empirical envelope needs its history.

The reason is that the empirical envelope measures moves in a noisy live volatility estimate, on a
process whose volatility is constant.

So on those indices the envelope quotes the law (`law_quantile`):
- **Volatility:** GBM at the named sigma with the Ito drift (`projection.py`).
- **Jump:** Gaussian at 1.32 x its name.
- **Step:** a fair +-0.1 coin each second, in price.

It uses no history and no corrector; AgACI on top of the law measured worse, because there is
nothing to correct. Outcomes are still settled, so the realised cover on the card stays honest.

## The boosted envelope, FX at 15m

`research/docs/gbm-envelope.md`: quantile boosting on volatility state, recent moves, range and
the hour, refit every 14 days and read through AgACI, beat the empirical envelope on pinball
everywhere. On FX it did so by 3.4 / 4.2 / 6.6% at N = 5 / 20 / 50, 2-3 points more than on our
memoryless walks, and with coverage flat by regime (FX N = 50 P90 84.5/89.7/93.8 ->
88.9/88.7/89.3). Elsewhere the gain was the walks' mechanical one, so it ships for FX 15m only.

There, the base quantile function is the frozen model's quantiles at this bar (`MODEL_LEVELS`,
interpolated, flat beyond the ends, sorted so they never cross) in place of the resolved history's.
AgACI's correctors read it exactly as they read the history, so the correction, the settling and
the realised cover are unchanged. The features are `learning/touches.py`'s, computed once per bar.
Without a usable model - missing, a different recipe, the series still cold - the envelope quotes
from its history as before. When the base changes, AgACI's state learned on the old one is dropped
and relearned, since a corrector tuned to one base is wrong on another.

## What it does not do

**P50 is not a direction call.** Its sign carried AUC 0.50-0.55 in the same study, and similar
readings have never paid their costs here. The envelope is published and journalled; nothing sizes,
enters or exits on it until the record says it should.
"""

from __future__ import annotations

import math
import os
import re
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from statistics import NormalDist

from till_platform.state import Restorable

from . import projection as pj
from .ranges import Ranges

#: Resolved N-bar moves kept per series and horizon. The study used 2,000; 1,000 keeps the state
#: file small (see research/docs/starving.md) and moves the quantiles by well under their own
#: sampling error at the tails quoted.
WINDOW = 1000

#: Below this many resolved moves the history is not trusted and the normal fallback is quoted.
MIN_HISTORY = 200

#: AgACI's correctors: twelve ACI steps, geometrically spaced from 0.0005 to 0.1, as in
#: research/harness/conformal.py. The aggregation decides which of them to trust.
GAMMAS: tuple[float, ...] = tuple(0.0005 * (0.1 / 0.0005) ** (k / 11) for k in range(12))

#: A corrector's level is kept inside this range, so it always reads a real quantile.
FLOOR, CEILING = 0.002, 0.998

#: The single corrector quoted while AgACI learns: the step the envelope shipped with.
STEADY_GAMMA = 0.005

#: Outcomes AgACI learns from before its aggregate is quoted. By 1,000 its levels had settled on
#: random walks (0.10 / 0.50 / 0.90 +- 0.02); at 400 they had not.
WARM = 1000

#: The percentiles quoted.
TARGETS: tuple[float, ...] = (0.1, 0.5, 0.9)

#: Horizons, in bars of the series' own timeframe. 50 is where AgACI earns its place: one-step ACI
#: held P90 only 87.8-88.1% there, AgACI 89.1-89.6% (research/docs/conformal.md); at 5 and 20 the
#: two are within a few tenths of a point.
HORIZONS: tuple[int, ...] = (5, 20, 50)
assert max(HORIZONS) < 64, "`Envelope.pending` holds at most 64 quotes"

#: A random walk's N-bar standard deviation is about sqrt(N) / 1.25 in units of an EWMA of true
#: range, which runs about 1.25 times a bar's standard deviation. The cold fallback's scale.
TR_TO_SD = 1.25


#: Step Index: one fair +-0.1 move a second, in price (`research/docs/generators.md`).
STEP_SIZE, STEP_EVERY_S = 0.1, 1.0


#: The boosted envelope (`research/docs/gbm-envelope.md`): 15m, one model file per
#: **family and horizon**, each holding one quantile regressor per level, read
#: through `shared/frozen.py`.
MODEL_INTERVAL = "15m"

#: Families that may have a boosted envelope, as `vol/clock.family` names them.
#:
#: **It was FX alone until 2026-10-07**, and that is why `conformal.md` could
#: measure a metals model covering 78.1% where it quoted 90% and nothing in the
#: pipeline would ever have caught it: metals was not in the contest. One model
#: per family rather than one over all of them, because a family is a different
#: process - the whole finding of `deriv-variants.md` is that an index with a
#: published law is quoted better by the law than by anything learned from a
#: pooled history.
#:
#: A family with no file yet simply has no model: `frozen.load` returns None,
#: `model_quantiles` returns None, and the history envelope quotes as it always
#: did. The miss is cached for `frozen.RECHECK`, so an untrained family does not
#: read the disk on every bar.
MODEL_FAMILIES: tuple[str, ...] = ("fx", "metals", "crypto")
MODELS: dict[tuple[str, int], str] = {
    (fam, n): f"envelope_{fam}15m_{n}" for fam in MODEL_FAMILIES for n in HORIZONS
}
MODEL_LEVELS: tuple[float, ...] = (0.05, 0.1, 0.5, 0.9, 0.95)
#: **`body` and `displaced` added 2026-10-08.** Asked for directly - put the
#: 70%-body candle and the two-candle displacement into the volatility models -
#: and the measurement behind it is `research/docs/zscore-window.md`: on 220,301
#: 4h bars a 70% body roughly **tripled** the separation of a z-score threshold
#: at every window, and the ordering held everywhere - plain bars, then 70%
#: body, then a 1-ATR displacement, then both. A feature worth more than the
#: statistic it was meant to support belongs in the model that forecasts size.
#:
#: Both come from `touches.base` and carry the zone rule's own numbers, so the
#: two subsystems mean the same thing by the same word.
#: **The forward readings joined on 2026-10-08 too.** `ensemble_bps`,
#: `forecast_bps`, `garch_bps` and `vol_stretch` were computed on every bar and
#: read by nothing - one comment each in `till_infinity/trading/` and no gate
#: anywhere - while `activity`, the field that beat a same-duty-cycle random
#: control at p = 0.001, had no reference at all. They are offered to the model
#: rather than wired into a gate, because a feature that does not help fails
#: `vs_champion` in the retrain contest and never ships, which is the safer way
#: to use a reading nobody has traded on yet.
#:
#: `sigma_movz` is the construction `transforms.py` found strongest of all - a
#: level against its own ten-bar spread, 58.3% against a random 50.3% at
#: p = 0.0005, ahead of the raw level. A standard deviation alone said nothing
#: (p = 0.844); it earns its place as a denominator and not as a feature.
MODEL_NAMES: tuple[str, ...] = (
    "lvol",
    "r1",
    "r5",
    "r20",
    "rng",
    "hour",
    "body",
    "displaced",
    "efficiency",
    "sigma_movz",
    "ens_ratio",
    "fc_ratio",
    "garch_ratio",
    "vol_stretch",
    "activity",
)
#: What changing the meaning of an input requires bumping.
#: **Bumped with the feature set, and that is the point of it.** `frozen.load`
#: checks this string and `MODEL_NAMES` against a spec before using it, so a
#: shipped six-feature model is *refused* rather than fed eight inputs - the
#: engine falls back to the history envelope until a retrained model arrives.
#: That is the safe failure and it is deliberate, but it means this change and a
#: retrain have to land together.
MODEL_RECIPE = (
    "2026-10-09 envelope: vol state, moves, range, hour, body, displacement, "
    "efficiency, forward readings, movz, activity (touches.base)"
)
#: Newest first. A model trained on an earlier recipe still loads, and is fed
#: the features *it* declares - so adding `body` and `displaced` does not strand
#: the three FX models already in service while they wait to be retrained.
MODEL_RECIPES: tuple[str, ...] = (
    MODEL_RECIPE,
    "2026-10-08b envelope: vol state, moves, range, hour, body, displacement, "
    "efficiency, forward readings, movz (touches.base)",
    "2026-10-08 envelope: vol state, moves, range, hour, body, displacement, "
    "forward readings, movz (touches.base)",
    "2026-09-29 envelope: vol state, moves, range, hour (touches.base)",
)


def model_family(feed: str) -> str | None:
    """The boosted envelope's family for a feed, or None if it has none.

    `clock.family` is the classifier the rest of `vol` already uses, so a feed
    cannot be one family here and another there.
    """
    from .clock import family

    fam = family(feed)
    return fam if fam in MODEL_FAMILIES else None


def model_applies(feed: str, interval: str) -> bool:
    """Whether a series is one a boosted envelope could be trained for: a feed in
    a known family, at 15m. Whether a model has actually been trained for it is
    `model_quantiles`' question, not this one."""
    return interval == MODEL_INTERVAL and model_family(feed) is not None


def model_quantiles(
    horizon: int,
    features: Mapping[str, float] | None,
    spec: dict | None = None,
    *,
    family: str = "fx",
) -> list[float] | None:
    """The boosted model's quantiles of the next `horizon` bars' move, in volatility units, at
    `MODEL_LEVELS`; None without features or a usable model. `spec` overrides the shipped one
    (the trainer scores a challenger with it), in which case `family` is not read."""
    if not features:
        return None
    if spec is None:
        if (family, horizon) not in MODELS:
            return None
        from till_platform import frozen

        spec = frozen.load(MODELS[(family, horizon)], recipe=MODEL_RECIPES, names=MODEL_NAMES)
        if spec is None:
            return None
    from till_platform.frozen import Quantiles

    # **The spec's own names, in the spec's order.** A model is fed what it was
    # trained on, not what this module currently believes the recipe to be -
    # otherwise adding a feature silently feeds every shipped model the wrong
    # vector, or `frozen.load` has to reject them all to prevent it.
    wanted = tuple(spec.get("names") or MODEL_NAMES)
    if any(name not in features for name in wanted):
        return None
    got = Quantiles(spec).predict([float(features[name]) for name in wanted])
    return got if all(math.isfinite(v) for v in got) else None


def _interpolate(level: float, quantiles: Sequence[float]) -> float:
    """The quantile at `level`, linear between `MODEL_LEVELS` and flat beyond them (np.interp)."""
    return _between(MODEL_LEVELS, quantiles, level)


def _between(levels: Sequence[float], quantiles: Sequence[float], level: float) -> float:
    """The quantile at `level`, linear between `levels` and flat beyond them (np.interp)."""
    if level <= levels[0]:
        return quantiles[0]
    if level >= levels[-1]:
        return quantiles[-1]
    for k in range(1, len(levels)):
        if level <= levels[k]:
            lo, hi = levels[k - 1], levels[k]
            w = (level - lo) / (hi - lo)
            return quantiles[k - 1] + w * (quantiles[k] - quantiles[k - 1])
    return quantiles[-1]


def _canonical(feed: str) -> str:
    """`Volatility 75 (1s) Index` -> `volatility_75_1s_index`, the form the published names take."""
    return "_".join(re.findall(r"[a-z0-9]+", feed.lower()))


def law_quantile(feed: str, seconds: float, level: float, price: float) -> float | None:
    """The published law's `level` quantile of `log(S_T / S_0)` over `seconds`, or None where
    no law is published (every real market, Boom, Crash and the rest)."""
    if seconds <= 0 or price <= 0:
        return None
    name = _canonical(feed)
    z = _normal_quantile(level)
    sigma = pj.sigma_for(name, seconds)
    if sigma is not None:
        return pj.drift_for(name, seconds, "ito") + sigma * z
    if name == "step_index":
        move = STEP_SIZE * math.sqrt(seconds / STEP_EVERY_S) * z
        return math.log1p(move / price) if move > -price else None
    return None


def has_law(feed: str) -> bool:
    """Whether the envelope quotes a published law for this feed."""
    return law_quantile(feed, 60.0, 0.9, 1.0) is not None


# ------------------------------------------------------------------ Deriv's own laws

#: The mechanics-only Deriv families (`research/docs/deriv-variants.md`): they publish how they
#: move but no volatility, and their feeds are memoryless, so the N-bar move is the N-fold
#: convolution of the one-bar move - fitted on history (`models/deriv_law_train.py`) and shipped
#: as a table in `models/deriv_law.json`, so a newly followed index is calibrated from bar zero.
#: It beat the empirical envelope by 3-7% pinball at 20-50 bars; AgACI on top made it worse.
OWN_LAW_FAMILIES: tuple[str, ...] = ("boom_", "crash_", "dex_", "range_break_", "drift_switch_")
LAW_MODEL = "deriv_law"
LAW_RECIPE = "2026-09-30 deriv own law: n-fold convolution of the one-bar log return"
#: The quantile levels each table holds, of `log(S_{t+n} / S_t)`.
LAW_LEVELS: tuple[float, ...] = (0.02, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.98)
LAW_NAMES: tuple[str, ...] = tuple(f"q{level:g}" for level in LAW_LEVELS)


def own_law_family(feed: str) -> bool:
    """Whether a feed is a mechanics-only Deriv index (and has no published law)."""
    name = _canonical(feed)
    return name.startswith(OWN_LAW_FAMILIES) and not has_law(name)


def table_quantile(table: Sequence[float], level: float) -> float:
    """A table's quantile at `level`, linear between `LAW_LEVELS` and flat beyond."""
    return _between(LAW_LEVELS, table, level)


def own_law(feed: str, interval: str, horizon: int) -> list[float] | None:
    """This index's own-law table for the next `horizon` bars of `interval`, or None."""
    if not own_law_family(feed):
        return None
    try:
        from till_platform import frozen

        spec = frozen.load(LAW_MODEL, recipe=LAW_RECIPE, names=LAW_NAMES)
    except Exception:  # a published extra must never stop a bar
        return None
    if not spec:
        return None
    got = spec.get("tables", {}).get(f"{_canonical(feed)}|{interval}|{horizon}")
    return got if got and len(got) == len(LAW_LEVELS) else None


def _normal_quantile(p: float) -> float:
    """Inverse standard normal, for the cold fallback."""
    return NormalDist().inv_cdf(min(max(p, 1e-9), 1 - 1e-9))


@dataclass(slots=True)
class Envelope(Restorable):
    """One series, one horizon: the history of resolved moves, the levels being read, the record."""

    horizon: int = 5
    #: The series, so a feed with a published law can be quoted from it (`law_quantile`).
    feed: str = ""
    #: The bar's length in seconds; the law's horizon is `horizon` of them.
    bar_seconds: float = 0.0
    #: What the quantiles are read from: "" the resolved history, else the boosted model's recipe.
    #: AgACI's state belongs to one base; a change of base relearns it.
    base: str = ""
    #: Resolved N-bar moves, in volatility units.
    history: deque = field(default_factory=lambda: deque(maxlen=WINDOW))
    #: Quotes waiting for their outcome: (close and sigma when quoted, published z per target,
    #: each corrector's z per target, AgACI's aggregate z per target). Bounded, like every persisted
    #: deque, so `restore_deque` gives it back as one; at most `horizon` quotes ever wait.
    pending: deque = field(default_factory=lambda: deque(maxlen=64))
    #: The single corrector's level per target - quoted while AgACI learns. The field the envelope
    #: shipped with, so a restored series keeps it.
    levels: list[float] = field(default_factory=lambda: list(TARGETS))
    #: Outcomes AgACI has learned from.
    learned: float = 0.0
    #: Per target, the level each corrector reads off the history - one per step in `GAMMAS`.
    experts: list[list[float]] = field(default_factory=lambda: [[t] * len(GAMMAS) for t in TARGETS])
    #: Per target and corrector, the aggregation's cumulative linearised regret and its square.
    regret: list[list[float]] = field(
        default_factory=lambda: [[0.0] * len(GAMMAS) for _ in TARGETS]
    )
    regret_sq: list[list[float]] = field(
        default_factory=lambda: [[0.0] * len(GAMMAS) for _ in TARGETS]
    )
    #: How many resolved quotes fell below each target's quantile, and how many resolved.
    hits: list[float] = field(default_factory=lambda: [0.0] * len(TARGETS))
    resolved: float = 0.0
    #: The latest quote, in volatility units, per target.
    quote: list[float] = field(default_factory=lambda: [0.0] * len(TARGETS))
    sigma: float = 0.0

    def observe(
        self,
        close: float,
        sigma: float,
        model: Sequence[float] | None = None,
        *,
        record: bool = True,
    ) -> None:
        """One closed bar: settle the quote made `horizon` bars ago, then quote the next N bars.

        `sigma` is the volatility unit as a log-return (bps / 10,000). `model` is the boosted
        model's quantiles at `MODEL_LEVELS` for this bar, where there is one: they replace the
        history as the base AgACI reads. `record=False` keeps the bar's place in the queue without
        quoting it, so nothing is learned from its outcome: a Mondrian bucket's envelope sees
        every bar but learns only from the quotes made in its bucket.
        """
        if close <= 0 or not (sigma > 0) or not math.isfinite(sigma):
            return
        if len(self.pending) >= self.horizon:
            settled = self.pending.popleft()
            then, unit, quoted = settled[0], settled[1], settled[2]
            y = math.log(close / then) / unit if quoted is not None else float("nan")
            if math.isfinite(y):
                self.history.append(y)
                self.resolved += 1
                for i, target in enumerate(TARGETS):
                    hit = 1.0 if y <= quoted[i] else 0.0
                    self.hits[i] += hit
                    steady = self.levels[i] + STEADY_GAMMA * (target - hit)
                    self.levels[i] = min(max(steady, FLOOR), CEILING)
                    # A quote made before AgACI carries no correctors' quotes: AgACI learns
                    # nothing from it.
                    if len(settled) > 4:
                        self._learn(i, target, y, settled[4][i], settled[3][i])
                if len(settled) > 4:
                    self.learned += 1
        if not record:
            self.pending.append((close, sigma, None))
            return
        if self._quote_law(close, sigma):
            return
        self._rebase(MODEL_RECIPE if model else "")
        ordered = (
            None if model else sorted(self.history) if len(self.history) >= MIN_HISTORY else None
        )
        each = [
            [self._quantile(level, ordered, model) for level in self.experts[i]]
            for i in range(len(TARGETS))
        ]
        agg = [self._aggregate(i, target, each[i]) for i, target in enumerate(TARGETS)]
        if self.learned >= WARM:
            self.quote = agg
        else:
            self.quote = [self._quantile(level, ordered, model) for level in self.levels]
        self.sigma = sigma
        self.pending.append((close, sigma, list(self.quote), each, agg))

    def _rebase(self, base: str) -> None:
        """Switch what the quantiles are read from, dropping AgACI's state learned on the old base.

        The waiting quotes still settle and count towards coverage; AgACI learns nothing from
        them, as after `adopt`."""
        if base == self.base:
            return
        self.base = base
        self.levels = list(TARGETS)
        self.learned = 0.0
        self.experts = [[t] * len(GAMMAS) for t in TARGETS]
        self.regret = [[0.0] * len(GAMMAS) for _ in TARGETS]
        self.regret_sq = [[0.0] * len(GAMMAS) for _ in TARGETS]
        self.pending = deque(((q[0], q[1], q[2]) for q in self.pending), maxlen=64)

    def _quote_law(self, close: float, sigma: float) -> bool:
        """Quote the published law, where there is one. Returns whether it did.

        In volatility units like every other quote, so `prices` and the settling need no change.
        The quote goes out without correctors' quotes, so AgACI learns nothing from it.
        """
        seconds = self.horizon * self.bar_seconds
        law = [law_quantile(self.feed, seconds, t, close) for t in TARGETS]
        if any(q is None for q in law):
            table = own_law(self.feed, _interval_of(self.bar_seconds), self.horizon)
            if table is None:
                return False
            law = [table_quantile(table, t) for t in TARGETS]
        self.quote = [q / sigma for q in law]
        self.sigma = sigma
        self.pending.append((close, sigma, list(self.quote)))
        return True

    @property
    def lawful(self) -> bool:
        """Whether this envelope quotes a law: Deriv's published one, or the index's own table."""
        return self.bar_seconds > 0 and (has_law(self.feed) or self.own_lawful)

    @property
    def own_lawful(self) -> bool:
        """Whether this envelope quotes the index's own convolved law (`own_law`)."""
        return (
            self.bar_seconds > 0
            and own_law(self.feed, _interval_of(self.bar_seconds), self.horizon) is not None
        )

    def _learn(self, i: int, target: float, y: float, quoted: float, each: list[float]) -> None:
        """One resolved outcome: step every corrector, and charge each its share of the pinball
        loss against the aggregate it fed (BOA's linearised regret). `quoted` is AgACI's own
        aggregate, whether or not it was the one published."""
        experts, regret, regret_sq = self.experts[i], self.regret[i], self.regret_sq[i]
        grad = (1.0 if y <= quoted else 0.0) - target
        for k, gamma in enumerate(GAMMAS):
            hit = 1.0 if y <= each[k] else 0.0
            experts[k] = min(max(experts[k] + gamma * (target - hit), FLOOR), CEILING)
            loss = grad * (each[k] - quoted)
            regret[k] += loss
            regret_sq[k] += loss * loss

    def _weights(self, i: int) -> list[float]:
        """Bernstein Online Aggregation's weights, each corrector with its own learning rate."""
        log_k = math.log(len(GAMMAS))
        logw = []
        for r, r2 in zip(self.regret[i], self.regret_sq[i], strict=True):
            eta = min(0.5, math.sqrt(log_k / (1.0 + r2)))
            logw.append(-eta * r - eta * eta * r2)
        top = max(logw)
        w = [math.exp(v - top) for v in logw]
        total = sum(w)
        return [v / total for v in w]

    def _aggregate(self, i: int, target: float, each: list[float]) -> float:
        """P10 and P90 by BOA's weights; P50 as the correctors' median, as in the study."""
        if target == 0.5:
            ordered = sorted(each)
            mid = len(ordered) // 2
            return (ordered[mid - 1] + ordered[mid]) / 2 if len(ordered) % 2 == 0 else ordered[mid]
        return sum(w * q for w, q in zip(self._weights(i), each, strict=True))

    @property
    def agaci_levels(self) -> list[float]:
        """The level AgACI effectively reads each target at: P10 and P90 its correctors' levels
        weighted, P50 their median."""
        out = []
        for i, target in enumerate(TARGETS):
            if target == 0.5:
                out.append(self._aggregate(i, target, self.experts[i]))
            else:
                out.append(
                    sum(w * a for w, a in zip(self._weights(i), self.experts[i], strict=True))
                )
        return out

    def adopt(self, taught: Envelope) -> None:
        """Take AgACI's correction state from an envelope that learned it from stored history.

        Replaced, not added to: the history it was learned from is the same past this envelope has
        been seeing, so adding would count those outcomes twice. The quotes still waiting were made
        by the correctors being replaced, so AgACI learns nothing from them; they still settle and
        still count towards coverage.
        """
        self.experts = [list(row) for row in taught.experts]
        self.regret = [list(row) for row in taught.regret]
        self.regret_sq = [list(row) for row in taught.regret_sq]
        self.learned = taught.learned
        self.levels = list(taught.levels)
        self.base = taught.base
        self.pending = deque(((q[0], q[1], q[2]) for q in self.pending), maxlen=64)

    @property
    def aggregated(self) -> bool:
        """Whether the quote is AgACI's, rather than the single corrector's while it learns."""
        return self.learned >= WARM

    def _quantile(
        self, level: float, ordered: list[float] | None, model: Sequence[float] | None = None
    ) -> float:
        if model:
            return _interpolate(level, model)
        if ordered:
            return ordered[round(level * (len(ordered) - 1))]
        return _normal_quantile(level) * math.sqrt(self.horizon) / TR_TO_SD

    @property
    def warm(self) -> bool:
        """Quotable: a published law is from the first bar; the empirical envelope once it has
        `MIN_HISTORY` resolved moves."""
        return self.lawful or bool(self.base) or len(self.history) >= MIN_HISTORY

    def coverage(self) -> list[float]:
        """The realised share of outcomes below each target's quote, over everything resolved."""
        return [h / self.resolved if self.resolved else float("nan") for h in self.hits]

    def prices(self, price: float) -> dict[str, float]:
        """The current quote as prices around `price`, and the realised coverage behind it."""
        if not self.warm or price <= 0 or self.sigma <= 0:
            return {}
        out: dict[str, float] = {}
        n = self.horizon
        for target, z in zip(TARGETS, self.quote, strict=True):
            name = f"env{n}_p{round(target * 100):d}"
            out[name] = round(price * math.exp(z * self.sigma), 10)
        for target, cover in zip(TARGETS, self.coverage(), strict=True):
            out[f"env{n}_cover_p{round(target * 100):d}"] = round(cover, 4)
        out[f"env{n}_width_bps"] = round((self.quote[-1] - self.quote[0]) * self.sigma * 10_000, 3)
        if self.own_lawful:
            out[f"env{n}_ownlaw"] = 1.0
        elif self.lawful:
            out[f"env{n}_law"] = 1.0
        if self.base:
            out[f"env{n}_model"] = 1.0
        return out


@dataclass(slots=True)
class Published(Restorable):
    """The coverage of what was actually published for one series and horizon.

    Under Mondrian the published quote comes from a bucket's envelope or from the pooled one,
    bar by bar, so neither envelope's own record is the card's. This settles the published
    quotes themselves.
    """

    horizon: int = 5
    pending: deque = field(default_factory=lambda: deque(maxlen=64))
    hits: list[float] = field(default_factory=lambda: [0.0] * len(TARGETS))
    resolved: float = 0.0

    def observe(self, close: float, sigma: float, quote: Sequence[float] | None) -> None:
        if close <= 0 or not (sigma > 0):
            return
        if len(self.pending) >= self.horizon:
            then, unit, quoted = self.pending.popleft()
            if quoted is not None:
                y = math.log(close / then) / unit
                if math.isfinite(y):
                    self.resolved += 1
                    for i, q in enumerate(quoted):
                        self.hits[i] += 1.0 if y <= q else 0.0
        self.pending.append((close, sigma, list(quote) if quote else None))

    def coverage(self) -> list[float]:
        return [h / self.resolved if self.resolved else float("nan") for h in self.hits]


#: Mondrian envelope by ZMA state (`research/docs/zma-conformal.md`): AgACI and history are kept
#: per stretched bucket (-1 down, 0 inside, +1 up), and a bucket's quote is published once it
#: has `MIN_HISTORY` resolved outcomes of its own; the pooled envelope's before that. It closed
#: 2-5 point coverage gaps in stretched states (FX N = 5 stretched-up P90 85.2% -> 89.9%) at equal
#: or better pinball. Not for a published law, which has nothing to correct.
#:
#: **Off by default.** It roughly triples each series' envelope state (about 65 KB to 189 KB across
#: the three horizons) for a gain of 1-2 coverage points in stretched states and at most 2% pinball,
#: on a 908 MB host whose container has been killed for memory before (docs/deployment.md). Turn it
#: on once the headroom is measured.
MONDRIAN = os.environ.get("STRUCTURES_ENVELOPE_MONDRIAN", "0") not in ("0", "false", "no")
BUCKETS: tuple[int, ...] = (-1, 0, 1)


@dataclass(slots=True)
class Book(Restorable):
    """Every series' envelopes, per (feed, interval) and horizon."""

    envelopes: dict[str, Envelope] = field(default_factory=dict)
    #: "feed|interval|n|bucket" -> that ZMA bucket's envelope (`MONDRIAN`).
    mondrian: dict[str, Envelope] = field(default_factory=dict)
    #: "feed|interval|n" -> the bucket whose envelope is published now; absent means pooled.
    chosen: dict[str, int] = field(default_factory=dict)
    #: "feed|interval|n" -> the published quotes' own coverage.
    published: dict[str, Published] = field(default_factory=dict)

    def observe(
        self,
        feed: str,
        interval: str,
        close: float,
        sigma: float,
        features: Mapping[str, float] | None = None,
        *,
        bucket: int | None = None,
        scale: Mapping[int, float] | None = None,
    ) -> None:
        """One closed bar for every horizon's envelope. `features` are the bar's `touches.base`
        where the boosted envelope applies (FX 15m); without them, or a usable model, the history
        is the base. `bucket` is the series' ZMA stretched state at this close, which keys the
        Mondrian envelopes; `scale` is the hour-of-week multiplier of the unit per horizon
        (`clock.py`), applied only where the history is the base."""
        seconds = _bar_seconds(interval)
        fam = model_family(feed)
        boosted = features is not None and interval == MODEL_INTERVAL and fam is not None
        for n in HORIZONS:
            key = f"{feed}|{interval}|{n}"
            found = self.envelopes.get(key)
            if found is None:
                found = self.envelopes[key] = Envelope(horizon=n)
            if found.feed != feed or found.bar_seconds != seconds:
                # Also fills an envelope restored from a state saved before it knew its series.
                found.feed, found.bar_seconds = feed, seconds
            model = _safe_quantiles(n, features, fam) if boosted else None
            lawful = found.lawful
            unit = sigma
            if scale and not model and not lawful:
                m = scale.get(n, 1.0)
                if m > 0 and math.isfinite(m):
                    unit = sigma * m
            found.observe(close, unit, model)
            use = found
            if MONDRIAN and bucket in BUCKETS and not lawful:
                for b in BUCKETS:
                    mk = f"{key}|{b}"
                    mb = self.mondrian.get(mk)
                    if mb is None:
                        mb = self.mondrian[mk] = Envelope(horizon=n, feed=feed, bar_seconds=seconds)
                    mb.observe(close, unit, model, record=b == bucket)
                mine = self.mondrian[f"{key}|{bucket}"]
                if mine.resolved >= MIN_HISTORY and mine.warm:
                    use = mine
            if use is found:
                self.chosen.pop(key, None)
            else:
                self.chosen[key] = int(bucket)  # type: ignore[arg-type]
            tracker = self.published.get(key)
            if tracker is None:
                tracker = self.published[key] = Published(horizon=n)
            tracker.observe(close, unit, use.quote if use.warm else None)

    def reading(self, feed: str, interval: str, price: float) -> dict[str, float]:
        """Every horizon's quote for this series, as published features. Absent while cold."""
        out: dict[str, float] = {}
        for n in HORIZONS:
            key = f"{feed}|{interval}|{n}"
            found = self.envelopes.get(key)
            if found is None:
                continue
            b = self.chosen.get(key)
            source = self.mondrian.get(f"{key}|{b}") if b is not None else None
            got = (source or found).prices(price)
            tracker = self.published.get(key)
            if got and tracker is not None and tracker.resolved > 0:
                for target, cover in zip(TARGETS, tracker.coverage(), strict=True):
                    got[f"env{n}_cover_p{round(target * 100):d}"] = round(cover, 4)
            if got and source is not None:
                got[f"env{n}_zma"] = float(b)
            out.update(got)
        if out:
            out["env_ref"] = price  # what the percentages on a card are measured from
        return out

    def teach(self, feed: str, interval: str, bars: Sequence[tuple[float, ...]]) -> int:
        """Warm AgACI from stored bars, oldest first, as (open, high, low, close), or as
        (time, open, high, low, close) when the bar's open time is known.

        For each horizon whose envelope has learned from fewer than `WARM` outcomes, the bars are
        replayed walk-forward through a fresh envelope in the engine's own unit (the EWMA of true
        range), and its correction state is adopted if it learned more on the same base. Where the
        boosted envelope applies and the times are given, the replay reads the boosted model
        through the same features the engine computes, with the rollover's wick cut as the engine
        cuts it, so AgACI is taught on the base it will correct. Returns how many envelopes took it.
        """
        if has_law(feed) or any(own_law(feed, interval, n) for n in HORIZONS):
            return 0  # quoted from a law, which has nothing to learn
        timed = bool(bars) and len(bars[0]) == 5
        fam = model_family(feed)
        boosted = timed and interval == MODEL_INTERVAL and fam is not None
        seconds = _bar_seconds(interval)
        taught = 0
        for n in HORIZONS:
            key = f"{feed}|{interval}|{n}"
            found = self.envelopes.get(key)
            if found is not None and found.learned >= WARM:
                continue
            replay, ranges = Envelope(horizon=n), Ranges()
            state = None
            if boosted:
                from ..learning import touches

                state = touches.Touches()
            for bar in bars:
                when, open_, high, low, close = bar if timed else (0.0, *bar)
                if timed:
                    from .. import rollover as ro

                    high, low, close = ro.trimmed(
                        feed, when, when + seconds, open_, high, low, close
                    )
                ranges.observe(open_, high, low, close)
                bps = ranges.ewma_tr_bps
                if not (bps > 0 and close > 0):
                    continue
                model = None
                if state is not None and state.advance(
                    feed, interval, when, high, low, close, bps / 10_000
                ):
                    model = _safe_quantiles(n, state.base(feed, interval), fam)
                replay.observe(close, bps / 10_000, model)
            if found is None:
                found = self.envelopes[key] = Envelope(horizon=n)
            if replay.learned > found.learned:
                found.adopt(replay)
                taught += 1
        return taught

    def forget(self, keep: set[str]) -> int:
        """Drop envelopes for feeds no longer followed. Returns how many went."""
        gone = [k for k in self.envelopes if k.split("|", 1)[0] not in keep]
        for k in gone:
            del self.envelopes[k]
        for book in (self.mondrian, self.chosen, self.published):
            for k in [k for k in book if k.split("|", 1)[0] not in keep]:
                del book[k]
        return len(gone)


def _safe_quantiles(
    horizon: int, features: Mapping[str, float] | None, family: str | None
) -> list[float] | None:
    """`model_quantiles`, with any fault read as no model: the history is always there to fall
    back on, and a model must never stop the envelope."""
    if family is None:
        return None
    try:
        return model_quantiles(horizon, features, family=family)
    except Exception:
        return None


def _interval_of(seconds: float) -> str:
    """The interval name for a bar length, as `levels.SECONDS` names it; "" if none."""
    from ..levels import SECONDS

    for name, length in SECONDS.items():
        if length == seconds and name not in ("daily", "weekly"):
            return name
    return ""


def _bar_seconds(interval: str) -> float:
    """An interval's length. Imported late: `levels` imports this package's volatility module."""
    from ..levels import SECONDS

    return float(SECONDS.get(interval, 0.0))


def card_lines(got: Mapping, price: Callable[[float], str]) -> list[str]:
    """The next-5- and next-50-bars envelope and the volatility state, as card lines. Read only.

    Shared by the level alert (`structures/service.py`) and the trade fill card (`trading`), which
    carries the signal's features on `Intent.features`, so both print the same numbers the same
    way. `price` formats a price for the card it is going on. The realised P90 cover is printed
    beside the quote, because a percentile is only worth what it has been hitting. P50 is not a
    direction call. Nothing is printed while the envelope is cold.
    """
    ref, p10, p50, p90 = (got.get(k) for k in ("env_ref", "env5_p10", "env5_p50", "env5_p90"))
    if not (ref and p10 and p50 and p90):
        return []

    def leg(value: float) -> str:
        return f"{price(value)} ({(value / ref - 1) * 100:+.2f}%)"

    lines = [
        f"🎯 next 5 bars · ceiling P90 {leg(p90)} · median P50 {leg(p50)} · floor P10 {leg(p10)}",
    ]
    if got.get("env5_law"):
        lines[0] += " · Deriv's published law"
    elif got.get("env5_ownlaw"):
        lines[0] += " · the index's own law"
    elif got.get("env5_model"):
        lines[0] += " · boosted"
    cover = got.get("env5_cover_p90")
    if isinstance(cover, int | float) and not math.isnan(cover):
        lines[0] += f" · P90 held {cover:.0%}"
    far10, far90 = got.get("env50_p10"), got.get("env50_p90")
    if far10 and far90:
        # The long horizon, where the corrector matters most - ceiling and floor only.
        lines.append(f"🔭 next 50 bars · ceiling P90 {leg(far90)} · floor P10 {leg(far10)}")
        far_cover = got.get("env50_cover_p90")
        if isinstance(far_cover, int | float) and not math.isnan(far_cover):
            lines[-1] += f" · P90 held {far_cover:.0%}"
    percentile = got.get("tr_percentile")
    if isinstance(percentile, int | float):
        # research/docs/fractal-twins.md: from the bottom fifth an expansion follows about three
        # times as often as the base rate; research/docs/anomalies.md has volatility state as the
        # strongest early warning of a shock. Neither says which way.
        if percentile <= 0.2:
            lines.append("⚖️ tight volatility compression · expansion watch, no side")
        elif percentile >= 0.8:
            lines.append("⚖️ volatility already expanded · wide bars, no side")
    # This hour's volatility against the average hour's, where the family has a clock.
    from . import clock

    lines += clock.card_line(dict(got))
    # The chance each band is touched on the way, where a model is trained for the series.
    from ..learning import touches

    lines += touches.card_line(got)
    return lines
