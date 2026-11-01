"""The one place that decides where a log record goes, and the width it gets.

Two failures, both silent, both of them things a reader could not tell from
working output.

The first is **truncation**. `rich` falls back to 80 columns when it cannot
measure a terminal - which is every containerised run - and it *truncates*
rather than wrapping, so a cut line still reads as a complete sentence and
nothing says the tail is gone. That ate the volatility scoreboard: a four-way
forecaster comparison that printed the first competitor and lost the other
three, and nobody noticed, because `restored models (...)` and `changes: ...
over 274 feed(s) -` were losing their tails the same way. `FALLBACK_WIDTH` is
200 and applies only when there is no terminal to ask, so it can never
override a width somebody can actually see.

The second is **configuration that does not take**. `setup_logging` is
idempotent on purpose - the second caller gets the first caller's handlers, not
a second copy of every record - which also means a later call asking for
`DEBUG` is a no-op unless it says `force`. A collector left running for a week
writes JSON lines to a file, and a record missing its level or its `extra`
fields is one nobody can filter.

This module is named `logging` inside a package that imports `logging`, which
is safe only because Python 3 imports are absolute. The first test here holds
that, because the failure if it ever stopped being true is unbounded
recursion at import time.
"""

import io
import logging

import orjson
import pytest

from till_infinity.utils.logging import (
    FALLBACK_WIDTH,
    JsonFormatter,
    _console,
    get_logger,
    log_level,
    quiet_noisy_loggers,
    reset_logging,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _clean_logging():
    reset_logging()
    yield
    reset_logging()
    logging.getLogger().setLevel(logging.WARNING)


def test_our_logging_module_does_not_shadow_the_stdlib_inside_the_package():
    """Asserted from inside our module, which is the only place it could fail.

    This was two lines asserting `logging.__name__ == "logging"` and
    `hasattr(logging, "getLogger")` against the name *this test file*
    imported - which is the standard library whatever our module is called,
    so it could not have failed. The name that matters is the one bound inside
    `till_infinity/utils/logging.py`: if that ever resolved to itself,
    `logging.getLogger` would recurse and the package would not import.
    """
    from till_infinity.utils import logging as ours

    assert ours is not logging
    assert ours.logging is logging
    assert ours.logging.handlers is logging.handlers
    # And the loggers handed out are the standard library's, not ours.
    assert isinstance(get_logger("till_infinity.test"), logging.Logger)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("debug", logging.DEBUG), ("WARNING", logging.WARNING), (logging.ERROR, logging.ERROR)],
)
def test_a_level_is_taken_in_any_case_or_already_as_a_number(value, expected):
    """Levels arrive from an env file, a flag and a caller, in that order of
    carelessness."""
    assert log_level(value) == expected


def test_an_unknown_level_is_refused_rather_than_defaulted():
    """A typo that fell back to `INFO` would read as working, and the one time
    somebody set `TILL_LOG_LEVEL` is the time they wanted something else."""
    with pytest.raises(ValueError, match="unknown log level"):
        log_level("chatty")


def test_the_default_level_is_info():
    assert setup_logging().level == logging.INFO


def test_an_explicit_level_beats_both_flags():
    """`--verbose --quiet` is a reachable pair of flags, and so is a level
    passed alongside either."""
    assert setup_logging(verbose=True, force=True).level == logging.DEBUG
    assert setup_logging(quiet=True, force=True).level == logging.WARNING
    assert setup_logging("ERROR", verbose=True, force=True).level == logging.ERROR


def test_the_level_comes_from_the_environment(monkeypatch):
    """Which is how a container is turned up without a redeploy."""
    monkeypatch.setenv("TILL_LOG_LEVEL", "DEBUG")
    assert setup_logging().level == logging.DEBUG


def test_a_second_setup_is_a_no_op_unless_it_says_force():
    """**Both halves are the point.** Two handlers on the root logger write
    every record twice, which doubles a week of collector output; and a second
    call that silently won the argument would mean the level an operator set
    depends on import order.
    """
    setup_logging()
    handlers = len(logging.getLogger().handlers)
    setup_logging(verbose=True)
    assert len(logging.getLogger().handlers) == handlers
    assert logging.getLogger().level == logging.INFO


