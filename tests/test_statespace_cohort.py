"""Cross-sectional pooling: orientation, agreement, and effective bets.

The orientation tests are the ones that matter. `regime-granularity.md`
measured the fx majors reading drift agreement **z -10.0** - below the null -
purely because EURUSD and USDJPY carry USD on opposite sides, while the same
family read |correlation| z +178.6. A silent `+1` on a member whose sign means
the opposite thing is how a cohort reports the strongest shared drift in the
cache as an absence of one.
"""

from __future__ import annotations

from till_infinity.actors.statespace import cohort


class TestOrient:
    def test_reference_as_base_rises_with_it(self) -> None:
        assert cohort.orient("USDJPY", "USD") == 1
        assert cohort.orient("USDCAD", "USD") == 1

    def test_reference_as_quote_falls_with_it(self) -> None:
        assert cohort.orient("EURUSD", "USD") == -1
        assert cohort.orient("GBPUSD", "USD") == -1

    def test_a_feed_without_the_reference_takes_no_side(self) -> None:
        """Not `+1`. A non-member's sign means nothing, so it must not vote."""
        assert cohort.orient("Germany_40", "USD") == 0
        assert cohort.orient("XAUUSD", "JPY") == 0

    def test_no_reference_orients_everything_positive(self) -> None:
        assert cohort.orient("BTCUSD", None) == 1
        assert cohort.orient("Germany_40", None) == 1

    def test_the_same_feed_orients_differently_per_cohort(self) -> None:
        """USDJPY is long USD and short JPY. One feed, two opposite signs."""
        assert cohort.orient("USDJPY", "USD") == 1
        assert cohort.orient("USDJPY", "JPY") == -1


class TestAgreement:
    def test_unanimous_is_one(self) -> None:
        assert cohort.agreement_of((1, 1, 1, 1)) == 1.0

    def test_an_even_split_is_below_chance(self) -> None:
        # 3 up and 3 down: 3 + 3 = 6 agreeing pairs of 15.
        assert cohort.agreement_of((1, 1, 1, -1, -1, -1)) == 6 / 15

    def test_a_four_three_split_matches_the_measured_fx_majors_value(self) -> None:
        """0.429 is what perfect USD sharing gives a split-convention family."""
        got = cohort.agreement_of((1, 1, 1, 1, -1, -1, -1))
        assert abs(got - 9 / 21) < 1e-12

    def test_zero_signs_are_excluded_not_counted_as_up(self) -> None:
        assert cohort.agreement_of((1, 1, 0, 0)) == 1.0

    def test_fewer_than_two_live_signs_is_zero(self) -> None:
        assert cohort.agreement_of((1,)) == 0.0
        assert cohort.agreement_of((0, 0, 1)) == 0.0


class TestIndependent:
    def test_unanimous_members_are_one_bet(self) -> None:
        assert abs(cohort.independent_of(6, 1.0) - 1.0) < 1e-12

    def test_chance_agreement_leaves_every_member_independent(self) -> None:
        assert abs(cohort.independent_of(6, 0.5) - 6.0) < 1e-12

    def test_below_chance_is_floored_rather_than_credited(self) -> None:
        """A cohort must never claim more independent bets than it has members."""
        assert cohort.independent_of(6, 0.2) == 6.0
        assert cohort.independent_of(6, 0.0) == 6.0

    def test_one_member_is_one_bet(self) -> None:
        assert cohort.independent_of(1, 1.0) == 1.0

    def test_partial_agreement_sits_between(self) -> None:
        got = cohort.independent_of(6, 0.75)
        assert 1.0 < got < 6.0


