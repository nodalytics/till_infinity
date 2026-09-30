"""Marcos López de Prado's methods, applied to this desk's questions.

Sources (all freely available): Bailey & López de Prado, "The Deflated Sharpe Ratio" (J. Portfolio
Management, 2014; SSRN 2460551) and "The Sharpe Ratio Efficient Frontier" (2012, SSRN 1821643, the
PSR); Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest Overfitting" (2015, SSRN
2326253) and the False Strategy Theorem; López de Prado, "Advances in Financial Machine Learning"
(Wiley 2018) ch. 3 (triple-barrier labels, meta-labeling), ch. 7 and 12 (purged / embargoed and
combinatorially purged cross-validation), ch. 10 (bet sizing from probabilities), ch. 19 (VPIN);
Easley, López de Prado & O'Hara, "Flow Toxicity and Liquidity in a High-Frequency World" (RFS 2012)
and "Discerning information from trade data" (JFE 2016, bulk volume classification); López de Prado,
"Machine Learning for Asset Managers" (Cambridge 2020) ch. 5 (trend-scanning labels) and
"Building Diversified Portfolios that Outperform Out of Sample" (JPM 2016, HRP).

Pre-registered, per part:

  PART=dsr    The desk's research survivors, deflated for the trials behind them. For a t-statistic
              the adaptation of the DSR is: under the null each of N trials is a unit-variance z, the
              expected maximum is E[max_N] = (1-g) PHI^-1(1 - 1/N) + g PHI^-1(1 - 1/(N e)) (g the
              Euler-Mascheroni constant; the False Strategy Theorem), and the deflated confidence is
              PHI(z - E[max_N]). Reported at three trial counts (the study's cells, a clustered
              effective count, and a hundred) with the Sidak family-wise confidence (1 - p)^N beside
              it. A survivor passes at deflated confidence > 0.95.
  PART=meta   Meta-labeling on production's zone touches (confirm.py's replay, reused from its saved
              rows): the primary model is the structures signal's side (fade, entered at the level
              timeframe's close); the triple-barrier label is whether the 1R target is hit before the
              structure stop within the time limit; the secondary model is gradient boosting on the
              card features and indicator states confirm.py computed (+ trend-scanning in variant B).
              Combinatorially purged cross-validation: N = 6 time groups, k = 2 test groups, 15
              splits, 5 backtest paths; training rows whose label span overlaps a test group are
              purged, and 1% of the span after each test group is embargoed. Bets are sized from the
              predicted probability, m = 2 PHI((p - 1/2) / sqrt(p (1 - p))) - 1, zero below 1/2.
              Pass: median path Sharpe > 0, >= 80% of paths positive, and >= 80% of paths beating the
              95th percentile of a random-size null (the same sizes shuffled within each test group),
              on real markets, and not on our walks. FX rollover touches are excluded, as confirm.py.
  PART=trend  Trend-scanning t-values (the OLS t of log price on time over the last L = 10, 20, 40,
              60 bars of the confirming timeframe, the L with the largest |t|) at each touch, known
              before it. Does the trend into the level separate touches that hold (hit 1R) from those
              that fail, beyond walks? Pass: AUC >= 0.53 with a day-bootstrap CI above 0.5 in both
              halves, and the walks' AUC within 0.02 of 0.5.
  PART=vpin   Bulk-volume VPIN on tick volume: buy share PHI(dP / sd(dP)) per 15m bar, VPIN the
              50-bar mean of |buy - sell| / volume. Added to a shock forecaster (a 4x-mean |r| bar in
              the next 4, anomalies.md's label, on volatility-state features). Pass: out-of-sample AUC
              gain >= 0.01 with a day-bootstrap CI above 0 in both halves, and < 0.005 on walks (whose
              volume is drawn independently of price).
"""
from __future__ import annotations

import itertools
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

PART = os.environ.get("PART", "dsr")
CONFIRM = Path(os.environ.get("CONFIRM", os.path.expanduser("~/till_infinity/data/confirm")))
OUT = Path(os.environ.get("OUT", ".data/lopezdeprado"))
GAMMA = 0.5772156649


def phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def phinv(p: float) -> float:
    from statistics import NormalDist

    return NormalDist().inv_cdf(min(max(p, 1e-12), 1 - 1e-12))


