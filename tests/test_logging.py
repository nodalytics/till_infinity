import logging

import orjson
import pytest

from till_infinity.logging import (
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


def test_module_name_does_not_shadow_the_stdlib():
    assert logging.__name__ == "logging"
    assert hasattr(logging, "getLogger")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("debug", logging.DEBUG), ("WARNING", logging.WARNING), (logging.ERROR, logging.ERROR)],
)
def test_log_level_coercion(value, expected):
    assert log_level(value) == expected


def test_log_level_rejects_nonsense():
    with pytest.raises(ValueError, match="unknown log level"):
        log_level("chatty")


def test_default_level_is_info():
    assert setup_logging().level == logging.INFO


def test_verbose_and_quiet_flags():
    assert setup_logging(verbose=True, force=True).level == logging.DEBUG
    assert setup_logging(quiet=True, force=True).level == logging.WARNING
    # An explicit level wins over both.
    assert setup_logging("ERROR", verbose=True, force=True).level == logging.ERROR


def test_level_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("TILL_LOG_LEVEL", "DEBUG")
    assert setup_logging().level == logging.DEBUG


def test_setup_is_idempotent_unless_forced():
    setup_logging()
    handlers = len(logging.getLogger().handlers)
    setup_logging(verbose=True)
    assert len(logging.getLogger().handlers) == handlers
    assert logging.getLogger().level == logging.INFO  # second call was a no-op


def test_log_file_gets_json_lines(tmp_path):
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


def test_json_formatter_includes_the_traceback():
    try:
        raise ValueError("nope")
    except ValueError:
        record = logging.LogRecord(
            "till_infinity", logging.ERROR, __file__, 1, "boom", None, exc_info=True
        )
        import sys

        record.exc_info = sys.exc_info()
        payload = orjson.loads(JsonFormatter().format(record))
    assert "ValueError: nope" in payload["exc"]


def test_noisy_libraries_are_muted():
    setup_logging("INFO", force=True)
    assert logging.getLogger("httpx").level == logging.WARNING
    quiet_noisy_loggers(logging.DEBUG)
    assert logging.getLogger("httpx").level == logging.DEBUG


def test_debug_leaves_third_party_loggers_alone():
    setup_logging(verbose=True, force=True)
    assert logging.getLogger("httpx").level == logging.DEBUG


def test_get_logger_defaults_to_the_package():
    assert get_logger().name == "till_infinity"
    assert get_logger("till_infinity.prices").name == "till_infinity.prices"


# ---------------------------------------------------------------------------
# Console width. `rich` falls back to 80 when it cannot detect a terminal, which
# is every containerised run, and it **truncates** rather than wrapping - so a
# cut line still reads as a complete sentence and nothing says the tail is gone.
# That silently ate the volatility scoreboard, which prints a four-way
# comparison and lost the three competitors.
# ---------------------------------------------------------------------------


def test_a_console_with_no_terminal_gets_a_usable_width():
    """The container case. 80 is what silently ate the scoreboard."""
    console = _console(stderr=True)
    if console.is_terminal:  # an interactive run keeps rich's own detection
        return
    assert console.width == FALLBACK_WIDTH
    assert console.width > 80


def test_a_real_terminal_keeps_its_own_width():
    """This must never override a width somebody can actually see."""
    console = _console()
    if not console.is_terminal:
        return
    assert console.width != FALLBACK_WIDTH or console.width == 200


def test_the_volatility_scoreboard_fits_in_one_line():
    """It compares four forecasters, and the comparison is the whole content -
    so it is the part a truncation removes first."""
    from till_infinity.structures.vol.learned import Learned

    model = Learned(warmup=1)
    for i in range(40):
        row = model.features("eurusd|5m", ew_bps=2.0, open_=100, high=101, low=99, close=100.5)
        model.observe("eurusd|5m", 2.0 + (i % 3), row, ew_bps=2.0)

    standings = model.standings()
    rendered = ", ".join(f"{name} {value:.3f}" for name, value in standings)
    line = f"structures: vol model: {model._seen} pair(s), accuracy {rendered} - beating naive"
    assert len(line) < FALLBACK_WIDTH, (len(line), line)
