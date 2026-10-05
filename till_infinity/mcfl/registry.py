"""The patterns the service can alert on, and what the research says about each.

A pattern is a detector over closed bars, the timeframes and asset classes it
runs on, and an **evidence line** quoted from the research doc that measured
it. The evidence is the part that matters most and the part most easily
overstated, so it is written here once, per pattern and per timeframe.

**The evidence never leaves the building.** A card shows only an opaque tier -
`TIER_A` where the edge passed, `CONTEXT` everywhere else - and a generic label
from `LABELS`; the evidence line rides in the payload's machine-side `meta` and
the logs (see `cards.py`). The tiers below are what decides `TIER_A`.

## Two badges, and only two places get the strong one

* **EDGE (measured)** - DISPLACE_C at a 12-bar low on crypto **1d** with its
  structure exit, and the BTC market mirror (M1, and B beside it). These
  passed frozen, out-of-sample tests (`turn-follow-ups.md` sections 5 and 6).
* **WEAK (measured, not significant alone)** - the same rule on crypto 4h:
  +0.036R on the fresh coins, inside the pooled pass but not significant by
  itself. It is not the 1d number and must not borrow it, so its cards are
  `CONTEXT`, not `TIER_A`.
* **DESCRIPTIVE: no edge found** - everything else, with the doc that says so.
  15m and 1h DISPLACE_C were never confirmed on fresh coins; the other
  patterns were measured and do not beat their walks.

Evidence is per timeframe because the numbers are. A 1d figure on a 15m card
would be the single most misleading thing this service could send.

## Enabled set

`MCFL_PATTERNS` names what is on. The default is `DEFAULT_ENABLED`: the
DISPLACE_C trade (crypto) and the market mirror with their exits. Everything
else is opt-in. CHoCH (CHARACTER_SHIFT) is not a pattern here at all, by the
desk's decision - see `events.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

TIMEFRAMES: tuple[str, ...] = ("15m", "1h", "4h", "1d")

CLASSES: tuple[str, ...] = ("crypto", "fx", "metals", "indices", "energy", "deriv")

EDGE = "EDGE (measured)"
WEAK = "WEAK (measured, not significant alone)"
DESCRIPTIVE = "DESCRIPTIVE: no edge found"

#: The footer every card carries.
FOOTER = "paper alert, not a trade instruction"


@dataclass(frozen=True, slots=True)
class Evidence:
    """What the research measured, for one pattern on one timeframe."""

    badge: str
    line: str
    doc: str

    @property
    def text(self) -> str:
        return f"{self.badge} · {self.line} ({self.doc})"

    @property
    def edge(self) -> bool:
        return self.badge == EDGE


@dataclass(frozen=True, slots=True)
class Pattern:
    """One alertable pattern.

    `kinds` are the event kinds (from `events.py`) it alerts on; `classes` the
    asset classes it runs on; `timeframes` where it may fire; `describe` the
    plain-English line for a card, keyed by bullish/bearish.
    """

    name: str
    title: str
    kinds: tuple[str, ...]
    classes: tuple[str, ...]
    timeframes: tuple[str, ...]
    describe: tuple[str, str]
    default: bool = False
    #: A trade with an entry, stop and frozen exit, rather than an observation.
    trade: bool = False


DTC_TF = TIMEFRAMES

PATTERNS: dict[str, Pattern] = {
    p.name: p
    for p in (
        Pattern(
            "DISPLACE_C_LOW12",
            "DISPLACE_C at a 12-bar low",
            ("DISPLACE_C_LOW12",),
            ("crypto",),
            DTC_TF,
            (
                "A violent bullish candle closed at a 12-bar low; the down-move was rejected.",
                "A violent bearish candle closed at a 12-bar high; the up-move was rejected.",
            ),
            default=True,
            trade=True,
        ),
        Pattern(
            "DISPLACE_C_LOW12_X",
            "DISPLACE_C at a 12-bar low (non-crypto)",
            ("DISPLACE_C_LOW12",),
            ("fx", "metals", "indices", "energy", "deriv"),
            DTC_TF,
            (
                "A violent bullish candle closed at a 12-bar low; the down-move was rejected.",
                "A violent bearish candle closed at a 12-bar high; the up-move was rejected.",
            ),
            trade=True,
        ),
        Pattern(
            "M1",
            "Market mirror: BTC on an alt's daily turn",
            ("M1",),
            ("crypto",),
            ("1d",),
            (
                "An alt printed DISPLACE_C at a 12-bar low on the daily: the market tends to turn "
                "with it, so the frozen rule buys BTC.",
                "",
            ),
            default=True,
            trade=True,
        ),
        Pattern(
            "B",
            "Market breadth: 3+ alts turned today",
            ("B",),
            ("crypto",),
            ("1d",),
            ("Three or more alts printed DISPLACE_C at a 12-bar low on the same daily close.", ""),
            default=True,
            trade=True,
        ),
        Pattern(
            "DISPLACE_C",
            "DISPLACE_C",
            ("DISPLACE_C",),
            CLASSES,
            TIMEFRAMES,
            (
                "Two strong bullish closes at their highs (or one huge one): a displacement up.",
                "Two strong bearish closes at their lows (or one huge one): a displacement down.",
            ),
        ),
        Pattern(
            "BREACH_REVERT",
            "Breach and revert (swing sweep)",
            ("BREACH_REVERT",),
            CLASSES,
            TIMEFRAMES,
            (
                "Price wicked under a swing low and closed back above it.",
                "Price wicked over a swing high and closed back below it.",
            ),
        ),
        Pattern(
            "DELIVERY_SHIFT",
            "Delivery shift (CISD)",
            ("DELIVERY_SHIFT",),
            CLASSES,
            TIMEFRAMES,
            (
                "A bullish close above the open of the last down-run: delivery shifted up.",
                "A bearish close below the open of the last up-run: delivery shifted down.",
            ),
        ),
        Pattern(
            "BOS",
            "Break of structure",
            ("STRUCTURE_SHIFT", "MAJOR_BOS"),
            CLASSES,
            TIMEFRAMES,
            (
                "Swing structure shifted up (higher highs and higher lows took over).",
                "Swing structure shifted down (lower highs and lower lows took over).",
            ),
        ),
        Pattern(
            "CLOSE_REVERT",
            "Close-beyond failure (turtle soup)",
            ("CLOSE_REVERT",),
            CLASSES,
            TIMEFRAMES,
            (
                "Price closed under a swing low, then closed back above it within 3 bars.",
                "Price closed over a swing high, then closed back below it within 3 bars.",
            ),
        ),
        Pattern(
            "SWEEP_SHIFT",
            "Sweep then shift",
            ("SWEEP_SHIFT",),
            CLASSES,
            TIMEFRAMES,
            (
                "A swing low was swept and, within 3 bars, price displaced or shifted up.",
                "A swing high was swept and, within 3 bars, price displaced or shifted down.",
            ),
        ),
        Pattern(
            "INDUCEMENT",
            "Inducement before a zone",
            ("INDUCEMENT",),
            CLASSES,
            TIMEFRAMES,
            (
                "A minor swing low was taken just before price came back to a demand zone.",
                "A minor swing high was taken just before price came back to a supply zone.",
            ),
        ),
        Pattern(
            "BREAKER",
            "Broken structure retested or reclaimed",
            ("BREAKER_RETEST", "RECLAIM"),
            CLASSES,
            TIMEFRAMES,
            (
                "A broken zone or gap was returned to (retest or reclaim).",
                "A broken zone or gap was returned to (retest or reclaim).",
            ),
        ),
        Pattern(
            "PROTECTED",
            "Protected low / high",
            ("PROTECTED", "PROTECTED_TAKEN"),
            CLASSES,
            TIMEFRAMES,
            (
                "A swing low held while its leg broke structure: a protected low.",
                "A swing high held while its leg broke structure: a protected high.",
            ),
        ),
    )
}

#: On unless `MCFL_PATTERNS` says otherwise.
DEFAULT_ENABLED: tuple[str, ...] = tuple(p.name for p in PATTERNS.values() if p.default)


def resolve(names: tuple[str, ...]) -> tuple[str, ...]:
    """Pattern names as given, unknown ones dropped (the caller warns)."""
    return tuple(n for n in names if n in PATTERNS)


# ------------------------------------------------------------------ evidence

_TURN = "turn-follow-ups.md"
_TP = "turning-points.md"

_DTC_CRYPTO: dict[str, Evidence] = {
    "1d": Evidence(
        EDGE,
        "+0.142R [+0.015, +0.280] on 58 fresh coins, +0.112R [+0.003, +0.216] on 73 more, "
        "+0.169R over 200 trades on the original 12; longs +0.24R, shorts +0.06R",
        f"{_TURN} §5",
    ),
    "4h": Evidence(
        WEAK,
        "+0.036R on the 58 fresh coins and +0.021R on 73 more at 4h; not significant on its own",
        f"{_TURN} §5",
    ),
    "1h": Evidence(
        DESCRIPTIVE,
        "never confirmed on fresh coins; in the 12-coin 1h/4h test the signature traded like "
        "walks (-0.045R against -0.046R)",
        f"{_TP} §3",
    ),
    "15m": Evidence(
        DESCRIPTIVE,
        "unconfirmed: no trade test on 15m; 15m was measured only for how violent turns are",
        f"{_TP} §4",
    ),
}

_DTC_OTHER = Evidence(
    DESCRIPTIVE,
    "outside crypto it was not confirmed: MT5 1d made -0.035R (walks -0.122R)",
    f"{_TURN} §5",
)

_FIXED: dict[str, Evidence] = {
    "M1": Evidence(
        EDGE,
        "+371 bps net a trade [+32, +706] on the 12 original coins; +281 bps [+75, +530] on 274 "
        "unseen perps; the forward log is still the test that matters",
        f"{_TURN} §6",
    ),
    "B": Evidence(
        EDGE,
        "secondary to M1: +141 bps over 12 days (12 coins), +136 bps over 71 days (274 perps); "
        "not separately tested for significance",
        f"{_TURN} §6",
    ),
    "DISPLACE_C": Evidence(
        DESCRIPTIVE,
        "3.8x likelier at major turns than at ordinary lows, but traded it matched walks; the lift "
        "is geometry, not information",
        f"{_TP} §1-3",
    ),
    "BREACH_REVERT": Evidence(
        DESCRIPTIVE,
        "every sweep form occurs at walk rates and predicts nothing; the excess wick sweeps are "
        "fat-tailed bars",
        "sweeps.md",
    ),
    "DELIVERY_SHIFT": Evidence(
        DESCRIPTIVE,
        "2.2x likelier at major turns, but as an entry the signature traded like walks "
        "(-0.045R against -0.046R)",
        f"{_TP} §1-3",
    ),
    "BOS": Evidence(
        DESCRIPTIVE,
        "no edge on the side or the follow-through; real broken levels hold 0.601 against about "
        "0.565 on walks, not tradeable after costs",
        "bos-predict.md, lrc-retest.md",
    ),
    "CLOSE_REVERT": Evidence(
        DESCRIPTIVE,
        "every sweep form predicts nothing; after it price goes 1 ATR its way first 49-52% of "
        "the time",
        "sweeps.md",
    ),
    "SWEEP_SHIFT": Evidence(
        DESCRIPTIVE,
        "the frozen primary failed at -0.021R [-0.030, -0.012] over 65,104 trades",
        "sweeps.md",
    ),
    "INDUCEMENT": Evidence(
        DESCRIPTIVE, "identified exactly and predicting nothing; no cell survived", "sweeps.md"
    ),
    "BREAKER": Evidence(
        DESCRIPTIVE, "identified exactly and predicting nothing; no cell survived", "sweeps.md"
    ),
    "PROTECTED": Evidence(
        DESCRIPTIVE,
        "protected lows hold 61% (sweep-strong 65%, weak 60%) and walks give the same numbers",
        "sweeps.md",
    ),
}


def evidence(pattern: str, timeframe: str, klass: str) -> Evidence:
    """The evidence line for this pattern on this timeframe and asset class."""
    if pattern == "DISPLACE_C_LOW12":
        if klass == "crypto":
            return _DTC_CRYPTO[timeframe]
        return _DTC_OTHER
    if pattern == "DISPLACE_C_LOW12_X":
        return _DTC_OTHER
    return _FIXED[pattern]


def for_event(kind: str) -> list[str]:
    """Patterns that alert on an event kind."""
    return [p.name for p in PATTERNS.values() if kind in p.kinds]


# ------------------------------------------------------------- what is shown

#: The tier a card shows instead of the evidence: opaque on purpose. The
#: evidence itself (`evidence`) stays machine-side - in the payload's metadata
#: and the logs - because the cards leave the building and the method must not.
TIER_A = "Tier A"
CONTEXT = "Context"

REVERSAL = ("Bullish reversal", "Bearish reversal")
BREAK = "Break of structure"
SWEEP = "Liquidity sweep"
EXIT = "Exit"

#: The only names a reader sees, by event kind. Generic by design: they say
#: what to watch, never how it was found.
LABELS: dict[str, str | tuple[str, str]] = {
    "DISPLACE_C_LOW12": REVERSAL,
    "DISPLACE_C": REVERSAL,
    "DELIVERY_SHIFT": REVERSAL,
    "PROTECTED": REVERSAL,
    "M1": REVERSAL,
    "B": REVERSAL,
    "BREACH_REVERT": SWEEP,
    "CLOSE_REVERT": SWEEP,
    "SWEEP_SHIFT": SWEEP,
    "INDUCEMENT": SWEEP,
    "STRUCTURE_SHIFT": BREAK,
    "MAJOR_BOS": BREAK,
    "BREAKER_RETEST": BREAK,
    "RECLAIM": BREAK,
    "PROTECTED_TAKEN": BREAK,
}


def label(kind: str, side: int) -> str:
    """The reader-facing name of an event kind on one side."""
    name = LABELS[kind]
    if isinstance(name, tuple):
        return name[0] if side > 0 else name[1]
    return name


def tier(pattern: str, timeframe: str, klass: str) -> str:
    """Tier A only where the research measured a significant edge; else Context."""
    return TIER_A if evidence(pattern, timeframe, klass).edge else CONTEXT
