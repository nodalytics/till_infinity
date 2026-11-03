import time
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from till_infinity.prices import INTERVALS
from till_infinity.prices.yahoo import RESAMPLE_FROM, YahooSource, resample, start_time, to_bars

NOW = datetime(2026, 8, 12, tzinfo=UTC)


def frame(rows: int, *, freq: str = "1h", tz: str | None = "UTC") -> pd.DataFrame:
    index = pd.date_range("2026-08-10", periods=rows, freq=freq, tz=tz)
    return pd.DataFrame(
        {
            "Open": range(rows),
            "High": [v + 2 for v in range(rows)],
            "Low": [v - 2 for v in range(rows)],
            "Close": [v + 1 for v in range(rows)],
            "Volume": [10] * rows,
        },
        index=index,
    )


def test_start_time_is_clamped_to_yahoos_retention():
    # A minute bar older than a week does not exist, however many are asked for.
    assert start_time(INTERVALS["1m"], 100_000, now=NOW) == NOW - timedelta(days=7)
    # Daily history is uncapped.
    assert start_time(INTERVALS["1d"], 10, now=NOW) < NOW - timedelta(days=17)


def test_to_bars_uses_utc_epoch_open_times():
    bars = to_bars(frame(3))
    assert [b.time for b in bars] == [
        int(datetime(2026, 8, 10, h, tzinfo=UTC).timestamp()) for h in range(3)
    ]
    assert bars[0].open == 0.0
    assert bars[0].volume == 10.0


def test_to_bars_treats_a_naive_index_as_utc():
    assert to_bars(frame(1, tz=None))[0].time == int(datetime(2026, 8, 10, tzinfo=UTC).timestamp())


def test_to_bars_of_an_empty_frame():
    assert to_bars(pd.DataFrame()) == []


@pytest.mark.parametrize(("name", "size"), [("2h", 2), ("4h", 4)])
def test_resample_builds_the_missing_intervals_from_1h(name, size):
    out = resample(frame(8), name)
    assert len(out) == 8 // size
    first = out.iloc[0]
    assert first["Open"] == 0
    assert first["High"] == size + 1  # highest of the source bars in the window
    assert first["Close"] == size  # last close in the window
    assert first["Volume"] == 10 * size


def test_resampled_bars_are_aligned_to_the_utc_grid():
    bars = to_bars(resample(frame(8), "4h"))
    assert all(bar.time % INTERVALS["4h"].seconds == 0 for bar in bars)


def test_supported_covers_every_interval_via_resampling():
    source = YahooSource.__new__(YahooSource)
    assert {i.name for i in source.supported(list(INTERVALS.values()))} == set(INTERVALS)
    assert set(RESAMPLE_FROM) <= set(INTERVALS)


@pytest.mark.asyncio
async def test_shaping_a_frame_does_not_block_the_event_loop():
    """Everything runs in one process, so on-loop CPU starves every consumer.

    `_download` was already threaded, but `resample` and `to_bars` were not,
    and they are the expensive half: pandas over the whole frame, then a Python
    loop building a dict per row. On the box that starved the structures
    consumer for the length of every backfill - its queue filled and the bus
    dropped quotes at eight a second - and because a backfill runs on every
    startup, each deploy took the level pipeline down for the length of the
    backfill rather than the length of the restart.
    """
    import asyncio

    source = YahooSource.__new__(YahooSource)
    big = frame(40_000, freq="1min")
    cache = {"1h": big}  # pre-seeded, so no download is attempted

    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            ticks += 1
            await asyncio.sleep(0.001)

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)  # let it start
    bars = await source._series("X", INTERVALS["4h"], 50, cache)
    beat.cancel()

    assert bars, "the shaping produced nothing, so the test proves nothing"
    assert len(bars) <= 50
    assert ticks > 1, "the loop never ran while the frame was being shaped"


def _shape_the_old_way(frame, source_name, interval_name, bars):
    """What `_shape` used to do: convert everything, then discard most of it."""
    if source_name != interval_name:
        frame = resample(frame, interval_name)
    return to_bars(frame)[-bars:]


@pytest.mark.parametrize("holes", [0, 1, 40])
def test_only_the_bars_that_are_kept_are_converted(holes):
    """Converting ten thousand rows to keep five hundred, on the startup path.

    The slice cannot be taken first without care: `to_bars` drops rows with a
    NaN open, so the last N rows are not the last N bars and the count comes up
    short. Dropping those in pandas first makes the two equivalent, and the
    test is the equivalence rather than the speed.
    """
    import numpy as np

    source = YahooSource.__new__(YahooSource)
    big = frame(3_000, freq="1min")
    if holes:
        # Gaps scattered through the tail, which is where the slice lands.
        big.iloc[-holes * 2 :: 2, big.columns.get_loc("Open")] = np.nan

    new = source._shape(big.copy(), "1m", "1m", 500)
    old = _shape_the_old_way(big.copy(), "1m", "1m", 500)

    assert [(b.time, b.open, b.close) for b in new] == [(b.time, b.open, b.close) for b in old], (
        "the fast path and the old path disagree"
    )
    assert len(new) == 500


