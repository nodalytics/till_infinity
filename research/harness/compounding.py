"""What turning an edge of size X into a large number actually requires.

`research/compounding.md`. The owner's goal is a desk that trades on its own and
**compounds a small account into a large one**. This is not a search for edge -
other harnesses do that, and `winning.py` reads this same record looking for it.
This asks the arithmetic underneath: *given an edge of size X with this book's
shape, what risk fraction turns it into a multiple, and what kills it?*

The answer decides which edges are worth chasing and how much size any of them
may be given.

## The distribution is measured, not assumed

Every path here resamples the **live** R distribution. Nothing is drawn from a
normal, because the property that matters most for ruin - the weight of the left
tail and the thinness of the right one - is exactly what a normal throws away.
`research/exiting.md` measured an exit whose entire edge lives in a thin right
tail; §6 shows what that does to sizing, and it is not a small effect.

R is reconstructed as `(exit - entry) * side / risk` on every row rather than
read from `r_multiple`, which 118 of the 398 outcomes predate. The two agree to
5e-5 on the rows carrying both, and that check is printed rather than trusted.

## Which copy of the journal

`JOURNAL` names the database. The research machine's replica is the default and
it **lagged production by a day** when this was first run - 325 attributed
closes against 398, missing all of 2026-09-11, which is the day `sweep-aware`
went from 16 closes to 87. On a record this short that is not a rounding
difference, so the headline run reads a copy taken from the production instance
and the replica's 325-close subset is kept as a second sample. Both are reported
in `research/compounding.md`; they agree on every conclusion and disagree on the
second decimal of the mean, which is itself the most useful thing a 398-trade
sample can tell anyone.

Running it:

    ./.secrets/lab.sh run research/harness/compounding.py \
        PATHS=40000 HORIZON=1000 BOOTSTRAPS=20000 WORKERS=48

against the replica, or with `JOURNAL=` pointing at a copy of production's
`journal.db` for the current record. Nothing here needs more than a few hundred
rows of that database, and it must not be run on the instance: two cores, and
research has OOM-killed the live desk before (`research/starving.md`).

## Both populations are read

43% of one day's closes never became an `outcome`: the position outlived the
`_refs` link to its decision, so it reached the journal as an `observation`
carrying `unattributed`. The loss is **not random** - those are the trades that
lived long enough to span a deploy.

`eef4912` (2026-09-11 12:37) records the full arithmetic on a parentless close.
Before it, an unattributed row carries `profit` and nothing R can be built from.
So §2 compares the two populations on the **money** scale, which both have, and
says whether the missing half would move the answer. How many unattributed rows
carry R yet is printed, so a re-run in a week can answer it directly instead of
by proxy.

## Ruin is first passage, not the endpoint

A path that halves at trade 300 and recovers by trade 1,000 has ruined. The
account would have been stopped - by the daily halt, by the broker, or by the
owner. So the barrier is tested against the running minimum of the path, never
its final value. Scoring the endpoint instead is the most common way a
compounding study flatters itself.

## Trades are not independent, and that is modelled

The desk runs up to `max_positions` at once on instruments that share factors,
so a bad hour is several trades rather than one. Three schemes are run and all
three reported:

* **iid** - resample single trades. The optimistic bound, and the one every
  textbook ruin formula silently assumes.
* **day** - resample whole trading days, each day's trades kept in order and
  together. Preserves the clustering; costs resolution, because the record has
  only 16 distinct days in it.
* **day + halt** - the same, with the live 3% daily loss halt applied inside
  each day. This is closest to what the desk actually does, and the halt turns
  out to be a real ruin-reducer rather than a formality.

## What would count as failure

That the sample cannot support a sizing decision at all. §3's bootstrap says
whether the measured mean is distinguishable from zero, and §8 says how many
trades it would take. If the answer is "not yet, and here is the number", that
is the result, and it is printed where it cannot be skipped.
"""

from __future__ import annotations

import json
import math
import multiprocessing as mp
import os
import sqlite3
import time
from typing import Any

import numpy as np

DATA = os.environ.get("DATA", os.path.expanduser("~/till_infinity/data"))
DB = os.environ.get("JOURNAL", os.path.join(DATA, "journal.db"))
SEED = int(os.environ.get("SEED", "11"))
#: Paths per cell. At 60k the Monte Carlo standard error on a 1% ruin figure is
#: 0.04%, an order of magnitude under the bootstrap error on the edge itself.
PATHS = int(os.environ.get("PATHS", "60000"))
#: Trades per path in §5. About forty days at the observed attributed rate.
HORIZON = int(os.environ.get("HORIZON", "1000"))
BOOTSTRAPS = int(os.environ.get("BOOTSTRAPS", "20000"))
WORKERS = int(os.environ.get("WORKERS", str(min(48, os.cpu_count() or 8))))
#: Losing half the account - the owner's own phrasing, and far enough from zero
#: that this is not a study of margin calls.
BARRIER = float(os.environ.get("BARRIER", "0.5"))
#: The live `plans.standard` daily loss halt.
HALT = float(os.environ.get("HALT", "0.03"))

