"""Closing the whole book on its net floating profit.

The account does not hold seventeen opinions, it holds one balance, and nothing
here read that. `Guard.allows` decides whether to open, the per-trade stops decide
each leg, and `daily_loss_fraction` halts opening on *realised* loss - none of them
can act on the floating total across positions, which with `parallel` on is the
same direction on the same instrument up to seventeen times over.
"""

from __future__ import annotations

from till_infinity.trading import Settings
from till_infinity.trading.risk import Guard


def desk(**over) -> Guard:
    made = Settings()
    for k, v in over.items():
        setattr(made, k, v)
    guard = Guard(made, currency="USD")
    guard.roll(10_000.0, now=1_000.0)
    return guard


class TestEveryRuleIsOffAtZero:
    """The idiom the rest of the module uses, and it matters more here: a basket
    close is the most destructive action the desk can take, so it must be
    impossible to get by accident."""

    def test_a_default_desk_never_closes_the_book(self):
        guard = desk()
        for net in (-5_000.0, -100.0, 0.0, 100.0, 5_000.0):
            assert guard.basket(net, 10_000.0) == "", net

    def test_the_settings_default_off(self):
        made = Settings()
        assert made.basket_give_back == 0.0
        assert made.basket_stop_fraction == 0.0
        assert made.basket_take_fraction == 0.0


class TestTheBasketStop:
    def test_it_closes_past_the_loss_share_of_opening_equity(self):
        guard = desk(basket_stop_fraction=0.02)  # 2% of 10,000 = 200
        assert guard.basket(-150.0, 10_000.0) == ""
        said = guard.basket(-250.0, 10_000.0)
        assert said, "a 250 loss should trip a 200 stop"
        assert "basket stop" in said, said

    def test_it_measures_against_the_days_opening_equity_not_the_current(self):
        """Equity moves during the day, so measuring against it would make the
        limit loosen as the desk lost - the mistake `daily_loss_limit` already
        avoids by holding `opening_equity`."""
        guard = desk(basket_stop_fraction=0.02)
        # Equity has halved, but the day opened at 10,000, so the limit is still 200.
        assert guard.basket(-250.0, 5_000.0) != ""
        assert guard.basket(-150.0, 5_000.0) == ""


class TestTheGiveBack:
    def test_it_closes_after_handing_back_the_share_of_a_peak(self):
        guard = desk(basket_give_back=0.5)
        assert guard.basket(100.0, 10_000.0) == ""  # a peak of 100 forms
        assert guard.basket(80.0, 10_000.0) == ""  # given back 20%
        said = guard.basket(40.0, 10_000.0)  # given back 60%
        assert said, "handing back 60% of a 100 peak should close at a 50% rule"
        assert "given back" in said, said

    def test_a_book_that_was_never_in_profit_is_left_to_the_stop(self):
        """**The trap.** With no peak, `peak * (1 - give)` is zero, so the rule
        would fire the first tick a book went red - doing the stop's job at a
        threshold nobody chose."""
        guard = desk(basket_give_back=0.5)
        for net in (-1.0, -50.0, -500.0):
            assert guard.basket(net, 10_000.0) == "", net

    def test_the_peak_is_the_highest_seen_and_not_the_latest(self):
        guard = desk(basket_give_back=0.5)
        guard.basket(200.0, 10_000.0)
        guard.basket(50.0, 10_000.0)  # trips, but the peak stands
        assert guard.basket_peak == 200.0

    def test_the_peak_survives_a_restart(self):
        """A peak that resets on deploy makes the rule measure from wherever the
        desk happened to reboot, which today it did six times."""
        guard = desk(basket_give_back=0.5)
        guard.basket(300.0, 10_000.0)
        saved = guard.state()
        fresh = desk(basket_give_back=0.5)
        fresh.restore(saved, now=1_000.0)
        assert fresh.basket_peak == 300.0
        assert fresh.basket(100.0, 10_000.0) != "", "a restored peak must still bind"

    def test_a_new_day_forgets_the_peak(self):
        guard = desk(basket_give_back=0.5)
        guard.basket(300.0, 10_000.0)
        guard.roll(10_000.0, now=1_000.0 + 86_400 * 2)
        assert guard.basket_peak == 0.0


