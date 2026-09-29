"""The retraining pipeline: the gates, promotion, the report, and the service loop."""

from __future__ import annotations

import json
import math
import random

import pytest
from click.testing import CliRunner

from till_infinity.cli import main
from till_infinity.models import retrain as rt
from till_infinity.models import shocks_train as st
from till_infinity.prices.models import Bar
from till_infinity.shared import frozen


@pytest.fixture(autouse=True)
def _models_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TI_MODELS_DIR", str(tmp_path / "models"))
    frozen.forget_cache()
    yield
    frozen.forget_cache()


GOOD = {
    "real": 0.74,
    "real_se": 0.004,
    "deriv": 0.60,
    "deriv_se": 0.02,
    "control": 0.50,
    "calibration": 1.05,
    "n": 1000,
}


# ------------------------------------------------------------------ the gates


def test_a_challenger_that_passes_every_gate_is_promoted():
    assert rt.gate(GOOD, {"real": 0.74}) == []
    assert rt.gate(GOOD, {}) == []  # no champion to beat


@pytest.mark.parametrize(
    ("change", "champion", "word"),
    [
        ({"real": 0.60}, {}, "below"),
        ({"real": 0.70}, {"real": 0.74}, "champion"),
        ({"calibration": 2.0}, {}, "calibration"),
        ({"calibration": float("nan")}, {}, "calibration"),
        ({"real": float("nan")}, {}, "below"),
        ({"deriv": 0.50}, {"deriv": 0.60}, "deriv"),
        ({"control": 0.56}, {}, "control"),
        ({"control": 0.44}, {}, "control"),
    ],
)
def test_each_gate_can_keep_the_champion(change, champion, word):
    reasons = rt.gate({**GOOD, **change}, champion)
    assert any(word in r for r in reasons)


def test_deriv_is_a_market_skill_there_is_kept_not_suspected():
    # well away from 0.5 on Deriv is fine - it is a market, not a control
    assert rt.gate({**GOOD, "deriv": 0.70}, {"real": 0.74, "deriv": 0.68}) == []


def test_the_slack_against_the_champion_widens_with_the_sample_noise():
    # 0.60 against 0.63 is inside two standard errors of 0.02, not inside 0.01
    assert rt.gate({**GOOD, "deriv": 0.60}, {"deriv": 0.63}) == []
    assert rt.gate({**GOOD, "deriv": 0.60, "deriv_se": 0.005}, {"deriv": 0.63})


def test_only_our_own_walks_are_a_control():
    rows = st.dataset(st.controls(walks=1, bars=1500))
    assert set(rows.kind) == {"control"}
    assert st.kind("Volatility 75 Index") == "deriv"
    assert st.kind("EURUSD") == "real"


def test_a_small_slip_against_the_champion_is_tolerated():
    assert rt.gate({**GOOD, "real": 0.735}, {"real": 0.74}) == []


# ------------------------------------------------------------------ promotion and the report


def _runner(spec, report):
    return lambda fetch, names: (spec, report)


def test_a_promoted_model_is_written_and_reported(monkeypatch):
    spec = {"recipe": "r", "names": ["a"], "baseline": 0.0, "trees": []}
    monkeypatch.setitem(rt.REGISTRY, "toy", _runner(spec, {"promoted": True, "reasons": []}))
    report = rt.run_once("toy", lambda s, i: [], ["X"])
    out = frozen.models_dir()
    assert json.loads((out / "toy.json").read_text()) == spec
    assert not (out / "toy.json.tmp").exists()
    lines = (out / "toy.report.jsonl").read_text().splitlines()
    assert json.loads(lines[-1])["promoted"] is True
    assert report["model"] == "toy"
    assert {"started", "finished"} <= set(report)


def test_a_kept_champion_writes_only_the_report(monkeypatch):
    monkeypatch.setitem(rt.REGISTRY, "toy", _runner(None, {"promoted": False, "reasons": ["x"]}))
    rt.run_once("toy", lambda s, i: [], ["X"])
    rt.run_once("toy", lambda s, i: [], ["X"])
    out = frozen.models_dir()
    assert not (out / "toy.json").exists()
    assert len((out / "toy.report.jsonl").read_text().splitlines()) == 2


def test_the_card_says_why_the_champion_stayed():
    card = rt.card({"model": "shocks", "promoted": False, "reasons": ["too weak"], "series": 3})
    assert "kept" in card["title"]
    assert "too weak" in card["body"]
    card = rt.card({"model": "shocks", "promoted": True, "reasons": [], "challenger": GOOD})
    assert "promoted" in card["title"]
    assert "0.74" in card["body"]


