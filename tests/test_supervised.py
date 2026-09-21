"""The guards on the supervised candle dataset, tested structurally.

These are not tests of whether a model works - that is what the walk-forward
report is for. They test the three claims the whole apparatus rests on, each of
which has been got wrong here before:

* a **feature** never reads a bar after the one it is built at;
* a **label** always does, because that is what makes it supervised;
* a split never lets one row's forward window reach into the other side.

The first two are tested the same way and in opposite directions: change a future
bar and assert the features do not move, then assert the label does. A test that
only checked "no leakage" would pass on a label that had stopped looking forward
at all, which would be a different and worse bug.
"""

from __future__ import annotations

import csv
import gzip
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research" / "training"))
sys.path.insert(0, str(ROOT / "research" / "harness"))

candles = pytest.importorskip("candles")
labels = pytest.importorskip("labels")
splits = pytest.importorskip("splits")


def fake_bars(n: int = 600, seed: int = 3) -> list[tuple]:
    """A random walk with a real range on every bar, as the loader expects."""
    rng = np.random.default_rng(seed)
    price = 100.0
    out = []
    for i in range(n):
        step = rng.normal(0, 0.8)
        o = price
        c = max(0.5, price + step)
        reach = abs(rng.normal(0, 0.4)) + 0.05
        h, low = max(o, c) + reach, min(o, c) - reach
        out.append((1_600_000_000 + i * 86_400, o, h, max(0.1, low), c, 1000.0 + i))
        price = c
    return out


