"""How long a test has to be, answered per candidate rather than by rule.

Edge decays, and a faster loop is worth real money - so the window is a search
parameter from one month to twelve, not a fixed two years. What cannot be a
preference is whether a given window can support a verdict, and that has an
answer: `minimum_track_record` says how many returns are needed before PSR
could reach its target, given the Sharpe, skew and kurtosis actually observed.

So a short window is not refused for being short. It is refused when it cannot
hold enough *episodes* for this candidate's trade frequency - and the refusal
says what it would need, which is a different and much more useful answer than
"too short".

**Two consequences of searching windows, both of which the system now prices.**

Episodes, not bars, are the sample. One month of 1-minute bars is about 30,000
bars, and for a strategy that trades five times a week it is about twenty
episodes. `overlapping-outcome-windows-leak` is what happens when the two are
confused: a short skip rule under a long forward window gave direction AUC
0.79 that collapsed to 0.51, because one event had been counted as many.

**Sweeping twelve windows is twelve times the trials.** That is not a reason
not to - it is a reason to count them, because the deflated Sharpe deflates
against the number of candidates and a window sweep multiplies it. Searching
hard and reporting honestly are compatible; searching hard and reporting the
best window as though it were the only one is not.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

#: Windows the search may use, in months.
MONTHS: tuple[int, ...] = tuple(range(1, 13))

#: Trading days in a month, and the hours a retail FX week actually offers.
#: Used to turn a window into an episode budget rather than a bar count.
DAYS_PER_MONTH = 21.0


@dataclass(frozen=True, slots=True)
class Window:
    """A test period, and what it can and cannot settle."""

    months: int

    def __post_init__(self) -> None:
        if self.months not in MONTHS:
            raise ValueError(f"window must be 1 to 12 months, got {self.months}")

    @property
    def days(self) -> float:
        return self.months * DAYS_PER_MONTH

    def episodes(self, per_day: float, hold_minutes: float = 0.0) -> float:
        """Independent episodes this window holds, not raw event count.

        **Raw frequency is not sample size, and tick data is where the two
        come apart hardest.** A thousand quote revisions in a minute overlap
        almost completely: this desk measured `probability_up` at 0.6365 on
        overlapping touches and 0.5092 once de-overlapped, so the overlap was
        worth more than the whole apparent effect.

        `hold_minutes` is the decorrelation time - how long a position or a
        forward window lasts. Events arriving faster than that are not new
        episodes, so the count is capped at one per holding period. Zero means
        "already independent", which is a claim for the caller to make rather
        than one this function should assume.
        """
        raw = self.days * per_day
        if hold_minutes <= 0.0:
            return raw
        ceiling = self.days * (1440.0 / hold_minutes)
        return min(raw, ceiling)


def feasible(
    window: Window,
    per_day: float,
    *,
    minimum: int | None = None,
    hold_minutes: float = 0.0,
) -> tuple[bool, str]:
    """Can this window hold enough episodes for this candidate?

    `minimum` defaults to `promotion.MIN_EPISODES`. The answer names the
    frequency as well as the window, because the two are only meaningful
    together: one month settles a strategy trading fifty times a day and
    settles nothing for one trading weekly.
    """
    from .promotion import MIN_EPISODES

    need = MIN_EPISODES if minimum is None else minimum
    have = window.episodes(per_day, hold_minutes)
    raw = window.days * per_day
    capped = " (capped by overlap)" if have < raw else ""
    if have >= need:
        return True, (
            f"{window.months}mo at {per_day:g}/day gives {have:.0f} independent episodes{capped}"
        )
    effective = have / window.days if window.days else 0.0
    months = need / (effective * DAYS_PER_MONTH) if effective else 0.0
    tail = (
        f"about {months:.1f} months would"
        if months
        else "no window at this frequency and holding period will"
    )
    return False, (
        f"{window.months}mo at {per_day:g}/day gives {have:.0f} independent "
        f"episodes{capped}, under {need} - {tail}."
    )


def shortest(
    per_day: float, *, minimum: int | None = None, hold_minutes: float = 0.0
) -> Window | None:
    """The shortest window that can settle a candidate at this frequency.

    The question a fast loop actually wants: not "is a month enough" but "what
    is the least history that could answer this". `None` means no window up to
    twelve months can, which is a decision to make early and cheaply.
    """
    for months in MONTHS:
        window = Window(months)
        ok, _why = feasible(window, per_day, minimum=minimum, hold_minutes=hold_minutes)
        if ok:
            return window
    return None


def sweep(
    per_day: float, *, minimum: int | None = None, hold_minutes: float = 0.0
) -> tuple[Window, ...]:
    """Every window that could settle this candidate.

    **Each one is a trial.** Pass the length of this tuple into the trial count
    so the deflation sees the sweep: twelve windows searched and the best
    reported is twelve trials, not one.
    """
    return tuple(
        Window(m)
        for m in MONTHS
        if feasible(Window(m), per_day, minimum=minimum, hold_minutes=hold_minutes)[0]
    )


def required_sharpe(window: Window, per_day: float, kurtosis: float = 20.0) -> float:
    """Roughly the per-period Sharpe needed for PSR 0.95 over this window.

    Inverts the PSR expression at zero skew, which is close enough to size a
    window before running anything. The kurtosis default is 20 rather than a
    Gaussian 3 because that is the low end of what this desk measures on
    traded markets - using 3 here would quietly halve the bar.
    """
    from .metrics import phi_inverse

    n = max(2.0, window.episodes(per_day))
    z = phi_inverse(0.95)
    # PSR = Phi( SR * sqrt(n-1) / sqrt(1 + (g4-1)/4 * SR^2) ), skew zero.
    # Solving for SR with a = (g4-1)/4:
    a = (kurtosis - 1.0) / 4.0
    denom = (n - 1.0) - a * z * z
    if denom <= 0.0:
        return float("inf")
    return z / denom**0.5


def budget(per_day: float, candidates: int) -> str:
    """One line on what a sweep costs, before it is run.

    Stated up front because the cost is the thing that gets forgotten: a
    sweep's trial count is its windows times its candidates, and the deflated
    Sharpe charges for all of it.
    """
    windows = sweep(per_day)
    trials = len(windows) * max(1, candidates)
    if not windows:
        return (
            f"no window up to 12 months settles {per_day:g} trades/day - this candidate "
            f"is unmeasurable on this frequency, which is cheaper to know now"
        )
    shortest_window = windows[0]
    return (
        f"{len(windows)} usable windows ({shortest_window.months}-{windows[-1].months}mo) "
        f"x {candidates} candidates = {trials} trials; the shortest needs a per-period "
        f"Sharpe near {required_sharpe(shortest_window, per_day):.3f}"
    )


__all__ = [
    "DAYS_PER_MONTH",
    "MONTHS",
    "Sequence",
    "Window",
    "budget",
    "feasible",
    "required_sharpe",
    "shortest",
    "sweep",
]
