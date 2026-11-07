"""The COT positioning fade, measured against the rule frozen in
`ideas/cot_fade_rule.json`.

Runs on the lab:

    ./.secrets/lab.sh run research/harness/cotfade.py

**The sign comes from production.** `cot.direction` owns the fact that CME
currency futures are quoted as the foreign currency in dollars, so a long
JAPANESE YEN future is short USDJPY. Re-deriving it here would be a second
copy of the one thing the source module says must not be wrong, and a test
asserts the production direction rather than the table.

**Entry is the usable Wednesday's daily close.** The spec says 18:00 UTC at
the H1 open; no H1 history of this length exists on the lab, and of the two
daily anchors the close is the nearer one to 18:00. The registration records
the deviation.

**Cost is not invented.** The per-bar `spread` column on these bars is the one
this repository measured as unusable - zero on 7-35% of bars and 3-8x below
the terminal's quote - so rather than cost from it or guess, this reports the
result gross and then the round trip **in R that would erase it**. A reader
can compare that against a quoted spread themselves.
"""

from __future__ import annotations

import csv
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from till_infinity.adapters.news.sources.cot import direction  # noqa: E402

COT = Path.home() / "till_infinity" / "data" / "cot"
FX = Path.home() / "till_infinity" / "data" / "cotfx"

#: COT market -> the pair this desk trades it through.
PAIRS = {
    "eur": "EURUSD",
    "jpy": "USDJPY",
    "gbp": "GBPUSD",
    "chf": "USDCHF",
    "cad": "USDCAD",
    "aud": "AUDUSD",
    "nzd": "NZDUSD",
    "xau": "XAUUSD",
}

#: An instrument no CFTC report describes, so the same scores traded on it
#: must read nothing. The registration named a Deriv volatility index; every
#: one of those has a space in its name and `lab.sh run` passes env arguments
#: through an unquoted `$*`, which splits them. The named property - no
#: positioning report exists for it - is what the arm is for, and this has it.
PLACEBO = "BNBUSD"

THRESHOLD = float(os.environ.get("THRESHOLD", "1.5"))
CHANGE_WEEKS = int(os.environ.get("CHANGE_WEEKS", "4"))
HOLD_WEEKS = int(os.environ.get("HOLD_WEEKS", "4"))
TRAILING = int(os.environ.get("TRAILING", "156"))
LAG_DAYS = int(os.environ.get("LAG_DAYS", "8"))
ATR_N = 20
DRAWS = int(os.environ.get("DRAWS", "400"))
SPLIT = os.environ.get("SPLIT", "2020-01-01")
SEED = int(os.environ.get("SEED", "20261107"))


def load_cot(feed: str) -> tuple[np.ndarray, np.ndarray]:
    """Report dates (epoch seconds) and the net share, oldest first."""
    dates, share = [], []
    with (COT / f"{feed}.csv").open() as handle:
        for row in csv.DictReader(handle):
            dates.append(datetime.fromisoformat(row["report_date"]).timestamp())
            share.append(float(row["net_share"]))
    order = np.argsort(np.asarray(dates))
    return np.asarray(dates)[order], np.asarray(share)[order]


def load_bars(symbol: str) -> dict[str, np.ndarray]:
    with np.load(FX / f"{symbol}.1d.npz") as data:
        return {k: data[k] for k in ("time", "open", "high", "low", "close")}


def atr(bars: dict[str, np.ndarray], n: int = ATR_N) -> np.ndarray:
    """ATR(n) whose value at i uses bars strictly before i."""
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out = np.full(len(tr), np.nan)
    for i in range(n, len(tr)):
        out[i] = tr[i - n : i].mean()
    return out


def scores(
    feed: str, change_weeks: int = CHANGE_WEEKS, trailing: int = TRAILING
) -> tuple[np.ndarray, np.ndarray]:
    """Usable dates and the score at each, for one market.

    The scale window **ends at t-1**: a standard deviation including t would
    label the week with its own answer, which is the global-quantile leak
    `impulse-vol.md` records.
    """
    dates, share = load_cot(feed)
    signed = share * direction(PAIRS[feed].lower())
    change = np.full(len(signed), np.nan)
    change[change_weeks:] = signed[change_weeks:] - signed[:-change_weeks]
    score = np.full(len(signed), np.nan)
    for t in range(change_weeks + trailing, len(signed)):
        window = change[t - trailing : t]
        sd = np.nanstd(window)
        if sd > 0.0:
            score[t] = change[t] / sd
    usable = dates + LAG_DAYS * 86400.0
    return usable, score


