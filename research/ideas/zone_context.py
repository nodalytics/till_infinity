"""What gives a zone its direction, beyond the break and the gap? Three kinds of evidence a single
chart's geometry does not hold, and two more it does. Pre-registered 2026-10-03, before any run.

Built on `zone_events.py` (its events, outcomes and V = 1 / V = 0 baseline). Every test reads the
qualified zones' first returns (near edge, body band) against the unqualified swing origins'
returns with the same reading, by quintile or flag, before and after a split, on P(1R) and net R.

  structure  the return leg's own shape, from the post-BOS peak to the bar before the return:
             counter (it closed below a minor 2/2 swing low formed after the BOS - a change of
             character against the zone), n_counter, pb_eff (net fall / path: low = corrective),
             pb_gaps (bearish gaps 0.1+ ATR), pb_bars
  focus      production's FOCuS changepoints and the zone: one dated at the origin, one in the leg,
             the lag to it, one against the zone on the return leg, one the zone's way just before it
  cusum      CUSUM ignition (k 0.5, h 5): the zone's way during the leg, against it on the return leg,
             the zone's way just before the return
  regime     (asked for later, NautilusTrader's indicators) VHF and Kaufman efficiency before the origin
             and before the return, pressure on the leg and on the return leg, and their swing (an
             origin that is the lowest of 20+ bars); flow adds book imbalance (bid vs ask depth within
             1%, the zone's way) at the return and over the pullback, from 2023
  rare       extraordinary swing points: the top 10 / 5 / 2% of left_extent, origin_tr, origin_vol,
             stretch, the fall's speed, displacement and relative force, thresholds from before 2023,
             and pairs of them (each top 10%), qualified zones vs ordinary swing points in the tail
  anchors    the zone band (+-0.25 ATR) holding what other participants watch: the previous day's
             or week's high/low, the week's or month's open, a big round number, a daily 5/5
             swing extreme
  smt        a correlated twin at the same moment (EURUSD/GBPUSD, AUDUSD/NZDUSD, EURJPY/GBPJPY,
             US500/NAS100, US30/US500, XAU/XAG, BTC/ETH, SOL/ETH, WTI/Brent, both ways): how much of
             the same leg the twin had given back (b_retrace: (its high since the BOS - its low since
             the peak) / (that high - its low over origin..BOS)) while this market reached its zone;
             smt = the twin gave back 0.3 less of its leg
  flow       Binance USD-M perpetuals (12 coins), zone events rebuilt on Binance's own candles, fees
             0.07% of price a trade. On the leg out: taker share the zone's way (buying for a bull
             zone), volume surge (leg / the 20 bars before), open-interest change; on the return
             leg: taker share the zone's way, volume against the leg's, open-interest change;
             funding at the return the zone's way (positive: the crowd already leans with it).
             Open interest exists from 2023: its split is 2024-09-01, the rest's 2023-01-01

  OUT=... MT5BT_DB=... BASE=<zone_events pickle> MODE=structure|smt|flow|rare|regime|plot python research/ideas/zone_context.py
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
import zone_events as E  # noqa: E402

OUT = Path(os.environ.get("OUT", ".data/zone_context"))
BASE = os.environ.get("BASE", "")
BIN = Path(os.environ.get("BINANCE", os.path.expanduser("~/till_infinity/data/binance")))
SPLIT = pd.Timestamp("2023-01-01", tz="UTC").timestamp()
SPLIT_OI = pd.Timestamp("2024-09-01", tz="UTC").timestamp()
TWINS = {"EURUSD": "GBPUSD", "AUDUSD": "NZDUSD", "EURJPY": "GBPJPY", "US SP 500": "US Tech 100",
         "Wall Street 30": "US SP 500", "XAUUSD": "XAGUSD", "BTCUSD": "ETHUSD", "SOLUSD": "ETHUSD",
         "US Oil": "UK Brent Oil"}
TWINS.update({v: k for k, v in list(TWINS.items()) if v not in TWINS})
COINS = ("BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX")


def first_returns(d: pd.DataFrame) -> pd.DataFrame:
    d = d[d["filled"] & (d["depth"] == "d0") & (d["bound"] == "body") & (d["ret"] == 1)].copy()
    d["hit"] = (d["best"] >= 1).astype(float)
    return d


def curve(d: pd.DataFrame, col: str, split: float, q: int = 5) -> pd.DataFrame:
    """P(1R) and R by quantile (or by value, for a flag) of `col`, V = 1 and V = 0, each half."""
    x = d.dropna(subset=[col]).copy()
    if x[col].dtype == bool or x[col].nunique() <= 2:
        x["bin"] = x[col].astype(int)
    else:
        edges = np.nanquantile(x.loc[x["ret_ts"] < split, col].astype(float), np.linspace(0, 1, q + 1)[1:-1])
        x["bin"] = np.searchsorted(edges, x[col].astype(float).to_numpy(), side="right") + 1
    x["half"] = np.where(x["ret_ts"] < split, "fit", "judge")
    g = x.groupby(["V", "half", "bin"]).agg(n=("hit", "size"), P1R=("hit", "mean"), R=("R", "mean"))
    return g.round(3).unstack(["V", "half"])


def report_structure(d):
    d = first_returns(d)
    d = d[~d["family"].str.startswith("deriv")]
    pd.set_option("display.width", 250)
    for col in ("fc_origin", "fc_leg", "fc_lag", "fc_against", "fc_with", "fc6_origin", "fc6_leg", "fc6_against",
                "cu_leg", "cu_against", "cu_with", "counter", "n_counter", "pb_eff", "pb_gaps", "pb_bars", "at_pdh", "at_pdl", "at_pwh", "at_pwl",
                "at_wopen", "at_mopen", "at_round", "at_dswing", "at_any"):
        if col not in d:
            continue
        if col == "n_counter":
            d[col] = d[col].clip(upper=5)
        print(f"\n{col}  (rows: quantile or flag; V True = qualified zones, False = baseline; fit < 2023 <= judge)")
        print(curve(d, col, SPLIT).to_string())


def report_regime(d):
    """Regime and pressure from Nautilus's indicator set, and their swing: an origin that is the
    lowest of 20+ bars. Quintiles on qualified zones vs ordinary swing points, both halves."""
    d = first_returns(d)
    d = d[~d["family"].str.startswith("deriv")].copy()
    d["swing20"] = d["left_extent"].astype(float) >= 20
    pd.set_option("display.width", 250)
    for col in ("vhf_o", "vhf_r", "er_o", "er_r", "press_leg", "press_pb", "swing20"):
        d[col] = d[col].astype(float) if col != "swing20" else d[col]
        print(f"\n{col}")
        print(curve(d, col, SPLIT).to_string())


def report_rare(d):
    """Extraordinary swing points: the rarest tails of each measure, thresholds from before 2023,
    qualified zones against ordinary swing points in the same tail, judged after."""
    d = first_returns(d)
    d = d[~d["family"].str.startswith("deriv")].copy()
    d["pre_speed"] = d["pre_speed"].astype(float)
    cols = ("left_extent", "origin_tr", "origin_vol", "stretch", "pre_speed", "disp", "rel_force")
    fit = d[d["ret_ts"] < SPLIT]
    rows, tails = [], {}
    for col in cols:
        x = d[col].astype(float)
        for q in (0.9, 0.95, 0.98):
            cut = np.nanquantile(fit[col].astype(float), q)
            tails[(col, q)] = x >= cut
            for V in (True, False):
                for half, m in (("fit", d["ret_ts"] < SPLIT), ("judge", d["ret_ts"] >= SPLIT)):
                    g = d[(x >= cut) & (d["V"] == V) & m]
                    rows.append(dict(measure=col, tail=f"top {round((1 - q) * 100)}%", V=V, half=half, n=len(g),
                                     P1R=g["hit"].mean(), R=g["R"].mean()))
    t = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    print("\nrarest swing points (thresholds from before 2023): P(1R) and R, qualified (True) vs ordinary (False)")
    print(t.pivot_table(index=["measure", "tail"], columns=["V", "half"], values=["n", "R"]).round(3).to_string())
    print("\nall first returns for scale:", d.groupby(["V", np.where(d["ret_ts"] < SPLIT, "fit", "judge")])["R"].mean().round(3).to_dict())
    # pairs of rare conditions (top 10% of each), qualified zones
    pairs = []
    for i, a_ in enumerate(cols):
        for b_ in cols[i + 1:]:
            m = tails[(a_, 0.9)] & tails[(b_, 0.9)] & d["V"]
            for half, mm in (("fit", d["ret_ts"] < SPLIT), ("judge", d["ret_ts"] >= SPLIT)):
                g = d[m & mm]
                pairs.append(dict(pair=f"{a_} & {b_}", half=half, n=len(g), R=g["R"].mean()))
    pr = pd.DataFrame(pairs).pivot_table(index="pair", columns="half", values=["n", "R"]).round(3)
    print("\npairs of rare conditions (each top 10%), qualified zones:")
    print(pr.to_string())


# -------------------------------------------------------------------------------------------- smt

def smt_one(job):
    import run as R
    sym, iv, rows = job
    R.DB = os.environ.get("MT5BT_DB")
    A, B = R.load(sym, iv), R.load(TWINS[sym], iv)
    if A is None or B is None:
        return None
    A, B = A.reset_index(drop=True), B.reset_index(drop=True)
    ta, tb_ = A["ts"].to_numpy(), B["ts"].to_numpy()
    out = []
    for r in rows.itertuples():
        s = int(r.side)
        ah, al = (A["high"].to_numpy(), A["low"].to_numpy()) if s > 0 else (-A["low"].to_numpy(), -A["high"].to_numpy())
        bh, bl = (B["high"].to_numpy(), B["low"].to_numpy()) if s > 0 else (-B["low"].to_numpy(), -B["high"].to_numpy())
        p, b, pk, k = int(r.p), int(r.b_idx), int(r.peak_idx), int(r.k_idx)
        t_p, t_b, t_pk, t_k = ta[p], ta[b], ta[pk], ta[k]

        def retrace(hh, ll, t):
            i_p, i_b = np.searchsorted(t, t_p), np.searchsorted(t, t_b, side="right")
            i_k = np.searchsorted(t, t_k)  # bars before the return bar
            i_pk = np.searchsorted(t, t_pk)
            if not (i_p < i_b <= i_pk < i_k):
                return np.nan
            low0 = ll[i_p:i_b].min()
            high = hh[i_b:i_k].max()
            now = ll[i_pk:i_k].min()
            return (high - now) / (high - low0) if high > low0 else np.nan

        a_r, b_r = retrace(ah, al, ta), retrace(bh, bl, tb_)
        out.append(dict(idx=r.Index, a_retrace=a_r, b_retrace=b_r))
    return pd.DataFrame(out)


def report_smt(d):
    d = first_returns(d)
    d = d[d["sym"].isin(TWINS)]
    jobs = [(sym, iv, g) for (sym, iv), g in d.groupby(["sym", "iv"])]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        got = [g for g in pool.map(smt_one, jobs) if g is not None]
    s = pd.concat(got).set_index("idx")
    d = d.join(s)
    d["rel"] = d["a_retrace"] - d["b_retrace"]
    d["smt"] = d["rel"] >= 0.3
    d.to_pickle(OUT / "smt.pkl.gz")
    pd.set_option("display.width", 250)
    print(f"\nSMT: {len(d)} first returns with a twin; twin retrace median {d['b_retrace'].median():.2f}, "
          f"this market {d['a_retrace'].median():.2f}; smt share {d['smt'].mean():.3f}")
    for col in ("smt", "rel", "b_retrace"):
        print(f"\n{col}")
        print(curve(d, col, SPLIT).to_string())


# ------------------------------------------------------------------------------------------- flow

def _binance(coin, iv):
    z = np.load(BIN / f"{coin}USDT.klines.{iv}.npz")
    df = pd.DataFrame({k: z[k] for k in ("time", "open", "high", "low", "close", "volume", "taker_buy_volume")})
    return df.rename(columns={"time": "ts"}).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def flow_one(job):
    coin, iv = job
    try:
        df = _binance(coin, iv)
    except OSError:
        return None
    a = P.atr(df, 14)
    rows = []
    for side, frame in ((1, df), (-1, E.flip(df))):
        rows += E.events(frame, a, side, 0.0, None, None, E.SEC[iv], spread_frac=0.0007)
    d = first_returns(pd.DataFrame(rows))
    if d.empty:
        return None
    v, tbv = df["volume"].to_numpy(), df["taker_buy_volume"].to_numpy()
    ts = df["ts"].to_numpy()
    try:
        m = np.load(BIN / f"{coin}USDT.metrics.npz")
        oi_t, oi = m["time"], m["sum_open_interest"]
    except OSError:
        oi_t = oi = np.zeros(0)
    try:
        fr = pd.read_csv(BIN / f"{coin}USDT.funding.csv")
        f_t = (fr.iloc[:, 0].to_numpy() // (1000 if fr.iloc[:, 0].max() > 1e11 else 1)).astype(np.int64)
        f_r = fr.iloc[:, -1].to_numpy(float)
    except OSError:
        f_t = f_r = np.zeros(0)

    try:
        bk = np.load(BIN / f"{coin}USDT.book15m.npz")
        bk_t = bk["time"]
        bk_imb = (bk["bid1_mean"] - bk["ask1_mean"]) / np.maximum(bk["bid1_mean"] + bk["ask1_mean"], 1e-12)
    except OSError:
        bk_t = bk_imb = np.zeros(0)

    def book_at(t0, t1):
        """Mean depth imbalance within 1% over book snapshots in [t0, t1) (one if t0 == t1)."""
        i0, i1 = np.searchsorted(bk_t, t0), np.searchsorted(bk_t, t1)
        if i1 <= i0:
            j = np.searchsorted(bk_t, t1, side="right") - 1
            return bk_imb[j] if 0 <= j < len(bk_imb) and t1 - bk_t[j] < 3600 else np.nan
        return float(np.mean(bk_imb[i0:i1]))

    def oi_at(t):
        j = np.searchsorted(oi_t, t, side="right") - 1
        return oi[j] if 0 <= j < len(oi) and t - oi_t[j] < 3600 else np.nan

    out = []
    for r in d.itertuples():
        s = int(r.side)
        p, b, pk, k = int(r.p), int(r.b_idx), int(r.peak_idx), int(r.k_idx)
        share = lambda i0, i1: np.sum(tbv[i0:i1]) / max(np.sum(v[i0:i1]), 1e-12)  # noqa: E731
        leg_buy = share(p, b + 1)
        pb_buy = share(pk, k) if k > pk else np.nan
        fz = np.searchsorted(f_t, ts[k], side="right") - 1
        out.append(dict(
            leg_taker=leg_buy if s > 0 else 1 - leg_buy,
            vol_surge=np.mean(v[p:b + 1]) / max(np.mean(v[max(0, p - 20):p]), 1e-12) if p >= 5 else np.nan,
            oi_leg=oi_at(ts[b]) / oi_at(ts[p]) - 1,
            pb_taker=(pb_buy if s > 0 else 1 - pb_buy) if pb_buy == pb_buy else np.nan,
            pb_vol=np.mean(v[pk:k]) / max(np.mean(v[p:b + 1]), 1e-12) if k > pk else np.nan,
            oi_pb=oi_at(ts[k - 1]) / oi_at(ts[pk]) - 1 if k > pk else np.nan,
            funding=s * f_r[fz] if 0 <= fz < len(f_r) else np.nan,
            # book imbalance the zone's way: bids over asks for a bull zone, at the return and over the pullback
            book_r=s * book_at(ts[k], ts[k]), book_pb=s * book_at(ts[pk], ts[k]) if k > pk else np.nan))
    d = d.reset_index(drop=True).join(pd.DataFrame(out))
    print(f"  flow {coin} {iv}: {len(d)} first returns", flush=True)
    return d.assign(sym=coin, iv=iv, family="crypto")


def report_flow():
    jobs = [(c, iv) for iv in ("1h", "4h") for c in COINS]
    with ProcessPoolExecutor(int(os.environ.get("WORKERS", 16))) as pool:
        got = [g for g in pool.map(flow_one, jobs) if g is not None]
    d = pd.concat(got, ignore_index=True)
    d.to_pickle(OUT / "flow.pkl.gz")
    pd.set_option("display.width", 250)
    print(f"\nflow: {len(d)} first returns on Binance (V=1 {int(d['V'].sum())}); all R {d['R'].mean():+.3f}, "
          f"V=1 {d.loc[d['V'], 'R'].mean():+.3f}, V=0 {d.loc[~d['V'], 'R'].mean():+.3f}")
    for col, split in (("leg_taker", SPLIT), ("vol_surge", SPLIT), ("pb_taker", SPLIT), ("pb_vol", SPLIT),
                       ("funding", SPLIT), ("oi_leg", SPLIT_OI), ("oi_pb", SPLIT_OI), ("book_r", SPLIT_OI),
                       ("book_pb", SPLIT_OI)):
        print(f"\n{col}")
        print(curve(d, col, split).to_string())


# ------------------------------------------------------------------------------------------- plot

def plot():
    """One sheet per test: the zone and the evidence each test reads, four examples each, and the
    quantile curves of P(1R) for qualified zones against the baseline."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    import run as R
    R.DB = os.environ.get("MT5BT_DB")
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(5)

    def candles(ax, df, i0, i1, color=True):
        w = df.iloc[i0:i1 + 1]
        x = np.arange(i0, i1 + 1)
        up = (w["close"] >= w["open"]).to_numpy()
        ax.vlines(x, w["low"], w["high"], color="#555", lw=0.5)
        ax.bar(x[up], (w["close"] - w["open"])[up], bottom=w["open"][up], color="#2a9d8f", width=0.7)
        ax.bar(x[~up], (w["close"] - w["open"])[~up], bottom=w["open"][~up], color="#e76f51", width=0.7)

    def zone_box(ax, df, r):
        o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        p = int(r.p)
        far, near = (l[p], max(o[p], c[p])) if r.side > 0 else (h[p], min(o[p], c[p]))
        ax.add_patch(Rectangle((p, min(far, near)), int(r.k_idx) - p, abs(near - far), color="#457b9d", alpha=0.3))
        ax.axvline(int(r.b_idx), color="k", ls="--", lw=0.8)
        ax.axvline(int(r.peak_idx), color="#999", ls=":", lw=0.8)
        ax.scatter([int(r.k_idx)], [near], marker="^" if r.side > 0 else "v", s=90,
                   color="green" if r.best >= 1 else "red", zorder=5)

    base = first_returns(pd.read_pickle(BASE))
    base = base[~base["family"].str.startswith("deriv") & base["V"] & (base["iv"] == "1h")]
    # structure
    for flag, title in ((True, "return leg broke a minor low after the BOS (counter-CHoCH)"),
                        (False, "return leg kept the structure (no counter-CHoCH)")):
        pick = base[base["counter"] == flag]
        pick = pick.iloc[rng.choice(len(pick), min(4, len(pick)), replace=False)]
        fig, axes = plt.subplots(2, 2, figsize=(18, 10))
        for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
            df = R.load(r.sym, r.iv).reset_index(drop=True)
            i0, i1 = max(0, int(r.p) - 20), min(len(df) - 1, int(r.k_idx) + 40)
            candles(ax, df, i0, i1)
            zone_box(ax, df, r)
            ax.set_title(f"{r.sym} {r.iv} {'bull' if r.side > 0 else 'bear'}  counter breaks {int(r.n_counter)}  "
                         f"pullback eff {r.pb_eff:.2f}  gaps {int(r.pb_gaps)}  -> {r.best:.1f}R", fontsize=9)
        fig.suptitle(f"structure: {title} | blue zone, dashed BOS, dotted post-BOS peak, triangle the return "
                     "(green made 1R)", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / f"structure_{'counter' if flag else 'kept'}.png", dpi=80)
        plt.close(fig)
    # FOCuS and CUSUM with the zones: the fires drawn on the chart
    from survivors import cusum as _cusum
    for col, title in (("fc6_origin", "a FOCuS change dated at the origin (threshold 6)"),
                       ("cu_leg", "a CUSUM ignition the zone's way during the leg"),
                       ("cu_against", "a CUSUM ignition against the zone on the return leg")):
        pick = base[base[col].astype(bool)] if col in base else base.iloc[0:0]
        if pick.empty:
            continue
        pick = pick.iloc[rng.choice(len(pick), min(4, len(pick)), replace=False)]
        fig, axes = plt.subplots(2, 2, figsize=(18, 10))
        for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
            df = R.load(r.sym, r.iv).reset_index(drop=True)
            frame = df if r.side > 0 else E.flip(df)
            c_ = frame["close"].to_numpy()
            rr = np.r_[0.0, np.diff(c_)]
            sc = pd.Series(np.abs(rr)).ewm(span=100).mean().shift(1).to_numpy() * np.sqrt(np.pi / 2)
            fu6, _ = P.focus_series(rr, sc, 6.0, True)
            fd6, _ = P.focus_series(rr, sc, 6.0, False)
            cs = _cusum(frame, P.atr(frame, 14))
            i0, i1 = max(0, int(r.p) - 20), min(len(df) - 1, int(r.k_idx) + 40)
            candles(ax, df, i0, i1)
            zone_box(ax, df, r)
            yl, yh = df["low"].iloc[i0:i1 + 1].min(), df["high"].iloc[i0:i1 + 1].max()
            for arr, col_, lab in ((np.flatnonzero(fu6), "#2a9d8f", "FOCuS zone way"),
                                   (np.flatnonzero(fd6), "#e76f51", "FOCuS against")):
                xs = arr[(arr >= i0) & (arr <= i1)]
                ax.scatter(xs, np.full(len(xs), yl), marker="|", s=200, color=col_, label=lab)
            for sd, col_, lab in ((1, "#1d3557", "CUSUM zone way"), (-1, "purple", "CUSUM against")):
                xs = cs.loc[(cs["side"] == sd) & (cs["i"] >= i0) & (cs["i"] <= i1), "i"].to_numpy()
                ax.scatter(xs, np.full(len(xs), yh), marker="*", s=90, color=col_, label=lab)
            ax.legend(fontsize=6, loc="upper left")
            ax.set_title(f"{r.sym} {r.iv} {'bull' if r.side > 0 else 'bear'}  -> {r.best:.1f}R"
                         + ("  stopped" if r.stopped else ""), fontsize=9)
        fig.suptitle(f"zones with {title} | ticks at the bottom: FOCuS fires; stars at the top: CUSUM ignitions | "
                     "blue zone, dashed BOS, dotted peak, triangle the return", fontsize=10)
        fig.tight_layout()
        fig.savefig(OUT / f"zones_{col}.png", dpi=80)
        plt.close(fig)
    # smt
    sp = OUT / "smt.pkl.gz"
    if sp.exists():
        s = pd.read_pickle(sp)
        s = s[s["V"] & (s["iv"] == "1h") & s["rel"].notna()]
        for flag in (True, False):
            pick = s[s["smt"] == flag]
            pick = pick.iloc[rng.choice(len(pick), min(4, len(pick)), replace=False)]
            fig, axes = plt.subplots(2, 2, figsize=(18, 10))
            for ax, (_, r) in zip(axes.flat, pick.iterrows(), strict=False):
                A = R.load(r.sym, r.iv).reset_index(drop=True)
                B = R.load(TWINS[r.sym], r.iv).reset_index(drop=True)
                i0, i1 = max(0, int(r.p) - 20), min(len(A) - 1, int(r.k_idx) + 30)
                ta = A["ts"].to_numpy()[i0:i1 + 1]
                bb = B.drop_duplicates("ts").set_index("ts").reindex(ta)
                na = A["close"].iloc[i0:i1 + 1].to_numpy()
                ax.plot(np.arange(i0, i1 + 1), (na - na[0]) / na[0] * 100, color="#1d3557", label=r.sym)
                nb = bb["close"].to_numpy()
                ax.plot(np.arange(i0, i1 + 1), (nb - nb[0]) / nb[0] * 100, color="#e76f51", label=TWINS[r.sym])
                for x_, ls in ((int(r.p), "-"), (int(r.b_idx), "--"), (int(r.peak_idx), ":"), (int(r.k_idx), "-")):
                    ax.axvline(x_, color="#999", ls=ls, lw=0.8)
                ax.legend(fontsize=7)
                ax.set_title(f"{r.sym} vs {TWINS[r.sym]} {r.iv} {'bull' if r.side > 0 else 'bear'}  gave back "
                             f"{r.a_retrace:.2f} vs twin {r.b_retrace:.2f}  -> {r.best:.1f}R", fontsize=9)
            fig.suptitle(f"SMT {'divergence (the twin gave back 0.3+ less)' if flag else 'no divergence'}: % change "
                         "from the window start; lines: origin, BOS (dashed), peak (dotted), return", fontsize=11)
            fig.tight_layout()
            fig.savefig(OUT / f"smt_{'divergent' if flag else 'together'}.png", dpi=80)
            plt.close(fig)
    # flow
    fp = OUT / "flow.pkl.gz"
    if fp.exists():
        f = pd.read_pickle(fp)
        f = f[f["V"] & (f["iv"] == "1h") & f["oi_pb"].notna()]
        pick = f.iloc[rng.choice(len(f), min(4, len(f)), replace=False)]
        fig = plt.figure(figsize=(18, 12))
        gs = fig.add_gridspec(4, 2, height_ratios=[3, 1, 3, 1])
        for n_, (_, r) in enumerate(pick.iterrows()):
            df = _binance(r.sym, r.iv)
            m = np.load(BIN / f"{r.sym}USDT.metrics.npz")
            i0, i1 = max(0, int(r.p) - 20), min(len(df) - 1, int(r.k_idx) + 30)
            ax = fig.add_subplot(gs[(n_ // 2) * 2, n_ % 2])
            az = fig.add_subplot(gs[(n_ // 2) * 2 + 1, n_ % 2])
            candles(ax, df, i0, i1)
            zone_box(ax, df, r)
            x = np.arange(i0, i1 + 1)
            vv, tb = df["volume"].to_numpy()[i0:i1 + 1], df["taker_buy_volume"].to_numpy()[i0:i1 + 1]
            az.bar(x, 2 * tb - vv, color=np.where(2 * tb - vv > 0, "#2a9d8f", "#e76f51"), width=0.8)
            ax2 = az.twinx()
            oi = pd.Series(m["sum_open_interest"], index=m["time"])
            oi = oi[~oi.index.duplicated()].sort_index().reindex(df["ts"].to_numpy()[i0:i1 + 1], method="ffill")
            ax2.plot(x, oi.to_numpy(), color="#1d3557", lw=1)
            az.set_ylabel("taker delta / OI", fontsize=8)
            ax.set_title(f"{r.sym}USDT {r.iv} {'bull' if r.side > 0 else 'bear'}  leg taker {r.leg_taker:.2f}  "
                         f"return taker {r.pb_taker:.2f}  OI on return {r.oi_pb:+.1%}  -> {r.best:.1f}R", fontsize=9)
        fig.suptitle("Binance flow: zone (blue), BOS (dashed), peak (dotted), return (triangle); below: taker buy minus "
                     "sell volume (bars) and open interest (line)", fontsize=11)
        fig.tight_layout()
        fig.savefig(OUT / "flow_examples.png", dpi=80)
        plt.close(fig)
    print("plots written", flush=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    mode = os.environ.get("MODE", "structure")
    if mode == "flow":
        report_flow()
    elif mode == "plot":
        plot()
    else:
        d = pd.read_pickle(BASE)
        {"structure": report_structure, "smt": report_smt, "rare": report_rare, "regime": report_regime}[mode](d)


if __name__ == "__main__":
    main()