# ------------------------------------------------------------------------------------------ dsr

def expected_max(n: float) -> float:
    """E[max of n iid standard normals], the False Strategy Theorem's approximation."""
    if n <= 1:
        return 0.0
    return (1 - GAMMA) * phinv(1 - 1 / n) + GAMMA * phinv(1 - 1 / (n * math.e))


#: The survivors, as each doc reported them: (study, claim, z, trials as cells tested, a clustered
#: effective count, what the z is). z from a t, or from an estimate over its standard error.
SURVIVORS = [
    ("confirm.md", "FX 1h + 15m candle, 2R: +0.370R vs plain", 4.0, 8366, 405, "t, clustered"),
    ("confirm.md", "FX 4h + choppy 1h, 1R: +0.233R vs plain", 3.8, 8366, 405, "t, clustered"),
    ("confirm.md", "Deriv 1h + 15m sweep, 1R: +0.148R vs plain", 3.6, 8366, 405, "t, clustered"),
    ("confirm.md", "Deriv pivot + 1h MFI, 2R: +0.195R vs plain", 3.2, 8366, 405, "t, clustered"),
    ("confirm.md", "crypto 1h + TRIX, 1R: +0.226R vs plain", 5.4, 8366, 405, "t, clustered"),
    ("gaptrade.md", "Friday-close fade, gross +2.11 bps", 5.0, 24 * 14, 24, "t, weekend bootstrap"),
    ("fridayflag.md", "big-gap AUC 0.601 [0.567, 0.637]", (0.601 - 0.5) / (0.035 / 1.96), 6, 3, "AUC / se"),
    ("bandrace.md", "FX touch90 skill +0.0865 (se 0.0026)", 0.0865 / 0.0026, 4 * 4 * 8, 16, "skill / se"),
    ("bandrace.md", "FX race N=20 skill +0.0207 [+0.0152, +0.0266]", 0.0207 / 0.0029, 4 * 4 * 8, 16,
     "skill / se"),
    ("calendar-returns.md", "FX vol profile, out-of-sample corr +0.96 over 168 buckets",
     math.atanh(0.96) * math.sqrt(168 - 3), 8 * 2, 8, "Fisher z"),
    ("triage.md", "opportunity gross +0.010R [-0.080, +0.037]", 0.010 / (0.117 / 3.92), 13, 13, "t"),
    ("triage.md", "snap gross +0.011R [-0.029, +0.052]", 0.011 / (0.081 / 3.92), 13, 13, "t"),
    ("stophunt.md", "best trigger gross +0.045R", 1.2, 180, 30, "t"),
    ("anomalies.md", "shock AUC 0.76 on FX (n ~ 10^5)", 50.0, 64, 16, "AUC / se, order of magnitude"),
]


def dsr() -> None:
    print("DEFLATED SIGNIFICANCE OF THE DESK'S SURVIVORS")
    print("deflated conf = PHI(z - E[max of N null z's]); sidak = (1 - p_one_sided)^N; pass > 0.95\n")
    print(f"  {'study':20s} {'claim':62s} {'z':>6s} | {'N cells':>8s} {'defl':>6s} {'sidak':>6s} | "
          f"{'N eff':>6s} {'defl':>6s} | {'N=100':>6s}")
    for study, claim, z, n, neff, kind in SURVIVORS:
        p = 1 - phi(z)
        cells = [phi(z - expected_max(m)) for m in (n, neff, 100)]
        sidak = (1 - p) ** n
        verdict = "PASS" if cells[1] > 0.95 else "fail"
        print(f"  {study:20s} {claim:62s} {z:6.2f} | {n:8d} {cells[0]:6.3f} {sidak:6.3f} | {neff:6d} "
              f"{cells[1]:6.3f} | {cells[2]:6.3f}  {verdict} ({kind})")
    print("\n  E[max] for reference: " + ", ".join(f"N={m}: {expected_max(m):.2f}"
                                                  for m in (10, 100, 405, 1000, 8366)))


# ------------------------------------------------------------------------------------------ meta

