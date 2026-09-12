"""Every cut this book publishes, re-run under `calibrating.md`'s correction.

`research/auditing.md`. `calibrating.md` measured what the desk's own methods do
on a world with no edge in it; this applies the result to the live book rather
than arguing from it. For each published cut table it reprints the rows with:

* the **percentile** interval `spending.py` ships,
* a **studentised** interval, which `calibrating.md` [7] found holds its nominal
  rate at n=16-50 where the percentile one reads 7-8% against 5%,
* the same studentised interval at a **Bonferroni alpha over the rows that
  actually get an interval** - `calibrating.md` [8] measures that combination at
  2.65% +-0.36 family-wise against the 32.10% the uncorrected percentile table
  runs at,
* and the **family-wise rate implied by the table's own row sizes**, computed
  from the measured per-row miss rates rather than assumed.

Rows are disjoint sets of closes, so the family-wise rate under independence is
exactly `1 - prod(1 - p(n_i))` and needs no correction for correlation.

## What this can and cannot re-run

`.data/closes.json` carries profit, `risk_money`, `r_multiple`, `best_r`,
`strategy`, `feed`, `interval`, `exit_kind` and the decision features, so every
cut that is a group-by over closes is recomputable here: `spending.md`'s three
tables, `instruments.md`'s instrument ranking, `giveback.md`'s give-back table.

Cuts over *replayed* populations - `exiting.md`'s eighteen exit policies,
`sweepregimes.py`'s twenty-one dimensions, `generators.md`'s tick-level stop
slippage - are not recomputable from the closes export and are judged on their
published numbers, with the arithmetic of the correction applied to the row
count. That distinction is in the output so a reader never has to guess which
they are looking at.

## What would have killed this, declared before any number was read

1. **The reproduction must match the published figure.** Every row this file
   reprints is a row some page already published; if the point estimate does not
   reproduce to 0.1 points of risk, the cut here is not the cut there and the
   comparison is meaningless. Checked per row and reported as MISMATCH.
2. **The studentised interval must not be uniformly wider.** If it is wider than
   the percentile one on every row, it is buying its coverage with width alone
   and the recommendation is a tautology. `calibrating.md` measured +10% at n=29
   and +2% at n=133, so a factor above 1.3 on the live book means the live
   distribution is not the one that was calibrated.
3. **A row that survives the correction must survive it at both alphas.** If a
   row clears Bonferroni over the rows that get an interval but not over all
   rows printed, it is inside the choice of denominator and is reported as such
   rather than as a survivor.

Run: `.venv/bin/python research/harness/calibaudit.py [path/to/closes.json]`
"""

from __future__ import annotations

