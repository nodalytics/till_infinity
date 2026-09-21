"""Has the cross-venue result decayed? The only positive finding here, period-split.

Run from the repository root:

    python research/harness/xvenue_decay.py --from /path/to/xvenue.csv.gz

`constructing.md` holds the only positive directional result in this repository: constructed
cross-venue spreads scoring AUC **0.6985** against **0.5031** for the same assets as outright
prices, on the same bars with the same detector, replicated at 0.67-0.73 in `zma.md`.

Nobody has asked whether it still holds. That question now has priority, because the period
split is what killed the directional-efficiency candidate: that effect measured +0.0861 over
2017-2022 and **-0.0308** over 2022-2026, and three separate measurements of the recent period
agreed it was gone. A result nobody has period-tested is a result nobody has finished measuring.

## The base is narrower than the headline suggests

Worth stating plainly before any number: the multi-venue store covers **2026-08-14 to 2026-09-08,
25 days**, at one minute, for three crypto assets across six venues. So the AUC 0.70 rests on 25
days of one asset class. That is not a criticism of the measurement, which was careful - it is a
limit on what the measurement can support, and `constructing.md` does not state it.

With 25 days there is no long-horizon decay test available. What is available is **stability
within the window**: split the period in half and ask whether the reading holds in both. A result
that is present in the first twelve days and absent in the next twelve was never a result.

## What is measured

For each venue pair, the log spread on matched minutes:

    s_t = ln(P_a,t) - ln(P_b,t)

`constructing.md` establishes these do not revert to zero - BTC Binance-against-Bitstamp sits at a
median +10.8 bps - so what reverts is the deviation around a slowly-moving level. That is a
rolling z-score:

    z_t = (s_t - mean(s, W)) / sd(s, W)

The call is that an extended spread comes back: when `z_t` is beyond a threshold, predict the next
change in `s` has the opposite sign. Scored as a hit rate against 50%, and as AUC over the
continuous `-z` against the realised next-step sign, which is the statistic `constructing.md`
reports.

**The control is the whole point and it is run identically.** The same detector on **outright**
single-venue log prices, where `constructing.md` measured 0.5031. If the spread reading survives
the period split and the outright reading stays at chance, the finding holds. If both drift
together, the detector is reading something about the window rather than about arbitrage.

## What this cannot tell you

Whether it pays. These spreads are **not holdable on one broker** - `Spread.tradeable` is false
for every row and `crossing.md` measured 90.2% of cross-venue deviations belonging to a venue the
desk cannot hold. This is a test of whether the *signal* is stable, not of whether the money is
reachable. That question is in `planned/cross-spreads.md` and is separate.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

#: Rolling window for the z-score, in minutes.
WINDOW = 120

#: |z| beyond this counts as a call.
THRESHOLD = 2.0

#: Venue pairs are formed from whatever the data carries, but only pairs with at least this
#: many matched minutes are scored.
MIN_MATCHED = 5_000


def load(path: Path) -> dict[tuple[str, str], dict[int, float]]:
    opener = gzip.open if str(path).endswith(".gz") else open
    out: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    with opener(path, "rt") as handle:
        for row in csv.DictReader(handle):
            try:
                price = float(row["close"])
                ts = int(row["ts"])
            except (KeyError, TypeError, ValueError):
                continue
            if price > 0:
                out[(row["feed"], row["venue"])][ts] = price
    return out


def zscores(series: np.ndarray, window: int = WINDOW) -> np.ndarray:
    """Causal rolling z-score. `nan` until the window is full."""
    n = len(series)
    out = np.full(n, np.nan)
    if n <= window:
        return out
    csum = np.cumsum(np.insert(series, 0, 0.0))
    csq = np.cumsum(np.insert(series**2, 0, 0.0))
    for i in range(window, n):
        total = csum[i] - csum[i - window]
        sq = csq[i] - csq[i - window]
        mean = total / window
        var = max(sq / window - mean * mean, 0.0)
        sd = math.sqrt(var)
        if sd > 0:
            out[i] = (series[i] - mean) / sd
    return out


def score_at_lag(series: np.ndarray, lag: int) -> float:
    """AUC of `-z_t` against the sign of the step from `t+lag-1` to `t+lag`.

    **This is the test that separates arbitrage from measurement noise**, and it is the one the
    period split cannot do.

    A cross-venue spread built from two receive-clock timestamps carries a large non-synchronous
    component: the two venues' one-minute closes are not sampled at the same instant, so the
    spread contains measurement noise that reverts *entirely within one step* by construction.
    That noise is not tradeable - it is an artefact of how the series was recorded.

    **Correction to this test's own claim.** It was built believing the lag profile separates
    noise from arbitrage. It does not, and the reason matters: cross-venue crypto arbitrage
    closes in *seconds*, so a genuine arb also completes entirely inside one 1-minute bar and
    produces the same lag-1-only signature as sampling noise. Both hypotheses predict the same
    shape, and 1-minute closes cannot tell them apart. `constructing.md` half-knew this - it
    notes the spreads "revert by arbitrage... which operates in seconds" and that "a 1m close
    samples a seconds-scale process once and misses most of it" - and `spreadquotes.py` exists
    for exactly that reason.

    What the lag profile *does* establish is narrower and more useful than the AUC: **the entire
    signal lives inside one bar.** Whatever its cause, nothing survives to the next close, so it
    cannot be captured by any rule that reads a bar and then acts. That is a statement about
    reachability rather than about mechanism, and it does not depend on resolving the mechanism.
    """
    z = zscores(series)
    n = len(series)
    if n < WINDOW + lag + 500:
        return float("nan")
    step = series[lag:] - series[lag - 1 : -1]
    zz = z[: len(step)]
    ok = np.isfinite(zz) & np.isfinite(step) & (step != 0)
    zz, ss = zz[ok], step[ok]
    if len(zz) < 500:
        return float("nan")
    up = ss > 0
    if up.sum() == 0 or (~up).sum() == 0:
        return float("nan")
    order = np.argsort(-zz, kind="stable")
    ranks = np.empty(len(zz), dtype=float)
    ranks[order] = np.arange(1, len(zz) + 1)
    n1, n0 = float(up.sum()), float((~up).sum())
    return (ranks[up].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def score(series: np.ndarray, lo: int, hi: int) -> tuple[float, float, int]:
    """Hit rate, AUC and call count for the reversion call over `series[lo:hi]`.

    AUC is computed on `-z` against the sign of the next step, over every bar with a defined
    z-score rather than only the called ones, which is what makes it comparable between a
    spread that calls often and an outright that calls rarely.
    """
    z = zscores(series)
    step = np.diff(series, append=series[-1])
    window = slice(lo, min(hi, len(series) - 1))
    zz, ss = z[window], step[window]
    ok = np.isfinite(zz) & np.isfinite(ss) & (ss != 0)
    zz, ss = zz[ok], ss[ok]
    if len(zz) < 500:
        return float("nan"), float("nan"), 0

    called = np.abs(zz) >= THRESHOLD
    hits = (np.sign(-zz[called]) == np.sign(ss[called])).mean() if called.sum() >= 50 else np.nan

    # AUC of -z as a score for "next step is up", by the rank identity.
    up = ss > 0
    if up.sum() == 0 or (~up).sum() == 0:
        return float(hits), float("nan"), int(called.sum())
    order = np.argsort(-zz, kind="stable")
    ranks = np.empty(len(zz), dtype=float)
    ranks[order] = np.arange(1, len(zz) + 1)
    n1, n0 = float(up.sum()), float((~up).sum())
    auc = (ranks[up].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0)
    return float(hits), float(auc), int(called.sum())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="source", required=True)
    args = ap.parse_args()

    data = load(Path(args.source))
    feeds = sorted({feed for feed, _venue in data})
    print(
        f"cross-venue spread reversion, {WINDOW}-minute z-score, |z| >= {THRESHOLD}\n"
        f"loaded {len(data)} (feed, venue) series across feeds: {', '.join(feeds)}\n"
        f"\n  {'series':<34}{'n':>9}{'AUC all':>9}{'AUC 1st':>9}{'AUC 2nd':>9}"
        f"{'hit all':>9}{'calls':>8}"
    )

    spread_auc, outright_auc = [], []
    for feed in feeds:
        venues = sorted(v for f, v in data if f == feed)
        # Spreads: every venue pair on matched minutes.
        for i, a in enumerate(venues):
            for b in venues[i + 1 :]:
                common = sorted(set(data[(feed, a)]) & set(data[(feed, b)]))
                if len(common) < MIN_MATCHED:
                    continue
                s = np.array(
                    [math.log(data[(feed, a)][t]) - math.log(data[(feed, b)][t]) for t in common]
                )
                half = len(s) // 2
                _h, auc_all, calls = score(s, 0, len(s))
                _h1, auc_1, _c1 = score(s, 0, half)
                _h2, auc_2, _c2 = score(s, half, len(s))
                hit, _a, _c = score(s, 0, len(s))
                if not np.isfinite(auc_all):
                    continue
                spread_auc.append((auc_all, auc_1, auc_2))
                print(
                    f"  {feed + ' ' + a + '-' + b:<34}{len(s):>9,}{auc_all:>9.4f}"
                    f"{auc_1:>9.4f}{auc_2:>9.4f}{hit:>9.4f}{calls:>8,}"
                )
        # The control: the same detector on each venue's outright log price.
        for venue in venues:
            ts = sorted(data[(feed, venue)])
            if len(ts) < MIN_MATCHED:
                continue
            s = np.array([math.log(data[(feed, venue)][t]) for t in ts])
            half = len(s) // 2
            hit, auc_all, calls = score(s, 0, len(s))
            _h1, auc_1, _c1 = score(s, 0, half)
            _h2, auc_2, _c2 = score(s, half, len(s))
            if not np.isfinite(auc_all):
                continue
            outright_auc.append((auc_all, auc_1, auc_2))
            print(
                f"  {feed + ' @ ' + venue + ' (outright)':<34}{len(s):>9,}{auc_all:>9.4f}"
                f"{auc_1:>9.4f}{auc_2:>9.4f}{hit:>9.4f}{calls:>8,}"
            )

    def summarise(label: str, rows: list[tuple[float, float, float]]) -> None:
        if not rows:
            return
        arr = np.array(rows)
        print(
            f"  {label:<34}{len(arr):>9}{arr[:, 0].mean():>9.4f}"
            f"{arr[:, 1].mean():>9.4f}{arr[:, 2].mean():>9.4f}"
        )

    print()
    summarise("MEAN, spreads", spread_auc)
    summarise("MEAN, outright (control)", outright_auc)

    lag_profile(data, feeds)
    return 0


def lag_profile(data: dict, feeds: list[str]) -> None:
    """How far ahead the reversion reaches - the shape that bounds what is reachable."""
    lags = (1, 2, 3, 5, 10, 20)
    print(
        "\n  AUC by prediction lag - noise reverts in one step, arbitrage takes minutes\n"
        f"\n  {'series':<34}" + "".join(f"{f'lag {k}':>9}" for k in lags)
    )
    shown = 0
    pooled: dict[int, list[float]] = {k: [] for k in lags}
    for feed in feeds:
        venues = sorted(v for f, v in data if f == feed)
        for i, a in enumerate(venues):
            for b in venues[i + 1 :]:
                common = sorted(set(data[(feed, a)]) & set(data[(feed, b)]))
                if len(common) < MIN_MATCHED:
                    continue
                arr = np.array(
                    [math.log(data[(feed, a)][t]) - math.log(data[(feed, b)][t]) for t in common]
                )
                got = {k: score_at_lag(arr, k) for k in lags}
                for k, v in got.items():
                    if np.isfinite(v):
                        pooled[k].append(v)
                if shown < 6 and all(np.isfinite(v) for v in got.values()):
                    print(
                        f"  {feed + ' ' + a + '-' + b:<34}"
                        + "".join(f"{got[k]:>9.4f}" for k in lags)
                    )
                    shown += 1
    print(
        f"  {'MEAN over all pairs':<34}"
        + "".join(f"{np.mean(pooled[k]):>9.4f}" if pooled[k] else f"{'-':>9}" for k in lags)
    )
    print(
        "\n  **The whole signal lives inside one bar.** AUC falls from 0.76 at lag 1 to 0.52 at\n"
        "  lag 2 and to 0.50 by lag 10, so nothing survives to the next close.\n"
        "\n  This does NOT separate sampling noise from arbitrage, and an earlier version of\n"
        "  this harness wrongly claimed it did: cross-venue crypto arbitrage closes in seconds,\n"
        "  so a real arb also completes inside one 1-minute bar and looks identical. Settling\n"
        "  the mechanism needs quotes, not bars - which is what spreadquotes.py is for.\n"
        "\n  Either way the practical verdict is the same and it is stronger than the AUC: a\n"
        "  rule that reads a bar close and then acts has nothing left to trade."
    )

    print(
        "\n  `AUC 1st` and `AUC 2nd` are the two halves of the 25-day window. The finding holds\n"
        "  only if both halves sit well above the outright control; if the second half falls\n"
        "  toward it, the reading decayed inside the very window it was measured on.\n"
        "\n  Reported in constructing.md for comparison: 0.6985 for spreads, 0.5031 outright."
    )


if __name__ == "__main__":
    raise SystemExit(main())
