"""Where a touch sits in the instrument's larger move.

Run from the repository root:  python research/harness/cycles.py

Every feature the model has is local to the touch - the last few bars before
price arrived. None of them says whether the instrument has been climbing for
a quarter, falling for one, or oscillating; nor, if oscillating, whether this
level is near the floor or near the ceiling. `docs/todo.md` §6c asks whether
that missing context carries anything.

## The label is a rule, not an eye

A regime label is the easiest thing in this field to fit backwards. "We were in
an uptrend" is trivially true afterwards and worthless in advance, so the label
here is computed from **daily closes strictly before the touch began** by one
rule with one threshold.

The rule is Kaufman's efficiency ratio over a window of daily closes:

    ER = |last - first| / sum of |bar-to-bar moves|

One if price went straight there, near zero if it wandered back over itself.
The threshold is not arbitrary: a random walk of N steps has an expected ER of
about **1 / sqrt(N)**, which is 0.129 at N=60. `TREND = 0.30` is therefore
"more than twice as directional as a coin", and the null it is measured against
is stated rather than assumed.

Position within the range is where the touch price sits between the window's
low and high. Defined always, but only *meaningful* when ranging - a trend has
no ceiling to be near, which is why it is reported split by direction.

## The falsification, which is about the interaction

Position-in-range alone will correlate with `side`: near the floor of a range,
most touches are from above. It would score as a discovery while adding nothing
to what `side` already says. So the question is not "does cycle state predict
direction" but **"does it change what `side` means"**:

    within each cycle state, does the up-rate for a given side differ from that
    side's pooled up-rate by more than the interval on the cell?

And the sample that matters is **cycles, not touches**. Touches inside one
uptrend are not independent draws on "does an uptrend matter".
"""

from __future__ import annotations

import bisect
import collections
import itertools
import math
import pickle
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

CACHE = Path(__file__).with_name("cycle-touches.pkl")

#: Daily closes in the window the cycle is measured over. Sixty trading days is
#: about a quarter - long enough to be a different object from a touch, short
#: enough that the stored history holds more than one of them.
WINDOW = 60

#: Efficiency ratio above which the window counts as trending rather than
#: ranging. A random walk over `WINDOW` steps averages 1/sqrt(60) = 0.129, so
#: this is twice a coin.
TREND = 0.30

#: Touches before a walk-forward model is scored, so the first predictions of a
#: cold model do not count against it.
WARM = 150

#: What the model already has, from `touches.FIELDS` plus the side.
KEYS = (
    "approach_vol",
    "depth_vol",
    "strength",
    "run_vol",
    "experience",
    "pivot",
    "backcheck",
    "regime",
    "above",
)

UP, RANGE, DOWN = 1, 0, -1
NAMES = {UP: "uptrend", RANGE: "range", DOWN: "downtrend"}


