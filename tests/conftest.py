"""Session-wide fixtures for the suite.

Its one job today is to put `tests/mechanics.Mechanics` in the strategy
registry. That happens here rather than with a `@register` decorator on the
class so that the *package* never sees it: nothing in `till_infinity` imports
`tests/`, `trading strategies` does not list it, and a production registry
built from the package alone is unchanged. Read `tests/mechanics.py` for why a
test vehicle is wanted at all.
"""

from __future__ import annotations

import mechanics
import pytest

from till_infinity import trading
from till_infinity.trading import config
from till_infinity.trading.strategies.strategy import STRATEGIES


@pytest.fixture(scope="session", autouse=True)
def _register_the_test_vehicle():
    """Register the vehicle for the session, and take it out again.

    Session-scoped because `settings()` names it as the default and is called
    from every corner of the suite; removed afterwards so a test run cannot
    leave a strategy behind for whatever imports the registry next.

    **It needs a `MAGIC_ORDER` slot as well as a registry entry**, and that is
    worth saying rather than hiding. Attribution is read back from a position's
    magic number: a strategy without a slot stamps a hashed one with no
    inverse, `Live.by` comes back empty, and every rule that matches on who
    opened a position stops matching.
    `test_one_strategy_cannot_hold_two_positions_on_one_instrument` predicts
    exactly that in its own docstring - "a strategy whose magic is unregistered
    slips the check" - and it was the test that found this.

    Appended for the session rather than committed to the tuple, because
    `MAGIC_ORDER` is append-only *production* config and a test vehicle has no
    business in it: production builds its registry from the package, which
    never sees this file.
    """
    STRATEGIES[mechanics.NAME] = mechanics.Mechanics
    # **Both bindings.** `trading/__init__.py` does `from .config import
    # MAGIC_ORDER`, which binds the tuple a second time - so patching the
    # config module alone leaves `td.MAGIC_ORDER` pointing at the original and
    # the two disagree about which strategies have a slot.
    was = config.MAGIC_ORDER
    widened = (*was, mechanics.NAME)
    config.MAGIC_ORDER = widened
    trading.MAGIC_ORDER = widened
    yield
    config.MAGIC_ORDER = was
    trading.MAGIC_ORDER = was
    STRATEGIES.pop(mechanics.NAME, None)