# ------------------------------------------------------------------ the service loop


def test_one_failing_model_still_cards_and_stamps_the_run(monkeypatch):
    def broken(fetch, names):
        raise RuntimeError("bridge went away")

    monkeypatch.setattr(rt, "REGISTRY", {"broken": broken})
    cards = []
    rt.watch(14, lambda s, i: [], ["X"], cards.append, once=True)
    assert len(cards) == 1
    assert "bridge went away" in cards[0]["body"]
    assert (frozen.models_dir() / "retrain.last").exists()


def test_only_the_named_models_run(monkeypatch):
    ran = []

    def runner(name):
        def go(fetch, names):
            ran.append(name)
            return None, {"promoted": False, "reasons": []}

        return go

    monkeypatch.setattr(rt, "REGISTRY", {"a": runner("a"), "b": runner("b")})
    rt.watch(14, lambda s, i: [], ["X"], once=True, only=["b"])
    assert ran == ["b"]


def test_symbols_come_from_the_broker_book(monkeypatch):
    monkeypatch.delenv("MODELS_SYMBOLS", raising=False)
    monkeypatch.setenv("PRICES_BROKER_SYMBOLS", "EURUSD, Volatility 75 Index ,")
    assert rt.symbols() == ["EURUSD", "Volatility 75 Index"]
    monkeypatch.setenv("MODELS_SYMBOLS", "XAUUSD")
    assert rt.symbols() == ["XAUUSD"]


def test_the_command_refuses_a_one_off_run_without_a_bridge(monkeypatch):
    pytest.importorskip("sklearn")
    monkeypatch.setenv("TRADING_MT5_URL", "")  # set, so a local .env cannot fill it in
    got = CliRunner().invoke(main, ["models", "retrain", "--once"])
    assert got.exit_code != 0
    assert "TRADING_MT5_URL" in got.output


# ------------------------------------------------------------------ the shock contest, end to end


def _walk(n: int, seed: int, clustered: bool) -> list[Bar]:
    rng = random.Random(seed)
    price, t, sigma, out = 100.0, 1_700_000_000, 0.001, []
    for _ in range(n):
        if clustered:
            sigma = min(0.02, max(0.0005, sigma * math.exp(rng.gauss(0, 0.15))))
        move = rng.gauss(0, sigma)
        high = price * math.exp(max(move, 0) + abs(rng.gauss(0, sigma / 2)))
        low = price * math.exp(min(move, 0) - abs(rng.gauss(0, sigma / 2)))
        close = price * math.exp(move)
        out.append(Bar(t, price, max(high, close, price), min(low, close, price), close))
        price, t = close, t + 900
    return out


def test_labels_look_ahead_within_the_series():
    rows = st.dataset({("EURUSD", "15m"): _walk(1500, 1, True)})
    when, kinds, x, y = rows.arrays()
    assert len(y) > 0
    assert set(kinds) == {"real"}
    assert list(when) == sorted(when)
    assert x.shape[1] == len(st.sh.NAMES)
    assert 0 < y.mean() < 0.5


def test_the_shock_contest_runs_and_its_export_is_exact(monkeypatch):
    pytest.importorskip("sklearn")
    full = st.controls
    monkeypatch.setattr(st, "controls", lambda: full(walks=2, bars=2500))
    series = {"EURUSD": _walk(4000, 2, True), "Volatility 75 Index": _walk(4000, 3, False)}
    spec, report = rt.run_shocks(
        lambda symbol, interval: series[symbol] if interval == "15m" else [], list(series)
    )
    assert report["series"] == 2
    assert report["evaluator_max_diff"] <= rt.GATES["exact"]
    assert {"real", "deriv", "control"} <= set(report["challenger"])
    assert "real" in report["champion"]  # the shipped model is the champion
    assert (spec is not None) == report["promoted"]


def test_every_series_keeps_its_own_name_through_the_merge():
    # A generator expression inside the comprehension once labelled every bar with the last series.
    rows = st.dataset(
        {("EURUSD", "15m"): _walk(1500, 1, True), ("Step Index", "1h"): _walk(1500, 2, False)}
    )
    assert set(rows.key) == {"EURUSD|15m", "Step Index|1h"}
    assert set(rows.kind) == {"real", "deriv"}
