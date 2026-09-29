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

## What it does not do

**P50 is not a direction call.** Its sign carried AUC 0.50-0.55 in the same study, and similar
readings have never paid their costs here. The envelope is published and journalled; nothing sizes,
enters or exits on it until the record says it should.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from statistics import NormalDist

from ..state import Restorable
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


def _normal_quantile(p: float) -> float:
    """Inverse standard normal, for the cold fallback."""
    return NormalDist().inv_cdf(min(max(p, 1e-9), 1 - 1e-9))


@dataclass(slots=True)
class Envelope(Restorable):
    """One series, one horizon: the history of resolved moves, the levels being read, the record."""

    horizon: int = 5
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

    def observe(self, close: float, sigma: float) -> None:
        """One closed bar: settle the quote made `horizon` bars ago, then quote the next N bars.

        `sigma` is the volatility unit as a log-return (bps / 10,000).
        """
        if close <= 0 or not (sigma > 0) or not math.isfinite(sigma):
            return
        if len(self.pending) >= self.horizon:
            settled = self.pending.popleft()
            then, unit, quoted = settled[0], settled[1], settled[2]
            y = math.log(close / then) / unit
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
        ordered = sorted(self.history) if len(self.history) >= MIN_HISTORY else None
        each = [
            [self._quantile(level, ordered) for level in self.experts[i]]
            for i in range(len(TARGETS))
        ]
        agg = [self._aggregate(i, target, each[i]) for i, target in enumerate(TARGETS)]
        if self.learned >= WARM:
            self.quote = agg
        else:
            self.quote = [self._quantile(level, ordered) for level in self.levels]
        self.sigma = sigma
        self.pending.append((close, sigma, list(self.quote), each, agg))

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
        self.pending = deque(((q[0], q[1], q[2]) for q in self.pending), maxlen=64)

    @property
    def aggregated(self) -> bool:
        """Whether the quote is AgACI's, rather than the single corrector's while it learns."""
        return self.learned >= WARM

    def _quantile(self, level: float, ordered: list[float] | None) -> float:
        if ordered:
            return ordered[round(level * (len(ordered) - 1))]
        return _normal_quantile(level) * math.sqrt(self.horizon) / TR_TO_SD

    @property
    def warm(self) -> bool:
        return len(self.history) >= MIN_HISTORY

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
        return out


@dataclass(slots=True)
class Book(Restorable):
    """Every series' envelopes, per (feed, interval) and horizon."""

    envelopes: dict[str, Envelope] = field(default_factory=dict)

    def observe(self, feed: str, interval: str, close: float, sigma: float) -> None:
        for n in HORIZONS:
            key = f"{feed}|{interval}|{n}"
            found = self.envelopes.get(key)
            if found is None:
                found = self.envelopes[key] = Envelope(horizon=n)
            found.observe(close, sigma)

    def reading(self, feed: str, interval: str, price: float) -> dict[str, float]:
        """Every horizon's quote for this series, as published features. Absent while cold."""
        out: dict[str, float] = {}
        for n in HORIZONS:
            found = self.envelopes.get(f"{feed}|{interval}|{n}")
            if found is not None:
                out.update(found.prices(price))
        if out:
            out["env_ref"] = price  # what the percentages on a card are measured from
        return out

    def teach(
        self, feed: str, interval: str, bars: Sequence[tuple[float, float, float, float]]
    ) -> int:
        """Warm AgACI from stored bars, oldest first, as (open, high, low, close).

        For each horizon whose envelope has learned from fewer than `WARM` outcomes, the bars are
        replayed walk-forward through a fresh envelope in the engine's own unit (the EWMA of true
        range), and its correction state is adopted if it learned more. Returns how many envelopes
        took it.
        """
        taught = 0
        for n in HORIZONS:
            key = f"{feed}|{interval}|{n}"
            found = self.envelopes.get(key)
            if found is not None and found.learned >= WARM:
                continue
            replay, ranges = Envelope(horizon=n), Ranges()
            for open_, high, low, close in bars:
                ranges.observe(open_, high, low, close)
                bps = ranges.ewma_tr_bps
                if bps > 0 and close > 0:
                    replay.observe(close, bps / 10_000)
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
        return len(gone)


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
    return lines
