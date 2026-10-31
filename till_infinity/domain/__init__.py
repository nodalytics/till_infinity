"""Facts about instruments and orders that are nobody's strategy.

**This package exists to break a cycle that was really a layering mistake.**
`risk/` imported `strategies.models` for `Intent`, `Position` and `Side`, and
`strategies/` imported back into `risk/` - so neither could be loaded without
the other. The fix was not a lazy import: risk applies *across* strategies, so
it must not depend on one, and the shared pieces were never strategy logic to
begin with.

What is here:

| module | what it is |
| --- | --- |
| `models` | `Intent`, `Position`, `Side`, `Spec` - the shapes an order and a holding take |
| `rollover` | which instruments roll, and when. A property of the contract |
| `swap` | the financing an overnight hold pays. A property of the venue |

**All of it is transitional.** Under Nautilus these are the engine's own:
`Order`, `Position`, `OrderSide`, and an `Instrument` that carries its own
rollover and financing. The package shrinks to nothing as the port proceeds,
which is the right shape for it - a domain layer that has to be *maintained*
beside a framework's own is a second model of the same thing.
"""

from ..domain.models import Intent, Position, Side

__all__ = ["Intent", "Position", "Side"]