class TestPool:
    def _pool(self, *, oriented: bool = False) -> cohort.Pool:
        return cohort.Pool(oriented=oriented)

    def _fill(self, pool: cohort.Pool, feeds, rate, when=5.0, interval="1m"):
        for feed in feeds:
            pool.observe(feed, interval, rate=rate, rate_sd=0.001, stretch=0.2, when=when)

    def test_a_feed_can_belong_to_two_cohorts(self) -> None:
        got = self._pool().cohorts_of("USDJPY")
        assert "fx majors" in got
        assert "jpy crosses" in got

    def test_the_interval_is_part_of_the_key(self) -> None:
        """A 1m rate and a 5m rate are not members of one pool."""
        pool = self._pool()
        self._fill(pool, ("EURUSD", "GBPUSD", "AUDUSD"), 0.01, interval="1m")
        assert pool.read("fx majors", "1m", now=5.0) is not None
        assert pool.read("fx majors", "5m", now=5.0) is None

    def test_volatility_is_pooled_unsigned_by_default(self) -> None:
        """EURUSD and USDJPY variance rising is the same event. No inversion."""
        pool = self._pool()
        self._fill(pool, ("EURUSD", "USDJPY", "USDCAD"), 0.01)
        got = pool.read("fx majors", "1m", now=5.0)
        assert got is not None
        assert got.agreement == 1.0
        assert abs(got.independent - 1.0) < 1e-12
        assert got.rate > 0

    def test_orientation_applies_only_when_asked_for(self) -> None:
        """With `oriented`, a shared leg on opposite sides splits the cohort."""
        pool = self._pool(oriented=True)
        self._fill(pool, ("EURUSD", "USDJPY", "USDCAD"), 0.01)
        got = pool.read("fx majors", "1m", now=5.0)
        assert got is not None
        # EURUSD inverts, so one of three opposes: 1 of 3 pairs agree.
        assert got.agreement == 1 / 3

    def test_too_few_live_members_publishes_nothing(self) -> None:
        pool = self._pool()
        self._fill(pool, ("EURUSD", "GBPUSD"), 0.01)
        assert pool.read("fx majors", "1m", now=5.0) is None

    def test_stale_members_do_not_prop_up_agreement(self) -> None:
        pool = self._pool()
        self._fill(pool, ("EURUSD", "GBPUSD", "AUDUSD"), 0.01, when=0.0)
        assert pool.read("fx majors", "1m", now=0.0) is not None
        assert pool.read("fx majors", "1m", now=cohort.FRESH_SECONDS + 1.0) is None

    def test_a_zero_rate_member_takes_no_side_and_is_not_live(self) -> None:
        pool = self._pool()
        self._fill(pool, ("EURUSD", "GBPUSD"), 0.01)
        self._fill(pool, ("AUDUSD",), 0.0)
        assert pool.read("fx majors", "1m", now=5.0) is None

    def test_the_tighter_member_dominates_the_pooled_rate(self) -> None:
        pool = self._pool()
        pool.observe("USDJPY", "1m", rate=0.010, rate_sd=0.0001, stretch=0.0, when=1.0)
        pool.observe("USDCAD", "1m", rate=0.002, rate_sd=0.010, stretch=0.0, when=1.0)
        pool.observe("USDCHF", "1m", rate=0.002, rate_sd=0.010, stretch=0.0, when=1.0)
        got = pool.read("fx majors", "1m", now=1.0)
        assert got is not None
        assert got.rate > 0.009
        assert got.rate_sd < 0.0001

    def test_a_zero_spread_cohort_falls_back_to_an_equal_mean(self) -> None:
        """`rate_sd` 0.0 means unstated, not certain."""
        pool = self._pool()
        for feed in ("EURUSD", "GBPUSD", "AUDUSD"):
            pool.observe(feed, "1m", rate=0.004, rate_sd=0.0, stretch=0.5, when=1.0)
        got = pool.read("fx majors", "1m", now=1.0)
        assert got is not None
        assert abs(got.rate - 0.004) < 1e-12
        assert got.rate_sd == 0.0
        assert abs(got.stretch - 0.5) < 1e-12

    def test_disagreeing_members_report_more_independent_bets(self) -> None:
        pool = self._pool()
        self._fill(pool, ("EURUSD", "GBPUSD"), 0.01)
        self._fill(pool, ("USDJPY", "USDCAD"), -0.01)
        got = pool.read("fx majors", "1m", now=5.0)
        assert got is not None
        assert got.live == 4
        assert got.agreement == 2 / 6
        assert abs(got.independent - 4.0) < 1e-12

    def test_every_published_key_is_prefixed(self) -> None:
        pool = self._pool()
        self._fill(pool, ("EURUSD", "GBPUSD", "AUDUSD"), 0.01)
        got = pool.read("fx majors", "1m", now=5.0)
        assert got is not None
        card = got.to_dict()
        assert all(k == "cohort" or k.startswith("cohort_") for k in card)

    def test_nothing_published_names_a_direction(self) -> None:
        """`direction-is-closed-not-just-null`. This publishes exposure.

        A field called `up`, `side` or `drift` would be read as a price claim on
        a service that folds log variance, and the measured value of the pooled
        direction is 2% of a spread. The same ban already applies to the
        service's alert line.
        """
        pool = self._pool()
        self._fill(pool, ("EURUSD", "GBPUSD", "AUDUSD"), 0.01)
        got = pool.read("fx majors", "1m", now=5.0)
        assert got is not None
        banned = ("up", "down", "side", "bullish", "bearish", "long", "short", "signal", "drift")
        for key in got.to_dict():
            assert key.removeprefix("cohort_") not in banned

    def test_readings_skips_cohorts_that_are_not_ready(self) -> None:
        pool = self._pool()
        self._fill(pool, ("USDJPY", "USDCAD", "USDCHF"), 0.01)
        got = pool.readings("1m", now=5.0)
        assert [r.cohort for r in got] == ["fx majors"]
