"""Levels defined by trade that did **not** happen.

Every other formation here is defined by presence. A pip is where price turned,
a run boundary is where volatility changed hands, an origin is the impulse that
set an extremum, a mode is where a lot happened. This one is the complement:
three bars where the first bar's high sits below the third bar's low leave a
range that price passed through in one direction and **never traded back into**.

The desk name is an imbalance or a fair-value gap. The mechanism claimed for it
is that the move was one-sided - buyers lifted every offer without sellers
getting a chance to transact - so the range is unfinished business and price
tends to come back and finish it.

That claim is testable and this makes no attempt to argue it. What is emitted
is the midpoint of the untraded range, as a turning point like any other, so
the outcome machinery gets to say whether price respects it.

## Why the middle, and why it is one point per gap

The **middle** because the gap is a range and the claim is about the range;
picking an edge would be picking which end of a band to believe, which is the
question `levels` answers with a zone rather than with a choice.

**One point** because a gap happens once. That is the honest shape of the
object and it is also the reason this pass rarely draws a level alone -
`form` needs three turns within a volatility unit, so a gap becomes a level
only where three of them have opened at nearly the same price, which does
happen in a repeatedly-traversed area and is exactly where the claim is
strongest. Everywhere else it merges into a level another pass drew, and
`agree` records that this one found it too.

## Size matters, and is measured in the usual currency

A gap smaller than the noise is not an imbalance, it is two bars. `MIN_GAP_VOL`
is in volatility units for the same reason everything else here is: a fixed
price width would give btc four gaps and eurusd four thousand.

## Filled gaps are not emitted

A gap price has already traded back through is finished business by its own
definition, and emitting it would be claiming the opposite of what the idea
says. The scan therefore looks forward from each gap and drops the ones later
bars covered - which costs a pass over the window and removes the only way this
formation could quietly become a list of every three-bar pattern in history.

## The family, and why one module rather than six

The three-bar gap above is one way price can leave a range untraded. The desk
reads five more, and they are all the same claim - *price passed here without
transacting properly, so it is unfinished* - differing only in what counts as
evidence. Splitting them across modules would hide that they are one idea, and
would make the honest comparison between them harder than it needs to be.

| kind | the evidence |
|------|--------------|
| `fvg` | three bars, the first's high below the third's low |
| `vi` | two bars whose **bodies** gap while their wicks still overlap |
| `og` | two bars that do not overlap **at all**, wicks included |
| `void` | one bar that is nearly all body - traversed, not auctioned |
| `ifvg` | an `fvg` price has closed through, read the other way up |
| `bpr` | where an up `fvg` and a down `fvg` overlap |

`vi` and `og` are the two halves of a distinction the three-bar form cannot
make. A body gap whose wicks overlap says price *was* quoted there and barely
traded; a true gap says it was never quoted at all. Those are different claims
about the same shape and this is the only place that separates them.

`void` is where the desk's displacement rule lands. A bar whose body is
`VOID_BODY` of its range and whose range reaches `VOID_VOL` units is a bar
price travelled rather than auctioned, and its body is the part nobody got a
second chance at. It is the one kind here defined by a single bar.

`ifvg` is the only kind that **needs** a filled gap, which is why the fill scan
earns its keep twice: `fvg` drops what it finds and `ifvg` keeps exactly that.

## What is already measured, and it is not encouraging

`research/docs/imbalance.md` took gap **edges** at first touch and found
**50.2%** against a **51.5%** breakeven and a 49.6% placebo - a loss, not a
small edge. That study measured the wick edge; this module emits the
**midpoint**, so it is not the same price, and none of the five kinds added
here were in it at all.

So nothing below is a claim that these work. Each is emitted as a turning point
and the outcome machinery is left to say whether price respects it, which is
the only way any of them becomes judgeable. The placebo in that study is the
bar to clear: a kind that reacts like an ordinary prior extreme at the same
distance is a way of *noticing* a level rather than a reason for one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ...shared.state import Restorable
from ..learning.touches import PUSH_BODY
from ..vol.volatility import Volatility
from .pips import Point, Swing

#: How large an untraded range must be to be an imbalance rather than two bars,
#: in volatility units.
MIN_GAP_VOL = 0.5

#: How much of the range must still be untraded for the gap to count as open.
#: Not "any part of it": a gap price has come back through nine tenths of is
#: finished in every sense that matters, and holding it open would keep a level
#: alive on the strength of a tenth of a bar.
OPEN_SHARE = 0.5

#: How large a body gap must be to count as a volume imbalance. Lower than
#: `MIN_GAP_VOL` because a `vi` is a smaller object by construction - it is the
#: space between two bodies inside overlapping ranges, not a hole in the range -
#: and holding it to the same floor would emit almost none of them.
MIN_VI_VOL = 0.25

#: What share of its own range a bar's body must be for the bar to count as a
#: void. **The desk's displacement rule**, imported from `learning.touches`
#: rather than restated: a bar this one-sided is one price travelled through
#: rather than auctioned at, and two copies of that number would drift apart
#: the first time the desk moved it. It has moved once already, 0.70 to 0.65
#: on 2026-10-08.
VOID_BODY = PUSH_BODY
#: And how large that bar must be, in volatility units. Body share alone would
#: call every quiet one-directional bar a void; the claim is about a bar big
#: enough that the traverse left something behind.
VOID_VOL = 1.5

#: The kinds this module can draw. `points` takes a subset.
KINDS: tuple[str, ...] = ("fvg", "vi", "og", "void", "ifvg", "bpr")


def _remaining(
    highs: Sequence[float],
    lows: Sequence[float],
    start: int,
    low: float,
    high: float,
    open_share: float,
) -> tuple[float, float]:
    """What is left of the band `(low, high)` after bar `start` onwards traded.

    Returned as `(top, bottom)`, eroded from whichever side each later bar
    arrived on. It stops early once the remainder has fallen through
    `open_share`, because every caller only asks whether it did.

    One definition shared by every kind here. It was extracted from `gaps`
    unchanged rather than rewritten: the `gap` pass draws levels in production,
    so a tidier erosion rule would have been a silent change to the live book
    dressed up as a refactor.
    """
    top, bottom = high, low
    span = (high - low) * open_share
    for j in range(start, len(highs)):
        if lows[j] < top and highs[j] > bottom:
            top = min(top, max(bottom, lows[j]))
            bottom = max(bottom, min(top, highs[j])) if highs[j] < top else bottom
        if top - bottom < span:
            break
    return top, bottom


def gaps(
    highs: Sequence[float],
    lows: Sequence[float],
    vol: Volatility,
    *,
    minimum_vol: float = MIN_GAP_VOL,
    open_share: float = OPEN_SHARE,
) -> list[tuple[int, float, float, float]]:
    """`(index, low, high, size in volatility units)` for each open gap.

    `index` is the middle bar of the three - the one the move happened on, and
    the one whose time stamps the point. Oldest first.
    """
    if len(highs) != len(lows) or len(highs) < 3:
        return []

    found: list[tuple[int, float, float, float]] = []
    for i in range(1, len(highs) - 1):
        before_high, before_low = highs[i - 1], lows[i - 1]
        after_high, after_low = highs[i + 1], lows[i + 1]
        if after_low > before_high:
            low, high = before_high, after_low  # a gap left by a move up
        elif before_low > after_high:
            low, high = after_high, before_low  # and one left by a move down
        else:
            continue
        middle = (low + high) / 2.0
        if middle <= 0:
            continue
        size = vol.units((high - low) / middle * 10_000)
        if size < minimum_vol:
            continue

        top, bottom = _remaining(highs, lows, i + 2, low, high, open_share)
        if top - bottom < (high - low) * open_share:
            continue
        found.append((i, low, high, size))
    return found


@dataclass(slots=True)
class Imbalance(Restorable):
    """One untraded or thinly-traded band, and what kind of evidence made it."""

    #: The bar that stamps it - the one the move happened on.
    index: int
    #: The band, ordered.
    low: float
    high: float
    #: Its height in volatility units. The strength of the claim.
    size_vol: float
    #: Which of `KINDS`.
    kind: str
    #: Left by a move **up**, so it sits below and reads as support. An `ifvg`
    #: reports the inverted sense rather than the original one, which is the
    #: whole point of the kind.
    up: bool

    @property
    def middle(self) -> float:
        return (self.low + self.high) / 2.0


def _vol_units(low: float, high: float, vol: Volatility) -> float:
    """A band's height in volatility units, or 0.0 where it cannot be priced."""
    middle = (low + high) / 2.0
    if middle <= 0 or high <= low:
        return 0.0
    return vol.units((high - low) / middle * 10_000)


