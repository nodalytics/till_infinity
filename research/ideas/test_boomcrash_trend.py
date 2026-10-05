"""Checks for boomcrash_trend.py on paths we build: the spike detector, the channel, and the pipeline."""
import numpy as np

import boomcrash_trend as B


def test_detect_merges_and_ex_is_monotone():
    n = 2000
    ms = np.arange(n, dtype=np.int64) * 1000
    d = np.full(n - 1, -0.01)
    d[[100, 500, 501, 1500]] = [5.0, 3.0, 2.0, 7.0]          # 500 and 501 are one spike
    bid = 1000 + np.r_[0.0, np.cumsum(d)]
    first, last, J, ex, sub, outage = B.detect(ms, bid, +1, theta=1e-3)
    assert list(first) == [101, 501, 1501] and list(last) == [101, 502, 1501]
    assert np.allclose(np.exp(J) * bid[first - 1] - bid[first - 1], [5.0, 5.0, 7.0])
    assert (np.diff(ex) <= 0).all() and sub == 0 and not outage.any()


def test_crash_side_and_outage():
    ms = np.array([0, 1000, 2000, 200_000, 201_000], dtype=np.int64)
    bid = np.array([100.0, 100.01, 95.0, 90.0, 90.01])
    first, last, J, ex, sub, outage = B.detect(ms, bid, -1, theta=1e-3)
    assert list(first) == [2] and np.allclose(J, [np.log(100.01 / 95.0)])     # the move across the 198 s hole is no spike
    assert outage.sum() == 1


def test_lrc_r_matches_polyfit():
    rng = np.random.default_rng(0)
    c = np.cumsum(rng.normal(size=300)) + 0.05 * np.arange(300)
    b, R = B.lrc_r(c, 100)
    for t in (99, 150, 299):
        w = c[t - 99:t + 1]
        x = np.arange(100)
        assert np.isclose(b[t], np.polyfit(x, w, 1)[0])
        assert np.isclose(R[t], np.corrcoef(x, w)[0, 1])
    assert np.isnan(b[98])


def _meta(days):
    return dict(day0=20000, day_end=20000 + days - 1, split_day=20000 + days // 2, swap=-36.0)


def _path(days, p=1 / 300, seed=0, s=+1):
    rng = np.random.default_rng(seed)
    n = days * 86400
    ms = 20000 * 86400000 + np.arange(n, dtype=np.int64) * 1000
    par = dict(p=p, J=rng.exponential(3.0, 1000) + 0.5, grind=-rng.uniform(0, 4e-6, 10000))
    par["J"] *= 2e-6 * 300 / par["J"].mean()                 # closure in log units: E[J] = lambda E[g]
    bid = B.simulate(ms, 5000.0, par, s, seed)
    return ms, bid, bid + 0.1, par


def test_pipeline_on_a_constant_hazard_path():
    ms, bid, ask, _ = _path(30)
    res = B.analyse("boom_300", ms, bid, ask, 1.2e-5, _meta(30), by_day=False, trades=True)
    assert abs(res["rate"][0] * 300 - 1) < 0.1
    assert res["ex_share"]["15m"] == 0.0                     # the grind is one-signed: never aligned
    a = res["agg"]["15m|full|dir"].sum(0)
    r = (a[0, B.F_SPK] / a[0, B.F_TICKS]) / (a[1, B.F_SPK] / a[1, B.F_TICKS])
    assert 0.85 < r < 1.15
    assert len(res["trades"]) > 1000


def test_feedback_raises_the_aligned_hazard():
    rng = np.random.default_rng(3)
    days = 120
    ms = 20000 * 86400000 + np.arange(days * 86400, dtype=np.int64) * 1000
    par = dict(p=1 / 300, J=rng.exponential(3.0, 1000) + 0.5, grind=-rng.uniform(0, 4e-6, 10000))
    par["J"] *= 2e-6 * 300 / par["J"].mean()
    bid = B.simulate(ms, 5000.0, par, +1, 5, feedback=True, warm=None)
    res = B.analyse("boom_300", ms, bid, bid + 0.1, 1.2e-5, _meta(days), by_day=False, trades=False)
    a = res["agg"]["4h|full|dir"].sum(0)
    r = (a[0, B.F_SPK] / a[0, B.F_TICKS]) / (a[1, B.F_SPK] / a[1, B.F_TICKS])
    assert 1.12 < r < 1.4
