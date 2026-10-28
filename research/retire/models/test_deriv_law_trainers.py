"""the Deriv own-law table's trainer and its contest, as these passed when the pipeline was retired.

Moved out of `tests/test_deriv_law.py` on 2026-10-28. The reader half stayed: the shipped
model is still read by the live package, and only the training and promotion of a
replacement is retired. These import `till_infinity.models.*_train`, which lives
beside this file, so they do not run as they stand.
"""

"""Deriv's own-law envelope: Boom, Crash, DEX, Range Break and Drift Switch quoted from a shipped
convolved table (`research/docs/deriv-variants.md`), cell by cell, calibrated from bar zero."""

from __future__ import annotations

import json
import math
import random

import numpy as np
import pytest

from till_infinity.models import deriv_law_train as dl
from till_infinity.prices.models import Bar
from till_infinity.shared import frozen
from till_infinity.structures.vol import envelope as ev

TABLE = [-0.004, -0.003, -0.002, -0.001, 0.0, 0.001, 0.002, 0.003, 0.004]


@pytest.fixture(autouse=True)
def models_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TI_MODELS_DIR", str(tmp_path))
    frozen.forget_cache()
    yield tmp_path
    frozen.forget_cache()


def _ship(path, tables, recipe=None):
    spec = {"recipe": recipe or ev.LAW_RECIPE, "names": list(ev.LAW_NAMES), "tables": tables}
    (path / f"{ev.LAW_MODEL}.json").write_text(json.dumps(spec))
    frozen.forget_cache()


@pytest.mark.parametrize(
    ("feed", "own"),
    [
        ("boom_1000_index", True),
        ("Crash 500 Index", True),
        ("DEX 600 UP Index", True),
        ("range_break_100_index", True),
        ("drift_switch_index_10", True),
        ("volatility_75_index", False),  # published law
        ("jump_50_index", False),
        ("step_index", False),
        ("eurusd", False),
    ],
)
def test_the_fitted_table_is_the_convolved_one_bar_law():
    spec = dl.fit({("Boom_1000_Index", "15m"): _walk(5000), ("EURUSD", "15m"): _walk(5000)})
    assert set(spec["tables"]) == {f"boom_1000_index|15m|{n}" for n in ev.HORIZONS}
    q = spec["tables"]["boom_1000_index|15m|20"]
    assert q == sorted(q)
    # iid Gaussian steps: the 20-bar P90 is about 1.2816 * 0.001 * sqrt(20)
    assert ev.table_quantile(q, 0.9) == pytest.approx(1.2816 * 0.001 * math.sqrt(20), rel=0.08)


def test_a_memoryless_series_passes_its_cell_and_a_regime_switcher_fails():
    good = {("Boom_1000_Index", "15m"): _walk(12_000)}
    cut = good[("Boom_1000_Index", "15m")][7_200].time
    spec = dl.fit({k: [b for b in v if b.time < cut] for k, v in good.items()})
    kept, cells = dl.select(spec, good, cut)
    assert all(c["pass"] for c in cells if c["n"] <= 20)
    assert kept["tables"]

    # a drift that switches sign every 400 bars: the one-bar law understates the N-bar spread
    rng = np.random.default_rng(5)
    price, out, t0 = 1000.0, [], 1_700_000_000
    for i in range(12_000):
        drift = 0.0006 if (i // 400) % 2 else -0.0006
        close = price * math.exp(drift + rng.normal(0, 0.0005))
        out.append(Bar(t0 + 900 * i, price, max(price, close), min(price, close), close))
        price = close
    bad = {("Drift_Switch_Index_10", "15m"): out}
    spec = dl.fit({k: [b for b in v if b.time < cut] for k, v in bad.items()})
    kept, cells = dl.select(spec, bad, cut)
    assert not any(c["pass"] for c in cells if c["n"] == 50)
    assert not any(k.endswith("|50") for k in kept["tables"])




# This one imported the trainer inside its body rather than at module scope, so a
# scan of module imports missed it and the split left it behind. The test run found it.

def test_the_retrain_contest_promotes_passing_cells():
    from till_infinity.models import retrain as rt

    bars = _walk(9_000 * 4, seed=9)  # 15m bars, long enough for a 90-day hold-out

    def fetch(symbol, interval):
        return bars if interval == "15m" else []

    spec, report = rt.run_deriv_law(fetch, ["Boom_1000_Index", "EURUSD"])
    assert report["series"] == 1
    assert report["challenger"]["cells"] == len(ev.HORIZONS)
    assert (spec is not None) == report["promoted"]
    if spec is not None:
        assert spec["recipe"] == ev.LAW_RECIPE
        assert all(k.startswith("boom_1000_index|15m|") for k in spec["tables"])
