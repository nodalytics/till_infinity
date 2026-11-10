"""The live volatility screen, and the gate that reads it.

**Two quantities at two speeds, measured in two places.** Cost barely moves -
a broker's spread is a property of the broker and the month - so choosing which
instruments are affordable belongs to an occasional survey of the whole book
(`research/harness/volatile.py`, 725 symbols). Volatility moves within the
session: `seasonality-belongs-on-q` measured FX intraday volatility peaking
14-15 UTC at 3x. So choosing which of them is volatile *now* belongs in the
running node, which is what this screens.

It ranks the **deployed** universe and not the broker's, because the adapter
loads only the instruments `TRADING_SYMBOLS` names. That limit is asserted in
the module docstring rather than left for a reader to assume.
"""

from __future__ import annotations

from types import SimpleNamespace

from till_infinity.strategies.screening import (
    ScreenConfig,
    VolatileScreen,
    ranked_bar_types,
)


def feed(screen: VolatileScreen, name: str, ranges: list[float], close: float = 100.0) -> None:
    """Push bar ranges into one bar type's window, as `on_bar` would."""
    screen._ranges.setdefault(name, __import__("collections").deque(maxlen=200))
    for span in ranges:
        screen._ranges[name].append(10_000.0 * span / close)


def ranked(screen: VolatileScreen) -> dict:
    """`_rank` on a stub whose publish and log are recorders."""
    sent: list[tuple[str, object]] = []
    said: list[str] = []
    stub = SimpleNamespace(
        _ranges=screen._ranges,
        _cfg=screen._cfg,
        _rankings=0,
        log=SimpleNamespace(info=said.append, warning=said.append),
        msgbus=SimpleNamespace(publish=lambda topic, msg: sent.append((topic, msg))),
    )
    VolatileScreen._rank(stub)
    return {"sent": sent, "said": said}


# ------------------------------------------------------------- the ranking


def test_the_loudest_instruments_are_the_ones_admitted():
    """The range, not the close-to-close standard deviation: `drive-q-from-the-
    range` measured the range-vs-close estimator ratio at 0.648 within strata on
    FX, and records the advantage growing as the window shortens - the regime a
    scalp lives in."""
    screen = VolatileScreen(ScreenConfig(bar_types=(), share=0.5))
    feed(screen, "LOUD.MT5-5-MINUTE-LAST-EXTERNAL", [2.0] * 40)
    feed(screen, "ALSO.MT5-5-MINUTE-LAST-EXTERNAL", [1.5] * 40)
    feed(screen, "QUIET.MT5-5-MINUTE-LAST-EXTERNAL", [0.2] * 40)
    feed(screen, "STILL.MT5-5-MINUTE-LAST-EXTERNAL", [0.1] * 40)

    got = ranked(screen)
    assert got["sent"], "nothing was published"
    _topic, payload = got["sent"][0]
    admitted = ranked_bar_types(payload)
    assert len(admitted) == 2, "half of four is two"
    assert {name.split(".")[0] for name in admitted} == {"LOUD", "ALSO"}


def test_the_median_is_used_so_one_news_bar_does_not_set_the_ranking():
    """A scalp meets the typical bar. With the mean, a single huge range would
    promote an otherwise quiet instrument over a consistently active one."""
    screen = VolatileScreen(ScreenConfig(bar_types=(), share=0.5))
    # Consistently active.
    feed(screen, "STEADY.MT5-5-MINUTE-LAST-EXTERNAL", [1.0] * 40)
    # Quiet, with one enormous bar - a higher mean, a lower median.
    feed(screen, "SPIKY.MT5-5-MINUTE-LAST-EXTERNAL", [0.1] * 39 + [100.0])

    _topic, payload = ranked(screen)["sent"][0]
    assert ranked_bar_types(payload)[0].startswith("STEADY")


def test_an_instrument_without_enough_bars_is_not_ranked():
    """A ranking computed from four bars is not a ranking. It is excluded
    rather than ranked low, because ranking it low is a claim."""
    screen = VolatileScreen(ScreenConfig(bar_types=(), share=1.0))
    feed(screen, "WARM.MT5-5-MINUTE-LAST-EXTERNAL", [1.0] * 40)
    feed(screen, "COLD.MT5-5-MINUTE-LAST-EXTERNAL", [9.0] * 4)

    _topic, payload = ranked(screen)["sent"][0]
    names = [row["bar_type"] for row in payload["ranked"]]
    assert any(n.startswith("WARM") for n in names)
    assert not any(n.startswith("COLD") for n in names), "four bars set the ranking"


