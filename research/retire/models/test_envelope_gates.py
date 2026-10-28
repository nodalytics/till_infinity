"""The envelope model's promotion gates, as they passed when retraining was retired.

Moved out of `tests/test_envelope_model.py` with `retrain.py` on 2026-10-28. The rest
of that file tests the shipped model being *read*, which still happens; these test the
gates that decided whether a freshly trained challenger was allowed to replace it.

`test_the_metals_model_conformal_measured_would_not_ship` is the one worth keeping
legible: the absolute gates were added on 2026-10-07 because the relative ones alone
would have shipped a metals model whose measured coverage was wrong.
"""

import pytest

from till_infinity.models import retrain as rt

GOOD = {
    "vs_empirical_slice": {"relative": -0.04, "low": -0.05, "high": -0.03, "se": 0.005},
    "worst_window": 0.88,
    "empirical_worst_window": 0.885,
    # Pooled coverage, which `envelope_train.summary` reports on every challenger
    # and the absolute gates read. A fixture without them is a challenger that
    # quoted no band at all.
    "p10": 0.10,
    "p50": 0.50,
    "p90": 0.90,
}

#: Quantile boosting as `conformal.md` measured it on metals at 50 bars: the
#: lowest pinball of any method in all 18 cells, and a worst slice of 78.1%
#: against a quoted 90%. Every *relative* gate passes it - it beats the history
#: envelope on pinball and its worst window is close to the history envelope's,
#: because that one is poor on metals too. This is the case the absolute floor
#: exists for, and the test below is the one that would have stopped it
#: shipping.
METALS_50 = {
    "vs_empirical_slice": {"relative": -0.06, "low": -0.07, "high": -0.05, "se": 0.004},
    "worst_window": 0.781,
    "empirical_worst_window": 0.79,
    "p10": 0.10,
    "p50": 0.50,
    "p90": 0.90,
}


def test_the_gates_promote_a_good_model():
    assert rt.envelope_gate(GOOD) == []


@pytest.mark.parametrize(
    ("change", "word"),
    [
        (
            {"vs_empirical_slice": {"relative": -0.01, "low": -0.02, "high": 0.001, "se": 0.005}},
            "noise",
        ),
        ({"worst_window": 0.86}, "worst"),
        ({"vs_champion": {"relative": 0.03, "se": 0.005}}, "champion"),
    ],
)
def test_the_gates_keep_the_champion(change, word):
    assert any(word in r for r in rt.envelope_gate({**GOOD, **change}))


def test_a_small_slip_against_the_champion_is_within_its_slack():
    assert rt.envelope_gate({**GOOD, "vs_champion": {"relative": 0.004, "se": 0.001}}) == []