#: Risk fractions to score. 0.001/0.0025/0.005 are the three shipping plans.
FRACTIONS = (0.0025, 0.005, 0.01, 0.02, 0.05, 0.10, 0.15, 0.20)
#: Per-trade mean R to impose on the measured shape. 0.0 is the fair coin.
EDGES = (0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30)
#: Closes a day, attributed, over the record. Used only to turn trades into
#: calendar time in §7.
PER_DAY = float(os.environ.get("PER_DAY", "25"))


# ---------------------------------------------------------------- loading


def side_sign(row: dict[str, Any]) -> float:
    return 1.0 if str(row.get("side", "")).lower().startswith("b") else -1.0


def r_of(row: dict[str, Any]) -> float | None:
    """R from prices. `risk_price` where the row has it, `|entry - stop|` where
    it does not - the pre-2026-08-30 rows carry the prices but not always the
    derived field. `profit / risk_money` is a different quantity (it carries
    slippage, commission and swap) and is never used as R."""
    entry, exit_ = row.get("entry"), row.get("exit")
    if entry is None or exit_ is None:
        return None
    risk = row.get("risk_price") or abs(entry - (row.get("stop") or entry))
    if not risk:
        return None
    return (exit_ - entry) * side_sign(row) / risk


def load(path: str) -> tuple[list[dict], list[dict]]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    attributed, unattributed = [], []
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries "
        "WHERE actor='trading' AND kind='outcome' ORDER BY time"
    ):
        row = json.loads(ctx or "{}")
        row["_t"], row["R"] = when, r_of(row)
        attributed.append(row)
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries "
        "WHERE actor='trading' AND kind='observation' ORDER BY time"
    ):
        if "unattributed" not in (ctx or ""):
            continue
        row = json.loads(ctx or "{}")
        if "unattributed" not in row:
            continue
        row["_t"], row["R"] = when, r_of(row)
        unattributed.append(row)
    conn.close()
    return attributed, unattributed


def day_of(row: dict) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(row["_t"]))


# ---------------------------------------------------------------- statistics


def boot_mean(sample: np.ndarray, rng: np.random.Generator, draws: int) -> np.ndarray:
    return sample[rng.integers(0, len(sample), size=(draws, len(sample)))].mean(axis=1)


def ceiling_for(sample: np.ndarray) -> float:
    """The fraction at which the worst observed trade takes the whole account.

    On this book the worst close is -2.28R, so nothing at or above 0.437 of
    equity per trade survives a repeat of a trade that has already happened.
    That number is a fact about the record, not a modelling choice, and it is
    the hard ceiling every table here stops below.
    """
    worst = float(sample.min())
    return (1.0 / -worst) if worst < 0 else float("inf")


def kelly(sample: np.ndarray) -> float:
    """The f maximising E[log(1 + f R)] on the empirical distribution.

    Golden-section, which is valid because E[log] is concave in f wherever it is
    finite. Returns 0 when the sample has no edge: the growth-optimal bet on a
    losing distribution is not to bet, and a Kelly figure that goes negative is
    an instruction to take the other side, which this desk cannot do trade by
    trade.
    """
    hi = ceiling_for(sample) * 0.999
    if not math.isfinite(hi) or hi <= 0:
        return 0.0

    def g(f: float) -> float:
        v = 1.0 + f * sample
        return -np.inf if (v <= 0).any() else float(np.log(v).mean())

    if g(1e-6) <= 0.0:
        return 0.0
    phi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = 0.0, hi
    c, d = b - phi * (b - a), a + phi * (b - a)
    for _ in range(300):
        if g(c) > g(d):
            b, d = d, c
            c = b - phi * (b - a)
        else:
            a, c = c, d
            d = a + phi * (b - a)
        if b - a < 1e-8:
            break
    return (a + b) / 2.0


def growth(sample: np.ndarray, f: float) -> float:
    v = 1.0 + f * sample
    return -np.inf if (v <= 0).any() else float(np.log(v).mean())


# ---------------------------------------------------------------- simulation

_S: dict[str, Any] = {}


