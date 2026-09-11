"""VIX as a scored member of the volatility ensemble.

`implied.md` is the only positive result in the research folder: over 15 years,
walk-forward, VIX beats a trailing realised estimate by 12-20 points of
R-squared and the naive baseline by +0.26 to +0.43. Its sharpest finding is that
`both` is no better than `vix` alone - VIX **replaces** the historical estimate
rather than adding to it, which is why this is a member of the ensemble rather
than a multiplier bolted on the side.
"""

import math

import pytest

from till_infinity.structures.vol import implied as implied_module
from till_infinity.structures.vol.implied import (
    IMPLIED_FEEDS,
    IMPLIED_INTERVALS,
    Implied,
    bps_for,
)
from till_infinity.structures.vol.volatility import Book


@pytest.fixture
def enabled(monkeypatch):
    """The member ships **off** - `vixseed` measured it last of five on half the
    series - so the tests that exercise it turn it on explicitly."""
    monkeypatch.setattr(implied_module, "ENABLED", True)
    monkeypatch.setattr("till_infinity.structures.vol.volatility.ENABLED", True)


def test_the_conversion_is_what_it_claims_to_be():
    """VIX 20 is 20% annualised sigma. At one day that is 20/sqrt(252) percent,
    which is 1.2599% - 125.99 bps - with no intraday assumption at all.

    Written out rather than recorded from a run: root-time scaling from an
    annualised 30-day number is a modelling assumption even here, and the thing
    most likely to be silently backwards.
    """
    got = bps_for(20.0, "1d")

    by_hand = 20.0 / math.sqrt(252.0) * 100.0  # percent -> bps
    assert by_hand == pytest.approx(125.99, abs=0.01)
    assert got == pytest.approx(by_hand, abs=0.01)

    # A week is five trading days, so the same reading scales by sqrt(5).
    assert bps_for(20.0, "1w") == pytest.approx(by_hand * math.sqrt(5.0), abs=0.1)


def test_a_stale_reading_is_absent_rather_than_carried():
    """If the feed dies the last value keeps voting with full confidence on
    every subsequent bar. Absent from the mapping is what the ensemble already
    handles - members are whatever `observe` was given."""
    held = Implied(max_age=86_400.0)
    held.observe(20.0, when=1000.0)

    assert held.bps("1d", now=1000.0) is not None
    assert held.bps("1d", now=1000.0 + 3_600) is not None
    assert held.bps("1d", now=1000.0 + 200_000) is None, "two days old and still voting"


def test_it_joins_only_the_feeds_and_intervals_it_was_measured_on(enabled):
    """VIX is a 30-day view published daily. Scaling it to a 1m bar assumes a
    flat term structure and no intraday seasonality, and the intraday U-shape is
    large and real - so the scope is a property to assert, not a convention to
    remember."""
    book = Book()

    for interval in ("1m", "5m", "15m", "1h", "4h"):
        assert book.votes_implied("spx500", interval) is False

    for interval in IMPLIED_INTERVALS:
        assert book.votes_implied("spx500", interval) is True

    # And only the four indices it was measured on.
    assert book.votes_implied("eurusd", "1d") is False
    assert book.votes_implied("volatility_75_index", "1d") is False
    for feed in IMPLIED_FEEDS:
        assert book.votes_implied(feed, "1d") is True


def test_weighting_is_on_only_where_vix_votes(enabled):
    """`Ensemble` is per `(feed, interval)`, so error-weighting can be turned on
    for the instances VIX joins without touching the other 49 instruments. That
    blast radius is the thing most likely to be got wrong, so it is asserted
    across a book holding both."""
    book = Book()
    book.implied.observe(20.0, when=1000.0)

    for feed in ("spx500", "eurusd", "volatility_75_index"):
        for interval in ("1m", "1d", "1w"):
            book.of(feed, interval)

    for feed in ("spx500",):
        for interval in IMPLIED_INTERVALS:
            assert book.of(feed, interval)._ensemble.weighted is True

    assert book.of("spx500", "1m")._ensemble.weighted is False
    assert book.of("eurusd", "1d")._ensemble.weighted is False
    assert book.of("volatility_75_index", "1w")._ensemble.weighted is False


