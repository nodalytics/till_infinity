"""Zone events: origins of validated displacement, their quality, their returns, and what happens there.

Pre-registered 2026-10-03, before any run. A zone is not a level; it is the origin of an event
with a causal chain, Zone -> Imbalance -> Displacement -> BOS. Every swing low (high) is a candidate
origin; the ones whose move completes the chain are QUALIFIED (V = 1), the rest (V = 0) are the
matched baseline - ordinary swing points returned to in the same way. Then each zone's returns are
followed through its lifecycle, and the question asked is

    P(price makes 1R in the BOS direction before the stop | the zone, its return state)

Construction (for a bullish zone; bearish is the same on the flipped chart):

  origin      a 3/3 swing low p, known at p + 3
  BOS         the first close above the last swing high known at p, within 20 bars, before any
              trade below the origin's low. The reference existed before the break - no look-ahead
  imbalance   gaps (a bar's low above the high two bars before) on the path p..BOS
  displacement  highest high p..BOS minus the origin low, in ATR
  V = 1       a BOS, at least one gap of 0.1+ ATR, displacement 2+ ATR. Thresholds kept loose so
              that BOS and imbalance quality can vary and be measured, not filtered
  force       (asked for with the formation fingerprint) through the break only: speed (displacement
              per bar, ATR), eff_close (net close move / summed close-to-close moves), vol_surprise
              (the leg's mean true range / the 20 bars' before the origin), rel_force (displacement /
              sqrt(bars) - against a random walk's spread), obstacles (swing highs of the 100 bars before
              the origin that the leg took out), gap_pre (largest gap / the pre-zone mean range). bos_follow is the one feature
              from after the break (VALIDATED) and is kept apart; the formation-only model omits it.
              Force regimes are quartiles, read for an optimum, not assumed monotone
  prior leg   (asked for later) the fall into the origin, from the last swing high before it: pre_size
              (ATR), pre_speed (ATR a bar), pre_eff (net / summed close moves), pre_gaps (bearish
              gaps), v_ratio (displacement out / the fall in), v_speed (speed out / speed in) - a hard
              fall met by a harder, imbalanced break is buyers stepping in aggressively
  quality     bos_close (BOS close past the level, ATR), bos_follow (furthest 5 bars past it, ATR),
              bos_bars (origin to break), disp (ATR), disp_eff (net move / summed bar ranges of the
              leg), n_gaps, gap_max (largest gap, ATR), d_zi (bars origin -> first gap), d_ib (bars
              first gap -> break), width (zone, ATR), vol_pct (ATR/price percentile, 500 bars)
  boundary    body (low -> body top: what the earlier studies used), candle (low -> high), wick (low
              -> body bottom), cluster (lowest low of p-2..p -> highest body top of p-2..p)
  live        once the pivot, the break and bos_follow (5 bars after it) are known
  lifecycle   return k = 1, 2, 3: a bar reaching the near edge while armed. Armed at birth; re-armed
              after a return once price closes 0.5 ATR beyond the near edge again. Dead on a close
              0.1 ATR past the far edge, or after 500 bars
  at return   age (bars since live), travel (furthest close from the near edge since live, before
              the return bar, ATR), approach (close 5 bars before the return bar minus the near edge,
              ATR - known when the resting order is touched. The first version used the return bar's
              own low, which a resting order cannot know, and judged a rule built on it; that run is
              void, see origin-zones.md), fill_bars (bars from the BOS
              until its first gap was filled; -1 not yet), bias4h (the 4h's last break agrees),
              nest4h (1h only: inside a live qualified 4h zone)
  depth       a resting buy at the near edge (d0), the middle (d50) and the far edge (d100); each
              counted only if price trades there within 12 bars of the return without first closing
              through. Stop: 0.1 ATR past the far edge, at least 0.25 ATR below the entry
  outcome     from the fill: 1R, 2R, 3R reached before the stop, within 5 days; on the fill bar only
              a close beyond counts toward a target and a low through the stop counts against
              (the bar cannot order them); a bar touching both is the stop. R net of the spread
              (the broker's floor) on entry and exit

Tests, in this order, each reported once:

  1  does qualification matter: P(1R) V = 1 against V = 0, first return, d0, body, by timeframe
     and family, with a day-bootstrap interval of the difference
  2  lifecycle: return 1 / 2 / 3; depth: d0 / d50 / d100; boundary: the four - each V = 1 vs V = 0
  3  quality: on V = 1 first returns before 2023-01-01, each feature's quintile curve of P(1R);
     a logistic model on all the features fitted there; judged once on 2023-01-01 onward - AUC,
     and P(1R) and mean R of its top fifth against V = 0 in the same period. A model that ranks
     in-sample and not out of sample is reported as that

  confirm     the one rule the study suggested, frozen in `zone_rule.json` before it was run, judged
              once on markets no zone study used (MODE=confirm)

  OUT=... MT5BT_DB=... MODE=run|plot|confirm python research/ideas/zone_events.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1]))

import prims as P  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/zone_events"))
LR, MAXLEG, GAP_MIN, DISP_MIN = 3, 20, 0.1, 2.0
REARM, BUF, EXPIRE, WINDOW, RETURNS = 0.5, 0.1, 500, 12, 3
SEC = {"1h": 3600, "4h": 14400, "1d": 86400}
SPLIT = pd.Timestamp("2023-01-01", tz="UTC").timestamp()
BOUNDS = ("body", "candle", "wick", "cluster")
DEPTHS = (("d0", 0.0), ("d50", 0.5), ("d100", 1.0))
#: formation (known by the break), validated (after it), and return state - kept apart so the
#: future cannot prove the past was a strong zone
FORMATION = ("bos_close", "bos_bars", "disp", "disp_eff", "speed", "eff_close", "vol_surprise", "rel_force",
             "obstacles", "n_gaps", "gap_max", "gap_pre", "d_zi", "d_ib", "width", "vol_pct",
             "pre_size", "pre_speed", "pre_eff", "pre_gaps", "v_ratio", "v_speed")
VALIDATED = ("bos_follow",)
RETURN = ("age", "travel", "approach", "fill_bars", "bias4h")
FEATURES = FORMATION + VALIDATED + RETURN
FORCE = ("disp", "speed", "eff_close", "bos_close", "vol_surprise", "rel_force", "obstacles",
         "pre_size", "pre_speed", "pre_eff", "v_ratio", "v_speed")


def flip(df):
    return df.assign(open=-df["open"], close=-df["close"], high=-df["low"], low=-df["high"])


def _outcome(h, l, c, f, entry, stop, H, spread):
    """From a resting buy filled on bar f at `entry`: the most R reached before the stop (0-3), and
    whether it was stopped, within H bars. R net of the spread on entry and exit."""
    risk = entry - stop
    if not risk > 0:
        return np.nan, np.nan
    best, stopped = 0.0, False
    end = min(len(c), f + H)
    for k in range(f, end):
        hit_s = l[k] <= stop
        top = c[k] if k == f else h[k]  # the fill bar: only its close is surely after the fill
        if hit_s:
            stopped = True
            break
        best = max(best, (top - entry - spread) / risk)
        if best >= 3:
            break
    return min(best, 3.0), stopped


def events(df: pd.DataFrame, a: np.ndarray, side: int, spread: float, bias: np.ndarray | None,
           live4h: list | None, sec: int) -> list[dict]:
    """Every swing-low origin of this (long-terms) chart, its chain, its returns and their outcomes."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy()
    n = len(df)
    H = max(1, int(5 * 86400 / sec))
    ph, pl = P.pivots(h, l, LR, LR)
    ph_known = np.array([x[0] for x in ph])
    vol = pd.Series(a / np.maximum(np.abs(c), 1e-12)).rolling(500, min_periods=100).rank(pct=True).to_numpy()
    rows = []
    for known, p, low in pl:
        A = a[p]
        if not A > 0:
            continue
        j = np.searchsorted(ph_known, p, side="right") - 1
        level = ph[j][2] if j >= 0 else np.nan
        b = -1
        if np.isfinite(level) and level > low:
            for k in range(p + 1, min(n, p + MAXLEG + 1)):
                if l[k] < low:
                    break
                if c[k] > level:
                    b = k
                    break
        end_leg = b if b >= 0 else min(n - 1, p + MAXLEG)
        gaps = [(k, l[k] - h[k - 2]) for k in range(p + 2, end_leg + 1) if l[k] - h[k - 2] > 0]
        big = [g for g in gaps if g[1] >= GAP_MIN * A]
        ext = h[p:end_leg + 1].max()
        disp = (ext - low) / A
        path = np.sum(h[p:end_leg + 1] - l[p:end_leg + 1])
        V = bool(b >= 0 and big and disp >= DISP_MIN)
        if b < 0:
            continue  # no break: not a zone of either kind (the baseline is swing points that broke
            # structure without the rest of the chain, and swing points below are counted apart)
        if b + 5 >= n:
            continue
        follow = (h[b:b + 6].max() - level) / A
        # the force that escaped the zone, measured through the break only
        pc = np.r_[c[0], c[:-1]]
        tr = np.maximum(h, pc) - np.minimum(l, pc)
        pre = tr[max(0, p - 20):p].mean() if p >= 5 else np.nan
        steps = np.abs(np.diff(c[p:b + 1])).sum()
        obstacles = sum(1 for x in ph if x[0] <= p and p - 100 <= x[1] < p and low < x[2] <= ext)
        # the leg INTO the origin: from the last swing high before it down to the origin low - how
        # hard the market was falling where buyers stepped in
        prev = [x for x in ph if x[1] < p and x[2] > low]
        if prev:
            q_ = prev[-1][1]
            pre_size = (h[q_] - low) / A
            pre_bars = max(p - q_, 1)
            pre_steps = np.abs(np.diff(c[q_:p + 1])).sum()
            pre_eff = (c[q_] - c[p]) / max(pre_steps, 1e-12)
            pre_gaps = sum(1 for k2 in range(q_ + 2, p + 1) if h[k2] < l[k2 - 2] - GAP_MIN * A)
        else:
            pre_size = pre_bars = pre_eff = pre_gaps = np.nan
        first_gap = big[0][0] if big else (gaps[0][0] if gaps else -1)
        # the first qualifying gap's fill: bars from the break until a low at or under its bottom
        fill_bars = -1
        if first_gap > 0:
            g_lo = h[first_gap - 2]
            hit = np.flatnonzero(l[b + 1:min(n, b + 1 + EXPIRE)] <= g_lo)
            fill_bars = int(hit[0]) + 1 if len(hit) else -1
        live = max(known, b + 5)
        base = dict(side=side, p=p, ts=int(ts[p]), V=V, bos_close=(c[b] - level) / A, bos_follow=follow,
                    bos_bars=b - p, disp=disp, disp_eff=(ext - low) / max(path, 1e-12), n_gaps=len(big),
                    gap_max=max((g[1] for g in gaps), default=0.0) / A,
                    speed=disp / max(b - p, 1), eff_close=(c[b] - c[p]) / max(steps, 1e-12),
                    vol_surprise=tr[p + 1:b + 1].mean() / pre if pre and pre > 0 else np.nan,
                    rel_force=disp / np.sqrt(max(b - p, 1)), obstacles=obstacles,
                    gap_pre=max((g[1] for g in gaps), default=0.0) / pre if pre and pre > 0 else np.nan,
                    pre_size=pre_size, pre_bars=pre_bars, pre_speed=pre_size / pre_bars if pre_bars == pre_bars else np.nan,
                    pre_eff=pre_eff, pre_gaps=pre_gaps,
                    v_ratio=disp / pre_size if pre_size and pre_size == pre_size and pre_size > 0 else np.nan,
                    v_speed=(disp / max(b - p, 1)) / (pre_size / pre_bars)
                    if pre_size and pre_size == pre_size and pre_size > 0 else np.nan,
                    d_zi=(first_gap - p) if first_gap > 0 else -1, d_ib=(b - first_gap) if first_gap > 0 else -1,
                    vol_pct=vol[p])
        bounds = {
            "body": (low, max(o[p], c[p])),
            "candle": (low, h[p]),
            "wick": (low, min(o[p], c[p])),
            "cluster": (l[max(0, p - 2):p + 1].min(), max(np.maximum(o, c)[max(0, p - 2):p + 1].max(), low)),
        }
        for bname, (far, near) in bounds.items():
            near = max(near, far + 0.05 * A)  # a band at least 0.05 ATR tall
            armed, k_ret, travel = True, 0, 0.0
            k = live + 1
            while k < min(n, live + EXPIRE) and k_ret < RETURNS:
                if c[k] < far - BUF * A:
                    break
                if not armed:
                    if c[k] >= near + REARM * A:
                        armed = True
                    travel = max(travel, (c[k] - near) / A)
                    k += 1
                    continue
                if l[k] > near:
                    travel = max(travel, (c[k] - near) / A)  # this bar's close is known before the next
                    k += 1
                    continue
                # a return
                k_ret += 1
                armed = False
                feats = dict(base, bound=bname, ret=k_ret, width=(near - far) / A, age=k - live,
                             travel=travel, approach=(c[max(0, k - 5)] - near) / A,
                             fill_bars=fill_bars if fill_bars < 0 or b + fill_bars <= k else -1,
                             bias4h=bool(bias[k]) if bias is not None else np.nan,
                             nest4h=bool(live4h[k]) if live4h is not None else np.nan, ret_ts=int(ts[k]))
                stop = far - BUF * A
                for dname, d in DEPTHS:
                    entry = near - d * (near - far)
                    st_ = min(stop, entry - 0.25 * A)
                    f = -1
                    for m in range(k, min(n, k + WINDOW)):
                        if c[m] < far - BUF * A and l[m] > entry:
                            break
                        if l[m] <= entry:
                            f = m
                            break
                    if f < 0:
                        rows.append(dict(feats, depth=dname, filled=False, best=np.nan, stopped=np.nan, R=np.nan))
                        continue
                    best, stopped = _outcome(h, l, c, f, entry, st_, H, spread)
                    # R a trade with a 1R target: +1 if it got there, else -1 when stopped, else the
                    # close after H bars
                    if best >= 1:
                        R = 1.0 - spread / (entry - st_)
                    elif stopped:
                        R = -1.0 - spread / (entry - st_)
                    else:
                        R = (c[min(n - 1, f + H - 1)] - entry - spread) / (entry - st_)
                    rows.append(dict(feats, depth=dname, filled=True, best=best, stopped=stopped, R=R))
                k += 1
    return rows