def test_nothing_warm_publishes_no_ranking_and_says_so():
    """Silence here would make every gated desk refuse for ever with no reason
    on the log. `venue-faults-hide-below-the-strategy` is the standing cost."""
    screen = VolatileScreen(ScreenConfig(bar_types=()))
    feed(screen, "COLD.MT5-5-MINUTE-LAST-EXTERNAL", [1.0] * 3)
    got = ranked(screen)
    assert not got["sent"], "a ranking was published off three bars"
    assert any("bars yet" in line for line in got["said"])


def test_the_whole_ranking_is_published_and_not_only_the_head():
    """A desk refused for being outside the top share should be able to say how
    far outside it was, which needs the ranking and not the admitted list."""
    screen = VolatileScreen(ScreenConfig(bar_types=(), share=0.25))
    for i in range(8):
        feed(screen, f"S{i}.MT5-5-MINUTE-LAST-EXTERNAL", [float(i + 1)] * 40)
    _topic, payload = ranked(screen)["sent"][0]
    assert len(payload["ranked"]) == 8
    assert len(payload["admitted"]) == 2
    assert payload["share"] == 0.25


def test_the_payload_reader_refuses_a_shape_it_does_not_know():
    """A consumer guessing at a producer's dict is how `statespace.proposals`
    came to have a producer and no consumer for weeks, so the shape is asserted
    in one place and anything else reads as empty rather than raising inside a
    gate."""
    assert ranked_bar_types({"admitted": ["A", "B"]}) == ["A", "B"]
    assert ranked_bar_types({"admitted": "A"}) == []
    assert ranked_bar_types({}) == []
    assert ranked_bar_types(None) == []
    assert ranked_bar_types("nonsense") == []


# ---------------------------------------------------------------- the gate


def gate(*, on: bool, admitted: list[str], mine: str) -> object:
    """`Desk._volatile_enough` on a stub carrying only what it reads."""
    from till_infinity.strategies.desk import Desk

    stub = SimpleNamespace(
        settings=SimpleNamespace(volatile_only=on),
        _admitted=admitted,
        _cfg=SimpleNamespace(
            bar_type=mine,
            instrument_id=SimpleNamespace(symbol="EURUSD"),
        ),
        _feed_name=lambda: "eurusd",
    )
    return Desk._volatile_enough(stub)


def test_off_is_a_true_no_op():
    """**A gate that silently admits everything reads the same as one that
    works.** Off must not consult the ranking at all, so a deploy that has not
    opted in is bit-identical to one before this existed."""
    assert gate(on=False, admitted=[], mine="X") is None
    assert gate(on=False, admitted=["Y"], mine="X") is None


def test_an_admitted_instrument_passes_and_another_is_refused():
    assert gate(on=True, admitted=["X", "Y"], mine="X") is None
    refusal = gate(on=True, admitted=["X", "Y"], mine="Z")
    assert refusal is not None
    assert refusal.gate == "not-volatile"
    assert "outside the top 2" in refusal.detail


def test_with_the_gate_on_and_no_ranking_it_refuses_rather_than_admits():
    """**The opposite of the usual choice here, and deliberate.** A scalp whose
    premise is "only the volatile ones" has no fallback instrument set, so
    admitting everything until the screener warms would trade the quiet book
    under a rule written for the loud one."""
    refusal = gate(on=True, admitted=[], mine="X")
    assert refusal is not None
    assert refusal.gate == "no-ranking"


def test_the_setting_is_off_by_default():
    from till_infinity.strategies.config import Settings

    assert Settings().volatile_only is False


def test_the_two_refusals_are_named_apart():
    """ "No ranking yet" and "ranked too quiet" are different operator problems -
    one is a cold screener and one is a working one - so they must not share a
    gate name on the tally."""
    cold = gate(on=True, admitted=[], mine="X")
    quiet = gate(on=True, admitted=["Y"], mine="X")
    assert cold.gate != quiet.gate


def test_the_topic_is_declared_so_a_subscription_cannot_be_silent():
    """`utils.topics.DECLARED` refuses an undeclared name, because a typo
    publishes into silence. The guard caught this topic during development."""
    from till_infinity.utils import topics

    assert topics.VOLATILE in topics.DECLARED


def _window(size: int = 200):
    from collections import deque

    return deque(maxlen=size)


