"""The volatility sizing reads, and why it is this one.

An EWMA of true range beat every figure the desk produces - `vol_bps`,
`garch_bps`, `ensemble_bps`, `forecast_bps`, `range_bps` - at the horizon each of
those was built for, across 11,797 recorded calls. Including GARCH at one bar
ahead scored against return variance, its own quantity: 0.331 to 0.166.
"""

from __future__ import annotations

import math

from till_infinity.structures.vol.ranges import MIN_VOL_BPS, TR_ALPHA, Ranges


def steady(book: Ranges, n: int, price: float = 100.0, span: float = 0.10) -> None:
    for i in range(n):
        base = price + i * 0.001
        book.observe(base, base + span / 2, base - span / 2, base)


class TestItIsAnEwmaAndNotAWindow:
    """Recursive, so it carries every bar with a decaying weight. Recomputing it
    over the kept window would be a different quantity."""

    def test_one_wide_bar_moves_it_part_of_the_way(self):
        book = Ranges()
        steady(book, 40)
        before = book.ewma_tr_bps
        book.observe(100.04, 101.5, 100.0, 101.4)
        after = book.ewma_tr_bps
        assert after > before, (before, after)
        # A mean over 60 bars would barely move; jumping to the new bar would
        # mean no smoothing at all. It should land between.
        assert after < 10 * before, (before, after)

    def test_it_decays_back_when_the_market_quietens(self):
        book = Ranges()
        steady(book, 40)
        calm = book.ewma_tr_bps
        book.observe(100.04, 101.5, 100.0, 101.4)
        loud = book.ewma_tr_bps
        steady(book, 60, price=101.4)
        assert book.ewma_tr_bps < loud, (loud, book.ewma_tr_bps)
        assert book.ewma_tr_bps == __import__("pytest").approx(calm, rel=0.35)

    def test_the_alpha_is_wilders(self):
        assert TR_ALPHA == 1.0 / 14.0

    def test_a_cold_book_reports_the_floor_rather_than_zero(self):
        assert Ranges().ewma_tr_bps == MIN_VOL_BPS


class TestItIsRelativeNotAbsolute:
    """**The trap that nearly inverted the measurement.**

    Scored in price units every estimator reached about 0.57 because it was
    tracking the price level; normalising collapsed them to 0.30 and reordered the
    table. An instrument that doubled in price has not doubled in volatility.
    """

    def test_the_same_percentage_range_reads_the_same_at_any_price(self):
        cheap, dear = Ranges(), Ranges()
        for i in range(60):
            b = 10.0 + i * 0.0001
            cheap.observe(b, b * 1.001, b * 0.999, b)
            d = 10_000.0 + i * 0.1
            dear.observe(d, d * 1.001, d * 0.999, d)
        assert cheap.ewma_tr_bps == __import__("pytest").approx(dear.ewma_tr_bps, rel=0.02)

    def test_it_is_in_basis_points_of_the_last_close(self):
        book = Ranges()
        steady(book, 80, price=100.0, span=0.10)  # 0.10 on 100 = 10bp
        assert book.ewma_tr_bps == __import__("pytest").approx(10.0, rel=0.05)


class TestSizingReadsIt:
    def test_the_multiplier_follows_the_ewma_not_vol_bps(self):
        """`vol_bps` is the fallback for a signal published before this feature
        existed, not a switch - an absent reading still has to size somehow."""
        from till_infinity.trading import Settings
        from till_infinity.trading.models import Side
        from till_infinity.trading.strategies.strategy import build

        settings = Settings()
        settings.volatility_target_bps = 10.0
        engine = build(["level-scalp"], settings)[0]
        args = {
            "feed": "gold",
            "positions": (),
            "equity": 10_000.0,
            "peak": 10_000.0,
            "interval": "15m",
            "side": Side.BUY,
        }
        # A calm EWMA against a loud vol_bps: the EWMA must decide.
        calm = engine.risk_scale(features={"ewma_tr_bps": 10.0, "vol_bps": 500.0}, **args)
        loud = engine.risk_scale(features={"ewma_tr_bps": 500.0, "vol_bps": 10.0}, **args)
        assert calm > loud, (calm, loud)

    def test_it_falls_back_to_vol_bps_when_absent(self):
        from till_infinity.trading import Settings
        from till_infinity.trading.models import Side
        from till_infinity.trading.strategies.strategy import build

        settings = Settings()
        settings.volatility_target_bps = 10.0
        engine = build(["level-scalp"], settings)[0]
        args = {
            "feed": "gold",
            "positions": (),
            "equity": 10_000.0,
            "peak": 10_000.0,
            "interval": "15m",
            "side": Side.BUY,
        }
        old = engine.risk_scale(features={"vol_bps": 500.0}, **args)
        both = engine.risk_scale(features={"ewma_tr_bps": 500.0, "vol_bps": 500.0}, **args)
        assert old == both, (old, both)


def test_the_engine_publishes_it():
    """Trading reads features off the bus and never touches the engine, so a
    reading that is not published cannot be sized from."""
    import inspect

    from till_infinity.structures import engine as eng

    assert '"ewma_tr_bps"' in inspect.getsource(eng)


def test_it_survives_a_restore():
    """Learned-ish state: an accumulated average that resets on every deploy is a
    cold estimate for the first fourteen bars of every run."""
    import pickle

    book = Ranges()
    steady(book, 80)
    before = book.ewma_tr_bps
    back = pickle.loads(pickle.dumps(book))
    assert back.ewma_tr_bps == before
    assert not math.isnan(back.ewma_tr_bps)