def _body(open_: float, close: float) -> tuple[float, float]:
    """A bar's body, ordered low to high."""
    return (close, open_) if open_ > close else (open_, close)


def volume_imbalances(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    vol: Volatility,
    *,
    minimum_vol: float = MIN_VI_VOL,
    open_share: float = OPEN_SHARE,
) -> list[Imbalance]:
    """Body gaps between adjacent bars whose ranges still overlap.

    The distinction `fvg` cannot draw. Price **was** quoted across this band -
    the wicks prove it - and almost nothing changed hands there, which is a
    weaker claim than a hole in the range and a different one.
    """
    n = len(closes)
    if n < 2 or len({len(opens), len(highs), len(lows), n}) != 1:
        return []
    out: list[Imbalance] = []
    for i in range(n - 1):
        bottom_a, top_a = _body(opens[i], closes[i])
        bottom_b, top_b = _body(opens[i + 1], closes[i + 1])
        if top_a < bottom_b and lows[i + 1] <= highs[i]:
            low, high, up = top_a, bottom_b, True
        elif top_b < bottom_a and lows[i] <= highs[i + 1]:
            low, high, up = top_b, bottom_a, False
        else:
            continue
        size = _vol_units(low, high, vol)
        if size < minimum_vol:
            continue
        top, bottom = _remaining(highs, lows, i + 2, low, high, open_share)
        if top - bottom < (high - low) * open_share:
            continue
        out.append(Imbalance(i, low, high, size, "vi", up))
    return out