def trades(
    feed: str,
    bars: dict[str, np.ndarray],
    usable: np.ndarray,
    score: np.ndarray,
    *,
    sides: np.ndarray | None = None,
    hold_weeks: int = HOLD_WEEKS,
    threshold: float = THRESHOLD,
    risk: np.ndarray | None = None,
) -> list[dict]:
    """One trade per firing, skipping any firing while a position is open.

    `sides` overrides the direction, which is how the sign-flip and coin arms
    keep every entry date and hold identical and change only the bet.
    """
    time, close = bars["time"], bars["close"]
    # Precomputed by the sweep, which would otherwise rebuild a 4,000-bar ATR
    # for every one of 2,400 cell-instruments.
    risk = 2.0 * atr(bars) if risk is None else risk
    hold = hold_weeks * 7 * 86400.0
    out: list[dict] = []
    free_at = -math.inf
    for t in range(len(score)):
        value = score[t]
        if not np.isfinite(value) or abs(value) < threshold:
            continue
        if usable[t] < free_at:
            continue
        i = int(np.searchsorted(time, usable[t], side="left"))
        j = int(np.searchsorted(time, usable[t] + hold, side="left"))
        if i >= len(time) or j >= len(time) or not np.isfinite(risk[i]) or risk[i] <= 0.0:
            continue
        side = -np.sign(value) if sides is None else sides[len(out) % len(sides)]
        out.append(
            {
                "entry_ts": float(time[i]),
                "r": float(side * (close[j] - close[i]) / risk[i]),
                "score": float(value),
                "side": float(side),
                "risk_px": float(risk[i]),
            }
        )
        free_at = usable[t] + hold
    return out


def unconditional(
    bars: dict[str, np.ndarray], hold_weeks: int = HOLD_WEEKS, risk: np.ndarray | None = None
) -> float:
    """What a LONG position earns, in R, averaged over every possible entry.

    The exact drift correction this study needs. `always-long` says what the
    rule's dates earned; this says what *any* dates earn at the same horizon
    and risk unit, so `r - side * unconditional` is the part of a trade that
    is not the instrument's own drift at this hold.

    A coin arm cannot do this job: a coin averages long and short and is
    mechanically near zero whatever the drift is, which is exactly what
    `sign-flip` reading +0.021 next to `always-long` reading +0.116 means.
    """
    time, close = bars["time"], bars["close"]
    risk = 2.0 * atr(bars) if risk is None else risk
    hold = hold_weeks * 7 * 86400.0
    got = []
    for i in range(len(time)):
        if not np.isfinite(risk[i]) or risk[i] <= 0.0:
            continue
        j = int(np.searchsorted(time, time[i] + hold, side="left"))
        if j >= len(time):
            break
        got.append((close[j] - close[i]) / risk[i])
    return float(np.mean(got)) if got else float("nan")


def summarise(rows: list[dict]) -> tuple[int, float, float]:
    if not rows:
        return 0, float("nan"), float("nan")
    r = np.asarray([row["r"] for row in rows])
    return len(r), float(r.mean()), float(r.std(ddof=1) / math.sqrt(len(r)))


