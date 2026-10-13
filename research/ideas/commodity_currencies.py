"""The commodity-currency claim, which predicts a sign, tested against the metals.

The trade-press claim is that currencies of raw-material exporters rise and fall
**with the prices of what they export**. It is a claim about *levels*, and it
predicts a **sign** for each pair, which makes it a pre-specified hypothesis
rather than a search: there is nothing to correct for multiplicity because
nothing is being chosen.

## The dollar is the confound, and one comparison is immune to it

The symbols the first pass lacked - crude, Brent, gas, the softs, platinum,
palladium and the dollar baskets - were fetched from the lab terminal, so the
whole published list is now testable, including the headline CAD exposure to
crude.

That raises the real problem, which is not availability. **Commodities are
priced in dollars**, so a weaker dollar lifts every one of them and lifts every
`XXXUSD` quote at the same time. The first pass measured `GBPUSD` against gold
at `+0.3598` against `AUDUSD` at `+0.4011`, and sterling is not a commodity
currency - so almost the entire raw correlation is the dollar, not the
commodity. Two things answer it:

* **partial correlation**, removing `USD Basket` from both legs. What survives
  is the part the dollar does not explain;
* **an exporter against an importer**, which no dollar effect can fake. Canada
  exports crude and Japan imports it, so the claim predicts `USDCAD` and
  `USDJPY` move **opposite** ways against oil. Both are dollar-base pairs, so a
  pure dollar effect must give them the **same** sign. Opposite signs are
  evidence the confound cannot manufacture.

`GBPUSD` and `EURUSD` are carried as standing controls for exactly this reason:
if they survive the dollar control as well as the exporters do, the effect was
never about commodities.

## And the claim is about the quantity this desk has measured as null

Price-level relationships across this universe came back null: 0 of 190 pairs
cointegrated against a matched null, 0 of 1,625 baskets at widths two to five,
and no lead at 1h or 3m. Volatility relationships came back large: a median
cross-instrument correlation of **0.5170**.

So the commodity-currency claim is a statement about the half that is null, and
the test is which half carries it:

* **return correlation**, contemporaneous, with the **predicted sign**. This is
  the claim's actual content;
* **cointegration**, which is the stronger form of "rise and fall together",
  against the established bar of **-4.07** from the two-real-leg block shuffle -
  not a local null, which would be weaker and would contradict it;
* **volatility correlation**, which is what this desk knows is there.

A claim that shows up only in the third has been mis-stated rather than refuted:
"their volatilities move together" is a different and much weaker assertion than
"their values rise and fall together".

Runs on the lab.
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relationship_screen as screen  # noqa: E402

#: Each claim as `(pair, commodity, predicted sign, why)`. The sign is fixed
#: before anything is measured, so this is a hypothesis and not a search.
#:
#: **The exporter-importer pair is the test no dollar effect can pass.** Canada
#: exports crude and Japan imports it, so the claim predicts `USDCAD` and
#: `USDJPY` move **opposite** ways against oil. Both are dollar-base pairs, so a
#: pure dollar effect - commodities are priced in dollars, so a weaker dollar
#: lifts them all - must give them the **same** sign. Two opposite signs cannot
#: be produced by the dollar.
CLAIMS = (
    # The headline claim, untestable until the energy symbols were fetched.
    ("USDCAD", "US Oil", -1, "Canada exports crude; stronger CAD lowers USDCAD"),
    ("USDCAD", "UK Brent Oil", -1, "the same claim on the other benchmark"),
    ("USDCAD", "NGAS", -1, "Canada exports natural gas"),
    # And its mirror: an importer, where the sign must flip.
    ("USDJPY", "US Oil", +1, "Japan imports crude; costlier oil weakens JPY"),
    ("USDJPY", "UK Brent Oil", +1, "the same claim on the other benchmark"),
    # Metals.
    ("AUDUSD", "XAUUSD", +1, "Australia exports gold"),
    ("USDCAD", "XAUUSD", -1, "Canada exports gold"),
    ("USDCAD", "XAGUSD", -1, "Canada exports silver"),
    ("USDCHF", "XAUUSD", -1, "CHF is said to trade with gold"),
    ("AUDUSD", "XPTUSD", +1, "Australia exports platinum group metals"),
    # Softs, for the New Zealand claim.
    ("NZDUSD", "Sugar", +1, "NZD is said to track soft commodities"),
    ("NZDUSD", "Cocoa", +1, "the same claim on another soft"),
    ("NZDUSD", "Cotton", +1, "the same claim on another soft"),
    ("NZDUSD", "CoffeeArab", +1, "the same claim on another soft"),
    # The controls that matter: these are **not** commodity currencies, so a
    # claim specific to exporters must not hold for them once the dollar is
    # removed. If they survive the control, the effect was never commodities.
    ("GBPUSD", "XAUUSD", +1, "CONTROL: not a commodity currency"),
    ("EURUSD", "XAUUSD", +1, "CONTROL: not a commodity currency"),
    ("GBPUSD", "US Oil", +1, "CONTROL: not a commodity currency"),
    ("EURUSD", "US Oil", +1, "CONTROL: not a commodity currency"),
)
#: The grid for the group test, as `currency -> (pair, orientation, exports)`.
#:
#: **`orientation` is the quote convention, not a fitted parameter.** `AUDUSD`
#: rises when the Australian dollar strengthens and `USDNOK` falls when the
#: krone does, so a raw correlation against the same commodity has opposite
#: signs for the two with no economics involved. Multiplying by this turns
#: every cell into the same quantity - "the currency strengthens when the
#: commodity rises" - and it is fixed by how the broker quotes the pair.
#:
#: `exports` is what the country actually sells, which gives the test in arm 6
#: its within-currency control: a commodity currency should load on **its own**
#: export class more than on the others, and that comparison needs no control
#: group at all.
NAMED = {
    "AUD": ("AUDUSD", +1, "metal"),
    "CAD": ("USDCAD", -1, "energy"),
    "NZD": ("NZDUSD", +1, "soft"),
    "NOK": ("USDNOK", -1, "energy"),
    "MXN": ("USDMXN", -1, "energy"),
    "ZAR": ("USDZAR", -1, "metal"),
}

#: Currencies the claim does **not** name, as the control group. `CHF` and
#: `JPY` are deliberately absent: the published list gives both a special
#: mention - the franc for gold, the yen as an oil importer - so neither is a
#: clean control, and arm 2 already uses the yen as a signed prediction.
#:
#: `SEK` and `PLN` are the two that matter. They are freely floating European
#: currencies with no commodity export story, which makes them controls on the
#: same footing as the named currencies rather than controls by construction.
CONTROL = {
    "GBP": ("GBPUSD", +1, None),
    "EUR": ("EURUSD", +1, None),
    "SEK": ("USDSEK", -1, None),
    "PLN": ("USDPLN", -1, None),
}

#: The commodities, by class, for the grid and the own-class test.
CLASSES = {
    "energy": ("US Oil", "UK Brent Oil", "NGAS"),
    "metal": ("XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"),
    "soft": ("Sugar", "Cocoa", "Cotton", "CoffeeArab", "CoffeeRobu"),
}

#: The dollar index the correlations are partialled against.
DOLLAR = os.environ.get("DOLLAR", "USD_Basket")
#: The established bar for a traded-against-traded cointegration test.
COINTEGRATION_BAR = float(os.environ.get("BAR", "-4.07"))
#: Bars per volatility observation.
SPAN = int(os.environ.get("SPAN", "24"))
#: Null repetitions.
REPS = int(os.environ.get("REPS", "12"))
SEED = 20261013


def native_returns(series):
    """One-bar returns on the instrument's **own** grid, gap-spanners dropped.

    **The order of differencing and aligning is not a detail, and getting it
    wrong invented the first version of this result.** `screen.align` takes the
    two series' common timestamps; differencing *after* that turns every hole
    in the common grid into a single increment spanning the hole. FX trades
    24/5 and crude, the softs and the indices do not, so the common grid
    between an FX pair and a commodity is mostly holes - and each one becomes
    a large move appearing in **both** series at the same index. Those shared
    jumps then dominate the correlation.

    The symptom was unmistakable once the control legs were printed: every
    commodity correlated with `USD Basket` at `|r|` between 0.75 and 0.86, with
    near-identical magnitudes within a sign group - crude at `+0.7514` and gas
    at `+0.7463`, two weakly related markets - and crude's sign was *positive*,
    which is the opposite of what a dollar effect does to a dollar-priced
    commodity. Uniform magnitudes with instrument-specific signs is a
    structural artefact, not economics.

    So each series is differenced on its own consecutive bars first, and an
    increment is kept only if its own timestamp gap is the modal spacing -
    which also drops the weekend gap, a 65-hour move that is not an hourly
    return on any instrument. Aligning the **returns** afterwards keeps only
    the bars where both instruments genuinely traded through the hour.
    """
    import numpy as np

    stamps = np.asarray(series[0], dtype=float)
    values = np.asarray(series[1], dtype=float)
    if len(stamps) < 3:
        return None
    gaps = np.diff(stamps)
    step = float(np.median(gaps))
    if step <= 0:
        return None
    keep = np.abs(gaps - step) <= 0.25 * step
    if keep.sum() < 400:
        return None
    return stamps[1:][keep], np.diff(values)[keep]


def paired(*series):
    """Native returns for two or three instruments, on their common hours."""
    import numpy as np

    got = [native_returns(one) for one in series]
    if any(one is None for one in got):
        return None
    stamps = got[0][0]
    for one in got[1:]:
        stamps = np.intersect1d(stamps, one[0])
    if len(stamps) < 400:
        return None
    out = []
    for one in got:
        _, index, _ = np.intersect1d(one[0], stamps, return_indices=True)
        steps = one[1][index]
        if steps.std() == 0:
            return None
        out.append(steps)
    return out


def returns_correlation(left, right) -> float:
    import numpy as np

    got = paired(left, right)
    if got is None:
        return float("nan")
    da, db = got
    return float(np.corrcoef(da, db)[0, 1])


def vol_correlation(left, right) -> float:
    import numpy as np

    got = paired(left, right)
    if got is None:
        return float("nan")
    out = []
    for steps in got:
        count = len(steps) // SPAN
        if count < 60:
            return float("nan")
        sd = steps[: count * SPAN].reshape(count, SPAN).std(axis=1)
        out.append(sd)
    first, second = out
    keep = (first > 0) & (second > 0)
    if keep.sum() < 60:
        return float("nan")
    first, second = np.log(first[keep]), np.log(second[keep])
    if first.std() == 0 or second.std() == 0:
        return float("nan")
    return float(np.corrcoef(first, second)[0, 1])


def split_t(left, right) -> float:
    import numpy as np

    got = screen.align(left, right)
    if got is None:
        return float("nan")
    _, a, b, _, _ = got
    half = len(a) // 2
    if half < 400:
        return float("nan")
    varx = float(((a[:half] - a[:half].mean()) ** 2).sum())
    if varx <= 0:
        return float("nan")
    ratio = float(
        ((a[:half] - a[:half].mean()) * (b[:half] - b[:half].mean())).sum() / varx
    )
    return screen.dickey_fuller(b[half:] - ratio * a[half:])[1]


def partial(left, right, control) -> tuple[float, float, float]:
    """`corr(left, right)` with `control` removed, on their common bars.

    The dollar is the confound the first pass could not address: gold is priced
    in dollars, so a weaker dollar lifts it and lifts every `XXXUSD` with it.
    `GBPUSD` against gold read `+0.3598` and sterling is not a commodity
    currency, so most of the raw correlation was never about commodities.

    The partial correlation is the textbook form,
    `(rxy - rxz * ryz) / sqrt((1 - rxz^2) * (1 - ryz^2))`, which is exactly the
    correlation of the two residuals after each is regressed on the dollar.
    """
    import numpy as np

    got = paired(left, right, control)
    if got is None:
        return float("nan"), float("nan"), float("nan")
    x, y, z = got
    rxy = float(np.corrcoef(x, y)[0, 1])
    rxz = float(np.corrcoef(x, z)[0, 1])
    ryz = float(np.corrcoef(y, z)[0, 1])
    base = (1.0 - rxz * rxz) * (1.0 - ryz * ryz)
    if base <= 0:
        return float("nan"), rxz, ryz
    return (rxy - rxz * ryz) / math.sqrt(base), rxz, ryz


def grid(dollar) -> dict[str, dict[str, float]]:
    """Every currency against every commodity, dollar removed and oriented.

    Returns `currency -> commodity -> oriented partial`, where positive always
    means the currency strengthened as the commodity rose.
    """
    out: dict[str, dict[str, float]] = {}
    for code, (pair, orient, _sells) in {**NAMED, **CONTROL}.items():
        left = screen.load(pair)
        if left is None:
            continue
        cells: dict[str, float] = {}
        for items in CLASSES.values():
            for item in items:
                right = screen.load(item.replace(" ", "_"))
                if right is None:
                    continue
                part, _a, _b = partial(left, right, dollar)
                if math.isfinite(part):
                    cells[item] = orient * part
        if cells:
            out[code] = cells
    return out


def arrangements(codes, size):
    """Every way to choose `size` of `codes`. The exact permutation set."""
    from itertools import combinations

    return list(combinations(sorted(codes), size))


def main() -> None:
    import numpy as np

    from till_infinity.structures.statespace.nulls import rotated

    print(
        "the claim predicts a sign, fixed before measuring; cointegration is\n"
        f"judged against the established {COINTEGRATION_BAR:+.2f} bar, not a local null\n"
    )
    print(
        "the dollar is the confound: commodities are priced in it, so a weaker\n"
        "dollar lifts them all. Arm 1 removes it, arm 2 uses a comparison it\n"
        "cannot fake, and arm 3 checks the non-commodity controls die.\n"
    )

    picker = np.random.default_rng(SEED)
    null_returns, null_vol, null_partial = [], [], []
    metals = [m for m in ("XAUUSD", "XAGUSD") if screen.load(m) is not None]
    for metal in metals:
        got = screen.load(metal)
        for _ in range(REPS):
            shift = int(picker.integers(200, max(len(got[1]) - 200, 201)))
            spun = (
                got[0],
                np.asarray(rotated(list(got[1]), shift), dtype=float),
                got[2],
            )
            for pair, _m, _s, _w in CLAIMS:
                other = screen.load(pair)
                if other is None:
                    continue
                r = returns_correlation(other, spun)
                if math.isfinite(r):
                    null_returns.append(abs(r))
                v = vol_correlation(other, spun)
                if math.isfinite(v):
                    null_vol.append(abs(v))
    r_bar = max(null_returns) if null_returns else float("nan")
    v_bar = max(null_vol) if null_vol else float("nan")

    dollar = screen.load(DOLLAR)
    if dollar is None:
        print(f"  {DOLLAR} not cached; the dollar cannot be controlled for")
        return

    # **A raw-correlation null does not bound a partial.** Partialling divides
    # by `sqrt((1 - rxz^2) * (1 - ryz^2))`, which is below one, so it can only
    # inflate the magnitude - and the headline figures here are partials. The
    # null therefore has to be built on the same statistic: rotate the
    # commodity's increments, leaving the pair and the dollar untouched, so
    # the pair-to-dollar correlation survives and only the commodity's link
    # to both is destroyed.
    for pair, item, _said, _why in CLAIMS:
        other, got = screen.load(pair), screen.load(item.replace(" ", "_"))
        if other is None or got is None:
            continue
        for _ in range(max(REPS // 4, 4)):
            shift = int(picker.integers(200, max(len(got[1]) - 200, 201)))
            spun = (
                got[0],
                np.asarray(rotated(list(got[1]), shift), dtype=float),
                got[2],
            )
            q, _a, _b = partial(other, spun, dollar)
            if math.isfinite(q):
                null_partial.append(abs(q))
    p_bar = max(null_partial) if null_partial else float("nan")

    print("=" * 112)
    print("ARM 1  the claim's own sign, raw and with the dollar removed")
    print("=" * 112)
    print(
        f"rotation null over {len(null_returns)} draws: "
        f"max |return correlation| {r_bar:.4f}\n"
    )
    print(
        f"partial null over {len(null_partial)} draws (the commodity rotated): "
        f"max |partial| {p_bar:.4f}\n"
    )
    print(
        f"{'pair':<9}{'commodity':<15}{'said':>6}{'raw':>9}{'sign':>6}"
        f"{'partial':>10}{'sign':>6}{'beats':>7}{'kept':>7}"
        f"{'r(fx,$)':>9}{'r(cmd,$)':>10}{'split t':>9}"
    )
    rows = []
    for pair, item, said, why in CLAIMS:
        left, right = screen.load(pair), screen.load(item.replace(" ", "_"))
        if left is None or right is None:
            print(f"{pair:<9}{item:<15}  not cached")
            continue
        raw = returns_correlation(left, right)
        part, rxz, ryz = partial(left, right, dollar)
        t = split_t(left, right)
        if not math.isfinite(raw):
            continue
        rows.append(
            {
                "pair": pair,
                "item": item,
                "said": said,
                "raw": raw,
                "partial": part,
                "t": t,
                "control": why.startswith("CONTROL"),
            }
        )
        ok_raw = (raw > 0) == (said > 0)
        ok_part = math.isfinite(part) and (part > 0) == (said > 0)
        kept = (
            abs(part) / abs(raw) if math.isfinite(part) and raw else float("nan")
        )
        beats = math.isfinite(part) and abs(part) > p_bar
        print(
            f"{pair:<9}{item:<15}{said:>+6}{raw:>+9.4f}{'yes' if ok_raw else 'NO':>6}"
            f"{part:>+10.4f}{'yes' if ok_part else 'NO':>6}"
            f"{'yes' if beats else 'no':>7}{kept:>7.2f}"
            f"{rxz:>+9.4f}{ryz:>+10.4f}{t:>+9.2f}"
        )

    print("\n" + "=" * 112)
    print("ARM 2  the exporter against the importer, which the dollar cannot explain")
    print("=" * 112)
    for item in ("US Oil", "UK Brent Oil"):
        cad = next(
            (r for r in rows if r["pair"] == "USDCAD" and r["item"] == item), None
        )
        jpy = next(
            (r for r in rows if r["pair"] == "USDJPY" and r["item"] == item), None
        )
        if not (cad and jpy):
            continue
        print(
            f"\n{item}:  USDCAD raw {cad['raw']:+.4f} partial {cad['partial']:+.4f}"
            f"   |   USDJPY raw {jpy['raw']:+.4f} partial {jpy['partial']:+.4f}"
        )
        opposed_raw = cad["raw"] * jpy["raw"] < 0
        opposed_part = (
            math.isfinite(cad["partial"])
            and math.isfinite(jpy["partial"])
            and cad["partial"] * jpy["partial"] < 0
        )
        print(
            f"   opposite signs: raw {'yes' if opposed_raw else 'NO'}, "
            f"with the dollar removed {'yes' if opposed_part else 'NO'}"
        )
    print(
        "\nBoth are dollar-base pairs, so a dollar effect gives them the **same**\n"
        "sign. Canada exports crude and Japan imports it, so the\n"
        "commodity-currency claim gives them **opposite** signs. Opposite signs\n"
        "are therefore evidence the dollar cannot manufacture."
    )

    print("\n" + "=" * 112)
    print("ARM 3  do the controls die when the dollar is removed, as they must")
    print("=" * 112)
    print(f"{'kind':<28}{'claims':>8}{'median |raw|':>14}{'median |partial|':>18}{'kept':>8}")
    for label, want in (("commodity currencies", False), ("CONTROLS, not one", True)):
        here = [
            r
            for r in rows
            if r["control"] == want and math.isfinite(r["partial"]) and r["raw"]
        ]
        if not here:
            continue
        raws = statistics.median(abs(r["raw"]) for r in here)
        parts = statistics.median(abs(r["partial"]) for r in here)
        print(
            f"{label:<28}{len(here):>8}{raws:>14.4f}{parts:>18.4f}"
            f"{parts / raws if raws else float('nan'):>8.2f}"
        )
    scored = [
        r for r in rows if math.isfinite(r["partial"]) and r["raw"]
    ]
    named = [abs(r["partial"]) for r in scored if not r["control"]]
    checks = [abs(r["partial"]) for r in scored if r["control"]]
    if named and checks:
        seen = statistics.median(named) - statistics.median(checks)
        pool = named + checks
        shuffler = np.random.default_rng(SEED + 1)
        over = 0
        for _ in range(4000):
            spun = list(pool)
            shuffler.shuffle(spun)
            a, b = spun[: len(named)], spun[len(named) :]
            if statistics.median(a) - statistics.median(b) >= seen:
                over += 1
        print(
            f"\ngap in median |partial|: {seen:+.4f}, "
            f"p = {(over + 1) / 4001:.4f} over 4000 label shuffles"
        )
    print(
        "\n**This is the test of whether the claim is about commodities at all.**\n"
        "Sterling and the euro are not commodity currencies, so if their\n"
        "correlation survives the dollar control as well as Australia's does,\n"
        "the effect was the dollar and the commodity story adds nothing."
    )

    print("\n" + "=" * 112)
    print("ARM 5  the same question with enough currencies to answer it")
    print("=" * 112)
    cells = grid(dollar)
    absent = [c for c in sorted(set(NAMED) | set(CONTROL)) if c not in cells]
    if absent:
        print(f"not cached, so not in the test: {', '.join(absent)}")
    print(
        f"\n{'currency':<10}{'pair':<9}{'named':>7}{'cells':>7}"
        f"{'median oriented partial':>26}"
    )
    middles: dict[str, float] = {}
    for code in sorted(cells):
        values = [v for v in cells[code].values() if math.isfinite(v)]
        if not values:
            continue
        middles[code] = statistics.median(values)
        pair = (NAMED | CONTROL)[code][0]
        print(
            f"{code:<10}{pair:<9}{'yes' if code in NAMED else 'no':>7}"
            f"{len(values):>7}{middles[code]:>+26.4f}"
        )
    named = [v for c, v in middles.items() if c in NAMED]
    checks = [v for c, v in middles.items() if c in CONTROL]
    if named and checks:
        seen = statistics.median(named) - statistics.median(checks)
        codes = sorted(middles)
        every = arrangements(codes, len(named))
        over = sum(
            1
            for pick in every
            if statistics.median([middles[c] for c in pick])
            - statistics.median([middles[c] for c in codes if c not in pick])
            >= seen
        )
        print(
            f"\nnamed median {statistics.median(named):+.4f}, "
            f"control median {statistics.median(checks):+.4f}, "
            f"gap {seen:+.4f}"
        )
        print(
            f"exact permutation over currency labels: {over} of {len(every)} "
            f"arrangements reach it, p = {over / len(every):.4f}"
        )
        print(
            f"the floor this design can return is {1 / len(every):.4f}, which is\n"
            "what the currency count buys - the hand-picked four-control\n"
            "version of this test could not go below 0.1 whatever was true."
        )

    print("\n" + "=" * 112)
    print("ARM 6  does each currency load on what its country actually sells")
    print("=" * 112)
    print(
        "**This arm needs no control group.** Each named currency is compared\n"
        "against itself: its loading on its own export class against its\n"
        "loading on the other classes. A dollar effect, a risk-appetite\n"
        "effect or any other common factor hits all three classes, so it\n"
        "cannot produce a gap here - only knowing what the country sells can.\n"
    )
    print(f"{'currency':<10}{'sells':<8}{'own class':>11}{'others':>9}{'gap':>9}")
    gaps = []
    for code in sorted(NAMED):
        if code not in cells:
            continue
        sells = NAMED[code][2]
        own = [
            v
            for item, v in cells[code].items()
            if item in CLASSES[sells] and math.isfinite(v)
        ]
        rest = [
            v
            for item, v in cells[code].items()
            if item not in CLASSES[sells] and math.isfinite(v)
        ]
        if not own or not rest:
            continue
        here = statistics.median(own) - statistics.median(rest)
        gaps.append(here)
        print(
            f"{code:<10}{sells:<8}{statistics.median(own):>+11.4f}"
            f"{statistics.median(rest):>+9.4f}{here:>+9.4f}"
        )
    if gaps:
        up = sum(1 for g in gaps if g > 0)
        print(
            f"\n{up} of {len(gaps)} load more on their own export class. "
            f"median gap {statistics.median(gaps):+.4f}."
        )
        print(
            "Under no relationship each currency is a coin, so the sign count\n"
            f"is binomial: p = {sum(math.comb(len(gaps), k) for k in range(up, len(gaps) + 1)) / 2 ** len(gaps):.4f} one-sided."
        )

    # **The sign count throws away most of what was measured**, and with six
    # currencies it cannot do better than 0.016 even if every one agrees. Each
    # currency has three classes and the question is where its own one ranks
    # among them, which is a draw from `{1, 2, 3}` under the null rather than a
    # coin - so the same six currencies carry `3 ** 6 = 729` arrangements
    # instead of 64, and a currency that ranks its own class second is
    # evidence rather than a failure.
    print(f"\n{'currency':<10}{'sells':<8}{'energy':>9}{'metal':>9}{'soft':>9}{'own rank':>10}")
    ranks = []
    for code in sorted(NAMED):
        if code not in cells:
            continue
        sells = NAMED[code][2]
        middles_by_class = {}
        for name, items in CLASSES.items():
            here = [
                v
                for item, v in cells[code].items()
                if item in items and math.isfinite(v)
            ]
            if here:
                middles_by_class[name] = statistics.median(here)
        if sells not in middles_by_class or len(middles_by_class) < len(CLASSES):
            continue
        order = sorted(middles_by_class, key=lambda k: -middles_by_class[k])
        rank = order.index(sells) + 1
        ranks.append(rank)
        print(
            f"{code:<10}{sells:<8}"
            f"{middles_by_class['energy']:>+9.4f}{middles_by_class['metal']:>+9.4f}"
            f"{middles_by_class['soft']:>+9.4f}{rank:>10}"
        )
    if ranks:
        total = sum(ranks)
        ways = len(CLASSES) ** len(ranks)
        # Exact null: the number of rank vectors summing to `total` or less.
        from itertools import product

        under = sum(
            1
            for pick in product(range(1, len(CLASSES) + 1), repeat=len(ranks))
            if sum(pick) <= total
        )
        print(
            f"\nrank sum {total} over {len(ranks)} currencies "
            f"(best possible {len(ranks)}, chance {2 * len(ranks)}): "
            f"p = {under / ways:.4f} exact over {ways} rank vectors"
        )

    # The one comparison in this study that holds everything but the export
    # constant. Norway and Sweden are neighbours of similar size, both
    # floating, both European, and only one of them sells oil.
    if "NOK" in cells and "SEK" in cells:
        for code in ("NOK", "SEK"):
            got = [
                v
                for item, v in cells[code].items()
                if item in CLASSES["energy"] and math.isfinite(v)
            ]
            if got:
                print(
                    f"\n{code} on energy: {statistics.median(got):+.4f}"
                    f"  ({'oil exporter' if code == 'NOK' else 'the control: no oil'})"
                )
        print(
            "Sweden is the control Norway deserves. Sterling and the euro\n"
            "differ from the krone in a dozen ways; the krona differs in one."
        )

    print("\n" + "=" * 112)
    print("ARM 4  the volatility channel, which this desk knows is large")
    print("=" * 112)
    print(f"rotation null over {len(null_vol)} draws: max |correlation| {v_bar:.4f}\n")
    print(f"{'pair':<9}{'commodity':<15}{'vol r':>9}{'beats null':>12}")
    beat = 0
    for pair, item, _said, _why in CLAIMS:
        left, right = screen.load(pair), screen.load(item.replace(" ", "_"))
        if left is None or right is None:
            continue
        v = vol_correlation(left, right)
        if not math.isfinite(v):
            continue
        over = abs(v) > v_bar
        beat += over
        print(f"{pair:<9}{item:<15}{v:>+9.4f}{'yes' if over else 'no':>12}")
    print(
        f"\n{beat} of the claims clear the volatility null. A claim that shows up\n"
        "only here has been **mis-stated rather than refuted**: 'their\n"
        "volatilities move together' is a different and far weaker assertion\n"
        "than 'their values rise and fall together', and it is the one this\n"
        "desk has already measured across the whole universe at a median of\n"
        "0.5170. It is not tradeable as a directional bet."
    )


if __name__ == "__main__":
    main()
