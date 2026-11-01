"""The risk-shaped subset of the configuration, which this package can own.

`strategies/config.py` is 1,583 lines of `TRADING_*` knobs about what to
trade, on which terminal, with which decision, and `Settings` is the mutable
object the whole desk threads around. The gates in `guard.py` and the bundles
in `plans.py` need **twenty-two numbers** out of it, and needing them is what
sent `guard.py` back upstairs the first time it was placed here:
`tests/test_service_boundaries.py` records the attempt and the import that was
the symptom.

So this is the twenty-two numbers and nothing else. It arrives as an argument
- `Guard(envelope)`, `fx_window(envelope, ...)` - rather than being reached
for, and it is built by `Settings.envelope()`, which lives upstairs in
`strategies/config.py` so that the dependency points the way `LAYERS` allows.

## Two decisions in here are worth more than the fields

**There are no defaults, deliberately.** A default here would put every number
in two places - `Settings` and this file - with nothing to notice when they
diverged, which is the single failure mode this repository keeps writing down:
a path scoped in one file and moved in another, an environment variable a
restart keeps the old value of, a deployed container whose limits had drifted
from the file that claimed to set them. Without defaults there is exactly one
way to obtain an `Envelope`, and a field added here is a `TypeError` at the
projection until the projection names it.

**The number travels and the argument stays.** Each field below carries one
line saying what it does. The measurement that chose the value - the 47,676
touches behind `min_reward_to_risk`, the 15.4x spread at 21:00 UTC behind
`quiet_hours`, the 32-of-36 rows behind `release_in_hold` - stays on the field
in `strategies/config.py`. Copying the arguments into a second file is the
same mistake as copying the defaults, in prose rather than in numbers.

## What is **not** here, and why the absences are the shape

`max_risk_money`, `min_edge` and `max_hold` are set by a `Plan` and are not in
this object, because nothing in this package reads them: a plan's twelve
`CONTROLS` are fields of `Plan` itself, and `Settings` is where they land.
Nothing is here because a plan touches it; everything is here because a gate
or the readout reads it.

`risk_plan`, `risk_fraction` and `min_probability` are the three that are not
gates. They are here for `plans.describe_effective`, which is the one readout
somebody checks before trusting the limits, and which has to be able to print
the three quantities a plan exists to keep consistent - size per trade, the
daily stop, and how selective the entry is.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Envelope:
    """The limits in force, as the gates and the readout read them.

    Frozen because a gate that could be re-tuned mid-session is a gate whose
    refusals cannot be read back: the journal would record a reason computed
    against a number nobody can recover. The plan and the environment are
    resolved into `Settings` first, and this is the projection of the result.
    """

    # ------------------------------------------------- what the readout prints
    #: The named plan in force. See `plans`.
    risk_plan: str
    #: Fraction of equity risked per trade.
    risk_fraction: float
    #: The signal's own confidence floor. Not read by any gate here - it is in
    #: this object so the readout can print the selectivity a plan chose.
    min_probability: float

    # --------------------------------------------------- the account's limits
    #: Open positions across everything, and per instrument.
    max_positions: int
    max_per_symbol: int
    #: Stop opening for the day after losing this fraction of the day's
    #: opening equity. Measured against the day's open rather than a rolling
    #: window, so a recovery cannot walk the limit forward.
    daily_loss_fraction: float
    #: Money at risk on any one currency, as a share of opening equity.
    #: Zero is off.
    max_currency_exposure: float

    # ------------------------------------------------------ the trade's gates
    #: Reward-to-risk floor from the quoted entry, spread included. Zero is
    #: off, explicitly: relying on "nothing is below zero" would leave the
    #: gate looking enforced while doing nothing.
    min_reward_to_risk: float
    #: The spread as a share of the target, and as a share of the risk. A
    #: scalper's targets are small by construction, so both are fractions
    #: rather than absolutes.
    max_spread_fraction: float
    max_spread_risk_fraction: float
    #: The most of a target the expected overnight swap may take over the
    #: planned hold. Zero is off.
    max_swap_fraction: float
    #: Seconds before the same instrument may be traded again after a loss.
    loss_cooldown: float

    # ------------------------------------------------------------- the clocks
    #: UTC hours in which nothing opens. Empty opens at any hour.
    quiet_hours: tuple[int, ...]
    #: `(start, end)` New York hours in which no **FX** entry opens, end
    #: exclusive; empty turns it off. New York rather than UTC so daylight
    #: saving cannot move the window.
    fx_quiet_ny: tuple[int, int] | tuple[()]
    #: Minutes after the Sunday FX open (17:00 New York) in which nothing
    #: opens. Zero turns it off.
    fx_sunday_open_min: float

    # ------------------------------------------------------------ the calendar
    #: Refuse an entry whose **planned hold** spans a high-impact release,
    #: rather than only one placed inside a window around the print. Off by
    #: default upstairs.
    release_in_hold: bool
    #: How far ahead `release_in_hold` will look, in seconds.
    release_hold_cap_s: float

    # ------------------------------------------------------------- the basket
    #: The three thresholds and two qualifiers `Guard.basket` applies to the
    #: whole open book, each off at zero. See `Guard.basket` for the order
    #: they are checked in, which is worst-first.
    basket_stop_fraction: float
    basket_momentum: float
    basket_give_back: float
    basket_spare_progress: float
    basket_take_fraction: float
