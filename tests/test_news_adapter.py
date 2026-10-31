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