def bet_size(p: np.ndarray) -> np.ndarray:
    """López de Prado's bet size from a probability, long-only on the primary's side."""
    p = np.clip(p, 1e-6, 1 - 1e-6)
    z = (p - 0.5) / np.sqrt(p * (1 - p))
    m = 2 * np.vectorize(phi)(z) - 1
    return np.clip(m, 0.0, 1.0)


def horizon_s(pair: str) -> float:
    import confirm as cf

    a, b = pair.split(">")
    ratio = max(cf.MIN[a] // cf.MIN[b], 1)
    return min(cf.LIMIT_HTF * ratio, cf.CAP_LIMIT) * cf.MIN[b] * 60.0


def meta_frame(universe: str, with_trend: bool) -> pd.DataFrame:
    """confirm.py's saved rows and features. The pickles are this harness family's own lab outputs,
    written by confirm.py and this file, never external input."""
    import confirm as cf

    rows = pd.read_pickle(CONFIRM / f"{universe}.pkl.gz")
    feats = pd.read_pickle(CONFIRM / f"{universe}.features.pkl.gz")
    base = rows[(rows["rule"] == "htf_close") & (rows["stop"] == "htf") & (rows["k"] == 1)]
    d = base[["sid", "pair", "family", "feed", "time", "rollover", "hit", "net"]].merge(
        feats, on=["sid", "pair"])
    d = d[~((d["family"] == "fx") & d["rollover"])].copy()
    d["pair"] = d["pair"].astype(str)
    d["family"] = d["family"].astype(str)
    d["pair_code"] = d["pair"].astype("category").cat.codes
    d["end"] = d["time"] + d["pair"].map({p: horizon_s(p) for p in d["pair"].unique()})
    if with_trend:
        tr = pd.read_pickle(OUT / f"{universe}.trend.pkl.gz")
        d = d.merge(tr, on=["sid", "pair"], how="left")
    d = d.sort_values("time").reset_index(drop=True)
    return d


def sharpe(daily: pd.Series) -> float:
    sd = daily.std(ddof=1)
    return float(daily.mean() / sd * math.sqrt(252)) if sd > 0 else float("nan")


def cpcv(d: pd.DataFrame, cols: list[str], label: str, rng: np.random.Generator, n_groups=6, k=2):
    """Combinatorially purged CV. Returns per-path Sharpe of the sized strategy, of the primary, and
    of the random-size null's 95th percentile, and the per-path AUC."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    edges = np.quantile(d["time"], np.linspace(0, 1, n_groups + 1))
    group = np.clip(np.searchsorted(edges, d["time"], side="right") - 1, 0, n_groups - 1)
    span = d["time"].max() - d["time"].min()
    embargo = 0.01 * span
    splits = list(itertools.combinations(range(n_groups), k))
    n_paths = math.comb(n_groups - 1, k - 1)
    seen = {g: 0 for g in range(n_groups)}
    size = np.full((n_paths, len(d)), np.nan)
    prob = np.full((n_paths, len(d)), np.nan)
    for test in splits:
        test_mask = np.isin(group, test)
        keep = ~test_mask
        for g in test:
            lo, hi = edges[g], edges[g + 1]
            # purge: training labels whose span [time, end] overlaps the test group; embargo after it
            overlap = (d["end"].to_numpy() >= lo) & (d["time"].to_numpy() <= hi + embargo)
            keep &= ~overlap
        if keep.sum() < 500:
            continue
        model = HistGradientBoostingClassifier(max_depth=3, max_iter=200, learning_rate=0.05,
                                               min_samples_leaf=100)
        model.fit(d.loc[keep, cols], d.loc[keep, label].astype(int))
        for g in test:
            m = group == g
            path = seen[g]
            seen[g] += 1
            p = model.predict_proba(d.loc[m, cols])[:, 1]
            prob[path, m] = p
            size[path, m] = bet_size(p)
    day = (d["time"] // 86_400).astype(int)
    out = []
    for path in range(n_paths):
        ok = ~np.isnan(size[path])
        if ok.sum() < 200:
            continue
        net = d["net"].to_numpy()
        sized = pd.Series(size[path] * net).where(ok).groupby(day).sum()
        prim = pd.Series(net).where(ok).groupby(day).sum()
        s_meta, s_prim = sharpe(sized), sharpe(prim)
        null = []
        for _ in range(100):
            shuffled = size[path].copy()
            for g in range(n_groups):
                m = (group == g) & ok
                shuffled[m] = rng.permutation(shuffled[m])
            null.append(sharpe(pd.Series(shuffled * net).where(ok).groupby(day).sum()))
        y = d[label].to_numpy()[ok].astype(int)
        auc = roc_auc_score(y, prob[path][ok]) if len(np.unique(y)) == 2 else float("nan")
        out.append({"path": path, "meta": s_meta, "primary": s_prim, "null95": float(np.nanquantile(null, 0.95)),
                    "null50": float(np.nanmedian(null)), "auc": auc, "taken": float((size[path][ok] > 0).mean()),
                    "mean_size": float(size[path][ok].mean())})
    return pd.DataFrame(out)


def meta() -> None:
    import confirm as cf

    rng = np.random.default_rng(3)
    for universe in ("real", "deriv", "walks"):
        for variant, with_trend in (("A: card + indicators", False), ("B: + trend-scanning", True)):
            if with_trend and not (OUT / f"{universe}.trend.pkl.gz").exists():
                continue
            d = meta_frame(universe, with_trend)
            cols = [*cf.FEATURES, "pair_code"] + (["trend_t", "trend_abs", "trend_len"] if with_trend else [])
            groups = [("all", d)] + ([(f, g) for f, g in d.groupby("family")] if universe == "real" else [])
            print(f"\n== META-LABELING · {universe} · {variant} · {len(d):,} touches, 1R hit {d['hit'].mean():.1%},"
                  f" primary net {d['net'].mean():+.3f}R", flush=True)
            for name, g in groups:
                if len(g) < 3000:
                    continue
                res = cpcv(g.reset_index(drop=True), cols, "hit", rng)
                if res.empty:
                    continue
                beats = (res["meta"] > res["null95"]).mean()
                pos = (res["meta"] > 0).mean()
                verdict = "PASS" if (res["meta"].median() > 0 and pos >= 0.8 and beats >= 0.8) else "fail"
                print(f"  {name:8s} n={len(g):6,} | paths {len(res)} | Sharpe meta median {res['meta'].median():+.2f}"
                      f" [{res['meta'].min():+.2f}, {res['meta'].max():+.2f}] | primary {res['primary'].median():+.2f}"
                      f" | random-size null median {res['null50'].median():+.2f}, 95th {res['null95'].median():+.2f}"
                      f" | positive {pos:.0%} | beats null95 {beats:.0%} | AUC {res['auc'].median():.3f}"
                      f" | taken {res['taken'].median():.0%} size {res['mean_size'].median():.2f} | {verdict}",
                      flush=True)


# ------------------------------------------------------------------------------------------ trend

def trend_t(logc: np.ndarray, k: int, lengths=(10, 20, 40, 60)) -> tuple[float, int]:
    best, best_len = 0.0, 0
    for n in lengths:
        if k - n + 1 < 0:
            continue
        y = logc[k - n + 1 : k + 1]
        x = np.arange(n, dtype=float)
        xm = x - x.mean()
        b = (xm * (y - y.mean())).sum() / (xm**2).sum()
        resid = y - y.mean() - b * xm
        se = math.sqrt((resid**2).sum() / (n - 2) / (xm**2).sum()) if n > 2 else float("inf")
        t = b / se if se > 0 else 0.0
        if abs(t) > abs(best):
            best, best_len = t, n
    return best, best_len


def trend() -> None:
    import confirm as cf

    universe = cf.UNIVERSE
    frames = cf.load()
    feats = pd.read_pickle(CONFIRM / f"{universe}.features.pkl.gz")[["sid", "pair"]]
    rows = pd.read_pickle(CONFIRM / f"{universe}.pkl.gz")
    base = rows[(rows["rule"] == "htf_close") & (rows["stop"] == "htf") & (rows["k"] == 1)][
        ["sid", "pair", "feed", "time"]]
    d = base.merge(feats, on=["sid", "pair"]).drop_duplicates(["sid", "pair"])
    series = {(s.lower(), iv): (df["ts"].to_numpy(), np.log(df["close"].to_numpy())) for (s, iv), df in frames.items()}
    touches = __import__("json").loads((CONFIRM / f"{universe}.touches.json").read_text())
    side = {i: (1 if z["above"] else -1) for i, z in enumerate(touches)}
    out = []
    for sid, pair, feed, t in d[["sid", "pair", "feed", "time"]].itertuples(index=False):
        b = str(pair).split(">")[1]
        got = series.get((str(feed), b))
        if got is None:
            continue
        ts, logc = got
        k = int(np.searchsorted(ts, t, side="left")) - 1  # bars that closed at or before the touch opened
        if k < 60:
            continue
        tt, n = trend_t(logc, k)
        # signed so that positive is a trend *with* the fade's side (price already turning its way)
        out.append((sid, pair, tt * side[int(sid)], abs(tt), n))
    tr = pd.DataFrame(out, columns=["sid", "pair", "trend_t", "trend_abs", "trend_len"])
    OUT.mkdir(parents=True, exist_ok=True)
    tr.to_pickle(OUT / f"{universe}.trend.pkl.gz")
    print(f"{universe}: trend-scanning t for {len(tr):,} touch x pair", flush=True)


def auc_ci(y, s, days, rng, n=300):
    from sklearn.metrics import roc_auc_score

    y, s, days = np.asarray(y), np.asarray(s), np.asarray(days)
    base = roc_auc_score(y, s)
    uniq = np.unique(days)
    by = {u: np.flatnonzero(days == u) for u in uniq}
    draws = []
    for _ in range(n):
        idx = np.concatenate([by[u] for u in rng.choice(uniq, len(uniq))])
        if len(np.unique(y[idx])) == 2:
            draws.append(roc_auc_score(y[idx], s[idx]))
    return base, np.quantile(draws, [0.025, 0.975])


def trend_report() -> None:
    rng = np.random.default_rng(5)
    print("\nTREND-SCANNING: does the trend into the level separate touches that hit 1R?")
    print("  trend_t > 0 = price already trending the fade's way; |t| = trend strength\n")
    for universe in ("real", "deriv", "walks"):
        path = OUT / f"{universe}.trend.pkl.gz"
        if not path.exists():
            continue
        d = meta_frame(universe, True).dropna(subset=["trend_t"])
        cut = d["time"].quantile(0.5)
        groups = [("all", d)] + ([(f, g) for f, g in d.groupby("family")] if universe == "real" else [])
        for name, g in groups:
            if len(g) < 1000:
                continue
            days = (g["time"] // 86_400).astype(int)
            for feat in ("trend_t", "trend_abs"):
                a, ci = auc_ci(g["hit"].astype(int), g[feat], days, rng)
                h = [auc_ci(p["hit"].astype(int), p[feat], (p["time"] // 86_400).astype(int), rng, n=100)[0]
                     for p in (g[g["time"] < cut], g[g["time"] >= cut])]
                print(f"  {universe:6s} {name:8s} {feat:9s} n={len(g):6,} AUC {a:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]"
                      f" halves {h[0]:.3f} / {h[1]:.3f}", flush=True)


# ------------------------------------------------------------------------------------------ vpin

def vpin_frame(sym: str) -> pd.DataFrame | None:
    import indicators as ind

    df = ind.frame(sym, "15m")
    if df is None or len(df) < 5000:
        return None
    df = df.reset_index(drop=True)
    if "volume" not in df or not (df["volume"] > 0).any():
        rng = np.random.default_rng(abs(hash(sym)) % 2**32)
        df["volume"] = rng.poisson(100, len(df)).astype(float)  # walks: volume independent of price
    c = np.log(df["close"].to_numpy())
    r = np.diff(c, prepend=c[0])
    h, lo = np.log(df["high"].to_numpy()), np.log(df["low"].to_numpy())
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - lo, np.abs(h - prev), np.abs(lo - prev)])
    sig = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().to_numpy()
    norm = pd.Series(np.abs(r)).rolling(500, min_periods=250).mean().to_numpy()
    shock = np.abs(r) > 4 * np.r_[np.nan, norm[:-1]]
    ahead = pd.Series(shock.astype(float)).rolling(4).max().shift(-4).to_numpy()
    sd = pd.Series(r).rolling(500, min_periods=250).std().shift(1).to_numpy()
    buy = np.vectorize(phi)(np.nan_to_num(r / np.where(sd > 0, sd, np.nan)))
    v = df["volume"].to_numpy().astype(float)
    imb = np.abs(2 * buy - 1) * v
    vpin = pd.Series(imb).rolling(50, min_periods=25).sum() / pd.Series(v).rolling(50, min_periods=25).sum()
    ts = df["ts"].to_numpy()
    hour = (ts // 3600) % 24
    out = pd.DataFrame({
        "time": ts, "y": ahead,
        "lvol": np.log(sig / pd.Series(sig).rolling(500, min_periods=250).mean().to_numpy()),
        "vov": pd.Series(np.log(sig)).diff().rolling(50).std().to_numpy(),
        "shocks20": pd.Series(shock.astype(float)).rolling(20).sum().to_numpy(),
        "shocks100": pd.Series(shock.astype(float)).rolling(100).sum().to_numpy(),
        "hsin": np.sin(2 * np.pi * hour / 24), "hcos": np.cos(2 * np.pi * hour / 24),
        "vpin": vpin.to_numpy(),
        "vpin_rank": vpin.rolling(500, min_periods=250).rank(pct=True).to_numpy(),
    })
    return out.dropna()


def vpin() -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier

    import indicators as ind

    rng = np.random.default_rng(9)
    groups = {"fx": [s for s, f in ind.FAMILY.items() if f == "fx"],
              "crypto": [s for s, f in ind.FAMILY.items() if f == "crypto"],
              "deriv": [s for s, f in ind.FAMILY.items() if f == "deriv"],
              "walks": [f"walk_{i}" for i in range(6)]}
    base_cols = ["lvol", "vov", "shocks20", "shocks100", "hsin", "hcos"]
    print("\nVPIN (bulk volume classification) added to a shock forecaster, 15m, next-4-bar 4x shock")
    for fam, syms in groups.items():
        frames = [f for f in (vpin_frame(s) for s in syms) if f is not None]
        if not frames:
            continue
        d = pd.concat(frames, ignore_index=True).sort_values("time")
        cut = d["time"].quantile(0.6)
        tr, te = d[d["time"] < cut], d[d["time"] >= cut]
        tr = tr.sample(min(300_000, len(tr)), random_state=0)
        preds = {}
        for name, cols in (("base", base_cols), ("vpin", [*base_cols, "vpin", "vpin_rank"])):
            m = HistGradientBoostingClassifier(max_depth=4, max_iter=200, learning_rate=0.05, min_samples_leaf=300)
            m.fit(tr[cols], tr["y"].astype(int))
            preds[name] = m.predict_proba(te[cols])[:, 1]
        from sklearn.metrics import roc_auc_score

        y = te["y"].astype(int).to_numpy()
        days = (te["time"] // 86_400).astype(int).to_numpy()
        uniq = np.unique(days)
        by = {u: np.flatnonzero(days == u) for u in uniq}
        gains = []
        for _ in range(200):
            idx = np.concatenate([by[u] for u in rng.choice(uniq, len(uniq))])
            if len(np.unique(y[idx])) == 2:
                gains.append(roc_auc_score(y[idx], preds["vpin"][idx]) - roc_auc_score(y[idx], preds["base"][idx]))
        half = te["time"] < te["time"].quantile(0.5)
        hg = []
        for m in (half.to_numpy(), ~half.to_numpy()):
            hg.append(roc_auc_score(y[m], preds["vpin"][m]) - roc_auc_score(y[m], preds["base"][m]))
        a0, a1 = roc_auc_score(y, preds["base"]), roc_auc_score(y, preds["vpin"])
        ci = np.quantile(gains, [0.025, 0.975])
        print(f"  {fam:7s} n test {len(te):7,} shock rate {y.mean():.3f} | AUC base {a0:.4f} + vpin {a1:.4f} |"
              f" gain {a1 - a0:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}] halves {hg[0]:+.4f} / {hg[1]:+.4f}", flush=True)


if __name__ == "__main__":
    {"dsr": dsr, "meta": meta, "trend": trend, "trend_report": trend_report, "vpin": vpin}[PART]()
