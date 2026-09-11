"""Is a synthetic's realised volatility the number in its name?

Deriv names each Volatility index for its annualised volatility:
`Volatility 75 Index` claims 75%. That is a *published parameter of a generator*
rather than an opinion about a market, so it is either true in our data or it
is not, and the answer is worth more than most things measured here:

* If realised == nominal, the denominator every threshold in this project is
  quoted in (`resolve_vol`, `MIN_ZONE_VOL`, `KEEP_VOL`) is **known a priori** on
  72% of the book, and estimating it is estimating a constant.
* `research/volatility.md` found a flat 20-bar mean matches the EWMA estimator
  almost everywhere. If a synthetic has no conditional heteroskedasticity at
  all, that is *why* - both are estimating something that does not move, and
  the published constant beats them both by having no estimation error.
* And if realised persistently differs from nominal, that gap is itself the
  finding: the generator is not the one on the tin.

## What would count as failure, written before running

1. **The premise dies** if realised/nominal is unstable - if the ratio moves by
   more than a few percent between the first and second thirty days, or does not
   order with the name.
2. **The constant-vol claim dies** if the synthetics show |return| autocorrelation
   comparable to the real controls. Vol clustering means vol moves, and a
   constant cannot track it.
3. **The whole run is void** if a statistic lands on *exactly* its null - an
   autocorrelation of 0.0000 or a variance ratio of exactly 1.0 is a dead
   column, not a null result (`research/README.md`).

## The controls

* **Real instruments** (gold, eurusd, btc, us100, usdjpy, silver) measured the
  same way. They must show vol clustering; if they do not, the measurement is
  broken and nothing about the synthetics can be read.
* **A phase-shuffle of each series' own returns**, which destroys every
  dependence and keeps the marginal distribution. Any autocorrelation or
  variance ratio is read against what the shuffle produces on the same data.
* **Split sample**: first 30 days propose, last 30 days dispose. Every headline
  number is reported in both halves and only believed if it survives.
"""

from __future__ import annotations

import json
import math
import os
import random
import sqlite3
import statistics as st
from collections import defaultdict

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
INTERVAL = os.environ.get("INTERVAL", "1m")
OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/genvol.json"))

#: Minutes in a 365-day year. The synthetics run 24/7/365 - there is no session
#: and no weekend - so this is the annualisation factor and not an approximation
#: of one. The real controls do *not* trade 24/7, which is why their annualised
#: numbers below are marked as not comparable to a name.
MINUTES_PER_YEAR = 365 * 24 * 60

#: Nominal annualised volatility, in percent, as published in the instrument's
#: own name. `None` means the family's name encodes something else (a spike
#: rate, a step size) and there is no vol claim to test.
NOMINAL = {
    "volatility_10_index": 10.0,
    "volatility_25_index": 25.0,
    "volatility_50_index": 50.0,
    "volatility_75_index": 75.0,
    "volatility_100_index": 100.0,
    "volatility_10_1s_index": 10.0,
    "volatility_25_1s_index": 25.0,
    "volatility_50_1s_index": 50.0,
    "volatility_75_1s_index": 75.0,
    "volatility_100_1s_index": 100.0,
    "volatility_150_1s_index": 150.0,
    "volatility_200_1s_index": 200.0,
    "volatility_250_1s_index": 250.0,
}

OTHER_SYNTH = [
    "boom_300_index", "boom_500_index", "boom_1000_index",
    "crash_300_index", "crash_500_index", "crash_1000_index",
    "jump_10_index", "jump_25_index", "jump_50_index",
    "jump_75_index", "jump_100_index",
    "step_index", "range_break_100_index", "range_break_200_index",
]

#: The positive control. These are real markets and must show volatility
#: clustering; a run where they do not is a broken measurement.
REAL = ["gold", "eurusd", "btc", "us100", "usdjpy", "silver"]

LAGS = (1, 2, 3, 5, 10, 20, 60)
VR_Q = (2, 5, 10, 30, 60)


def bars(conn, feed: str) -> list[tuple[int, float, float, float, float]]:
    rows = conn.execute(
        "SELECT ts, open, high, low, close FROM bars WHERE feed=? AND interval=? ORDER BY ts ASC",
        (feed, INTERVAL),
    ).fetchall()
    return [
        (int(ts), float(o), float(h), float(lo), float(c))
        for ts, o, h, lo, c in rows
        if None not in (o, h, lo, c) and o > 0 and h > 0 and lo > 0 and c > 0
    ]


def logrets(rows) -> list[float]:
    """Log returns between *consecutive* bars only.

    A gap in the series - and the real feeds have weekends - is skipped rather
    than treated as a one-minute move. One weekend return logged as a minute
    would dominate the variance of a whole instrument.
    """
    out = []
    for (t0, _, _, _, c0), (t1, _, _, _, c1) in zip(rows, rows[1:], strict=False):
        if t1 - t0 == 60_000:
            out.append(math.log(c1 / c0))
    return out


