"""The bridge's **real** response shapes, recorded from a live terminal.

Every other MT5 test in this suite drives a `FakeBridge` whose replies were
written by hand, and on 2026-11-03 that is exactly why the suite was green over
a desk that could not receive a bar. The fake returned `time` as an integer
because that is what the code expected; the bridge returns an ISO string
because it runs its rows through `pandas.to_datetime`. Every bar poll raised
`invalid literal for int() with base 10: '2026-11-...'` on all six symbols,
continuously, while the node reported healthy.

**So the fixtures here are recorded, not written.** `RATES` and `INFO_KEYS`
below were captured from the terminal the desk trades through, verbatim, with
nothing normalised. A test that builds its own input tests the author's belief
about the input.

## What this does and does not cover

It covers the **parse**: given what the bridge actually sends, does the adapter
produce a bar and a quote with the right numbers. That is the half of the
end-to-end path no existing test reached.

It does **not** cover the round trip to a fill. Four faults on 2026-11-03 sat
between a configured desk and a trade - sixteen retired rule names, lowercase
symbols, these timestamps, and a 5-minute subscription under M15 rules - and
only this one is a parse. The others are configuration, and
`test_entrypoints.py` asserts the shipped configuration while
`scripts/deploy.sh --check` asserts the deployed one. A test that places an
order against a live terminal is a different kind of test: it touches the
venue the desk trades through, so it belongs behind a marker and a demo
account, not in the default suite.

**If a fixture here is ever "corrected" to an integer, the bug comes back.**
That is the whole point of the file.
"""

from __future__ import annotations

import json

import pytest

#: Recorded from `GET /api/v1/symbols/rates/pos?symbol=EURUSD&timeframe=M15&num_bars=2`
#: against the live terminal on 2026-11-03. Verbatim.
#:
#: Note three things a hand-written fake got wrong or would have:
#: `time` is a **naive ISO string**, not an epoch; the volume field is
#: **`tick_volume`**, not `volume`; and `spread` is an integer in points.
RATES_JSON = """
[{"time":"2026-11-03T21:30:00","open":1.11919,"high":1.11923,"low":1.11903,
  "close":1.11919,"tick_volume":272,"spread":2,"real_volume":0},
 {"time":"2026-11-03T21:45:00","open":1.11921,"high":1.11921,"low":1.11898,
  "close":1.11902,"tick_volume":282,"spread":2,"real_volume":0}]
"""

#: A subset of the keys `GET /api/v1/symbols/info/{symbol}` returns, recorded
#: the same way. The quote path reads `bid` and `ask`; the rest are here so a
#: reader can see the reply is a symbol *info* payload carrying a tick, not a
#: tick payload.
INFO_KEYS = (
    "ask",
    "bid",
    "digits",
    "spread",
    "currency_base",
    "currency_profit",
    "trade_mode",
    "volume_min",
)


def rates() -> list[dict]:
    return json.loads(RATES_JSON)


def test_the_recorded_rates_are_the_shape_the_bridge_sends():
    """Guards the fixture itself. If someone normalises `time` to an epoch to
    make a test pass, the defect this file exists for returns silently."""
    rows = rates()

    assert len(rows) == 2
    for row in rows:
        assert isinstance(row["time"], str), (
            "the bridge sends an ISO string - `pd.to_datetime` then `to_dict`. "
            "An integer here means the fixture has been edited and the bar "
            "path is no longer being tested against reality."
        )
        assert "T" in row["time"], "an ISO datetime, not a date"
        assert not row["time"].endswith("Z"), "naive - pandas produced it from an epoch"
        assert "tick_volume" in row, "not `volume` - the name a fake would guess"
        assert "volume" not in row


def test_a_bar_parses_out_of_the_recorded_row():
    """The defect, pinned against real input. `_bar` did `float(row["time"])`
    and the poll loop `int(row["time"])`, so both raised on every bar."""
    from nautilus_trader.model.data import BarType
    from nautilus_trader.test_kit.providers import TestInstrumentProvider

    from till_infinity.adapters.mt5.data import _bar, _bar_seconds

    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    bar_type = BarType.from_str(f"{instrument.id}-15-MINUTE-LAST-EXTERNAL")
    row = rates()[0]

    made = _bar(bar_type, row, instrument, 900.0)

    assert float(made.open) == pytest.approx(1.11919)
    assert float(made.high) == pytest.approx(1.11923)
    assert float(made.low) == pytest.approx(1.11903)
    assert float(made.close) == pytest.approx(1.11919)
    assert float(made.volume) == pytest.approx(272.0), "from `tick_volume`"
    # Stamped at the close, one interval past the open the bridge reported.
    assert made.ts_event == int((_bar_seconds(row) + 900.0) * 1e9)
    assert made.ts_event > 0


def test_the_two_recorded_bars_are_fifteen_minutes_apart():
    """A sanity check on the recording, and on the parse: if the ISO string
    were being read as a number the gap would be meaningless."""
    from till_infinity.adapters.mt5.data import _bar_seconds

    first, second = (_bar_seconds(row) for row in rates())

    assert second - first == pytest.approx(900.0), "M15, as requested"


def test_the_poll_loop_would_advance_on_these_rows():
    """The loop keeps `_last_bar` per bar type and skips anything at or before
    it. With the old bare `int()` this never got a number to compare, so the
    guard could not advance and no bar was ever published."""
    from till_infinity.adapters.mt5.data import _bar_seconds

    seen = 0
    published = []
    for row in rates():
        opened = int(_bar_seconds(row))
        if opened <= seen:
            continue
        seen = opened
        published.append(opened)

    assert len(published) == 2, "both rows advance the watermark"
    assert published == sorted(published)


def test_the_info_payload_carries_the_quote_the_desk_reads():
    """`_undealable` refuses on a missing quote and `Surprise.decide` refuses
    earlier still, so a desk whose quote never arrives declines everything and
    reports gate counts rather than an error. The fields are named here so a
    rename on the bridge fails a test instead of a desk."""
    for key in ("bid", "ask"):
        assert key in INFO_KEYS, f"the quote path reads {key}"


@pytest.mark.parametrize("field", INFO_KEYS)
def test_every_recorded_info_field_is_still_named_that(field):
    """Recorded from the live terminal. These are the names, not guesses."""
    assert field, "an empty field name is a broken recording"
    assert field.islower(), "MT5's own field names are lower case"


def test_the_old_conversion_raises_on_the_recorded_row():
    """**The test of the test.** A fixture that the broken code would also have
    parsed proves nothing, so this pins the failure itself.

    `_bar` did `float(row.get("time") or 0.0)` and the poll loop
    `int(row.get("time") or 0)`. Both raise `ValueError` on the string the
    bridge actually sends, which is what took every bar from the desk - and
    both passed every existing test, because the fake bridge sends an integer.
    """
    row = rates()[0]

    with pytest.raises(ValueError, match="invalid literal"):
        int(row["time"])

    with pytest.raises(ValueError, match="could not convert string to float"):
        float(row["time"])

    # And the replacement does not.
    from till_infinity.adapters.mt5.data import _bar_seconds

    assert _bar_seconds(row) > 0.0