def test_the_member_reaches_the_ensemble_and_is_scored(enabled):
    """The whole point of this shape: it is scored against what the bar actually
    did, so a member that is wrong loses its vote without anyone intervening."""
    book = Book()
    vol = book.of("spx500", "1d")

    # The quote has to move or the fit is degenerate - one coefficient cannot be
    # estimated from a column of identical values, and `Fit.predict` says so by
    # returning None rather than by dividing by zero.
    for i in range(400):
        book.implied.observe(15.0 + (i % 20), when=1000.0 + i)
        book.observe_bar("spx500", "1d", 100.0, 101.0, 99.0, 100.5, when=1000.0 + i)

    assert "vix" in vol._ensemble._members, "it has to reach the members mapping"
    # Scored against what the bar actually did, which is the whole argument for
    # this shape: a member that is wrong loses its vote without anyone
    # intervening. Past SCORE_WARMUP it appears in the standings the journal
    # reports, which is where that losing would be visible.
    assert vol._ensemble._score("vix").seen > 0
    assert "vix" in dict(vol._ensemble.standings())


def test_a_seeded_score_is_a_prior_and_not_a_floor():
    """`SCORE_WARMUP` is 60, which at daily bars is three months before VIX earns
    any weight - so the scores are seeded from history. A seed the live
    observations contradict has to be able to lose."""
    from till_infinity.structures.vol.consensus_vol import Ensemble

    held = Ensemble(weighted=True)
    held.seed("vix", error=0.05, seen=200.0)
    assert held.accuracy("vix") == pytest.approx(0.95, abs=0.01)

    # Consistently wrong from here: the seeded accuracy has to decay.
    for _ in range(400):
        held.observe({"vix": 100.0})
        held.settle(1.0)
    assert held.accuracy("vix") < 0.5, "a seed that is wrong must be able to lose"


def test_the_fit_recovers_a_known_premium():
    """The member's whole content is one coefficient. Given a series where
    realised is exactly `0.6 * quote + 10`, the fit has to return that - and if
    it cannot, nothing built on it means anything."""
    from till_infinity.structures.vol.implied import Fit

    fit = Fit()
    for i in range(300):
        quote = 100.0 + i % 50
        fit.observe(quote, 0.6 * quote + 10.0)

    assert fit.predict(200.0) == pytest.approx(130.0, abs=0.01)


def test_the_fit_does_not_vote_until_it_means_something():
    """A coefficient from thirty bars is a number, not an estimate. Absent
    rather than guessing, so the ensemble simply has four members until then."""
    from till_infinity.structures.vol.implied import MIN_FIT, Fit

    fit = Fit()
    for i in range(MIN_FIT - 1):
        fit.observe(100.0 + i % 7, 60.0 + i % 7)
    assert fit.predict(120.0) is None

    fit.observe(100.0, 60.0)
    assert fit.predict(120.0) is not None


def test_the_fit_learns_from_a_bar_only_after_being_scored_on_it(enabled):
    """The same rule `Ensemble.settle` follows: a bar may not inform the
    forecast it is about to judge."""
    book = Book()
    book.implied.observe(20.0, when=1000.0)
    fit = book.implied_fit("spx500", "1d")

    assert fit.n == 0
    book.observe_bar("spx500", "1d", 100.0, 101.0, 99.0, 100.5, when=1000.0)
    assert fit.n == 1, "one bar in, one observation - and the forecast came first"


def test_it_reports_the_fitted_value_and_not_the_quote(enabled):
    """Raw VIX scores worse than predicting the mean on four of eight series.
    What reaches the ensemble must be the de-biased number."""
    from till_infinity.structures.vol.implied import bps_for

    book = Book()
    for i in range(400):
        book.implied.observe(15.0 + (i % 20), when=1000.0 + i)
        book.observe_bar("spx500", "1d", 100.0, 101.0, 99.0, 100.4, when=1000.0 + i)

    book.implied.observe(20.0, when=1400.0)
    got = book.implied_bps("spx500", "1d", now=1400.0)
    assert got is not None
    assert got != pytest.approx(bps_for(20.0, "1d"), abs=1.0), "that is the raw quote"


