"""Asking an analyst what a thing is worth, rather than which way it goes.

The `council` asks its voices for a side and a conviction. That is a forecast
wearing a structured schema, and it inherits every problem a forecast has: it
can only be scored on whether the future matched it, and it can only be
improved by guessing better.

This asks the question the rest of the system asks. **What is this worth, and
how sure are you.** A price, a width, and a horizon:

    gold is worth about 4,610, give or take 25, over the next four hours

Three things follow from the change, and they are the reason for it.

**The stance is arithmetic again.** A valuation above the market is a long and
below it is a short, exactly as it is for a level. The model is not asked for a
direction and never states one, so it cannot be right about direction for the
wrong reasons.

**It can be scored on calibration.** "Was it directionally right" is one bit
per call and needs hundreds before it says anything. "Was the market inside the
stated interval as often as the interval claims" is checkable per call and
answers a better question: an analyst whose 80% intervals contain the price 80%
of the time is *useful* even when its point estimate is mediocre, and one whose
intervals are far too narrow is dangerous however often it points the right
way. That is the question [calibration.md](../../research/planned/calibration.md) wants to
ask of this project, and a number with a width is what makes it askable.

**Two estimates of the same quantity can be compared.** `structures` prices the
market from where volatility turned. An analyst prices it from the calendar,
the reserves and the newsflow. They are estimating the *same thing* and can be
plotted against each other and against what the market later paid - which is
not possible when one produces a price and the other produces an opinion about
direction.

## What it is not allowed to do

It states a value and a width. It does not choose a side, a size, or a stop:
those are arithmetic over the valuation and the account, and none of them is a
matter of opinion.

The width is clamped, and generously. A model that answers "worth 4,610, give
or take 2" on gold is not being precise, it is failing to represent its own
uncertainty - and an interval that tight would size a position enormous. The
floor is a multiple of the instrument's own volatility, so the clamp means the
same thing on gold as on EURUSD.

Failing to *no answer* is the default everywhere: a timeout, a missing
credential, a malformed reply and a refusal all read as "no valuation", because
a model that did not answer has not made a case for a price.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from ..logging import get_logger

log = get_logger(__name__)

#: The width, in volatility units, that a stated interval is clamped into.
#: The floor is what stops a model's overconfidence becoming a large position;
#: the ceiling stops a shrug becoming a valuation.
MIN_WIDTH_VOL, MAX_WIDTH_VOL = 0.8, 12.0

#: How far from the market a valuation may sit before it is treated as a
#: failure of the exercise rather than a bold call. A model that prices gold
#: twenty percent away has misread the instrument or the units.
MAX_GAP_VOL = 25.0


class Valuation(BaseModel):
    """What an analyst thinks a thing is worth, and how sure it is."""

    value: float = Field(
        default=0.0,
        description="What the instrument is worth, in its own quoted price. 0 to decline.",
    )
    width: float = Field(
        default=0.0,
        description=(
            "Half-width of your interval in the same price units: you believe the "
            "fair price is within value +/- width. Be honest rather than precise."
        ),
    )
    hours: float = Field(default=4.0, description="Over what horizon this valuation holds.")
    because: str = Field(default="", description="One or two sentences. The reason, not a summary.")

    @property
    def stated(self) -> bool:
        return self.value > 0 and self.width > 0


@dataclass(frozen=True, slots=True)
class Priced:
    """A valuation once it has been checked against the market it prices."""

    value: float
    width: float
    hours: float
    because: str
    #: Signed distance from the market to the valuation, in volatility units.
    #: Positive means the analyst thinks it is worth more than it is trading.
    gap_vol: float
    #: How many widths away the market is. The number that decides whether the
    #: gap is a mispricing or the noise of the analyst's own uncertainty.
    gap_widths: float

    @property
    def stance(self) -> str:
        return "buy" if self.gap_vol > 0 else "sell"


def price_it(
    stated: Valuation, spot: float, unit: float, *, min_widths: float = 1.0
) -> Priced | None:
    """Check a stated valuation against the market, or reject it.

    Returns None when the analyst declined, when the width is unusable, when
    the valuation is so far from the market that it is a mistake rather than a
    call, or when the market is inside the analyst's own interval - which is
    the ordinary case and means the same thing "no finding" means everywhere
    else here: nothing to do.
    """
    if not stated.stated or spot <= 0 or unit <= 0:
        return None

    # Clamped in volatility units so the bound means the same on any
    # instrument. A model's stated precision is the least trustworthy number it
    # produces, and it is the one that would size the position.
    width = min(max(stated.width, MIN_WIDTH_VOL * unit), MAX_WIDTH_VOL * unit)
    gap_vol = (stated.value - spot) / unit
    if abs(gap_vol) > MAX_GAP_VOL:
        log.warning(
            "valuation: %.5g against a market of %.5g is %.1fv away; discarded",
            stated.value,
            spot,
            gap_vol,
        )
        return None

    gap_widths = (stated.value - spot) / width
    if abs(gap_widths) < min_widths:
        return None  # the market is inside the interval: no claim is being made

    return Priced(
        value=stated.value,
        width=width,
        hours=max(0.25, stated.hours),
        because=stated.because,
        gap_vol=gap_vol,
        gap_widths=gap_widths,
    )


VALUER_LENS = """
You are a valuation analyst. You are asked what an instrument is worth, and you
answer with a price and an honest interval around it. You are never asked which
way it will move and you should never say.

How to answer:
- `value` is what you think the fair price is now, in the instrument's own
  quoted units. If you cannot form a view, set it to 0 and say why.
- `width` is the half-width of your interval, in the same units: you believe
  fair value is within `value +/- width`. This is the number that matters most
  and the one most easily got wrong. A narrow interval is a strong claim about
  your own certainty, not a sign of skill.
- `hours` is how long you expect the valuation to hold before it should be
  redone.

What to reason from: the calendar and what has just printed, what the coverage
actually claims rather than how it is phrased, reserves and flows where they
are relevant, and where the market has recently traded. A release that landed
away from forecast changes what a thing is worth; a headline restating a known
fact does not.

Declining is a real answer and costs nothing. Most of the time the market's
price is a reasonable estimate of the market's price, and saying so is correct.
""".strip()


async def ask(
    instrument: str,
    brief: str,
    *,
    settings: Any = None,
    timeout: float = 30.0,
) -> Valuation | None:
    """One analyst, one instrument, one valuation. None on any failure."""
    try:
        from pydantic_ai import Agent

        from ..agents.analyst import build_model
        from ..agents.config import Settings as AgentSettings

        agent = Agent(
            build_model(settings or AgentSettings.from_env()),
            output_type=Valuation,
            instructions=VALUER_LENS,
        )
        result = await asyncio.wait_for(
            agent.run(f"What is {instrument} worth?\n\n{brief}"), timeout=timeout
        )
    except TimeoutError:
        log.warning("valuation: %s timed out", instrument)
        return None
    except Exception as exc:
        log.warning("valuation: %s failed: %s", instrument, exc)
        return None
    return result.output