def opening_gaps(
    highs: Sequence[float],
    lows: Sequence[float],
    vol: Volatility,
    *,
    minimum_vol: float = MIN_GAP_VOL,
    open_share: float = OPEN_SHARE,
) -> list[Imbalance]:
    """Adjacent bars that do not overlap at all - wicks included.

    The strongest form of the claim, and the rarest on a continuous series: a
    band price was never quoted across. On an instrument that closes, most of
    these are the session break rather than anything anyone did.
    """
    n = len(highs)
    if n < 2 or len(lows) != n:
        return []
    out: list[Imbalance] = []
    for i in range(n - 1):
        if lows[i + 1] > highs[i]:
            low, high, up = highs[i], lows[i + 1], True
        elif highs[i + 1] < lows[i]:
            low, high, up = highs[i + 1], lows[i], False
        else:
            continue
        size = _vol_units(low, high, vol)
        if size < minimum_vol:
            continue
        top, bottom = _remaining(highs, lows, i + 2, low, high, open_share)
        if top - bottom < (high - low) * open_share:
            continue
        out.append(Imbalance(i, low, high, size, "og", up))
    return out


def voids(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    vol: Volatility,
    *,
    body_share: float = VOID_BODY,
    minimum_vol: float = VOID_VOL,
    open_share: float = OPEN_SHARE,
) -> list[Imbalance]:
    """Single bars that are nearly all body - price travelled, not auctioned.

    The desk's displacement rule as a formation. The band is the **body**, not
    the range: the wicks are where price was rejected, and the body is the part
    it went through without stopping.
    """
    n = len(closes)
    if n < 1 or len({len(opens), len(highs), len(lows), n}) != 1:
        return []
    out: list[Imbalance] = []
    for i in range(n):
        span = highs[i] - lows[i]
        if span <= 0:
            continue
        low, high = _body(opens[i], closes[i])
        if (high - low) / span < body_share:
            continue
        size = _vol_units(low, high, vol)
        if size < minimum_vol:
            continue
        top, bottom = _remaining(highs, lows, i + 1, low, high, open_share)
        if top - bottom < (high - low) * open_share:
            continue
        out.append(Imbalance(i, low, high, size, "void", closes[i] > opens[i]))
    return out


def inversions(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    vol: Volatility,
    *,
    minimum_vol: float = MIN_GAP_VOL,
) -> list[Imbalance]:
    """Three-bar gaps price has **closed** through, read the other way up.

    `gaps` throws these away and this is the kind that wants them. The desk
    reading is that a gap which fails becomes the opposite: support that gave
    way is resistance, and the band it gave way through is where that is
    tested. A close beyond the far edge is the test used rather than a wick,
    because a wick through a band is the band holding.
    """
    n = len(highs)
    if n < 3 or len({len(lows), len(closes), n}) != 1:
        return []
    out: list[Imbalance] = []
    for i in range(1, n - 1):
        if lows[i + 1] > highs[i - 1]:
            low, high, up = highs[i - 1], lows[i + 1], True
        elif lows[i - 1] > highs[i + 1]:
            low, high, up = highs[i + 1], lows[i - 1], False
        else:
            continue
        size = _vol_units(low, high, vol)
        if size < minimum_vol:
            continue
        # Closed through, in the direction that would break it: an up gap is
        # inverted by a close below its low, a down gap by a close above.
        broke = (
            any(closes[j] < low for j in range(i + 2, n))
            if up
            else any(closes[j] > high for j in range(i + 2, n))
        )
        if not broke:
            continue
        out.append(Imbalance(i, low, high, size, "ifvg", not up))
    return out


