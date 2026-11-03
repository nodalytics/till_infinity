import orjson
import pytest

from till_infinity.prices import INTERVALS, Settings, TradingViewSource
from till_infinity.prices.tradingview import (
    INTERVAL_CODES,
    decode,
    encode,
    extract_bars,
    message,
    symbol_spec,
)


def test_frames_round_trip():
    assert encode("hi") == "~m~2~m~hi"
    assert decode("~m~2~m~hi~m~3~m~bye") == ["hi", "bye"]


def test_decode_handles_a_heartbeat_between_payloads():
    raw = "~m~5~m~~h~42" + encode('{"m":"x","p":[]}')
    assert decode(raw) == ["~h~42", '{"m":"x","p":[]}']


def test_decode_ignores_a_truncated_tail():
    assert decode("~m~2~m~ok~m~99~m~short") == ["ok", "short"]


def test_message_matches_the_servers_length_prefix():
    frame = message("create_series", ["cs", "s1"])
    length, body = frame.removeprefix("~m~").split("~m~", 1)
    assert int(length) == len(body)
    assert orjson.loads(body) == {"m": "create_series", "p": ["cs", "s1"]}


def test_symbol_spec_is_the_leading_equals_form():
    spec = symbol_spec("OANDA", "XAUUSD")
    assert spec.startswith("=")
    assert orjson.loads(spec[1:])["symbol"] == "OANDA:XAUUSD"


def test_extract_bars_reads_a_timescale_update():
    params = [
        "cs_abc",
        {"s1": {"s": [{"i": 0, "v": [60, 1.0, 2.0, 0.5, 1.5, 9.0]}], "t": "s1"}},
    ]
    (bar,) = extract_bars(params)
    assert (bar.time, bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        60,
        1.0,
        2.0,
        0.5,
        1.5,
        9.0,
    )


def test_extract_bars_keeps_volumeless_fx_candles():
    params = ["cs", {"s1": {"s": [{"i": 0, "v": [60, 1.0, 2.0, 0.5, 1.5]}]}}]
    (bar,) = extract_bars(params)
    assert bar.volume is None


def test_extract_bars_skips_malformed_entries():
    params = ["cs", {"s1": {"s": [{"v": [60, 1.0]}, {"v": None}, "junk"]}}, "tail"]
    assert extract_bars(params) == []


def test_every_interval_has_a_resolution_code():
    assert set(INTERVAL_CODES) == set(INTERVALS)


@pytest.mark.parametrize("name", ["2h", "4h"])
def test_partial_bars_are_dropped_by_default(name):
    interval = INTERVALS[name]
    source = TradingViewSource(Settings())
    from till_infinity.prices.models import Bar

    forming = Bar(10_000_000_000, 1, 1, 1, 1, 0)
    closed = Bar(1_600_000_000, 1, 1, 1, 1, 0)
    assert source.keep([closed, forming], interval) == [closed]

    source.settings.include_partial = True
    assert source.keep([closed, forming], interval) == [closed, forming]