def one(job):
    import run as R
    from mt5bt import load_specs
    sym, iv = job
    R.DB = os.environ.get("MT5BT_DB")
    df = R.load(sym, iv)
    if df is None:
        return None
    df = df.reset_index(drop=True)
    spec = load_specs(R.DB).get(sym)
    spread = R.spread_floor(sym, spec) * spec.point if spec is not None else 0.0
    a = P.atr(df, 14)
    d4 = R.load(sym, "4h")
    bias = live4h_up = live4h_dn = None
    if d4 is not None:
        import zones as Z
        d4 = d4.reset_index(drop=True)
        k4 = P.htf_index(df["ts"].to_numpy(), SEC[iv], d4["ts"].to_numpy(), SEC["4h"])
        b4 = Z.bias_4h(d4)[np.maximum(k4, 0)]
        bias = b4
        if iv == "1h":
            live4h_up, live4h_dn = _nest(df, d4, k4)
    out = []
    for side, frame in ((1, df), (-1, flip(df))):
        bs = None if bias is None else (bias == side)
        nest = None if iv != "1h" or live4h_up is None else (live4h_up if side > 0 else live4h_dn)
        out += events(frame, a, side, spread, bs, nest, SEC[iv])
    print(f"  {sym} {iv}: {len(out)} rows", flush=True)
    return pd.DataFrame(out).assign(sym=sym, iv=iv, family=R.FAMILY.get(sym, "?"))