def balanced_ranges(
    highs: Sequence[float],
    lows: Sequence[float],
    vol: Volatility,
    *,
    minimum_vol: float = MIN_VI_VOL,
    open_share: float = OPEN_SHARE,
) -> list[Imbalance]:
    """Where an up gap and a down gap overlap.

    Two imbalances in opposite directions covering one band means price left it
    unfinished going both ways, which the desk reads as the strongest of these
    and is a narrower object than either gap alone. Stamped at the later of the
    two, since that is when the overlap existed.
    """
    n = len(highs)
    if n < 3 or len(lows) != n:
        return []
    ups: list[tuple[int, float, float]] = []
    downs: list[tuple[int, float, float]] = []
    for i in range(1, n - 1):
        if lows[i + 1] > highs[i - 1]:
            ups.append((i, highs[i - 1], lows[i + 1]))
        elif lows[i - 1] > highs[i + 1]:
            downs.append((i, highs[i + 1], lows[i - 1]))
    out: list[Imbalance] = []
    for up_i, up_low, up_high in ups:
        for dn_i, dn_low, dn_high in downs:
            low, high = max(up_low, dn_low), min(up_high, dn_high)
            if high <= low:
                continue
            size = _vol_units(low, high, vol)
            if size < minimum_vol:
                continue
            index = max(up_i, dn_i)
            top, bottom = _remaining(highs, lows, index + 2, low, high, open_share)
            if top - bottom < (high - low) * open_share:
                continue
            out.append(Imbalance(index, low, high, size, "bpr", up_i > dn_i))
    return out


def imbalances(
    opens: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    vol: Volatility,
    *,
    kinds: Sequence[str] = KINDS,
) -> list[Imbalance]:
    """Every requested kind, oldest first.

    See `structures-drawing-gaps.md` in research/docs.
    """
    wanted = tuple(k for k in kinds if k in KINDS)
    out: list[Imbalance] = []
    if "fvg" in wanted:
        out += [
            Imbalance(i, low, high, size, "fvg", lows[i + 1] > highs[i - 1])
            for i, low, high, size in gaps(highs, lows, vol)
        ]
    if "vi" in wanted:
        out += volume_imbalances(opens, highs, lows, closes, vol)
    if "og" in wanted:
        out += opening_gaps(highs, lows, vol)
    if "void" in wanted:
        out += voids(opens, highs, lows, closes, vol)
    if "ifvg" in wanted:
        out += inversions(highs, lows, closes, vol)
    if "bpr" in wanted:
        out += balanced_ranges(highs, lows, vol)
    out.sort(key=lambda g: (g.index, g.kind))
    return out


def points(
    times: Sequence[float],
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    vol: Volatility,
    *,
    opens: Sequence[float] | None = None,
    kinds: Sequence[str] = KINDS,
) -> list[Point]:
    """Open imbalances as turning points, so levels can form at them.

    **`opens` is optional and two kinds need it.** `vi` and `void` are both
    claims about where a bar's body sits, which highs and lows cannot express,
    so without opens they are skipped rather than approximated - a body
    inferred from the range is a different object wearing the same name.

    See `structures-drawing-gaps.md` in research/docs.
    """
    if not closes or len(times) != len(closes) or len(highs) != len(closes):
        return []
    wanted = tuple(kinds)
    if opens is None or len(opens) != len(closes):
        opens, wanted = list(closes), tuple(k for k in wanted if k not in ("vi", "void"))
    spot = closes[-1]
    out: list[Point] = []
    for found in imbalances(opens, highs, lows, closes, vol, kinds=wanted):
        after = min(found.index + 1, len(times) - 1)
        out.append(
            Point(
                index=found.index,
                time=int(times[found.index]),
                price=found.middle,
                swing=Swing.HIGH if found.middle > spot else Swing.LOW,
                # How big the imbalance is, in basis points of volatility unit,
                # so it ranks the way prominence does for the other formations.
                prominence_bps=found.size_vol * 10_000,
                confirmed=float(times[after]),
            )
        )
    return out
