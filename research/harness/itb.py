"""What asavinov/intelligent-trading-bot does differently, tested here.

ITB's core - up/down race labels, P(up) - P(down) as the score, LightGBM/LR/NN, TA
features - is already covered by `horizons.py`, `questions.py` and `ensemble.py`, and found
no directional edge after costs. Five things it does differently were never tested. Each is
run on every real instrument in the lab's broker bars (15 FX pairs, XAU, XAG, BTC, ETH, SOL),
with the house rules: stops resolved on wicks (`bars.py`, a bar spanning both levels is the
stop), non-overlapping entries, spread charged, thresholds chosen on data before the test
block, and the two halves of the test period reported.

  A  purged rolling retrain. Our intraday harnesses fit once on the first 60%. ITB's
     `predict_rolling` refits every step on a trailing window, with a gap equal to the label
     horizon. Here: monthly refits on the trailing W days (180 at 15m, 365 at 1h), purge H
     bars, against the fixed 60/40 fit on the same test months.
  B  ITB's label: a 5:1 race (target T, stop 0.2T). In volatility units (stop = baseline x
     sqrt(H)), and at a **fixed** distance per instrument - the training median of that unit,
     held constant - which is ITB's fixed-percent idea. The single-feature AUC of short-window
     volatility on each label says how much of the fixed version is volatility in disguise.
  C  ITB's trading: a two-state machine on score = P(up) - P(down), buy above theta_buy, sell
     below theta_sell, hold in between - no stop, no horizon. Thresholds chosen on a
     validation block (40-60%), traded on the last 40%, long-only (ITB's) and long/short, with
     ITB's zero-latency fill and with a one-bar delay. Judged against always-long and against
     an **exposure-matched null**: the same position series circularly shifted per instrument,
     which keeps the trade count, every holding length and the exposure, and destroys timing.
  D  ITB's `smoothen`: an EWM of the score, span chosen on validation from {1,3,6,12,24}, for
     the two-state machine and for fixed-horizon race trades - net R and trade count.
  E  ITB's own setting: crypto at the finest bars the lab holds (3m; ITB uses 1m) and its exact
     label - +2% before -0.4% within two hours (40 x 3m, ITB: 120 x 1m) - at a 0.1%-per-side
     taker fee, plus the same race in volatility units. Also how much ITB's tie rule (a bar that
     touches both levels counts as the target) inflates the label against ours.

Run on the lab, one part per process:
  ./.secrets/lab.sh run research/harness/itb.py PART=A SEQLAB=$HOME/till_infinity/data/seqlab OMP_NUM_THREADS=4
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).parent))
import horizons
import questions
import spikerisk
from bars import Fitted, long_R, paths

DB = os.environ.get("PRICES_DB", "data/prices.db")
if not Path(DB).exists():
    sqlite3.connect(":memory:").close()
    DB = ":memory:"
for _mod in (spikerisk, horizons, questions):
    _mod.DB = DB

# 3m is not a setup the other harnesses know; E needs it.
spikerisk.SETUPS["3m"] = (180, 40, 500, True)
horizons.HORIZONS["3m"] = (40,)
questions.MINUTES["3m"] = 3

FX = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "USDCNH",
      "AUDJPY", "CHFJPY", "EURAUD", "EURCHF", "EURGBP", "EURJPY", "GBPJPY"]
REAL = {
    "fx": [(s, "SEQLAB") for s in FX],
    "metal": [("XAUUSD", "SEQLAB"), ("XAGUSD", "SEQLAB")],
    "crypto": [("BTCUSD", "SEQLAB"), ("ETHUSD", "SEQLAB"), ("SOLUSD", "SEQLAB")],
}
CRYPTO = {"crypto": REAL["crypto"]}
#: The negative control for C: the Volatility indices are exact geometric Brownian motions
#: (`twins.md`), so a timing rule has nothing to time. A machine that "wins" here is a method
#: that manufactures wins.
VOLS = ["Volatility_10_Index", "Volatility_25_Index", "Volatility_50_Index", "Volatility_75_Index",
        "Volatility_100_Index", "Volatility_10_1s_Index", "Volatility_25_1s_Index", "Volatility_50_1s_Index",
        "Volatility_75_1s_Index", "Volatility_100_1s_Index"]
CONTROL = {"synthetic": [(s, "SEQLAB") for s in VOLS]}
questions.COST_V.setdefault("synthetic", 0.17)  # catalogue.md, the Volatility family
H = {"15m": 8, "1h": 5, "3m": 40}
SECONDS = {"3m": 180, "15m": 900, "1h": 3600}
WINDOW_DAYS = {"15m": 180, "1h": 365}


def frame(interval, universe):
    d, cols = horizons.build(interval, universe)
    h = H[interval]
    keep = [c for c in d.columns if "@" not in c or c.endswith(f"@{h}")]
    return d[keep].copy(), cols


def blocks(d):
    size = d.groupby("ticker").ts.transform("size").to_numpy()
    frac = d["_pos"].to_numpy() / size
    return frac < 0.4, (frac >= 0.4) & (frac < 0.6), frac >= 0.6


def race_cost(d, interval, h):
    return questions.cost_R(d, interval, 1.5 * d["_base"].to_numpy() * np.sqrt(h))


# ------------------------------------------------------------------------------ A


def part_a(interval):
    d, cols = frame(interval, REAL)
    h = H[interval]
    X = d[cols].to_numpy(float)
    ts = d.ts.to_numpy()
    split = d.split.to_numpy()
    cost = race_cost(d, interval, h)
    purge = h * SECONDS[interval]
    window = WINDOW_DAYS[interval] * 86400
    months = pd.to_datetime(ts, unit="s").to_period("M").astype(str).to_numpy()
    print(f"\n{'=' * 110}\nA {interval}: {d.ticker.nunique()} series, {len(d):,} bars, H={h}, "
          f"rolling window {WINDOW_DAYS[interval]}d, purge {h} bars")
    for side, label, rcol in (("long", "tb_up", "R"), ("short", "tb_dn", "Rs")):
        y = d[f"{label}@{h}"].to_numpy()
        R = d[f"{rcol}@{h}"].to_numpy()
        ok = ~np.isnan(y) & ~np.isnan(R)
        tr, te = ok & (split == 0), ok & (split > 0)
        m = Fitted(horizons.gbm(), X[tr], y[tr])
        p = m.predict_proba(X)[:, 1]
        take = questions.thin(d, te & (p >= np.quantile(p[tr], 0.95)), h)
        questions.report("A", f"{side} fixed 60/40 fit", interval, d, take, R - cost, R)
        sel = np.zeros(len(d), bool)
        for month in np.unique(months[te]):
            rows = te & (months == month)
            start = ts[rows].min()
            trn = ok & (ts >= start - window) & (ts < start - purge)
            if trn.sum() < 2000 or y[trn].min() == y[trn].max():
                continue
            mm = Fitted(horizons.gbm(), X[trn], y[trn])
            cut = np.quantile(mm.predict_proba(X[trn])[:, 1], 0.95)
            idx = np.flatnonzero(rows)
            sel[idx[mm.predict_proba(X[idx])[:, 1] >= cut]] = True
        questions.report("A", f"{side} rolling monthly refit", interval, d,
                         questions.thin(d, sel, h), R - cost, R)
        uncond = questions.thin(d, te, h)
        questions.report("A", f"{side} every bar", interval, d, uncond, R - cost, R)


# ------------------------------------------------------------------------------ B


def part_b(interval):
    d, cols = frame(interval, REAL)
    h = H[interval]
    X = d[cols].to_numpy(float)
    fut = paths(d, h)
    unit = d["_base"].to_numpy() * np.sqrt(h)
    split = d.split.to_numpy()
    # ITB's fixed percent: each instrument's typical unit on the training block, held constant
    med = pd.Series(np.where(split == 0, unit, np.nan)).groupby(d.ticker.to_numpy()).transform("median")
    fixed = med.to_numpy()
    everybar = np.ones(len(d), bool)
    short_vol = d["short"].to_numpy()
    print(f"\n{'=' * 110}\nB {interval}: 5:1 race (target 5 units, stop 1), H={h}")
    for scale, u in (("vol units", unit), ("fixed per instrument", fixed)):
        for side in (1, -1):
            R, w = long_R(fut * side, 5 * u, u)
            cost = questions.cost_R(d, interval, u)
            name = f"{'long' if side > 0 else 'short'} 5:1 {scale}"
            questions.one_sided("B", name, interval, d, X, everybar, R, cost, h)
            y = (w == 1)
            te = (split > 0) & ~np.isnan(R) & np.isfinite(short_vol)
            if 0 < y[te].mean() < 1:
                print(f"      base rate {y[te].mean():.1%}; AUC of short-window volatility alone on this "
                      f"label {roc_auc_score(y[te], short_vol[te]):.3f}")


# ------------------------------------------------------------------------------ C and D


def score_models(d, cols, h, fit):
    X = d[cols].to_numpy(float)
    out = []
    for label in ("tb_up", "tb_dn"):
        y = d[f"{label}@{h}"].to_numpy()
        ok = fit & ~np.isnan(y)
        out.append(Fitted(horizons.gbm(), X[ok], y[ok]).predict_proba(X)[:, 1])
    return out[0] - out[1]  # ITB's `difference` combine


def machine(score, buy, sell, long_short):
    """ITB's two-state rule per series: enter above `buy`, leave (or reverse) below `sell`."""
    pos = np.zeros(len(score))
    state = 0.0
    for i, s in enumerate(score):
        if np.isnan(s):
            pos[i] = state
            continue
        if s >= buy:
            state = 1.0
        elif s <= sell:
            state = -1.0 if long_short else 0.0
        pos[i] = state
    return pos


