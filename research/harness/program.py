"""The research program from `research/papers/`: six directions, measured.

Papers 1-3 (drafts in `research/papers/`) propose a probabilistic model of market-state
transitions: the current state gives each candidate price zone a probability of being reached
(Paper 1), historical twins give an empirical version of the same (Paper 2), and the two combine
(Paper 3). A follow-up proposes seven more directions. Six are measured here, on 20 real
instruments and four exact random walks from the Deriv synthetics (the control), at a 15m base and
a 1h base, horizon H = 16 bars. Everything is fit, remembered or tuned on each series' first 60% by
time and scored on the last 40%.

Zones. Around every moment, a grid of levels at +-{1, 2, 3, 4, 6, 8} baseline moves - the
continuous probability field of direction 1 - plus the nearest untaken 50-bar swing high and low
(liquidity zones, sized by how many highs/lows cluster at them). "Hit" is a wick touching the level
within H bars; the time of the first touch is recorded.

1  Paper 3's decomposition, M0-M3, on P(hit within H):
     M0  physics: first passage of a random walk, 2(1 - Phi(d / (sigma sqrt H))), sigma from the
         EWMA - distance and volatility only, no fit
     M1  state only: gradient boosting on distance, zone kind and size, speed, directional
         efficiency and velocity (both toward the zone), the volatility ratio, the hour
     M2  memory only: the share of the 50 nearest historical twins (fractal embedding, 32 bars on
         each of three timeframes) that reached the same distance on the same side
     M3  combined: M1's inputs plus M2's evidence
   log loss, Brier, AUC; calibration in the top bin; and the field's up/down skew traded.
2  Hazard: a discrete-time hazard model, P(first touch at step t | not before, X), gradient boosting
   on the M3 inputs plus t. Its cumulative curve gives P(hit within 4, 8, 16 bars) and an expected
   time; scored against the physics first-passage curve, the twins' empirical curve, and a direct
   model per horizon.
3  Entropy and competition: normalise the 12 grid probabilities (M3) into a distribution over
   destinations; its Shannon entropy H, the change dH, and the top-two ratio R. Do they predict the
   size of the next move beyond the volatility ratio, its direction, or its speed?
4  Memory decay: twins drawn from all history older than the query (an embargo of H bars),
   the 500 most similar re-weighted by recency with half-lives 1 week, 1 month, 6 months,
   2 years, infinite; the half-life chosen on the first half of the test period and reported on
   the second, overall and in calm vs volatile regimes.
5  Impossibility region: the 95% boundary of adverse excursion over H for a long and a short, from
   twins, from a Gaussian, and from a gradient-boosted quantile model - coverage (target 5%
   exceedance) and width - and used as a stop against a fixed-width stop of the same median width,
   at equal money at risk.
6  The field itself: its skew (up-side minus down-side probability) as a direction signal, and how
   often it has a local maximum that the physics field does not.

Run on the lab:
  ./.secrets/lab.sh run research/harness/program.py BASE=15m SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=16
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from scipy import stats
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import spikerisk
from fractal_twins import FAMILIES, bars, normalise, windows

torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "8")))
RNG = np.random.default_rng(31)
BASE = os.environ.get("BASE", "15m")
LADDER = {"15m": ("15m", "1h", "4h"), "1h": ("1h", "4h", "1d")}[BASE]
SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
H = 16
GRID = (1.0, 2.0, 3.0, 4.0, 6.0, 8.0)
COST_V = {"fx": 0.8, "metal": 0.16, "crypto": 0.5, "control": 0.15}
STEP = 2  # moments every other bar


def gbm(**kw):
    return HistGradientBoostingClassifier(max_depth=4, learning_rate=0.06, max_iter=200, min_samples_leaf=300, **kw)


def build():
    out = []
    for family, syms in FAMILIES.items():
        for s in syms:
            try:
                close_t, per, lc, base, df = bars(s, LADDER[0])
                higher = [bars(s, tf) for tf in LADDER[1:]]
            except (ValueError, FileNotFoundError) as exc:
                print(f"  skip {s}: {str(exc)[:80]}")
                continue
            n = len(lc)
            idx = np.arange(600, n - H - 1, STEP)
            parts = [windows(per, idx, 32)]
            ok = np.ones(len(idx), bool)
            for ct, p_, _, _, _ in higher:
                j = np.searchsorted(ct, close_t[idx], side="right") - 1
                ok &= j >= 32
                parts.append(windows(p_, np.clip(j, 32, None), 32))
            emb = normalise(np.concatenate(parts, axis=1))
            hi, lo = np.log(df.high.to_numpy()), np.log(df.low.to_numpy())
            b = base[idx]
            up = np.column_stack([hi[idx + k] - lc[idx] for k in range(1, H + 1)]) / b[:, None]
            dn = np.column_stack([lc[idx] - lo[idx + k] for k in range(1, H + 1)]) / b[:, None]
            end = (lc[idx + H] - lc[idx]) / b
            r = np.diff(lc, prepend=np.nan)
            sig = pd.Series(r).pow(2).ewm(alpha=1 / 30, adjust=False).mean().pow(0.5).to_numpy()
            speed = pd.Series(np.abs(r)).rolling(10).mean().to_numpy() / base
            eff = (lc - np.concatenate([np.full(20, np.nan), lc[:-20]])) / pd.Series(np.abs(r)).rolling(20).sum().to_numpy()
            vel = pd.Series(r).rolling(5).mean().to_numpy() / base
            swing_hi = pd.Series(hi).shift(1).rolling(50).max().to_numpy()
            swing_lo = pd.Series(lo).shift(1).rolling(50).min().to_numpy()
            band = 0.25 * base
            size_hi = sum((np.concatenate([np.full(k, np.nan), hi[:-k]]) >= swing_hi - band).astype(float) for k in range(1, 51))
            size_lo = sum((np.concatenate([np.full(k, np.nan), lo[:-k]]) <= swing_lo + band).astype(float) for k in range(1, 51))
            hour = pd.to_datetime(df.ts.to_numpy()[idx], unit="s").hour.to_numpy()
            keep = ok & np.isfinite(b) & np.isfinite(up).all(1) & np.isfinite(dn).all(1) & np.isfinite(eff[idx]) & np.isfinite(swing_hi[idx])
            m = int(keep.sum())
            out.append(dict(
                family=np.full(m, family), sym=np.full(m, s), t=idx[keep], ts=df.ts.to_numpy()[idx][keep],
                emb=emb[keep], up=up[keep], dn=dn[keep], end=end[keep],
                sigr=(sig[idx] / base[idx])[keep], speed=speed[idx][keep], eff=eff[idx][keep], vel=vel[idx][keep],
                d_hi=((swing_hi[idx] - lc[idx]) / b)[keep], d_lo=((lc[idx] - swing_lo[idx]) / b)[keep],
                size_hi=size_hi[idx][keep], size_lo=size_lo[idx][keep], hour=hour[keep],
                test=(idx >= n * 0.6)[keep], half=(idx >= n * 0.8)[keep],
                cost=np.full(m, COST_V[family] / np.sqrt(SECONDS[LADDER[0]] / 300)),
            ))
    return {k: np.concatenate([o[k] for o in out]) for k in out[0]}


def zones(c):
    """One row per (moment, zone): the 12 grid levels and the two swing zones."""
    n = len(c["t"])
    rows = []
    for side in (1, -1):
        for d in GRID:
            rows.append(dict(m=np.arange(n), side=np.full(n, side), dist=np.full(n, d), kind=np.zeros(n), size=np.zeros(n)))
        dist = c["d_hi"] if side > 0 else c["d_lo"]
        size = c["size_hi"] if side > 0 else c["size_lo"]
        rows.append(dict(m=np.arange(n), side=np.full(n, side), dist=np.maximum(dist, 0.05), kind=np.ones(n), size=size))
    z = {k: np.concatenate([r[k] for r in rows]) for k in rows[0]}
    m = z["m"]
    path = np.where(z["side"][:, None] > 0, c["up"][m], c["dn"][m])  # excursion toward the zone
    touch = path >= z["dist"][:, None]
    z["hit"] = touch.any(1).astype(float)
    z["ttime"] = np.where(touch.any(1), touch.argmax(1) + 1, H + 1)
    return z


def features(c, z, analog=None):
    m = z["m"]
    s = z["side"]
    X = [np.log(z["dist"]), z["kind"], np.log1p(z["size"]), c["speed"][m], s * c["eff"][m], s * c["vel"][m],
         np.log(c["sigr"][m]), np.sin(2 * np.pi * c["hour"][m] / 24), np.cos(2 * np.pi * c["hour"][m] / 24), s]
    if analog is not None:
        X += list(analog)
    return np.nan_to_num(np.column_stack(X), nan=0.0, posinf=0.0, neginf=0.0)


def physics(c, z, steps=H):
    sig = c["sigr"][z["m"]] * np.sqrt(np.pi / 2)  # the EWMA sigma, in baseline units
    return np.clip(2 * (1 - stats.norm.cdf(z["dist"] / (sig * np.sqrt(steps)))), 1e-4, 1 - 1e-4)


def twin_index(c, mem, queries, k=50, spare=160):
    """The k nearest twins in `mem`, never one from the same series within H bars of the query.

    Without that exclusion a training query finds itself and its neighbours in time, whose futures
    overlap its own, so the evidence carries the query's outcome and a model fit on it learns to
    over-trust it (the first run's M3: top bin predicted 0.969, realised 0.884)."""
    E = torch.tensor(c["emb"][mem])
    sym = np.unique(c["sym"], return_inverse=True)[1]
    out = np.empty((len(queries), k), np.int64)
    for i in range(0, len(queries), 512):
        q = queries[i:i + 512]
        cand = mem[torch.topk(torch.tensor(c["emb"][q]) @ E.T, k + spare, dim=1).indices.numpy()]
        near = (sym[cand] == sym[q][:, None]) & (np.abs(c["t"][cand] - c["t"][q][:, None]) <= H)
        order = np.argsort(near, axis=1, kind="stable")[:, :k]  # the unexcluded first, similarity order kept
        assert not np.take_along_axis(near, order, 1).any(), "raise spare: too many twins excluded"
        out[i:i + 512] = np.take_along_axis(cand, order, 1)
    return out


def analog_evidence(c, z, nn_of_moment):
    """Share of each moment's twins reaching the zone's distance on its side, and their median time."""
    rows = len(z["m"])
    share, med = np.empty(rows), np.empty(rows)
    cdf = [np.empty(rows) for _ in range(3)]
    for i in range(0, rows, 50_000):  # (rows, k, H) in one piece would be ~16GB
        sl = slice(i, i + 50_000)
        nn = nn_of_moment[z["m"][sl]]
        path = np.where(z["side"][sl][:, None, None] > 0, c["up"][nn], c["dn"][nn])
        touch = path >= z["dist"][sl][:, None, None]
        hit = touch.any(2)
        t = np.where(hit, touch.argmax(2) + 1, H + 1)
        share[sl] = hit.mean(1)
        med[sl] = np.median(t, axis=1)
        for j, s in enumerate((4, 8, 16)):
            cdf[j][sl] = np.mean(hit & (t <= s), axis=1)
    return share, med, cdf


def score(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return f"logloss {log_loss(y, p):.4f} Brier {brier_score_loss(y, p):.4f} AUC {roc_auc_score(y, p):.3f}"


def trade(c, sig, rows, label):
    """Long when the signal is in the training block's top 20%, short in its bottom 20%."""
    tr = rows & ~c["test"]
    hi, lo = np.quantile(sig[tr], 0.8), np.quantile(sig[tr], 0.2)
    side = np.where(sig >= hi, 1.0, np.where(sig <= lo, -1.0, 0.0))
    out = []
    for name, fm in (("real", c["family"] != "control"), ("control", c["family"] == "control")):
        k = rows & c["test"] & fm & (side != 0) & ((c["t"] % H) == 0)
        if k.sum() < 30:
            continue
        net = side[k] * c["end"][k] - c["cost"][k]
        null = []
        for _ in range(150):
            f = RNG.uniform(0.1, 0.9)
            tot, n = 0.0, 0
            for s in np.unique(c["sym"][fm]):
                mm = rows & c["test"] & (c["sym"] == s) & ((c["t"] % H) == 0)
                p = np.roll(side[mm], int(f * mm.sum()))
                tot += (p[p != 0] * c["end"][mm][p != 0] - c["cost"][mm][p != 0]).sum()
                n += (p != 0).sum()
            null.append(tot / max(n, 1))
        null = np.array(null)
        out.append(f"{name} n={k.sum()} net {net.mean():+.3f}+-{net.std() / np.sqrt(k.sum()):.3f} "
                   f"({net[~c['half'][k]].mean():+.3f}/{net[c['half'][k]].mean():+.3f}) z {(net.mean() - null.mean()) / null.std():+.1f}")
    print(f"    {label:<40} " + " | ".join(out))


def main():
    c = build()
    n = len(c["t"])
    real = c["family"] != "control"
    tr_m, te_m = ~c["test"], c["test"]
    print(f"\n{'=' * 110}\nPROGRAM base {BASE} (ladder {', '.join(LADDER)}), H={H}, {len(np.unique(c['sym']))} series, {n:,} moments")

    # twins for every moment used: a training memory, queries = a training sample (to fit M2/M3) and the test moments
    mem = RNG.choice(np.flatnonzero(tr_m), min(300_000, tr_m.sum()), replace=False)
    q_tr = RNG.choice(np.flatnonzero(tr_m), min(60_000, tr_m.sum()), replace=False)
    q_te = np.flatnonzero(te_m & ((c["t"] % 4) == 0))
    used = np.concatenate([q_tr, q_te])
    nn_of = np.zeros((n, 50), np.int64)
    nn_of[used] = twin_index(c, mem, used)
    keep_m = np.zeros(n, bool)
    keep_m[used] = True

    z = zones(c)
    zmask = keep_m[z["m"]]
    z = {k: v[zmask] for k, v in z.items()}
    zm = z["m"]
    ztr, zte = c["test"][zm] == 0, c["test"][zm] == 1
    zreal = real[zm]
    share, t_med, a_cdf = analog_evidence(c, z, nn_of)
    y = z["hit"]

    # ---------------------------------------------------------------- 1  M0-M3
    print("\n  1  PAPER 3 DECOMPOSITION - P(zone reached within H), test block")
    p0 = physics(c, z)
    X1 = features(c, z)
    X3 = features(c, z, [share, np.log(t_med)])
    m1 = gbm().fit(X1[ztr], y[ztr])
    p1 = m1.predict_proba(X1)[:, 1]
    # M2: the analogue share, calibrated on training moments by a one-feature logistic fit
    m2 = gbm().fit(np.column_stack([share, z["kind"]])[ztr], y[ztr])
    p2 = m2.predict_proba(np.column_stack([share, z["kind"]]))[:, 1]
    m3 = gbm().fit(X3[ztr], y[ztr])
    p3 = m3.predict_proba(X3)[:, 1]
    for name, p in (("M0 physics (no fit)", p0), ("M1 state only", p1), ("M2 memory only", p2), ("M3 combined", p3)):
        print(f"    {name:<22} real {score(y[zte & zreal], p[zte & zreal])} | control {score(y[zte & ~zreal], p[zte & ~zreal])}")
    for name, p in (("M1", p1), ("M3", p3)):
        top = zte & zreal & (p >= 0.95)
        if top.sum():
            print(f"    {name} top bin: predicted {p[top].mean():.3f}, realised {y[top].mean():.3f} (n={top.sum():,})")

    # ---------------------------------------------------------------- 6  the field and its skew
    print("\n  6  THE PROBABILITY FIELD - grid probabilities by side")
    grid = z["kind"] == 0
    field_skew = {}
    for name, p in (("M0 physics", p0), ("M1 state", p1), ("M2 memory", p2), ("M3 combined", p3)):
        up = pd.Series(np.where(grid & (z["side"] > 0), p, np.nan)).groupby(zm).mean()
        dn = pd.Series(np.where(grid & (z["side"] < 0), p, np.nan)).groupby(zm).mean()
        sk = np.full(n, np.nan)
        sk[up.index.to_numpy()] = (up - dn).to_numpy()
        field_skew[name] = sk
    # local maxima: a grid probability higher than both its nearer and farther neighbour, per side
    arr = {}
    for name, p in (("M0 physics", p0), ("M3 combined", p3)):
        count, tot = 0, 0
        for side in (1, -1):
            sel = grid & (z["side"] == side) & zte
            df_ = pd.DataFrame({"m": zm[sel], "d": z["dist"][sel], "p": p[sel]}).sort_values(["m", "d"])
            P = df_.pivot(index="m", columns="d", values="p").to_numpy()
            if P.shape[1] >= 3:
                interior = (P[:, 1:-1] > P[:, :-2]) & (P[:, 1:-1] > P[:, 2:])
                count += interior.any(1).sum()
                tot += len(P)
        arr[name] = count / max(tot, 1)
    print("    share of test moments whose field has an interior peak on a side: "
          + ", ".join(f"{k} {v:.2%}" for k, v in arr.items()))
    rows = np.isfinite(field_skew["M3 combined"])
    up_move = (c["end"] > 0).astype(float)
    for name, sk in field_skew.items():
        k = rows & te_m
        a = [f"{lab} AUC {roc_auc_score(up_move[k & fm], sk[k & fm]):.3f}" for lab, fm in (("real", real), ("control", ~real))]
        print(f"    skew {name:<14} direction " + " | ".join(a))
    for name in ("M1 state", "M3 combined"):
        sk = np.nan_to_num(field_skew[name], nan=0.0)
        trade(c, sk, rows, f"trade the field skew, {name}")

    # ---------------------------------------------------------------- 2  hazard
    print("\n  2  HAZARD - P(reached within t) and time to zone, test block")
    sub = RNG.choice(np.flatnonzero(ztr), min(400_000, ztr.sum()), replace=False)
    steps = np.arange(1, H + 1)
    at_risk = z["ttime"][sub][:, None] >= steps[None, :]
    event = (z["ttime"][sub][:, None] == steps[None, :]) & at_risk
    rr, ss = np.nonzero(at_risk)
    Xh = np.column_stack([X3[sub][rr], steps[ss]])
    hz = gbm().fit(Xh, event[rr, ss].astype(float))
    te_rows = np.flatnonzero(zte)
    te_rows = RNG.choice(te_rows, min(300_000, len(te_rows)), replace=False)
    surv = np.ones(len(te_rows))
    cdf = {}
    for s_ in steps:
        h = hz.predict_proba(np.column_stack([X3[te_rows], np.full(len(te_rows), s_)]))[:, 1]
        surv = surv * (1 - h)
        if s_ in (4, 8, 16):
            cdf[s_] = 1 - surv
    exp_time = None
    for s_, j in ((4, 0), (8, 1), (16, 2)):
        yt = (z["ttime"][te_rows] <= s_).astype(float)
        fm = zreal[te_rows]
        # a random training sample - the zone rows are grouped by kind, so a leading slice is one kind
        pick = RNG.choice(np.flatnonzero(ztr), min(300_000, ztr.sum()), replace=False)
        direct = gbm().fit(X3[pick], (z["ttime"][pick] <= s_).astype(float)).predict_proba(X3[te_rows])[:, 1]
        preds = {"physics first passage": physics(c, {k: v[te_rows] for k, v in z.items()}, s_),
                 "twins empirical": a_cdf[j][te_rows], "direct model at t": direct, "hazard model": cdf[s_]}
        print(f"    within {s_:>2} bars (base rate {yt[fm].mean():.1%}):")
        for name, p in preds.items():
            print(f"      {name:<24} real {score(yt[fm], p[fm])} | control {score(yt[~fm], p[~fm])}")
    hit_te = z["ttime"][te_rows] <= H
    # expected time within H, from the hazard curve, against the realised first-touch time
    surv = np.ones(len(te_rows))
    et = np.zeros(len(te_rows))
    for s_ in steps:
        h = hz.predict_proba(np.column_stack([X3[te_rows], np.full(len(te_rows), s_)]))[:, 1]
        et += s_ * surv * h
        surv = surv * (1 - h)
    et = et / np.maximum(1 - surv, 1e-6)
    k = hit_te & zreal[te_rows]
    print(f"    expected time to zone (given hit), real: Spearman with realised {stats.spearmanr(et[k], z['ttime'][te_rows][k]).statistic:+.3f}; "
          f"twins' median {stats.spearmanr(t_med[te_rows][k], z['ttime'][te_rows][k]).statistic:+.3f}; "
          f"distance alone {stats.spearmanr(z['dist'][te_rows][k], z['ttime'][te_rows][k]).statistic:+.3f}")

    # ---------------------------------------------------------------- 3  entropy and competition
    print("\n  3  ENTROPY AND COMPETITION - the distribution over the 12 grid destinations (M3)")
    g = grid & np.isin(zm, q_te)
    P = pd.DataFrame({"m": zm[g], "col": (z["side"][g] * z["dist"][g]), "p": p3[g]}).pivot(index="m", columns="col", values="p")
    mids = P.index.to_numpy()
    Pm = P.to_numpy()
    Pn = Pm / Pm.sum(1, keepdims=True)
    ent = -(Pn * np.log(Pn + 1e-12)).sum(1)
    srt = np.sort(Pn, axis=1)
    ratio = srt[:, -1] / srt[:, -2]
    mag = np.abs(c["end"][mids])
    lsig = np.log(c["sigr"][mids])
    first = np.where(np.isfinite(ent), 1, 0)
    fam_real = real[mids]
    # entropy change between consecutive test moments of one series
    order = np.lexsort((c["t"][mids], c["sym"][mids]))
    dH = np.full(len(mids), np.nan)
    same = c["sym"][mids][order][1:] == c["sym"][mids][order][:-1]
    dH[order[1:]] = np.where(same, np.diff(ent[order]), np.nan)
    resid = mag - np.polyval(np.polyfit(lsig[fam_real], mag[fam_real], 1), lsig)  # size beyond the volatility ratio
    for name, v in (("entropy H", ent), ("change dH", dH), ("top-two ratio R", ratio)):
        ok = np.isfinite(v)
        out = []
        for lab, fm in (("real", fam_real), ("control", ~fam_real)):
            kk = ok & fm
            out.append(f"{lab}: |move| {stats.spearmanr(v[kk], mag[kk]).statistic:+.3f}, "
                       f"beyond vol {stats.spearmanr(v[kk], resid[kk]).statistic:+.3f}, "
                       f"up-move AUC {roc_auc_score((c['end'][mids] > 0)[kk], v[kk]):.3f}")
        print(f"    {name:<16} " + " | ".join(out))
    print(f"    (the volatility ratio alone: |move| Spearman {stats.spearmanr(lsig[fam_real], mag[fam_real]).statistic:+.3f} real)")

    # ---------------------------------------------------------------- 4  memory decay
    print("\n  4  MEMORY DECAY - twins weighted by recency, all history before the query (embargo H bars)")
    allmem = np.flatnonzero((c["t"] % 4) == 0)
    months = pd.to_datetime(c["ts"], unit="s").to_period("M").astype(str)
    qd = q_te[(c["t"][q_te] % 8) == 0]
    halves = {"1 week": 7, "1 month": 30, "6 months": 182, "2 years": 730, "infinite": np.inf}
    est = {h_: {"up": np.full(n, np.nan), "mag": np.full(n, np.nan)} for h_ in halves}
    embargo = H * SECONDS[LADDER[0]]
    for mo in np.unique(months[qd]):
        qs = qd[months[qd] == mo]
        start = c["ts"][qs].min()
        pool = allmem[c["ts"][allmem] < start - embargo]
        if len(pool) < 5000:
            continue
        E = torch.tensor(c["emb"][pool])
        for i in range(0, len(qs), 512):
            qq = qs[i:i + 512]
            top = torch.topk(torch.tensor(c["emb"][qq]) @ E.T, 500, dim=1).indices.numpy()
            nn = pool[top]
            age = (c["ts"][qq][:, None] - c["ts"][nn]) / 86400.0
            for h_, days in halves.items():
                w = np.ones_like(age) if np.isinf(days) else 0.5 ** (age / days)
                w = w / w.sum(1, keepdims=True)
                est[h_]["up"][qq] = (w * (c["end"][nn] > 0)).sum(1)
                est[h_]["mag"][qq] = (w * np.abs(c["end"][nn])).sum(1)
    done = np.isfinite(est["infinite"]["up"])
    vol_hi = c["sigr"] >= np.nanmedian(c["sigr"][done])
    for lab, sel in (("first half (choose)", done & ~c["half"]), ("second half (report)", done & c["half"])):
        for regime, rm in (("all", np.ones(n, bool)), ("calm", ~vol_hi), ("volatile", vol_hi)):
            k = sel & rm & real
            line = []
            for h_ in halves:
                rho = stats.spearmanr(est[h_]["mag"][k], np.abs(c["end"][k])).statistic
                auc = roc_auc_score(c["end"][k] > 0, est[h_]["up"][k])
                line.append(f"{h_}: size {rho:+.3f} dir {auc:.3f}")
            print(f"    {lab:<22} {regime:<9} " + " | ".join(line))

    # ---------------------------------------------------------------- 5  impossibility region
    print("\n  5  IMPOSSIBILITY REGION - the 95% boundary of adverse excursion over H")
    q = q_te
    nnq = nn_of[q]
    for side, name in ((1, "long"), (-1, "short")):
        adverse = c["dn"] if side > 0 else c["up"]  # a long's adverse excursion is the fall
        mae = adverse[:, -1] * 0 + adverse.max(1)
        b_twin = np.quantile(adverse[nnq].max(2), 0.95, axis=1)
        b_gauss = c["sigr"][q] * np.sqrt(np.pi / 2) * np.sqrt(H) * stats.norm.ppf(0.975)
        Xq = np.nan_to_num(np.column_stack([np.log(c["sigr"]), c["speed"], side * c["eff"], side * c["vel"]]))
        qm = HistGradientBoostingRegressor(loss="quantile", quantile=0.95, max_depth=4, max_iter=200).fit(
            Xq[q_tr], adverse[q_tr].max(1))
        b_qm = qm.predict(Xq[q])
        for bname, bnd in (("twins", b_twin), ("Gaussian", b_gauss), ("quantile model", b_qm)):
            out = []
            for lab, fm in (("real", real[q]), ("control", ~real[q])):
                exc = np.mean(mae[q][fm] > bnd[fm])
                out.append(f"{lab} exceed {exc:.1%} median width {np.median(bnd[fm]):.2f}")
            print(f"    {name:<5} {bname:<15} " + " | ".join(out))
        # as a stop, at equal money at risk: the boundary vs a fixed width equal to its median
        for bname, bnd in (("twins", b_twin), ("quantile model", b_qm)):
            fixed = np.full(len(q), np.median(bnd[real[q]]))
            res = []
            for sname, stop in (("boundary", bnd), ("fixed", fixed)):
                path = adverse[q]
                hit = (path >= stop[:, None]).any(1)
                pnl = np.where(hit, -1.0, side * c["end"][q] / stop) - c["cost"][q] / stop
                k = real[q] & ((c["t"][q] % H) == 0)
                res.append(f"{sname} stopped {hit[k].mean():.1%} R {pnl[k].mean():+.3f} 1% {np.quantile(pnl[k], 0.01):+.2f}")
            print(f"      as a stop ({bname}): " + " | ".join(res))


if __name__ == "__main__":
    main()