def ann_vol(rets: list[float]) -> float:
    if len(rets) < 100:
        return float("nan")
    return st.pstdev(rets) * math.sqrt(MINUTES_PER_YEAR) * 100.0


def parkinson(rows) -> float:
    """High-low range estimator. On a GBM sampled continuously it equals the
    close-to-close figure; below it means the bar's extremes are not being
    resolved - which is what a bar built from two-second ticks would do."""
    vals = [math.log(h / lo) ** 2 for _, _, h, lo, _ in rows if h > lo]
    if len(vals) < 100:
        return float("nan")
    return math.sqrt(st.fmean(vals) / (4 * math.log(2))) * math.sqrt(MINUTES_PER_YEAR) * 100.0


def acf(xs: list[float], lag: int) -> float:
    n = len(xs)
    if n <= lag + 10:
        return float("nan")
    m = st.fmean(xs)
    num = sum((xs[i] - m) * (xs[i + lag] - m) for i in range(n - lag))
    den = sum((x - m) ** 2 for x in xs)
    return num / den if den else float("nan")


def variance_ratio(rets: list[float], q: int) -> float:
    """Var of q-period returns over q times var of one-period returns.

    1.0 is a martingale. Below 1 is mean reversion, above 1 is trending. This
    is the test that decides whether anything here is tradable at all: a
    generator that is a martingale at every horizon cannot be traded
    directionally, whatever else is true about it.
    """
    n = len(rets)
    if n < q * 50:
        return float("nan")
    v1 = st.pvariance(rets)
    agg = [sum(rets[i : i + q]) for i in range(0, n - q + 1, q)]
    if len(agg) < 30 or v1 == 0:
        return float("nan")
    return st.pvariance(agg) / (q * v1)


def kurtosis(xs: list[float]) -> float:
    if len(xs) < 100:
        return float("nan")
    m = st.fmean(xs)
    s = st.pstdev(xs)
    if s == 0:
        return float("nan")
    return st.fmean([((x - m) / s) ** 4 for x in xs])


def forecast_scores(rets: list[float], nominal: float | None) -> dict:
    """Walk-forward: predict |r_t| from information before t.

    Three forecasts - the published constant, a flat 20-bar mean of |r|, and an
    EWMA with the half-life `volatility.md` found optimal. Scored by calibration
    ratio and by mean absolute error, *not* only by correlation: a constant has
    zero correlation by construction and reading that as a loss would be the
    dead-column error in reverse.
    """
    n = len(rets)
    if n < 2000:
        return {}
    absr = [abs(r) for r in rets]
    # The constant a published vol implies for E|r| on one minute: for a normal
    # variate, E|r| = sigma * sqrt(2/pi).
    const = None
    if nominal is not None:
        sigma_1m = (nominal / 100.0) / math.sqrt(MINUTES_PER_YEAR)
        const = sigma_1m * math.sqrt(2.0 / math.pi)

    alpha = 1 - 0.5 ** (1 / 7)  # half-life 7 bars
    ewma = st.fmean(absr[:20])
    flat: list[float] = []
    out = {k: {"err": 0.0, "sum_f": 0.0, "sum_a": 0.0, "n": 0, "fs": [], "as": []} for k in ("const", "flat20", "ewma")}
    for i in range(20, n):
        window = absr[i - 20 : i]
        f_flat = st.fmean(window)
        f_ewma = ewma
        a = absr[i]
        for name, f in (("const", const), ("flat20", f_flat), ("ewma", f_ewma)):
            if f is None:
                continue
            r = out[name]
            r["err"] += abs(f - a)
            r["sum_f"] += f
            r["sum_a"] += a
            r["n"] += 1
            r["fs"].append(f)
            r["as"].append(a)
        ewma = (1 - alpha) * ewma + alpha * a
    scored = {}
    for name, r in out.items():
        if not r["n"]:
            continue
        fs, ays = r["fs"], r["as"]
        sf, sa = st.pstdev(fs), st.pstdev(ays)
        if sf == 0 or sa == 0:
            corr = None  # a constant forecast: correlation is undefined, not zero
        else:
            mf, ma = st.fmean(fs), st.fmean(ays)
            corr = st.fmean([(f - mf) * (a - ma) for f, a in zip(fs, ays, strict=False)]) / (sf * sa)
        scored[name] = {
            "mae": r["err"] / r["n"],
            "ratio": (r["sum_f"] / r["sum_a"]) if r["sum_a"] else None,
            "corr": corr,
            "n": r["n"],
        }
    return scored


def measure(feed: str, rows, rets: list[float], nominal: float | None, shuffled=False) -> dict:
    got = {
        "feed": feed,
        "bars": len(rows),
        "rets": len(rets),
        "ann_vol": ann_vol(rets),
        "parkinson": parkinson(rows) if not shuffled else None,
        "nominal": nominal,
        "kurtosis": kurtosis(rets),
        "acf_abs": {lag: acf([abs(r) for r in rets], lag) for lag in LAGS},
        "acf_ret": {lag: acf(rets, lag) for lag in LAGS},
        "vr": {q: variance_ratio(rets, q) for q in VR_Q},
    }
    if got["nominal"] and not math.isnan(got["ann_vol"]):
        got["ratio_to_name"] = got["ann_vol"] / got["nominal"]
    return got


