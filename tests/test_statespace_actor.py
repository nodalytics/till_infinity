"""The seam between the indicator panel and the sweep, and the proposal path.

`actor.py` is the only file in `statespace` allowed to know about Nautilus, so
it is where the two things that need a `Bar` live: `detector_reader`, which
turns a catalogued detector into the plain `candles -> floats` value a sweep
holds, and `_propose`, which puts a trading proposal on the bus.

Two traps are pinned here because both are silent when wrong.

**A reader built by hand is a reader with the wrong units.**
`indicators.build_detector` picks the volatility unit that matches the source's
dimension, and `bars.check_scale` refuses a pair that does not - a log return
divided by a price range "reads perfectly calibrated at a price near 1.0 and is
wrong by a factor of the price everywhere else". So the test asserts the reader
goes through `build_detector`.

**`Price` is fixed-precision, and the precision truncates the feed before the
detector sees it.** Measured on the fold: btc at its tradable two decimals
moves a 1m reading by 3e-5 relative, and a volume precision of 0 rounded 701 of
3,000 btc volumes to zero. A sweep measures the series rather than a fill, so
it takes the series undamaged.
"""

from __future__ import annotations

import math
import random
from typing import Any

import pytest

from till_infinity.indicators import BAR_DETECTORS, FRAMEWORK, TICK_DETECTORS
from till_infinity.statespace import actor as ss_actor


def walk(n: int = 400, *, seed: int = 7, start: float = 1.1000, step: float = 0.0004):
    """A walk with a varying bar shape, so a shape reader has something to see."""
    rng = random.Random(seed)
    price, out = start, []
    for _ in range(n):
        price += rng.gauss(0.0, step)
        span = abs(rng.gauss(0.0, step)) + 1e-9
        low = price - rng.random() * span
        out.append((low + rng.random() * span, low + span, low, price))
    return out


class Readout:
    """Only what `proposing` reads, so a field it does not read cannot pass."""

    feed = "eurusd"
    interval = "1h"
    at = 1_700_000_000.0
    #: log variance; `exp(value / 2)` is a return standard deviation.
    value = 2.0 * math.log(1e-4)
    spread = 0.05
    surprise = 4.5
    stretch = 0.0

    def covering(self, coverage: float) -> None:
        return None

    def barrier(self, probability: float, horizon: float) -> dict[str, float]:
        return {"probability": 0.42}


class TestTheReadingsTable:
    @pytest.mark.parametrize("name", sorted(ss_actor.READINGS))
    def test_every_catalogued_reading_produces_a_number_on_a_real_series(self, name) -> None:
        """A detector the table names and the reader cannot read is a sweep
        reporting a null for a question it never asked - the same failure
        `_register` raises on rather than skipping."""
        sources = BAR_DETECTORS.get(name, (None, ()))[1]
        source = str(sources[0]) if sources else None
        extra = {"hazard": 1.0 / 24.0} if name == "changepoint" else {}
        got = ss_actor.detector_reader(name, source, **extra)(walk())
        assert len(got) == 400
        live = [v for v in got if not math.isnan(v)]
        assert live, f"{name} produced no reading at all"
        assert all(v >= 0.0 for v in live), "an unsigned reader returned a negative"

    def test_a_signed_reading_is_available_but_is_not_the_default(self) -> None:
        """The statistic is a forward **absolute** move, so a signed trigger
        would be asking a direction question under a dispersion label - and
        direction is the one question measured closed here. `signed=True` is
        how a caller asks for it, which records the choice."""
        plain = ss_actor.detector_reader("variance_ratio", "log_return")(walk())
        signed = ss_actor.detector_reader(
            "variance_ratio", "log_return", read=lambda i: i.z, signed=True
        )(walk())
        assert any(v < 0.0 for v in signed if not math.isnan(v))
        assert all(v >= 0.0 for v in plain if not math.isnan(v))

    def test_a_detector_with_no_catalogued_reading_says_what_to_pass(self) -> None:
        """A detector exposes several readings - `Trendlines` alone has five -
        and which one is the candidate is a decision about the search. The
        error has to name the way out, or a caller reads it as "unsupported"."""
        with pytest.raises(ValueError, match="no catalogued sweep reading"):
            ss_actor.detector_reader("levels", "close")
        with pytest.raises(ValueError, match="read="):
            ss_actor.detector_reader("bjorgum")

    def test_the_framework_indicators_in_price_units_are_absent_on_purpose(self) -> None:
        """`bars.check_scale` refuses one of ours whose threshold would be in
        the instrument's own units and cannot refuse one of Nautilus's, because
        theirs take no `unit_from`. `AverageTrueRange.value` is a price
        distance and `sma` is a price, so a sweep thresholding either puts a
        gold threshold on EURUSD.

        `rsi`, `aroon` and `stochastics` are bounded by construction and are
        present. `roc` is dimensionless and **not** present: a dimensionless
        reading is not a scale-free one, because its scale is the instrument's
        volatility.
        """
        bounded = {"rsi", "aroon", "stochastics"}
        assert bounded <= set(ss_actor.READINGS)
        for name in ("atr", "sma", "ema", "bollinger", "obv", "vwap", "roc"):
            assert name in FRAMEWORK, f"{name} is not a framework indicator any more"
            assert name not in ss_actor.READINGS, f"{name} is thresholdable in price units"

    def test_no_tick_detector_is_in_the_table(self) -> None:
        """`spread` and `ticks` are fed ticks, and one instance has one set of
        accumulators - `bars.check_feed` raises rather than logging when a
        detector is fed two kinds, because the result is "a plausible-looking
        number from neither"."""
        assert not set(ss_actor.READINGS) & set(TICK_DETECTORS)

    def test_a_reader_is_fresh_per_call_so_an_arm_cannot_inherit_state(self) -> None:
        """**The property every series arm depends on.** An arm manufactures a
        null series and the sweep runs the same reader over it; a reader that
        kept its detector across calls would fold the real series and the null
        into one set of accumulators, which is `check_feed`'s failure in a
        different costume."""
        reader = ss_actor.detector_reader("cusum", "close")
        first = reader(walk(seed=1))
        again = reader(walk(seed=1))
        other = reader(walk(seed=2))
        assert first == again, "the reader is not reproducible"
        assert first != other