def _init(steps, flat, offset, length, scheme, horizon, barrier, targets):
    _S.update(steps=steps, flat=flat, offset=offset, length=length,
              scheme=scheme, horizon=horizon, barrier=barrier, targets=targets)


def _draw(rng: np.random.Generator, n: int) -> np.ndarray:
    """An (n, horizon) matrix of per-trade log growth factors."""
    horizon = _S["horizon"]
    if _S["scheme"] == "iid":
        steps = _S["steps"]
        return steps[rng.integers(0, len(steps), size=(n, horizon))]
    # Day-block: draw whole days and lay them end to end, then cut into paths.
    # A day straddles a path boundary now and then, which is the only edge this
    # loses against building each path separately - and it buys a fully
    # vectorised gather instead of a Python loop over 60,000 paths.
    flat, offset, length = _S["flat"], _S["offset"], _S["length"]
    want = n * horizon
    mean_len = max(1.0, float(length.mean()))
    draws = int(want / mean_len) + 64
    while True:
        pick = rng.integers(0, len(length), size=draws)
        lens = length[pick]
        total = int(lens.sum())
        if total >= want:
            break
        draws = int(draws * 1.3) + 64
    starts = offset[pick]
    ends = np.cumsum(lens)
    begins = ends - lens
    idx = np.repeat(starts - begins, lens) + np.arange(total)
    return flat[idx][:want].reshape(n, horizon)


def _cell(args) -> tuple:
    seed, n = args
    rng = np.random.default_rng(seed)
    step = _draw(rng, n)
    path = np.cumsum(step, axis=1, out=step)
    ruined = path.min(axis=1) <= _S["barrier"]
    finals = path[:, -1].copy()
    hits = []
    if not _S["targets"]:
        return int(ruined.sum()), finals, hits
    low = np.minimum.accumulate(path, axis=1)
    for logt in _S["targets"]:
        reached = path >= logt
        any_ = reached.any(axis=1)
        first = np.where(any_, reached.argmax(axis=1) + 1, -1)
        # Ruin counts only if it happened *before* the target was reached.
        safe = np.where(any_, low[np.arange(n), np.maximum(first - 1, 0)], low[:, -1])
        hits.append((any_.sum(), first[any_], (safe <= _S["barrier"]).sum()))
    return int(ruined.sum()), finals, hits


def simulate(sample, blocks, f, scheme="day", halt=0.0, paths=PATHS,
             horizon=HORIZON, barrier=BARRIER, targets=(), seed=SEED) -> dict:
    """Monte-Carlo one (distribution, fraction) cell.

    `blocks` are **index** arrays into `sample`, one per trading day, in the
    order that day traded them. They are indices rather than values so that
    shifting the distribution to a hypothetical edge shifts the days with it -
    getting that wrong makes every day-scheme column identical across edges,
    which is how the bug was caught.

    The halt is applied *inside* a day before the day enters the pool, so a day
    that loses 3% contributes flat steps from there on, which is what standing
    aside for the rest of a session does to an equity curve. A single trade can
    still blow through it: at f=0.20 the worst close on record takes 46% in one
    fill, and no daily rule can refuse a trade it has already taken.
    """
    if f >= ceiling_for(sample):
        return {"f": f, "ruin": 1.0, "median": 0.0, "p05": 0.0, "p95": 0.0,
                "growth": float("-inf"), "n": 0, "hits": []}
    steps = np.log1p(f * sample)
    prepared = []
    for idx in blocks:
        s = np.log1p(f * sample[idx])
        if halt > 0.0:
            run = np.cumsum(s)
            bad = np.flatnonzero(run <= math.log(1.0 - halt))
            if len(bad):
                s = s.copy()
                s[bad[0] + 1:] = 0.0
        prepared.append(s)
    flat = np.concatenate(prepared) if prepared else steps
    length = np.array([len(s) for s in prepared], dtype=np.int64)
    offset = np.concatenate([[0], np.cumsum(length)[:-1]]).astype(np.int64)

    # Chunk on *elements*, not paths: a 120,000-trade horizon at 4,000 paths
    # a chunk is 3.8GB in one worker, and 48 of those is how a 64-core machine
    # gets OOM-killed doing arithmetic that fits on a laptop.
    per = max(1, min(4000, int(4_000_000 / max(1, horizon))))
    jobs, done = [], 0
    i = 0
    while done < paths:
        n = min(per, paths - done)
        jobs.append((seed * 1_000_003 + i * 7919, n))
        done += n
        i += 1
    args = (steps, flat, offset, length, scheme, horizon,
            math.log(barrier), tuple(math.log(t) for t in targets))
    if WORKERS > 1 and len(jobs) > 1:
        with mp.Pool(WORKERS, initializer=_init, initargs=args) as pool:
            out = pool.map(_cell, jobs, chunksize=1)
    else:
        _init(*args)
        out = [_cell(j) for j in jobs]

    ruined = sum(o[0] for o in out)
    finals = np.concatenate([o[1] for o in out])
    n = len(finals)
    hits = []
    for k in range(len(targets)):
        reached = sum(o[2][k][0] for o in out)
        firsts = np.concatenate([o[2][k][1] for o in out]) if reached else np.array([])
        before = sum(o[2][k][2] for o in out)
        hits.append({
            "reached": reached / n,
            "median_trades": float(np.median(firsts)) if len(firsts) else float("nan"),
            "ruin_first": before / n,
        })
    return {
        "f": f, "ruin": ruined / n,
        "median": float(np.exp(np.median(finals))),
        "p05": float(np.exp(np.percentile(finals, 5))),
        "p95": float(np.exp(np.percentile(finals, 95))),
        "growth": float(np.median(finals) / horizon),
        "n": n, "hits": hits,
    }