def test_the_contest_runs_on_a_toy_fetch():
    pytest.importorskip("sklearn")
    from till_infinity.prices.models import Bar

    def walk(seed: int) -> list[Bar]:
        rng, price, out = random.Random(seed), 1.1, []
        for i in range(10_500):
            sigma = 0.0015 if (i // 1500) % 2 else 0.0006
            close = price * math.exp(rng.gauss(0, sigma))
            out.append(
                Bar(
                    1_700_000_000 + 900 * i,
                    price,
                    max(price, close) * (1 + sigma / 3),
                    min(price, close) * (1 - sigma / 3),
                    close,
                )
            )
            price = close
        return out

    data = {"EURUSD": walk(1), "GBPUSD": walk(2)}
    run = rt.REGISTRY["envelope_fx15m_5"]
    spec, report = run(lambda s, i: data[s] if i == "15m" else [], list(data))
    assert report["family"] == "fx"
    assert report["evaluator_max_diff"] <= rt.GATES["exact"]
    for key in ("vs_empirical", "vs_empirical_slice", "worst_window", "empirical_worst_window"):
        assert key in report["challenger"]
    assert (spec is not None) == report["promoted"]


# ------------------------------------------- the absolute gates (added 2026-10-07)


def test_the_metals_model_conformal_measured_would_not_ship():
    """`conformal.md`'s closing recommendation, as a test.

    Quantile boosting had the lowest pinball of every method in all 18 family x
    horizon cells and a worst slice in metals of 78.1% at 50 bars. Every
    *relative* gate passes it, because the history envelope is poor on metals
    too - which is exactly how a model that quotes 90 and covers 78 reaches
    production.
    """
    reasons = rt.envelope_gate(METALS_50)
    assert reasons, "78.1% worst-window coverage must not promote"
    assert any("floor" in r for r in reasons)
    # And it is the absolute floor that catches it, not the relative one: its
    # worst window is within `slice_points` of the history envelope's.
    assert not any("against the history envelope's" in r for r in reasons)


def test_the_relative_gates_alone_would_have_passed_it():
    """The reason the floor had to be added rather than the others tightened."""
    from till_infinity.models.envelope_train import ENVELOPE_GATES

    mine = METALS_50["worst_window"]
    theirs = METALS_50["empirical_worst_window"]
    assert mine >= theirs - ENVELOPE_GATES["slice_points"]
    assert METALS_50["vs_empirical_slice"]["high"] < ENVELOPE_GATES["beats_empirical"]


@pytest.mark.parametrize("cover", [0.84, 0.70, 0.0])
def test_any_worst_window_under_the_floor_is_refused(cover):
    got = rt.envelope_gate({**GOOD, "worst_window": cover, "empirical_worst_window": cover})
    assert any("floor" in r for r in got)


def test_a_worst_window_just_over_the_floor_is_allowed():
    """The history envelope moves with it, so only the absolute gate is in play:
    0.851 against its 0.885 would fail the *relative* one on its own."""
    just = {**GOOD, "worst_window": 0.851, "empirical_worst_window": 0.855}
    assert rt.envelope_gate(just) == []


@pytest.mark.parametrize(
    ("level", "value"),
    [("p10", 0.14), ("p10", 0.06), ("p50", 0.55), ("p90", 0.86), ("p90", 0.94)],
)
def test_a_band_wrong_at_any_level_is_refused(level, value):
    """A model can buy pinball with a band that is wrong in a useful direction,
    so each level is checked against its own nominal rather than the width."""
    got = rt.envelope_gate({**GOOD, level: value})
    assert any(level in r for r in got), got


def test_a_missing_coverage_figure_is_refused_rather_than_assumed():
    """Absent is not passing. A challenger that reported no coverage at all used
    to clear every gate here, because all of them were comparisons."""
    for level in ("p10", "p50", "p90"):
        missing = {k: v for k, v in GOOD.items() if k != level}
        assert any(level in r for r in rt.envelope_gate(missing))
    nan = rt.envelope_gate({**GOOD, "worst_window": float("nan")})
    assert any("floor" in r for r in nan)


# Also from tests/test_envelope_model.py: this one reads the trainer's own replay,
# so it went with `envelope_train.py`. It pinned a defect rather than a design - the
# three bps readings were fed as zeroes because the trainer replays through `Ranges`,
# which cannot produce them. See research/docs/forward-features.md.

def test_the_trainer_feeds_activity_but_still_not_the_bps_readings():
    """**A feature that is constant in training cannot be judged by the contest.**

    It wins no splits, so `vs_champion` measures no loss from dropping it whatever
    it would have been worth live - the model is not choosing to ignore it, it is
    being shown a column of zeroes. `activity` is fed properly because the volume
    it needs is already on the bar; the three bps readings are not, because the
    trainer replays through `Ranges`, which cannot produce them. The second half of
    this test pins a defect rather than a design - when it starts failing, the
    skew has been fixed and `research/docs/forward-features.md` wants updating.
    """
    from till_infinity.models import envelope_train as et

    rows = [x for x in et._track("EURUSD", _volume_bars()).x if x is not None]
    assert rows, "the replay produced no warm rows"
    col = {name: i for i, name in enumerate(ev.MODEL_NAMES)}

    seen = {round(r[col["activity"]], 9) for r in rows}
    assert len(seen) > 50, f"activity barely moves in training: {len(seen)} distinct"
    assert min(seen) > 0.0

    for name in ("ens_ratio", "fc_ratio", "garch_ratio", "vol_stretch"):
        assert {round(r[col[name]], 9) for r in rows} == {0.0}, (
            f"{name} now varies in training - the skew is fixed, so drop it from this "
            "list and update research/docs/forward-features.md"
        )