async def test_the_quote_is_polled_and_reaches_the_book(enabled, monkeypatch):
    """Built and never fed is how a member ships inert: `Implied.level` stays
    zero, `fresh` is false, and it is absent from every ensemble while looking
    entirely configured."""
    from till_infinity.structures.vol import implied as mod

    monkeypatch.setattr(mod, "latest", lambda *_a, **_k: 17.29)
    watcher = _watcher()

    await watcher._read_implied()

    assert watcher.engine.vol.implied.level == pytest.approx(17.29)
    assert watcher.engine.vol.implied.fresh(now=__import__("time").time())


async def test_a_source_that_stops_leaves_the_last_quote_standing(enabled, monkeypatch):
    """The failure that matters for a daily series: it looks alive long after it
    dies. Silence must not overwrite, and `MAX_AGE` is what retires the reading
    rather than a zero written over it."""
    from till_infinity.structures.vol import implied as mod

    watcher = _watcher()
    monkeypatch.setattr(mod, "latest", lambda *_a, **_k: 17.29)
    await watcher._read_implied()

    monkeypatch.setattr(mod, "latest", lambda *_a, **_k: None)
    watcher._implied_at = 0.0
    await watcher._read_implied()

    assert watcher.engine.vol.implied.level == pytest.approx(17.29), "not zeroed"


async def test_polling_respects_its_own_interval(enabled, monkeypatch):
    """VIX is published daily. Asking Yahoo on every bus message would be rude
    and would learn nothing."""
    from till_infinity.structures.vol import implied as mod

    calls = []
    monkeypatch.setattr(mod, "latest", lambda *_a, **_k: calls.append(1) or 17.29)
    watcher = _watcher()

    await watcher._read_implied()
    await watcher._read_implied()
    await watcher._read_implied()

    assert len(calls) == 1, "one read, then the interval holds"


def _watcher():
    from till_infinity.bus import Bus
    from till_infinity.structures.config import Settings
    from till_infinity.structures.service import Watcher

    return Watcher(Bus(), settings=Settings(warm=False, journalling=False))


async def test_it_says_it_is_live_once_per_process_not_once_per_level(enabled, monkeypatch):
    """`Implied.level` **persists**. Restored at 17.17 from the previous
    container, `level > 0` was already true at start, so the line inferring
    "first quote" from it never printed - and "is this running" became
    unanswerable from the log, which is the one thing the line was for."""
    from till_infinity.structures.vol import implied as mod

    monkeypatch.setattr(mod, "latest", lambda *_a, **_k: 17.29)
    watcher = _watcher()
    # As restored: a level already standing from a previous process.
    watcher.engine.vol.implied.observe(17.17, when=1.0)

    assert watcher._implied_said is False
    await watcher._read_implied()
    assert watcher._implied_said is True, "it has to say so even with a level held"

    watcher._implied_at = 0.0
    await watcher._read_implied()
    assert watcher._implied_said is True, "and only once"


def test_the_seed_file_is_shipped_and_shaped_right():
    """`MIN_FIT` is 250 observations and production gets **one daily bar a day**,
    so without a seed the member is about a year from voting. The file is 6KB,
    derived from twenty years of public Yahoo data, and ships with the package
    so a fresh container has it without extra infrastructure."""
    from till_infinity.structures.vol.implied import IMPLIED_FEEDS, IMPLIED_INTERVALS, seeds

    got = seeds()

    assert set(got) == set(IMPLIED_FEEDS)
    for feed, intervals in got.items():
        assert set(intervals) == set(IMPLIED_INTERVALS), feed
        for interval, part in intervals.items():
            assert part["fit"]["n"] > 250, f"{feed} {interval} would not warm anything"
            assert "vix" in part["scores"]


