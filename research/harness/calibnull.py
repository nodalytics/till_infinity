"""A world where every strategy's true edge is exactly minus its costs.

`research/calibrating.md`. This module is the **instrument**, not the result:
it builds synthetic books whose true return on risk is known in closed form, so
that the desk's own analysis can be run on them and its false-positive rate
measured. `calibfpr.py` and `calibscan.py` hold the measurements.

## Why a known answer is available at all

`research/deriving.md` proves that a predictable position on a martingale has
zero gross expectancy, so `E[net] = -(c/2) x turnover` for every stop, target,
trail, entry filter and sizing rule. `research/rebuilding.md` then showed the
Deriv generators can be re-instantiated from published parameters alone. Put
those together and a simulated path is a world where **every strategy's true
edge is the negative of its costs and nothing else**, which makes any "edge" an
analysis finds there a false positive by construction.

Concretely, with `shared.replay.walk` charging a round trip of `c` on a stop
distance of `risk`, and writing `k = c / risk`:

    entry  = level + c/2              (up; mirrored for down)
    R      = (P_exit - c/2 - entry) / risk = (P_exit - level - c) / risk
    E[P_exit] = level                 (optional stopping, bounded hold)
    =>  E[R] = -k   exactly, for every policy, every entry rule, every size.

So the null value of return-on-risk is `-COST_R`, analytically, and the pool's
own mean is a check on the arithmetic rather than the source of the number.

## Three things that would break the null, and what is done about them

**Geometric Brownian motion is not a martingale in the price.** `rebuildgen`'s
`gen_gbm` is driftless *in the log*, which leaves `+sigma^2/2` of drift in the
price - about +0.8% of risk per twenty-bar trade at the Volatility family's
scale, a third of the cost being charged. That is a real edge in what is
supposed to be a null world. The generators here therefore carry the Ito
compensator, which is a one-line difference and is the whole reason this module
does not simply import `gen_gbm`. `rebuildgen.py` is read, not edited.

**Range Break is not a martingale between breaks.** `_fold` reflects the walk
off both edges, and a reflecting walk drifts toward the centre; `deriving.md`
measures exactly that (sub-diffusive by 3.6x and 8.9x) and says the break pays
for it. A range-bound instrument in the pool would put a genuine mean-reverting
edge inside the null, so the family is excluded rather than included wrongly.

**Boom and Crash do not close on their published parameters.**
`rebuilding.md` found `lambda`, `E[g]` and `E[J]` miss `E[J] = lambda * E[g]`
by 6-12% on all six feeds, which is drift. The closure is imposed here, which
makes the process an exact martingale, and that arm is run separately because
its one-sided jump tail is a different distributional question.

The martingale property is not assumed: `check_world()` measures the mean price
increment against its own standard error and the pool's mean R against `-k`.

## What would have killed this, declared before any number was read

1. **The pool's mean price increment is more than 3 SE from zero.** Then the
   world is not a martingale, every "true value" below is wrong, and nothing in
   `calibrating.md` may be reported.
2. **The pool's return on risk differs from `-COST_R` by more than 3 SE.** The
   theorem's prediction is exact; a miss means the replay, the cost model or
   the quote grid is not doing what the derivation above says.
3. **The null book does not resemble the real book.** The per-close standard
   deviation of return on risk must land within 25% of the live 0.805, and the
   stop row within 5 points of the live -102.7%. A false-positive rate measured
   on a distribution the desk does not have does not transfer to the desk, and
   would have to be reported as such rather than as a correction.
4. **Any rate landing on exactly its null to four decimals** - 0.0500, 0.5000 -
   is treated as a bug and hunted, per `research/README.md`.
5. **The exit mix is all stops.** `exiting.md` records a replay that exited 98%
   by stop where the desk exits 13%; an exit mix that far from the live one is
   evidence about the harness, and is reported next to the live mix.

Run on the lab:

    ./.secrets/lab.sh run research/harness/calibnull.py CLOSES=1000000
"""

from __future__ import annotations