def daily() -> dict[str, tuple[list[int], list[float]]]:
    """One daily close series per feed, from the venue with the deepest history.

    **A cross-venue median was the first attempt and it was wrong here**, which
    is worth recording because it is the opposite of what the rest of the
    project does. Venues within a feed sit at slightly different levels - spx500
    quotes between 7,780 and 7,805 across eight of them, a third of a percent -
    and they do not all report every day. So the median switches between price
    levels as coverage changes, and every switch adds a step to the path that
    the instrument never took.

    The efficiency ratio is a *ratio to the path*, so inflating the path
    crushes it: the same instrument over the same window read 0.081 through the
    median and 0.121 through one venue's own series. Across twelve years a
    clean series medians 0.131 against a random-walk expectation of 0.129,
    which is the check that says the measure is behaving.

    Consensus earns its keep at tick level, where a single broker's spike is a
    false touch. It buys nothing across a quarter, where every venue agrees
    about the direction and only disagrees about the third decimal.
    """
    from till_infinity.prices.config import FEEDS

    owner = {}
    for name, feed in FEEDS.items():
        for group in feed.symbols.values():
            for sym in group:
                owner[(sym.venue.upper(), sym.ticker.upper())] = name

    conn = sqlite3.connect("file:.data/prices/prices.db?mode=ro", uri=True)
    gathered: dict[str, dict[tuple[str, str], dict[int, float]]] = collections.defaultdict(
        lambda: collections.defaultdict(dict)
    )
    for ts, ticker, venue, close in conn.execute(
        "select ts, ticker, venue, close from bars where interval = '1d' and close is not null"
        " order by ts"
    ):
        feed = owner.get((venue.upper(), ticker.upper()))
        if feed:
            # Keyed by UTC day, last write winning, so a venue that reports a
            # day more than once contributes it once.
            gathered[feed][(venue, ticker)][int(ts) // 86400] = float(close)

    series: dict[str, tuple[list[int], list[float]]] = {}
    for feed, venues in gathered.items():
        days = max(venues.values(), key=len)
        stamps = sorted(days)
        # The close of day D is only known once D is over.
        series[feed] = ([(day + 1) * 86400 for day in stamps], [days[day] for day in stamps])
    return series


def state(closes: list[float], price: float) -> tuple[float, float, float]:
    """(signed efficiency ratio, position in range, net move) for one window.

    The ratio is returned **signed** rather than already thresholded into a
    label, so the threshold stays a free parameter of the analysis instead of
    being baked into the cache. `direction_of` applies it.
    """
    if len(closes) < WINDOW:
        return 0.0, 0.5, 0.0
    window = closes[-WINDOW:]
    net = window[-1] - window[0]
    path = sum(abs(b - a) for a, b in itertools.pairwise(window))
    ratio = abs(net) / path if path else 0.0
    low, high = min(window), max(window)
    # Clamped: price can sit outside a window it is not a member of, and a
    # position of 1.4 is not a position within a range.
    position = 0.5 if high <= low else min(max((price - low) / (high - low), 0.0), 1.0)
    return (ratio if net > 0 else -ratio), position, net


def direction_of(signed: float, trend: float = TREND) -> int:
    """Label one signed efficiency ratio. The only place the threshold acts."""
    if abs(signed) < trend:
        return RANGE
    return UP if signed > 0 else DOWN


def rank_direction(signed: float, history: list[float]) -> int:
    """Label by where this ratio sits in **this feed's own** past ratios.

    A fixed threshold cannot label a downtrend, and that is not a sample
    accident. Markets fall faster and messier than they rise, so a decline
    rarely sustains a high efficiency ratio over a quarter: at `TREND` the
    twelve-year daily history calls **0.0% of us100 days and 0.1% of spx500
    days** a downtrend. A symmetric threshold on an asymmetric process labels
    one tail and never the other, which leaves half the question unasked
    rather than answered.

    Terciles of the feed's own distribution are symmetric by construction, and
    self-calibrating in the way the rest of this project prefers - btc's
    ordinary directionality is not eurusd's. Point-in-time: only ratios from
    before this moment are in `history`.
    """
    if len(history) < 100:
        return RANGE
    ordered = sorted(history)
    low = ordered[len(ordered) // 3]
    high = ordered[2 * len(ordered) // 3]
    if signed >= high:
        return UP
    if signed <= low:
        return DOWN
    return RANGE


class Cycles:
    """Cycle state per feed, answerable as of any moment.

    Built once from the whole daily history and then *queried* by time, which
    is what keeps it point-in-time: a lookup at `when` uses only the closes of
    days that had already ended.
    """

    def __init__(self) -> None:
        self.series = daily()
        self._ratios: dict[str, list[float]] = {}

    def at(self, feed: str, when: float, price: float) -> tuple[float, float, float] | None:
        found = self.series.get(feed)
        if not found:
            return None
        stamps, closes = found
        cut = bisect.bisect_left(stamps, when)
        if cut < WINDOW:
            return None
        return state(closes[:cut], price)

    def history(self, feed: str, when: float) -> list[float]:
        """Every signed ratio this feed printed before `when`. Point-in-time."""
        found = self.series.get(feed)
        if not found:
            return []
        stamps, closes = found
        cut = bisect.bisect_left(stamps, when)
        if feed not in self._ratios:
            self._ratios[feed] = [
                state(closes[:i], closes[i - 1])[0] for i in range(WINDOW, len(closes) + 1)
            ]
        # Ratio i in the cache was computed from closes[:WINDOW + i].
        return self._ratios[feed][: max(cut - WINDOW + 1, 0)]


def load():
    """Resolved touches, each carrying the cycle state it began in.

    Its own replay rather than `touches.load()`, which caches a row shape
    without `started` - and the label has to be read at the moment price
    arrived at the level, not at the moment it resolved. The touch is the thing
    being predicted; using anything from its own lifetime would be the leak
    this whole script is written to avoid.
    """
    if CACHE.exists():
        return pickle.loads(CACHE.read_bytes())

    from touches import FIELDS, _bars

    from till_infinity.structures.engine import Engine

    cycles = Cycles()
    engine = Engine(intervals=("1m", "5m", "15m", "1h"))
    rows = []
    for bar in _bars():
        engine.observe_bar(bar)
        for _level, touch in engine.drain_resolved():
            if not touch.push_vol:
                continue
            found = cycles.at(touch.feed, touch.started, touch.entry)
            if found is None:
                continue
            signed, position, net = found
            history = cycles.history(touch.feed, touch.started)
            rows.append(
                {
                    **{f: float(getattr(touch.features, f)) for f in FIELDS},
                    "above": 1.0 if touch.features.side.name == "ABOVE" else 0.0,
                    "up": touch.push_vol > 0,
                    "feed": touch.feed,
                    "interval": touch.interval,
                    "started": float(touch.started),
                    "resolved": float(touch.resolved),
                    "push_vol": float(touch.push_vol),
                    "cycle_er": signed,
                    "cycle_pos": position,
                    "cycle_net": net,
                    "cycle_rank": rank_direction(signed, history),
                }
            )
    rows.sort(key=lambda r: r["resolved"])
    CACHE.write_bytes(pickle.dumps(rows))
    return rows


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """A binomial interval that stays sane at small n, unlike the normal one."""
    if not n:
        return 0.0, 1.0
    p = hits / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(centre - half, 0.0), min(centre + half, 1.0)


def runs(rows) -> dict[str, int]:
    """How many distinct cycles the touches actually span, per feed.

    The number that sizes every claim below. A thousand touches inside one
    uptrend are one observation of an uptrend.
    """
    seen: dict[str, list] = collections.defaultdict(list)
    for row in sorted(rows, key=lambda r: r["started"]):
        seen[row["feed"]].append(direction_of(row["cycle_er"]))
    counted = {}
    for feed, states in seen.items():
        counted[feed] = 1 + sum(1 for a, b in itertools.pairwise(states) if a != b)
    return counted


def sample(rows) -> None:
    """What the sample actually is, before anything is claimed from it."""
    print("=== 0. how many cycles is this, really")
    counted = runs(rows)
    per_feed = collections.Counter(r["feed"] for r in rows)
    print(f"    {'feed':<10} {'touches':>8} {'cycles':>8} {'span':>9}")
    print("    " + "-" * 38)
    for feed in sorted(per_feed, key=lambda f: -per_feed[f]):
        times = [r["started"] for r in rows if r["feed"] == feed]
        span = (max(times) - min(times)) / 86400
        print(f"    {feed:<10} {per_feed[feed]:>8} {counted[feed]:>8} {span:>8.1f}d")
    print(f"    {'total':<10} {len(rows):>8} {sum(counted.values()):>8}")

    print("\n=== 1. what the labeller sees")
    by_state = collections.Counter(NAMES[direction_of(r["cycle_er"])] for r in rows)
    for name, n in by_state.most_common():
        print(f"    {name:<12} {n:>6} touches ({n / len(rows):>5.1%})")


def main() -> None:
    rows = load()
    print(f"{len(rows):,} resolved touches carrying a cycle label\n")
    sample(rows)

    print("\n=== 2. the falsification: does cycle state change what `side` means")
    print("    pooled first, then within each state\n")
    print(
        f"    {'side':<8} {'cycle':<12} {'n':>6} {'up-rate':>9}"
        f" {'95% interval':>18} {'vs pooled':>11}"
    )
    print("    " + "-" * 68)
    for above in (1.0, 0.0):
        side = "above" if above else "below"
        same = [r for r in rows if r["above"] == above]
        if not same:
            continue
        hits = sum(1 for r in same if r["up"])
        pooled = hits / len(same)
        lo, hi = wilson(hits, len(same))
        print(
            f"    {side:<8} {'(pooled)':<12} {len(same):>6} {pooled:>8.1%}"
            f" {f'{lo:.1%} - {hi:.1%}':>18}"
        )
        for direction in (UP, RANGE, DOWN):
            cell = [r for r in same if direction_of(r["cycle_er"]) == direction]
            if not cell:
                continue
            got = sum(1 for r in cell if r["up"])
            rate = got / len(cell)
            lo, hi = wilson(got, len(cell))
            # Separated only if the cell interval excludes the pooled rate.
            mark = "*" if not (lo <= pooled <= hi) else ""
            print(
                f"    {'':<8} {NAMES[direction]:<12} {len(cell):>6} {rate:>8.1%}"
                f" {f'{lo:.1%} - {hi:.1%}':>18} {100 * (rate - pooled):>+9.1f}pp {mark}"
            )
        print()

    print("=== 3. position within the range, for the touches that are in one")
    ranging = [r for r in rows if direction_of(r["cycle_er"]) == RANGE]
    print(f"    {len(ranging):,} touches labelled ranging\n")
    print(f"    {'side':<8} {'where in range':<16} {'n':>6} {'up-rate':>9} {'95% interval':>18}")
    print("    " + "-" * 62)
    bands = (("bottom third", 0.0, 1 / 3), ("middle", 1 / 3, 2 / 3), ("top third", 2 / 3, 1.01))
    for above in (1.0, 0.0):
        side = "above" if above else "below"
        for label, lo_b, hi_b in bands:
            cell = [r for r in ranging if r["above"] == above and lo_b <= r["cycle_pos"] < hi_b]
            if not cell:
                continue
            got = sum(1 for r in cell if r["up"])
            lo, hi = wilson(got, len(cell))
            print(
                f"    {side:<8} {label:<16} {len(cell):>6} {got / len(cell):>8.1%}"
                f" {f'{lo:.1%} - {hi:.1%}':>18}"
            )
        print()

    sensitivity(rows)
    calibrated(rows)
    modelled(rows)


def auc(scored: list[tuple[float, bool]]) -> float:
    """Rank AUC. Reported beside accuracy because the base rate here is skewed.

    A model can be 74.8% accurate on this data by saying "the level holds" and
    never looking at anything else, so accuracy alone cannot tell a model that
    ranks well from one that has memorised the majority class.
    """
    ranked = sorted(scored, key=lambda it: it[0])
    positives = sum(1 for _, y in ranked if y)
    negatives = len(ranked) - positives
    if not positives or not negatives:
        return 0.5
    total = 0.0
    i = 0
    rank = 0.0
    # Ties share the average rank, or a model that outputs one constant scores
    # something other than 0.5.
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        average = (i + j - 1) / 2 + 1
        for k in range(i, j):
            if ranked[k][1]:
                total += average
        rank += 0
        i = j
    return (total - positives * (positives + 1) / 2) / (positives * negatives)


def walk(rows, keys, use_cycle=False):
    """Walk-forward accuracy and AUC. Every touch predicted before it is learned."""
    from river import linear_model, preprocessing

    model = preprocessing.StandardScaler() | linear_model.LogisticRegression()
    hits = seen = 0
    scored = []
    for i, row in enumerate(rows):
        x = {k: row[k] for k in keys}
        if use_cycle:
            direction = direction_of(row["cycle_er"])
            x["cycle_up"] = 1.0 if direction == UP else 0.0
            x["cycle_down"] = 1.0 if direction == DOWN else 0.0
            x["rank_up"] = 1.0 if row["cycle_rank"] == UP else 0.0
            x["rank_down"] = 1.0 if row["cycle_rank"] == DOWN else 0.0
            x["cycle_er"] = row["cycle_er"]
            x["cycle_pos"] = row["cycle_pos"]
        probability = model.predict_proba_one(x).get(True, 0.5)
        if i >= WARM:
            seen += 1
            hits += (probability > 0.5) == row["up"]
            scored.append((probability, row["up"]))
        model.learn_one(x, row["up"])
    return (hits / seen if seen else 0.0), auc(scored), seen


def sensitivity(rows) -> None:
    """Whether the answer depends on the threshold that was chosen a priori."""
    print("=== 4. does the threshold change the answer")
    print("    TREND = 0.30 was fixed before looking. This is the robustness check,")
    print("    not a search for one that works.\n")
    print(
        f"    {'TREND':>7} {'up':>6} {'range':>7} {'down':>7}"
        f" {'cells that separate from pooled':>34}"
    )
    print("    " + "-" * 66)
    for trend in (0.10, 0.129, 0.15, 0.20, 0.25, 0.30, 0.40):
        labels = [direction_of(r["cycle_er"], trend) for r in rows]
        counts = collections.Counter(labels)
        separated = []
        for above in (1.0, 0.0):
            same = [r for r in rows if r["above"] == above]
            pooled = sum(1 for r in same if r["up"]) / len(same)
            for direction in (UP, RANGE, DOWN):
                cell = [r for r in same if direction_of(r["cycle_er"], trend) == direction]
                if len(cell) < 30:
                    continue
                got = sum(1 for r in cell if r["up"])
                lo, hi = wilson(got, len(cell))
                if not (lo <= pooled <= hi):
                    side = "above" if above else "below"
                    separated.append(f"{side}/{NAMES[direction]}")
        note = ", ".join(separated) if separated else "none"
        print(
            f"    {trend:>7.3f} {counts.get(UP, 0) / len(rows):>5.1%}"
            f" {counts.get(RANGE, 0) / len(rows):>6.1%} {counts.get(DOWN, 0) / len(rows):>6.1%}"
            f" {note:>34}"
        )


def calibrated(rows) -> None:
    """The same falsification under the self-calibrating labeller.

    This is the version that can see a downtrend, so it is the one that tests
    the half of the question a fixed threshold cannot reach.
    """
    print("\n=== 4b. the same question, labelled by the feed's own terciles")
    balance = collections.Counter(NAMES[r["cycle_rank"]] for r in rows)
    print(
        "    labels: "
        + ", ".join(f"{k} {v} ({v / len(rows):.1%})" for k, v in balance.most_common())
        + "\n"
    )
    print(
        f"    {'side':<8} {'cycle':<12} {'n':>6} {'up-rate':>9}"
        f" {'95% interval':>18} {'vs pooled':>11}"
    )
    print("    " + "-" * 68)
    for above in (1.0, 0.0):
        side = "above" if above else "below"
        same = [r for r in rows if r["above"] == above]
        hits = sum(1 for r in same if r["up"])
        pooled = hits / len(same)
        lo, hi = wilson(hits, len(same))
        print(
            f"    {side:<8} {'(pooled)':<12} {len(same):>6} {pooled:>8.1%}"
            f" {f'{lo:.1%} - {hi:.1%}':>18}"
        )
        for direction in (UP, RANGE, DOWN):
            cell = [r for r in same if r["cycle_rank"] == direction]
            if not cell:
                continue
            got = sum(1 for r in cell if r["up"])
            rate = got / len(cell)
            lo, hi = wilson(got, len(cell))
            mark = "*" if not (lo <= pooled <= hi) else ""
            print(
                f"    {'':<8} {NAMES[direction]:<12} {len(cell):>6} {rate:>8.1%}"
                f" {f'{lo:.1%} - {hi:.1%}':>18} {100 * (rate - pooled):>+9.1f}pp {mark}"
            )
        print()


def modelled(rows) -> None:
    """Does a model given the cycle beat the same model without it."""
    print("\n=== 5. does it help a model that already has everything else")
    print(f"    walk-forward over {len(rows) - WARM:,} touches, AUC beside accuracy\n")
    print(f"    {'features':<38} {'accuracy':>10} {'AUC':>8}")
    print("    " + "-" * 58)

    decided = rows[WARM:]
    holds = sum(1 for r in decided if bool(r["above"]) == r["up"]) / len(decided)
    print(f"    {'assume the level holds (no model)':<38} {holds:>9.1%} {'-':>8}")

    got, area, _ = walk(rows, ("above",))
    print(f"    {'side only':<38} {got:>9.1%} {area:>8.3f}")
    got, area, _ = walk(rows, KEYS)
    print(f"    {'all nine features':<38} {got:>9.1%} {area:>8.3f}")
    got, area, _ = walk(rows, KEYS, use_cycle=True)
    print(f"    {'all nine + cycle':<38} {got:>9.1%} {area:>8.3f}")
    got, area, _ = walk(rows, ("above",), use_cycle=True)
    print(f"    {'side + cycle':<38} {got:>9.1%} {area:>8.3f}")


if __name__ == "__main__":
    main()
