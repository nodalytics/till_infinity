"""The PCA, OU and s-score pieces of pca_residuals.py on synthetic data with known answers."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import pca_residuals as PR  # noqa: E402


def test_bets_identity_and_one_factor():
    ent, pr = PR.bets(np.ones(10))
    assert abs(ent - 10) < 1e-9 and abs(pr - 10) < 1e-9
    ent, pr = PR.bets(np.r_[10.0, np.zeros(9)])
    assert abs(ent - 1) < 1e-9 and abs(pr - 1) < 1e-9


def test_one_factor_share():
    # N coins loading equally on one factor with correlation rho: lambda1 = 1 + (N-1) rho
    rng = np.random.default_rng(0)
    T, N, rho = 20000, 20, 0.5
    f = rng.standard_normal(T)
    R = np.sqrt(rho) * f[:, None] + np.sqrt(1 - rho) * rng.standard_normal((T, N))
    ev, V, sd = PR.eig_corr(R)
    assert abs(ev[0] - (1 + (N - 1) * rho)) < 0.3
    assert abs(ev[0] / ev.sum() - (1 + (N - 1) * rho) / N) < 0.02
    assert np.all(np.sign(V[:, 0]) == np.sign(V[0, 0]))


def test_marchenko_pastur_iid():
    rng = np.random.default_rng(1)
    T, N = 2000, 200
    ev, _, _ = PR.eig_corr(rng.standard_normal((T, N)))
    lo, hi = PR.mp_edges(N / T)
    assert ev[0] < hi * 1.05 and ev[-1] > lo * 0.9
    x = np.linspace(lo, hi, 20001)
    assert abs(np.trapezoid(PR.mp_density(x, N / T), x) - 1) < 0.01


def test_ou_fit_recovers_half_life():
    rng = np.random.default_rng(2)
    hl = 10.0
    b = 2 ** (-1 / hl)
    n, reps = 4000, 30
    x = np.zeros((n, reps))
    for t in range(1, n):
        x[t] = 0.3 * (1 - b) + b * x[t - 1] + rng.standard_normal(reps)
    bh, a, vz = PR.ou_fit(x)
    assert abs(np.median(np.log(2) / -np.log(bh)) - hl) < 1.0
    assert abs(np.median(a / (1 - bh)) - 0.3) < 0.3
    assert abs(np.median(vz) - 1) < 0.05


def test_residual_step_removes_factor_and_scores_stretch():
    rng = np.random.default_rng(3)
    W, N = 252, 15
    m = 0.02 * rng.standard_normal(W)
    beta = 1 + 0.3 * rng.standard_normal(N)
    phi = 2 ** (-1 / 5)
    x = np.zeros((W, N))
    for t in range(1, W):
        x[t] = phi * x[t - 1] + 0.01 * rng.standard_normal(N)
    # coin 0 ends far above its residual mean: s must be strongly positive
    x[-1, 0] += 0.08
    R = m[:, None] * beta[None, :] + np.diff(x, axis=0, prepend=0)
    st = PR.residual_step(R, 1, 60)
    # the market is gone from the residual: the fitted beta on PC1 tracks the true beta
    F = R[-60:] @ st["Q"].T
    resid = R[-60:] - np.column_stack([np.ones(60), F]) @ np.vstack([np.zeros((1, N)), st["beta"]])
    assert abs(np.corrcoef(resid[:, 1:].mean(1), m[-60:])[0, 1]) < 0.3
    assert st["valid"][0] and st["s"][0] > 1.5
    assert np.median(st["hl"][st["valid"]]) < 15


def test_hedge_is_factor_neutral_and_unit_gross():
    rng = np.random.default_rng(4)
    k, n = 3, 12
    beta = rng.standard_normal((k, n))
    Q = rng.standard_normal((k, n))
    pos = np.zeros((2, n))
    pos[0, [1, 4]] = [1, -1]
    pos[1, 2] = 1
    w = PR.hedge(pos, beta, Q)
    assert np.allclose(np.abs(w).sum(1), 1)
    # exposure of the book to factor j through the coins: sum_i w_i beta_ji equals what the
    # eigenportfolio legs remove: w = c (pos - (beta pos) Q), so w beta' = c (beta pos - (beta pos) Q beta')
    raw = pos - (pos @ beta.T) @ Q
    assert np.allclose(w, raw / np.abs(raw).sum(1, keepdims=True))


def test_pipeline_earns_on_ou_and_not_on_iid():
    out = {}
    for kind in ("ou", "iid"):
        P = PR.sim_panel(1500, 20, kind, seed=11, iv="1d")
        res = PR.run_pass(P, 1, [(1.25, 0.5, 20.0)])
        g = PR.daily(res, 0)
        out[kind] = (g["gross"].mean(), g["net"].mean(), len(res["trades"]))
    assert out["ou"][0] > 0 and out["ou"][1] > 0
    assert abs(out["iid"][0]) < out["ou"][0] / 3
    assert out["ou"][2] > 50 and out["iid"][2] > 50


def test_r_trades_geometry():
    P = PR.sim_panel(800, 12, "ou", seed=5, iv="1d")
    res = PR.run_pass(P, 1, [(1.25, 0.5, 20.0)])
    rt = PR.r_trades(P, res["trades"], 0)
    assert len(rt) > 20
    assert (rt["risk_atr"] >= 0.25 - 1e-9).all()
    assert (rt.loc[rt["how"] == "stop", "R"] < -0.9).all()
    for a, b in zip(PR.NS[:-1], PR.NS[1:]):
        assert rt[f"P{a}R"].mean() >= rt[f"P{b}R"].mean()


def test_funding_lands_on_the_held_bar(tmp_path, monkeypatch):
    # a settlement exactly at a bar's close belongs to that bar
    step = 14400
    ts0 = 1_700_000_000 // step * step
    s = np.array([ts0 + step, ts0 + step + 1, ts0 + 1])
    b = np.ceil((s - ts0 - step) / step).astype(int)
    assert list(b) == [0, 1, 0]
