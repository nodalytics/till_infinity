"""Does the width estimator recover a width it is given?

[quantising.md](../quantising.md) measures Range Break's range directly off the
feed - `W = sqrt(12 Var)` on within-episode ticks, de-meaned per episode, scanned
against a minimum episode length - and reads **RB100 at about 38 units, RB200
above 60 and not converged**. [rebuilding.md](../rebuilding.md) fits a simulated
variance-ratio curve to `deriving.md`'s published table and gets **one shared
width of 60**. Those cannot both be right, and the disagreement is worth more
than either number until it is resolved.

The two pages agree on what would settle it, and neither had run it: **give both
estimators the same simulated truth, at the feed's own sample, and see which one
comes back with the width it was given.** That is all this harness does.

## What is compared

For each true width `W`, simulate Range Break 100 at the published break rate
(86.6 minutes) and the fitted jump, at the feed's own tick count and again at
twenty times it, and read:

* **the direct estimator** - `sqrt(12 x mean within-episode variance)` and the
  mean within-episode range, over the same cuts on minimum episode length and
  the same "largest cut retaining five episodes" saturation rule;
* **the curve estimator** - the ex-break (`splice`) variance-ratio curve, scored
  against `deriving.md`'s published six numbers and against its two short lags
  alone, which is the scoring [rebuilding.md](../rebuilding.md) ends on.

## What would count as failure, written before any number was looked at

1. **The direct estimator is biased** if `W_hat` at the feed's own sample misses
   the true `W` by more than 5% at the saturated cut. The feed's measured 38 then
   does not mean the range is 38 wide, and the size of the bias says what it does
   mean.
2. **The curve estimator is unidentified** if two widths a factor of 1.5 apart
   score within one Monte Carlo standard deviation of each other on the published
   curve. A best-fit width from an unidentified curve is not a measurement.
3. **The run is void** if the two estimators applied to the *same* simulated
   truth disagree by less at 20x the sample than at 1x - that would make the
   disagreement Monte Carlo noise rather than bias, and nothing here would be
   about the feed.
4. **The run is void** if the episode detector fires at a rate the simulation was
   not given. Both estimators run twice, once on the true break points and once
   on the same detector the feed is read with, and a detector that changes the
   answer is reported rather than chosen between.
5. **Neither page wins by default.** If the direct estimator is unbiased, the
   fitted 60 is refuted and is corrected. If it is biased low by the amount the
   feed's 38 needs, the fitted 60 survives *and the bias is the finding*.
"""

from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuildgen as G
import rebuildstep as S

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/rebuildwidth.json"))
SEED = int(os.environ.get("SEED", "20260912"))
SEEDS = int(os.environ.get("SEEDS", "6"))
WIDTHS = tuple(int(w) for w in os.environ.get("WIDTHS", "30,38,45,52,60,72").split(","))
#: the cuts quantising.md scans, and its saturation rule
CUTS = (240, 512, 1024, 2048, 4096, 8192, 16384)
MIN_EPS = 5
#: Range Break 100, as published: 86.6 minutes a break at 60 ticks a minute, and
#: the break jump rebuilding.md fitted. Neither is at issue here.
MBT = 86.6 * S.TPB
JUMP = 130.0
FEED_TICKS = 86_400


def width_scan(px: np.ndarray, brk_idx: np.ndarray, step: float = 1.0) -> dict:
    """`quantising.md`'s estimator, reimplemented from its description.

    Episodes are the runs of ticks between breaks, each de-meaned by its own
    sample mean; the width is `sqrt(12 Var)` because a reflecting box has a
    uniform stationary law, and the mean within-episode range is the same number
    seen a second way.
    """
    edges = np.concatenate([[0], brk_idx, [px.size]])
    eps = [px[edges[i]: edges[i + 1]] for i in range(edges.size - 1)]
    eps = [e for e in eps if e.size >= 2]
    scan = []
    for cut in CUTS:
        js = [e for e in eps if e.size >= cut]
        if not js:
            continue
        scan.append({"cut": cut, "n_episodes": len(js),
                     "n_ticks": int(sum(e.size for e in js)),
                     "w_var": math.sqrt(12.0 * float(np.mean([e.var() for e in js]))) / step,
                     "w_range": float(np.mean([np.ptp(e) for e in js])) / step})
    sat = [r for r in scan if r["n_episodes"] >= MIN_EPS]
    return {"scan": scan, "n_episodes": len(eps),
            "mean_episode": float(np.mean([e.size for e in eps])) if eps else 0.0,
            "w_sat": sat[-1]["w_var"] if sat else float("nan"),
            "w_sat_range": sat[-1]["w_range"] if sat else float("nan"),
            "sat_cut": sat[-1]["cut"] if sat else 0,
            "sat_eps": sat[-1]["n_episodes"] if sat else 0}