# ---------------------------------------------------------------- shapes


def shift_to(sample: np.ndarray, mean: float) -> np.ndarray:
    """The measured shape moved so its mean is `mean`. Every trade improves by
    the same amount - a **broad** edge, and the most generous possible reading
    of what "an edge of X" means."""
    return sample - sample.mean() + mean


def tail_edge(sample: np.ndarray, mean: float, share: float) -> np.ndarray:
    """The same mean, carried only by the best `share` of trades.

    Every trade is first made `mean` **worse** than a zero-edge book, and the
    edge plus what was given away is handed to the top `share`. So `1 - share`
    of trades are strictly worse than having no edge at all, and the mean is
    still exactly `mean`.

    That is the shape `research/exiting.md` was left with once its two
    look-aheads were removed: the better policy is worse on **64%** of the same
    trades, its median falling from +0.498R to +0.133R while its mean rose.
    `share=0.36` is that case; the thinner shares say what a rarer tail costs.
    """
    base = sample - sample.mean() - mean
    out = base.copy()
    order = np.argsort(base)
    k = max(1, int(round(share * len(base))))
    out[order[-k:]] += 2.0 * mean / (k / len(base))
    return out


# ---------------------------------------------------------------- reporting


def rule(title: str) -> None:
    print("\n" + "=" * 88)
    print(title)
    print("=" * 88)