class TestTheBasketTarget:
    def test_it_closes_at_the_profit_share(self):
        guard = desk(basket_take_fraction=0.01)  # 1% of 10,000 = 100
        assert guard.basket(80.0, 10_000.0) == ""
        said = guard.basket(120.0, 10_000.0)
        assert said, "a 120 profit should reach a 100 target"
        assert "basket target" in said, said


class TestTheWorstReasonWins:
    def test_a_book_tripping_the_stop_reports_the_stop(self):
        """Two rules can fire on one book. The loss is the one an operator needs
        to read first, so it is checked first."""
        guard = desk(basket_stop_fraction=0.01, basket_give_back=0.5)
        guard.basket(500.0, 10_000.0)  # a peak forms
        said = guard.basket(-200.0, 10_000.0)  # trips both
        assert "basket stop" in said, said


class TestTheServiceActsOnIt:
    async def test_it_closes_every_position_and_journals_once(self):
        from till_infinity.bus import Bus
        from till_infinity.trading.models import Intent, Position, Side
        from till_infinity.trading.service import Live, Trader

        settings = Settings(live=False)
        settings.basket_stop_fraction = 0.01  # 1% of 10,000 = 100
        trader = Trader(Bus(), settings=settings)
        trader.guard.roll(10_000.0, now=1_000.0)
        trader.equity = 10_000.0

        shut: list[int] = []

        class Book:
            async def close_position(self, ticket, volume=0.0):
                shut.append(ticket)

        # `execution` is a property returning `paper or broker`, so the stub goes
        # on `paper` - which is also where a paper desk's orders really go.
        trader.paper = Book()
        written: list[object] = []

        class Journal:
            async def write(self, entry):
                written.append(entry)
                return getattr(entry, "id", "x")

        trader.journal = Journal()

        for ticket, profit in ((1, -80.0), (2, -60.0), (3, 20.0)):
            position = Position(
                ticket=ticket,
                symbol="XAUUSD",
                side=Side.BUY,
                volume=0.05,
                price_open=4400.0,
                profit=profit,
            )
            intent = Intent(
                feed="gold",
                symbol="XAUUSD",
                side=Side.BUY,
                volume=0.05,
                entry=4400.0,
                stop=4390.0,
                target=4420.0,
                interval="15m",
            )
            trader.open[ticket] = Live(position=position, intent=intent, by="snap")

        closed = await trader._basket()  # net is -120, past the 100 stop

        assert closed == 3, closed
        assert sorted(shut) == [1, 2, 3], shut
        assert len(written) == 1, "the whole book closing is one event, not three"

    async def test_a_flat_book_does_nothing(self):
        from till_infinity.bus import Bus
        from till_infinity.trading.service import Trader

        settings = Settings(live=False)
        settings.basket_stop_fraction = 0.01
        trader = Trader(Bus(), settings=settings)
        assert await trader._basket() == 0


