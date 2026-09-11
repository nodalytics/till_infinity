"""Do fat tails thin as the interval lengthens, and is the Gaussian MAD ratio right?

`research/cascading.md` §3, the weakest of the four in the sense that it is
nearly certain to be true and therefore says little on its own. It is here
because it is nearly free, and because it tests an assumption the volatility
code makes without stating.

## The two questions, and only the second can change anything

**Kurtosis of log returns by timeframe, per instrument.** The prediction is a
monotone decline from 1m to 1d. Confirming it would confirm textbook
aggregational Gaussianity and change nothing.

**The constant.** `volatility.py` chose mean absolute deviation over standard
deviation because "for fat-tailed financial returns the mean absolute deviation
answers that more stably". `MAD_TO_SIGMA` then converts between the two using
`sqrt(pi/2) = 1.25331`, **which is the Gaussian ratio** - the one value that is
certainly wrong for a fat-tailed series. The same constant appears in
`context/timing.py` as its reciprocal `sqrt(2/pi)`, converting the other way;
both are the same Gaussian assumption.

So this measures `sigma / MAD` directly, per feed and per interval, and asks
how far from 1.25331 it runs and whether it varies by timeframe. **If it varies
by timeframe the constant is right at one horizon and wrong at the others**,
which is a different and worse problem than being uniformly off - a uniform
error is absorbed by whatever thresholds were tuned against it.

## What kills each

Kurtosis: a flat or rising profile with the interval.

The constant: `sigma / MAD` sitting at 1.2533 across the board, which would say
the Gaussian ratio is fine in practice however fat the tails are. This is less
absurd than it sounds - the ratio is a **central** statistic and the fourth
moment is a **tail** one, and a distribution can have infinite kurtosis and a
near-Gaussian `sigma / MAD`.

## Controls and discipline

* **Split-sample.** 60 days by time; a feed whose direction disagrees between
  halves is counted as disagreeing.
* **A Gaussian arm**, drawn at each interval's own sample size, so that the
  reported kurtosis and ratio can be read against what this estimator returns
  when the answer is known. At `n = 56` daily bars, sample kurtosis is mostly
  noise, and the control says how much.
* **Two tail measures beside kurtosis**, because kurtosis on 56 points is not a
  measurement: the Hill tail index on the top 5% of `|r|`, and the ratio of the
  99th percentile of `|r|` to its median. Both are far better behaved in small
  samples, and if they disagree with kurtosis the disagreement is the finding.
* **`shared.strata.compare`** on the ratio, cut within interval and class.
"""

from __future__ import annotations

import math
import os
import sqlite3
import statistics as st
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.expanduser("~/till_infinity/repo"))

from till_infinity.shared.strata import compare  # noqa: E402

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("DB", os.path.join(DATA, "research.db"))
SEED = int(os.environ.get("SEED", "17"))
INTERVALS = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
MIN_N = 40
GAUSS_DRAWS = 200
#: sqrt(pi/2), as `consensus_vol.MAD_TO_SIGMA` defines it.
GAUSSIAN_RATIO = math.sqrt(math.pi / 2.0)

SYNTH = ("boom_", "crash_", "jump_", "volatility_", "step_", "range_break_")
FX = (
    "audjpy", "audusd", "cadjpy", "chfjpy", "euraud", "eurchf", "eurgbp",
    "eurjpy", "eurusd", "gbpjpy", "gbpusd", "nzdusd", "usdcad", "usdchf", "usdjpy",
)
INDEX = ("aus200", "fra40", "ger40", "hk50", "jp225", "uk100", "us100", "us30")


def klass(feed: str) -> str:
    if feed.startswith(SYNTH):
        return "synthetic"
    if feed in FX:
        return "fx"
    if feed in INDEX:
        return "index"
    if feed in ("gold", "silver"):
        return "metal"
    if feed in ("btc", "eth"):
        return "crypto"
    return "other"


