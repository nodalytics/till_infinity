"""The zero-skill null for the desk's weighting loops: would they look the same if nothing had skill?

Production has online loops that turn their own outcomes into weights, rankings or permissions. A
loop that prefers one arm on noise is acting on nothing, and the display it prints (a best arm at
"+0.3R", a feed "right 55% of 400 calls") reads exactly like skill. This drives the **production
code itself** with streams where nothing has skill and measures what the loops then show and do.

The loops (update rule, decay, what it feeds, threshold):

  policy    `trading.strategies.policy.Policy` over `Ledger`: an EWMA of each shape's clipped R
            (decay 0.05, half-life ~14), per context (family|interval, family, book), backing off.
            It picks the arm with the highest mean among arms seen >= 30 times - no margin over the
            fallback. It feeds `opportunity`'s exit geometry: target, trail, hold.
  entries   `policy.Entries`: the same ledger, per family and strategy. Recording only; nothing
            reads it.
  zma gate  `structures.zma.Zma` edge record: cumulative, undecayed calls and right. A feed is
            "earned" at >= 200 calls and right > 52% (`TRADING_ZMA_GATE`, on by default, and
            `cycle-turn` / `turning`'s permission). It feeds a veto (cycle-scalp) and a permission
            to trade (cycle-turn, turning).
  cycles    `structures.cycles` depth head: an online regression, `depth_skill` > 0.05 after 200
            settled turns lets the cap shrink a push (`STRUCTURES_CYCLES_ACT`, off by default).

Not covered, and why:
  - the volatility ensemble's member weights: a weighting of estimators, not an arm with a skill;
  - the break model's calibration: it gates nothing in trading;
  - the retrain gates: already judged against day-bootstrap standard errors (models/retrain.py).

Zero-skill streams:
  (a) iid    rewards drawn with replacement from the journal's own resolved rewards, independent
             of arm and context;
  (b) perm   the journal's real reward stream with its rewards permuted across rows (arm and context
             kept, the link to the reward broken);
  (c) walks  for the loops that read prices: iid Student-t(3) walks and GARCH(1,1) walks, both
             generated here. Deriv is a market (it is in the journal stream like any other family),
             never a control.

Horizons: the desk's actual volume per day (from the journal) for 30, 90 and 180 days, many seeds.

Pre-registered: a loop is **safe** if, under the null, it takes its action (departs from the
default, vetoes, grants permission) on at most **5%** of the occasions it would act on, counted
across every feed or context it covers at once, since the desk runs them all at once. Where it is
not, the threshold that brings it to 5% is reported.

Run on the lab:
  JOURNAL=$HOME/till_infinity/data/journal.db python research/harness/zeroskill.py
  PART=policy | zma | cycles | all (default)
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from statistics import NormalDist

import numpy as np

from till_infinity.structures import zma as zm
from till_infinity.trading.strategies import policy as pol
from till_infinity.trading.strategies.opportunity import PRESETS

JOURNAL = os.path.expanduser(os.environ.get("JOURNAL", "~/till_infinity/data/journal.db"))
PART = os.environ.get("PART", "all")
SEEDS = int(os.environ.get("SEEDS", "200"))
HORIZONS = (30, 90, 180)
FALSE_ACTION = 0.05


def say(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------------------------ the journal


def stream():
    """The policy's real credit stream: every resolved untaken intent with a reward, in time order,
    as (time, feed, interval, strategy, arm, reward). Plus the desk's closed trades' R."""
    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=300.0)
    rows, closed, picks = [], [], []
    for t, kind, ctx in conn.execute(
        "SELECT time, kind, context FROM entries WHERE actor='trading' AND kind IN "
        "('observation','outcome','decision') ORDER BY time"
    ):
        c = json.loads(ctx)
        if kind == "observation" and isinstance(c.get("reward"), int | float) and c.get("untaken"):
            by = str(c.get("strategy") or c.get("taken_by") or "")
            shape = PRESETS.get(by)
            arm = shape.named() if shape is not None else str(c.get("arm") or "")
            rows.append((t, str(c.get("feed") or ""), str(c.get("interval") or ""), by, arm,
                         float(c["reward"])))
        elif kind == "outcome" and isinstance(c.get("r_multiple"), int | float):
            closed.append(float(c["r_multiple"]))
        elif kind == "decision" and c.get("arm_reason"):
            picks.append((t, str(c.get("feed") or ""), str(c.get("arm_reason"))))
    return rows, closed, picks


# ------------------------------------------------------------------------------------ the policy


def drive(rows, rewards):
    """Production Policy and Entries fed `rows` with `rewards`; what they then show."""
    policy, entries = pol.Policy(), pol.Entries()
    for (_, feed, interval, by, arm, _), r in zip(rows, rewards, strict=True):
        if arm:
            policy.observe(feed, interval, arm, r)
        entries.observe(feed, by, r)
    fallback = policy.fallback.named()
    out = {"departs": 0, "contexts": 0, "best": [], "gap": [], "vs_fallback": [], "lead": []}
    contexts = {ctx for (ctx, _arm) in policy.ledger.cells}
    for ctx in contexts:
        warm = {a: s for a, s in policy.ledger.arms(ctx).items() if s.seen >= policy.MIN_SEEN
                and a in policy.arms}
        if not warm:
            continue
        out["contexts"] += 1
        best_arm, best = max(warm.items(), key=lambda kv: kv[1].mean)
        out["departs"] += best_arm != fallback
        out["best"].append(best.mean)
        if len(warm) >= 2:
            out["gap"].append(best.mean - min(s.mean for s in warm.values()))
        if fallback in warm and best_arm != fallback:
            out["vs_fallback"].append(best.mean - warm[fallback].mean)
        others = [s.mean for a, s in warm.items() if a != best_arm]
        if others:
            # The winner's lead over the rest: the margin a rule would need before departing.
            out.setdefault("lead", []).append(best.mean - float(np.mean(others)))
    ranks = []
    for fam in {f for (f, _a) in entries.ledger.cells}:
        ranked = [(n, s) for (f, n), s in entries.ledger.cells.items() if f == fam and s.seen >= 30]
        if len(ranked) >= 2:
            means = [s.mean for _, s in ranked]
            ranks.append(max(means) - min(means))
    out["entries_gap"] = ranks
    return out


def tile(rows, days, rng):
    """`days` of rows at the stream's real daily volume, resampled whole days from the stream."""
    by_day = defaultdict(list)
    for r in rows:
        by_day[int(r[0] // 86_400)].append(r)
    keys = sorted(by_day)
    out, t = [], 0.0
    for d in range(days):
        for r in by_day[keys[rng.integers(len(keys))]]:
            out.append((t + d * 86_400 + (r[0] % 86_400),) + r[1:])
    return out


def pct(values, q):
    return float(np.percentile(values, q)) if len(values) else float("nan")


def policy_part(rows, closed, picks):
    rng = np.random.default_rng(0)
    real = np.array([r[5] for r in rows])
    days = max(1, (rows[-1][0] - rows[0][0]) / 86_400) if rows else 1
    arms = Counter(r[4] for r in rows if r[4])
    say(f"POLICY: {len(rows):,} resolved untaken rewards over {days:.1f} days "
        f"({len(rows) / days:.0f} a day), {len(arms)} arms credited, {len(closed)} closed trades")
    clipped = np.clip(real, *pol.CLIP)
    say(f"  reward (clipped): mean {clipped.mean():+.3f}R sd {clipped.std():.3f} "
        f"median {np.median(clipped):+.3f} | closed trades mean {np.mean(closed):+.3f}R" if closed else "")
    say("  arms: " + ", ".join(f"{a.split('/')[1]}..:{n}" for a, n in arms.most_common()))

    got = drive(rows, list(real))
    say(f"\n  REAL stream ({days:.0f} days): {got['contexts']} warm contexts, departs from the "
        f"fallback in {got['departs']}; best arm's mean median {pct(got['best'], 50):+.3f}R "
        f"(max {max(got['best'], default=float('nan')):+.3f}); top-bottom gap median "
        f"{pct(got['gap'], 50):.3f}R; entries gap median {pct(got['entries_gap'], 50):.3f}R")

    for label, horizon in [("real length", None)] + [(f"{d} days", d) for d in HORIZONS]:
        stats = defaultdict(list)
        for s in range(SEEDS):
            r = np.random.default_rng(1000 + s)
            base = rows if horizon is None else tile(rows, horizon, r)
            rew = np.array([x[5] for x in base])
            for null, values in (("perm", r.permutation(rew)), ("iid", r.choice(real, len(rew)))):
                g = drive(base, list(values))
                stats[f"{null} depart"].append(g["departs"] / max(g["contexts"], 1))
                stats[f"{null} contexts"].append(g["contexts"])
                stats[f"{null} best"].extend(g["best"])
                stats[f"{null} maxbest"].append(max(g["best"], default=np.nan))
                stats[f"{null} gap"].extend(g["gap"])
                stats[f"{null} vsfb"].extend(g["vs_fallback"])
                stats[f"{null} lead"].extend(g["lead"])
                stats[f"{null} egap"].extend(g["entries_gap"])
        for null in ("perm", "iid"):
            say(f"\n  NULL {null}, {label} ({SEEDS} seeds): warm contexts {np.mean(stats[null + ' contexts']):.1f}"
                f" | departs from fallback in {np.mean(stats[null + ' depart']):.0%} of them"
                f" | best arm's mean p50/p95 {pct(stats[null + ' best'], 50):+.3f}/{pct(stats[null + ' best'], 95):+.3f}R"
                f" | book's max best p50/p95 {pct(stats[null + ' maxbest'], 50):+.3f}/{pct(stats[null + ' maxbest'], 95):+.3f}R"
                f" | gap p50/p95 {pct(stats[null + ' gap'], 50):.3f}/{pct(stats[null + ' gap'], 95):.3f}R"
                f" | best's lead over the rest p95 {pct(stats[null + ' lead'], 95):.3f}R"
                f" (n {len(stats[null + ' vsfb'])} with a warm fallback)"
                f" | entries gap p95 {pct(stats[null + ' egap'], 95):.3f}R")
        if horizon is None:
            for key, real_v in (("best", got["best"]), ("gap", got["gap"]), ("lead", got["lead"]),
                                ("egap", got["entries_gap"])):
                null_v = stats[f"perm {key}"]
                if real_v and null_v:
                    beyond = np.mean([v > pct(null_v, 95) for v in real_v])
                    say(f"    real vs perm null, {key}: {beyond:.0%} of real contexts beyond the null's p95")
    # What production actually printed: the arm_reason on decisions.
    if picks:
        vals = []
        for _, _, why in picks:
            try:
                vals.append(float(why.rsplit(" at ", 1)[1].rstrip("R")))
            except (IndexError, ValueError):
                pass
        cold = sum("cold" in w for _, _, w in picks)
        say(f"\n  PRODUCTION's own picks: {len(picks)} decisions, {cold} cold (default), "
            f"{len(vals)} warm picks; the printed mean p50/p95 {pct(vals, 50):+.3f}/{pct(vals, 95):+.3f}R")


# ------------------------------------------------------------------------------------ the z gate


def walk(n, rng, kind):
    if kind == "t3":
        r = rng.standard_t(3, n) * 0.001
    else:  # GARCH(1,1), persistent volatility, no direction
        r, v = np.empty(n), 1e-6
        z = rng.standard_normal(n)
        for i in range(n):
            v = 2e-8 + 0.08 * (r[i - 1] ** 2 if i else 0.0) + 0.9 * v
            r[i] = math.sqrt(v) * z[i]
    return 100.0 * np.exp(np.cumsum(r))


BARS_PER_DAY = {"1m": 1440, "5m": 288, "15m": 96, "1h": 24, "4h": 6}  # 24/7; FX runs 5/7 of it


def zma_part():
    say("\nZMA EDGE RECORD on walks we generate: the production Zma, warmed on the store's 3,000 bars, "
        "then live. 'earned' = edge_calls >= %d and right > %.0f%%" % (200, 52))
    zs = NormalDist()
    rows = []
    for interval, per_day in BARS_PER_DAY.items():
        for kind in ("t3", "garch"):
            for days in HORIZONS:
                n = 3000 + int(per_day * days * 5 / 7)
                seeds = max(8, min(SEEDS, int(4e6 / n)))
                earned_end, ever, frac, calls = 0, 0, [], []
                for s in range(seeds):
                    rng = np.random.default_rng(7000 + s)
                    z = zm.Zma()
                    passed = 0
                    ever_s = False
                    checks = 0
                    for i, p in enumerate(walk(n, rng, kind)):
                        z.observe(float(p))
                        if i >= 3000 and i % 10 == 0:
                            checks += 1
                            ok = z.edge_calls >= 200 and z.edge_right / z.edge_calls > 0.52
                            passed += ok
                            ever_s |= ok
                    earned_end += z.edge_calls >= 200 and z.edge_right / max(z.edge_calls, 1) > 0.52
                    ever += ever_s
                    frac.append(passed / max(checks, 1))
                    calls.append(z.edge_calls)
                n_calls = float(np.mean(calls))
                exact = 1 - zs.cdf(0.02 / math.sqrt(0.25 / n_calls)) if n_calls >= 200 else float("nan")
                rows.append((interval, kind, days, seeds, n_calls, earned_end / seeds, ever / seeds,
                             float(np.mean(frac)), exact))
                say(f"  {interval:4s} {kind:5s} {days:3d}d: seeds {seeds:3d} | edge calls {n_calls:8,.0f} | "
                    f"earned at end {earned_end / seeds:5.1%} (binomial {exact:5.1%}) | ever earned "
                    f"{ever / seeds:5.1%} | share of time earned {np.mean(frac):5.1%}")
    # A book of feeds at once: how many earn on a coin, and the Bonferroni line.
    say("\n  a book of F series (feed x interval) all on a coin, at the end of each horizon:")
    for F in (50, 100, 200):
        for interval in BARS_PER_DAY:
            for days in HORIZONS:
                share = next(r[5] for r in rows if r[0] == interval and r[1] == "t3" and r[2] == days)
                say(f"    F={F:3d} {interval:4s} {days:3d}d: expected {F * share:5.1f} series earned by chance,"
                    f" P(at least one) {1 - (1 - share) ** F:5.1%}") if interval in ("15m", "1h", "4h") else None
    say("\n  the line that holds the book's false-earn rate at 5% (Bonferroni over F series):")
    for F in (1, 50, 100, 200):
        zc = zs.inv_cdf(1 - FALSE_ACTION / F)
        line = ", ".join(f"n={n}: {0.5 + zc * math.sqrt(0.25 / n):.3f}" for n in (200, 500, 1000, 5000, 20000))
        say(f"    F={F:3d} (z {zc:.2f}): {line}")


# ------------------------------------------------------------------------------------ cycles


def cycles_part():
    try:
        from till_infinity.structures import cycles as cy
    except Exception as exc:  # river missing
        say(f"\nCYCLES: skipped ({exc})")
        return
    say("\nCYCLES DEPTH HEAD on walks we generate: production Book, skill > %.2f after %d settled turns"
        % (cy.MIN_SKILL, cy.WARM))
    for kind in ("t3", "garch"):
        for days in (30, 90):
            n = int(1440 * days * 5 / 7)
            seeds = max(4, min(12, SEEDS // 20))
            earned, skills, settled = 0, [], []
            t0 = time.time()
            for s in range(seeds):
                rng = np.random.default_rng(9000 + s)
                book = cy.Book()
                series = None
                for i, p in enumerate(walk(n, rng, kind)):
                    series = book.observe("walk", "1m", float(p))
                    if i % 15 == 14:
                        book.observe("walk", "15m", float(p))
                    if i % 60 == 59:
                        book.observe("walk", "1h", float(p))
                turns = series.turns
                settled.append(turns.settled)
                if turns.warm:
                    skills.append(turns.depth_skill)
                    earned += turns.depth_skill > cy.MIN_SKILL
            say(f"  1m+15m+1h {kind:5s} {days:3d}d: seeds {seeds} | settled turns p50 "
                f"{pct(settled, 50):.0f} | warm {len(skills)} | skill p50/p95 {pct(skills, 50):+.3f}/"
                f"{pct(skills, 95):+.3f} | earned {earned}/{seeds} ({time.time() - t0:.0f}s)")

if __name__ == "__main__":
    if PART in ("all", "policy"):
        rows, closed, picks = stream()
        if rows:
            policy_part(rows, closed, picks)
        else:
            say("POLICY: no resolved untaken rewards in the journal")
    if PART in ("all", "zma"):
        zma_part()
    if PART in ("all", "cycles"):
        cycles_part()
