"""The band family: eleven estimators, two signal forms, per-side asymmetry.

`strategies/bands.py` exists to make the exit measurable. `ManagedExit` says
break-even and trailing are "an empirical question about this strategy on these
instruments and nothing in this repository answers it", and the rules that
could have answered it place 4 to 18 positions over the catalogue's 76 days.
A band turn on the same 5,135 bars fires often enough to say something: 57 to
204 positions depending on the estimator.

**It is not a direction claim and these tests do not treat it as one.**
`direction-is-closed-not-just-null` records the direction gate finding a
planted drift at z +2.90 while earning 2% of a spread, and a moving-average
crossover is the most-tested direction idea in the subject's history.

Two defects found while building it are pinned below, because both were silent.
"""

from __future__ import annotations

import pytest

from till_infinity.strategies import bands


def _bar(open_=1.1000, high=1.1020, low=1.0990, close=1.1010):
    from nautilus_trader.model.data import Bar

    class Fake:
        """Enough of a `Bar` for `Band.update`, which reads four prices."""

        def __init__(self, o, h, low_, c):
            self.open, self.high, self.low, self.close = o, h, low_, c

    assert Bar is not None
    return Fake(open_, high, low, close)


class TestEveryEstimatorBuildsAndWarms:
    """A kind that cannot build is a cell a sweep loses, and a sweep over
    eleven estimators that silently runs eight is the shape of the defect that
    made `leaf_sweep` report one leaf's result for four rules."""

    @pytest.mark.parametrize("kind", bands.KINDS)
    def test_a_band_warms_and_returns_a_price(self, kind):
        band = bands.Band(kind, 5, side=1)
        closes = [1.1000 + i * 0.0001 for i in range(60)]
        for close in closes:
            band.update(_bar(close=close, high=close + 0.0010, low=close - 0.0010))

        assert band.initialized is True, f"{kind} never warmed"
        assert band.value > 0.0, f"{kind} produced no price"
        # **Sixty bars, not five, and plausibility rather than `initialized`.**
        # `vidya` reports `initialized=True` after its span while reading
        # 0.7745 on data around 1.1000, and `adaptive` is built directly
        # because the factory returns `None` for it.
        assert band.plausible(closes[-1]), f"{kind} warmed to {band.value} at {closes[-1]}"

    def test_the_eleven_are_eight_nautilus_averages_and_three_of_ours(self):
        """Named so a sweep's cell count is checkable against the registry
        rather than against a number somebody typed."""
        assert len(bands.AVERAGES) == 8
        assert len(bands.OURS) == 4
        assert len(bands.KINDS) == 12
        assert set(bands.BREAK_ONLY) <= set(bands.KINDS)


class TestTheThreeThisModuleAdds:
    def test_the_centroid_reads_the_bars_mass_not_its_close(self):
        """What makes it a different estimator from `sma` rather than a slower
        copy: the typical price `(h + l + c) / 3`. `drive-q-from-the-range` is
        the standing reason to prefer a range-aware estimator - the
        range-vs-close ratio runs 0.648 on FX."""
        centroid = bands.Band("centroid", 2)
        sma = bands.Band("sma", 2)
        for _ in range(2):
            bar = _bar(open_=1.1000, high=1.1100, low=1.1000, close=1.1000)
            centroid.update(bar)
            sma.update(bar)

        assert centroid.value == pytest.approx((1.1100 + 1.1000 + 1.1000) / 3.0)
        assert centroid.value > sma.value, "a high wick lifts the centroid and not the close mean"

    def test_the_rolling_extremes_read_the_wick_not_the_close(self):
        """A rolling max of closes is not the level anybody is watching - a
        Donchian edge is the extreme of the highs."""
        top = bands.Band("rmax", 3)
        bottom = bands.Band("rmin", 3)
        for high, low in ((1.1050, 1.0950), (1.1080, 1.0990), (1.1020, 1.0900)):
            bar = _bar(high=high, low=low)
            top.update(bar)
            bottom.update(bar)

        assert top.value == pytest.approx(1.1080)
        assert bottom.value == pytest.approx(1.0900)

    def test_a_sigma_band_is_a_price_and_carries_its_side(self):
        """**A level, not a volatility reading.** `k` sigma either side of the
        window's own mean, which is the only form of this that is a price a
        participant could be watching. The side is the band's, so a long tests
        the upper edge and a short the lower."""
        closes = (1.1000, 1.1010, 1.1020, 1.1030, 1.1040)
        up = bands.Band("sigma", len(closes), side=1, sigma_k=2.0)
        down = bands.Band("sigma", len(closes), side=-1, sigma_k=2.0)
        for close in closes:
            up.update(_bar(close=close))
            down.update(_bar(close=close))

        middle = sum(closes) / len(closes)
        assert up.value > middle > down.value
        assert up.value - middle == pytest.approx(middle - down.value), "symmetric about the mean"

    def test_the_deviation_is_the_populations_and_not_a_samples(self):
        """The window **is** the data the band is drawn from rather than a
        draw from something larger. At span 20 the two differ by 2.6% - enough
        to move a `k` of 2 by 0.05 sigma and not enough for anyone to notice
        it was the wrong one."""
        roll = bands.Rolling(4)
        for value in (1.0, 2.0, 3.0, 4.0):
            roll.update(value)

        assert roll.stdev == pytest.approx((sum((v - 2.5) ** 2 for v in (1, 2, 3, 4)) / 4) ** 0.5)
        assert roll.mean == pytest.approx(2.5)

    def test_a_window_below_two_has_no_deviation_rather_than_a_zero_division(self):
        roll = bands.Rolling(3)
        assert roll.stdev == 0.0
        roll.update(1.0)
        assert roll.stdev == 0.0