def write_bars(path: Path, rows: list[tuple]) -> Path:
    with gzip.open(path, "wt", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(["ts", "open", "high", "low", "close", "volume"])
        out.writerows(rows)
    return path


@pytest.fixture
def one_file(tmp_path: Path) -> Path:
    return write_bars(tmp_path / "alpha_1d_test.csv.gz", fake_bars())


class TestFeaturesCannotSeeForward:
    def test_changing_a_later_bar_does_not_move_a_feature(self, tmp_path: Path):
        """**The structural guard.** Every feature slice ends at `at` inclusive, so
        rewriting everything after it must leave the row untouched."""
        rows = fake_bars()
        at = 400
        bars, _ = candles.read(write_bars(tmp_path / "a_1d_test.csv.gz", rows))
        before = candles.features(bars, candles.true_range(bars), at)

        # Replace every bar after `at` with something wildly different.
        wrecked = list(rows[: at + 1]) + [
            (t, o * 5, h * 5, low * 5, c * 5, v) for (t, o, h, low, c, v) in rows[at + 1 :]
        ]
        bars2, _ = candles.read(write_bars(tmp_path / "b_1d_test.csv.gz", wrecked))
        after = candles.features(bars2, candles.true_range(bars2), at)

        assert before == pytest.approx(after), "a feature moved when only the future changed"

    def test_the_true_range_is_causal_too(self, tmp_path: Path):
        """It feeds almost every feature and the label band, so if it peeks,
        everything does."""
        rows = fake_bars()
        at = 300
        bars, _ = candles.read(write_bars(tmp_path / "c_1d_test.csv.gz", rows))
        keep = candles.true_range(bars)[at]
        wrecked = list(rows[: at + 1]) + [
            (t, o, h * 10, low, c, v) for (t, o, h, low, c, v) in rows[at + 1 :]
        ]
        bars2, _ = candles.read(write_bars(tmp_path / "d_1d_test.csv.gz", wrecked))
        assert candles.true_range(bars2)[at] == pytest.approx(keep)


class TestLabelsMustSeeForward:
    """The other half, and it is not a formality.

    A supervised label is *defined* by looking ahead. If one of these ever stops
    changing when the future changes, the family has quietly become a function of
    the past and would train to near-perfect accuracy against itself.
    """

    @pytest.mark.parametrize("family", ["banded", "triple", "speed", "expansion", "seasonal"])
    def test_a_label_changes_when_the_future_changes(self, tmp_path: Path, family: str):
        rows = fake_bars()
        at, horizon = 300, 5
        bars, _ = candles.read(write_bars(tmp_path / f"e{family}_1d_test.csv.gz", rows))
        tr = candles.true_range(bars)
        y, _ret, valid, names = labels.FAMILIES[family](bars, tr, horizon, 1.0)
        assert valid[at]

        # Push the forward window *against* whatever the label currently says, so
        # a label already pinned at the top class still has somewhere to move. A
        # fixed upward push passes for five families and silently cannot move
        # `triple` when that bar already resolved as `target`.
        away = 0.6 if y[at] >= len(names) - 1 else 1.55
        pushed = list(rows)
        for i in range(at + 1, at + horizon + 1):
            t, o, h, low, c, v = pushed[i]
            pushed[i] = (t, o * away, h * (away + 0.05), low * (away - 0.05), c * away, v)
        bars2, _ = candles.read(write_bars(tmp_path / f"f{family}_1d_test.csv.gz", pushed))
        y2, _r2, _v2, _n2 = labels.FAMILIES[family](bars2, candles.true_range(bars2), horizon, 1.0)

        assert y[at] != y2[at], f"{family} did not react to its own forward window"

    def test_regime_needs_a_longer_horizon_and_says_so(self, one_file: Path, capsys):
        """A variance ratio over five bars means nothing, so the family declines.
        It used to decline by raising `IndexError` three frames away."""
        panel = candles.build([one_file], family="regime", horizon=5, band=1.0)
        assert len(panel) == 0
        assert panel.x.shape == (0, len(candles.FEATURE_NAMES))
        said = capsys.readouterr().out
        assert "horizon" in said, said
        assert "8 bars" in said, said

    def test_regime_works_once_the_horizon_is_long_enough(self, one_file: Path):
        panel = candles.build([one_file], family="regime", horizon=20, band=1.0, verbose=False)
        assert len(panel) > 100


class TestNoFeatureIsTheLabel:
    @pytest.mark.parametrize("family", ["banded", "triple", "speed"])
    def test_nothing_correlates_almost_perfectly_with_its_own_label(
        self, one_file: Path, family: str
    ):
        """The AUC-1.000 incident, as a standing check. A forward return left in
        the feature table would show up here at ~1.0."""
        panel = candles.build([one_file], family=family, horizon=5, band=1.0, verbose=False)
        assert len(panel) > 100
        for i, name in enumerate(panel.names):
            column = panel.x[:, i].astype(float)
            if column.std() == 0:
                continue
            r = abs(float(np.corrcoef(column, panel.y.astype(float))[0, 1]))
            assert r < 0.9, f"{name} correlates {r:.3f} with the label - it is the label"


class TestTheSplitsHoldTheBoundary:
    def test_training_never_reaches_into_the_test_period(self, one_file: Path):
        """Purge and embargo, checked in the units that matter: bar timestamps.

        A training row labelled `horizon` bars ahead must not have that window
        land on or after the first test bar.
        """
        panel = candles.build([one_file], family="banded", horizon=5, band=1.0, verbose=False)
        spacing = float(np.median(np.diff(np.sort(panel.when))))
        folds = list(splits.walk_forward(panel.when, panel.horizon, folds=4))
        assert folds, "no folds were produced"
        for train, test in folds:
            reach = panel.when[train].max() + panel.horizon * spacing
            assert reach <= panel.when[test].min(), "a training label reached into the test period"

    def test_the_embargo_leaves_a_real_gap(self, one_file: Path):
        panel = candles.build([one_file], family="banded", horizon=5, band=1.0, verbose=False)
        spacing = float(np.median(np.diff(np.sort(panel.when))))
        for train, test in splits.walk_forward(panel.when, panel.horizon, folds=4):
            gap = (panel.when[test].min() - panel.when[train].max()) / spacing
            assert gap >= splits.WARMUP, f"gap of only {gap:.0f} bars"

    def test_leave_one_out_never_trains_on_the_held_out_instrument(self, tmp_path: Path):
        paths = [
            write_bars(tmp_path / f"{name}_1d_test.csv.gz", fake_bars(seed=seed))
            for seed, name in enumerate(("alpha", "beta", "gamma"))
        ]
        panel = candles.build(paths, family="banded", horizon=5, band=1.0, verbose=False)
        seen = list(splits.leave_one_out(panel.groups, panel.when, panel.horizon))
        assert seen, "no instruments were held out"
        for name, train, test in seen:
            assert name not in set(panel.groups[train].tolist()), name
            assert set(panel.groups[test].tolist()) == {name}
            # And the time cut is kept, or this measures correlation, not forecasting.
            assert panel.when[test].min() > panel.when[train].max()


class TestTheNullIsTheRightShape:
    def test_a_block_shuffle_keeps_the_class_balance(self, one_file: Path):
        panel = candles.build([one_file], family="banded", horizon=5, band=1.0, verbose=False)
        shuffled = splits.block_shuffle(panel.y, panel.when, panel.horizon)
        assert np.array_equal(np.bincount(shuffled), np.bincount(panel.y))

    def test_it_actually_moves_the_labels(self, one_file: Path):
        panel = candles.build([one_file], family="banded", horizon=5, band=1.0, verbose=False)
        shuffled = splits.block_shuffle(panel.y, panel.when, panel.horizon)
        assert (shuffled != panel.y).mean() > 0.1, "the null is not a null"


class TestBarsAreRepairedAndCounted:
    def test_a_close_outside_the_range_is_widened_and_counted(self, tmp_path: Path):
        """Yahoo does this on up to 6% of rows. Silently trusting it breaks every
        first-passage label; silently dropping it breaks contiguity. So: repair
        minimally, and count."""
        rows = [
            (1_600_000_000, 100.0, 101.0, 99.0, 100.5, 1.0),
            (1_600_086_400, 100.5, 101.0, 100.0, 105.0, 1.0),  # close above the high
        ]
        bars, repaired = candles.read(write_bars(tmp_path / "g_1d_test.csv.gz", rows))
        assert repaired == 1
        assert bars[1, 2] == 105.0, "the high should have been widened to hold the close"
        assert bars[1, 3] == 100.0, "the low should not have moved"

    def test_the_repair_count_reaches_the_panel(self, tmp_path: Path):
        rows = fake_bars()
        rows[50] = (rows[50][0], 100.0, 101.0, 99.0, 140.0, 1.0)
        path = write_bars(tmp_path / "h_1d_test.csv.gz", rows)
        panel = candles.build([path], family="banded", horizon=5, band=1.0, verbose=False)
        assert panel.repairs.get("h") == 1, panel.repairs


class TestTheTripleBarrierIsBiasedAgainstTheTrade:
    def test_a_bar_touching_both_barriers_counts_as_a_stop(self):
        """A bar does not record which of its extremes arrived first, so the
        ambiguity is resolved against the trade. That biases every result
        downward, which is the direction an honest bias points."""
        bars = np.array(
            [
                [0, 100.0, 100.5, 99.5, 100.0],
                # Reaches far both ways in one bar: both barriers inside it.
                [86_400, 100.0, 130.0, 70.0, 100.0],
                [172_800, 100.0, 100.5, 99.5, 100.0],
            ]
        )
        tr = np.full(len(bars), 0.05)  # 5% of price, so barriers sit at 105 and 95
        side, took = labels._first_passage(bars, tr, horizon=1, band=1.0)
        assert side[0] == -1, "both touched should resolve as the adverse side"
        assert took[0] == 1


class TestCandleShapeIsScaleFree:
    def test_multiplying_every_price_leaves_the_windows_alone(self, tmp_path: Path):
        """**The units lesson, as a test.** A convolution fed raw prices learns the
        price level. Gold at 400 and gold at 4,300 must look identical here."""
        rows = fake_bars()
        small = write_bars(tmp_path / "i_1d_test.csv.gz", rows)
        big = write_bars(
            tmp_path / "j_1d_test.csv.gz",
            [(t, o * 40, h * 40, low * 40, c * 40, v) for (t, o, h, low, c, v) in rows],
        )
        one, _p1 = candles.sequences([small], family="banded", horizon=5, band=1.0)
        two, _p2 = candles.sequences([big], family="banded", horizon=5, band=1.0)
        assert one.shape == two.shape
        assert np.allclose(one, two, atol=1e-3), "the shape changed when only the scale did"


class TestGapsAreLevelsUntilPriceReturns:
    """The operator's reading of a fair value gap, which is not an event.

    A gap matters because price may come back to it later and react from the
    edge - and that edge is a **wick**, the low of the candle that opened a
    bullish gap. So the feature is a standing level with a distance, an age and
    the size of the origin wick, not a flag on one bar.
    """

    @staticmethod
    def _with_a_bullish_gap() -> np.ndarray:
        # Bar 2's low (105) sits above bar 0's high (101), so the band was
        # traded only by bar 1 - the classic three-candle gap at span 2.
        rows = [(100, 101, 99, 100), (100, 110, 100, 109), (109, 112, 105, 111)]
        rows += [(111, 113, 108, 112)] * 37  # price never returns to 105
        return np.array(
            [(i * 3600, o, h, low, c) for i, (o, h, low, c) in enumerate(rows)], dtype=float
        )

    def test_an_untouched_gap_stands_and_is_measured_from_its_wick(self):
        bars = self._with_a_bullish_gap()
        standing = candles.standing_gaps(bars, candles.true_range(bars))
        distance, age, wick = standing[20, :3]
        assert distance > 0, "an untouched gap should still be a level twenty bars later"
        assert 0 < age < 1, age
        assert wick > 0, "the origin candle's lower wick defines the edge"

    def test_price_returning_to_it_ends_it(self):
        """**The whole point.** A filled gap is not a level any more, and a
        feature that kept reporting one would be describing history."""
        bars = self._with_a_bullish_gap()
        filled = bars.copy()
        filled[10, 3] = 104.0  # a low that trades into the band
        filled[10, 4] = 106.0
        standing = candles.standing_gaps(filled, candles.true_range(filled))
        assert standing[20, 0] == 0.0, "a filled gap must stop counting"

    def test_the_formation_bar_is_not_yet_a_level(self):
        """Causality, and the reason both feature families exist. At the bar the
        gap forms there is nothing to come back to yet, so `standing_gaps` reports
        nothing and the instantaneous `gap_2_tr` feature carries formation."""
        bars = self._with_a_bullish_gap()
        standing = candles.standing_gaps(bars, candles.true_range(bars))
        assert standing[2, 0] == 0.0

    def test_size_and_shape_are_both_present(self):
        """A doji and a huge indecisive bar have identical shape fractions, so
        size in true ranges has to be carried separately or the operator's
        long-candle rule cannot be expressed at all."""
        for name in ("body_frac", "body_tr", "upper_wick", "upper_wick_tr"):
            assert name in candles.FEATURE_NAMES, name
        assert len(candles.FEATURE_NAMES) == 34, len(candles.FEATURE_NAMES)
