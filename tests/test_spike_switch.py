"""The risk switch: halve into the windows where a large bar is likely.

It reads one published number - where the 14-bar true-range average sits in its own
last 1,500 bars - and can only shrink a trade. The properties worth pinning are that
it is off unless configured, never enlarges, reaches every path that sizes a trade,
and survives a restore. See `research/docs/crash-timing.md`.
"""

from __future__ import annotations

import inspect
import pickle

import pytest

from till_infinity.structures.vol.volatility import Volatility
from till_infinity.trading import Settings, scaling
from till_infinity.trading.models import Side
from till_infinity.trading.strategies.strategy import build, spike_scale


def bars(vol, n, *, span, price=100.0):
    """`n` bars of the same shape: open and close at `price`, a range of `span` either side."""
    for _ in range(n):
        vol.observe_bar(price, price + span, price - span, price)
        vol.update(price)


# ------------------------------------------------------------------ the multiplier


def test_it_is_off_unless_configured():
    assert scaling.by_spike(0.99, 0.0) == 1.0


def test_below_the_threshold_is_full_size():
    assert scaling.by_spike(0.79, 0.8) == 1.0


def test_at_or_above_it_is_the_floor():
    assert scaling.by_spike(0.8, 0.8) == pytest.approx(0.5)
    assert scaling.by_spike(1.0, 0.8, floor=0.25) == pytest.approx(0.25)


def test_a_missing_reading_sizes_as_before():
    """A signal published before the feature existed still has to size."""
    assert scaling.by_spike(None, 0.8) == 1.0


@pytest.mark.parametrize("floor", [1.5, 2.0, 10.0])
def test_it_can_never_enlarge(floor):
    """A misconfigured floor above one must not size up into the loudest bars."""
    assert scaling.by_spike(0.95, 0.8, floor=floor) == 1.0


def test_it_never_sizes_to_nothing():
    assert scaling.by_spike(0.95, 0.8, floor=0.0) == scaling.FLOOR


# ------------------------------------------------------------------ the reading


def test_a_cold_series_reads_the_middle():
    vol = Volatility()
    bars(vol, 5, span=0.1)
    assert vol.tr_percentile == 0.5


def test_a_widening_range_reads_high_and_a_narrowing_one_low():
    vol = Volatility()
    bars(vol, 200, span=0.1)
    bars(vol, 20, span=0.5)
    assert vol.tr_percentile > 0.9
    bars(vol, 200, span=0.02)
    assert vol.tr_percentile < 0.1


def test_the_window_is_bounded():
    vol = Volatility()
    bars(vol, 1_700, span=0.1)
    assert len(vol._tr_history) == 1_500


def test_it_survives_a_restore():
    """Production restores rather than builds; a percentile that restarts cold on every
    deploy would read the middle for the first twenty bars of every run."""
    vol = Volatility()
    bars(vol, 200, span=0.1)
    bars(vol, 20, span=0.5)
    back = pickle.loads(pickle.dumps(vol))
    assert back.tr_percentile == vol.tr_percentile


def test_a_state_saved_before_the_feature_restores_cold_not_broken():
    vol = Volatility()
    bars(vol, 50, span=0.1)
    state = vol.__getstate__()
    if isinstance(state, tuple):  # slots dataclass: (None, {slot: value})
        state = (state[0], {k: v for k, v in state[1].items() if k != "_tr_history"})
    else:
        state = {k: v for k, v in state.items() if k != "_tr_history"}
    old = Volatility.__new__(Volatility)
    old.__setstate__(state)
    assert old.tr_percentile == 0.5


def test_the_engine_publishes_it():
    """Trading reads features off the bus and never touches the engine."""
    from till_infinity.structures import engine as eng

    assert '"tr_percentile": vol.tr_percentile' in inspect.getsource(eng)


# ------------------------------------------------------------------ the wiring


ARGS = {
    "feed": "gold",
    "positions": (),
    "equity": 10_000.0,
    "peak": 10_000.0,
    "interval": "15m",
    "side": Side.BUY,
}


def test_risk_scale_halves_in_the_loud_window():
    settings = Settings()
    settings.spike_above = 0.8
    engine = build(["level-scalp"], settings)[0]
    quiet = engine.risk_scale(features={"tr_percentile": 0.3}, **ARGS)
    loud = engine.risk_scale(features={"tr_percentile": 0.9}, **ARGS)
    assert loud == pytest.approx(quiet * 0.5)


def test_risk_scale_ignores_it_when_off():
    engine = build(["level-scalp"], Settings())[0]
    quiet = engine.risk_scale(features={"tr_percentile": 0.3}, **ARGS)
    loud = engine.risk_scale(features={"tr_percentile": 0.99}, **ARGS)
    assert quiet == loud


def test_spike_scale_reads_the_signal_features():
    settings = Settings()
    settings.spike_above = 0.8
    assert spike_scale({"tr_percentile": 0.85}, settings) == pytest.approx(0.5)
    assert spike_scale({"tr_percentile": "0.85"}, settings) == 1.0  # not a number
    assert spike_scale(None, settings) == 1.0


@pytest.mark.parametrize(
    "module",
    [
        "till_infinity.trading.service",  # consensus, parallel and follower re-sizing
        "till_infinity.trading.strategies.swing",  # FadeToValue, which skips risk_scale
        "till_infinity.trading.strategies.council",  # flat fraction, skips risk_scale
    ],
)
def test_every_path_that_sizes_a_trade_reads_it(module):
    """The trader re-sizes at the flat fraction in the consensus path, in parallel mode
    and onto followers, discarding every multiplier. A switch that lived only in
    `risk_scale` would be inert in exactly the modes that take the most trades."""
    import importlib

    source = inspect.getsource(importlib.import_module(module))
    assert "spike_scale(" in source, module


def test_the_service_sizes_through_it_everywhere_it_resizes():
    import re

    from till_infinity.trading import service

    source = inspect.getsource(service)
    flat = source.count("risk_fraction=self.settings.risk_fraction\n")
    switched = len(
        re.findall(
            r"risk_fraction=self\.settings\.risk_fraction\n\s*\* strategy\.spike_scale", source
        )
    )
    assert flat == switched == 3, (flat, switched)


def test_settings_read_it_from_the_environment(monkeypatch):
    monkeypatch.setenv("TRADING_SPIKE_ABOVE", "0.8")
    monkeypatch.setenv("TRADING_SPIKE_FLOOR", "0.4")
    got = Settings.from_env()
    assert got.spike_above == pytest.approx(0.8)
    assert got.spike_floor == pytest.approx(0.4)


def test_it_is_off_by_default():
    assert Settings().spike_above == 0.0