def simulate(width: int, n_ticks: int, seed: int) -> dict:
    """One Range Break path, with the true break points kept."""
    rng = np.random.default_rng([seed, width])
    stream = G.gen_rangebreak(n_ticks, 1.0, width, MBT, 0.0, 5000.0, rng,
                              jump_pool=np.array([JUMP]), anchor="edge")
    px = np.concatenate(list(stream))[:n_ticks]
    # the true breaks: a step larger than any in-range move can be
    d = np.abs(np.diff(px))
    true_brk = np.flatnonzero(d > 2.0) + 1
    bars = G.bars_from_stream(iter([px]), S.TPB, n_ticks // S.TPB)
    det = np.flatnonzero(S.break_bars(bars, 1.0)) * S.TPB
    return {"px": px, "bars": bars, "true": true_brk, "detected": det}


def curve_err(bars: dict) -> dict:
    """The ex-break variance-ratio curve, and its distance from the published one."""
    cur = S.vr_curves(bars, 1.0)
    tgt = S.PUBLISHED_VR["range_break_100_index"]["splice"]
    err = {n: cur["splice"][n] - tgt[n] for n in S.VR_N}
    short = [abs(err[n]) for n in (1, 5)]
    return {"splice": {n: cur["splice"][n] for n in S.VR_N},
            "mae": float(np.mean([abs(v) for v in err.values()])),
            "mae_short": float(np.mean(short))}


def main() -> None:
    print("=" * 118)
    print("DOES THE WIDTH ESTIMATOR RECOVER A WIDTH IT IS GIVEN?")
    print(f"  seed {SEED}   {SEEDS} paths a width   break every {MBT:.0f} ticks   "
          f"jump {JUMP:.0f}   {G.machine()}")
    print("=" * 118)
    ledger: list[dict] = []
    payload: dict = {"widths": list(WIDTHS), "seeds": SEEDS}

    print("\n[1] THE DIRECT ESTIMATOR, ON A TRUTH IT WAS GIVEN")
    print("    `quantising.md`'s scan, run on simulated Range Break paths of known")
    print("    width at the feed's own tick count. The saturation rule is its own:")
    print("    the largest cut still retaining five episodes.")
    print(f"    {'true W':>7s} {'sample':>8s} {'eps':>5s} {'mean ep':>8s} {'sat cut':>8s} "
          f"{'sat eps':>8s} {'W(var)':>17s} {'W(range)':>17s} {'bias':>8s}")
    direct = {}
    for label, nt in (("feed 1x", FEED_TICKS), ("20x", 20 * FEED_TICKS)):
        for w in WIDTHS:
            got, gotr, neps, mep, cut, seps = [], [], [], [], [], []
            for s in range(SEEDS):
                sim = simulate(w, nt, SEED + s)
                r = width_scan(sim["px"], sim["true"])
                got.append(r["w_sat"])
                gotr.append(r["w_sat_range"])
                neps.append(r["n_episodes"])
                mep.append(r["mean_episode"])
                cut.append(r["sat_cut"])
                seps.append(r["sat_eps"])
            m, sd = float(np.nanmean(got)), float(np.nanstd(got))
            mr = float(np.nanmean(gotr))
            bias = m / w - 1.0
            print(f"    {w:7d} {label:>8s} {np.mean(neps):5.1f} {np.mean(mep):8.0f} "
                  f"{np.mean(cut):8.0f} {np.mean(seps):8.1f} "
                  f"{m:9.1f} +-{sd:5.1f} {mr:17.1f} {bias:+8.1%}")
            direct[f"{label}/{w}"] = {"w_var": m, "sd": sd, "w_range": mr, "bias": bias}
            if label == "feed 1x":
                ledger.append({"test": "the direct estimator is within 5% of the width "
                                       "it was given", "feed": f"W={w}",
                               "value": bias, "fired": abs(bias) > 0.05})
    payload["direct"] = direct

    print("\n[2] THE SAME, WITH THE EPISODES CUT BY THE DETECTOR RATHER THAN THE TRUTH")
    print("    A detector that misses a break glues two episodes together and inflates")
    print("    the width; one that fires on nothing splits an episode and deflates it.")
    print(f"    {'true W':>7s} {'true eps':>9s} {'det eps':>8s} {'W(true cuts)':>13s} "
          f"{'W(det cuts)':>12s}")
    for w in WIDTHS:
        a, b, na, nb = [], [], [], []
        for s in range(SEEDS):
            sim = simulate(w, FEED_TICKS, SEED + s)
            a.append(width_scan(sim["px"], sim["true"])["w_sat"])
            b.append(width_scan(sim["px"], sim["detected"])["w_sat"])
            na.append(sim["true"].size)
            nb.append(sim["detected"].size)
        print(f"    {w:7d} {np.mean(na):9.1f} {np.mean(nb):8.1f} "
              f"{np.nanmean(a):13.1f} {np.nanmean(b):12.1f}")
        ledger.append({"test": "the break detector does not move the width",
                       "feed": f"W={w}",
                       "value": float(np.nanmean(b) / max(np.nanmean(a), 1e-9) - 1),
                       "fired": abs(np.nanmean(b) / max(np.nanmean(a), 1e-9) - 1) > 0.1})

    print("\n[3] THE CURVE ESTIMATOR, ON THE SAME TRUTHS")
    print("    The ex-break variance ratio against `deriving.md`'s published six")
    print("    numbers, and against its two short lags alone - the scoring")
    print("    `rebuilding.md` ends on, after `quantising.md` showed the long lags")
    print("    are the splice rather than the process.")
    print(f"    {'true W':>7s} {'n=1':>7s} {'n=5':>7s} {'n=20':>7s} {'n=100':>7s} "
          f"{'MAE all 6':>11s} {'MAE short':>11s}")
    tgt = S.PUBLISHED_VR["range_break_100_index"]["splice"]
    print(f"    {'PUBLISHED':>7s} {tgt[1]:7.3f} {tgt[5]:7.3f} {tgt[20]:7.3f} "
          f"{tgt[100]:7.3f}")
    curve = {}
    for w in WIDTHS:
        rows = [curve_err(simulate(w, 20 * FEED_TICKS, SEED + s)["bars"])
                for s in range(SEEDS)]
        sp = {n: float(np.mean([r["splice"][n] for r in rows])) for n in S.VR_N}
        mae = float(np.mean([r["mae"] for r in rows]))
        mshort = float(np.mean([r["mae_short"] for r in rows]))
        sd_short = float(np.std([r["mae_short"] for r in rows]))
        print(f"    {w:7d} {sp[1]:7.3f} {sp[5]:7.3f} {sp[20]:7.3f} {sp[100]:7.3f} "
              f"{mae:11.4f} {mshort:8.4f} +-{sd_short:.4f}")
        curve[w] = {"splice": sp, "mae": mae, "mae_short": mshort, "sd_short": sd_short}
    payload["curve"] = curve
    best = min(curve, key=lambda w: curve[w]["mae_short"])
    rival = sorted(curve, key=lambda w: curve[w]["mae_short"])[1]
    sep = abs(curve[best]["mae_short"] - curve[rival]["mae_short"]) / \
        max(curve[best]["sd_short"], 1e-9)
    print(f"\n    best on the short lags: W = {best}, next {rival}, separated by "
          f"{sep:.1f} Monte Carlo sd")
    ledger.append({"test": "the curve identifies the width", "feed": "RB100",
                   "value": sep, "fired": sep < 1.0})

    print("\n[4] THE TWO ESTIMATORS ON THE SAME TRUTH")
    print("    What the direct estimator reads off a path whose width the curve")
    print("    estimator likes, and vice versa. If the feed's measured 38 is what a")
    print("    true 60 reads, the two pages are not in disagreement at all.")
    print(f"    {'true W':>7s} {'direct W at 1x':>15s} {'curve MAE short':>16s} "
          f"{'reads as the feed?':>19s}")
    for w in WIDTHS:
        d = direct[f"feed 1x/{w}"]["w_var"]
        print(f"    {w:7d} {d:15.1f} {curve[w]['mae_short']:16.4f} "
              f"{'yes' if abs(d - 38.0) < 3.0 else '':>19s}")
    payload["ledger"] = ledger

    print("\n[5] THE FAILURE LEDGER")
    by: dict[str, list] = {}
    for e in ledger:
        by.setdefault(e["test"], []).append(e)
    print(f"{'condition':56s} {'cells':>6s} {'fired':>6s} {'worst cell':>26s}")
    nf = 0
    for name, es in sorted(by.items()):
        hit = [e for e in es if e["fired"]]
        nf += len(hit)
        worst = max(es, key=lambda e: abs(e.get("value") or 0))
        print(f"{name:56s} {len(es):6d} {len(hit):6d} "
              f"{str(worst['feed'])[:16] + ' ' + format(worst['value'], '.4g'):>26s}")
    print(f"\n    {len(ledger)} pre-registered comparisons, {nf} fired.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(json.loads(json.dumps(payload, default=float)), fh, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
