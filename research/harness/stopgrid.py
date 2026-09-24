"""How wide should a stop be, as a function of the volatility state, at equal money at risk?

`riskswitch.py` compared two stops - 1U at size 1 against 2U at size 0.5 - split by a model
score. Production does something else: it halves *size* when `tr_percentile` >= 0.8 and
leaves the stop where it was. This harness asks the general question on a grid:

  a rule = (k_lo, k_hi, theta, m)
    tr_percentile <  theta   stop k_lo x U, size 1/k_lo          (money at risk 1)
    tr_percentile >= theta   stop k_hi x U, size m/k_hi          (money at risk m)

  k in {0.5, 0.75, 1, 1.5, 2, 3}, theta in {0.5, 0.6, 0.7, 0.8, 0.9, 0.95}, m in {1, 0.5}.
  m = 1 is the literal "equal money at risk" question; m = 0.5 is production's family, where
  the high state also risks half. Production today is (1, 1, 0.8, 0.5); "also widen" is
  (1, 2, 0.8, 1) - a 2U stop at half size - and (1, 2, 0.8, 0.5) is widening at production's
  own risk. `flat` is (1, 1, -, 1). A uniform rule (k_lo = k_hi, m = 1) ignores theta, so it
  is counted once: 402 distinct rules.

Every outcome is in one currency: U at size 1, which is "R" of the flat 1U rule. A rule's
loss is therefore capped near -1 (or -m) whatever its k, and only a gap goes past it.

Positions, which know nothing about the rule: always long, always short, and momentum (the
sign of the last 20 closes), each entered at the close and held H bars (15m: 8, 1h: 5,
1d: 5). The stop is a resting order: taken by the wick, filled at the level or at the open
when a bar gaps through it (`bars.race`, stop-only). Unstopped, it is marked at the H-th
close. A no-stop baseline at size 1 is carried alongside.

  U            trailing mean |log return| (500 bars; 250 daily; returns across a missing bar
               excluded intraday) x sqrt(H), known at the entry close.
  tr_percentile  true range TR = max(H-L, |H-Cprev|, |L-Cprev|) in log price, EWMA alpha 1/14,
               ranked within its own last 1500 values including the current one - causal, the
               research twin of `Volatility.tr_percentile`.
  cost         a round-trip spread in M5-volatility units, x base / sqrt(minutes/5), paid by
               every position at its size: real families as `questions.COST_V`, synthetics from
               `research/docs/catalogue.md`. A wider stop at a smaller size pays less of it.

Method. Entries every H-th bar per series, so no two overlap. Each series split by time:
first 60% of its entries is training, last 40% is test, reported as two halves (A, B). The
rule is chosen on training only, per (interval, family, position), by a criterion fixed
before any test number was printed (`CRITERION`). Differences on test are given a
block-bootstrap SE (40 calendar blocks), and with 402 rules x 3 positions x ~11 families x
3 intervals a lone 2-SE result means nothing: the bar is |t| >= 3 with both test halves
agreeing.

The criterion, and the one that was dropped. The first choice was the 1% expected
shortfall per unit of standard deviation, meant to stop "smaller position" from winning a
tail contest. The training landscape (STAGE=train, no test number seen) showed it picks the
tightest stop everywhere: a 0.5U stop at double size is a lottery ticket whose right tail
inflates the sd, so ES/sd flatters it. It was replaced, still before any test number was
printed, by the literal question: the 1% expected shortfall (ES1, mean of the worst 1%) in
R, ties to the higher mean - with the mean-maximising rule reported beside it. Because every
rule risks the same money, ES1 sits near -1R by construction and moves only through slip
past the stop (which shrinks as 1/k), cost (also 1/k) and the high state's risk m. Past
k = 3 a stop is hit on under ~1% of entries and ES1 starts measuring "a smaller position",
which is why the grid stops at 3U.

Fills. `bars.race` fills at the level unless the bar *opens* beyond it, which is right for a
continuous path and badly wrong where the adverse move is one tick: a Boom short or Crash
long is stopped by a spike that lands 10-19R past the level (generators.md, on ticks), and
the bar shows only its wick. So a second fill is carried for every stop - the extreme of the
bar that took it - and used where the stop sits on the spike side (Boom and DEX UP shorts,
Crash and DEX DOWN longs; `leg`). Applied to the grind side, or to every stop, it charged a
0.5U stop 0.2-0.4R of "slip" on a walked path - an artefact, seen on training and dropped.
Jump and Range Break jump both ways and are judged on the level fill, which understates them.

Three selections, each among rules that risk the same money as the rule they would replace:
  A  any (k_lo, k_hi, theta), m = 1            186 rules, against flat
  C  k_lo = 1 fixed, any k_hi and theta, m = 1  36 rules, against flat - "widen only when hot"
  B  m = 0.5 at theta = 0.8, any k_lo, k_hi     36 rules, against production
Grouping this way was also fixed on training: letting m = 0.5 rules compete on ES1 with m = 1
ones just rewards risking less money.

  state table  per state (tr_percentile >= 0.8 or not) and k at size 1/k: stop rate, share
               of stops that gapped, slip past the level in R, and the stop's "tax" - mean
               (R with the stop - R without) / k, zero on a martingale for any k.

Data: the lab's seqlab bars ($SEQLAB/<SYMBOL>.<interval>.npz, 50,000 bars each), real and
Deriv synthetics. Every series passes `spikerisk.leak_check` (close location vs next return,
|corr| <= 0.15) or is skipped and named; daily bars start 1993.

Run on the lab (never on production):
  ./.secrets/lab.sh run research/harness/stopgrid.py OMP_NUM_THREADS=8 [STAGE=train|all]
      [FILL=primary|level|x] [INTERVALS=15m,1h,1d] [SEQLAB=...] [OUT=...]
STAGE=train prints training metrics only - the landscape the criterion was chosen from.
Writes $OUT (default ~/till_infinity/results/stopgrid.csv).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from bars import Bars, race
from spikerisk import leak_check

SEQLAB = Path(os.environ.get("SEQLAB", "~/till_infinity/data/seqlab")).expanduser()
OUT = Path(os.environ.get("OUT", "~/till_infinity/results/stopgrid.csv")).expanduser()
STAGE = os.environ.get("STAGE", "all")

H_FOR = {"15m": 8, "1h": 5, "1d": 5}
MINUTES = {"15m": 15, "1h": 60, "1d": 1440}
BASE_BARS = {"15m": 500, "1h": 500, "1d": 250}
DAILY_FROM = pd.Timestamp("1993-01-01").timestamp()

FX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDCNH",
      "EURGBP", "EURJPY", "EURCHF", "EURAUD", "GBPJPY", "AUDJPY", "CHFJPY"]
FAMILY_OF = [  # (family, test on the symbol name), first match wins
    ("fx", lambda s: s in FX),
    ("metal", lambda s: s in ("XAUUSD", "XAGUSD")),
    ("crypto", lambda s: s in ("BTCUSD", "ETHUSD", "SOLUSD")),
    ("volatility", lambda s: s.startswith("Volatility_")),
    ("jump", lambda s: s.startswith("Jump_")),
    ("step", lambda s: "Step_" in s),
    ("boom", lambda s: s.startswith("Boom_")),
    ("crash", lambda s: s.startswith("Crash_")),
    ("range_break", lambda s: s.startswith("Range_Break_")),
    ("dex", lambda s: s.startswith("DEX_")),
    ("drift", lambda s: s.startswith("Drift_Switch_")),
]
# Round-trip spread in M5-volatility units. Real: questions.COST_V (fx is its 0.8, not the
# catalogue's 21:00 worst case). Synthetics: catalogue.md's measured medians per family;
# dex and drift were not sampled and take a cautious 0.2.
COST_V = {"fx": 0.8, "metal": 0.16, "crypto": 0.5, "volatility": 0.17, "jump": 0.12, "step": 0.075,
          "boom": 0.13, "crash": 0.17, "range_break": 0.14, "dex": 0.2, "drift": 0.2}

KS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
THETAS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)
MS = (1.0, 0.5)
PRODUCTION = (1.0, 1.0, 0.8, 0.5)
FLAT = (1.0, 1.0, 0.8, 1.0)
WIDEN = (1.0, 2.0, 0.8, 1.0)
WIDEN_HALF = (1.0, 2.0, 0.8, 0.5)
POSITIONS = ("long", "short", "momentum")
# Chosen on training only, before any test number was printed (see the docstring for why the
# first choice, es_sd, was dropped after the training landscape showed it rewards a lottery).
CRITERION = os.environ.get("CRITERION", "es1")
SPIKY = {"boom", "crash", "dex"}
FILL = os.environ.get("FILL", "primary")
INTERVALS = tuple(os.environ.get("INTERVALS", "15m,1h,1d").split(","))


def rules():
    out = []
    for m in MS:
        for klo in KS:
            for khi in KS:
                if klo == khi and m == 1.0:
                    out.append((klo, khi, 0.8, m))  # theta is irrelevant; one representative
                    continue
                out += [(klo, khi, th, m) for th in THETAS]
    return out


def family(sym):
    return next((f for f, test in FAMILY_OF if test(sym)), None)


def load(sym, interval):
    """One seqlab series, bars repaired to contain their own open and close, leak-checked."""
    z = np.load(SEQLAB / f"{sym}.{interval}.npz")
    d = pd.DataFrame({k: z[k].astype(float) for k in ("time", "open", "high", "low", "close")})
    d = d[(d.close > 0) & (d.open > 0) & (d.low > 0)]
    if interval == "1d":
        d = d[d.time >= DAILY_FROM]
    d = d.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    d["high"] = d[["open", "high", "close"]].max(axis=1)
    d["low"] = d[["open", "low", "close"]].min(axis=1)
    leak_check(d, f"{sym}/{interval}")
    return d


def series(sym, interval):
    """Per-entry outcomes of one series: every H-th bar with a full path and a state."""
    H, fam = H_FOR[interval], family(sym)
    d = load(sym, interval)
    lo, lh, ll, lc = (np.log(d[c].to_numpy()) for c in ("open", "high", "low", "close"))
    r = pd.Series(lc).diff()
    if interval != "1d":
        r[d.time.diff().to_numpy() != MINUTES[interval] * 60] = np.nan
    nb = BASE_BARS[interval]
    base = r.abs().rolling(nb, min_periods=nb // 2).mean().to_numpy()
    prev = np.concatenate([[np.nan], lc[:-1]])
    tr = np.nanmax(np.column_stack([lh - ll, np.abs(lh - prev), np.abs(ll - prev)]), axis=1)
    ew = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean()
    pct = ew.rolling(1500, min_periods=500).rank(pct=True).to_numpy()
    mom = np.sign(lc - pd.Series(lc).shift(20).to_numpy())

    n = len(d)
    shift = lambda x, k: np.concatenate([x[k:], np.full(k, np.nan)]) - lc
    P = Bars(*(np.column_stack([shift(x, k) for k in range(1, H + 1)]) for x in (lo, lh, ll, lc)))
    U = base * np.sqrt(H)
    ok = np.isfinite(P.c).all(axis=1) & np.isfinite(U) & (U > 0) & np.isfinite(pct) & (mom != 0)
    idx = np.flatnonzero(ok)
    if len(idx) < 200 * H:
        return None
    idx = idx[(idx - idx[0]) % H == 0]  # non-overlapping
    if len(idx) < 200:
        return None
    sub = lambda a: a[idx]
    Ps = Bars(sub(P.o), sub(P.h), sub(P.l), sub(P.c))
    Us = U[idx]
    part = np.where(np.arange(len(idx)) < int(0.6 * len(idx)), 0, 1)
    cut_b = int(0.6 * len(idx)) + (len(idx) - int(0.6 * len(idx))) // 2
    part[cut_b:] = 2
    cost = COST_V[fam] * base[idx] / np.sqrt(MINUTES[interval] / 5) / Us
    out = dict(sym=np.full(len(idx), sym), family=np.full(len(idx), fam), time=d.time.to_numpy()[idx],
               part=part, pct=pct[idx], cost=cost, mom=mom[idx], spike=np.full(len(idx), spike_dir(sym)))
    # what makes a leg: per position and stop width, R in U at size 1, stopped?, slip past level (U)
    for pos, sgn in (("long", 1.0), ("short", -1.0), ("momentum", mom[idx])):
        Q = Ps * sgn
        out[f"{pos}|none"] = Q.end / Us
        for k in KS:
            lvl = k * Us
            w, fill = race(Q, np.full(len(idx), np.inf), lvl)
            stopped = w == -1
            # The pessimistic fill: the low of the bar that took the stop. A bar cannot show a jump
            # inside it, and on the spike side of Boom/Crash the fill lands where the spike lands
            # (generators.md: 10-19R past the level on ticks), which is the bar's extreme.
            first = np.argmax(Q.l <= -lvl[:, None], axis=1)
            worst = np.minimum(Q.l[np.arange(len(idx)), first], fill)
            out[f"{pos}|{k}"] = np.where(stopped, fill, Q.end) / Us
            out[f"{pos}|{k}|hit"] = stopped
            out[f"{pos}|{k}|slip"] = np.where(stopped, (fill + lvl) / Us, 0.0)  # <= 0, in U
            out[f"{pos}|{k}|x"] = np.where(stopped, worst, Q.end) / Us
            out[f"{pos}|{k}|xslip"] = np.where(stopped, (worst + lvl) / Us, 0.0)
    return pd.DataFrame(out)


def stats(x):
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 20:
        return dict(n=n)
    sd = x.std()
    srt = np.sort(x)
    es = lambda q: srt[: max(1, int(np.ceil(q * n)))].mean()
    return dict(n=n, mean=x.mean(), se=sd / np.sqrt(n), sd=sd, sharpe=x.mean() / sd if sd else np.nan,
                p1=np.quantile(x, 0.01), es1=es(0.01), es01=es(0.001), worst=x.min(),
                es_sd=es(0.01) / sd if sd else np.nan)


def spike_dir(sym):
    """+1 where the one-tick jumps are up (Boom, DEX UP), -1 where down (Crash, DEX DOWN), else 0."""
    if sym.startswith("Boom_") or (sym.startswith("DEX_") and "_UP" in sym):
        return 1.0
    if sym.startswith("Crash_") or (sym.startswith("DEX_") and "_DOWN" in sym):
        return -1.0
    return 0.0


def fill_of(fam):
    """Which fill a family is judged on: `spike` for the one-sided jump families, else the level."""
    return FILL if FILL in ("level", "x") else ("spike" if fam in SPIKY else "level")


def leg(g, pos, k, fill):
    """R (U, size 1), stopped?, slip (U) of one stop width under a fill model.

    level  bars.race: the level, or the open of a bar that gaps through it
    x      the extreme of the bar that took the stop - every stop treated as jumped
    spike  x only where the stop sits on the spike side (a short on Boom / DEX UP, a long on
           Crash / DEX DOWN): the side generators.md measured filling 10-19R past on ticks.
           The grind side is walked to, and there the level is the fill.
    """
    R, hit, slip = g[f"{pos}|{k}"].to_numpy(), g[f"{pos}|{k}|hit"].to_numpy(), g[f"{pos}|{k}|slip"].to_numpy()
    if fill == "level":
        return R, hit, slip
    Rx, sx = g[f"{pos}|{k}|x"].to_numpy(), g[f"{pos}|{k}|xslip"].to_numpy()
    if fill == "x":
        return Rx, hit, sx
    side = {"long": 1.0, "short": -1.0}.get(pos)
    side = g.mom.to_numpy() if side is None else side
    jumped = side * g.spike.to_numpy() < 0
    return np.where(jumped, Rx, R), hit, np.where(jumped, sx, slip)


def outcome(g, pos, rule, fill="level"):
    """Money (U at size 1) of each entry under a rule, and what it was: stopped, slip in R, size, high."""
    klo, khi, th, m = rule
    hi = g.pct.to_numpy() >= th
    size = np.where(hi, m / khi, 1 / klo)
    k = np.where(hi, khi, klo)
    (Rl, hl, sl), (Rh, hh, sh) = leg(g, pos, klo, fill), leg(g, pos, khi, fill)
    R, hit = np.where(hi, Rh, Rl), np.where(hi, hh, hl)
    slip = np.where(hi, sh, sl) / k   # in R of its own leg
    return size * (R - g.cost.to_numpy()), hit, slip, size, hi


def describe(g, pos, rule, fill="level"):
    x, hit, slip, size, hi = outcome(g, pos, rule, fill)
    s = stats(x)
    gaps = hit & (slip < -1e-9)
    s.update(stop=hit.mean(), gap=gaps.sum() / max(hit.sum(), 1), slip_mean=slip[hit].mean() if hit.any() else 0.0,
             slip_p1=np.quantile(slip[hit], 0.01) if hit.sum() >= 20 else np.nan,
             slip_worst=slip[hit].min() if hit.any() else 0.0, exposure=size.mean(), high=hi.mean(),
             risk=np.where(hi, rule[3], 1.0).mean())
    return s


def baseline(g, pos):
    return stats(g[f"{pos}|none"].to_numpy() - g.cost.to_numpy())


def label(rule):
    klo, khi, th, m = rule
    if klo == khi and m == 1.0:
        return f"{klo:g}U always"
    return f"{klo:g}U | {khi:g}U x{m:g} @>={th:g}"


def boot_diff(g, pos, a, b, metric, fill, B=300, seed=0):
    """Test-period difference metric(a) - metric(b), and its SE from a 40-block calendar bootstrap."""
    xa, xb = outcome(g, pos, a, fill)[0], outcome(g, pos, b, fill)[0]
    blocks = pd.qcut(g.time.rank(method="first"), 40, labels=False).to_numpy()
    groups = [np.flatnonzero(blocks == j) for j in range(40)]
    f = lambda x: stats(x)[metric]
    d0 = f(xa) - f(xb)
    rng = np.random.default_rng(seed)
    ds = []
    for _ in range(B):
        take = np.concatenate([groups[j] for j in rng.integers(0, 40, 40)])
        ds.append(f(xa[take]) - f(xb[take]))
    return d0, np.std(ds)


def states(g, pos, fill):
    """Per volatility state and stop width, at equal money at risk (size 1/k): what the stop does.

    tax  = mean(R_stop - R_nostop) / k: what the stop itself costs or earns against holding the
           same size without it, before spread. Zero on a martingale whatever k; negative means
           stops sell the low that then comes back.
    """
    hi = g.pct.to_numpy() >= 0.8
    none = g[f"{pos}|none"].to_numpy()
    c = g.cost.to_numpy()
    print(f"    by state (tr_percentile >= 0.8 or not), size 1/k, fill={fill}:")
    print(f"      {'state':<5} {'k':>4} {'n':>7} {'stop':>5} {'gap':>5} {'slip mean':>9} {'slip 1%':>8} {'worst':>7} "
          f"{'tax (R)':>15} {'cost':>6} {'ES1':>6} {'nostop ES1':>10}")
    for name, m in (("low", ~hi), ("high", hi)):
        for k in KS:
            R, hit, slip = (a[m] for a in leg(g, pos, k, fill))
            slip = slip / k
            lslip = g[f"{pos}|{k}|slip"].to_numpy()[m]
            tax = (R - none[m]) / k
            out = stats((R - c[m]) / k)
            nost = stats((none[m] - c[m]) / k)
            sl = slip[hit]
            print(f"      {name:<5} {k:>4g} {m.sum():>7,} {hit.mean():5.1%} {np.mean(lslip[hit] < -1e-9) if hit.any() else 0:5.1%} "
                  f"{sl.mean() if hit.any() else 0:+9.3f} {np.quantile(sl, .01) if len(sl) >= 20 else np.nan:+8.2f} "
                  f"{sl.min() if hit.any() else 0:+7.2f} {tax.mean():+7.3f} +-{tax.std() / np.sqrt(len(tax)):.3f} "
                  f"{np.mean(c[m]) / k:6.3f} {out.get('es1', np.nan):+6.2f} {nost.get('es1', np.nan):+10.2f}")


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    syms = sorted({p.name.split(".")[0] for p in SEQLAB.glob("*.npz")})
    R = rules()
    print(f"{len(R)} rules x {len(POSITIONS)} positions; criterion {CRITERION} (then mean); stage {STAGE}")
    rows = []
    for interval in INTERVALS:
        parts, skipped = [], []
        for s in syms:
            if family(s) is None or not (SEQLAB / f"{s}.{interval}.npz").exists():
                continue
            try:
                f = series(s, interval)
            except ValueError as e:
                skipped.append(str(e).split(" - ")[0])
                continue
            if f is not None:
                parts.append(f)
        d = pd.concat(parts, ignore_index=True)
        d["interval_"] = interval
        print(f"\n{'=' * 110}\n{interval}  H={H_FOR[interval]}  {d.sym.nunique()} series, {len(d):,} entries"
              f" ({(d.part == 0).sum():,} train)", flush=True)
        for s in skipped:
            print(f"  skipped (leak): {s}")
        periods = {"train": d.part == 0} if STAGE == "train" else \
            {"train": d.part == 0, "test": d.part > 0, "testA": d.part == 1, "testB": d.part == 2}
        for fam, gf in d.groupby("family"):
            fill = fill_of(fam)
            print(f"\n--- {interval} {fam}: {gf.sym.nunique()} series ({', '.join(sorted(gf.sym.unique()))}), "
                  f"{len(gf):,} entries, span {pd.to_datetime(gf.time.min(), unit='s'):%Y-%m-%d} .. "
                  f"{pd.to_datetime(gf.time.max(), unit='s'):%Y-%m-%d}, cost {gf.cost.median():.3f}U median, "
                  f"judged on fill={fill}", flush=True)
            for pos in POSITIONS:
                n0 = len(rows)
                for per, mask in periods.items():
                    g = gf[mask.loc[gf.index]]
                    rows.append(dict(interval=interval, family=fam, position=pos, period=per, fill=fill,
                                     rule="no stop x1", klo=np.inf, khi=np.inf, theta=np.nan, m=1.0, **baseline(g, pos)))
                    for rule in R:
                        rows.append(dict(interval=interval, family=fam, position=pos, period=per, fill=fill,
                                         rule=label(rule), klo=rule[0], khi=rule[1], theta=rule[2], m=rule[3],
                                         **describe(g, pos, rule, fill)))
                report(fam, pos, gf, pd.DataFrame(rows[n0:]), fill)
        pd.DataFrame(rows).to_csv(OUT, index=False)
        if SUMMARY:
            pd.DataFrame(SUMMARY).to_csv(OUT.with_name(OUT.stem + "_summary.csv"), index=False)
    print(f"\nwrote {OUT}")


GROUPS = {  # each compares rules that risk the same money, against the rule it would replace
    "A": ("any widths, equal money at risk (m=1)", lambda t: t.m == 1.0, FLAT),
    "C": ("1U normally, any width above theta, m=1", lambda t: (t.m == 1.0) & (t.klo == 1.0), FLAT),
    "B": ("production's risk (m=0.5 at 0.8), any widths", lambda t: (t.m == 0.5) & (t.theta == 0.8), PRODUCTION),
}


def pick(tr, by, group="A"):
    """The training winner among a group's stop rules: highest `by`, ties to the higher mean."""
    tr = tr[GROUPS[group][1](tr)]
    ok = tr[np.isfinite(tr.klo)].dropna(subset=[by])
    keys = [by, "mean"] if by != "mean" else ["mean", "es1"]
    b = ok.sort_values(keys, ascending=False).iloc[0]
    return (b.klo, b.khi, b.theta, b.m)