class TestTheAsymmetryPreservesItsOwnAverage:
    """`refit-the-parameter-a-lever-multiplies` records a multiplier whose mean
    was not 1 reversing a +1192 result to -24 by moving the average rather than
    the asymmetry. So a tilt has to leave the geometric mean alone."""

    def test_a_tilt_of_one_is_exactly_neutral(self):
        tuning = bands.Tuning(fast=20, slow=50, stop_vol=3.0)
        assert tuning.span_for(20, 1) == tuning.span_for(20, -1) == 20
        assert tuning.stop_for(1) == tuning.stop_for(-1) == pytest.approx(3.0)

    def test_a_tilt_moves_the_sides_apart_and_not_their_average(self):
        tuning = bands.Tuning(stop_vol=3.0, stop_tilt=4.0)
        up, down = tuning.stop_for(1), tuning.stop_for(-1)

        assert up == pytest.approx(6.0)
        assert down == pytest.approx(1.5)
        assert (up * down) ** 0.5 == pytest.approx(3.0), "the geometric mean is the shared value"
        assert up / down == pytest.approx(4.0), "and the ratio is the tilt"


class TestWhatASweepVariesIsReadPerCall:
    def test_the_tuning_is_read_from_the_environment_each_time(self, monkeypatch):
        """**Read per call and not at import.** A sweep sets the environment
        per cell inside one process, so a value captured at import would run
        every cell as the first one - the defect that made a sweep report one
        leaf's result for four rules."""
        monkeypatch.setenv("TRADING_BAND_KIND", "hull")
        monkeypatch.setenv("TRADING_BAND_FAST", "7")
        assert bands.Tuning.read().kind == "hull"
        assert bands.Tuning.read().fast == 7

        monkeypatch.setenv("TRADING_BAND_KIND", "centroid")
        assert bands.Tuning.read().kind == "centroid", "the second cell is not the first"

    def test_an_unknown_estimator_is_refused_by_name(self, monkeypatch):
        """Rather than falling back to a default, which would report a cell
        for an estimator that never ran."""
        monkeypatch.setenv("TRADING_BAND_KIND", "kagi")
        with pytest.raises(ValueError, match="not a band this rule can build"):
            bands.Tuning.read()

    def test_a_two_sided_kind_is_forced_into_the_form_that_fits_it(self, monkeypatch):
        """A fast/slow pair of rolling maxima is two lagging copies of one
        extreme and crosses almost never. Corrected rather than refused: a
        sweep asking for every estimator in both forms would otherwise lose a
        third of its cells to an argument about a form that does not apply."""
        monkeypatch.setenv("TRADING_BAND_MODE", "cross")
        for kind in bands.BREAK_ONLY:
            monkeypatch.setenv("TRADING_BAND_KIND", kind)
            assert bands.Tuning.read().mode == "break", kind

        monkeypatch.setenv("TRADING_BAND_KIND", "ema")
        assert bands.Tuning.read().mode == "cross", "and an average keeps the form it was given"