def block_bootstrap(rows: list[dict], rng: np.random.Generator) -> tuple[float, float]:
    """A 2.5-97.5 interval, resampling blocks the length of the hold.

    The registration said whole calendar weeks; blocks of `HOLD_WEEKS` are
    used instead because that is the scale on which two trades of this rule
    can share a window, and it is the more conservative of the two.
    """
    if len(rows) < 4:
        return float("nan"), float("nan")
    order = sorted(rows, key=lambda row: row["entry_ts"])
    width = HOLD_WEEKS * 7 * 86400.0
    start = order[0]["entry_ts"]
    keyed: dict[int, list[float]] = defaultdict(list)
    for row in order:
        keyed[int((row["entry_ts"] - start) // width)].append(row["r"])
    blocks = list(keyed.values())
    # Resampled to the same number of blocks, so the interval reflects the
    # number of independent windows rather than the number of trades.
    means = []
    for _ in range(DRAWS):
        drawn = [blocks[k] for k in rng.integers(0, len(blocks), len(blocks))]
        flat = [value for block in drawn for value in block]
        if flat:
            means.append(float(np.mean(flat)))
    if not means:
        return float("nan"), float("nan")
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def main() -> int:
    rng = np.random.default_rng(SEED)
    split = datetime.fromisoformat(SPLIT).timestamp()
    print(
        f"cot-fade  threshold {THRESHOLD}  change {CHANGE_WEEKS}w  hold {HOLD_WEEKS}w  "
        f"trailing {TRAILING}w  lag {LAG_DAYS}d  draws {DRAWS}\n"
    )

    placebo_bars = load_bars(PLACEBO)
    real: dict[str, list[dict]] = {}
    arms: dict[str, list[dict]] = defaultdict(list)
    per_feed: list[dict] = []

    header = f"{'feed':5s} {'n':>4s} {'meanR':>8s} {'se':>7s} {'lo':>8s} {'hi':>8s} {'win':>6s}"
    print(header)
    print("-" * len(header))
    for feed, symbol in PAIRS.items():
        bars = load_bars(symbol)
        usable, score = scores(feed)
        rows = trades(feed, bars, usable, score)
        real[feed] = rows
        n, mean, se = summarise(rows)
        lo, hi = block_bootstrap(rows, rng)
        win = np.mean([row["r"] > 0 for row in rows]) if rows else float("nan")
        print(f"{feed:5s} {n:4d} {mean:8.3f} {se:7.3f} {lo:8.3f} {hi:8.3f} {win:6.3f}")

        drift = unconditional(bars)
        dedrifted = [row["r"] - row["side"] * drift for row in rows]
        longs = np.mean([row["side"] > 0 for row in rows]) if rows else float("nan")
        per_feed.append(
            {
                "feed": feed,
                "n": n,
                "mean": mean,
                "drift": drift,
                "dedrifted": float(np.mean(dedrifted)) if dedrifted else float("nan"),
                "long_share": float(longs),
            }
        )

        # ── the arms, each sharing this feed's entry dates and holds ──
        flipped = trades(feed, bars, usable, score, sides=rng.choice([-1.0, 1.0], max(len(rows), 1)))
        arms["sign-flip"].extend(flipped)
        arms["always-long"].extend(
            trades(feed, bars, usable, score, sides=np.ones(max(len(rows), 1)))
        )
        shuffled = score.copy()
        finite = np.isfinite(shuffled)
        shuffled[finite] = rng.permutation(shuffled[finite])
        arms["shuffled-score"].extend(trades(feed, bars, usable, shuffled))
        stale = np.full(len(score), np.nan)
        stale[8:] = score[:-8]
        arms["stale-8w"].extend(trades(feed, bars, usable, stale))
        arms["placebo-" + PLACEBO].extend(trades(feed, placebo_bars, usable, score))

    pooled = [row for rows in real.values() for row in rows]
    n, mean, se = summarise(pooled)
    lo, hi = block_bootstrap(pooled, rng)
    signs = [np.mean([row["r"] for row in rows]) > 0 for rows in real.values() if rows]
    print("-" * len(header))
    print(f"{'ALL':5s} {n:4d} {mean:8.3f} {se:7.3f} {lo:8.3f} {hi:8.3f}")
    print(f"\nsign agreement: {sum(signs)} of {len(signs)} instruments positive")

    print(f"\n{'arm':22s} {'n':>5s} {'meanR':>8s} {'se':>7s}   vs real")
    for name, rows in arms.items():
        an, amean, ase = summarise(rows)
        gap = mean - amean if np.isfinite(amean) else float("nan")
        print(f"{name:22s} {an:5d} {amean:8.3f} {ase:7.3f}   {gap:+8.3f}")

    early = [row for row in pooled if row["entry_ts"] < split]
    late = [row for row in pooled if row["entry_ts"] >= split]
    for label, rows in (("discovery  <" + SPLIT, early), ("confirm   >=" + SPLIT, late)):
        hn, hmean, hse = summarise(rows)
        hlo, hhi = block_bootstrap(rows, rng)
        print(f"\n{label}: n {hn}  meanR {hmean:.3f}  se {hse:.3f}  [{hlo:.3f}, {hhi:.3f}]")

    if pooled and np.isfinite(mean):
        # What a round trip would have to cost, in R, to erase the result. No
        # spread is invented; this is the number to compare a quote against.
        print(f"\nerased by a round trip of {mean:.3f} R (gross result, no cost applied)")
    print(
        f"\n{'feed':5s} {'n':>4s} {'meanR':>8s} {'drift':>8s} {'de-drift':>9s} {'long%':>7s}"
    )
    for row in per_feed:
        print(
            f"{row['feed']:5s} {row['n']:4d} {row['mean']:8.3f} {row['drift']:8.3f} "
            f"{row['dedrifted']:9.3f} {row['long_share']:7.3f}"
        )
    weighted = [
        row["dedrifted"] * row["n"] for row in per_feed if np.isfinite(row["dedrifted"])
    ]
    counts = [row["n"] for row in per_feed if np.isfinite(row["dedrifted"])]
    if counts:
        print(f"\nde-drifted pooled meanR: {sum(weighted) / sum(counts):+.3f}")
    positive = sum(1 for row in per_feed if row["dedrifted"] > 0)
    print(f"de-drifted sign agreement: {positive} of {len(per_feed)}")
    overall_long = np.mean([row["side"] > 0 for row in pooled])
    print(f"long share of all trades: {overall_long:.3f} (0.5 means drift cannot tilt the result)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