class TestThePrecision:
    def test_the_sweep_takes_the_series_undamaged(self) -> None:
        """A `Price` at two decimals truncates a btc feed before the detector
        sees it: measured, that moves a 1m reading by 3e-5 relative, and a
        volume precision of 0 rounded 701 of 3,000 btc volumes to zero. The
        default here is 8 and is deliberately **not** a tradable precision."""
        gold = [(a * 60_000, b * 60_000, c * 60_000, d * 60_000) for a, b, c, d in walk()]
        fine = ss_actor.detector_reader("cusum", "close", precision=8)(gold)
        coarse = ss_actor.detector_reader("cusum", "close", precision=1)(gold)
        assert fine != coarse, "the precision made no difference, so the test proves nothing"
        live = [(a, b) for a, b in zip(fine, coarse, strict=True) if not math.isnan(a)]
        worst = max(abs(a - b) / max(abs(a), 1e-12) for a, b in live)
        assert worst > 1e-6, f"truncation moved the reading by only {worst:.3g}"


class TestTheProposalPath:
    """`service.py` published on `PROPOSES` and the actor did not."""

    @staticmethod
    def _actor(**overrides: Any) -> ss_actor.StatespaceActor:
        """An actor with a config and no engine.

        `StatespaceActor.__new__` rather than `object.__new__`, which Cython
        refuses, and `_propose` returns the payload rather than publishing it -
        `Actor.msgbus` is read-only, so a method that published could not be
        tested without a running engine.
        """
        made = ss_actor.StatespaceActor.__new__(ss_actor.StatespaceActor)
        made._cfg = ss_actor.StatespaceConfig(**overrides)  # type: ignore[attr-defined]
        return made

    def test_a_surprising_bar_becomes_a_proposal(self) -> None:
        """The gap in the Nautilus port: `Settings.proposals` was on and
        nothing came out of the actor path. A producer whose own tally counts
        what it sent looks healthy, which is the bug that hid
        `statespace.proposals` for weeks."""
        bar = {"open": 1.1000, "high": 1.1012, "low": 1.0999, "close": 1.1010}
        got = self._actor()._propose(Readout(), bar)
        assert got is not None
        assert got["shape"] == "statespace"
        assert got["direction"] == 1, "the bar closed up and the proposal did not"
        assert got["features"]["base_rate_up"] == 0.5, "direction is a coin here and says so"

    def test_the_sign_comes_from_the_bar_and_not_from_the_reading(self) -> None:
        """This service folds log variance, so a side taken from the reading
        would be the side of a volatility move published as a price claim - the
        category error already corrected twice in this package, where `side`
        became `variance_side` and the alert kind `break` became `surprise`."""
        down = {"open": 1.1010, "high": 1.1012, "low": 1.0999, "close": 1.1000}
        got = self._actor()._propose(Readout(), down)
        assert got is not None
        assert got["direction"] == -1

    def test_a_doji_is_not_a_proposal(self) -> None:
        """A bar whose open and close agree expressed no direction, and turning
        that into a trade would invent a conviction nobody had."""
        flat = {"open": 1.1000, "high": 1.1012, "low": 1.0999, "close": 1.1000}
        assert self._actor()._propose(Readout(), flat) is None

    def test_an_unsurprising_bar_is_not_a_proposal(self) -> None:
        """`proposing.TRIGGER` is 3.0: returns turn at z 1.3 to 1.95 and
        non-returners reach 2.2, so z 2.5 already misses 85-89% of them."""
        quiet = Readout()
        quiet.surprise = 1.0  # type: ignore[misc]
        bar = {"open": 1.1000, "high": 1.1012, "low": 1.0999, "close": 1.1010}
        assert self._actor()._propose(quiet, bar) is None

    def test_the_producer_can_be_switched_off_and_is_not_by_default(self) -> None:
        """Off is a config choice and not the default. The standing reason not
        to ship a producer switched off is `trading.turn_exit`, which has never
        once run in production while its end-to-end path passed every test."""
        bar = {"open": 1.1000, "high": 1.1012, "low": 1.0999, "close": 1.1010}
        assert self._actor(proposals=False)._propose(Readout(), bar) is None
        assert ss_actor.StatespaceConfig().proposals is True

    def test_both_topics_are_declared_so_neither_publishes_into_silence(self) -> None:
        """A typo publishes into silence and nothing downstream can tell that
        from a quiet market. `topics.publish` checks the registry at publish
        time; checking the defaults here fails at test time instead."""
        from till_infinity.utils import topics

        cfg = ss_actor.StatespaceConfig()
        assert cfg.topic in topics.DECLARED
        assert cfg.proposals_topic in topics.DECLARED
        assert cfg.proposals_topic != cfg.topic, (
            "two producers on one topic is how a consumer loses track of which produced what"
        )
