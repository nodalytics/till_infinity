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
moves that silently: the same number can start behaving like a P80. So each level is run through
**adaptive conformal inference** (Gibbs & Candes, 2021). The level actually read off the history,
`a`, moves after every resolved outcome by `a <- a + GAMMA * (target - hit)`, where `hit` is whether
the outcome fell below the quantile that was quoted. A P90 being hit 80% of the time is read from
further up the tail until it covers 90% again. Feedback arrives N bars late, exactly as it would to
anyone quoting it live, so nothing here sees the future.

Measured in `research/harness/envelope.py` on the last 40% of two years of 15m and 1h bars (15
FX pairs, metals, crypto, and random walks as the control): the empirical envelope under this
correction held P10 / P50 / P90 at 10.0% / 50.0% / 90.0% with a spread of 0.0-0.3 points across
twenty slices of time, where a plain Gaussian band read 7% / 49% / 93%. A quantile-boosted model
scored slightly better (lower pinball loss, and flat coverage across volatility regimes); it needs
offline training and is the next step, not this one.

## What it does not do

**P50 is not a direction call.** Its sign carried AUC 0.50-0.55 in the same study, and similar
readings have never paid their costs here. The envelope is published and journalled; nothing sizes,
enters or exits on it until the record says it should.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from statistics import NormalDist

from ..state import Restorable

#: Resolved N-bar moves kept per series and horizon. The study used 2,000; 1,000 keeps the state
#: file small (see research/docs/starving.md) and moves the quantiles by well under their own
#: sampling error at the tails quoted.
WINDOW = 1000

#: Below this many resolved moves the history is not trusted and the normal fallback is quoted.
MIN_HISTORY = 200

#: The adaptive conformal step. At 0.005 a level that has drifted ten points takes a few hundred
#: resolutions to come back - fast enough to track a regime, slow enough not to chase noise. The
#: study's value.
GAMMA = 0.005

#: The percentiles quoted.
TARGETS: tuple[float, ...] = (0.1, 0.5, 0.9)

#: Horizons, in bars of the series' own timeframe.
HORIZONS: tuple[int, ...] = (5, 20)
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
    #: Quotes waiting for their outcome: (close and sigma when quoted, quoted z per target).
    #: Bounded, like every deque that is persisted, so `restore_deque` gives it back as one - and at
    #: most `horizon` quotes are ever waiting, so the bound never bites.
    pending: deque = field(default_factory=lambda: deque(maxlen=64))
    #: The level actually read for each target - the adaptive conformal state.
    levels: list[float] = field(default_factory=lambda: list(TARGETS))
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
            then, unit, quoted = self.pending.popleft()
            y = math.log(close / then) / unit
            if math.isfinite(y):
                self.history.append(y)
                self.resolved += 1
                for i, target in enumerate(TARGETS):
                    hit = 1.0 if y <= quoted[i] else 0.0
                    self.hits[i] += hit
                    self.levels[i] = min(max(self.levels[i] + GAMMA * (target - hit), 0.002), 0.998)
        ordered = sorted(self.history) if len(self.history) >= MIN_HISTORY else None
        self.quote = [self._quantile(level, ordered) for level in self.levels]
        self.sigma = sigma
        self.pending.append((close, sigma, list(self.quote)))

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

    def forget(self, keep: set[str]) -> int:
        """Drop envelopes for feeds no longer followed. Returns how many went."""
        gone = [k for k in self.envelopes if k.split("|", 1)[0] not in keep]
        for k in gone:
            del self.envelopes[k]
        return len(gone)


def card_lines(got: Mapping, price: Callable[[float], str]) -> list[str]:
    """The next-5-bars envelope and the volatility state, as notification-card lines. Read only.

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