def test_a_frame_shorter_than_asked_for_returns_what_there_is():
    source = YahooSource.__new__(YahooSource)
    assert len(source._shape(frame(20, freq="1min"), "1m", "1m", 500)) == 20


def test_a_frame_with_no_open_column_is_not_an_error():
    import pandas as pd

    source = YahooSource.__new__(YahooSource)
    assert source._shape(pd.DataFrame({"Close": [1.0]}), "1m", "1m", 5) == []


class TestAShutMarketIsNotAskedEverySweep:
    """**Yahoo answers a closed market exactly as it answers a delisted one.**

    "possibly delisted; no price data found" covers both, so a weekend put
    eight index and futures symbols into a retry loop that ran on every sweep
    for two days. It was the dominant line in the container's log and pure
    work on two cores that `structures` needs - the same starvation the
    threading fix above exists for, arrived at from the other side.
    """

    def _job(self, ticker="^NDX", interval="1m"):
        from till_infinity.prices.models import Symbol
        from till_infinity.prices.source import Job

        return Job(
            source="yahoo",
            feed="us100",
            symbol=Symbol("YAHOO", ticker),
            intervals=(INTERVALS[interval],),
        )

    def _source(self, fail_with=None):
        from till_infinity.prices.source import PermanentError

        source = YahooSource.__new__(YahooSource)
        source.settings = type("S", (), {"yahoo_request_gap": 0.0, "yahoo_concurrency": 1})()
        calls: list[str] = []

        async def series(ticker, interval, bars, cache):
            calls.append(ticker)
            if fail_with:
                raise PermanentError(fail_with)
            return []

        source._series = series  # type: ignore[method-assign]
        source.keep = lambda candles, interval: candles  # type: ignore[method-assign]
        return source, calls

    async def _sink(self, key, candles):
        from till_infinity.prices.models import WriteResult

        return WriteResult()

    @pytest.mark.asyncio
    async def test_the_second_sweep_does_not_ask_again(self):
        import till_infinity.prices.yahoo as y

        y.forget_quiet()
        source, calls = self._source(fail_with="possibly delisted; no price data found")
        job = self._job()
        await source.fetch(job, 100, self._sink)
        await source.fetch(job, 100, self._sink)
        await source.fetch(job, 100, self._sink)
        assert calls == ["^NDX"], f"asked {len(calls)} times; the backoff did nothing"

    @pytest.mark.asyncio
    async def test_the_wait_widens_rather_than_repeating_one_delay(self):
        import till_infinity.prices.yahoo as y

        y.forget_quiet()
        source, _ = self._source(fail_with="no price data found")
        job = self._job()
        waits = []
        for _ in range(4):
            # Pretend the wait has elapsed, so the next attempt is allowed.
            if ("^NDX", "1m") in y._QUIET:
                _until, strikes = y._QUIET[("^NDX", "1m")]
                y._QUIET[("^NDX", "1m")] = (0.0, strikes)
            await source.fetch(job, 100, self._sink)
            until, _strikes = y._QUIET[("^NDX", "1m")]
            waits.append(round(until - time.time()))
        assert waits == sorted(waits), f"the wait must widen, got {waits}"
        assert waits[-1] > waits[0], f"the wait never widened: {waits}"

    @pytest.mark.asyncio
    async def test_it_is_capped_so_a_reopening_market_is_found_again(self):
        import till_infinity.prices.yahoo as y

        y.forget_quiet()
        source, _ = self._source(fail_with="no price data found")
        job = self._job()
        for _ in range(20):
            if ("^NDX", "1m") in y._QUIET:
                _u, strikes = y._QUIET[("^NDX", "1m")]
                y._QUIET[("^NDX", "1m")] = (0.0, strikes)
            await source.fetch(job, 100, self._sink)
        until, strikes = y._QUIET[("^NDX", "1m")]
        left = until - time.time()
        assert left <= y.QUIET_MAX_S + 1, f"waiting {left:.0f}s, past the cap"
        assert strikes >= 20

    @pytest.mark.asyncio
    async def test_a_symbol_that_answers_is_forgotten(self):
        """Monday has to undo Saturday, or the cap is the only way back."""
        import till_infinity.prices.yahoo as y

        y.forget_quiet()
        y._QUIET[("^NDX", "1m")] = (0.0, 7)
        source, calls = self._source()  # answers normally
        await source.fetch(self._job(), 100, self._sink)
        assert ("^NDX", "1m") not in y._QUIET, "a symbol that answered is still being skipped"
        assert calls == ["^NDX"]