def main() -> None:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    feeds = list(NOMINAL) + OTHER_SYNTH + REAL
    results = []
    for feed in feeds:
        rows = bars(conn, feed)
        if len(rows) < 5000:
            print(f"{feed}: only {len(rows)} bars, skipped")
            continue
        half = len(rows) // 2
        parts = {"all": rows, "first30": rows[:half], "last30": rows[half:]}
        entry = {"feed": feed, "real": feed in REAL, "parts": {}}
        for name, part in parts.items():
            rets = logrets(part)
            entry["parts"][name] = measure(feed, part, rets, NOMINAL.get(feed))
        rets_all = logrets(rows)
        # The shuffle control: same marginal distribution, no dependence.
        rnd = random.Random(20260911)
        shuf = rets_all[:]
        rnd.shuffle(shuf)
        entry["shuffled"] = measure(feed, rows, shuf, NOMINAL.get(feed), shuffled=True)
        entry["forecast"] = {
            "first30": forecast_scores(logrets(parts["first30"]), NOMINAL.get(feed)),
            "last30": forecast_scores(logrets(parts["last30"]), NOMINAL.get(feed)),
        }
        results.append(entry)
        a = entry["parts"]["all"]
        print(
            f"{feed:26s} bars={a['bars']:7d} ann={a['ann_vol']:8.2f} "
            f"nom={a['nominal']} ratio={a.get('ratio_to_name')} "
            f"kurt={a['kurtosis']:.2f} acf|r|1={a['acf_abs'][1]:+.4f} "
            f"(shuf {entry['shuffled']['acf_abs'][1]:+.4f}) vr10={a['vr'][10]:.4f}",
            flush=True,
        )

    with open(OUT, "w") as fh:
        json.dump(results, fh, indent=1, default=str)
    print(f"\nwrote {OUT}")

    print("\n=== realised vs nominal annualised volatility (percent) ===")
    print(f"{'feed':26s} {'nom':>6s} {'all':>8s} {'first30':>8s} {'last30':>8s} {'ratio':>7s} {'park':>8s} {'p/cc':>6s}")
    for e in results:
        a, f, l = e["parts"]["all"], e["parts"]["first30"], e["parts"]["last30"]
        nom = a["nominal"]
        pk = a["parkinson"]
        nom_s = "-" if nom is None else f"{nom:.0f}"
        ratio_s = "-" if nom is None else f"{a['ann_vol'] / nom:.4f}"
        pcc = pk / a["ann_vol"] if a["ann_vol"] else float("nan")
        print(
            f"{e['feed']:26s} {nom_s:>6s} "
            f"{a['ann_vol']:8.2f} {f['ann_vol']:8.2f} {l['ann_vol']:8.2f} "
            f"{ratio_s:>7s} {pk:8.2f} {pcc:6.3f}"
        )

    print("\n=== volatility clustering: acf of |1m return|, real vs shuffled ===")
    print(f"{'feed':26s} " + " ".join(f"L{l:<6d}" for l in LAGS) + "  | shuffled L1  L5")
    for e in results:
        a, s = e["parts"]["all"], e["shuffled"]
        mark = "REAL " if e["real"] else "     "
        print(
            f"{mark}{e['feed']:21s} "
            + " ".join(f"{a['acf_abs'][l]:+.4f}" for l in LAGS)
            + f"  | {s['acf_abs'][1]:+.4f} {s['acf_abs'][5]:+.4f}"
        )

    print("\n=== variance ratios (1.0 = martingale) ===")
    print(f"{'feed':26s} " + " ".join(f"q={q:<6d}" for q in VR_Q) + " | shuffled q=10")
    for e in results:
        a, s = e["parts"]["all"], e["shuffled"]
        mark = "REAL " if e["real"] else "     "
        print(
            f"{mark}{e['feed']:21s} "
            + " ".join(f"{a['vr'][q]:.4f} " for q in VR_Q)
            + f"| {s['vr'][10]:.4f}"
        )

    print("\n=== forecasting |next 1m return|: published constant vs flat-20 vs ewma(h=7) ===")
    print(f"{'feed':26s} {'half':8s} {'model':7s} {'mae':>10s} {'ratio':>7s} {'corr':>8s}")
    for e in results:
        for half in ("first30", "last30"):
            for name, sc in e["forecast"][half].items():
                c = sc["corr"]
                corr_s = "   const" if c is None else f"{c:8.4f}"
                ratio = sc["ratio"] if sc["ratio"] is not None else float("nan")
                print(
                    f"{e['feed']:26s} {half:8s} {name:7s} {sc['mae']:10.3e} "
                    f"{ratio:7.4f} {corr_s}"
                )


if __name__ == "__main__":
    main()
