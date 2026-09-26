"""Price as a particle, done with physics rather than the metaphor.

Three standard tools, each fit on the first 60% of every series by time and tested on the last
40%, on 20 real instruments (FX, metals, crypto) with four exact random walks from the Deriv
synthetics as the control, at 15m, 1h and 1d.

1  Langevin / Fokker-Planck, by Kramers-Moyal estimation. Model the log-price as a particle,
   dx = D1(s) dt + sqrt(2 D2(s)) dW, and measure the force field directly: the drift D1 (the
   conditional mean move over h bars) and the diffusion D2 (its conditional variance) as
   functions of a state s. `barrier-geometry-is-irrelevant.md` says only drift can pay, so the
   test is whether the drift field measured on training data predicts the test block, and
   whether trading its sign pays net. States:
     eq    displacement from equilibrium, (log price - EMA50) / (baseline sqrt 50)
     eff   directional efficiency, 20-bar net move over path
     rng   position inside the 50-bar range, -0.5 at the low to +0.5 at the high (the zone idea)
   Plus the spring constant of an Ornstein-Uhlenbeck fit, dx = -k * eq + noise, on both blocks.
2  The quantum harmonic oscillator. Quantum-finance models the return density as a mixture of
   squared oscillator eigenfunctions |psi_n|^2 (Hermite functions). Fit on training returns
   standardised by an EWMA sigma, scored by out-of-sample log-likelihood against a Gaussian and a
   Student-t. A density model: it can say how fat the tails are, never which way.
3  "Collapsing the wave function" as Bayesian filtering. A latent drift mu_t that wanders
   (mu_t = mu_{t-1} + q eta), observed through each bar's return. A particle filter tracks the
   posterior cloud over mu_t; in this linear-Gaussian model its exact limit is the Kalman filter,
   used here. Trade the sign of the posterior drift when it is confidently away from zero - the
   noise q and the confidence threshold chosen on the training block.

Trades hold h bars from the next bar's open-to-close path (one bar of latency: the decision at
the close of bar t earns bars t+1..t+h), non-overlapping, net of spread (house assumption,
`questions.COST_V`; 0.15 for the synthetics), both halves of the test reported, and judged
against a null that shifts every series' positions by one common offset.

Run on the lab:
  ./.secrets/lab.sh run research/harness/physics.py SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=8
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.polynomial.hermite import hermval
from scipy import stats
from scipy.optimize import minimize
from scipy.special import factorial

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk

FAMILIES = {
    "fx": ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "EURJPY", "GBPJPY",
           "EURGBP", "AUDJPY", "EURAUD", "CHFJPY", "EURCHF", "USDCNH"],
    "metal": ["XAUUSD", "XAGUSD"],
    "crypto": ["BTCUSD", "ETHUSD", "SOLUSD"],
    "control": ["Volatility_25_Index", "Volatility_75_Index", "Volatility_100_Index", "Step_Index"],
}
COST_V = {"fx": 0.8, "metal": 0.16, "crypto": 0.5, "control": 0.15}
MINUTES = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}
HOLDS = {"15m": (4, 16), "1h": (4, 24), "4h": (3, 12), "1d": (5, 20)}
SECONDS = {k: v * 60 for k, v in MINUTES.items()}
RNG = np.random.default_rng(17)


def load(sym, interval):
    try:
        df = spikerisk.load(None, sym, "SEQLAB", interval)
    except (ValueError, FileNotFoundError) as exc:
        print(f"  skip {sym} {interval}: {str(exc)[:80]}")
        return None
    return df


def frame(interval):
    parts = []
    long = 250 if interval == "1d" else 500
    for family, syms in FAMILIES.items():
        for s in syms:
            df = load(s, interval)
            if df is None or len(df) < 3 * long:
                continue
            lc = np.log(df.close)
            r = lc.diff()
            base = r.abs().rolling(long, min_periods=long // 2).mean()
            f = pd.DataFrame({"sym": s, "family": family, "ts": df.ts, "lc": lc, "r": r, "base": base})
            f["eq"] = (lc - lc.ewm(span=50, adjust=False).mean()) / (base * np.sqrt(50))
            f["eff"] = (lc - lc.shift(20)) / r.abs().rolling(20).sum()
            hi = np.log(df.high).shift(1).rolling(50).max()
            lo = np.log(df.low).shift(1).rolling(50).min()
            f["rng"] = (lc - lo) / (hi - lo) - 0.5
            f["sigma"] = np.sqrt((r**2).ewm(alpha=1 / 30, adjust=False).mean().shift(1))
            for h in HOLDS[interval]:
                # decision at close t, earns t+1 .. t+h: one bar of latency
                f[f"fwd{h}"] = (lc.shift(-(h + 1)) - lc.shift(-1)) / base
            f["pos"] = np.arange(len(f))
            f["test"] = f.pos >= len(f) * 0.6
            f["half"] = f.pos >= len(f) * 0.8
            parts.append(f)
    return pd.concat(parts, ignore_index=True)


def score_trades(d, pos, h, interval, label):
    """Net per trade in baseline units, non-overlapping test entries, common-offset null."""
    cost = d.family.map(COST_V).to_numpy() / np.sqrt(MINUTES[interval] / 5)
    fwd = d[f"fwd{h}"].to_numpy()
    rows = []
    for fam in ["real", *FAMILIES]:
        fm = (d.family != "control").to_numpy() if fam == "real" else (d.family == fam).to_numpy()
        k = fm & d.test.to_numpy() & ((d.pos.to_numpy() % h) == 0) & np.isfinite(fwd)
        trade = k & (pos != 0)
        if trade.sum() < 30:
            continue
        net = pos[trade] * fwd[trade] - cost[trade]
        a, b = net[~d.half.to_numpy()[trade]].mean(), net[d.half.to_numpy()[trade]].mean()
        # common-offset null: shift each series' test positions by the same fraction
        null = []
        per = [(pos[k & (d.sym == s).to_numpy()], fwd[k & (d.sym == s).to_numpy()], cost[k & (d.sym == s).to_numpy()])
               for s in d.sym[fm].unique()]
        for _ in range(200):
            fr = RNG.uniform(0.1, 0.9)
            tot, n = 0.0, 0
            for p, f_, c in per:
                if len(p) < 5:
                    continue
                q = np.roll(p, int(fr * len(p)))
                tot += (q[q != 0] * f_[q != 0] - c[q != 0]).sum()
                n += (q != 0).sum()
            null.append(tot / max(n, 1))
        null = np.array(null)
        z = (net.mean() - null.mean()) / max(null.std(), 1e-12)
        rows.append(f"{fam} n={trade.sum()} net {net.mean():+.3f}+-{net.std() / np.sqrt(len(net)):.3f} "
                    f"({a:+.3f}/{b:+.3f}) z {z:+.1f}")
    print(f"    {label:<38} " + " | ".join(rows))


# ------------------------------------------------------------------------------ 1


def kramers_moyal(d, interval):
    print("\n  1  Kramers-Moyal drift field D1(s), trained on 60%, traded on 40% (units: baseline moves)")
    tr = ~d.test.to_numpy()
    for state in ("eq", "eff", "rng"):
        x = d[state].to_numpy()
        for h in HOLDS[interval]:
            fwd = d[f"fwd{h}"].to_numpy()
            ok = np.isfinite(x) & np.isfinite(fwd)
            edges = np.unique(np.nanquantile(x[tr & ok & (d.family != "control").to_numpy()],
                                              np.linspace(0, 1, 11)))
            b = np.clip(np.searchsorted(edges, x, side="right") - 1, 0, len(edges) - 2)
            pos = np.zeros(len(d))
            prof = []
            for fam_mask, name in (((d.family != "control").to_numpy(), "real"), ((d.family == "control").to_numpy(), "control")):
                for i in range(len(edges) - 1):
                    m = tr & ok & fam_mask & (b == i) & ((d.pos.to_numpy() % h) == 0)
                    if m.sum() < 30:
                        continue
                    mu, se = fwd[m].mean(), fwd[m].std() / np.sqrt(m.sum())
                    if name == "real":
                        prof.append(f"{mu:+.2f}")
                    # trade only bins whose training drift is at least two standard errors from zero
                    if abs(mu) > 2 * se:
                        pos[fam_mask & (b == i)] = np.sign(mu)
            te = ~tr & ok & ((d.pos.to_numpy() % h) == 0)
            realm = te & (d.family != "control").to_numpy()
            # out-of-sample: does the training drift field line up with the test drift field?
            test_prof = [fwd[realm & (b == i)].mean() for i in range(len(edges) - 1)]
            train_prof = [float(p) for p in prof] if len(prof) == len(test_prof) else None
            agree = (np.corrcoef(train_prof, test_prof)[0, 1] if train_prof else np.nan)
            print(f"   {state:<4} h={h:<3} D1 by decile (train, real): {' '.join(prof)} | "
                  f"train-test profile corr {agree:+.2f}")
            score_trades(d, pos, h, interval, f"trade sign(D1) where |D1| > 2 SE, h={h}")
    # the spring: Ornstein-Uhlenbeck restoring constant, one-bar
    for blk, m in (("train", ~d.test.to_numpy()), ("test", d.test.to_numpy())):
        out = []
        for fam in FAMILIES:
            k = m & (d.family == fam).to_numpy()
            x, y = d["eq"].to_numpy()[k], (d["r"].groupby(d["sym"]).shift(-1) / d["base"]).to_numpy()[k]
            ok = np.isfinite(x) & np.isfinite(y)
            res = stats.linregress(x[ok], y[ok])
            out.append(f"{fam} slope {res.slope:+.4f} (t {res.slope / res.stderr:+.1f})")
        print(f"   OU spring, next-bar move on displacement, {blk}: " + " | ".join(out))


# ------------------------------------------------------------------------------ 2


def hermite_density(x, w, s):
    """sum_n w_n |psi_n(x/s)|^2 / s, psi_n the normalised Hermite functions."""
    u = x / s
    out = np.zeros_like(u)
    for n, wn in enumerate(w):
        c = np.zeros(n + 1)
        c[n] = 1
        psi = hermval(u, c) * np.exp(-u**2 / 2) / np.sqrt(2**n * factorial(n) * np.sqrt(np.pi))
        out += wn * psi**2
    return out / s


def qho(d):
    print("\n  2  Quantum harmonic oscillator density vs Gaussian and Student-t, next-bar returns / EWMA sigma")
    z = (d.r / d.sigma).to_numpy()
    for fam in ["real", *FAMILIES]:
        fm = (d.family != "control").to_numpy() if fam == "real" else (d.family == fam).to_numpy()
        tr = fm & ~d.test.to_numpy() & np.isfinite(z)
        te = fm & d.test.to_numpy() & np.isfinite(z)
        ztr = z[tr]
        if len(ztr) > 200_000:
            ztr = RNG.choice(ztr, 200_000, replace=False)
        ztr = np.clip(ztr, -12, 12)
        zte = np.clip(z[te], -12, 12)
        ll_norm = stats.norm.logpdf(zte, *stats.norm.fit(ztr)).mean()
        tpar = stats.t.fit(ztr)
        ll_t = stats.t.logpdf(zte, *tpar).mean()
        best = None
        for n_states in (1, 3, 5):
            def nll(p, n_states=n_states):
                w = np.exp(p[:n_states]) / np.exp(p[:n_states]).sum()
                return -np.log(hermite_density(ztr, w, np.exp(p[-1])) + 1e-300).mean()
            p0 = np.concatenate([np.zeros(n_states), [0.0]])
            fit = minimize(nll, p0, method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-4, "fatol": 1e-6})
            w = np.exp(fit.x[:n_states]) / np.exp(fit.x[:n_states]).sum()
            ll = np.log(hermite_density(zte, w, np.exp(fit.x[-1])) + 1e-300).mean()
            if best is None or ll > best[0]:
                best = (ll, n_states, w)
        print(f"    {fam:<8} test log-lik per bar: Gaussian {ll_norm:+.4f} | Student-t {ll_t:+.4f} (df {tpar[0]:.1f}) | "
              f"QHO {best[0]:+.4f} ({best[1]} states, weights {' '.join(f'{v:.2f}' for v in best[2])})")


# ------------------------------------------------------------------------------ 3


def kalman_drift(r, sigma, q):
    """Posterior mean and sd of a random-walk drift observed through returns (per series)."""
    n = len(r)
    m, P = 0.0, 1e-8
    mean, sd = np.full(n, np.nan), np.full(n, np.nan)
    for t in range(n):
        mean[t], sd[t] = m, np.sqrt(P)  # the belief before bar t is seen: causal
        s2 = sigma[t] ** 2 if np.isfinite(sigma[t]) and sigma[t] > 0 else np.nan
        P = P + q**2 * (s2 if np.isfinite(s2) else 0.0)
        if np.isfinite(r[t]) and np.isfinite(s2):
            K = P / (P + s2)
            m = m + K * (r[t] - m)
            P = (1 - K) * P
    return mean, sd


def filtering(d, interval):
    print("\n  3  Collapsing the drift's wave function: Kalman (the particle filter's exact limit here)")
    best = None
    for q in (0.003, 0.01, 0.03, 0.1):
        snr = np.full(len(d), np.nan)
        for s, g in d.groupby("sym"):
            idx = g.index.to_numpy()
            mean, sd = kalman_drift(g.r.shift(-0).to_numpy(), g.sigma.to_numpy(), q)
            # decision at close t uses the belief after bar t: shift the before-belief back one
            mean_after = np.concatenate([mean[1:], [np.nan]])
            sd_after = np.concatenate([sd[1:], [np.nan]])
            snr[idx] = mean_after / sd_after
        tr = ~d.test.to_numpy() & np.isfinite(snr) & (d.family != "control").to_numpy()
        h = HOLDS[interval][0]
        fwd = d[f"fwd{h}"].to_numpy()
        k = tr & np.isfinite(fwd) & ((d.pos.to_numpy() % h) == 0)
        ic = stats.spearmanr(snr[k], fwd[k]).statistic
        if best is None or ic > best[0]:
            best = (ic, q, snr)
    ic, q, snr = best
    print(f"    chosen on training: q = {q} (train IC {ic:+.3f})")
    tr = ~d.test.to_numpy() & np.isfinite(snr)
    for h in HOLDS[interval]:
        th = np.nanquantile(np.abs(snr[tr & (d.family != "control").to_numpy()]), 0.8)
        pos = np.where(np.abs(snr) >= th, np.sign(snr), 0.0)
        pos[~np.isfinite(snr)] = 0.0
        score_trades(d, pos, h, interval, f"trade sign(posterior drift), top 20% |SNR|, h={h}")


def snr_column(d, q):
    """Kalman posterior drift over its sd, as believed after each bar closes."""
    snr = np.full(len(d), np.nan)
    for _, g in d.groupby("sym"):
        mean, sd = kalman_drift(g.r.to_numpy(), g.sigma.to_numpy(), q)
        snr[g.index.to_numpy()] = np.concatenate([mean[1:], [np.nan]]) / np.concatenate([sd[1:], [np.nan]])
    return snr


def mtf(base, htfs):
    """Multi-timeframe: each higher timeframe's state, from its last *completed* bar, joined onto
    every lower-timeframe decision; then a joint drift field and a timeframe-agreement rule."""
    d = frame(base)
    d["snr"] = snr_column(d, 0.01)
    d["close_t"] = d.ts + SECONDS[base]
    for htf in htfs:
        h_ = frame(htf)
        h_["snr"] = snr_column(h_, 0.01)
        h_["close_t"] = h_.ts + SECONDS[htf]
        cols = {c: f"{c}_{htf}" for c in ("eq", "eff", "rng", "snr")}
        joined = []
        for s, g in d.groupby("sym"):
            hh = h_[h_.sym == s][["close_t", *cols]].rename(columns=cols).sort_values("close_t")
            if hh.empty:
                continue
            m = pd.merge_asof(g[["close_t"]].reset_index().sort_values("close_t"), hh, on="close_t",
                              direction="backward", allow_exact_matches=True)
            joined.append(m.set_index("index"))
        j = pd.concat(joined)
        for c in cols.values():
            d[c] = j[c].reindex(d.index)
    print(f"\n{'=' * 110}\nMTF base {base} with {', '.join(htfs)}: {d.sym.nunique()} series, {len(d):,} bars")
    tr = ~d.test.to_numpy()
    real = (d.family != "control").to_numpy()
    for state in ("eq", "eff", "rng"):
        for htf in htfs:
            x, y = d[state].to_numpy(), d[f"{state}_{htf}"].to_numpy()
            ok_x = np.isfinite(x) & np.isfinite(y)
            ex = np.unique(np.nanquantile(x[tr & ok_x & real], [0, 1 / 3, 2 / 3, 1]))
            ey = np.unique(np.nanquantile(y[tr & ok_x & real], [0, 1 / 3, 2 / 3, 1]))
            bx = np.clip(np.searchsorted(ex, x, side="right") - 1, 0, len(ex) - 2)
            by = np.clip(np.searchsorted(ey, y, side="right") - 1, 0, len(ey) - 2)
            for h in HOLDS[base]:
                fwd = d[f"fwd{h}"].to_numpy()
                ok = ok_x & np.isfinite(fwd)
                pos = np.zeros(len(d))
                for fam_mask in (real, ~real):
                    for i in range(len(ex) - 1):
                        for j_ in range(len(ey) - 1):
                            m = tr & ok & fam_mask & (bx == i) & (by == j_) & ((d.pos.to_numpy() % h) == 0)
                            if m.sum() < 30:
                                continue
                            mu, se = fwd[m].mean(), fwd[m].std() / np.sqrt(m.sum())
                            if abs(mu) > 2 * se:
                                pos[fam_mask & (bx == i) & (by == j_)] = np.sign(mu)
                score_trades(d, pos, h, base, f"joint D1({state} {base} x {state} {htf}), h={h}")
    # agreement: the posterior drift points the same way on every timeframe
    snrs = [d["snr"].to_numpy()] + [d[f"snr_{h}"].to_numpy() for h in htfs]
    same = np.all([np.sign(v) == np.sign(snrs[0]) for v in snrs[1:]], axis=0) & np.all(
        [np.isfinite(v) for v in snrs], axis=0)
    th = np.nanquantile(np.abs(snrs[0][tr & real]), 0.8)
    for h in HOLDS[base]:
        pos = np.where(same & (np.abs(snrs[0]) >= th), np.sign(snrs[0]), 0.0)
        score_trades(d, pos, h, base, f"posterior drift agrees on all timeframes, h={h}")
        pos_any = np.where(same, np.sign(snrs[0]), 0.0)
        score_trades(d, pos_any, h, base, f"agreement alone (no |SNR| filter), h={h}")


if __name__ == "__main__":
    part = os.environ.get("PHYS_PART", "single")
    if part == "mtf":
        mtf("1h", ("4h", "1d"))
        mtf("15m", ("1h", "4h"))
    else:
        intervals = os.environ.get("INTERVALS", "15m,1h,1d").split(",")
        for interval in intervals:
            d = frame(interval)
            print(f"\n{'=' * 110}\n{interval}: {d.sym.nunique()} series, {len(d):,} bars; holds {HOLDS[interval]}")
            kramers_moyal(d, interval)
            qho(d)
            filtering(d, interval)