def _nest(df, d4, k4):
    """For each 1h bar, whether its low (high) sits inside a live qualified 4h bullish (bearish)
    zone - one whose BOS chain completed, not yet closed through."""
    import zones as Z
    a4 = P.atr(d4, 14)
    up = np.zeros(len(df), bool)
    dn = np.zeros(len(df), bool)
    lo1, hi1 = df["low"].to_numpy(), df["high"].to_numpy()
    zs = Z.long_zones(d4, a4)
    short = Z.long_zones(Z.flip(d4), a4, -1)
    for z in short:
        z.lo, z.hi = -z.lo, -z.hi
    c4 = d4["close"].to_numpy()
    for z in zs + short:
        lo, hi = min(z.lo, z.hi), max(z.lo, z.hi)
        A = a4[z.p]
        # live from z.live until a 4h close through the far edge
        dead = len(d4)
        for k in range(z.live + 1, min(len(d4), z.live + EXPIRE)):
            if (c4[k] < z.lo - BUF * A) if z.side > 0 else (c4[k] > z.lo + BUF * A):
                dead = k
                break
        bars = np.flatnonzero((k4 >= z.live) & (k4 < dead))
        if not len(bars):
            continue
        if z.side > 0:
            up[bars] |= (lo1[bars] <= hi) & (lo1[bars] >= lo - 0.1 * A)
        else:
            dn[bars] |= (hi1[bars] >= lo) & (hi1[bars] <= hi + 0.1 * A)
    return up, dn