class TestTheTurnExitCarriesTheAsymmetry:
    """**Without a turn exit the win rate is 0.00 by construction.** With no
    target and no hold clock the only exit is the stop, which is what the
    first run measured on all 57 positions across five estimators. Switching
    it on took `ema` from -160.27 at 7 positions to +100.78 at 57, win rate
    0.00 to 0.26.

    The three-way flag exists because the interesting arm is neither on nor
    off. `band_asymmetry.py` measured `both` at a payoff ratio of **2.61
    against the 2.75 its 0.27 win rate requires**, while a trail at 2.0 took
    the same cell to 1.28 against 2.14 - so the policies that look like
    improvements cut the right tail that pays for everything. `losers` is the
    arm that cuts the left tail only.
    """

    def test_the_conventional_rule_is_the_default(self):
        assert bands.Tuning().exit_turn == "both"
        assert bands.Tuning().exit_on_turn is True

    def test_never_is_the_control_and_reports_as_no_turn_exit(self):
        """Kept as the arm that shows what the turn exit is worth - 6 positions
        over 5,135 bars, since a held position blocks re-entry and only a stop
        ends it - and not as a candidate."""
        assert bands.Tuning(exit_turn="never").exit_on_turn is False

    def test_the_asymmetric_arm_still_closes_something(self):
        """`losers` has to read as a turn exit, or a reader checking whether
        the cross closes anything gets the wrong answer for the one arm that
        matters."""
        assert bands.Tuning(exit_turn="losers").exit_on_turn is True

    @pytest.mark.parametrize(
        ("given", "wanted"),
        [
            ("both", "both"),
            ("1", "both"),
            ("never", "never"),
            ("0", "never"),
            ("losers", "losers"),
            ("LOSERS", "losers"),
            (None, "both"),
        ],
    )
    def test_the_old_boolean_spelling_still_reads(self, given, wanted):
        """The flag was a boolean first and a sweep script may still pass one,
        so `1` and `0` map onto the ends rather than raising."""
        assert bands._turn(given) == wanted

    def test_an_unknown_arm_is_refused_by_name(self):
        """Rather than defaulting, which would report a cell for an arm that
        never ran - the defect this file has pinned twice already."""
        with pytest.raises(ValueError, match="not a turn exit"):
            bands._turn("winners")


def test_the_rule_publishes_a_volatility_the_trail_can_use():
    """A rule carrying no volatility gets no trail, silently: `advance`
    multiplies by `vol_bps` and stands down on a zero. The band rule publishes
    `ma_atr` with `ma_close` as its anchor rather than writing an ATR into
    `vol_bps`, which would put one journal column in two estimators -
    `structure.py` gives that reason in place. `exits._trail_vol_bps` does the
    conversion for any `*_atr` with its anchor."""
    from types import SimpleNamespace

    from till_infinity.strategies.exits import _trail_vol_bps

    intent = SimpleNamespace(features={"ma_atr": 0.0012, "ma_close": 1.1000})
    assert _trail_vol_bps(intent) == pytest.approx(0.0012 / 1.1000 * 10_000.0)

    # The anchor has to share the prefix. A `ma_atr` beside a `bos_close` is
    # two moments' prices and would read calibrated near 1.0 only.
    assert _trail_vol_bps(SimpleNamespace(features={"ma_atr": 0.0012})) == 0.0


class TestTheAsymmetricArmActuallyCloses:
    """**34,130 swallowed failures in one sweep.**

    `_leave(losers_only=True)` first asked `Position.unrealized_pnl(price)`,
    which takes a Nautilus `Price` while `Desk._tick()` returns this desk's own
    tick with plain floats. Every call raised `Argument 'price' has incorrect
    type (expected Price, got float)`, the handler counted it as a warning and
    carried on, and the whole `losers` arm closed nothing while still reporting
    cells for a third of the grid.

    So the side is decided from the prices, which have no type to get wrong.
    """

    def _position(self, *, long: bool, entry: float):
        from types import SimpleNamespace

        return SimpleNamespace(is_long=long, is_short=not long, avg_px_open=entry)

    def _desk(self, bid: float | None, ask: float | None):
        from types import SimpleNamespace

        desk = bands.Bands.__new__(bands.Bands)
        desk.counts = {}
        tick = None if bid is None else SimpleNamespace(bid=bid, ask=ask)
        desk._tick = lambda: tick  # type: ignore[method-assign]
        return desk

    def test_a_long_is_judged_on_the_bid_it_would_exit_on(self):
        """Not the mid and not the ask: the question is whether the trade is
        behind at the price it would actually get."""
        held = self._position(long=True, entry=1.1000)

        assert self._desk(1.0990, 1.1010)._behind(held) is True
        assert self._desk(1.1010, 1.1030)._behind(held) is False
        # The ask alone is above the entry and the bid is not, which is the
        # case a mid would get wrong.
        assert self._desk(1.0999, 1.1005)._behind(held) is True

    def test_a_short_is_judged_on_the_ask(self):
        held = self._position(long=False, entry=1.1000)

        assert self._desk(1.0990, 1.0995)._behind(held) is False
        assert self._desk(1.1005, 1.1010)._behind(held) is True

    def test_a_position_with_no_entry_is_left_alone(self):
        """Cutting on a price nothing measured would close the winners this arm
        exists to keep, so the missing case leans the safe way."""
        held = self._position(long=True, entry=0.0)
        assert self._desk(1.0, 1.1)._behind(held) is False

    def test_no_quote_leaves_everything_alone_and_is_counted(self):
        """The same safe direction, and counted so a run that lost its quote
        stream is visible in the tally rather than in the fills."""
        desk = self._desk(None, None)
        held = self._position(long=True, entry=1.1000)

        assert desk._behind(held) is False
        assert desk.counts["no_quote"] == 1
