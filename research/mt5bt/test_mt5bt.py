"""Checks of the fill rules on bars built by hand, where the right answer is known.

    .venv/bin/python -m pytest research/mt5bt/test_mt5bt.py -q
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mt5bt import Book, Costs, lookahead, run, t_walk  # noqa: E402
from mt5bt.data import EXAMPLE_SPECS  # noqa: E402

SPEC = EXAMPLE_SPECS["EURUSD"]
T0 = int(pd.Timestamp("2026-07-14 10:00", tz="UTC").timestamp())  # a Tuesday


def book(rows, spread=10.0):
    """rows of (open, high, low, close), 15m apart; spread in points (10 points = 1 pip)."""
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "ts", T0 + 900 * np.arange(len(df)))
    df["spread"] = spread
    return Book("EURUSD", df, SPEC, "15m")


def one(side, stop, target=0.0, hold=0, i=0):
    return lambda bars, b: pd.DataFrame({"i": [i], "side": [side], "stop": [stop],
                                         "target": [target], "hold": [hold]})


def trade(b, strat, **kw):
    t, _ = run(b, strat, Costs(swap=False), **kw)
    assert len(t) == 1
    return t.iloc[0]


def test_a_long_buys_the_ask_and_is_stopped_on_the_bid():
    b = book([(1.1000,) * 4, (1.1000, 1.1005, 1.0985, 1.0990)])
    t = trade(b, one(+1, 0.0010))
    assert t["entry"] == pytest.approx(1.1001)  # 1.1000 bid + 1 pip
    assert t["reason"] == "stop" and t["exit"] == pytest.approx(1.0991)
    assert t["R"] == pytest.approx(-1.0, abs=0.02)  # the lot grid rounds the size down


def test_a_short_sells_the_bid_and_is_stopped_on_the_ask():
    # the bid high 1.1009 never reaches the 1.1010 stop; the ask (bid + 1 pip) does
    b = book([(1.1000,) * 4, (1.1000, 1.1009, 1.0995, 1.1000)])
    t = trade(b, one(-1, 0.0010))
    assert t["entry"] == pytest.approx(1.1000)
    assert t["reason"] == "stop" and t["exit"] == pytest.approx(1.1010)


def test_a_gap_through_the_stop_fills_at_the_open():
    b = book([(1.1000,) * 4, (1.1000, 1.1002, 1.0998, 1.1000), (1.0970, 1.0975, 1.0960, 1.0965)])
    t = trade(b, one(+1, 0.0010))
    assert t["reason"] == "stop_gap" and t["exit"] == pytest.approx(1.0970)
    assert t["R"] < -2.5  # a gap costs more than the planned 1R


def test_a_bar_touching_both_levels_is_the_stop():
    b = book([(1.1000,) * 4, (1.1000, 1.1030, 1.0980, 1.1000)])
    assert trade(b, one(+1, 0.0010, target=0.0010))["reason"] == "stop"


def test_ticks_decide_a_bar_touching_both_levels():
    b = book([(1.1000,) * 4, (1.1000, 1.1030, 1.0980, 1.1000)])
    ms = (T0 + 900) * 1000
    b.ticks = pd.DataFrame({"ts_ms": [ms + 1000, ms + 2000], "bid": [1.1025, 1.0985],
                            "ask": [1.1026, 1.0986]})
    assert trade(b, one(+1, 0.0010, target=0.0010))["reason"] == "target"


def test_time_exit_on_the_close_of_the_last_held_bar():
    b = book([(1.1000,) * 4] + [(1.1000, 1.1002, 1.0998, 1.1001)] * 5)
    t = trade(b, one(+1, 0.0050, hold=3))
    assert t["reason"] == "time" and t["exit_bar"] == 3 and t["exit"] == pytest.approx(1.1001)


def test_the_spread_is_paid_once_a_round_trip():
    b = book([(1.1000,) * 4] + [(1.1000,) * 4] * 3)
    long_ = trade(b, one(+1, 0.0050, hold=2))
    short = trade(b, one(-1, 0.0050, hold=2))
    for t in (long_, short):
        assert t["net"] == pytest.approx(-t["spread_cost"])
        assert t["spread_cost"] == pytest.approx(0.0001 / SPEC.tick_size * SPEC.tick_value * t["volume"])


def test_below_the_minimum_lot_is_refused_not_rounded_up():
    b = book([(1.1000,) * 4, (1.1000,) * 4])
    t, refused = run(b, one(+1, 0.0010), Costs(swap=False), equity=100.0, risk=0.0001)
    assert t.empty and "minimum" in refused["why"].iat[0]


def test_swap_is_charged_across_the_rollover():
    # 20:45 UTC entry in July; the 17:00 New York rollover is 21:00 UTC
    b = book([(1.1000,) * 4] * 4)
    b.bars["ts"] = int(pd.Timestamp("2026-07-14 20:30", tz="UTC").timestamp()) + 900 * np.arange(4)
    t, _ = run(b, one(+1, 0.0050, hold=3), Costs(swap=True))
    assert t["swap_cost"].iat[0] == pytest.approx(9.7 * SPEC.point / SPEC.tick_size
                                                  * SPEC.tick_value * t["volume"].iat[0])


def test_the_audit_catches_a_peek_and_passes_a_causal_rule():
    from mt5bt.strategies.donchian import donchian_peek, strategy

    walk = Book("EURUSD", t_walk(3000, seed=5), SPEC, "15m")
    assert lookahead(strategy, walk)["ok"]
    assert not lookahead(donchian_peek, walk)["ok"]


def test_no_edge_on_a_walk_costs_the_spread():
    """Random entries on an iid walk: gross about zero, net about minus the spread, in R."""
    from mt5bt.strategies.random_entry import strategy

    walk = Book("EURUSD", t_walk(120_000, seed=9, spread_points=8.0), SPEC, "15m")
    t, _ = run(walk, strategy, Costs(swap=False))
    gross = (t["gross"] / t["risk_money"]).to_numpy()
    se = gross.std() / np.sqrt(len(gross))
    assert abs(gross.mean()) < 3 * se + 0.01
    assert t["R"].mean() == pytest.approx(gross.mean() - (t["spread_cost"] / t["risk_money"]).mean(),
                                          abs=1e-9)


# ------------------------------------------------------------------ bid/ask, ticks, tick volume


def ticked(prices, spread=0.0001, every_s=30):
    """A book whose bars are built from ticks: (bid) prices every `every_s` seconds."""
    from mt5bt import bars_from_ticks

    ms = (T0 + every_s * np.arange(len(prices))) * 1000
    ticks = pd.DataFrame({"ts_ms": ms, "bid": prices, "ask": np.asarray(prices) + spread})
    b = Book("EURUSD", bars_from_ticks(ticks, "15m", SPEC), SPEC, "15m")
    b.ticks = ticks
    return b


def test_strategies_see_both_sides_and_tick_volume():
    b = book([(1.1000, 1.1005, 1.0995, 1.1002)])
    row = b.bars.iloc[0]
    assert row["ask_high"] == pytest.approx(1.1006) and row["mid_close"] == pytest.approx(1.10025)
    assert row["spread_price"] == pytest.approx(0.0001) and "tick_volume" in b.bars


def test_bars_from_ticks_keep_both_sides_and_count_ticks():
    prices = [1.1000] * 30 + [1.1010] * 30 + [1.0990] * 30  # 90 ticks, 30 s apart: 45 minutes
    b = ticked(prices)
    assert len(b.bars) == 3 and list(b.bars["tick_volume"]) == [30.0, 30.0, 30.0]
    assert b.bars["ask_close"].iat[1] == pytest.approx(1.1011)
    assert b.bars["spread"].iat[0] == pytest.approx(10.0)


def test_ticks_fill_a_jump_through_the_stop_at_the_tick_not_the_level():
    # long from 1.1001 (ask), stop 10 pips; the bid jumps from 1.0995 to 1.0950 in one tick
    prices = [1.1000] * 30 + [1.1000] * 20 + [1.0995, 1.0950] + [1.0950] * 38
    b = ticked(prices)
    t, _ = run(b, one(+1, 0.0010), Costs(swap=False, fill="ticks"))
    assert t["fill"].iat[0] == "ticks" and t["reason"].iat[0] == "stop"
    assert t["exit"].iat[0] == pytest.approx(1.0950)
    # the jump is inside a bar, so bars can only fill at the level: the optimism ticks remove
    bars, _ = run(b, one(+1, 0.0010), Costs(swap=False, fill="bars"))
    assert bars["exit"].iat[0] == pytest.approx(1.0991)
    assert t["R"].iat[0] < bars["R"].iat[0] - 4


def test_a_short_on_ticks_exits_on_the_ask():
    prices = [1.1000] * 30 + [1.1000] * 10 + [1.1009] * 50  # bid 1.1009: ask 1.1010 hits the stop
    b = ticked(prices)
    t, _ = run(b, one(-1, 0.0010), Costs(swap=False, fill="ticks"))
    assert t["reason"].iat[0] == "stop" and t["exit"].iat[0] == pytest.approx(1.1010)
    assert t["spread_cost"].iat[0] > 0


# ------------------------------------------------------------------ resting stop orders, OCO


def pending(rows):
    return lambda bars, b: pd.DataFrame(rows)


def test_a_buy_stop_fills_at_its_level_on_the_ask():
    b = book([(1.1000,) * 4, (1.1000, 1.1003, 1.0998, 1.1001), (1.1001, 1.1020, 1.1000, 1.1015)])
    t, _ = run(b, pending([dict(i=0, side=1, entry=1.1010, expires=5, stop=0.0030)]),
               Costs(swap=False))
    # the ask high is 1.1004 on bar 1, 1.1021 on bar 2: fills on bar 2 at the level
    assert t["entry_bar"].iat[0] == 2 and t["entry"].iat[0] == pytest.approx(1.1010)


def test_a_stop_order_gapped_through_fills_at_the_open():
    b = book([(1.1000,) * 4, (1.0950, 1.0955, 1.0940, 1.0945)])
    t, _ = run(b, pending([dict(i=0, side=-1, entry=1.0990, expires=3, stop=0.0030)]),
               Costs(swap=False))
    assert t["entry"].iat[0] == pytest.approx(1.0950)


def test_an_order_that_expires_never_fills():
    b = book([(1.1000,) * 4] * 6)
    t, _ = run(b, pending([dict(i=0, side=1, entry=1.1050, expires=3, stop=0.0030)]),
               Costs(swap=False))
    assert t.empty


def test_one_cancels_the_other_and_a_bar_through_both_is_the_whipsaw():
    legs = [dict(i=0, side=1, entry=1.1010, expires=5, stop=0.0020, oco=7),
            dict(i=0, side=-1, entry=1.0990, expires=5, stop=0.0020, oco=7)]
    up = book([(1.1000,) * 4, (1.1000, 1.1015, 1.0995, 1.1012), (1.1012, 1.1013, 1.0980, 1.0985)])
    t, _ = run(up, pending(legs), Costs(swap=False))
    assert len(t) == 1 and t["side"].iat[0] == 1  # the buy stop came first; the sell stop died
    both = book([(1.1000,) * 4, (1.1000, 1.1015, 1.0985, 1.1012)])  # one bar through both, closes up
    t, _ = run(both, pending(legs), Costs(swap=False))
    assert len(t) == 1 and t["side"].iat[0] == -1  # the leg against the close: the worse case


def test_a_trailing_stop_follows_completed_bars_and_takes_the_profit():
    # long from 1.1001; the bid runs to a 1.1050 high, then falls back
    b = book([(1.1000,) * 4, (1.1000, 1.1020, 1.0999, 1.1018), (1.1018, 1.1050, 1.1015, 1.1045),
              (1.1045, 1.1046, 1.1020, 1.1025)])
    t, _ = run(b, lambda bars, bk: pd.DataFrame(
        [dict(i=0, side=1, stop=0.0030, trail=0.0020)]), Costs(swap=False))
    # after bar 2 the best bid is 1.1050, so the stop is 1.1030; bar 3's low of 1.1020 takes it
    assert t["reason"].iat[0] == "trail" and t["exit"].iat[0] == pytest.approx(1.1030)
    assert t["R"].iat[0] > 0


# ------------------------------------------------------------------ resting orders and trails on ticks


def test_a_resting_buy_stop_jumped_through_fills_at_the_tick_not_the_level():
    # quiet for a bar, then the bid jumps from 1.1000 to 1.1030 in one tick: a buy stop at 1.1011
    prices = [1.1000] * 30 + [1.1000] * 10 + [1.1030] * 50
    b = ticked(prices)
    t, _ = run(b, pending([dict(i=0, side=1, entry=1.1011, expires=3, stop=0.0050)]),
               Costs(swap=False, fill="ticks"))
    assert t["fill"].iat[0] == "ticks"
    assert t["entry"].iat[0] == pytest.approx(1.1031)  # the tick's ask, 20 pips past the level


def test_a_trailing_stop_on_ticks_follows_ticks_already_seen():
    # long from 1.1001; the bid climbs to 1.1050, then falls through 1.1030
    prices = [1.1000] * 30 + list(np.linspace(1.1000, 1.1050, 20)) + [1.1040, 1.1020] + [1.1020] * 38
    b = ticked(prices)
    t, _ = run(b, lambda bars, bk: pd.DataFrame([dict(i=0, side=1, stop=0.0030, trail=0.0020)]),
               Costs(swap=False, fill="ticks"))
    assert t["fill"].iat[0] == "ticks" and t["reason"].iat[0] == "trail"
    assert t["exit"].iat[0] == pytest.approx(1.1020)  # the first tick at or below 1.1030


def test_one_cancels_the_other_by_tick_time():
    # one bar touches both edges: ticks say the low came first, so the sell stop wins
    prices = [1.1000] * 30 + [1.0985, 1.1015] + [1.1015] * 58
    b = ticked(prices)
    legs = [dict(i=0, side=1, entry=1.1011, expires=3, stop=0.0030, oco=1),
            dict(i=0, side=-1, entry=1.0990, expires=3, stop=0.0030, oco=1)]
    t, _ = run(b, pending(legs), Costs(swap=False, fill="ticks"))
    assert len(t) == 1 and t["side"].iat[0] == -1