def main() -> None:
    rng = np.random.default_rng(SEED)
    t0 = time.time()
    print(f"journal {DB}   paths={PATHS} horizon={HORIZON} workers={WORKERS} seed={SEED}")

    attributed, unattributed = load(DB)
    rs = np.array([r["R"] for r in attributed if r["R"] is not None])
    daylists: dict[str, list[int]] = {}
    keep = [r for r in attributed if r["R"] is not None]
    for i, r in enumerate(keep):
        daylists.setdefault(day_of(r), []).append(i)
    blocks = [np.array(v, dtype=np.int64) for v in daylists.values()]

    # ---------------------------------------------------------------- 1
    rule("1. the record")
    stored = [(r["R"], r["r_multiple"]) for r in attributed
              if r.get("r_multiple") is not None and r["R"] is not None]
    drift = max(abs(a - b) for a, b in stored) if stored else float("nan")
    print(f"attributed outcomes    {len(attributed):5d}    R reconstructed on {len(rs)}")
    print(f"  stored r_multiple on {len(stored):5d}    max |reconstructed - stored| = {drift:.2e}")
    withr = sum(1 for r in unattributed if r["R"] is not None)
    print(f"unattributed closes    {len(unattributed):5d}    carrying R: {withr} "
          f"({100 * withr / max(1, len(unattributed)):.1f}%; eef4912 landed 2026-09-11 12:37)")
    print(f"span {min(daylists)} .. {max(daylists)}   {len(blocks)} trading days, "
          f"lengths {sorted(len(b) for b in blocks)}")
    print("  per-day mean R, which is what the day-block scheme resamples "
          "and the only thing it has:")
    for d in sorted(daylists):
        v = rs[np.array(daylists[d])]
        print(f"    {d}  n={len(v):3d}  mean {v.mean():+.4f}  sum {v.sum():+8.2f}")
    dm = np.array([rs[np.array(v)].mean() for v in daylists.values()])
    print(f"  {len(dm)} day means: {dm.mean():+.4f} +/- {dm.std(ddof=1):.4f}")

    # Is the day-to-day spread real, or is it what 15 groups of these sizes
    # produce from one urn? The day scheme's whole claim is that a bad day is
    # several trades rather than one, and that claim is testable. Between-group
    # sum of squares against 20,000 shuffles of R across days, day sizes held.
    sizes = np.array([len(v) for v in daylists.values()])
    grand = rs.mean()
    observed = float((sizes * (dm - grand) ** 2).sum())
    edges = np.concatenate([[0], np.cumsum(sizes)])
    null = np.empty(BOOTSTRAPS)
    for i in range(BOOTSTRAPS):
        shuffled = rs[rng.permutation(len(rs))]
        means = np.array([shuffled[edges[j]:edges[j + 1]].mean() for j in range(len(sizes))])
        null[i] = float((sizes * (means - grand) ** 2).sum())
    pval = float((null >= observed).mean())
    print(f"  clustering test: between-day SS {observed:.2f} against a shuffled null "
          f"of {null.mean():.2f} +/- {null.std(ddof=1):.2f},  p = {pval:.3f}")
    print("  " + ("days cluster: the day column in §5 is the honest one."
                  if pval < 0.05 else
                  "not separable from chance at 15 days. The day column in §5 is an "
                  "upper bound, the iid column a lower one, and the truth is between."))

    # ---------------------------------------------------------------- 2
    rule("2. does the half that went missing change the sign")
    pa = np.array([r.get("profit") or 0.0 for r in attributed], dtype=float)
    pu = np.array([r.get("profit") or 0.0 for r in unattributed], dtype=float)
    imp = np.array([abs(r["profit"] / r["R"]) for r in attributed
                    if r["R"] is not None and abs(r["R"]) > 0.2 and r.get("profit")])
    unit = float(np.median(imp))
    print(f"implied money at risk per trade: median {unit:.2f} "
          f"(p25 {np.percentile(imp, 25):.2f}, p75 {np.percentile(imp, 75):.2f}, n={len(imp)})")
    print("  the two populations, on the one scale both of them have:")
    for name, p in (("attributed", pa), ("unattributed", pu)):
        b = boot_mean(p / unit, rng, 8000)
        print(f"    {name:<13} n={len(p):4d}  total {p.sum():+9.2f}  mean {p.mean():+7.3f}"
              f"  as R {p.mean() / unit:+.3f}  [{np.percentile(b, 2.5):+.3f}, "
              f"{np.percentile(b, 97.5):+.3f}]  win {100 * (p > 0).mean():.1f}%")
    both = np.concatenate([pa, pu]) / unit
    print(f"    {'union':<13} n={len(both):4d}  total {(pa.sum() + pu.sum()):+9.2f}"
          f"  as R {both.mean():+.3f}")
    sa = np.array([r.get("seconds") or 0 for r in attributed], dtype=float)
    su = np.array([r.get("seconds") or 0 for r in unattributed], dtype=float)
    print(f"  hold median {np.median(sa):.0f}s vs {np.median(su):.0f}s;  over 1800s: "
          f"{100 * (sa > 1800).mean():.1f}% vs {100 * (su > 1800).mean():.1f}%")

    # ---------------------------------------------------------------- 3
    rule("3. the measured edge, with its interval")
    bs = boot_mean(rs, rng, BOOTSTRAPS)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    skew = float(((rs - rs.mean()) ** 3).mean() / rs.std() ** 3)
    kurt = float(((rs - rs.mean()) ** 4).mean() / rs.std() ** 4)
    print(f"n={len(rs)}  mean {rs.mean():+.4f}R  median {np.median(rs):+.4f}R  "
          f"sd {rs.std(ddof=1):.4f}  skew {skew:+.3f}  kurtosis {kurt:.2f}  "
          f"win {100 * (rs > 0).mean():.1f}%")
    print(f"bootstrap 95% CI on the mean [{lo:+.4f}, {hi:+.4f}]   "
          f"P(mean > 0) = {100 * (bs > 0).mean():.2f}%")
    print(f"worst {rs.min():+.3f}R  best {rs.max():+.3f}R  ->  no risk fraction at or "
          f"above {ceiling_for(rs):.3f} survives a repeat of the worst trade on record")
    print("percentiles  " + "  ".join(f"p{q}={np.percentile(rs, q):+.2f}"
                                      for q in (1, 5, 10, 25, 50, 75, 90, 95, 99)))
    print(f"\n  {'strategy':<18} {'n':>4} {'mean':>8} {'median':>8} {'sd':>7} {'win':>6}"
          f"  {'95% CI on mean':<22} Kelly")
    groups: dict[str, list[float]] = {}
    for r in attributed:
        if r["R"] is not None:
            groups.setdefault(r.get("strategy") or "?", []).append(r["R"])
    for name, vals in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        v = np.array(vals)
        if len(v) < 5:
            continue
        b = boot_mean(v, rng, 8000)
        ci = f"[{np.percentile(b, 2.5):+.3f}, {np.percentile(b, 97.5):+.3f}]"
        print(f"  {name:<18} {len(v):4d} {v.mean():+8.4f} {np.median(v):+8.4f} "
              f"{v.std(ddof=1):7.3f} {100 * (v > 0).mean():5.1f}%  {ci:<22} {kelly(v):.3f}")

    # ---------------------------------------------------------------- 4
    rule("4. Kelly, and how far below it a sane book sits")
    k_measured = kelly(rs)
    kb = np.array([kelly(rs[rng.integers(0, len(rs), len(rs))]) for _ in range(2000)])
    print(f"measured book: f* = {k_measured:.4f}   bootstrap median {np.median(kb):.4f}  "
          f"95% CI [{np.percentile(kb, 2.5):.4f}, {np.percentile(kb, 97.5):.4f}]")
    print(f"  f* is exactly zero in {100 * (kb <= 1e-6).mean():.1f}% of resamples, which is "
          f"the fraction of resamples with no edge to bet")
    print(f"\n  {'edge':>6} {'full Kelly':>11} {'half':>8} {'quarter':>8} {'tenth':>8}"
          f" | {'g full':>9} {'g half':>9} {'g quarter':>10} | {'ceiling':>8}")
    for mu in EDGES:
        s = shift_to(rs, mu)
        k = kelly(s)
        row = [growth(s, x * k) if k > 0 else 0.0 for x in (1.0, 0.5, 0.25)]
        print(f"  {mu:+6.2f} {k:11.4f} {k / 2:8.4f} {k / 4:8.4f} {k / 10:8.4f} | "
              f"{row[0]:9.5f} {row[1]:9.5f} {row[2]:10.5f} | {ceiling_for(s):8.3f}")

    # ---------------------------------------------------------------- 5
    rule(f"5. ruin and growth over {HORIZON} trades ({HORIZON / PER_DAY:.0f} days), "
         f"barrier = losing {100 * (1 - BARRIER):.0f}%")
    named = [("measured", rs)] + [(f"{mu:+.2f}R", shift_to(rs, mu)) for mu in EDGES]
    for label, s in named:
        k = kelly(s)
        print(f"\n  edge {label}  (mean {s.mean():+.4f}R, Kelly f* = {k:.4f})")
        print(f"  {'f':>7} {'f/K':>6} | {'iid':>8} {'day':>8} {'day+halt':>9} | "
              f"{'median x':>10} {'p5 x':>9} {'p95 x':>10} {'g/trade':>9}")
        for f in FRACTIONS:
            if f >= ceiling_for(s):
                continue
            a = simulate(s, blocks, f, "iid", 0.0, seed=SEED + 1)
            d = simulate(s, blocks, f, "day", 0.0, seed=SEED + 2)
            h = simulate(s, blocks, f, "day", HALT, seed=SEED + 3)
            ratio = f"{f / k:.2f}" if k > 0 else "-"
            print(f"  {f:7.4f} {ratio:>6} | {100 * a['ruin']:7.2f}% {100 * d['ruin']:7.2f}% "
                  f"{100 * h['ruin']:8.2f}% | {d['median']:10.3f} {d['p05']:9.4f} "
                  f"{d['p95']:10.2f} {d['growth']:+9.5f}")

    # ---------------------------------------------------------------- 6
    rule("6. the same mean, broad or in a tail")
    print("Every row in a block has the same per-trade mean R. `broad` adds it to")
    print("every trade. `tail s` takes it off every trade and gives it back only to")
    print("the best s of them, so 1-s of trades are worse than having no edge at all.")
    print("0.36 is the shape exiting.md was left with after its look-aheads came out.")
    for mu in (0.05, 0.10, 0.20):
        print(f"\n  edge {mu:+.2f}R")
        print(f"  {'shape':<10} {'sd':>6} {'median R':>9} {'win':>6} {'Kelly':>7} | "
              f"{'ruin .01':>9} {'ruin .02':>9} {'ruin .05':>9} {'ruin .10':>9} | "
              f"{'median x .02':>13} {'p5 .02':>9}")
        shapes = [("broad", shift_to(rs, mu))]
        shapes += [(f"tail {sh:.2f}", tail_edge(rs, mu, sh)) for sh in (0.36, 0.10, 0.02)]
        for name, s in shapes:
            cells = {f: simulate(s, blocks, f, "day", 0.0, seed=SEED + 5)
                     for f in (0.01, 0.02, 0.05, 0.10)}
            print(f"  {name:<10} {s.std(ddof=1):6.3f} {np.median(s):+9.3f} "
                  f"{100 * (s > 0).mean():5.1f}% {kelly(s):7.3f} | "
                  + " ".join(f"{100 * cells[f]['ruin']:8.2f}%" for f in (0.01, 0.02, 0.05, 0.10))
                  + f" | {cells[0.02]['median']:13.3f} {cells[0.02]['p05']:9.4f}")

    # ---------------------------------------------------------------- 7
    rule("7. what the goal costs, in trades and in calendar")
    print(f"First passage to a multiple, {PER_DAY:.0f} closes a day, 252 days a year.")
    print("`ruin first` is the share of paths that halved before ever touching the")
    print("target - the 5th-percentile path this study exists to make visible.")
    targets = (10.0, 100.0, 1000.0)
    print(f"\n  {'edge':>6} {'f':>7} {'f/K':>6} | " + " | ".join(
        f"{f'{t:.0f}x reach':>10} {'trades':>8} {'years':>6} {'ruin1st':>8}" for t in targets))
    for mu in (0.02, 0.05, 0.10, 0.20, 0.30):
        s = shift_to(rs, mu)
        k = kelly(s)
        for f in sorted({0.0025, round(k / 4, 4), round(k / 2, 4)}):
            if f <= 0 or f >= ceiling_for(s):
                continue
            g = growth(s, f)
            if g <= 0:
                continue
            need = int(min(60_000, max(2_000, math.ceil(2.0 * math.log(max(targets)) / g))))
            sim = simulate(s, blocks, f, "day", 0.0, horizon=need,
                           paths=max(4_000, min(PATHS, int(8_000_000 / need))),
                           targets=targets, seed=SEED + 4)
            cells = []
            for h in sim["hits"]:
                tr = h["median_trades"]
                yrs = float("nan") if math.isnan(tr) else tr / PER_DAY / 252
                cells.append(f"{100 * h['reached']:9.1f}% {tr:8.0f} {yrs:6.1f} "
                             f"{100 * h['ruin_first']:7.1f}%")
            print(f"  {mu:+6.2f} {f:7.4f} {f / k:6.2f} | " + " | ".join(cells)
                  + f"   [horizon {need}]")

    # ---------------------------------------------------------------- 8
    rule("8. how many trades before this record can decide anything")
    print("Power to reject 'mean R <= 0' at 95% one-sided, drawing from the measured")
    print("shape shifted to each edge. The shape is what makes this bite: a skewed,")
    print("fat-tailed sample needs more trades than the normal formula asks for.")
    print("A tail-shaped edge is harder to see as well as harder to size: the")
    print("variance that made it dangerous in §6 is the same variance that hides it.")
    per_day = f"days at {PER_DAY:.0f}/day"
    print(f"\n  {'edge':>6} {'shape':>10} {'sd':>6} {'normal n':>10} "
          f"{'resampled n (80% power)':>25} {per_day:>18}")
    grid = (25, 50, 75, 100, 150, 200, 300, 400, 600, 800, 1200, 1600, 2400,
            3200, 4800, 6400, 9600, 12800, 19200, 25600, 38400, 51200, 76800)
    cases = [(mu, "broad", shift_to(rs, mu))
             for mu in (0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50)]
    cases += [(mu, f"tail {sh:.2f}", tail_edge(rs, mu, sh))
              for mu in (0.05, 0.10, 0.20) for sh in (0.36, 0.10, 0.02)]
    for mu, shape, s in cases:
        sd = s.std(ddof=1)
        normal = (1.645 + 0.842) ** 2 * sd ** 2 / mu ** 2
        found = None
        for n in grid:
            trials, wins = 4000, 0
            for _ in range(trials // 200):  # chunked so a wide n cannot blow memory
                draws = s[rng.integers(0, len(s), size=(200, n))]
                m = draws.mean(axis=1)
                se = draws.std(axis=1, ddof=1) / math.sqrt(n)
                wins += int((m - 1.645 * se > 0).sum())
            if wins / trials >= 0.80:
                found = n
                break
        days = f"{found / PER_DAY:.0f}" if found else ">3072"
        print(f"  {mu:+6.2f} {shape:>10} {sd:6.3f} {normal:10.0f} "
              f"{found or '>76800'!s:>25} {days:>18}")

    # ---------------------------------------------------------------- 9
    rule("9. the table to act on")
    print("For each edge, the largest risk fraction whose probability of halving")
    print(f"over {HORIZON} trades stays inside a budget, found by bisection on the")
    print("day-block scheme, and what that fraction then buys. `to 100x` is the")
    print(f"median first passage in years at {PER_DAY:.0f} closes a day.")

    def largest_under(s, budget, halt, lo=0.0, hi=None, rounds=8):
        hi = min(hi or 0.30, ceiling_for(s) * 0.95)
        if simulate(s, blocks, hi, "day", halt, paths=12_000, seed=SEED + 6)["ruin"] <= budget:
            return hi
        for _ in range(rounds):
            mid = (lo + hi) / 2
            if simulate(s, blocks, mid, "day", halt, paths=12_000, seed=SEED + 6)["ruin"] <= budget:
                lo = mid
            else:
                hi = mid
        return lo

    for budget in (0.01, 0.05):
        print(f"\n  ruin budget: P(halve within {HORIZON} trades) <= {100 * budget:.0f}%")
        print(f"  {'edge':>9} {'Kelly':>7} | {'f (no halt)':>12} {'f/K':>6} {'g/trade':>9} "
              f"{'median x':>12} {'p5 x':>9} {'to 100x, yr':>12} | {'f (3% halt)':>12} {'f/K':>6}")
        for label, s in named:
            k = kelly(s)
            if k <= 0:
                print(f"  {label:>9} {k:7.3f} | {'none':>12} {'-':>6} {'-':>9} {'-':>12} "
                      f"{'-':>9} {'never':>12} | {'none':>12} {'-':>6}")
                continue
            f = largest_under(s, budget, 0.0)
            fh = largest_under(s, budget, HALT)
            g = growth(s, f) if f > 0 else 0.0
            cell = simulate(s, blocks, f, "day", 0.0, seed=SEED + 8) if f > 0 else None
            years = (math.log(100.0) / g / PER_DAY / 252) if g > 0 else float("inf")
            print(f"  {label:>9} {k:7.3f} | {f:12.4f} {f / k:6.2f} {g:+9.5f} "
                  f"{cell['median']:12.3f} {cell['p05']:9.4f} {years:12.2f} | "
                  f"{fh:12.4f} {fh / k:6.2f}")

    # ---------------------------------------------------------------- 10
    rule("10. the one strategy with a positive point estimate, sized")
    print("`sweep-aware` is the only strategy on the book whose mean R is above")
    print("zero. Its interval covers zero, so this is not a recommendation - it is")
    print("what the sizing question looks like when it is asked of a real")
    print("distribution rather than a shifted one, and how far the answer moves")
    print("between the point estimate and the bottom of its own interval.")
    for name in ("sweep-aware", "thesis-only"):
        rows = [r for r in attributed if r["R"] is not None and r.get("strategy") == name]
        if len(rows) < 25:
            continue
        sub = np.array([r["R"] for r in rows])
        subday: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            subday.setdefault(day_of(r), []).append(i)
        subblocks = [np.array(v, dtype=np.int64) for v in subday.values()]
        b = boot_mean(sub, rng, BOOTSTRAPS)
        lo5 = float(np.percentile(b, 5))
        print(f"\n  {name}: n={len(sub)} over {len(subblocks)} days, mean {sub.mean():+.4f}R, "
              f"sd {sub.std(ddof=1):.3f}, 5th pct of the bootstrap {lo5:+.4f}R, "
              f"Kelly on the point estimate {kelly(sub):.4f}")
        print(f"  {'f':>7} | {'iid':>8} {'day':>8} {'day+halt':>9} | {'median x':>10} "
              f"{'p5 x':>9} {'g/trade':>9}")
        for f in FRACTIONS:
            if f >= ceiling_for(sub):
                continue
            a_ = simulate(sub, subblocks, f, "iid", 0.0, seed=SEED + 9)
            d_ = simulate(sub, subblocks, f, "day", 0.0, seed=SEED + 9)
            h_ = simulate(sub, subblocks, f, "day", HALT, seed=SEED + 9)
            print(f"  {f:7.4f} | {100 * a_['ruin']:7.2f}% {100 * d_['ruin']:7.2f}% "
                  f"{100 * h_['ruin']:8.2f}% | {d_['median']:10.3f} {d_['p05']:9.4f} "
                  f"{d_['growth']:+9.5f}")
        # What the same book looks like if the truth is the bottom of the interval.
        pess = sub - sub.mean() + lo5
        print(f"  at the 5th percentile of its own mean ({lo5:+.4f}R): Kelly "
              f"{kelly(pess):.4f}, and at f=0.01 the chance of halving over "
              f"{HORIZON} trades is "
              f"{100 * simulate(pess, subblocks, 0.01, 'day', 0.0, seed=SEED + 9)['ruin']:.2f}%")

    print(f"\ndone in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    mp.set_start_method("fork", force=True)
    main()