def _boot(x: pd.DataFrame, y: pd.DataFrame, col: str, rng, draws=2000):
    """Day-bootstrap 90% interval of mean(x) - mean(y)."""
    dx, dy = x.groupby("day")[col].agg(["sum", "count"]), y.groupby("day")[col].agg(["sum", "count"])
    days = np.union1d(dx.index, dy.index)
    dx, dy = dx.reindex(days, fill_value=0), dy.reindex(days, fill_value=0)
    out = []
    for _ in range(draws):
        s = rng.integers(0, len(days), len(days))
        out.append(dx["sum"].values[s].sum() / max(dx["count"].values[s].sum(), 1)
                   - dy["sum"].values[s].sum() / max(dy["count"].values[s].sum(), 1))
    return np.quantile(out, [0.05, 0.95])


def report(d: pd.DataFrame):
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 300)
    rng = np.random.default_rng(3)
    d = d.copy()
    d["day"] = d["ret_ts"] // 86400
    d["hit1"] = (d["best"] >= 1).astype(float)
    d["hit2"] = (d["best"] >= 2).astype(float)
    d["scope"] = np.where(d["family"].str.startswith("deriv"), "deriv", "real")
    f = d[d["filled"]]

    def table(g, by):
        rows = []
        for key, x in g.groupby(by):
            q, u = x[x["V"]], x[~x["V"]]
            if len(q) < 50 or len(u) < 50:
                continue
            lo, hi = _boot(q, u, "hit1", rng, 1000)
            rows.append(dict(**dict(zip(by, key if isinstance(key, tuple) else (key,), strict=True)),
                             n_V=len(q), P1R_V=q["hit1"].mean(), n_base=len(u), P1R_base=u["hit1"].mean(),
                             diff=q["hit1"].mean() - u["hit1"].mean(), lo=lo, hi=hi,
                             P2R_V=q["hit2"].mean(), P2R_base=u["hit2"].mean(),
                             R_V=q["R"].mean(), R_base=u["R"].mean()))
        return pd.DataFrame(rows).round(4)

    core = f[(f["ret"] == 1) & (f["depth"] == "d0") & (f["bound"] == "body")]
    print("\n1  qualified (V=1) vs the other swing origins that broke structure (V=0): first return, near edge, body")
    print(table(core, ["scope", "iv"]).to_string(index=False))
    print(table(core[core["scope"] == "real"], ["family"]).to_string(index=False))
    print("\n2a lifecycle (return 1/2/3), real markets")
    print(table(f[(f["depth"] == "d0") & (f["bound"] == "body") & (f["scope"] == "real")], ["iv", "ret"]).to_string(index=False))
    print("\n2b depth (near edge / middle / far edge), first return, real markets")
    print(table(f[(f["ret"] == 1) & (f["bound"] == "body") & (f["scope"] == "real")], ["iv", "depth"]).to_string(index=False))
    print("\n2c boundary, first return, near edge, real markets")
    print(table(f[(f["ret"] == 1) & (f["depth"] == "d0") & (f["scope"] == "real")], ["iv", "bound"]).to_string(index=False))
    fill = d[(d["ret"] == 1) & (d["bound"] == "body") & (d["scope"] == "real")]
    print("\n   share of returns that reach each depth:",
          fill.groupby(["V", "depth"])["filled"].mean().round(3).unstack().to_string())

    # 3 quality, V=1 first returns, near edge, body, real markets
    q = core[(core["scope"] == "real") & core["V"]].copy()
    base = core[(core["scope"] == "real") & ~core["V"]]
    feats = list(FEATURES) + (["nest4h"] if "nest4h" in q else [])
    for col in feats:
        q[col] = pd.to_numeric(q[col], errors="coerce").astype(float)
    tr, te = q[q["ret_ts"] < SPLIT], q[q["ret_ts"] >= SPLIT]
    print(f"\n3  quality - V=1 first returns, real markets: {len(tr)} before 2023 (fit), {len(te)} after (judge)")
    curves = []
    for col in feats:
        x = tr[[col, "hit1"]].dropna()
        if x[col].nunique() < 3:
            curves.append(dict(feature=col, **{f"q{i}": np.nan for i in range(1, 6)}))
            continue
        bins = pd.qcut(x[col].rank(method="first"), 5, labels=False)
        m = x.groupby(bins)["hit1"].mean()
        curves.append(dict(feature=col, **{f"q{i + 1}": m.get(i, np.nan) for i in range(5)}))
    print("   P(1R) by quintile of each feature, fitting period:")
    print(pd.DataFrame(curves).round(3).to_string(index=False))
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    Xtr, Xte = tr[feats].fillna(tr[feats].median()), te[feats].fillna(tr[feats].median())
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(Xtr, tr["hit1"])
    p_tr, p_te = model.predict_proba(Xtr)[:, 1], model.predict_proba(Xte)[:, 1]
    cut = np.quantile(p_tr, 0.8)
    top = te[p_te >= cut]
    base_te = base[base["ret_ts"] >= SPLIT]
    print(f"   AUC fit {roc_auc_score(tr['hit1'], p_tr):.3f}  judge {roc_auc_score(te['hit1'], p_te):.3f}")
    print(f"   judge period: top fifth by the model n {len(top)}  P(1R) {top['hit1'].mean():.3f}  R {top['R'].mean():+.3f}"
          f" | all V=1 P(1R) {te['hit1'].mean():.3f} R {te['R'].mean():+.3f}"
          f" | V=0 baseline P(1R) {base_te['hit1'].mean():.3f} R {base_te['R'].mean():+.3f}")
    coef = pd.Series(model[-1].coef_[0], index=feats).sort_values()
    print("   standardised coefficients:", coef.round(3).to_dict())
    # formation only (nothing after the break) - the score a zone could carry from birth
    form = [c_ for c_ in FORMATION if c_ in feats]
    m2 = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(Xtr[form], tr["hit1"])
    print(f"   formation-only AUC fit {roc_auc_score(tr['hit1'], m2.predict_proba(Xtr[form])[:, 1]):.3f}  judge "
          f"{roc_auc_score(te['hit1'], m2.predict_proba(Xte[form])[:, 1]):.3f}")

    # force regimes: quartiles of each force dimension, fitting and judging periods, against V=0
    print("\n4  force regimes - P(1R) by quartile (weak / moderate / strong / extreme), V=1 first returns")
    rows = []
    for col in FORCE:
        edges = np.nanquantile(tr[col], [0.25, 0.5, 0.75])
        for name, x in (("fit", tr), ("judge", te)):
            reg = np.searchsorted(edges, x[col].to_numpy(), side="right")
            m = pd.Series(x["hit1"].to_numpy()).groupby(reg).mean()
            rows.append(dict(force=col, period=name, **{k: m.get(i, np.nan) for i, k in
                                                        enumerate(("weak", "moderate", "strong", "extreme"))}))
    print(pd.DataFrame(rows).round(3).to_string(index=False))
    print(f"   baseline V=0: fit {base[base['ret_ts'] < SPLIT]['hit1'].mean():.3f}  judge {base_te['hit1'].mean():.3f}")
    # force x imbalance
    fe, ie = np.nanquantile(tr["disp"], [1 / 3, 2 / 3]), np.nanquantile(tr["gap_pre"], [1 / 3, 2 / 3])
    for name, x in (("fit", tr), ("judge", te)):
        g = x.assign(F=np.searchsorted(fe, x["disp"], side="right"), I=np.searchsorted(ie, x["gap_pre"], side="right"))
        print(f"   force (rows, displacement tercile) x imbalance (cols, gap / pre-zone range tercile), {name}:")
        print(g.pivot_table(index="F", columns="I", values="hit1", aggfunc="mean").round(3).to_string())
    curves_plot(tr, te, base, feats)