def moments(r: np.ndarray) -> dict | None:
    """Everything one series of returns has to say, with the tail measured three ways."""
    r = r[np.isfinite(r)]
    if r.size < MIN_N:
        return None
    mu = float(r.mean())
    dev = r - mu
    sd = float(np.sqrt(np.mean(dev * dev)))
    mad = float(np.mean(np.abs(dev)))
    if sd <= 0 or mad <= 0:
        return None
    kurt = float(np.mean(dev ** 4) / (sd ** 4))
    mag = np.abs(dev)
    ordered = np.sort(mag)
    top = ordered[int(ordered.size * 0.95):]
    top = top[top > 0]
    # Hill on the top 5%: the slope of the log-excesses over the threshold. The
    # reciprocal is the tail index; larger `hill` is a fatter tail. Reported
    # because kurtosis on 56 daily bars is a statement about one observation.
    hill = float(np.mean(np.log(top / top[0]))) if top.size > 5 and top[0] > 0 else float("nan")
    med = float(np.median(mag))
    return {
        "n": int(r.size),
        "kurtosis": kurt,
        "excess": kurt - 3.0,
        "ratio": sd / mad,
        "hill": hill,
        "p99_over_median": float(np.quantile(mag, 0.99)) / med if med > 0 else float("nan"),
    }