SUMMARY: list[dict] = []


def report(fam, pos, gf, t, fill):
    """The chosen rules against flat, production and the two widenings - test only if STAGE=all."""
    tr = t[t.period == "train"]
    best = {grp: pick(tr, CRITERION, grp) for grp in GROUPS}
    b_mean = pick(tr, "mean", "A")
    named = [("no stop x1", None), ("flat 1U", FLAT), ("production", PRODUCTION), ("widen 2U x.5", WIDEN),
             ("widen 2U x.25", WIDEN_HALF)] + [(f"{grp}: {label(r)}", r) for grp, r in best.items()] + \
            [(f"A by mean: {label(b_mean)}", b_mean)]
    show = "train" if STAGE == "train" else "test"
    g = gf[gf.part == 0] if STAGE == "train" else gf[gf.part > 0]
    # Jump and Range Break jump both ways: the level fill flatters them and the bar-extreme fill
    # damns them, so both bounds are shown.
    for fl in dict.fromkeys((fill, "level") + (("x",) if fam in ("jump", "range_break") else ())):
        print(f"  [{pos}] {show}, fill={fl}:  {'rule':<30} {'mean':>7} {'sd':>6} {'shrp':>6} {'p1':>6} {'ES1':>6} "
              f"{'ES.1':>6} {'worst':>7} {'stop':>5} {'gap':>5} {'slip1%':>6} {'expo':>5} {'risk':>5}")
        for name, rule in named:
            r = baseline(g, pos) if rule is None else describe(g, pos, rule, fl)
            extra = "" if rule is None else (f"{r['stop']:5.0%} {r['gap']:5.0%} {r['slip_p1']:+6.2f} "
                                             f"{r['exposure']:5.2f} {r['risk']:5.2f}")
            print(f"         {name:<44} {r['mean']:+7.3f} {r['sd']:6.2f} {r['sharpe']:+6.3f} {r['p1']:+6.2f} "
                  f"{r['es1']:+6.2f} {r['es01']:+6.2f} {r['worst']:+7.2f} {extra}")
    if STAGE == "train" and pos != "momentum":
        states(g, pos, fill)
    if STAGE == "train":
        return
    states(g, pos, fill)
    for bname, brule in list(best.items()) + [("A by mean", b_mean)]:
        vs_name, vs = ("prod", PRODUCTION) if bname == "B" else ("flat", FLAT)
        for metric in ("es1", "mean", "sharpe"):
            d0, se = boot_diff(g, pos, brule, vs, metric, fill)
            halves = [stats(outcome(g[g.part == p], pos, brule, fill)[0])[metric]
                      - stats(outcome(g[g.part == p], pos, vs, fill)[0])[metric] for p in (1, 2)]
            SUMMARY.append(dict(interval=g.interval_.iloc[0], family=fam, position=pos, group=bname, rule=label(brule),
                                vs=vs_name, metric=metric, rule_value=stats(outcome(g, pos, brule, fill)[0])[metric],
                                vs_value=stats(outcome(g, pos, vs, fill)[0])[metric], diff=d0, se=se,
                                half_a=halves[0], half_b=halves[1]))
            print(f"    {bname:<9} - {vs_name}, {metric:<6}: {d0:+.3f} +- {se:.3f} (t {d0 / se if se else np.nan:+.1f}; "
                  f"A {halves[0]:+.3f} B {halves[1]:+.3f})")
    for vname, v, ref, rname in (("widen 2U x.5", WIDEN, FLAT, "flat"), ("widen 2U x.25", WIDEN_HALF, PRODUCTION, "production"),
                                 ("production", PRODUCTION, FLAT, "flat")):
        for metric in ("es1", "mean"):
            d0, se = boot_diff(g, pos, v, ref, metric, fill)
            halves = [stats(outcome(g[g.part == p], pos, v, fill)[0])[metric]
                      - stats(outcome(g[g.part == p], pos, ref, fill)[0])[metric] for p in (1, 2)]
            SUMMARY.append(dict(interval=g.interval_.iloc[0], family=fam, position=pos, group=vname, rule=label(v),
                                vs=rname, metric=metric, rule_value=stats(outcome(g, pos, v, fill)[0])[metric],
                                vs_value=stats(outcome(g, pos, ref, fill)[0])[metric], diff=d0, se=se,
                                half_a=halves[0], half_b=halves[1]))
            print(f"    {vname} - {rname}, {metric:<5}: {d0:+.3f} +- {se:.3f} (t {d0 / se if se else np.nan:+.1f})")


if __name__ == "__main__":
    main()