def curves_plot(tr, te, base, feats):
    """P(1R) by quintile of each feature, fitting and judging periods, with the V=0 baseline."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cols = [c_ for c_ in feats if tr[c_].nunique() > 3]
    nc = 4
    nr = int(np.ceil(len(cols) / nc))
    fig, axes = plt.subplots(nr, nc, figsize=(18, 3.2 * nr))
    b_fit, b_te = base[base["ret_ts"] < SPLIT]["hit1"].mean(), base[base["ret_ts"] >= SPLIT]["hit1"].mean()
    for ax, col in zip(axes.flat, cols, strict=False):
        edges = np.nanquantile(tr[col], [0.2, 0.4, 0.6, 0.8])
        for name, x, style in (("before 2023", tr, "-o"), ("2023 on", te, "--s")):
            q = np.searchsorted(edges, x[col].to_numpy(), side="right")
            m = pd.Series(x["hit1"].to_numpy()).groupby(q).mean()
            ax.plot(m.index + 1, m.values, style, label=name)
        ax.axhline(b_fit, color="#999", lw=0.8)
        ax.axhline(b_te, color="#999", lw=0.8, ls="--")
        ax.set_title(col, fontsize=9)
        ax.set_xticks([1, 2, 3, 4, 5])
    axes.flat[0].legend(fontsize=7)
    for ax in axes.flat[len(cols):]:
        ax.axis("off")
    fig.suptitle("P(1R before the stop) at the first return to a qualified zone, by quintile of each feature "
                 "(grey: swing origins without the chain, V=0)", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT / "zone_event_curves.png", dpi=80)
    plt.close(fig)


def plot():
    """Qualified zone events drawn with their fingerprint: the origin (body band), every gap on the
    path, the broken swing high and the BOS bar, the returns with the R each reached."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    OUT.mkdir(parents=True, exist_ok=True)
    for sym, iv in (("EURUSD", "1h"), ("XAUUSD", "4h"), ("US Tech 100", "1h"), ("GBPJPY", "4h"),
                    ("BTCUSD", "4h"), ("Germany 40", "1h")):
        df = R.load(sym, iv)
        if df is None:
            continue
        df = df.reset_index(drop=True)
        a = P.atr(df, 14)
        rng = np.random.default_rng(len(sym))
        picks = []
        for side, frame in ((1, df), (-1, flip(df))):
            ev = pd.DataFrame(events(frame, a, side, 0.0, None, None, SEC[iv]))
            if ev.empty:
                continue
            ev = ev[ev["V"] & (ev["bound"] == "body") & (ev["depth"] == "d0")]
            picks.append(ev)
        ev = pd.concat(picks) if picks else pd.DataFrame()
        if ev.empty:
            continue
        zs = ev.drop_duplicates(["p", "side"])
        chosen = zs.iloc[np.sort(rng.choice(len(zs), min(4, len(zs)), replace=False))]
        fig, axes = plt.subplots(2, 2, figsize=(18, 11))
        o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        for ax, (_, z) in zip(axes.flat, chosen.iterrows(), strict=False):
            p, side, b = int(z.p), int(z.side), int(z.p + z.bos_bars)
            rets = ev[(ev["p"] == p) & (ev["side"] == side)].sort_values("ret")
            last = int(np.searchsorted(df["ts"].to_numpy(), rets["ret_ts"].max())) if len(rets) else b + 30
            i0, i1 = max(0, p - 30), min(len(df) - 1, last + 40)
            w = df.iloc[i0:i1 + 1]
            x = np.arange(i0, i1 + 1)
            up = (w["close"] >= w["open"]).to_numpy()
            ax.vlines(x, w["low"], w["high"], color="#555", lw=0.5)
            ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
            ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)
            far, near = (l[p], max(o[p], c[p])) if side > 0 else (h[p], min(o[p], c[p]))
            ax.add_patch(Rectangle((p - 0.4, min(far, near)), i1 - p, abs(near - far), color="#457b9d", alpha=0.25))
            for k in range(p + 2, b + 1):  # the gaps on the path
                if side > 0 and l[k] > h[k - 2]:
                    ax.add_patch(Rectangle((k - 2, h[k - 2]), 2, l[k] - h[k - 2], color="#f4a261", alpha=0.6))
                if side < 0 and h[k] < l[k - 2]:
                    ax.add_patch(Rectangle((k - 2, h[k]), 2, l[k - 2] - h[k], color="#f4a261", alpha=0.6))
            ax.axvline(b, color="k", lw=0.8, ls="--")
            ax.annotate("BOS", (b, c[b]), fontsize=8)
            for _, r in rets.iterrows():
                k = int(np.searchsorted(df["ts"].to_numpy(), r.ret_ts))
                ok = r.best >= 1 if r.filled else False
                ax.scatter([k], [near], marker="^" if side > 0 else "v", s=90,
                           color="green" if ok else "red", zorder=5)
                ax.annotate(f"r{int(r.ret)}: {r.best:.1f}R" + (" stop" if r.stopped else ""), (k, near), fontsize=7,
                            xytext=(3, -12 * side), textcoords="offset points")
            ax.set_title(f"{sym} {iv} {'bull' if side > 0 else 'bear'}  disp {z.disp:.1f}  speed {z.speed:.2f}  "
                         f"eff {z.eff_close:.2f}  BOS+{z.bos_close:.2f}  volx {z.vol_surprise:.1f}  "
                         f"gaps {int(z.n_gaps)}  obst {int(z.obstacles)}", fontsize=9)
        fig.suptitle("qualified zone events: origin band (blue), gaps on the path (orange), BOS bar (dashed); each "
                     "return: green made 1R before the stop, red did not | title: the formation fingerprint", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"events_{sym.replace(' ', '_')}_{iv}.png", dpi=80)
        plt.close(fig)
        print(f"  {sym} {iv}: {len(zs)} qualified zones", flush=True)