def run() -> None:
    started = time.time()
    rng = np.random.default_rng(SEED)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=600.0)
    feeds = [f for (f,) in conn.execute("SELECT DISTINCT feed FROM bars ORDER BY feed")]
    span = conn.execute("SELECT MIN(ts), MAX(ts) FROM bars WHERE interval='1m'").fetchone()
    cut = (span[0] + span[1]) // 2

    got: dict[tuple[str, str], dict] = {}
    halves: dict[tuple[str, str, str], dict] = {}
    rows: list[dict] = []
    sizes: dict[str, list[int]] = defaultdict(list)

    for feed in feeds:
        for interval in INTERVALS:
            raw = conn.execute(
                "SELECT ts, close FROM bars WHERE feed=? AND interval=? ORDER BY ts",
                (feed, interval),
            ).fetchall()
            if len(raw) < MIN_N + 2:
                continue
            ts = np.array([r[0] for r in raw], dtype=np.int64)
            close = np.array([float(r[1]) for r in raw], dtype=float)
            keep = close > 0
            ts, close = ts[keep], close[keep]
            if ts.size < MIN_N + 2:
                continue
            # Only between adjacent bars of this interval: a return spanning a
            # weekend is the fattest observation in every FX series and it is
            # not a market move. Dropping it is the conservative direction -
            # it can only make tails look thinner.
            step = np.diff(ts) == SECONDS[interval] * 1000
            r = np.log(close[1:] / close[:-1])[step]
            rts = ts[1:][step]
            made = moments(r)
            if made is None:
                continue
            got[(feed, interval)] = made
            sizes[interval].append(made["n"])
            for name, mask in (("first", rts < cut), ("second", rts >= cut)):
                part = moments(r[mask])
                if part:
                    halves[(feed, interval, name)] = part
            rows.append({
                "ratio": made["ratio"], "kurtosis": made["kurtosis"],
                "excess": made["excess"], "hill": made["hill"],
                "interval": interval, "klass": klass(feed), "feed": feed,
                "fast": "1m-15m" if SECONDS[interval] <= 900 else "30m-1d",
            })

    # The Gaussian arm, at each interval's own median sample size.
    control: dict[str, dict[str, tuple[float, float]]] = {}
    for interval in INTERVALS:
        if not sizes[interval]:
            continue
        n = int(st.median(sizes[interval]))
        ks, rs = [], []
        for _ in range(GAUSS_DRAWS):
            made = moments(rng.normal(size=n))
            if made:
                ks.append(made["kurtosis"])
                rs.append(made["ratio"])
        if ks:
            control[interval] = {
                "n": (float(n), 0.0),
                "kurtosis": (st.fmean(ks), st.stdev(ks)),
                "ratio": (st.fmean(rs), st.stdev(rs)),
            }

    print("=" * 100)
    print("THREE: how tails and the MAD ratio move with the interval. Gaussian control at matched n.")
    print("=" * 100)
    print(f"  {'interval':>9s} {'feeds':>6s} {'median n':>9s} {'kurtosis':>10s} {'excess':>9s} "
          f"{'hill':>8s} {'p99/med':>9s} {'sigma/MAD':>10s} | {'gauss kurt':>11s} {'gauss sd':>9s} "
          f"{'gauss ratio':>12s}")
    for interval in INTERVALS:
        part = [v for (f, i), v in got.items() if i == interval]
        if not part:
            continue
        ctl = control.get(interval, {})
        print(
            f"  {interval:>9s} {len(part):6d} {int(st.median(p['n'] for p in part)):9,d} "
            f"{st.median(p['kurtosis'] for p in part):10.3f} "
            f"{st.median(p['excess'] for p in part):9.3f} "
            f"{st.median(p['hill'] for p in part if math.isfinite(p['hill'])):8.4f} "
            f"{st.median(p['p99_over_median'] for p in part):9.3f} "
            f"{st.median(p['ratio'] for p in part):10.5f} | "
            f"{ctl.get('kurtosis', (float('nan'),))[0]:11.3f} "
            f"{ctl.get('kurtosis', (0, float('nan')))[1]:9.3f} "
            f"{ctl.get('ratio', (float('nan'),))[0]:12.5f}"
        )
    print(f"\n  medians across feeds. The Gaussian ratio the code uses is {GAUSSIAN_RATIO:.5f}.")

    print("\nIs the decline monotone, per feed? (1m .. 1d, only feeds carrying every interval)")
    full = [f for f in feeds if all((f, i) in got for i in INTERVALS)]
    for name, key in (("kurtosis", "kurtosis"), ("hill", "hill"), ("p99/median", "p99_over_median")):
        strict = weak = 0
        for f in full:
            seq = [got[(f, i)][key] for i in INTERVALS]
            if any(not math.isfinite(v) for v in seq):
                continue
            weak += 1
            if all(seq[i] >= seq[i + 1] for i in range(len(seq) - 1)):
                strict += 1
        print(f"  {name:>12s}: {strict}/{weak} feeds decline at every step")
    # And the weaker, fairer statement: does it fall from the fastest to the slowest.
    for name, key in (("kurtosis", "kurtosis"), ("hill", "hill"), ("p99/median", "p99_over_median")):
        down = tot = 0
        for f in full:
            a, b = got[(f, "1m")][key], got[(f, "1d")][key]
            if math.isfinite(a) and math.isfinite(b):
                tot += 1
                down += 1 if b < a else 0
        print(f"  {name:>12s}: {down}/{tot} feeds are thinner at 1d than at 1m")

    print("\nby class, sigma / MAD:")
    print("  " + f"{'class':>10s}" + "".join(f"{i:>10s}" for i in INTERVALS))
    for name in sorted({klass(f) for f in feeds}):
        line = f"  {name:>10s}"
        for interval in INTERVALS:
            part = [v["ratio"] for (f, i), v in got.items() if i == interval and klass(f) == name]
            line += f"{(st.median(part) if part else float('nan')):10.5f}"
        print(line)

    print("\nby class, kurtosis:")
    print("  " + f"{'class':>10s}" + "".join(f"{i:>10s}" for i in INTERVALS))
    for name in sorted({klass(f) for f in feeds}):
        line = f"  {name:>10s}"
        for interval in INTERVALS:
            part = [v["kurtosis"] for (f, i), v in got.items() if i == interval and klass(f) == name]
            line += f"{(st.median(part) if part else float('nan')):10.3f}"
        print(line)

    print("\nsplit sample - does the ratio hold between the two halves of the 60 days?")
    print(f"  {'interval':>9s} {'feeds':>6s} {'first':>9s} {'second':>9s} {'|gap|':>8s} "
          f"{'max |gap|':>10s}")
    for interval in INTERVALS:
        pairs = [
            (halves[(f, interval, 'first')]["ratio"], halves[(f, interval, 'second')]["ratio"])
            for f in feeds
            if (f, interval, "first") in halves and (f, interval, "second") in halves
        ]
        if len(pairs) < 3:
            continue
        gaps = [abs(a - b) for a, b in pairs]
        print(f"  {interval:>9s} {len(pairs):6d} {st.median(a for a, _ in pairs):9.5f} "
              f"{st.median(b for _, b in pairs):9.5f} {st.median(gaps):8.5f} {max(gaps):10.5f}")

    print("\nthe ten furthest from the Gaussian ratio, at 5m:")
    at5 = sorted(
        ((abs(v["ratio"] - GAUSSIAN_RATIO), f, v) for (f, i), v in got.items() if i == "5m"),
        reverse=True,
    )[:10]
    for _, f, v in at5:
        print(f"  {f:>24s} {klass(f):>10s} ratio {v['ratio']:.5f} "
              f"({(v['ratio'] / GAUSSIAN_RATIO - 1) * 100:+.1f}% on the constant)  "
              f"kurtosis {v['kurtosis']:9.2f}")

    if rows:
        print("\n" + "=" * 100)
        print("Conditioned: sigma / MAD for the fast intervals against the slow, within class")
        print("=" * 100)
        print(compare(rows, value="ratio", bucket="fast", within=("interval", "klass"),
                      min_n=20).render())

    print(f"\n{time.time() - started:.0f}s")


if __name__ == "__main__":
    run()