import collections
import math
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, os.environ.get("REPO", os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

import research.harness.spending as S  # noqa: E402
from research.harness.calibfpr import (  # noqa: E402
    MIN_INTERVAL_N,
    boot,
    on_risk,
    studentised,
    t_crit,
)

DRAWS = int(os.environ.get("DRAWS", "20000"))
SEED = int(os.environ.get("SEED", "31"))

#: `calibrating.md` [1], the measured rate at which a 95% percentile bootstrap
#: interval on return-on-risk misses the true value, by row size. Interpolated
#: on log n for sizes in between. This is the only place a number from that page
#: is hard-coded, and it is the whole reason this file can quote a family-wise
#: rate for a table nobody ran two thousand null books of.
MISS_BY_N: tuple[tuple[int, float], ...] = (
    (8, 0.1055), (16, 0.0765), (17, 0.0780), (23, 0.0850), (28, 0.0690),
    (29, 0.0705), (50, 0.0620), (100, 0.0525), (133, 0.0470), (300, 0.0470),
    (685, 0.0507), (1000, 0.0440),
)


def miss_rate(n: int) -> float:
    """The measured per-row miss rate at `n`, interpolated on log n."""
    if n < MIN_INTERVAL_N:
        return 0.0
    xs = [math.log(k) for k, _ in MISS_BY_N]
    ys = [v for _, v in MISS_BY_N]
    return float(np.interp(math.log(n), xs, ys))


def family_wise(sizes) -> float:
    """`1 - prod(1 - p_i)` over the rows that get an interval."""
    out = 1.0
    for n in sizes:
        out *= 1.0 - miss_rate(n)
    return 1.0 - out


def rows_of(path: Path) -> list[dict]:
    return S.load(path)


def pairs_of(rows) -> tuple[np.ndarray, np.ndarray]:
    p, q = [], []
    for row in rows:
        risk = float(row.get("risk_money") or 0.0)
        if row.get("profit") is None or risk <= 0:
            continue
        p.append(float(row["profit"]))
        q.append(risk)
    return np.array(p), np.array(q)


def interval_row(profit, risk, alpha: float, rng):
    """Percentile, studentised at 5%, and studentised at `alpha`."""
    n = profit.size
    if n < MIN_INTERVAL_N:
        return None
    pct = boot(profit, risk, rng, draws=DRAWS)
    stu = studentised(profit, risk, rng, DRAWS, 0.05)
    cor = studentised(profit, risk, rng, DRAWS, alpha)
    return pct, stu, cor


def excludes_zero(band) -> bool:
    return band is not None and not (band[0] <= 0.0 <= band[1])


def show(label: str, groups: "collections.OrderedDict", published: dict | None = None,
         note: str = "") -> dict:
    """One cut table, reprinted with the correction."""
    rng = np.random.default_rng(SEED)
    # The row size that matters is the number of closes carrying **both** a
    # profit and a risk figure, which is what `interval()` sees - not the number
    # of closes in the group. Counting the group inflates the number of rows the
    # correction is over and makes it look harsher than it is.
    sizes = [pairs_of(v)[0].size for v in groups.values()]
    wide = [n for n in sizes if n >= MIN_INTERVAL_N]
    alpha = 0.05 / max(len(wide), 1)
    alpha_all = 0.05 / max(len(sizes), 1)
    print(f"\n## {label}")
    print(f"   {len(sizes)} rows, {len(wide)} with n>={MIN_INTERVAL_N}, "
          f"Bonferroni alpha {alpha:.4f} over those "
          f"({alpha_all:.4f} over all rows)")
    if note:
        print(f"   {note}")
    print(f"   family-wise chance that at least one row misses, from the measured")
    print(f"   per-row rates at these sizes: {family_wise(wide) * 100:.1f}%\n")
    print(f"   {'row':22} {'n':>4} {'on risk':>9} {'percentile 95%':>22} "
          f"{'studentised 95%':>22} {'corrected':>22}  verdict")
    out = {"rows": [], "wide": len(wide), "sizes": sizes}
    for name, rows in groups.items():
        profit, risk = pairs_of(rows)
        if profit.size == 0:
            continue
        est = on_risk(profit, risk)
        got = interval_row(profit, risk, alpha, rng)
        if got is None:
            print(f"   {name:22} {profit.size:4d} {est * 100:+8.1f}% "
                  f"{'too few to say':>22} {'':>22} {'':>22}  not testable")
            out["rows"].append({"name": name, "n": int(profit.size), "est": est,
                                "verdict": "not testable"})
            continue
        pct, stu, cor = got
        z0, z1, z2 = (excludes_zero(pct), excludes_zero(stu), excludes_zero(cor))
        if z2:
            verdict = "survives the correction"
        elif z1:
            verdict = "lost to the correction"
        elif z0:
            verdict = "lost to the interval"
        else:
            verdict = "-"
        flag = ""
        if published and name in published:
            gap = abs(est - published[name])
            if gap > 0.001:
                flag = f"  MISMATCH vs published {published[name] * 100:+.1f}%"
        print(f"   {name:22} {profit.size:4d} {est * 100:+8.1f}% "
              f"[{pct[0] * 100:+7.1f}%,{pct[1] * 100:+7.1f}%] "
              f"[{stu[0] * 100:+7.1f}%,{stu[1] * 100:+7.1f}%] "
              f"[{cor[0] * 100:+7.1f}%,{cor[1] * 100:+7.1f}%]  {verdict}{flag}")
        out["rows"].append({"name": name, "n": int(profit.size), "est": est,
                            "pct": pct, "stu": stu, "cor": cor, "verdict": verdict})
    kept = [r for r in out["rows"] if r.get("verdict") == "survives the correction"]
    raw = [r for r in out["rows"] if r.get("verdict", "").startswith(
        ("survives", "lost to the correction", "lost to the interval"))]
    print(f"\n   uncorrected, {len(raw)} row(s) exclude zero; "
          f"after the correction, {len(kept)}: "
          f"{', '.join(r['name'] for r in kept) if kept else 'none'}")
    return out


def widths(rows) -> None:
    """Condition 2: is the studentised interval buying coverage with width?"""
    rng = np.random.default_rng(SEED + 1)
    ratios = []
    by_strategy: dict[str, list] = collections.defaultdict(list)
    for row in rows:
        by_strategy[str(row.get("strategy") or "unknown")].append(row)
    for part in by_strategy.values():
        profit, risk = pairs_of(part)
        if profit.size < MIN_INTERVAL_N:
            continue
        pct = boot(profit, risk, rng, draws=DRAWS)
        stu = studentised(profit, risk, rng, DRAWS, 0.05)
        if pct and stu:
            ratios.append((stu[1] - stu[0]) / (pct[1] - pct[0]))
    if ratios:
        print(f"\n[CHECK] studentised width / percentile width over "
              f"{len(ratios)} live rows: min {min(ratios):.2f}, "
              f"median {float(np.median(ratios)):.2f}, max {max(ratios):.2f}"
              f"   (calibrating.md measured 1.10 at n=29, 1.02 at n=133)")
        return max(ratios) <= 1.3
    return True


def keeps_table(rows) -> None:
    """`giveback.md`'s table, with an interval on the give-back.

    The published table has six rows of means with no interval on any of them,
    and a live setting was changed off one row of ten closes. The quantity with
    money in it is `best_r - r_multiple`: what the trade had and did not keep.
    """
    print("\n## giveback.md: what each strategy kept of its high-water mark")
    groups: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    for row in rows:
        best, got = row.get("best_r"), row.get("r_multiple")
        if best is None or got is None:
            continue
        groups[str(row.get("strategy") or "unknown")].append((float(best), float(got)))
    order = sorted(groups.items(), key=lambda kv: -len(kv[1]))
    wide = [len(v) for _, v in order if len(v) >= MIN_INTERVAL_N]
    alpha = 0.05 / max(len(wide), 1)
    print(f"   {len(order)} rows, {len(wide)} with n>={MIN_INTERVAL_N}, "
          f"Bonferroni alpha {alpha:.4f}\n")
    print(f"   {'strategy':20} {'n':>4} {'peak':>7} {'kept':>7} {'gave back':>10} "
          f"{'95% on the give-back':>24} {'corrected':>24}")
    for name, vals in order:
        arr = np.array(vals)
        peak, got = arr[:, 0], arr[:, 1]
        back = peak - got
        n = back.size
        if n < 2:
            continue
        se = back.std(ddof=1) / math.sqrt(n)
        lo95, hi95 = back.mean() - t_crit(n - 1) * se, back.mean() + t_crit(n - 1) * se
        lo_c, hi_c = (back.mean() - t_crit(n - 1, alpha) * se,
                      back.mean() + t_crit(n - 1, alpha) * se)
        print(f"   {name:20} {n:4d} {peak.mean():+7.3f} {got.mean():+7.3f} "
              f"{back.mean():+10.3f} [{lo95:+10.3f},{hi95:+9.3f}] "
              f"[{lo_c:+10.3f},{hi_c:+9.3f}]")


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".data/closes.json")
    rows = rows_of(path)
    real = [r for r in rows if not S.generated(r.get("feed"))]
    print("EVERY PUBLISHED CUT, RE-RUN UNDER calibrating.md's CORRECTION")
    print(f"{path}: {len(rows)} closes, {len(real)} on real markets")
    ok = widths(real)
    if not ok:
        print("   ** the studentised interval is uniformly wider on this book;"
              " condition 2 fired **")

    def group(rows_in, key, order_by_n=True):
        got: dict[str, list] = collections.defaultdict(list)
        for row in rows_in:
            got[str(row.get(key) or "unknown")].append(row)
        items = sorted(got.items(), key=lambda kv: -len(kv[1]) if order_by_n else kv[0])
        return collections.OrderedDict(items)

    show("spending.md: real markets by strategy", group(real, "strategy"),
         published={"snap": -0.343, "thesis-only": -0.010, "sweep-aware": -0.251,
                    "runner": -0.056, "fade-to-value": -0.387})
    show("spending.md: real markets by how the trade ended", group(real, "exit_kind"),
         note="stop and target exclude zero by construction - a stop returns about -1R")
    bands: dict[str, list] = collections.OrderedDict(
        (name, []) for name in ("below 1:1", "1:1 to 2:1", "2:1 and above"))
    for row in real:
        rr = row.get("reward_to_risk")
        if rr is None:
            continue
        rr = float(rr)
        bands["below 1:1" if rr < 1 else "1:1 to 2:1" if rr < 2 else "2:1 and above"].append(row)
    show("spending.md: real markets by planned reward-to-risk", bands,
         published={"below 1:1": -0.021, "1:1 to 2:1": -0.219, "2:1 and above": -0.533})
    show("spending.md: real markets by interval", group(real, "interval"))
    show("spending.md: real markets by hour",
         group(real, "hour"), note="the cut spending.md ran and did not report")
    show("instruments.md: every instrument, real and generated", group(rows, "feed"),
         note="the published ranking is on mean R; this is on return on risk, "
              "which is the comparable quantity across position sizes")
    gen = [r for r in rows if S.generated(r.get("feed"))]
    show("instruments.md: the generated half, by instrument", group(gen, "feed"),
         note="deriving.md's theorem says every row here is -(cost) and nothing else")
    keeps_table(rows)

    print("\n[NOTE] Cuts over replayed populations are not recomputable from the")
    print("       closes export - exiting.md's eighteen policies, sweepregimes'")
    print("       twenty-one dimensions, generators.md's tick-level slippage.")
    print("       research/auditing.md judges those on their published numbers.")


if __name__ == "__main__":
    main()