def confirm(d: pd.DataFrame):
    """The frozen rule (`zone_rule.json`), judged once on markets no zone study used."""
    import json
    rule = json.loads((HERE / "zone_rule.json").read_text())["rule"]
    rng = np.random.default_rng(11)
    d = d[d["filled"] & (d["ret"] == 1) & (d["depth"] == "d0") & (d["bound"] == "body")].copy()
    d["day"] = d["ret_ts"] // 86400
    d["approach"] = d["approach"].astype(float)
    slow = d["approach"] <= rule["approach_max_atr"]
    groups = {"rule: qualified, slow": d[d["V"] & slow], "qualified, any approach": d[d["V"]],
              "unqualified, slow": d[~d["V"] & slow]}
    for scope, mask in (("all", np.ones(len(d), bool)), ("crypto", d["family"].eq("crypto").to_numpy()),
                        ("metal", d["family"].eq("metal").to_numpy()), ("deriv", d["family"].eq("deriv").to_numpy())):
        print(f"\n{scope}")
        for name, g in groups.items():
            g = g[mask[g.index.map(d.index.get_loc)]] if scope != "all" else g
            if len(g) < 20:
                print(f"  {name}: n {len(g)}")
                continue
            boots = []
            days = g.groupby("day")["R"].agg(["sum", "count"])
            for _ in range(2000):
                s_ = rng.integers(0, len(days), len(days))
                boots.append(days["sum"].values[s_].sum() / days["count"].values[s_].sum())
            lo, hi = np.quantile(boots, [0.05, 0.95])
            print(f"  {name}: n {len(g)}  P(1R) {(g['best'] >= 1).mean():.3f}  R {g['R'].mean():+.3f}  "
                  f"[{lo:+.3f}, {hi:+.3f}]  by timeframe {g.groupby('iv')['R'].mean().round(3).to_dict()}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if os.environ.get("MODE") == "plot":
        plot()
        return
    if os.environ.get("MODE") == "confirm":
        import run as R
        R.FAMILY.update({s: "deriv" for s in ("Volatility 10 Index", "Volatility 50 Index", "Volatility 100 Index",
                                              "Step Index 200", "Step Index 500", "Drift Switch Index 20",
                                              "Drift Switch Index 30")})
        syms = [*R.FRESH, "XPTUSD", "XPDUSD", "XCUUSD", "Volatility 10 Index", "Volatility 50 Index",
                "Volatility 100 Index", "Step Index 200", "Step Index 500", "Drift Switch Index 20",
                "Drift Switch Index 30"]
        jobs = [(s, iv) for iv in ("1h", "4h", "1d") for s in syms]
        with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
            got = [g for g in pool.map(one, jobs) if g is not None and len(g)]
        d = pd.concat(got, ignore_index=True)
        d.to_pickle(OUT / "zone_events_confirm.pkl.gz")
        confirm(d)
        return
    import run as R
    syms = os.environ.get("SYMBOLS")
    syms = syms.split(",") if syms else [s for s in R.FAMILY if s not in R.FRESH]
    jobs = [(s, iv) for iv in os.environ.get("INTERVALS", "1h,4h,1d").split(",") for s in syms]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 20))) as pool:
        got = [g for g in pool.map(one, jobs) if g is not None and len(g)]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "zone_events.pkl.gz")
    report(d)


if __name__ == "__main__":
    main()
