"""Direction 7: is there a market state manifold with recurring regions and distinguishable transitions?

The question, from the research program behind `research/papers/`: "Do financial markets exhibit
recurring regions in state space with statistically distinguishable transition distributions?"

The states are program.py's fractal embeddings - 32 bars of return, range and close location on each
of three timeframes, over the trailing baseline move - for 20 real instruments and four exact
random walks (the control), at a 15m or 1h base. Everything is fit on each series' first 60% by time
and scored on the last 40%.

1  Shape of the cloud. Intrinsic dimension (TwoNN) of real states, of the random walks' states, and
   of a Gaussian with the real states' covariance; the variance held by the leading principal
   components; and how much tighter k-means packs real states than it packs that Gaussian.
2  Regions. k-means with K = 8, 32, 128 on the real training states (16 principal components).
   Do the regions recur - is each one's share of the test block its share of the training block?
   Are they just instruments - mutual information between region and family or symbol?
3  Transitions. Region now -> region after 16 and 64 bars (same series). Information gain of the
   training transition matrix over the training occupancy, on the test block, in bits, real
   against control. The windows overlap, so persistence is partly mechanical; the control has the
   same overlap, and the real-minus-control gap is the market's.
4  Distinguishable outcomes. Each region's training mean of the signed move, the |move|, and the
   up-minus-down asymmetry of reaching +-2 baseline moves. Do these hold on the test block, region
   by region (correlation across regions)? Does the region forecast |move| beyond the volatility
   ratio? Does it forecast direction, and does that trade?

Run on the lab:
  BASE=15m SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=14 python research/harness/manifold.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from scipy import stats
from sklearn.cluster import MiniBatchKMeans
from sklearn.decomposition import PCA
from sklearn.metrics import mutual_info_score, normalized_mutual_info_score, roc_auc_score
from sklearn.neighbors import NearestNeighbors

sys.path.insert(0, str(Path(__file__).parent))
import program
from program import H, LADDER, RNG, BASE

KS = (8, 32, 128)
LAGS = (H, 4 * H)
REACH = 2.0  # baseline moves, for the up/down asymmetry


def twonn(X):
    """TwoNN intrinsic dimension (Facco et al. 2017), maximum likelihood form, 10% longest ratios trimmed."""
    d, _ = NearestNeighbors(n_neighbors=3).fit(X).kneighbors(X)
    r1, r2 = d[:, 1], d[:, 2]
    ok = r1 > 0
    mu = np.sort(r2[ok] / r1[ok])
    mu = mu[: int(0.9 * len(mu))]
    return len(mu) / np.log(mu).sum()


def gaussian_like(X, n):
    return RNG.multivariate_normal(X.mean(0), np.cov(X, rowvar=False), size=n, method="eigh")


def shape(c, real, tr):
    print("\n  1  SHAPE OF THE CLOUD - intrinsic dimension (TwoNN, 20,000 states), leading-component variance")
    emb = c["emb"]
    out = {}
    for name, m in (("real", real & tr), ("control", ~real & tr)):
        idx = RNG.choice(np.flatnonzero(m), min(20_000, m.sum()), replace=False)
        X = emb[idx].astype(np.float64)
        g = gaussian_like(X, len(X))
        pca = PCA(n_components=64, svd_solver="randomized", random_state=0).fit(X)
        cum = np.cumsum(pca.explained_variance_ratio_)
        out[name] = (twonn(X), twonn(g))
        print(f"    {name:<8} ambient {X.shape[1]}, TwoNN {out[name][0]:5.1f} | Gaussian with its covariance {out[name][1]:5.1f} | "
              f"variance in 2 / 16 / 64 components {cum[1]:.2f} / {cum[15]:.2f} / {cum[63]:.2f}")
    for fam in ("fx", "metal", "crypto"):
        m = (c["family"] == fam) & tr
        idx = RNG.choice(np.flatnonzero(m), min(20_000, m.sum()), replace=False)
        print(f"    {fam:<8} TwoNN {twonn(emb[idx].astype(np.float64)):5.1f}")


def main():
    c = program.build()
    n = len(c["t"])
    real = c["family"] != "control"
    tr, te = ~c["test"], c["test"]
    print(f"\n{'=' * 110}\nMANIFOLD base {BASE} (ladder {', '.join(LADDER)}), H={H}, {len(np.unique(c['sym']))} series, {n:,} moments")

    shape(c, real, tr)

    # principal components of the real training states, applied to everything
    fit_idx = RNG.choice(np.flatnonzero(real & tr), min(200_000, (real & tr).sum()), replace=False)
    pca = PCA(n_components=16, svd_solver="randomized", random_state=0).fit(c["emb"][fit_idx])
    Z = pca.transform(c["emb"]).astype(np.float32)

    # moment -> the same series' moment `lag` bars later
    key = {(s, t): i for i, (s, t) in enumerate(zip(c["sym"], c["t"]))}
    nxt = {lag: np.array([key.get((s, t + lag), -1) for s, t in zip(c["sym"], c["t"])]) for lag in LAGS}

    mag = np.abs(c["end"])
    up_hit = (c["up"] >= REACH).any(1).astype(float)
    dn_hit = (c["dn"] >= REACH).any(1).astype(float)
    lsig = np.log(c["sigr"])
    resid = mag - np.polyval(np.polyfit(lsig[real & te], mag[real & te], 1), lsig)

    for K in KS:
        print(f"\n  K = {K} regions")
        km = MiniBatchKMeans(n_clusters=K, batch_size=8192, n_init=3, random_state=0).fit(Z[fit_idx])
        lab = km.predict(Z)

        # --- 1b clusteredness: inertia per point against a Gaussian with the same covariance
        g = gaussian_like(Z[fit_idx].astype(np.float64), len(fit_idx)).astype(np.float32)
        kg = MiniBatchKMeans(n_clusters=K, batch_size=8192, n_init=3, random_state=0).fit(g)
        ctl_idx = np.flatnonzero(~real & tr)
        kc = MiniBatchKMeans(n_clusters=K, batch_size=8192, n_init=3, random_state=0).fit(Z[ctl_idx])
        gc = gaussian_like(Z[ctl_idx].astype(np.float64), len(ctl_idx)).astype(np.float32)
        kgc = MiniBatchKMeans(n_clusters=K, batch_size=8192, n_init=3, random_state=0).fit(gc)
        print(f"    clusteredness: k-means inertia / that of a same-covariance Gaussian - real {km.inertia_ / kg.inertia_:.3f} | "
              f"control {kc.inertia_ / kgc.inertia_:.3f}   (1.0 = no more clustered than a Gaussian)")

        # --- 2 recurrence and identity
        occ_tr = np.bincount(lab[real & tr], minlength=K) / (real & tr).sum()
        occ_te = np.bincount(lab[real & te], minlength=K) / (real & te).sum()
        tv = 0.5 * np.abs(occ_tr - occ_te).sum()
        empty = int((np.bincount(lab[real & te], minlength=K) == 0).sum())
        nmi_f = normalized_mutual_info_score(c["family"][real & te], lab[real & te])
        nmi_s = normalized_mutual_info_score(c["sym"][real & te], lab[real & te])
        # hour of day as a check that regions are not the session clock
        nmi_h = normalized_mutual_info_score(c["hour"][real & te], lab[real & te])
        print(f"    recurrence: occupancy train vs test, total variation {tv:.3f}, empty regions on test {empty} | "
              f"NMI with family {nmi_f:.3f}, symbol {nmi_s:.3f}, hour {nmi_h:.3f}")

        # --- 3 transitions
        for lag in LAGS:
            res = []
            for name, fm in (("real", real), ("control", ~real)):
                base_rows = fm & ((c["t"] % lag) == 0) & (nxt[lag] >= 0)
                a_tr = base_rows & tr & (c["test"][np.maximum(nxt[lag], 0)] == 0)
                a_te = base_rows & te
                T = np.ones((K, K))
                np.add.at(T, (lab[a_tr], lab[nxt[lag][a_tr]]), 1)
                T /= T.sum(1, keepdims=True)
                occ = (np.bincount(lab[nxt[lag][a_tr]], minlength=K) + 1.0)
                occ /= occ.sum()
                i, j = lab[a_te], lab[nxt[lag][a_te]]
                ll_t = -np.log2(T[i, j]).mean()
                ll_o = -np.log2(occ[j]).mean()
                stay = np.mean(i == j)
                stay0 = np.sum(occ ** 2)
                res.append(f"{name} gain {ll_o - ll_t:.3f} bits of {ll_o:.2f}, stay {stay:.3f} (chance {stay0:.3f}), n={a_te.sum()}")
            print(f"    transitions after {lag:>3} bars: " + " | ".join(res))

        # --- 4 outcomes by region: do training properties hold on test, region by region
        rows = []
        for name, fm in (("real", real), ("control", ~real)):
            m_tr, m_te = fm & tr, fm & te
            cnt_tr = np.bincount(lab[m_tr], minlength=K)
            cnt_te = np.bincount(lab[m_te], minlength=K)
            ok = (cnt_tr >= 300) & (cnt_te >= 300)

            def by(v, m, cnt):
                return np.bincount(lab[m], weights=v[m], minlength=K) / np.maximum(cnt, 1)

            s_end = (by(c["end"], m_tr, cnt_tr), by(c["end"], m_te, cnt_te))
            s_mag = (by(mag, m_tr, cnt_tr), by(mag, m_te, cnt_te))
            s_asy = (by(up_hit - dn_hit, m_tr, cnt_tr), by(up_hit - dn_hit, m_te, cnt_te))
            cor = [stats.spearmanr(a[ok], b[ok]).statistic if ok.sum() > 3 else np.nan for a, b in (s_end, s_mag, s_asy)]
            # the moment-level forecasts: the region's training mean
            f_mag = s_mag[0][lab]
            f_end = s_end[0][lab]
            k = m_te & ok[lab]
            rho = stats.spearmanr(f_mag[k], mag[k]).statistic
            rho_r = stats.spearmanr(f_mag[k], resid[k]).statistic
            auc = roc_auc_score(c["end"][k] > 0, f_end[k])
            rows.append(f"{name}: regions {ok.sum()}, train-vs-test across regions: signed move {cor[0]:+.2f}, "
                        f"|move| {cor[1]:+.2f}, up-down asymmetry {cor[2]:+.2f} | moment level: |move| {rho:+.3f}, "
                        f"beyond vol {rho_r:+.3f}, direction AUC {auc:.3f}")
        for r in rows:
            print(f"    {r}")
        print(f"    (the volatility ratio alone: |move| Spearman {stats.spearmanr(lsig[real & te], mag[real & te]).statistic:+.3f} real)")

        # signed move per region: how far do the most extreme regions' training means carry
        m_tr = real & tr
        cnt = np.bincount(lab[m_tr], minlength=K)
        mean_tr = np.bincount(lab[m_tr], weights=c["end"][m_tr], minlength=K) / np.maximum(cnt, 1)
        sd_tr = np.sqrt(np.bincount(lab[m_tr], weights=c["end"][m_tr] ** 2, minlength=K) / np.maximum(cnt, 1) - mean_tr ** 2)
        # overlapping moments: count only every H-th bar as independent for the t-statistic
        eff = np.bincount(lab[m_tr & ((c["t"] % H) == 0)], minlength=K)
        tstat = mean_tr / (sd_tr / np.sqrt(np.maximum(eff, 1)))
        big = np.flatnonzero((np.abs(tstat) > 3) & (cnt >= 300))
        if len(big):
            m_te = real & te
            te_mean = np.array([c["end"][m_te & (lab == k)].mean() if (m_te & (lab == k)).sum() else np.nan for k in big])
            same = np.mean(np.sign(te_mean) == np.sign(mean_tr[big]))
            print(f"    regions with a training drift |t| > 3: {len(big)} of {K}; sign kept on test in {same:.0%} "
                  f"(train means {', '.join(f'{v:+.2f}' for v in mean_tr[big][:6])}; test {', '.join(f'{v:+.2f}' for v in te_mean[:6])})")
        else:
            print(f"    regions with a training drift |t| > 3: none of {K}")
        program.trade(c, mean_tr[lab], np.ones(n, bool), f"trade the region's training drift, K={K}")


def barriers(c):
    """Net of a long and of a short with symmetric stops and targets at +-REACH, resolved on wicks.

    A bar that reaches both levels is the stop; untouched after H bars, the trade exits at the close."""
    up_t = np.where((c["up"] >= REACH).any(1), (c["up"] >= REACH).argmax(1), H)
    dn_t = np.where((c["dn"] >= REACH).any(1), (c["dn"] >= REACH).argmax(1), H)
    long_ = np.where(up_t < dn_t, REACH, np.where(dn_t <= up_t, -REACH, 0.0))
    long_ = np.where((up_t == H) & (dn_t == H), c["end"], long_)
    short = np.where(dn_t < up_t, REACH, np.where(up_t <= dn_t, -REACH, 0.0))
    short = np.where((up_t == H) & (dn_t == H), -c["end"], short)
    return long_ - c["cost"], short - c["cost"]


def barrier_trade(c, sig, label, L, S):
    """program.trade with the barrier outcome: long in the training block's top 20% of `sig`, short in its bottom."""
    tr = ~c["test"]
    hi, lo = np.quantile(sig[tr], 0.8), np.quantile(sig[tr], 0.2)
    side = np.where(sig >= hi, 1, np.where(sig <= lo, -1, 0))
    out = []
    for name, fm in (("real", c["family"] != "control"), ("control", c["family"] == "control")):
        k = c["test"] & fm & (side != 0) & ((c["t"] % H) == 0)
        if k.sum() < 30:
            continue
        net = np.where(side[k] > 0, L[k], S[k])
        null = []
        for _ in range(150):
            f = RNG.uniform(0.1, 0.9)
            tot, cnt = 0.0, 0
            for s in np.unique(c["sym"][fm]):
                mm = c["test"] & (c["sym"] == s) & ((c["t"] % H) == 0)
                p = np.roll(side[mm], int(f * mm.sum()))
                tot += np.where(p > 0, L[mm], S[mm])[p != 0].sum()
                cnt += (p != 0).sum()
            null.append(tot / max(cnt, 1))
        null = np.array(null)
        wins = np.mean(net + c["cost"][k] > 0)  # gross win rate
        out.append(f"{name} n={k.sum()} win {wins:.3f} net {net.mean():+.3f}+-{net.std() / np.sqrt(k.sum()):.3f} "
                   f"({net[~c['half'][k]].mean():+.3f}/{net[c['half'][k]].mean():+.3f}) z {(net.mean() - null.mean()) / null.std():+.1f}")
    print(f"    {label:<44} " + " | ".join(out))


