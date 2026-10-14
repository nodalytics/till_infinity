"""Does a real level emit anything at all - before, during or after a touch?

`statespace-conditional-holds.md` closed the **per-level** question: `tau` over
279 levels came back at 0.0109 against a simulated null of 0.0085, so a level's
own record is sampling noise and no estimator was ever going to read it.

That is not the same question as this one. `tau` asks whether level #47 differs
from level #48. This asks whether a touch at a real level **looks different from
a touch at a price that is not one**, pooled over every touch. The second
question has every event in one cell instead of a dozen per level, which is the
only place a tiny signal could still be alive. Asked on 2026-10-14, in those
words: *real levels should emit or give some kind of signal before, during or
after for us to know if they are real, it might just be a tiny signal.*

## The panel

Nineteen observables, scale-free so instruments pool, in the three windows:

**Before** the touch - approach speed, deceleration, range and volume ramp, how
far out price stood a bar earlier, and how many momentum and acceleration turns
the approach contained. **During** - wick on the touched side, body, rejection,
overshoot past the price, range spike, volume spike, spread spike, and
`wick x volume`, which is the CWRV combination: a long wick on heavy volume is
absorption, the same wick on light volume is nothing. **After** - retrace,
activity, volume, and drift through.

Nothing here is a hold rate. The dead statistic is excluded on purpose.

## Why a distance-matched placebo is not enough on its own

A real level here is a 100-bar extreme, so a touch at one is **by construction**
a visit to a price not exceeded in 100 bars, while the placebo at a matched
distance is often inside the recent range. Several of the `before` and `during`
measures would separate the two on that definition alone, with no market
structure involved, and reporting that as a signal would be reporting the
detector back to itself.

So every arm is run a second time on a **block-shuffled copy of the same
instrument**: the same bars in blocks of fifty, re-levelled in log space, each
bar keeping its own open, high, low, volume and spread. Bar geometry, volatility
clustering and the marginal return distribution survive; long-range level
structure does not. Extremes are re-detected there, so the shuffled arm carries
the identical definitional advantage and no real levels. A claim has to beat
both its permutation null and the shuffled arm.

## The null, and the family

Each anchor contributes one real price and one placebo price at a matched
distance - a matched pair. The null flips the labels **within a pair**, all of
that pair's events together, which preserves event counts, the instrument mix
and the time overlap between a pair's touches. Four hundred draws. The
family-wise p is the fraction of draws whose largest `|AUC - 0.5|` over all
nineteen beats the observed largest, so nineteen chances at 0.05 do not buy a
finding.

## The power sweep answers "it might just be a tiny signal"

A null is worth nothing without the size it could have seen, so a known shift is
planted on the real events of one `during` and one `after` observable, swept from
0.02 to 0.40 standard deviations, and the AUC and p reported at each step. That
says where this design goes blind, and therefore what "tiny" would have to mean
to have escaped it.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))
FRAME = os.environ.get("FRAME", "1h")
LIMIT = int(os.environ.get("LIMIT", "40000"))
#: Bars behind an anchor that define the extreme and the typical bar.
LOOKBACK = int(os.environ.get("LOOKBACK", "100"))
PER_FEED = int(os.environ.get("PER_FEED", "80"))
#: Bars ahead of an anchor that a price is watched for. Bounded so one pair
#: cannot contribute a thousand events while another contributes four.
HORIZON = int(os.environ.get("HORIZON", "1500"))
CAP = int(os.environ.get("CAP", "30"))
#: Bars of history each observable needs behind the touch, and ahead of it.
WARM = 20
AFTER = 6
DRAWS = int(os.environ.get("DRAWS", "400"))
BLOCK = int(os.environ.get("BLOCK", "50"))
JITTER = 0.15
#: Anchors at least `HORIZON` apart, so no two pairs watch the same bars.
#: The first run of this harness spaced eighty anchors over a series and
#: watched 1500 bars from each, so pairs overlapped six deep; a null that
#: flips pair labels then understates its own variance, and the generated
#: feeds - which have no levels at all - duly produced `retrace3` at
#: p 0.007. Overlap is the knob that produced that, so it is a knob.
OVERLAP = os.environ.get("OVERLAP", "0") == "1"
SEED = int(os.environ.get("SEED", "20261014"))
TRADED = tuple(os.environ.get("TRADED", "EURUSD,GBPUSD,USDJPY,XAUUSD,AUDUSD,USDCAD").split(","))
#: Two independent Deriv volatility indices, which is the placebo pair this
#: desk carries in every relationship harness, plus one with a known step
#: generator.
GENERATED = tuple(
    os.environ.get("GENERATED", "Volatility_75_Index,Volatility_10_Index,Step_Index_200").split(",")
)

BEFORE = ("approach", "decel", "ramp", "vramp", "standoff", "turns", "accel_turns")
DURING = ("wick", "body", "reject", "overshoot", "spike", "vspike", "sprd", "wickvol")
AFTER_F = ("retrace3", "activity5", "vafter5", "drift5")
PANEL = BEFORE + DURING + AFTER_F
#: The two the power sweep plants an effect on: one definitional-risk `during`
#: measure and one `after` measure, which cannot be definitional.
PLANTED = ("wick", "retrace3")


def load(name: str) -> dict[str, np.ndarray] | None:
    path = CACHE / f"{name}.{FRAME}.npz"
    if not path.exists():
        return None
    with np.load(path) as bundle:
        need = {"time", "open", "high", "low", "close", "volume", "spread"}
        if not need <= set(bundle.keys()):
            return None
        order = np.argsort(bundle["time"])
        got = {k: np.asarray(bundle[k], dtype=float)[order] for k in need}
    keep = (
        (got["high"] >= got["low"])
        & (got["low"] > 0)
        & (got["volume"] > 0)
        & np.isfinite(got["close"])
    )
    got = {k: v[keep] for k, v in got.items()}
    if len(got["close"]) < 8000:
        return None
    if len(got["close"]) > LIMIT:
        got = {k: v[-LIMIT:] for k, v in got.items()}
    return got


def shuffle_blocks(bars: dict[str, np.ndarray], rng) -> dict[str, np.ndarray]:
    """The same bars in a new order, re-levelled so the path is continuous.

    Each bar keeps its own open, high, low, volume and spread **as log offsets
    from its own close**, so the geometry that makes a touch detectable is
    untouched. Only the order of the blocks changes, which is what carries a
    level: a price revisited in the real series is not revisited here.
    """
    close = bars["close"]
    ret = np.diff(np.log(close))
    geom = {k: np.log(bars[k] / close) for k in ("open", "high", "low")}
    blocks = len(ret) // BLOCK
    if blocks < 4:
        return bars
    order = rng.permutation(blocks)
    take = np.concatenate([np.arange(b * BLOCK, (b + 1) * BLOCK) for b in order])
    walk = np.concatenate([[np.log(close[0])], np.log(close[0]) + np.cumsum(ret[take])])
    source = np.concatenate([[0], take + 1])
    out = {"close": np.exp(walk)}
    for k in ("open", "high", "low"):
        out[k] = np.exp(walk + geom[k][source])
    for k in ("volume", "spread"):
        out[k] = bars[k][source]
    out["time"] = bars["time"][: len(walk)]
    # Re-levelling cannot break the ordering, but a float round trip can.
    out["high"] = np.maximum.reduce([out["high"], out["open"], out["close"]])
    out["low"] = np.minimum.reduce([out["low"], out["open"], out["close"]])
    return out


def features(bars, price: float, i: int, move: float, from_below: bool) -> dict | None:
    """The panel at one touch, or `None` if the bar cannot support it."""
    o, h, l_, c = bars["open"], bars["high"], bars["low"], bars["close"]
    v, s = bars["volume"], bars["spread"]
    if i < WARM or i + AFTER + 1 >= len(c):
        return None
    past = slice(i - WARM, i)
    ranges = h[past] - l_[past]
    base_r = float(ranges.mean())
    base_v = float(v[past].mean())
    base_s = float(s[past].mean())
    bar = float(h[i] - l_[i])
    if not (base_r > 0 and base_v > 0 and bar > 0 and move > 0):
        return None
    recent = h[i - 3 : i] - l_[i - 3 : i]
    steps = np.diff(c[i - 6 : i])
    accel = np.diff(steps)
    nxt = slice(i + 1, i + 1 + 5)
    ahead_r = h[nxt] - l_[nxt]
    sign = 1.0 if from_below else -1.0
    top, bottom = max(o[i], c[i]), min(o[i], c[i])
    wick = (h[i] - top) / bar if from_below else (bottom - l_[i]) / bar
    vspike = float(v[i]) / base_v
    out = {
        "approach": abs(c[i - 1] - c[i - 4]) / (3.0 * move),
        "decel": (abs(c[i - 1] - c[i - 2]) - abs(c[i - 3] - c[i - 4])) / move,
        "ramp": float(recent.mean()) / base_r,
        "vramp": float(v[i - 3 : i].mean()) / base_v,
        "standoff": abs(c[i - 1] - price) / move,
        "turns": float(np.count_nonzero(np.diff(np.sign(steps)) != 0)) / max(len(steps) - 1, 1),
        "accel_turns": float(np.count_nonzero(np.diff(np.sign(accel)) != 0))
        / max(len(accel) - 1, 1),
        "wick": wick,
        "body": abs(c[i] - o[i]) / bar,
        "reject": ((h[i] - c[i]) if from_below else (c[i] - l_[i])) / bar,
        "overshoot": ((h[i] - price) if from_below else (price - l_[i])) / move,
        "spike": bar / base_r,
        "vspike": vspike,
        "sprd": float(s[i]) / base_s if base_s > 0 else 1.0,
        "wickvol": wick * vspike,
        "retrace3": sign * (price - c[i + 3]) / move,
        "activity5": float(ahead_r.mean()) / base_r,
        "vafter5": float(v[nxt].mean()) / base_v,
        "drift5": sign * (c[i + 5] - price) / move,
    }
    return out if all(math.isfinite(x) for x in out.values()) else None


def events(bars, price: float, start: int, move: float) -> list[dict]:
    """Every distinct visit to `price`, one event per approach.

    After a visit the walk skips forward until the bar no longer contains the
    price **and** the close is half a typical bar away, so a price that sits
    inside twenty consecutive bars contributes one event rather than twenty.
    """
    h, l_, c = bars["high"], bars["low"], bars["close"]
    out: list[dict] = []
    end = min(start + HORIZON, len(c) - AFTER - 1)
    i = max(start, WARM)
    while i < end and len(out) < CAP:
        if not (l_[i] <= price <= h[i]):
            i += 1
            continue
        got = features(bars, price, i, move, bool(c[i - 1] < price))
        if got is not None:
            out.append(got)
        j = i + 1
        while j < end and (l_[j] <= price <= h[j] or abs(c[j] - price) < 0.5 * move):
            j += 1
        i = j
    return out


def pairs_for(bars, rng, feed: str) -> list[tuple]:
    """One real level and one distance-matched placebo per anchor.

    Each pair carries its feed, so a pooled AUC can be split by instrument -
    this desk has had a pooled median agree with a claim every subgroup
    refuted - and whether its placebo landed **beyond** the extreme or inside
    it, which is the confound any `during` measure has to survive.
    """
    closes, highs, lows = bars["close"], bars["high"], bars["low"]
    last = len(closes) - HORIZON - AFTER - 2
    span = last - LOOKBACK
    if span <= 0:
        return []
    step = max(1, span // max(PER_FEED, 1))
    if not OVERLAP:
        step = max(step, HORIZON)
    out: list[tuple] = []
    for k, at in enumerate(range(LOOKBACK, last, step)):
        window = slice(max(at - LOOKBACK, 0), at)
        move = float(np.median(highs[window] - lows[window]))
        if not (move > 0):
            continue
        level = float(highs[window].max() if k % 2 == 0 else lows[window].min())
        here = float(closes[at])
        gap = level - here
        if abs(gap) < 0.25 * move:
            continue
        scale = 1.0 + float(rng.uniform(-JITTER, JITTER))
        placebo = here + gap * scale
        real, fake = events(bars, level, at, move), events(bars, placebo, at, move)
        if real and fake:
            out.append((real, fake, feed, scale > 1.0))
    return out


def auc(a: np.ndarray, b: np.ndarray) -> float:
    """`P(a > b) + 0.5 P(a = b)`, which is the tie-aware form.

    A plain `>` count reads 1.0000 when one arm is constant, which is how a
    base-rate arm once scored a perfect AUC in this repo.
    """
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    order = np.sort(b)
    lo = np.searchsorted(order, a, side="left")
    hi = np.searchsorted(order, a, side="right")
    return float(np.mean(lo + 0.5 * (hi - lo)) / len(order))


def table(pairs, rng, plant=None, only=None) -> dict:
    """Observed AUCs, their matched-pair permutation nulls, and the family p."""
    names = tuple(only) if only else PANEL
    stacked = {
        name: (
            [np.array([e[name] for e in pair[0]]) for pair in pairs],
            [np.array([e[name] for e in pair[1]]) for pair in pairs],
        )
        for name in names
    }
    if plant is not None:
        pname, size = plant
        sd = float(
            np.std(
                np.concatenate(
                    [np.concatenate(stacked[pname][0]), np.concatenate(stacked[pname][1])]
                )
            )
        )
        stacked[pname] = ([r + size * sd for r in stacked[pname][0]], stacked[pname][1])

    observed = {n: auc(np.concatenate(r), np.concatenate(f)) for n, (r, f) in stacked.items()}
    means = {
        n: (float(np.mean(np.concatenate(r))), float(np.mean(np.concatenate(f))))
        for n, (r, f) in stacked.items()
    }
    beaten = dict.fromkeys(names, 0)
    family = 0
    seen = max(abs(observed[n] - 0.5) for n in names)
    # Whether a real level is **visited more often** than its placebo. Outside
    # the family because the magnet effect is already refuted in `docs/` - this
    # is a consistency check on that, not a new claim.
    counts = np.array([float(len(pair[0])) for pair in pairs])
    other = np.array([float(len(pair[1])) for pair in pairs])
    wider = 0
    seen_gap = abs(float(counts.mean() - other.mean()))
    for _ in range(DRAWS):
        flip = rng.random(len(pairs)) < 0.5
        left_n = np.where(flip, other, counts).mean()
        right_n = np.where(flip, counts, other).mean()
        if abs(float(left_n - right_n)) >= seen_gap:
            wider += 1
        widest = 0.0
        for n, (real, fake) in stacked.items():
            left = [fake[i] if flip[i] else real[i] for i in range(len(pairs))]
            right = [real[i] if flip[i] else fake[i] for i in range(len(pairs))]
            drawn = auc(np.concatenate(left), np.concatenate(right))
            if abs(drawn - 0.5) >= abs(observed[n] - 0.5):
                beaten[n] += 1
            widest = max(widest, abs(drawn - 0.5))
        if widest >= seen:
            family += 1
    return {
        "auc": observed,
        "means": means,
        "p": {n: (beaten[n] + 1) / (DRAWS + 1) for n in names},
        "family": (family + 1) / (DRAWS + 1),
        "events": sum(len(pair[0]) for pair in pairs),
        "pairs": len(pairs),
        "visits": (float(counts.mean()), float(other.mean()), (wider + 1) / (DRAWS + 1)),
    }


def main() -> None:
    rng = np.random.default_rng(SEED)
    print(
        f"frame {FRAME}  {LOOKBACK}-bar extremes, {HORIZON} bars watched, "
        f"{CAP} events a price\n{DRAWS} matched-pair label flips\n"
    )
    for group, names in (("traded", TRADED), ("generated", GENERATED)):
        real_pairs: list[tuple[list[dict], list[dict]]] = []
        shuffled_pairs: list[tuple[list[dict], list[dict]]] = []
        used: list[str] = []
        for name in names:
            bars = load(name)
            if bars is None:
                print(f"  (no {name}.{FRAME})")
                continue
            used.append(name)
            real_pairs += pairs_for(bars, rng, name)
            shuffled_pairs += pairs_for(shuffle_blocks(bars, rng), rng, name)
        if not real_pairs:
            continue
        got = table(real_pairs, np.random.default_rng(SEED + 1))
        ctrl = table(shuffled_pairs, np.random.default_rng(SEED + 2))
        print("=" * 86)
        print(f"{group}: {', '.join(used)}")
        print("=" * 86)
        print(
            f"  {got['events']:,} real-level touches over {got['pairs']} matched pairs; "
            f"shuffled control {ctrl['events']:,} over {ctrl['pairs']}\n"
        )
        print(f"  {'':<12}{'AUC':>8}{'p':>8}{'shuffled':>10}{'p':>8}   window")
        for name in PANEL:
            window = "before" if name in BEFORE else "during" if name in DURING else "after"
            mark = "  <--" if got["p"][name] < 0.05 and ctrl["p"][name] >= 0.05 else ""
            print(
                f"  {name:<12}{got['auc'][name]:>8.4f}{got['p'][name]:>8.3f}"
                f"{ctrl['auc'][name]:>10.4f}{ctrl['p'][name]:>8.3f}   {window}{mark}"
            )
        print(
            f"\n  family-wise p over all {len(PANEL)}: real {got['family']:.3f}, "
            f"shuffled {ctrl['family']:.3f}"
        )
        real_v, fake_v, p_v = got["visits"]
        ctrl_v, ctrl_f, ctrl_p = ctrl["visits"]
        print(
            f"  visits a price: real {real_v:.2f} vs placebo {fake_v:.2f} "
            f"(p {p_v:.3f}); shuffled {ctrl_v:.2f} vs {ctrl_f:.2f} (p {ctrl_p:.3f})"
        )
        print(
            "  An arrow is a marginal pass that the shuffled copy of the same\n"
            "  bars does not reproduce. Without the family-wise p below 0.05 it\n"
            "  is still one of nineteen chances.\n"
        )
        survivors = [n for n in PANEL if got["p"][n] < 0.05 and ctrl["p"][n] >= 0.05]
        for name in survivors:
            real_m, fake_m = got["means"][name]
            print(f"  {name.upper()}  AUC {got['auc'][name]:.4f}, so: is it real?")
            print(
                f"    in its own units : real {real_m:.4f} vs placebo {fake_m:.4f}"
                f"  ({real_m - fake_m:+.4f})"
            )
            feeds = sorted({pair[2] for pair in real_pairs})
            parts = []
            for feed in feeds:
                sub = [pair for pair in real_pairs if pair[2] == feed]
                if len(sub) < 6:
                    continue
                one = table(sub, np.random.default_rng(SEED + 7), only=(name,))
                parts.append(f"{feed} {one['auc'][name]:.4f} (p {one['p'][name]:.3f})")
            print("    by instrument   : " + "; ".join(parts))
            print(
                "      A pooled AUC that no instrument shows on its own is\n"
                "      Simpson's, which this desk has been caught by before."
            )
            for label, want in (("beyond the extreme", True), ("inside it", False)):
                sub = [pair for pair in real_pairs if pair[3] is want]
                if len(sub) < 6:
                    continue
                one = table(sub, np.random.default_rng(SEED + 8), only=(name,))
                print(
                    f"    placebo {label:<18}: AUC {one['auc'][name]:.4f} "
                    f"(p {one['p'][name]:.3f}, {one['pairs']} pairs)"
                )
            print(
                "      Half the placebos land past the extreme, where only a bar\n"
                "      that broke it can arrive. If the effect lives in that half\n"
                "      alone it is the construction, not the level.\n"
            )

        # **Only the first visit.** A level that has been tested nine times is
        # not the thing anyone means by a level emitting a signal; the first
        # test is. Same panel, same null, one event per price.
        fresh = [(pair[0][:1], pair[1][:1], pair[2], pair[3]) for pair in real_pairs]
        fresh_ctrl = [(pair[0][:1], pair[1][:1], pair[2], pair[3]) for pair in shuffled_pairs]
        first = table(fresh, np.random.default_rng(SEED + 5))
        first_ctrl = table(fresh_ctrl, np.random.default_rng(SEED + 6))
        widest = sorted(PANEL, key=lambda n: -abs(first["auc"][n] - 0.5))[:4]
        print(
            f"  FIRST VISIT ONLY  {first['events']:,} events, family-wise p "
            f"{first['family']:.3f} (shuffled {first_ctrl['family']:.3f})"
        )
        for name in widest:
            print(
                f"    {name:<12}{first['auc'][name]:>8.4f}{first['p'][name]:>8.3f}"
                f"{first_ctrl['auc'][name]:>10.4f}{first_ctrl['p'][name]:>8.3f}"
            )
        print()

        print("  POWER  a known shift planted on the real events only")
        for name in PLANTED:
            line = []
            for size in (0.02, 0.05, 0.10, 0.20, 0.40):
                planted = table(real_pairs, np.random.default_rng(SEED + 3), plant=(name, size))
                line.append(
                    f"{size:.2f}: AUC {planted['auc'][name]:.4f} p {planted['p'][name]:.3f}"
                )
            print(f"    {name:<10}" + "  |  ".join(line))
        print(
            "\n  The smallest shift with p < 0.05 is the smallest signal this\n"
            "  design could have seen. A null above it means absent; a null\n"
            "  below it means only smaller than that.\n"
        )


if __name__ == "__main__":
    main()
