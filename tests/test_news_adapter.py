"""The news adapter, and the lookahead it exists to prevent.

An economic calendar entry exists long before its number does, so a stored row
replayed at its scheduled time hands a strategy the outcome before it
happened. That is the same mistake `drawing.gaps` made - emitting only the
gaps that went on to be filled, which read +0.50R a trade as a bias.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from till_infinity.adapters.news.data import (
    CalendarEvent,
    Importance,
    MacroObservation,
    Stage,
)

NS = 1_700_000_000 * 1_000_000_000


def event(stage: Stage, **kwargs) -> CalendarEvent:
    base = {
        "event_id": "nfp",
        "title": "Nonfarm Payrolls",
        "country": "US",
        "importance": Importance.HIGH,
        "ts_event": NS,
        "ts_init": NS,
        "forecast": 180.0,
        "previous": 150.0,
    }
    base.update(kwargs)
    return CalendarEvent(stage=stage, **base)


class TestTheTwoStagesAreTheLookaheadGuard:
    def test_a_scheduled_entry_carrying_an_actual_is_refused(self):
        """Refused rather than blanked: silently dropping it would hide a
        broken producer, which is how a leak survives a review."""
        with pytest.raises(ValueError, match="lookahead"):
            event(Stage.SCHEDULED, actual=254.0)

    def test_a_scheduled_entry_has_no_surprise(self):
        assert event(Stage.SCHEDULED).surprise is None

    def test_a_released_entry_has_one(self):
        assert event(Stage.RELEASED, actual=254.0).surprise == pytest.approx(74.0)

    def test_a_released_entry_without_a_forecast_has_none(self):
        """No forecast, no surprise - the surprise is the deviation, not the
        level."""
        assert event(Stage.RELEASED, actual=254.0, forecast=None).surprise is None

    def test_the_forecast_and_previous_survive_both_stages(self):
        """A scheduled entry is not empty: the forecast is what was knowable,
        and it is what a strategy positions against."""
        for stage, extra in ((Stage.SCHEDULED, {}), (Stage.RELEASED, {"actual": 254.0})):
            got = event(stage, **extra)
            assert got.forecast == 180.0
            assert got.previous == 150.0


class TestEmbargoIsHighImportanceOnly:
    @pytest.mark.parametrize(
        ("importance", "expected"),
        [(Importance.HIGH, True), (Importance.MEDIUM, False), (Importance.LOW, False)],
    )
    def test_only_high_importance_embargoes(self, importance, expected):
        """Standing aside for every calendar entry is standing aside always,
        which is a strategy nobody chose."""
        assert event(Stage.SCHEDULED, importance=importance).embargoed is expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (0, Importance.LOW),
            (1, Importance.MEDIUM),
            (2, Importance.HIGH),
            (None, Importance.LOW),
            ("junk", Importance.LOW),
            (99, Importance.LOW),
        ],
    )
    def test_importance_coerces_rather_than_raising(self, raw, expected):
        assert Importance.of(raw) is expected


class TestMacroObservationsCarryPublicationTime:
    def test_the_stamp_is_when_it_could_have_been_acted_on(self):
        """An observation's period and its publication date are weeks apart,
        and only one of them is tradable."""
        got = MacroObservation(
            series="CPIAUCSL", value=3.1, period="2026-09", ts_event=NS, ts_init=NS
        )
        assert got.ts_event == NS
        assert got.period == "2026-09"

    def test_it_renders_readably(self):
        got = MacroObservation(
            series="DGS10", value=4.25, period="2026-10-30", ts_event=NS, ts_init=NS, unit="%"
        )
        assert "DGS10" in repr(got)
        assert "4.25" in repr(got)


class TestHistoryIsServedPointInTime:
    @staticmethod
    def _store(rows: list[dict]) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "news.db"
        with sqlite3.connect(tmp) as db:
            db.execute(
                "CREATE TABLE events (id TEXT, source TEXT, title TEXT, country TEXT, "
                "time REAL, announced REAL, importance INT, actual TEXT, forecast TEXT, "
                "previous TEXT, unit TEXT, period TEXT)"
            )
            for row in rows:
                db.execute(
                    "INSERT INTO events VALUES (:id, :source, :title, :country, :time, "
                    ":announced, :importance, :actual, :forecast, :previous, :unit, :period)",
                    row,
                )
        return tmp

    def _client(self, path: Path):
        """A client with just enough wired to exercise the history path."""
        from till_infinity.adapters.news.client import NewsDataClient, NewsDataClientConfig

        client = NewsDataClient.__new__(NewsDataClient)
        client._cfg = NewsDataClientConfig(db_path=str(path), minimum_importance="low")
        client._floor = Importance.LOW
        client._published = set()
        # The real client resolves one path in `__init__` - the config's, or
        # `NEWS_DB` - and both reads and writes go through it.
        client._db = str(path)
        # The real client always has one; a bare instance does not, and the
        # error *handler* uses it - so without this the test exercising "a
        # missing store does not raise" raised in the handler itself.
        return client

    def _row(self, **over) -> dict:
        row = {
            "id": "nfp",
            "source": "cal",
            "title": "Nonfarm Payrolls",
            "country": "US",
            "time": 1_700_000_000.0,
            "announced": 1_699_000_000.0,
            "importance": 2,
            "actual": "254",
            "forecast": "180",
            "previous": "150",
            "unit": "k",
            "period": "2026-09",
        }
        row.update(over)
        return row

    def test_a_released_entry_yields_two_stages_in_order(self):
        client = self._client(self._store([self._row()]))
        got = client._stages(self._row(), Importance.HIGH)
        assert [e.stage for e in got] == [Stage.SCHEDULED, Stage.RELEASED]
        assert got[0].ts_event < got[1].ts_event
        assert got[0].actual is None
        assert got[1].actual == pytest.approx(254.0)

    def test_an_unreleased_entry_yields_only_the_announcement(self):
        client = self._client(self._store([self._row(actual=None)]))
        got = client._stages(self._row(actual=None), Importance.HIGH)
        assert [e.stage for e in got] == [Stage.SCHEDULED]

    def test_a_missing_announcement_time_is_placed_before_the_release(self):
        """The exact announcement time matters less than it being *before* the
        release, which is what stops the leak."""
        client = self._client(self._store([self._row(announced=None)]))
        got = client._stages(self._row(announced=None), Importance.HIGH)
        assert got[0].ts_event < got[1].ts_event

    def test_an_entry_with_no_release_time_is_dropped(self):
        client = self._client(self._store([self._row(time=0)]))
        assert client._stages(self._row(time=0), Importance.HIGH) == []

    def test_numbers_survive_commas_and_percent_signs(self):
        client = self._client(self._store([self._row()]))
        got = client._stages(self._row(actual="1,234", forecast="5%"), Importance.HIGH)
        assert got[1].actual == pytest.approx(1234.0)
        assert got[1].forecast == pytest.approx(5.0)

    def test_the_importance_floor_filters(self):
        client = self._client(self._store([self._row()]))
        client._floor = Importance.HIGH
        assert client._carried(Importance.LOW, "US") is False
        assert client._carried(Importance.HIGH, "US") is True

    def test_a_missing_store_returns_nothing_rather_than_raising(self):
        """A node that cannot read the calendar must still start: no news is
        recoverable, a node that will not boot is not.

        Against the extracted function rather than the method, because
        `Component._log` is read-only - which is why the reading was pulled
        out of the client in the first place.
        """
        from till_infinity.adapters.news.client import read_rows

        window = type("W", (), {"start": None, "end": None, "limit": 10})()
        rows, error = read_rows("/nonexistent/news.db", "events", window)
        assert rows == []
        assert error

    def test_an_unknown_table_is_refused_rather_than_interpolated(self):
        from till_infinity.adapters.news.client import read_rows

        window = type("W", (), {"start": None, "end": None, "limit": 10})()
        rows, error = read_rows("/tmp/x.db", "events; DROP TABLE events", window)
        assert rows == []
        assert "unknown table" in error

    def test_no_store_configured_is_empty_without_an_error(self):
        from till_infinity.adapters.news.client import read_rows

        window = type("W", (), {"start": None, "end": None, "limit": 10})()
        assert read_rows(None, "events", window) == ([], "")


class TestTheSweepPublishesEachStageOnceAndOnlyWhenKnowable:
    """The live half of the same guard `_stages` carries.

    A sweep that published every entry it could still see would make an
    embargo fire continuously - the failure shape of an alert per touched bar
    - and one that published a stage before its time would be the lookahead
    `_stages` exists to prevent, reintroduced by the loop around it.
    """

    NOW = 1_700_000_100.0

    def _client(self, rows: list[dict]):
        """`Component._clock` is read-only, which is why `_sweep` takes the
        time as an argument - the same reason `read_rows` is a function."""
        history = TestHistoryIsServedPointInTime()
        client = history._client(history._store(rows))
        published: list[CalendarEvent] = []
        client._handle_data = published.append
        return client, published

    def _row(self, **over) -> dict:
        return TestHistoryIsServedPointInTime()._row(**over)

    async def test_a_released_entry_publishes_both_stages(self):
        client, published = self._client([self._row()])
        await client._sweep(self.NOW)
        assert [e.stage for e in published] == [Stage.SCHEDULED, Stage.RELEASED]

    async def test_an_unreleased_entry_publishes_only_its_announcement(self):
        """The forecast is knowable; the number is not, and will not be until
        the release."""
        ahead = self._row(actual=None, time=self.NOW + 86_400, announced=self.NOW - 86_400)
        client, published = self._client([ahead])
        await client._sweep(self.NOW)
        assert [e.stage for e in published] == [Stage.SCHEDULED]

    async def test_an_entry_announced_in_the_future_publishes_nothing(self):
        """Not yet knowable at all. The row is in the store because we poll a
        forward window, not because anybody could have traded it."""
        later = self._row(announced=self.NOW + 60, time=self.NOW + 120)
        client, published = self._client([later])
        await client._sweep(self.NOW)
        assert published == []

    async def test_a_second_sweep_publishes_nothing_again(self):
        client, published = self._client([self._row()])
        await client._sweep(self.NOW)
        await client._sweep(self.NOW)
        assert len(published) == 2


class TestCollectingWritesWhatTheProvidersReturned:
    """`fetch_into` is a function for the same reason `read_rows` is one: a
    store and a list of sources, not a client, so the collecting half runs
    against a fake provider and a temporary file instead of a kernel."""

    async def test_a_dead_provider_is_counted_and_the_others_still_land(self, tmp_path):
        from till_infinity.adapters.news.client import fetch_into
        from till_infinity.adapters.news.sources import Batch, Event, Settings, Source
        from till_infinity.adapters.news.sources.source import PermanentError
        from till_infinity.adapters.news.store import SqliteStore

        class Fake(Source):
            name = "fake"

            def __init__(self, settings, batch=None, fail=False):
                super().__init__(settings)
                self.batch, self.fail = batch or Batch(), fail

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return None

            async def poll(self):
                if self.fail:
                    raise PermanentError("404")
                return self.batch

        settings = Settings(data_dir=tmp_path)
        event = Event(source="cal", id="cpi", title="CPI m/m", country="US", time=1.0)
        async with SqliteStore(tmp_path / "news.db") as store:
            harvest = await fetch_into(
                store,
                [Fake(settings, fail=True), Fake(settings, Batch(events=[event]))],
                retries=1,
            )
            assert harvest.failed == 1
            assert harvest.events.inserted == 1
            # Re-serving the same window writes nothing: the store dedups, so
            # a provider that repeats itself costs one no-op write.
            again = await fetch_into(store, [Fake(settings, Batch(events=[event]))])
            assert again.events.touched == 0


class TestTheStoreTheClientWritesIsTheStoreItReads:
    """The join between the two halves, and it was broken when they met.

    `read_rows` bounded an observation window on a `published` column and
    `store.py` has none - it records the *period* a figure describes. SQLite
    answered "no such column", the client logged a warning and served an empty
    history, which looks exactly like a store with no macro rows in it. The
    window is now bounded on a column the table actually has.
    """

    async def test_macro_written_by_the_store_comes_back_out(self, tmp_path):
        from till_infinity.adapters.news.client import (
            NewsDataClient,
            NewsDataClientConfig,
            read_rows,
        )
        from till_infinity.adapters.news.sources import Observation
        from till_infinity.adapters.news.store import SqliteStore

        at = 1_700_000_000.0
        async with SqliteStore(tmp_path / "news.db") as store:
            await store.write_observations(
                [
                    Observation(
                        source="imf",
                        series="USA..M",
                        time=at,
                        value=253e9,
                        period="2026-M07",
                    )
                ]
            )
        window = type("W", (), {"start": at - 86_400, "end": at + 86_400, "limit": 10})()
        rows, error = read_rows(str(tmp_path / "news.db"), "observations", window)
        assert not error
        assert [r["series"] for r in rows] == ["USA..M"]

        client = NewsDataClient.__new__(NewsDataClient)
        client._cfg = NewsDataClientConfig(db_path=str(tmp_path / "news.db"))
        client._db = str(tmp_path / "news.db")
        (observation,) = client._macro_history(window)
        assert observation.value == pytest.approx(253e9)
        assert observation.period == "2026-M07"
        assert observation.ts_event == int(at * 1e9)