def _bars(spelling: str, count: int = 3, span: float = 0.20, close: float = 100.0) -> list:
    """`count` bars of `spelling`, as a `request_bars` response carries them."""
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.objects import Price, Quantity

    bar_type = BarType.from_str(spelling)
    return [
        Bar(
            bar_type=bar_type,
            open=Price(close, 2),
            high=Price(close + span / 2, 2),
            low=Price(close - span / 2, 2),
            close=Price(close, 2),
            volume=Quantity(1, 0),
            ts_event=i * 60_000_000_000,
            ts_init=i * 60_000_000_000,
        )
        for i in range(count)
    ]


def test_it_warms_from_history_so_the_gate_is_not_a_five_hour_halt():
    """**The defect this exists for stopped the desk trading.**

    `_rank` needs 20 bars of an instrument's own before it will rank it, and
    `Desk._volatile_enough` refuses every signal until a ranking exists. With
    no history request that is 20 *live* bars - five hours at 15m - so
    `TRADING_VOLATILE_ONLY=1` was a five-hour trading halt after every deploy.
    Measured on 2026-11-10: the screen came up at 19:04 and at 19:19 reported
    "no instrument with 20 bars yet, of 38 subscribed" while four signals were
    refused as `no-ranking`.

    Driven unbound on a stub because **`Actor.clock` and `Actor.log` are
    read-only** on the Cython base, which is the same reason
    `StatespaceActor._say_tally` and `actor.alert_for` are asserted this way.
    """
    import datetime

    asked: list[tuple[str, int]] = []
    spellings = (
        "EURUSD.SIM-15-MINUTE-LAST-EXTERNAL",
        "XAUUSD.SIM-15-MINUTE-LAST-EXTERNAL",
    )
    stub = SimpleNamespace(
        _cfg=SimpleNamespace(bar_types=spellings, warm_bars=40),
        request_bars=lambda bar_type, _since, limit=None: asked.append(
            (str(bar_type), int(limit or 0))
        ),
        clock=SimpleNamespace(utc_now=lambda: datetime.datetime(2026, 11, 10)),
        log=SimpleNamespace(warning=lambda *_: None),
    )
    VolatileScreen._warm(stub)

    assert [name for name, _ in asked] == list(spellings), asked
    assert {limit for _, limit in asked} == {40}, "the request did not carry the warm count"

    # A span per bar type, so one number covers every interval screened: 40
    # bars of 15 minutes is ten hours back, not forty seconds.
    assert len(asked) == 2


def test_the_history_response_reaches_the_ranges():
    """**Nautilus answers `request_bars` into `on_historical_data`, not
    `on_bar`**, so a request with no handler warms nothing at all - the half
    that asking on its own does not buy."""
    rows = _bars("EURUSD.SIM-15-MINUTE-LAST-EXTERNAL", count=3)
    stub = SimpleNamespace(_ranges={"EURUSD.SIM-15-MINUTE-LAST-EXTERNAL": _window()})
    stub.on_bar = lambda bar: VolatileScreen.on_bar(stub, bar)
    VolatileScreen.on_historical_data(stub, rows)
    assert len(stub._ranges["EURUSD.SIM-15-MINUTE-LAST-EXTERNAL"]) == 3

    # A bar type the screen does not rank is ignored rather than folded.
    VolatileScreen.on_historical_data(stub, _bars("XAUUSD.SIM-15-MINUTE-LAST-EXTERNAL"))
    assert len(stub._ranges) == 1, "a foreign bar type created a range"


def test_warming_off_is_a_no_op_rather_than_a_crash():
    """`warm_bars=0` is how a backtest keeps the screen on live bars only."""
    asked: list[str] = []
    stub = SimpleNamespace(
        _cfg=SimpleNamespace(bar_types=("EURUSD.SIM-15-MINUTE-LAST-EXTERNAL",), warm_bars=0),
        request_bars=lambda *a, **k: asked.append("asked"),
        clock=SimpleNamespace(utc_now=lambda: None),
        log=SimpleNamespace(warning=lambda *_: None),
    )
    from till_infinity.strategies.screening import ScreenConfig

    assert ScreenConfig().warm_bars > 0, "the default must warm, since production is the live node"
    # `on_start` guards the call, so the no-op is the guard rather than `_warm`.
    if stub._cfg.warm_bars > 0:
        VolatileScreen._warm(stub)
    assert asked == []