import json
import math
import multiprocessing as mp
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.environ.get("REPO", os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

import research.harness.rebuildgen as G  # noqa: E402
from till_infinity.shared.replay import walk  # noqa: E402

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/results"))
#: Closes in the pool. A book is drawn from it; the pool's own mean is the
#: reference the analytic null is checked against, so it wants to be large.
CLOSES = int(os.environ.get("CLOSES", "1000000"))
#: Round-trip cost as a share of the risk deployed. `spending.md` measures the
#: live stop row at -102.7% against a nominal -100%, which is 2.7 points of
#: spread and slippage on a 1R stop, so this is the live number rather than a
#: guess. A zero-cost null is a different and easier world and is not used.
COST_R = float(os.environ.get("COST_R", "0.027"))
SEED = int(os.environ.get("SEED", "20260911"))
#: How many one-bar standard deviations the desk's *volatility unit* is worth.
#: `risk_vol` on the live record has a median of 1.328, and a stop 1.3 one-bar
#: sigmas away is hit by almost everything; the live book stops 31.6% of the
#: time over a median of four minutes, which is a much wider stop in bar terms.
#: This and `HOLD_MULT` are the only two shape knobs, they are set by matching
#: the live exit mix and per-close spread, and **neither can move the answer**:
#: the theorem fixes expectancy at `-COST_R` for every policy.
UNIT_MULT = float(os.environ.get("UNIT_MULT", "2.0"))
HOLD_MULT = float(os.environ.get("HOLD_MULT", "0.3"))
WORKERS = int(os.environ.get("WORKERS", str(min(32, os.cpu_count() or 8))))
#: Include the Boom/Crash arm, with the closure imposed. Separate because the
#: one-sided jump tail is a different distributional question from the rest.
FAT = os.environ.get("FAT", "0") == "1"

MINUTE_TICKS = 60

# ------------------------------------------------------------- the live book --
#: The real-markets half of `.data/closes.json` as `spending.py` restricts it:
#: 133 closes carrying both a profit and a risk figure. Every composition below
#: is the live one, so that a null book is the desk's own book with the market
#: replaced and nothing else changed.
LIVE_N = 133
LIVE_ON_RISK = -0.22222
LIVE_R_SD = 0.8053
LIVE_STOP_ROW = -1.028
LIVE_SKEW = 0.722
LIVE_XKURT = 0.527
#: `(name, closes)` - the twelve rows `spending.py`'s strategy cut produces.
#: Only the first five clear the n>=8 floor `interval()` needs, which is itself
#: part of the answer: a twelve-row table is a five-interval table.
LIVE_STRATEGIES: tuple[tuple[str, int], ...] = (
    ("snap", 29), ("thesis-only", 28), ("sweep-aware", 23), ("runner", 17),
    ("fade-to-value", 16), ("inverse", 6), ("unknown", 5), ("approach-scalp", 3),
    ("confluence-scalp", 2), ("opportunity", 2), ("level-scalp", 1), ("origin-swing", 1),
)
LIVE_FEEDS: tuple[tuple[str, int], ...] = (
    ("gold", 29), ("us30", 12), ("us100", 10), ("ger40", 9), ("uk100", 8), ("silver", 7),
    ("us2000", 6), ("gbpusd", 6), ("btc", 5), ("fra40", 5), ("gbpjpy", 4), ("usdchf", 4),
    ("eurchf", 4), ("audusd", 3), ("usdcad", 3), ("eth", 2), ("brent", 2), ("aus200", 2),
    ("hk50", 2), ("wti", 2), ("euraud", 2), ("audjpy", 2), ("spx500", 1), ("eu50", 1),
    ("usdcnh", 1), ("eurjpy", 1),
)
LIVE_INTERVALS: tuple[tuple[str, int], ...] = (
    ("1m", 44), ("3m", 37), ("5m", 34), ("15m", 12), ("30m", 3), ("1h", 2), ("2h", 1),
)

#: `till_infinity/trading/strategies/opportunity.py::PRESETS`, read off the
#: shipping classes. `hold=0` there means "the deployment ceiling and nothing
#: tighter"; `replay.py` records that the live desk holds about 30 bars, which
#: is the number used. The theorem makes the *choice* of policy irrelevant to
#: expectancy, so this set is here only to reproduce the live book's shape.
SHAPES: dict[str, dict] = {
    "snap": {"stop": 1.0, "target": 1.0, "trail": 0.75, "protect": 0.5, "hold": 2},
    "thesis-only": {"stop": 1.0, "target": 1.0, "trail": 0.0, "protect": 0.0, "hold": 30},
    "sweep-aware": {"stop": 1.0, "target": 6.0, "trail": 0.5, "protect": 1.0, "hold": 30},
    "runner": {"stop": 1.0, "target": 3.0, "trail": 1.0, "protect": 1.0, "hold": 30},
    "fade-to-value": {"stop": 1.0, "target": 1.0, "trail": 0.0, "protect": 0.0, "hold": 30},
    "inverse": {"stop": 1.0, "target": 1.0, "trail": 0.0, "protect": 0.0, "hold": 30},
    "unknown": {"stop": 1.0, "target": 2.0, "trail": 0.5, "protect": 1.0, "hold": 30},
    "approach-scalp": {"stop": 1.0, "target": 1.0, "trail": 0.0, "protect": 0.0, "hold": 30},
    "confluence-scalp": {"stop": 1.5, "target": 6.0, "trail": 0.5, "protect": 1.0, "hold": 30},
    "opportunity": {"stop": 1.0, "target": 3.0, "trail": 1.0, "protect": 1.0, "hold": 30},
    "level-scalp": {"stop": 1.0, "target": 1.0, "trail": 0.0, "protect": 0.0, "hold": 30},
    "origin-swing": {"stop": 1.0, "target": 2.5, "trail": 4.0, "protect": 1.5, "hold": 60},
}
STRATEGY_NAMES = tuple(SHAPES)

#: Instrument families. Each is a martingale in the *price*, which is the thing
#: the theorem needs and which `gen_gbm` is not.
FAMILIES: tuple[tuple[str, str, float, float], ...] = (
    # (name, kind, annualised volatility, tick seconds)
    ("vol_10", "gbm", 10.0, 2.0), ("vol_25", "gbm", 25.0, 2.0),
    ("vol_50", "gbm", 50.0, 2.0), ("vol_75", "gbm", 75.0, 2.0),
    ("vol_100", "gbm", 100.0, 2.0), ("vol_75_1s", "gbm", 75.0, 1.0),
    ("jump_10", "jump", 10.0, 1.0), ("jump_25", "jump", 25.0, 1.0),
    ("jump_50", "jump", 50.0, 1.0), ("jump_75", "jump", 75.0, 1.0),
    ("jump_100", "jump", 100.0, 1.0),
    ("step", "step", 0.0, 1.0),
)
#: `rebuildvol.py`: the Jump family reads 1.3226x its name, which leaves
#: `1.3226^2 - 1` of the diffusive variance for the jumps at three a minute.
JUMP_MULT = 1.3226
JUMP_RATE_PER_MIN = 3.0
#: `rebuildpaper.py::BOOM`, fitted on the feed: lambda, E[g], CV[g], E[J],
#: median J, side. `E[J]` is replaced by `lambda * E[g]` here - the closure
#: `rebuilding.md` found the published numbers miss by 6-12% - because an
#: unclosed compound Poisson has drift and would not be a null.
BOOM = {
    "boom_500": (529.4, 0.00977, 0.661, 3.9635, +1),
    "crash_500": (507.7, 0.00624, 0.655, 2.6280, -1),
    "boom_1000": (908.3, 0.01511, 0.671, 12.2198, +1),
    "crash_1000": (973.8, 0.00605, 0.656, 4.9718, -1),
}


# ------------------------------------------------------------- generators ----
def gen_mart_gbm(n_ticks, sigma_ann, tick_seconds, p0, grid, rng, chunk=2_000_000):
    """`rebuildgen.gen_gbm` with the Ito compensator, so the **price** is a
    martingale rather than the log price.

    Without `-sigma^2/2` the price drifts up by `sigma^2 t / 2`, which at the
    Volatility family's scale is about +0.8% of risk over a twenty-bar trade -
    a third of the cost this world charges, sitting inside the null.
    """
    s = (sigma_ann / 100.0) * math.sqrt(tick_seconds / G.SECONDS_PER_YEAR)
    logp = math.log(p0)
    done = 0
    while done < n_ticks:
        m = min(chunk, n_ticks - done)
        path = logp + np.cumsum(rng.standard_normal(m) * s - 0.5 * s * s)
        logp = float(path[-1])
        px = np.exp(path)
        yield np.round(px / grid) * grid if grid else px
        done += m


def gen_mart_jump(n_ticks, sigma_ann, tick_seconds, rate_per_min, jump_log, p0, grid,
                  rng, chunk=2_000_000):
    """The Jump family, compensated the same way.

    A symmetric jump of `+-a` in the log multiplies the price by `cosh(a)` in
    expectation, so the compensator carries `-lambda_tick * ln cosh(a)` beside
    the diffusive `-sigma^2/2`.
    """
    s = (sigma_ann / 100.0) * math.sqrt(tick_seconds / G.SECONDS_PER_YEAR)
    p_jump = rate_per_min * tick_seconds / 60.0
    drift = -0.5 * s * s - p_jump * math.log(math.cosh(jump_log))
    logp = math.log(p0)
    done = 0
    while done < n_ticks:
        m = min(chunk, n_ticks - done)
        steps = rng.standard_normal(m) * s + drift
        nj = rng.poisson(p_jump * m)
        if nj:
            pos = rng.integers(0, m, nj)
            np.add.at(steps, pos, jump_log * rng.choice(np.array([-1.0, 1.0]), size=nj))
        path = logp + np.cumsum(steps)
        logp = float(path[-1])
        px = np.exp(path)
        yield np.round(px / grid) * grid if grid else px
        done += m


def stream_for(name, kind, sigma, tick_s, n_ticks, rng):
    tpb = int(round(60.0 / tick_s))
    if kind == "step":
        return G.gen_step(n_ticks, 0.1, 0.5, 9000.0, rng), tpb
    if kind == "gbm":
        return gen_mart_gbm(n_ticks, sigma, tick_s, 10_000.0, 1e-4, rng), tpb
    if kind == "jump":
        sig_tick = (sigma / 100.0) * math.sqrt(tick_s / G.SECONDS_PER_YEAR)
        sig_min = sig_tick * math.sqrt(60.0 / tick_s)
        j2 = (JUMP_MULT ** 2 - 1.0) * sig_min ** 2 / JUMP_RATE_PER_MIN
        return gen_mart_jump(n_ticks, sigma, tick_s, JUMP_RATE_PER_MIN,
                             math.sqrt(j2), 10_000.0, 1e-4, rng), tpb
    if kind == "boom":
        lam, gm, gcv, jmed, side = BOOM[name]
        jmean = lam * gm  # the closure, imposed
        return G.gen_boomcrash(n_ticks, lam, gm, gcv, jmean, min(jmed, jmean * 0.999),
                               side, 100_000.0, 0.0, rng), tpb
    raise ValueError(kind)


# ------------------------------------------------------------------ a book ---
def bars_for(name, kind, sigma, tick_s, n_bars, rng):
    stream, tpb = stream_for(name, kind, sigma, tick_s, n_bars * tpb_of(tick_s), rng)
    return G.bars_from_stream(stream, tpb, n_bars)


def tpb_of(tick_s: float) -> int:
    return int(round(60.0 / tick_s))


def one_family(args):
    """Replay `n_trades` non-overlapping trades on freshly generated bars.

    The entries are placed on a fixed grid rather than chosen, because the
    theorem covers every entry rule and a filter would only make the world
    harder to describe without making it different.
    """
    name, kind, sigma, tick_s, n_trades, seed, cost_r, live_rr, live_rv, live_rm = args
    rng = np.random.default_rng([seed, abs(hash(name)) % (2 ** 31)])
    out_r, out_exit, out_strat, out_rr, out_rm, out_rv = [], [], [], [], [], []
    block = 200_000
    made = 0
    t0 = time.time()
    while made < n_trades:
        bars_d = bars_for(name, kind, sigma, tick_s, block, rng)
        cl = bars_d["close"]
        n = bars_d["n"]
        if n < 400:
            break
        bars = list(zip(bars_d["ts"].tolist(), bars_d["open"].tolist(),
                        bars_d["high"].tolist(), bars_d["low"].tolist(), cl.tolist(),
                        strict=True))
        # A volatility unit the way the desk carries one: a trailing 20-bar
        # standard deviation of the close, in price. `volatility.md` measured a
        # flat 20-bar mean beating the shipping estimator at every interval, so
        # this is the better of the two rather than a simplification.
        lr = np.zeros(n)
        lr[1:] = np.diff(cl) / cl[:-1]
        c1 = np.concatenate([[0.0], np.cumsum(lr)])
        c2 = np.concatenate([[0.0], np.cumsum(lr * lr)])
        unit = np.zeros(n)
        w = 20
        s1 = c1[w:n] - c1[:n - w]
        s2 = c2[w:n] - c2[:n - w]
        var = np.maximum((s2 - s1 * s1 / w) / (w - 1), 0.0)
        unit[w:] = np.sqrt(var) * cl[w:]
        i = 40
        while i < n - 300 and made < n_trades:
            si = int(rng.integers(0, len(STRATEGY_NAMES)))
            sname = STRATEGY_NAMES[si]
            shape = SHAPES[sname]
            u = unit[i] * UNIT_MULT
            if u <= 0:
                i += 25
                continue
            rv = float(live_rv[rng.integers(0, live_rv.size)])
            rr = float(live_rr[rng.integers(0, live_rr.size)])
            # `reward_to_risk` written at entry is `push * target / (risk_vol *
            # stop)`, so fixing the live ratio fixes the push the trade aims at.
            push = rr * rv * shape["stop"] / shape["target"]
            risk_price = rv * shape["stop"] * u
            if risk_price <= 0 or push <= 0:
                i += 25
                continue
            trade = {"up": bool(rng.integers(0, 2)), "unit": u, "push_vol": push,
                     "level": cl[i], "risk_vol": rv, "context": {}}
            policy = {"stop_mult": shape["stop"], "target_mult": shape["target"],
                      "trail_vol": shape["trail"], "protect_r": shape["protect"],
                      "trail_after_r": shape["protect"]}
            hold_bars = max(1, int(round(shape["hold"] * HOLD_MULT)))
            # The trade is entered at the close of bar `i`, so the walk starts
            # at `i + 1`. Starting it at `i` would test the exits against that
            # bar's own high and low, which happened *before* the entry - the
            # look-ahead `replay.py`'s docstring exists because of.
            got = walk(bars, i + 1, trade, cost=cost_r * risk_price, hold=hold_bars,
                       policy=policy)
            if got is None:
                i += 25
                continue
            r, kind_exit = got
            out_r.append(r)
            out_exit.append(kind_exit)
            out_strat.append(si)
            out_rr.append(rr)
            out_rv.append(rv)
            out_rm.append(float(live_rm[rng.integers(0, live_rm.size)]))
            made += 1
            i += hold_bars + 25
        if time.time() - t0 > 3600:
            break
    ex = {"stop": 0, "target": 1, "hold": 2}
    return (name, np.array(out_r), np.array([ex[e] for e in out_exit], dtype=np.int8),
            np.array(out_strat, dtype=np.int8), np.array(out_rr),
            np.array(out_rv), np.array(out_rm))


def live_draws():
    """The live book's `reward_to_risk`, `risk_vol` and `risk_money` columns.

    Resampled rather than modelled: the null book is meant to be the desk's own
    book with the *market* replaced, so its geometry should be the live one.
    Falls back to the fitted lognormals when the export is not on the machine.
    """
    path = os.environ.get("CLOSES_JSON", ".data/closes.json")
    try:
        import re
        rows = [r.get("ctx", {}) for r in json.loads(open(path).read())]
        gen = re.compile(r"^(volatility|jump|boom|crash|step|range_break)_", re.I)
        pay = [r for r in rows
               if not gen.match(str(r.get("feed") or ""))
               and r.get("profit") is not None and float(r.get("risk_money") or 0) > 0]
        if len(pay) >= 100:
            return (np.array([float(r["reward_to_risk"]) for r in pay]),
                    np.array([float(r["risk_vol"]) for r in pay]),
                    np.array([float(r["risk_money"]) for r in pay]), "live export")
    except Exception:
        pass
    rng = np.random.default_rng(7)
    return (np.exp(rng.normal(math.log(1.364), 0.80, 4000)),
            np.exp(rng.normal(math.log(1.328), 0.62, 4000)),
            np.exp(rng.normal(math.log(22.95), 0.30, 4000)), "fitted fallback")


def build(n_closes: int, fat: bool, seed: int) -> dict:
    rr, rv, rm, src = live_draws()
    fams = list(FAMILIES)
    if fat:
        fams += [(k, "boom", 0.0, 1.0) for k in BOOM]
    # Each family is split across several workers with independent seeds, so
    # sixty-four cores are sixty-four paths rather than twelve.
    shards = max(1, WORKERS // len(fams)) if WORKERS > len(fams) else 1
    per = max(500, n_closes // (len(fams) * shards) + 1)
    jobs = []
    for j, (n, k, sg, t) in enumerate(fams):
        for sh in range(shards):
            jobs.append((n, k, sg, t, per, seed + 1000 * j + 7 * sh, COST_R, rr, rv, rm))
    print(f"  {len(fams)} families x {shards} shards x {per} closes, {WORKERS} workers,"
          f" geometry from {src}", flush=True)
    with mp.Pool(WORKERS) as pool:
        got = pool.map(one_family, jobs)
    names: list[str] = []
    R, EX, ST, RR, RV, RM, FAM = [], [], [], [], [], [], []
    for name, r, ex, st, rrv, rvv, rmv in got:
        if name not in names:
            names.append(name)
        idx = names.index(name)
        R.append(r); EX.append(ex); ST.append(st); RR.append(rrv)
        RV.append(rvv); RM.append(rmv); FAM.append(np.full(r.size, idx, dtype=np.int16))
    for idx, name in enumerate(names):
        sel = np.concatenate(FAM) == idx
        rr_all = np.concatenate(R)
        print(f"    {name:12} {int(sel.sum()):8d} closes  mean R "
              f"{rr_all[sel].mean():+.5f}", flush=True)
    return {"family_names": names, "r": np.concatenate(R), "exit": np.concatenate(EX),
            "strategy": np.concatenate(ST), "reward_to_risk": np.concatenate(RR),
            "risk_vol": np.concatenate(RV), "risk_money": np.concatenate(RM),
            "family": np.concatenate(FAM)}


# --------------------------------------------------------- the world's checks --
def check_world(pool: dict) -> list[dict]:
    """The pre-registered conditions, scored. Printed before anything else."""
    led: list[dict] = []
    r = pool["r"]
    n = r.size
    se = r.std(ddof=1) / math.sqrt(n)
    print(f"\n[0] THE WORLD  n={n} closes, cost {COST_R * 100:.1f}% of risk\n")

    # (2) the theorem's prediction, exactly
    z = (r.mean() + COST_R) / se
    print(f"  mean R            {r.mean():+.5f}   theorem says {-COST_R:+.5f}"
          f"   SE {se:.5f}   z {z:+.2f}")
    led.append({"test": "pool mean R equals -COST_R within 3 SE", "value": z,
                "fired": abs(z) > 3})

    # return on risk, the statistic spending.py actually reports
    onr = float((r * pool["risk_money"]).sum() / pool["risk_money"].sum())
    w = pool["risk_money"]
    se_onr = float(np.sqrt(((w * (r - onr)) ** 2).sum()) / w.sum())
    z2 = (onr + COST_R) / se_onr
    print(f"  on risk           {onr * 100:+.4f}%  theorem says {-COST_R * 100:+.4f}%"
          f"  SE {se_onr * 100:.4f}%  z {z2:+.2f}")
    led.append({"test": "pool return-on-risk equals -COST_R within 3 SE", "value": z2,
                "fired": abs(z2) > 3})

    # (3) does it look like the desk's book
    sd = float(r.std(ddof=1))
    print(f"\n  per-close sd      {sd:.4f}   live {LIVE_R_SD:.4f}"
          f"   ratio {sd / LIVE_R_SD:.3f}")
    led.append({"test": "per-close sd within 25% of the live 0.805",
                "value": sd / LIVE_R_SD - 1, "fired": abs(sd / LIVE_R_SD - 1) > 0.25})
    names = {0: "stop", 1: "target", 2: "hold"}
    live_mix = {"stop": 42 / 133, "target": 17 / 133, "hold": 50 / 133}
    print(f"\n  {'exit':8} {'share':>8} {'live':>8} {'mean R':>9} {'live':>9}")
    live_mean = {"stop": -1.028, "target": +0.796, "hold": +0.043}
    for k, nm in names.items():
        m = pool["exit"] == k
        if not m.any():
            continue
        print(f"  {nm:8} {m.mean() * 100:7.1f}% {live_mix[nm] * 100:7.1f}% "
              f"{r[m].mean():+9.3f} {live_mean[nm]:+9.3f}")
        if nm == "stop":
            led.append({"test": "stop row within 5 points of the live -102.7%",
                        "value": r[m].mean() - LIVE_STOP_ROW,
                        "fired": abs(r[m].mean() - LIVE_STOP_ROW) > 0.05})
    stops = float((pool["exit"] == 0).mean())
    led.append({"test": "exit mix is not 98% stops (exiting.md's harness bug)",
                "value": stops, "fired": stops > 0.90})

    print(f"\n  R quantiles  " + "  ".join(
        f"{p}%={np.percentile(r, p):+.3f}" for p in (1, 5, 25, 50, 75, 95, 99)))
    print(f"  live         1%=-1.385  5%=-1.256  25%=-0.945  50%=-0.217  "
          f"75%=+0.269  95%=+0.965  99%=+1.919")
    print(f"  skew {float(((r - r.mean()) ** 3).mean() / sd ** 3):+.3f}"
          f" (live {LIVE_SKEW:+.3f})   excess kurtosis {G.kurtosis(r) - 3.0:+.3f}"
          f" (live {LIVE_XKURT:+.3f})")

    # The stop row is relabelled by the trail, and that is worth showing rather
    # than arguing: on the five strategies whose shape carries no trail and no
    # break-even move, a "stop" is the stop.
    flat = [i for i, nm in enumerate(STRATEGY_NAMES)
            if SHAPES[nm]["trail"] == 0.0 and SHAPES[nm]["protect"] == 0.0]
    m = (pool["exit"] == 0) & np.isin(pool["strategy"], flat)
    if m.any():
        print(f"\n  stop row on the {len(flat)} untrailed shapes: {r[m].mean():+.4f}"
              f"  (n={int(m.sum())}) - a stop that is a stop")
    m2 = (pool["exit"] == 0) & ~np.isin(pool["strategy"], flat)
    if m2.any():
        print(f"  stop row on the trailed shapes:      {r[m2].mean():+.4f}"
              f"  (n={int(m2.sum())}) - break-even and trail exits wear the same label")
    return led


def main() -> None:
    t0 = time.time()
    print("A NULL WORLD: EVERY STRATEGY'S TRUE EDGE IS MINUS ITS COSTS")
    print(f"machine: {G.machine()}   seed {SEED}   cost {COST_R}   fat arm {FAT}\n")
    pool = build(CLOSES, FAT, SEED)
    led = check_world(pool)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "calibnull_fat.npz" if FAT else "calibnull.npz")
    np.savez_compressed(
        path, r=pool["r"], exit=pool["exit"], strategy=pool["strategy"],
        reward_to_risk=pool["reward_to_risk"], risk_vol=pool["risk_vol"],
        risk_money=pool["risk_money"], family=pool["family"],
        family_names=np.array(pool["family_names"]),
        strategy_names=np.array(STRATEGY_NAMES), cost_r=np.array([COST_R]))
    print(f"\n  wrote {path}  ({pool['r'].size} closes)")

    print("\n[LEDGER] the conditions written down before the numbers\n")
    for row in led:
        print(f"  {'FIRED ' if row['fired'] else 'held  '} {row['test']:58} "
              f"{row['value']:+.4f}")
    print(f"\n  {sum(1 for x in led if x['fired'])} of {len(led)} fired"
          f"   ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
