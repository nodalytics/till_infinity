"""The surprise a rule will trade is a band, and both ends are configurable.

The operator, 2026-11-21: *"can the 3sigma be a range instead of a fixed
values, still part of our tests: 1.3 to 3.5 sigma instead of 3sigma only."*

## Why a band, and why the evidence points the unintuitive way

A surprise is a **standardised one-step innovation**, so 3.0 is three standard
deviations from what the model expected. The rule has always had a floor and no
ceiling.

`origin-returns-turn-at-z-one-three` measured **returns turning at z 1.3 to
1.95** while **non-returners reach 2.2**. So for a reversion rule a *larger*
surprise is **less** likely to come back - the edge, if any, lives at the low
end and the big readings are the ones that keep going. The same note records
that **z 2.5 already misses 85-89% of returns**, which says the standing floor
of 3.0 may be the expensive half of the current setting rather than the safe
one.

## The asymmetry these tests exist to pin

`statespace.proposing` publishes nothing below **its own** trigger. So:

* a rule floor **below** the producer's trigger buys no proposals - it only
  makes the gate look open, and the refusal counter reads as a quiet market;
* a rule floor **above** it throws away a band of work already done, which is
  the defect `SurpriseProfile.least_surprise`'s comment records.

Both ends therefore have to move together, and asking for 1.3 at the rule
requires `STATESPACE_TRIGGER=1.3` at the producer.

**Defaults are unchanged.** Unset, the floor is 3.0 and the ceiling infinite,
which is exactly what this desk has always run.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _clean_env():
    kept = {
        name: os.environ.pop(name, None)
        for name in ("STATESPACE_TRIGGER", "TRADING_SURPRISE_MIN", "TRADING_SURPRISE_MAX")
    }
    yield
    for name, value in kept.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


class TestTheProducersTrigger:
    def test_unset_is_the_number_on_record(self) -> None:
        from till_infinity.statespace.proposing import TRIGGER, trigger_now

        assert trigger_now() == TRIGGER == 3.0

    def test_it_can_be_lowered_for_a_sweep(self) -> None:
        from till_infinity.statespace.proposing import trigger_now

        os.environ["STATESPACE_TRIGGER"] = "1.3"
        assert trigger_now() == 1.3

    @pytest.mark.parametrize("bad", ["nonsense", "-2", "0", ""])
    def test_a_value_that_is_not_a_threshold_falls_back(self, bad: str) -> None:
        """**Falls back loudly rather than trading on a typo.** A zero or a
        negative trigger would publish every bar, which on 207 armed
        feed-intervals is the twelve-thousand-readings-an-hour case `actor.py`
        warns about."""
        from till_infinity.statespace.proposing import trigger_now

        os.environ["STATESPACE_TRIGGER"] = bad
        assert trigger_now() == 3.0


class TestTheProfileDefaults:
    def test_the_floor_is_the_producers_trigger(self) -> None:
        """Equal, not merely below: the comment records that at 3.5 every
        proposal in [3.0, 3.5) was emitted only to be refused."""
        from till_infinity.statespace.proposing import TRIGGER
        from till_infinity.strategies.surprise import SurpriseProfile

        assert SurpriseProfile.least_surprise == TRIGGER

    def test_there_is_no_ceiling_by_default(self) -> None:
        """Infinite is the behaviour this rule has always had, so merging the
        band changes nothing until someone sets it."""
        import math

        from till_infinity.strategies.surprise import SurpriseProfile

        assert math.isinf(SurpriseProfile.most_surprise)


class TestTheBandResolves:
    """`_band` needs a desk, so these drive the pure arithmetic through a stub.

    A `Desk` cannot be instantiated without a `BacktestEngine` or a
    `TradingNode` around it - `sizes.py` gives that reason for keeping its own
    logic in plain objects - so the resolution is exercised with the two
    attributes it reads.
    """

    def _stub(self):
        from till_infinity.strategies.surprise import Surprise, SurpriseProfile

        class _Cfg:
            rule = "statespace-surprise"

        class _Log:
            def __init__(self) -> None:
                self.said: list[str] = []

            def warning(self, text: str) -> None:
                self.said.append(text)

        class _Stub(Surprise):
            profile = SurpriseProfile

            def __init__(self) -> None:
                self._cfg = _Cfg()
                self.log = _Log()

        return _Stub()

    def test_unset_is_the_floor_and_no_ceiling(self) -> None:
        import math

        low, high = self._stub()._band()
        assert low == 3.0
        assert math.isinf(high)

    def test_a_band_both_ends_set(self) -> None:
        os.environ["STATESPACE_TRIGGER"] = "1.3"
        os.environ["TRADING_SURPRISE_MIN"] = "1.3"
        os.environ["TRADING_SURPRISE_MAX"] = "3.5"
        assert self._stub()._band() == (1.3, 3.5)

    def test_a_floor_below_what_is_published_is_clamped_and_said(self) -> None:
        """**The asymmetry.** Asking for 1.3 while the producer still emits at
        3.0 buys nothing, so the floor is raised to what is actually published
        and the desk says so once rather than looking open."""
        os.environ["TRADING_SURPRISE_MIN"] = "1.3"
        stub = self._stub()
        low, _ = stub._band()
        assert low == 3.0
        assert any("publishes nothing below" in line for line in stub.log.said)

    def test_it_says_it_only_once(self) -> None:
        """A refusal-rate warning repeated per bar is how a desk produced a
        38,748-line deploy."""
        os.environ["TRADING_SURPRISE_MIN"] = "1.3"
        stub = self._stub()
        for _ in range(5):
            stub._band()
        assert len(stub.log.said) == 1

    @pytest.mark.parametrize(("low", "high"), [("3.5", "1.3"), ("3.0", "3.0")])
    def test_an_empty_band_falls_back_rather_than_trading_nothing(
        self, low: str, high: str
    ) -> None:
        """Inverted, or a point. A desk that refuses everything and a desk with
        no setups write the same report line, which is what
        `venue-faults-hide-below-the-strategy` is named for."""
        import math

        os.environ["TRADING_SURPRISE_MIN"] = low
        os.environ["TRADING_SURPRISE_MAX"] = high
        stub = self._stub()
        got_low, got_high = stub._band()
        assert got_low == 3.0
        assert math.isinf(got_high)
        assert any("is \nempty" in line or "empty" in line for line in stub.log.said)
