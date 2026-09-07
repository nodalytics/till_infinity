"""What every service needs and none of them owns."""

from __future__ import annotations

import sqlite3

import pytest

from till_infinity.shared import db, env

# ------------------------------------------------------------------ readers


def test_a_bad_number_falls_back_rather_than_raising(monkeypatch, caplog):
    """The divergence this module exists to end. `agents`, `structures` and
    `trading` caught ValueError and defaulted silently; `news` and `prices`
    did `float(raw) if raw else default`, which raises - and a raise at import
    time takes the service down before it starts. Same typo, opposite
    outcomes, decided by which prefix you mistyped."""
    monkeypatch.setenv("TILL_TEST_NUMBER", "abc")

    with caplog.at_level("WARNING"):
        assert env.number("TILL_TEST_NUMBER", 2.5) == 2.5

    assert "TILL_TEST_NUMBER" in caplog.text, "a silent default hides the typo"


def test_a_bad_whole_number_falls_back_loudly(monkeypatch, caplog):
    monkeypatch.setenv("TILL_TEST_WHOLE", "seven")

    with caplog.at_level("WARNING"):
        assert env.whole("TILL_TEST_WHOLE", 7) == 7

    assert "TILL_TEST_WHOLE" in caplog.text


def test_a_float_written_where_an_int_was_wanted_is_read_not_discarded(monkeypatch):
    """An env file is a text file, and `10.0` there is someone saying ten."""
    monkeypatch.setenv("TILL_TEST_WHOLE", "10.0")

    assert env.whole("TILL_TEST_WHOLE", 3) == 10


def test_unset_and_empty_are_the_same_thing(monkeypatch):
    """`NAME=` is how people comment a setting out, and treating it as "set to
    empty" means a blank line changes behaviour."""
    monkeypatch.delenv("TILL_TEST_STR", raising=False)
    assert env.env("TILL_TEST_STR", "fallback") == "fallback"

    monkeypatch.setenv("TILL_TEST_STR", "   ")
    assert env.env("TILL_TEST_STR", "fallback") == "fallback"
    assert env.number("TILL_TEST_STR", 1.5) == 1.5


def test_a_flag_set_to_a_typo_is_on(monkeypatch):
    """The direction that leaves a service running, which is the rule
    docs/trading.md already states for the strategy list."""
    monkeypatch.setenv("TILL_TEST_FLAG", "yes-please")
    assert env.flag("TILL_TEST_FLAG", False) is True

    for off in ("0", "false", "NO", "off", "  Off  "):
        monkeypatch.setenv("TILL_TEST_FLAG", off)
        assert env.flag("TILL_TEST_FLAG", True) is False


def test_a_flag_that_is_unset_takes_its_default(monkeypatch):
    monkeypatch.delenv("TILL_TEST_FLAG", raising=False)

    assert env.flag("TILL_TEST_FLAG", True) is True
    assert env.flag("TILL_TEST_FLAG", False) is False


def test_a_comma_list_survives_a_hand_edited_file(monkeypatch):
    """`a,,b` and a trailing comma are what an edited env file looks like, and
    an empty name reaching a lookup is a silent miss rather than an error."""
    monkeypatch.setenv("TILL_TEST_LIST", " gold , , btc,  ")

    assert env.names("TILL_TEST_LIST") == ("gold", "btc")


def test_an_empty_list_takes_the_default(monkeypatch):
    monkeypatch.setenv("TILL_TEST_LIST", " , ")

    assert env.names("TILL_TEST_LIST", ("gold",)) == ("gold",)


# ------------------------------------------------------------------ the store


def test_a_connection_carries_the_settled_pragmas(tmp_path):
    """Three stores held these four lines identically. Three copies that agree
    today are three that can disagree tomorrow, and the way that shows up -
    one collector locking under load while its neighbour does not - is
    expensive to trace back to a missing PRAGMA."""
    conn = db.connect(tmp_path / "nested" / "test.db")

    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10_000
    conn.close()


def test_the_parent_directory_is_made(tmp_path):
    target = tmp_path / "a" / "b" / "test.db"

    db.connect(target).close()

    assert target.exists()


def test_a_read_only_connection_cannot_write(tmp_path):
    """Enforced at the driver rather than by remembering: these files are the
    evidence every measurement in research/ is computed from."""
    path = tmp_path / "test.db"
    writer = db.connect(path)
    writer.execute("CREATE TABLE t (x INTEGER)")
    writer.commit()
    writer.close()

    reader = db.read_only(path)
    assert reader.execute("SELECT count(*) FROM t").fetchone()[0] == 0
    with pytest.raises(sqlite3.OperationalError):
        reader.execute("INSERT INTO t VALUES (1)")
    reader.close()
