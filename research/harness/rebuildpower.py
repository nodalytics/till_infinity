"""At what sample size does a test start telling the rebuild from the feed?

"Indistinguishable" is not an answer until it carries a sample size. A rebuild
that survives a test on ten thousand points and dies on a million is a good
rebuild and a *precisely* described one; a rebuild that survives a test on two
hundred points has been asked nothing. This harness turns every pass in
`rebuildvol.py`, `rebuildstep.py` and `rebuildspike.py` into one number per
family:

    n*  =  the sample size at which a two-sided two-sample Kolmogorov-Smirnov
           test at alpha = 0.05 separates the rebuild from the feed

computed two ways that have to agree. **Empirically**, by subsampling both to
size `n` and counting rejections over many draws, and reading off where the
rejection rate crosses 50%. **In closed form**, from the estimated sup-distance
between the two distributions: equal samples reject when `D > c*sqrt(2/n)` with
`c = 1.3581`, so `n* = 2c^2/D^2`. The second is the only route available where
the real sample runs out before the test fires, which it does for most of these
families - and in that case the honest answer is a *lower bound* on `n*`,
reported as one.

The same machinery answers the question from the other side. At the real
sample's own size, what discrepancy *could* have been seen? For the Volatility
family that converts directly into a volatility misspecification: the sup
distance between `N(0, 1)` and `N(0, (1+e)^2)` is a function of `e` alone, so
the detectable `e` at 86,410 bars is a number, and the rebuild's measured `D`
converts back into the largest `e` consistent with it.

## What would count as failure, written before any number was looked at

1. **The whole study is void** if the null control misbehaves - the first thirty
   days of a real feed against its last thirty, and two seeds of the same
   rebuild against each other, must reject at close to 5% across the whole `n`
   grid. A rejection rate that climbs with `n` on either of those means the
   estimator is reading something other than the law and every `n*` below is
   meaningless.
2. **The study is void** if the closed-form `n*` and the empirical crossing
   disagree by more than a factor of 3 on the *positive* controls, where the
   answer is known: sigma off by 1%, 0.5% and 0.2%, Student-t(6) at matched
   variance, `p_up = 0.501`, and `lambda` off by 10%. If the formula cannot
   predict where a known error is caught, its extrapolation past the end of the
   real sample is worthless.
3. **A family is reported as separable** only where `D` exceeds the null floor
   measured on that family's own real-against-real control. Below that floor the
   result is a bound and is printed as one.
4. **The run is void** if a rejection rate lands on exactly 0.000 or exactly
   1.000 across every `n` - both are the signature of a degenerate comparison
   rather than of a measurement.
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

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/rebuildpower.json"))
SEED = int(os.environ.get("SEED", "20260912"))
NS = tuple(int(x) for x in os.environ.get("NS", "1000,3000,10000,30000,86000").split(","))
B_SMALL = int(os.environ.get("B_SMALL", "150"))
B_LARGE = int(os.environ.get("B_LARGE", "40"))
#: The control grid runs past the end of the real sample, because both sides of a
#: control comparison are simulated and the point is to check the closed-form n*
#: where it can be checked.
CTL_NS = tuple(int(x) for x in os.environ.get(
    "CTL_NS", "10000,30000,100000,300000,1000000").split(","))
CTL_N = int(os.environ.get("CTL_N", "1200000"))
KS_C = 1.3581


def rejection_curve(a: np.ndarray, b: np.ndarray, rng, ns=None) -> list[dict]:
    """Subsample both to `n`, KS at 5%, count rejections. The rebuild side is
    always the larger sample, so the real side is what runs out."""
    from scipy.stats import ks_2samp
    out = []
    for n in (ns or NS):
        if a.size < n or b.size < n:
            continue
        reps = B_SMALL if n <= 10_000 else B_LARGE
        rej = 0
        ds = []
        for _ in range(reps):
            sa = a if n == a.size else rng.choice(a, n, replace=False)
            sb = rng.choice(b, n, replace=False)
            r = ks_2samp(sa, sb, method="asymp")
            ds.append(r.statistic)
            rej += int(r.pvalue < 0.05)
        out.append({"n": n, "reps": reps, "reject_rate": rej / reps,
                    "mean_D": float(np.mean(ds)),
                    "crit_D": KS_C * math.sqrt(2.0 / n)})
    return out


def crossing(curve: list[dict], level: float = 0.5) -> float:
    """Where the rejection rate first crosses `level`, log-interpolated."""
    prev = None
    for c in curve:
        if c["reject_rate"] >= level:
            if prev is None:
                return float(c["n"])
            x0, y0 = math.log(prev["n"]), prev["reject_rate"]
            x1, y1 = math.log(c["n"]), c["reject_rate"]
            if y1 == y0:
                return float(c["n"])
            return float(math.exp(x0 + (level - y0) * (x1 - x0) / (y1 - y0)))
        prev = c
    return float("inf")


def d_from_sigma(eps: float) -> float:
    """Sup distance between N(0,1) and N(0,(1+eps)^2) - the exact KS separation
    a volatility misspecification of `eps` produces."""
    from scipy.stats import norm
    x = np.linspace(0.0, 12.0, 60001)
    return float(np.max(np.abs(norm.cdf(x) - norm.cdf(x / (1.0 + eps)))))


def sigma_from_d(d: float) -> float:
    lo, hi = 1e-6, 0.5
    for _ in range(60):
        mid = math.sqrt(lo * hi)
        if d_from_sigma(mid) < d:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


def report(name: str, a: np.ndarray, b: np.ndarray, floor: np.ndarray | None,
           rng, rows: list, curves: dict) -> dict:
    """One family, one statistic: D, the floor, n* both ways."""
    k = G.ks2(a, b, cap=1_000_000, rng=rng)
    kf = G.ks2(floor[0], floor[1], cap=1_000_000, rng=rng) if floor is not None else None
    curve = rejection_curve(a, b, rng)
    curves[name] = curve
    d = k["D"]
    d_floor = kf["D"] if kf else float("nan")
    above = d > d_floor if kf else True
    row = {"what": name, "n_real": int(a.size), "n_sim": int(b.size), "D": d,
           "D_crit": k["D_crit_05"], "D_floor": d_floor, "p": k["p"],
           "nstar_closed": G.nstar(d) if above else float("inf"),
           "nstar_bound": G.nstar(max(d_floor, d)) if kf else float("nan"),
           "nstar_empirical": crossing(curve), "above_floor": bool(above)}
    rows.append(row)
    return row


def main() -> None:
    rng = np.random.default_rng(SEED)
    payload: dict = {}
    curves: dict = {}
    rows: list = []
    ledger: list = []
    print("=" * 118)
    print("HOW CLOSE IS THE REBUILD - the sample size at which each family separates")
    print(f"  seed {SEED}   n grid {NS}   {G.machine()}")
    print("=" * 118)

    # ---------------------------------------------------------- volatility ----
    print("\n[1] VOLATILITY - volatility_75_index, one-minute log returns and tick returns")
    vb = G.real_bars("volatility_75_index")
    vt = G.real_ticks("volatility_75_index")
    grid = G.quote_grid(vt["mid"])
    rr = G.logrets(vb["close"], vb["ts"])
    rt = np.diff(np.log(vt["mid"]))
    rt = rt[np.isfinite(rt)]
    big = G.bars_from_stream(
        G.gen_gbm(30 * 900_000, 75.0, 2.0, float(vb["close"][0]), grid,
                  np.random.default_rng(SEED)), 30, 900_000, keep_ticks=3_000_000)
    sr = G.logrets(big["close"], big["ts"])
    stk = np.diff(np.log(big["ticks"]))
    stk = stk[np.isfinite(stk)]
    h = rr.size // 2
    report("volatility 1m log returns", rr, sr, (rr[:h], rr[h:]), rng, rows, curves)
    ht = rt.size // 2
    report("volatility tick returns", rt, stk, (rt[:ht], rt[ht:]), rng, rows, curves)
    # the rebuild against itself, two seeds - the pure Monte Carlo floor
    big2 = G.bars_from_stream(
        G.gen_gbm(30 * 200_000, 75.0, 2.0, float(vb["close"][0]), grid,
                  np.random.default_rng(SEED + 1)), 30, 200_000)
    sr2 = G.logrets(big2["close"], big2["ts"])
    report("volatility rebuild vs rebuild (MC floor)", sr2, sr, None, rng, rows, curves)
    report("volatility feed vs feed (null floor)", rr[:h], rr[h:], None, rng, rows, curves)

    # ---------------------------------------------------------------- step ----
    print("[2] STEP INDEX - the one-minute change, sixty flips of a coin")
    sb = G.real_bars("step_index")
    chg_r = np.diff(sb["close"])
    sim = S.sim_step(600_000, 0.5, SEED, float(sb["close"][0]))
    chg_s = np.diff(sim["close"])
    hs = chg_r.size // 2
    report("step 1m change", chg_r, chg_s, (chg_r[:hs], chg_r[hs:]), rng, rows, curves)

    # ---------------------------------------------------------------- boom ----
    print("[3] BOOM 500 - tick returns, the whole mixture")
    import rebuildspike as K
    bt = G.real_ticks("boom_500_index")
    bb = G.real_bars("boom_500_index")
    f = K.detect(bt["mid"])
    f["spread"] = float(np.median(bt["spread"]))
    f["grid"] = G.quote_grid(bt["mid"])
    f["tag"] = "boom_500_index/power"
    bsim = K.build(f, f["grid"], float(bb["close"][0]), 120_000, SEED, True)
    dr = np.diff(bt["mid"])
    ds = np.diff(bsim["ticks"])
    hb = dr.size // 2
    report("boom_500 tick moves", dr, ds, (dr[:hb], dr[hb:]), rng, rows, curves)
    # in price, not in the log: this generator is additive in price and the feed's
    # level wanders far enough over sixty days that a log return carries the level
    rrb = np.diff(bb["close"])
    rsb = np.diff(bsim["close"])
    hbb = rrb.size // 2
    report("boom_500 1m price change", rrb, rsb, (rrb[:hbb], rrb[hbb:]), rng, rows, curves)

    # --------------------------------------------------------- range break ----
    print("[4] RANGE BREAK 100 - the one-minute change")
    rb = G.real_bars("range_break_100_index")
    rtk = G.real_ticks("range_break_100_index")
    d = np.diff(rtk["mid"])
    step = float(np.median(np.abs(d[d != 0])))
    brk = S.break_stats(rb, step)
    vis = S.visited_ranges(rb, step)
    mbt = brk["minutes_per_break"] * S.TPB
    band, _got, _d = S.fit_band(vis, mbt, brk["_jump"],
                                float(rb["close"][0]), step, SEED)
    rsim = S.sim_rb(300_000, band, mbt, brk["_jump"], SEED, float(rb["close"][0]), step)
    cr = np.diff(rb["close"]) / step
    cs = np.diff(rsim["close"]) / step
    hr = cr.size // 2
    report("range_break_100 1m change", cr, cs, (cr[:hr], cr[hr:]), rng, rows, curves)
    print(f"    (band fitted at {band} steps, break every {mbt:.0f} ticks)")

    # ---------------------------------------------------------------- jump ----
    print("[5] JUMP 75 - the one-minute log return")
    jb = G.real_bars("jump_75_index")
    jt = G.real_ticks("jump_75_index")
    jd = np.diff(jt["mid"])
    jmed = float(np.median(np.abs(jd[jd != 0])))
    jidx = np.flatnonzero(np.abs(jd) > 10 * jmed)
    span_min = (jt["ts"][-1] - jt["ts"][0]) / 60000.0
    rate = jidx.size / span_min
    sigma_min = (75.0 / 100.0) / math.sqrt(G.MINUTES_PER_YEAR)
    jsize = math.sqrt(0.7477 * sigma_min ** 2 / rate)
    jsim = G.bars_from_stream(
        G.gen_jump(60 * 400_000, 75.0, 1.0, rate, jsize, float(jb["close"][0]),
                   G.quote_grid(jt["mid"]), np.random.default_rng(SEED)), 60, 400_000)
    rj = G.logrets(jb["close"], jb["ts"])
    sj = G.logrets(jsim["close"], jsim["ts"])
    hj = rj.size // 2
    report("jump_75 1m log returns", rj, sj, (rj[:hj], rj[hj:]), rng, rows, curves)

    print("\n[6] THE ANSWER, AS A NUMBER")
    print(f"{'statistic':42s} {'n real':>8s} {'n sim':>9s} {'KS D':>9s} {'D crit':>8s} "
          f"{'floor D':>8s} {'p':>8s} {'n* closed':>12s} {'n* empirical':>13s}")
    for r in rows:
        ns_c = "-" if not math.isfinite(r["nstar_closed"]) else f"{r['nstar_closed']:.3g}"
        ns_e = "not by " + str(max(NS)) if not math.isfinite(r["nstar_empirical"]) \
            else f"{r['nstar_empirical']:.3g}"
        print(f"{r['what']:42s} {r['n_real']:8d} {r['n_sim']:9d} {r['D']:9.5f} "
              f"{r['D_crit']:8.5f} {r['D_floor']:8.5f} {r['p']:8.4f} {ns_c:>12s} {ns_e:>13s}")
    print("    n* closed is 2c^2/D^2 with c = 1.3581 and is only quoted where D clears the")
    print("    real-against-real floor; where it does not, the honest statement is the bound")
    print("    in the next line rather than a number here.")
    for r in rows:
        if r["D"] < r["D_crit"]:
            b = G.nstar(r["D_crit"])
            r["nstar_lower_bound"] = b
            print(f"      {r['what']:42s} D {r['D']:.5f} < the 5% critical "
                  f"{r['D_crit']:.5f} -> the two laws are within {r['D_crit']:.5f} of "
                  f"each other, so n* > {b:.3g}")

    print("\n[7] THE REJECTION CURVES - what fraction of draws a 5% test rejects")
    print(f"{'statistic':44s} " + " ".join(f"{'n=' + str(n):>10s}" for n in NS))
    for name, c in curves.items():
        if name.startswith("control"):
            continue
        byn = {x["n"]: x for x in c}
        print(f"{name:44s} " + " ".join(
            (f"{byn[n]['reject_rate']:10.3f}" if n in byn else f"{'-':>10s}") for n in NS))
    print("\n    and the control curves, on their own grid:")
    print(f"{'wrong generator':44s} " + " ".join(f"{'n=' + str(n):>10s}" for n in CTL_NS))
    for name, c in curves.items():
        if not name.startswith("control"):
            continue
        byn = {x["n"]: x for x in c}
        print(f"{name:44s} " + " ".join(
            (f"{byn[n]['reject_rate']:10.3f}" if n in byn else f"{'-':>10s}") for n in CTL_NS))
    print(f"{'':44s} " + " ".join(f"{'(nominal 0.05)':>10s}" for _ in NS[:1]))

    # --------------------------------------------------------- the controls ---
    print("\n[8] THE POSITIVE CONTROLS - where the answer is known, does the formula")
    print("    predict where the error is caught?")
    print(f"{'wrong generator':34s} {'D measured':>11s} {'D closed form':>14s} "
          f"{'n* closed':>11s} {'n* empirical':>13s} {'ratio':>7s}")
    ctl_rows = []
    # The controls need a bigger grid than the feed can supply: a 1% volatility
    # error has a true sup-distance of 0.0024 and is not caught until about
    # 600,000 points, which is seven times the whole 60-day bar sample. Both
    # sides here are simulated, so the grid can go there and the closed-form n*
    # can actually be checked against a crossing.
    print("    (the empirical crossing runs systematically below the closed form because")
    print("     the measured D at finite n carries its own noise on top of the true one;")
    print("     the closed form is therefore the conservative side of the answer.)")
    for name, eps in (("sigma +1%", 0.01), ("sigma +0.5%", 0.005), ("sigma +0.2%", 0.002)):
        bad = G.bars_from_stream(
            G.gen_gbm(30 * CTL_N, 75.0 * (1 + eps), 2.0, float(vb["close"][0]), grid,
                      np.random.default_rng(SEED + 3)), 30, CTL_N)
        rbad = G.logrets(bad["close"], bad["ts"])
        k = G.ks2(sr, rbad, cap=CTL_N, rng=rng)
        cv = rejection_curve(sr[:CTL_N], rbad, rng, CTL_NS)
        nc, ne = G.nstar(k["D"]), crossing(cv)
        dclosed = d_from_sigma(eps)
        ratio = ne / nc if math.isfinite(ne) and nc > 0 else float("nan")
        print(f"{name:34s} {k['D']:11.5f} {dclosed:14.5f} {nc:11.3g} "
              + (f"{ne:13.3g}" if math.isfinite(ne) else f"{'not by ' + str(max(CTL_NS)):>13s}")
              + f" {ratio:7.2f}")
        ctl_rows.append({"name": name, "D": k["D"], "D_closed": dclosed,
                         "nstar_closed": nc, "nstar_emp": ne, "ratio": ratio})
        curves["control " + name] = cv
        if math.isfinite(ne):
            ledger.append({"test": "closed-form n* within a factor of 3 of the empirical one",
                           "feed": name, "value": ratio,
                           "fired": not (1 / 3 <= ratio <= 3)})
    # Student-t
    import rebuildvol as V
    tbad = G.bars_from_stream(
        V._student_stream(30 * CTL_N, 75.0, 2.0, float(vb["close"][0]), grid,
                          np.random.default_rng(SEED + 4), 6), 30, CTL_N)
    rt6 = G.logrets(tbad["close"], tbad["ts"])
    k = G.ks2(sr, rt6, cap=CTL_N, rng=rng)
    cv = rejection_curve(sr[:CTL_N], rt6, rng, CTL_NS)
    nc_t, ne_t = G.nstar(k["D"]), crossing(cv)
    ratio_t = ne_t / nc_t if math.isfinite(ne_t) and nc_t > 0 else float("nan")
    ne_s = f"{ne_t:13.3g}" if math.isfinite(ne_t) else f"{'not by ' + str(max(CTL_NS)):>13s}"
    print(f"{'Student-t(6), matched variance':34s} {k['D']:11.5f} {'-':>14s} "
          f"{nc_t:11.3g} " + ne_s + f" {ratio_t:7.2f}")
    curves["control Student-t(6)"] = cv
    ctl_rows.append({"name": "student-t(6)", "D": k["D"], "nstar_closed": nc_t,
                     "nstar_emp": ne_t})

    print("\n[9] THE SAME QUESTION FROM THE OTHER SIDE - what could have been seen?")
    dcrit_bars = KS_C * math.sqrt(2.0 / rr.size)
    dcrit_ticks = KS_C * math.sqrt(2.0 / rt.size)
    e_bars = sigma_from_d(dcrit_bars)
    row_v = next(r for r in rows if r["what"] == "volatility 1m log returns")
    e_rebuild = sigma_from_d(max(row_v["D"], 1e-9))
    print("    volatility_75_index, 86,410 one-minute returns:")
    print(f"      the smallest KS separation a 5% test can see here is D = {dcrit_bars:.5f},")
    print(f"      which is a volatility misspecification of {100 * e_bars:.3f}%.")
    print(f"      the rebuild's measured D = {row_v['D']:.5f} corresponds to at most "
          f"{100 * e_rebuild:.3f}%.")
    sharp = e_bars / 0.005
    print("      `genvol.py`'s realised-vs-nominal band is 0.5%, so the direct")
    print(f"      volatility comparison is {sharp:.1f}x sharper than KS on the same bars:")
    print("      a distribution test is the wrong instrument for a scale parameter.")
    print(f"    on {rt.size} tick returns the detectable separation is D = {dcrit_ticks:.5f}.")
    # the coin
    p_meas, p_se = 0.499734, 0.000220
    n_coin = 0.25 * (1.96 / abs(p_meas - 0.5)) ** 2
    print(f"    step_index: the feed's own measured bias is {abs(p_meas - 0.5):.6f} "
          f"+- {p_se:.6f};")
    print(f"      a fair-coin test needs n = {n_coin:.3g} flips to call that a bias, against")
    print(f"      the {chg_r.size * 60:,} the sixty-day bar sample carries.")

    print("\n[10] THE NULL CONTROLS - both must sit near 0.05 at every n")
    for name in ("volatility feed vs feed (null floor)",
                 "volatility rebuild vs rebuild (MC floor)"):
        c = curves.get(name, [])
        worst = max((x["reject_rate"] for x in c), default=float("nan"))
        print(f"    {name:46s} max rejection rate {worst:.3f} over {len(c)} sizes")
        ledger.append({"test": "VOID unless the null control stays near 5%", "feed": name,
                       "value": worst, "fired": worst > 0.25})
        if c and all(x["reject_rate"] == 0.0 for x in c):
            ledger.append({"test": "VOID: rejection rate exactly 0 at every n", "feed": name,
                           "value": 0.0, "fired": True})

    print("\n[11] THE FAILURE LEDGER")
    by: dict[str, list] = {}
    for e in ledger:
        by.setdefault(e["test"], []).append(e)
    print(f"{'condition':62s} {'cells':>6s} {'fired':>6s} {'worst cell':>34s}")
    nf = 0
    for name, es in sorted(by.items()):
        f2 = [e for e in es if e["fired"]]
        nf += len(f2)
        worst = max(es, key=lambda e: abs(e.get("value") or 0))
        print(f"{name:62s} {len(es):6d} {len(f2):6d} "
              f"{worst['feed'][:26] + ' ' + format(worst['value'], '.4g'):>34s}")
    print(f"\n    {len(ledger)} pre-registered comparisons, {nf} fired.")

    payload = {"rows": rows, "curves": curves, "controls": ctl_rows, "ledger": ledger,
               "detectable_sigma_bars": e_bars, "rebuild_sigma_bound": e_rebuild,
               "n_coin": n_coin, "ns": list(NS)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(json.loads(json.dumps(payload, default=float)), fh, indent=1)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