def test_seeding_gives_the_member_a_vote_immediately(enabled):
    """The whole point: a fresh book with no history must already be able to
    price the member, rather than waiting a year of daily bars."""
    from till_infinity.structures.vol.volatility import Book

    cold = Book()
    cold.implied.observe(17.2, when=1000.0)
    assert cold.implied_bps("spx500", "1d", now=1000.0) is None, "the premise"

    warm = Book()
    warm.seed_implied()
    warm.implied.observe(17.2, when=1000.0)

    got = warm.implied_bps("spx500", "1d", now=1000.0)
    assert got is not None
    assert 0 < got < 200, "a de-biased daily sigma in bps"

    # And the ensemble starts weighted by what history said, not by nothing.
    assert warm.of("spx500", "1d")._ensemble.accuracy("vix") > 0.5


def test_seeding_never_overwrites_what_was_learned_live(enabled):
    """A seed is a prior. Applying it on every restart would make live
    observations unable to accumulate past one container's lifetime, which is
    the failure `Ensemble.seed`'s own docstring warns about in reverse."""
    from till_infinity.structures.vol.volatility import Book

    book = Book()
    book.seed_implied()
    fit = book.implied_fit("spx500", "1d")
    before = fit.n

    for i in range(50):
        fit.observe(100.0 + i, 50.0 + i)
    grown = fit.n
    assert grown == before + 50

    book.seed_implied()
    assert book.implied_fit("spx500", "1d").n == grown, "the seed must not reset it"


async def test_the_seed_is_applied_once_before_the_first_quote(enabled, monkeypatch):
    """Built and never called is how the last three features shipped inert. The
    seed runs on the poll rather than in `__init__`, because the engine may be
    restored afterwards and seeding a book about to be replaced seeds nothing."""
    from till_infinity.structures.vol import implied as mod

    monkeypatch.setattr(mod, "latest", lambda *_a, **_k: 17.29)
    watcher = _watcher()

    assert watcher.engine.vol.implied_fit("spx500", "1d").n == 0
    await watcher._read_implied()

    assert watcher.engine.vol.implied_fit("spx500", "1d").n > 250
    assert watcher._implied_seeded is True

    # And it can price the member immediately, which is the whole point.
    assert (
        watcher.engine.vol.implied_bps("spx500", "1d", now=watcher.engine.vol.implied.at)
        is not None
    )


def test_the_quote_fetch_cannot_hang():
    """It sits in the structures **message loop**, and CI runs with no network -
    its workflow says "No network in CI: every test runs against fakes".

    Without a timeout the fetch blocks forever: a Deploy job sat `in_progress`
    for **fifty minutes** on 2026-09-11, blocking every deploy behind it, and it
    read as a failure when it was a hang. A quote is worth less than a trading
    loop, so it gets a short leash."""
    import inspect

    from till_infinity.structures.vol import implied as mod

    assert mod.FETCH_TIMEOUT > 0
    source = inspect.getsource(mod.latest)
    assert "timeout=" in source, "the library call must carry one"

    # And the caller keeps its own ceiling, because a library's timeout is the
    # library's promise rather than the loop's guarantee.
    from till_infinity.structures import service

    assert "wait_for" in inspect.getsource(service.Watcher._read_implied)


async def test_a_hanging_quote_does_not_stop_the_loop(enabled, monkeypatch):
    """The behavioural half: a fetch that never returns must leave the reading
    alone and let the loop carry on, not take the service with it."""
    import time as clock

    from till_infinity.structures.vol import implied as mod

    monkeypatch.setattr(mod, "FETCH_TIMEOUT", 0.02)
    # Short on purpose. `asyncio.to_thread` cannot be cancelled, so `wait_for`
    # frees the **loop** and leaves the thread running to completion - which is
    # the right trade (the service keeps working) and a real limitation (a hung
    # fetch still holds a worker until it returns). A 30s sleep here proved the
    # same point and held the whole suite at teardown for 30 seconds.
    monkeypatch.setattr(mod, "latest", lambda *_a, **_k: clock.sleep(0.4))

    watcher = _watcher()
    watcher.engine.vol.implied.observe(17.17, when=1.0)

    await watcher._read_implied()

    assert watcher.engine.vol.implied.level == pytest.approx(17.17), "the last quote stands"
