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
| `models` | `Intent`, `Position`, `Side`, `SymbolSpec` - the shapes an order and a holding take |
| `rollover` | which instruments roll, and when. A property of the contract |
| `swap` | the financing an overnight hold pays. A property of the venue |
| `barriers` | what a stop-and-target geometry is worth before anything is traded |

**Three of the four are transitional.** Under Nautilus `models`, `rollover` and
`swap` are the engine's own: `Order`, `Position`, `OrderSide`, and an
`Instrument` that carries its own rollover and financing. Those three shrink to
nothing as the port proceeds, which is the right shape for them - a domain
layer that has to be *maintained* beside a framework's own is a second model of
the same thing. `barriers` is not in that set. It is first-passage arithmetic
against this desk's own measurements, and the framework has nothing that
replaces it.
"""

from ..domain.models import Intent, Position, Side

__all__ = ["Intent", "Position", "Side"]