def follow():
    """Two follow-ups to the first run: are the transitions the clock, and does the region asymmetry pay?"""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import OneHotEncoder

    c = program.build()
    n = len(c["t"])
    real = c["family"] != "control"
    tr, te = ~c["test"], c["test"]
    print(f"\n{'=' * 110}\nMANIFOLD FOLLOW-UP base {BASE}, H={H}, {n:,} moments")
    fit_idx = RNG.choice(np.flatnonzero(real & tr), min(200_000, (real & tr).sum()), replace=False)
    pca = PCA(n_components=16, svd_solver="randomized", random_state=0).fit(c["emb"][fit_idx])
    Z = pca.transform(c["emb"]).astype(np.float32)
    key = {(s, t): i for i, (s, t) in enumerate(zip(c["sym"], c["t"]))}
    nxt = {lag: np.array([key.get((s, t + lag), -1) for s, t in zip(c["sym"], c["t"])]) for lag in LAGS}
    # volatility decile of now, cut on the real training block
    vdec = np.digitize(np.log(c["sigr"]), np.quantile(np.log(c["sigr"][real & tr]), np.linspace(0.1, 0.9, 9)))
    L, S = barriers(c)
    up_hit = (c["up"] >= REACH).any(1).astype(float)
    dn_hit = (c["dn"] >= REACH).any(1).astype(float)

    for K in (8, 32):
        km = MiniBatchKMeans(n_clusters=K, batch_size=8192, n_init=3, random_state=0).fit(Z[fit_idx])
        lab = km.predict(Z)
        print(f"\n  K = {K} regions")
        print("    next region, test log loss in bits (real); lower is better. 'clock' = hour of the next moment, 'vol' = volatility decile now")
        for lag in LAGS:
            base_rows = real & ((c["t"] % lag) == 0) & (nxt[lag] >= 0)
            a_tr = base_rows & tr & (c["test"][np.maximum(nxt[lag], 0)] == 0)
            a_te = base_rows & te
            y_tr, y_te = lab[nxt[lag][a_tr]], lab[nxt[lag][a_te]]
            cols = {"region": lab, "clock": c["hour"][np.maximum(nxt[lag], 0)], "vol": vdec}
            res = []
            for name, use in (("occupancy", ()), ("clock", ("clock",)), ("clock+vol", ("clock", "vol")),
                              ("region", ("region",)), ("region+clock+vol", ("region", "clock", "vol"))):
                if not use:
                    occ = np.bincount(y_tr, minlength=K) + 1.0
                    p = (occ / occ.sum())[y_te]
                else:
                    enc = OneHotEncoder(handle_unknown="ignore").fit(np.column_stack([cols[u][a_tr] for u in use]))
                    m = LogisticRegression(max_iter=300, C=0.5).fit(enc.transform(np.column_stack([cols[u][a_tr] for u in use])), y_tr)
                    P = m.predict_proba(enc.transform(np.column_stack([cols[u][a_te] for u in use])))
                    idx = np.searchsorted(m.classes_, y_te)
                    ok = (idx < len(m.classes_)) & (m.classes_[np.minimum(idx, len(m.classes_) - 1)] == y_te)
                    p = np.where(ok, P[np.arange(len(y_te)), np.minimum(idx, len(m.classes_) - 1)], 1e-4)
                res.append(f"{name} {-np.log2(np.clip(p, 1e-4, 1)).mean():.3f}")
            print(f"    after {lag:>3} bars: " + " | ".join(res))

        # the up/down asymmetry by region: size on test, and traded with symmetric barriers
        m_tr, m_te = real & tr, real & te
        cnt_tr = np.bincount(lab[m_tr], minlength=K)
        asy_tr = np.bincount(lab[m_tr], weights=(up_hit - dn_hit)[m_tr], minlength=K) / np.maximum(cnt_tr, 1)
        cnt_te = np.bincount(lab[m_te], minlength=K)
        asy_te = np.bincount(lab[m_te], weights=(up_hit - dn_hit)[m_te], minlength=K) / np.maximum(cnt_te, 1)
        base_tr = (up_hit - dn_hit)[m_tr].mean()
        o = np.argsort(asy_tr)
        print(f"    asymmetry P(reach +{REACH:g}) - P(reach -{REACH:g}), training mean {base_tr:+.3f}; most negative / most positive regions:")
        print("      train " + " ".join(f"{asy_tr[i]:+.3f}" for i in np.r_[o[:3], o[-3:]]))
        print("      test  " + " ".join(f"{asy_te[i]:+.3f}" for i in np.r_[o[:3], o[-3:]]))
        # is the asymmetry the recent move? its correlation with the last 20 bars' efficiency and velocity
        print(f"    region asymmetry vs moment's efficiency, velocity (Spearman, real test): "
              f"{stats.spearmanr(asy_tr[lab][m_te], c['eff'][m_te]).statistic:+.3f}, "
              f"{stats.spearmanr(asy_tr[lab][m_te], c['vel'][m_te]).statistic:+.3f}")
        barrier_trade(c, asy_tr[lab], f"barriers +-{REACH:g} on region asymmetry, K={K}", L, S)
        barrier_trade(c, -c["vel"], "barriers on -velocity (reversion, reference)", L, S)


if __name__ == "__main__":
    follow() if os.environ.get("PART") == "follow" else main()
