"""Session-wide fixtures for the suite.

**Deliberately almost empty.** Its one job used to be registering
`tests/mechanics.Mechanics` in a strategy registry, so that `settings()` could
name a test vehicle as its default. There is no registry: a decision is a mixin
composed into a Nautilus `Strategy` (see `strategies/surprise.py`), so a test
that wants one defines it in the test file - as `tests/test_desk.py` does with
`_Deciding`, `_Unwanting` and `_Declining`.

That fixture also had to append a `MAGIC_ORDER` slot, because attribution was
read back from a position's magic number and a strategy without a slot stamped
a hashed one with no inverse. Attribution is now Nautilus's `strategy_id`,
assigned by the framework, so neither the registry entry nor the magic slot has
anything to do.
"""

from __future__ import annotations