def test_a_file_record_carries_everything_needed_to_filter_it(tmp_path):
    """The message interpolated, the level, the logger and the `extra` fields.

    A collector runs for a week and the file is read afterwards with `jq`. A
    record holding `"fetched %d bars"` and a separate args tuple, or dropping
    `symbol`, is a line nobody can select on.
    """
    path = tmp_path / "logs" / "till.log"
    setup_logging("INFO", log_file=path, force=True)
    get_logger("till_infinity.test").info("fetched %d bars", 42, extra={"symbol": "OANDA:XAUUSD"})
    for handler in logging.getLogger().handlers:
        handler.flush()

    record = orjson.loads(path.read_text().splitlines()[-1])
    assert record["msg"] == "fetched 42 bars"
    assert record["level"] == "INFO"
    assert record["logger"] == "till_infinity.test"
    assert record["symbol"] == "OANDA:XAUUSD"
    assert record["ts"].startswith("20")


def test_an_exception_reaches_the_file_with_its_traceback():
    """A JSON line is one record, so a traceback that went to the formatter's
    default place went nowhere - and an error log with no stack is an error
    nobody can locate."""
    try:
        raise ValueError("nope")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "till_infinity", logging.ERROR, __file__, 1, "boom", None, exc_info=True
        )
        record.exc_info = sys.exc_info()
        payload = orjson.loads(JsonFormatter().format(record))
    assert "ValueError: nope" in payload["exc"]


def test_third_party_libraries_are_muted_at_our_level_and_not_theirs():
    """`httpx` logs a line per request. At `INFO` over a week that is the
    whole file."""
    setup_logging("INFO", force=True)
    assert logging.getLogger("httpx").level == logging.WARNING
    quiet_noisy_loggers(logging.DEBUG)
    assert logging.getLogger("httpx").level == logging.DEBUG


def test_debug_leaves_third_party_loggers_alone():
    """Somebody asking for `DEBUG` is debugging, and the request `httpx` made
    is usually the thing they are looking for."""
    setup_logging(verbose=True, force=True)
    assert logging.getLogger("httpx").level == logging.DEBUG


def test_get_logger_defaults_to_the_package():
    assert get_logger().name == "till_infinity"
    assert get_logger("till_infinity.prices").name == "till_infinity.prices"


# ---------------------------------------------------------------- console width


def test_a_console_with_nothing_attached_gets_the_fallback_width(monkeypatch):
    """The containerised case, and the one that ate the scoreboard.

    Both branches are forced here rather than detected. They used to be
    guarded by `if console.is_terminal: return`, so under `pytest` - where
    output is captured and nothing is a terminal - the pair asserted the
    fallback and nothing else, and in an interactive run they asserted
    nothing at all.
    """
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setattr("sys.stderr", io.StringIO())

    console = _console(stderr=True)
    assert console.is_terminal is False
    assert console.width == FALLBACK_WIDTH
    assert console.width > 80, "80 is rich's own fallback, and what truncated"


def test_a_real_terminal_keeps_the_width_it_reports(monkeypatch):
    """This must never override a width somebody can actually see.

    `COLUMNS` is how `rich` is told a width when it has a terminal, so 123 is
    an arbitrary number chosen to be nothing else in this file - and
    deliberately not 200, because the assertion that used to stand here read
    `width != FALLBACK_WIDTH or width == 200`, which with `FALLBACK_WIDTH` at
    200 is true for every width there is.
    """
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("COLUMNS", "123")
    monkeypatch.setattr("sys.stderr", io.StringIO())

    console = _console(stderr=True)
    assert console.is_terminal is True
    assert console.width == 123
    assert console.width != FALLBACK_WIDTH


# **`test_the_volatility_scoreboard_fits_in_one_line` left with its
# subject.** It built a `structures.vol.learned.Learned` to check the
# four-forecaster comparison fits a terminal line, and `structures/` is
# retired. The console-width behaviour it leaned on is covered by the two
# tests above; what went is the scoreboard, not the width handling.