class TestItUsesMomentumAndTargetProgress:
    """**Closing on a net dip is blunt.** A book whose positions are nearly at
    target may be in the last pullback before them, and a basket close pays the
    spread on every leg to avoid it. And give-back is backward-looking: it waits for
    profit to be handed back, while `cusum` reads the reversal that will do it.
    """

    def test_a_book_nearly_at_target_is_spared_the_give_back(self):
        guard = desk(basket_give_back=0.5, basket_spare_progress=0.8)
        guard.basket(200.0, 10_000.0, progress=0.85)
        # Handed back 60%, which would normally close it - but it is 85% of the way.
        assert guard.basket(80.0, 10_000.0, progress=0.85) == ""

    def test_a_book_going_nowhere_is_not_spared(self):
        guard = desk(basket_give_back=0.5, basket_spare_progress=0.8)
        guard.basket(200.0, 10_000.0, progress=0.2)
        assert guard.basket(80.0, 10_000.0, progress=0.2) != ""

    def test_progress_never_spares_the_stop(self):
        """A loss limit answers to nothing else. A book 95% of the way to target
        that is still past the stop is past the stop."""
        guard = desk(basket_stop_fraction=0.01, basket_spare_progress=0.8)
        said = guard.basket(-200.0, 10_000.0, progress=0.95)
        assert said, "progress must not spare the loss limit"
        assert "basket stop" in said, said

    def test_momentum_against_the_book_closes_it(self):
        guard = desk(basket_momentum=2.0)
        assert guard.basket(50.0, 10_000.0, against=1.0) == ""
        said = guard.basket(50.0, 10_000.0, against=2.5)
        assert said, "2.5v against a 2.0v tolerance should close"
        assert "momentum" in said, said

    def test_momentum_is_read_before_give_back(self):
        """The same reversal, seen sooner. An operator reading the log should be
        told the market turned, not that profit went missing."""
        guard = desk(basket_momentum=2.0, basket_give_back=0.5)
        guard.basket(200.0, 10_000.0, against=0.0)
        said = guard.basket(50.0, 10_000.0, against=3.0)
        assert "momentum" in said, said

    def test_an_unknown_progress_does_not_spare_anything(self):
        """None means unmeasurable, and treating that as "not close" would let an
        unmeasurable book escape the rule."""
        guard = desk(basket_give_back=0.5, basket_spare_progress=0.8)
        guard.basket(200.0, 10_000.0, progress=None)
        assert guard.basket(80.0, 10_000.0, progress=None) != ""

    def test_both_are_off_at_zero(self):
        guard = desk(basket_give_back=0.5)
        guard.basket(200.0, 10_000.0, progress=0.99, against=99.0)
        assert guard.basket(80.0, 10_000.0, progress=0.99, against=99.0) != ""


class TestTheBookReadings:
    def test_progress_is_the_median_not_the_mean(self):
        """One malformed target - `best_r` reached 1,771 on the record - would
        otherwise decide the whole book."""
        from till_infinity.bus import Bus
        from till_infinity.trading.models import Intent, Position, Side
        from till_infinity.trading.service import Live, Trader

        trader = Trader(Bus(), settings=Settings(live=False))
        for ticket, target in ((1, 4420.0), (2, 4420.0), (3, 4_000_000.0)):
            trader.open[ticket] = Live(
                position=Position(
                    ticket=ticket,
                    symbol="XAUUSD",
                    side=Side.BUY,
                    volume=0.05,
                    price_open=4400.0,
                    price_current=4402.0,
                ),
                intent=Intent(
                    feed="gold",
                    symbol="XAUUSD",
                    side=Side.BUY,
                    volume=0.05,
                    entry=4400.0,
                    stop=4390.0,
                    target=target,
                    interval="15m",
                ),
                by="snap",
            )
        got = trader._book_progress()
        assert got is not None
        assert 0.05 < got < 0.15, got

    def test_a_hedged_book_reads_near_zero_momentum(self):
        """A per-position reading would call a hedged book alarming from both
        sides at once."""
        from till_infinity.bus import Bus
        from till_infinity.structures.context.cusum import Cusum
        from till_infinity.trading.models import Intent, Position, Side
        from till_infinity.trading.service import Live, Trader

        trader = Trader(Bus(), settings=Settings(live=False))
        running = Cusum()
        running.up, running.down, running.started = 2.0, 0.0, True
        trader._push["gold"] = running
        for ticket, side in ((1, Side.BUY), (2, Side.SELL)):
            trader.open[ticket] = Live(
                position=Position(
                    ticket=ticket,
                    symbol="XAUUSD",
                    side=side,
                    volume=0.05,
                    price_open=4400.0,
                    price_current=4400.0,
                ),
                intent=Intent(
                    feed="gold",
                    symbol="XAUUSD",
                    side=side,
                    volume=0.05,
                    entry=4400.0,
                    stop=4390.0,
                    target=4420.0,
                    interval="15m",
                ),
                by="snap",
            )
        assert abs(trader._book_against()) < 1e-9, trader._book_against()

    def test_a_flat_book_has_no_progress_to_report(self):
        from till_infinity.bus import Bus
        from till_infinity.trading.service import Trader

        trader = Trader(Bus(), settings=Settings(live=False))
        assert trader._book_progress() is None
        assert trader._book_against() == 0.0