def run_machine(d, score, buy, sell, long_short, mask, cost_log, delay):
    """Net log return summed over series on `mask` rows; position at t earns bar t+1+delay."""
    total, exposure, trades, per = 0.0, 0.0, 0, {}
    lc = d["_lc"].to_numpy()
    for t, g in d[mask].groupby("ticker"):
        idx = g.index.to_numpy()
        pos = machine(score[idx], buy, sell, long_short)
        r = np.diff(lc[idx], append=np.nan)  # close t -> close t+1
        if delay:
            r = np.concatenate([r[1:], [np.nan]])
        r = np.nan_to_num(r)
        change = np.abs(np.diff(pos, prepend=0.0))
        net = pos * r - change * cost_log[idx] / 2
        per[t] = (pos, r, cost_log[idx])
        total += net.sum()
        exposure += np.abs(pos).mean() * len(idx)
        trades += int((change > 0).sum())
    return total, exposure, trades, per


def null_shift(per, n=200, seed=11):
    """The same position series, circularly shifted per instrument: same exposure, trade count
    and holding lengths, no timing."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        s = 0.0
        for pos, r, c in per.values():
            k = rng.integers(len(pos) // 10, len(pos) - len(pos) // 10) if len(pos) > 20 else 0
            p = np.roll(pos, k)
            s += (p * r - np.abs(np.diff(p, prepend=0.0)) * c / 2).sum()
        out.append(s)
    return np.array(out)


def part_cd(interval, which):
    d, cols = frame(interval, REAL)
    h = H[interval]
    fit, val, te = blocks(d)
    score = score_models(d, cols, h, fit)
    fam = d.family.map(questions.COST_V).to_numpy()
    cost_log = fam * d["_base"].to_numpy() / np.sqrt(questions.MINUTES[interval] / 5)  # round trip
    lc = d["_lc"].to_numpy()
    spans = (1,) if which == "C" else (1, 3, 6, 12, 24)
    print(f"\n{'=' * 110}\n{which} {interval}: two-state machine on P(up)-P(down), H={h}, "
          f"{d.ticker.nunique()} series; thresholds (and span) chosen on the validation block")
    half = te & (d.split.to_numpy() == 2)
    for long_short in (False, True):
        for delay in (0, 1):
            best = None
            for span in spans:
                sm = score if span == 1 else pd.Series(score).groupby(d.ticker.to_numpy()).transform(
                    lambda s, sp=span: s.ewm(span=sp, adjust=False).mean()).to_numpy()
                v = sm[val]
                for qb in (0.7, 0.8, 0.9, 0.95):
                    for qs in (0.05, 0.1, 0.2, 0.3, 0.5):
                        b, s_ = np.quantile(v, qb), np.quantile(v, qs)
                        tot, _, _, _ = run_machine(d, sm, b, s_, long_short, val, cost_log, delay)
                        if best is None or tot > best[0]:
                            best = (tot, span, b, s_, sm)
            _, span, b, s_, sm = best
            tot, expo, trades, per = run_machine(d, sm, b, s_, long_short, te, cost_log, delay)
            a, _, _, _ = run_machine(d, sm, b, s_, long_short, te & ~half, cost_log, delay)
            bb, _, _, _ = run_machine(d, sm, b, s_, long_short, half, cost_log, delay)
            null = null_shift(per)
            always = 0.0
            for _, g in d[te].groupby("ticker"):
                idx = g.index.to_numpy()
                always += np.nansum(np.diff(lc[idx])) - cost_log[idx[0]]
            n_te = te.sum()
            print(f"  {'long/short' if long_short else 'long-only ':<10} {'next-bar' if delay else 'same-bar'} "
                  f"span {span:>2}: net {tot:+8.3f} log (test-a {a:+.3f}, test-b {bb:+.3f}) | exposure "
                  f"{expo / n_te:5.1%} | trades {trades:>5} | shifted null {null.mean():+8.3f} +- {null.std():.3f} "
                  f"(z {(tot - null.mean()) / max(null.std(), 1e-12):+.1f}) | always long {always:+8.3f}")
    if which == "D":
        # fixed-horizon race trades, raw vs smoothed score, thresholds from validation quantiles
        Rl, Rs = d[f"R@{h}"].to_numpy(), d[f"Rs@{h}"].to_numpy()
        cost = race_cost(d, interval, h)
        for span in (1, 3, 6, 12, 24):
            sm = score if span == 1 else pd.Series(score).groupby(d.ticker.to_numpy()).transform(
                lambda s, sp=span: s.ewm(span=sp, adjust=False).mean()).to_numpy()
            hi, lo = np.quantile(sm[val], 0.8), np.quantile(sm[val], 0.2)
            side = np.where(sm >= hi, 1, np.where(sm <= lo, -1, 0))
            g = np.where(side == 1, Rl, np.where(side == -1, Rs, np.nan))
            take = questions.thin(d, te & (side != 0) & ~np.isnan(g), h)
            questions.report("D", f"race top/bottom 20%, span {span}", interval, d, take, g - cost, g)


# ------------------------------------------------------------------------------ E


def first_touch_both(P, up, dn):
    """Share of races whose first touching bar touches both levels - ITB scores these as the
    target, `bars.py` as the stop."""
    n, hh = P.c.shape
    done = np.zeros(n, bool)
    both = np.zeros(n, bool)
    for k in range(hh):
        u, v = P.h[:, k] >= up, P.l[:, k] <= -dn
        both |= ~done & u & v
        done |= u | v
    return both, done


def part_e():
    interval = "3m"
    d, cols = frame(interval, CRYPTO)
    h = H[interval]
    X = d[cols].to_numpy(float)
    fut = paths(d, h)
    split = d.split.to_numpy()
    everybar = np.ones(len(d), bool)
    unit = d["_base"].to_numpy() * np.sqrt(h)
    print(f"\n{'=' * 110}\nE 3m crypto: {d.ticker.nunique()} series, {len(d):,} bars, H={h} (two hours)")
    up, dn = np.log(1.02), -np.log(1 - 0.004)
    fee = np.full(len(d), 2 * 0.001)  # 0.1% taker each side, in log terms
    for side in (1, -1):
        P = fut * side
        R, w = long_R(P, np.full(len(d), up), np.full(len(d), dn))
        both, done = first_touch_both(P, np.full(len(d), up), np.full(len(d), dn))
        te = (split > 0) & ~np.isnan(P.end)
        wins_ours = (w == 1)[te].mean()
        wins_itb = ((w == 1) | both)[te].mean()
        print(f"  {'long' if side > 0 else 'short'} ITB label (+2% before -0.4%): win rate {wins_ours:.2%} with a "
              f"two-level bar as the stop, {wins_itb:.2%} with ITB's rule (that bar as the target); "
              f"resolved {done[te].mean():.1%}")
        name = f"{'long' if side > 0 else 'short'} +2%/-0.4% fixed"
        questions.one_sided("E", name + " [0.1%/side fee]", interval, d, X, everybar, R, fee / dn, h)
        questions.one_sided("E", name + " [house spread]", interval, d, X, everybar, R,
                            questions.cost_R(d, interval, np.full(len(d), dn)), h)
        Rv, _ = long_R(P, 5 * unit, unit)
        questions.one_sided("E", f"{'long' if side > 0 else 'short'} 5:1 vol units [house spread]", interval,
                            d, X, everybar, Rv, questions.cost_R(d, interval, unit), h)


def part_verify(interval):
    """C again, broken down: per family, per series, delays of 0-2 bars, and the negative
    control. Thresholds chosen on validation exactly as in C (span 1)."""
    universe = {**REAL, **CONTROL}
    d, cols = frame(interval, universe)
    h = H[interval]
    fit, val, te = blocks(d)
    fam = d.family.to_numpy()
    cost_log = d.family.map(questions.COST_V).to_numpy() * d["_base"].to_numpy() / np.sqrt(
        questions.MINUTES[interval] / 5)
    print(f"\n{'=' * 110}\nVERIFY {interval}: two-state machine, per family, with the random-walk control")
    for family in ("fx", "metal", "crypto", "synthetic"):
        k = fam == family
        if not k.any():
            continue
        sub = d[k].copy()
        idx_map = np.flatnonzero(k)
        # models fit on this family's own fit block (the control must be fit on itself)
        score = score_models(sub.reset_index(drop=True), cols, h, fit[idx_map])
        sub = sub.reset_index(drop=True)
        v_, t_ = val[idx_map], te[idx_map]
        cl = cost_log[idx_map]
        lc = sub["_lc"].to_numpy()
        for long_short in (False, True):
            best = None
            for qb in (0.7, 0.8, 0.9, 0.95):
                for qs in (0.05, 0.1, 0.2, 0.3, 0.5):
                    b, s_ = np.quantile(score[v_], qb), np.quantile(score[v_], qs)
                    tot, _, _, _ = run_machine(sub, score, b, s_, long_short, v_, cl, 1)
                    if best is None or tot > best[0]:
                        best = (tot, b, s_)
            _, b, s_ = best
            always = sum(np.nansum(np.diff(lc[g.index.to_numpy()])) for _, g in sub[t_].groupby("ticker"))
            for delay in (0, 1, 2):
                tot, expo, trades, per = run_machine_delay(sub, score, b, s_, long_short, t_, cl, delay)
                null = null_shift(per)
                series = {t: (p * r - np.abs(np.diff(p, prepend=0.0)) * c / 2).sum() for t, (p, r, c) in per.items()}
                pos_series = sum(v > 0 for v in series.values())
                print(f"  {family:<9} {'long/short' if long_short else 'long-only ':<10} delay {delay}: net {tot:+7.3f} "
                      f"| null {null.mean():+7.3f} +- {null.std():.3f} (z {(tot - null.mean()) / max(null.std(), 1e-12):+.1f})"
                      f" | always long {always:+7.3f} | trades {trades:>5} | series positive {pos_series}/{len(series)}")


def run_machine_delay(d, score, buy, sell, long_short, mask, cost_log, delay):
    """`run_machine` with any delay: a position decided at close t earns close t+delay -> t+delay+1."""
    total, exposure, trades, per = 0.0, 0.0, 0, {}
    lc = d["_lc"].to_numpy()
    for t, g in d[mask].groupby("ticker"):
        idx = g.index.to_numpy()
        pos = machine(score[idx], buy, sell, long_short)
        r = np.diff(lc[idx], append=np.nan)
        if delay:
            r = np.concatenate([r[delay:], np.full(delay, np.nan)])
        r = np.nan_to_num(r)
        change = np.abs(np.diff(pos, prepend=0.0))
        per[t] = (pos, r, cost_log[idx])
        total += (pos * r - change * cost_log[idx] / 2).sum()
        exposure += np.abs(pos).mean() * len(idx)
        trades += int((change > 0).sum())
    return total, exposure, trades, per


def part_fx15():
    """The one survivor, pressed: 15m FX two-state machine. A null that shifts every pair by the
    **same** offset (FX shares the dollar, so positions and P&L are correlated across pairs and an
    independent shift understates the null's spread), month-by-month P&L, and costs at 1x, 2x and
    3x the assumption, at one- and two-bar delays."""
    interval = "15m"
    d, cols = frame(interval, {"fx": REAL["fx"]})
    h = H[interval]
    fit, val, te = blocks(d)
    score = score_models(d, cols, h, fit)
    base_cost = d.family.map(questions.COST_V).to_numpy() * d["_base"].to_numpy() / np.sqrt(
        questions.MINUTES[interval] / 5)
    lc, ts = d["_lc"].to_numpy(), d.ts.to_numpy()
    print(f"\n{'=' * 110}\nFX15: {d.ticker.nunique()} pairs")
    for long_short in (False, True):
        best = None
        for qb in (0.7, 0.8, 0.9, 0.95):
            for qs in (0.05, 0.1, 0.2, 0.3, 0.5):
                b, s_ = np.quantile(score[val], qb), np.quantile(score[val], qs)
                tot, _, _, _ = run_machine(d, score, b, s_, long_short, val, base_cost, 1)
                if best is None or tot > best[0]:
                    best = (tot, b, s_)
        _, b, s_ = best
        for mult in (1, 2, 3):
            for delay in (1, 2):
                tot, _, trades, per = run_machine_delay(d, score, b, s_, long_short, te, base_cost * mult, delay)
                # common-offset null: one offset (as a fraction of each series) for every pair
                rng = np.random.default_rng(3)
                null = []
                for _ in range(300):
                    f = rng.uniform(0.1, 0.9)
                    tot0 = 0.0
                    for pos, r, c in per.values():
                        p0 = np.roll(pos, int(f * len(pos)))
                        tot0 += (p0 * r - np.abs(np.diff(p0, prepend=0.0)) * c / 2).sum()
                    null.append(tot0)
                null = np.array(null)
                print(f"  {'long/short' if long_short else 'long-only ':<10} cost x{mult} delay {delay}: net {tot:+7.3f} | "
                      f"common-shift null {null.mean():+7.3f} +- {null.std():.3f} (z {(tot - null.mean()) / null.std():+.1f}, "
                      f"beaten by {np.mean(null >= tot):.1%} of shifts) | trades {trades}")
        # month by month, delay 1, assumed cost
        _, _, _, per = run_machine_delay(d, score, b, s_, long_short, te, base_cost, 1)
        monthly = {}
        for t, (pos, r, c) in per.items():
            idx = d[te & (d.ticker == t).to_numpy()].index.to_numpy()
            pnl = pos * r - np.abs(np.diff(pos, prepend=0.0)) * c / 2
            for m_, v in pd.Series(pnl, index=pd.to_datetime(ts[idx], unit="s").to_period("M")).groupby(level=0).sum().items():
                monthly[str(m_)] = monthly.get(str(m_), 0.0) + v
        pos_m = sum(v > 0 for v in monthly.values())
        print(f"  months positive {pos_m}/{len(monthly)}: " + " ".join(f"{k[2:]} {v:+.2f}" for k, v in sorted(monthly.items())))


def part_spread():
    """The cost assumption against the broker's own spreads. `questions.COST_V` charges FX 0.8
    M5-volatility units, from one EURUSD measurement at the worst hour of the day; crosses are
    wider. The lab's bars carry the broker's spread per bar, in points."""
    seqlab = Path(os.environ["SEQLAB"])
    print(f"{'pair':8} {'digits':>6} {'spread pts':>10} {'real bp':>8} {'assumed bp':>10} {'ratio':>6}")
    ratios = []
    for s in FX:
        z = np.load(seqlab / f"{s}.15m.npz")  # plain arrays; never allow_pickle
        c, sp = z["close"][-20000:], z["spread"][-20000:]
        dec = max(len(f"{x:.6f}".rstrip("0").split(".")[1]) for x in c[-2000:])
        real = np.nanmedian(sp) * 10.0 ** -dec / np.nanmedian(c)
        assumed = 0.8 * np.nanmean(np.abs(np.diff(np.log(c)))) / np.sqrt(3)
        ratios.append(real / assumed)
        print(f"{s:8} {dec:>6} {np.nanmedian(sp):>10.1f} {real * 1e4:>8.2f} {assumed * 1e4:>10.2f} "
              f"{real / assumed:>6.2f}")
    print(f"median real/assumed {np.median(ratios):.2f}, max {np.max(ratios):.2f}")


if __name__ == "__main__":
    part = os.environ.get("PART", "A")
    if part == "A":
        for iv in ("15m", "1h"):
            part_a(iv)
    elif part == "B":
        for iv in ("15m", "1h"):
            part_b(iv)
    elif part in ("C", "D"):
        for iv in ("15m", "1h"):
            part_cd(iv, part)
    elif part == "E":
        part_e()
    elif part == "W":
        part_fx15()
    elif part == "S":
        part_spread()
    elif part == "V":
        for iv in ("15m", "1h"):
            part_verify(iv)
