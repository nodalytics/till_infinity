"""MCFL's types: every entity is frozen, has an identity, a direction, the bar it happened at and
the first bar at which it could have been known.

v1: L1 is a token layer. Each bar is one CANDLE token (a fuzzy word that also carries the raw bar
as its lexeme) and, from the second bar, one BAR_RELATION token. L0, the bars, is only the input.

`known_at` is mandatory because it is the one field that keeps the language honest. A swing low at
bar p is not a swing low until three bars later; anything that reads it before then is reading the
future. The truncation test in `tests/test_causality.py` holds every entity to it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: The layer each type lives in. L0 is the bars themselves, the input, and not an entity.
LAYER = {
    "CANDLE": 1, "BAR_RELATION": 1,
    "EXTREME": 2, "VOID": 2, "DISPLACE": 2, "BREAK": 2, "BREACH_REVERT": 2,
    "PIN": 2, "ENGULF": 2, "INSIDE_BREAK": 2, "STAR": 2, "DISPLACE_C": 2, "DELIVERY_SHIFT": 2, "REJECT": 2,
    "REVISIT": 2, "REJECT_PATH": 2, "ACCEPT": 2, "FAIL": 2, "EXPIRE": 2,
    "ORIGIN": 3, "LEG": 3, "ZONE": 3,
    # v2 (see V2_TYPES)
    "SWING": 2, "STRUCTURE_SHIFT": 2, "CHARACTER_SHIFT": 2,
    "VOID_PARTIAL": 2, "VOID_FILLED": 2, "VOID_INVERTED": 2,
    "BALANCE": 2, "IMBALANCE": 2,
    "RANGE_TEST": 2, "ESCAPE": 2, "FAILED_ESCAPE": 2,
    "POOL_TAKEN": 2, "SWEEP_PROTECTED": 2,
    "RETRACE": 2, "PULLBACK": 2,
    "SESSION_OPEN": 2, "SESSION_EXTREME": 2, "SESSION_EXTREME_TAKEN": 2,
    "FOCUS": 2, "FOCUS6": 2, "CUSUM_IGNITION": 2,
    "PURGE": 2, "DISTRIBUTION": 2, "PATTERN": 2,
    "RANGE": 3, "POOL": 3, "DAX50": 3, "DAX_SETUP": 3, "FOCUS_ZONE": 3, "CRT3": 3, "NESTED": 3,
    # the time core (see TIME_TYPES)
    "HTF_CLOSE": 2, "WINDOW_CLOSE": 2, "DAY_OPEN": 2, "WEEK_OPEN": 2, "MONTH_OPEN": 2,
    "TIMEOUT": 2, "STALL": 2, "SESSION_FIRST_MOVE": 2, "LATE": 2, "EARLY": 2, "TEMPO_STATE": 2,
    "WINDOW": 3, "EPISODE": 3, "IN_WINDOW": 3,
    # the sweeps study (see SWEEP_TYPES)
    "CLOSE_REVERT": 2, "INDUCEMENT": 2, "BREAKER_RETEST": 2, "RECLAIM": 2, "PROTECTED_TAKEN": 2,
    "SWEEP_SHIFT": 3, "PROTECTED": 3,
}
V2_TYPES = ("SWING", "STRUCTURE_SHIFT", "CHARACTER_SHIFT", "VOID_PARTIAL", "VOID_FILLED", "VOID_INVERTED",
            "BALANCE", "IMBALANCE", "RANGE", "RANGE_TEST", "ESCAPE", "FAILED_ESCAPE", "POOL", "POOL_TAKEN",
            "SWEEP_PROTECTED", "RETRACE", "PULLBACK", "DAX50", "DAX_SETUP", "SESSION_OPEN", "SESSION_EXTREME",
            "SESSION_EXTREME_TAKEN", "FOCUS", "FOCUS6", "CUSUM_IGNITION", "FOCUS_ZONE", "PURGE", "DISTRIBUTION", "CRT3",
            "PATTERN", "NESTED")
"""The types v2 adds, in the order of the roadmap's items."""
TIME_TYPES = ("EPISODE", "IN_WINDOW", "WINDOW", "WINDOW_CLOSE", "DAY_OPEN", "WEEK_OPEN", "MONTH_OPEN", "HTF_CLOSE",
              "TIMEOUT", "STALL", "SESSION_FIRST_MOVE", "LATE", "EARLY", "TEMPO_STATE")
"""The types the time core adds, in the order of the roadmap's items (1, 2, 4, 6, 8)."""
SWEEP_TYPES = ("CLOSE_REVERT", "SWEEP_SHIFT", "INDUCEMENT", "BREAKER_RETEST", "RECLAIM", "PROTECTED",
               "PROTECTED_TAKEN")
"""The types the sweeps study adds (`sweeps.py`): the close-beyond failure, the sweep and shift,
inducement, a broken structure's return, and protected lows and highs."""
CALENDAR_TYPES = ("WINDOW", "WINDOW_CLOSE", "DAY_OPEN", "WEEK_OPEN", "MONTH_OPEN", "HTF_CLOSE")
"""Anchors the calendar alone decides: the same on a walk given the same timestamps."""
TOKEN_TYPES = tuple(k for k, v in LAYER.items() if v == 1)
EVENT_TYPES = tuple(k for k, v in LAYER.items() if v == 2)
STRUCTURE_TYPES = tuple(k for k, v in LAYER.items() if v == 3)
RELATIONS = ("BEFORE", "AFTER", "TOUCH", "CROSS", "CONTAIN", "INVALIDATE")
#: tie-break inside one bar: what is observed comes before what is interpreted from it
ORDER = {t: i for i, t in enumerate(
    ("CANDLE", "BAR_RELATION",
     # time core: the clock's anchors are observed first - a period closes before the next one opens
     "HTF_CLOSE", "WINDOW_CLOSE", "DAY_OPEN", "WEEK_OPEN", "MONTH_OPEN", "WINDOW",
     "EXTREME", "BREACH_REVERT", "CLOSE_REVERT", "VOID", "PIN", "ENGULF", "INSIDE_BREAK", "STAR", "DISPLACE_C",
     "DELIVERY_SHIFT", "PATTERN", "BALANCE", "IMBALANCE", "PURGE", "SESSION_OPEN", "SESSION_EXTREME",
     "SESSION_EXTREME_TAKEN", "FOCUS", "FOCUS6", "CUSUM_IGNITION",
     "STALL", "SWING", "SESSION_FIRST_MOVE", "STRUCTURE_SHIFT", "VOID_PARTIAL", "VOID_FILLED", "VOID_INVERTED",
     "RANGE", "RANGE_TEST", "FAILED_ESCAPE", "ESCAPE", "POOL", "POOL_TAKEN", "SWEEP_PROTECTED",
     "SWEEP_SHIFT",
     "DISPLACE", "BREAK", "CHARACTER_SHIFT", "PROTECTED", "PULLBACK", "ORIGIN", "LEG", "ZONE", "DAX50", "DAX_SETUP", "FOCUS_ZONE",
     "REVISIT", "INDUCEMENT", "RETRACE", "REJECT_PATH", "REJECT", "ACCEPT", "FAIL", "EXPIRE",
     "BREAKER_RETEST", "RECLAIM", "PROTECTED_TAKEN",
     "DISTRIBUTION", "CRT3", "NESTED",
     "TIMEOUT", "EPISODE", "IN_WINDOW", "TEMPO_STATE", "LATE", "EARLY"))}


class Dir(str, Enum):
    """UP and DOWN; NONE only for L1 tokens with no direction (a doji, an inside bar)."""
    UP = "UP"
    DOWN = "DOWN"
    NONE = "NONE"

    @property
    def arrow(self) -> str:
        return {"UP": "↑", "DOWN": "↓", "NONE": "·"}[self.value]

    @property
    def letter(self) -> str:
        return self.value[0]

    def flip(self) -> Dir:
        return {Dir.UP: Dir.DOWN, Dir.DOWN: Dir.UP, Dir.NONE: Dir.NONE}[self]

    @staticmethod
    def of(side: int) -> Dir:
        return Dir.UP if side > 0 else Dir.DOWN


SIDES = (Dir.UP, Dir.DOWN)
"""The two directions a rule is run in: written for UP, run on the chart and on the chart flipped."""

# How a value reads on the flipped chart (prices negated, highs and lows swapped). One table, used
# by the token frames (`candles.frame`), the grammar's clauses (`view`) and the symmetry test.
NEG_FIELD = frozenset({"open", "high", "low", "close", "price", "level", "far", "near", "extreme_px",
                       # v2
                       "body_mid", "range_mid", "peak", "taker_skew", "swept_level", "upper_edge",
                       "lower_edge"})
"""Price fields: negated under the flip."""
POINTS = "OHLC"
"""Order of the point-relation matrices, row-major: `points` is the bar's O, H, L, C (rows) against
the previous bar's O, H, L, C (columns); `inner` is the bar against itself. Each cell is + (ABOVE),
= (EQUAL within the tolerance) or - (BELOW)."""
_SW = {"O": "O", "H": "L", "L": "H", "C": "C"}
_NEG = {"+": "-", "-": "+", "=": "="}

#: Named point relations, each a production over one matrix cell: (matrix, row, column, class).
NAMED_POINTS = {
    # the open against the previous bar
    "OPEN_AT_PREV_CLOSE": ("points", "O", "C", "="), "OPEN_GAP_UP": ("points", "O", "C", "+"),
    "OPEN_GAP_DOWN": ("points", "O", "C", "-"), "OPEN_AT_PREV_OPEN": ("points", "O", "O", "="),
    "OPEN_ABOVE_PREV_HIGH": ("points", "O", "H", "+"), "OPEN_BELOW_PREV_LOW": ("points", "O", "L", "-"),
    "OPEN_AT_PREV_HIGH": ("points", "O", "H", "="), "OPEN_AT_PREV_LOW": ("points", "O", "L", "="),
    # the close against the previous bar
    "CLOSE_AT_PREV_CLOSE": ("points", "C", "C", "="), "CLOSE_AT_PREV_OPEN": ("points", "C", "O", "="),
    "CLOSE_ABOVE_PREV_HIGH": ("points", "C", "H", "+"), "CLOSE_BELOW_PREV_LOW": ("points", "C", "L", "-"),
    "CLOSE_AT_PREV_HIGH": ("points", "C", "H", "="), "CLOSE_AT_PREV_LOW": ("points", "C", "L", "="),
    # the high against the previous bar
    "HIGH_ABOVE_PREV_HIGH": ("points", "H", "H", "+"), "HIGH_AT_PREV_HIGH": ("points", "H", "H", "="),
    "HIGH_BELOW_PREV_HIGH": ("points", "H", "H", "-"), "HIGH_AT_PREV_CLOSE": ("points", "H", "C", "="),
    "HIGH_AT_PREV_OPEN": ("points", "H", "O", "="), "HIGH_AT_PREV_LOW": ("points", "H", "L", "="),
    "HIGH_BELOW_PREV_LOW": ("points", "H", "L", "-"),
    # the low against the previous bar
    "LOW_BELOW_PREV_LOW": ("points", "L", "L", "-"), "LOW_AT_PREV_LOW": ("points", "L", "L", "="),
    "LOW_ABOVE_PREV_LOW": ("points", "L", "L", "+"), "LOW_AT_PREV_CLOSE": ("points", "L", "C", "="),
    "LOW_AT_PREV_OPEN": ("points", "L", "O", "="), "LOW_AT_PREV_HIGH": ("points", "L", "H", "="),
    "LOW_ABOVE_PREV_HIGH": ("points", "L", "H", "+"),
    # within the bar
    "OPEN_AT_HIGH": ("inner", "O", "H", "="), "OPEN_AT_LOW": ("inner", "O", "L", "="),
    "CLOSE_AT_HIGH": ("inner", "C", "H", "="), "CLOSE_AT_LOW": ("inner", "C", "L", "="),
    "OPEN_EQ_CLOSE": ("inner", "O", "C", "="),
}
COMPOSITE_POINTS = {"BODY_MIRROR": ("OPEN_AT_PREV_CLOSE", "CLOSE_AT_PREV_OPEN")}
"""Conjunctions of named relations: BODY_MIRROR, the bar retraced the previous body exactly."""
POINT_ALIASES = {"HIGH_AT_OPEN": "OPEN_AT_HIGH", "HIGH_AT_CLOSE": "CLOSE_AT_HIGH",
                 "LOW_AT_OPEN": "OPEN_AT_LOW", "LOW_AT_CLOSE": "CLOSE_AT_LOW"}
"""Second names for the same within-bar facts; the grammar's qualifiers accept either."""


def point_twin(name: str) -> str:
    """A named relation's flip twin: H and L swap in both points, ABOVE and BELOW swap."""
    if name in COMPOSITE_POINTS:
        return name  # both its parts are their own twins
    m, x, y, k = NAMED_POINTS[name]
    want = (m, _SW[x], _SW[y], _NEG[k])
    return next(n for n, v in NAMED_POINTS.items() if v == want)


_PAIRS = (("HH", "LL"), ("BULL", "BEAR"), ("ABOVE", "BELOW"), ("Q1", "Q4"), ("Q2", "Q3"),
          # v2: swing labels, structure states, taker skew
          ("LH", "HL"), ("EH", "EL"), ("UP", "DOWN"), ("BUY", "SELL"), ("EQUAL_HIGHS", "EQUAL_LOWS"))
SWAP_VALUE = {**{a: b for a, b in _PAIRS}, **{b: a for a, b in _PAIRS},
              **{n: point_twin(n) for n in NAMED_POINTS if point_twin(n) != n}}
"""Class values and named relations that trade places under the flip; every other value is its
own mirror (size, body, strength grades, INSIDE, OPEN_AT_PREV_CLOSE, ...)."""


def swap_key(k: str) -> str:
    """A field's name on the flipped chart: high and low, and upper and lower (wick) fields, trade
    places; a named-relation column trades with its mirror."""
    if k in ("high", "low"):
        return "low" if k == "high" else "high"
    if k.startswith("upper"):
        return "lower" + k[5:]
    if k.startswith("lower"):
        return "upper" + k[5:]
    return SWAP_VALUE.get(k, k)


def flip_points(s: str) -> str:
    """A point-relation matrix of the flipped chart: H and L swap on both sides, and every ABOVE (+)
    becomes BELOW (-)."""
    out = [""] * 16
    for i, x in enumerate(POINTS):
        for j, y in enumerate(POINTS):
            out[POINTS.index(_SW[x]) * 4 + POINTS.index(_SW[y])] = _NEG[s[i * 4 + j]]
    return "".join(out)


def flip_value(key: str, v: Any) -> Any:
    """Value `v` of field `key` (already read under its flipped name) as the flipped chart has it."""
    if v is None:
        return v
    if isinstance(v, Dir):
        return v.flip()
    if key == "band":
        return (-v[1], -v[0])
    if key in ("points", "inner"):
        return flip_points(v)
    if key in NEG_FIELD:
        return -v
    if isinstance(v, str):
        return SWAP_VALUE.get(v, v)
    if isinstance(v, tuple) and all(isinstance(x, str) for x in v):
        return tuple(sorted(SWAP_VALUE.get(x, x) for x in v))
    return v


def make_id(kind: str, d: Dir, at: int, suffix: str = "") -> str:
    """Ids are built from content, not counters, so the same event parsed from a truncated series
    gets the same id."""
    return f"{kind}.{d.letter}.{at}{'.' + suffix if suffix else ''}"


def freeze(x: Any) -> Any:
    """Lists (from JSON) back to tuples, numpy scalars to Python ones, so entities stay hashable."""
    if isinstance(x, (list, tuple)):
        return tuple(freeze(v) for v in x)
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        return x.item()
    return x


def attrs_of(d: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    return tuple(sorted((k, freeze(v)) for k, v in d.items()))


@dataclass(frozen=True)
class Force:
    """How a leg got through the structure it broke. Units: ATR at the origin, bars."""
    magnitude: float  # (furthest price of the leg through the break - origin extreme) / ATR
    speed: float  # magnitude / duration, ATR per bar
    efficiency: float | None  # net close move / summed |close-to-close| moves, origin to break
    penetration: float  # break close past the reference / ATR
    surprise: float | None  # the leg's mean true range / the mean of the 20 bars before the origin
    duration: int  # bars from origin to break


@dataclass(frozen=True)
class Span:
    """The time core's item 1: an entity as an interval of bars and of wall-clock time.

    `start` and `end` are bars (inclusive); the interval in time is [open of `start`, close of `end`),
    in UTC epoch seconds. `known_at_ts` is the close of the `known_at` bar - the moment the entity
    could first be known. `trade_sec` is the trading time inside the interval (the bars' own lengths
    summed), against the calendar time `seconds`; the difference is the clock's gaps (weekends,
    closures). A calendar WINDOW is known when it opens: its wall-clock end is scheduled
    (`end_ts`), its last bar not yet seen (`end` None). `hour_rate` (item 8) is how common the
    entity's type has been at its hour of day: 24 x the share of the type's recent events that fell
    in that hour (1 is uniform), None for tokens, without timestamps or in warm-up. All are
    attributes of time, so the price flip leaves them unchanged."""
    start: int
    end: int | None
    start_ts: int | None = None
    end_ts: int | None = None
    known_at_ts: int | None = None
    trade_sec: int | None = None
    hour_rate: float | None = None

    @property
    def bars(self) -> int | None:
        return None if self.end is None else self.end - self.start + 1

    @property
    def seconds(self) -> int | None:
        """Calendar time from the first bar's open to the last bar's close."""
        return None if self.start_ts is None or self.end_ts is None else self.end_ts - self.start_ts

    @property
    def gap_sec(self) -> int | None:
        """Calendar time minus trading time: the closures inside the interval."""
        s = self.seconds
        return None if s is None or self.trade_sec is None else s - self.trade_sec


#: Time fields a clause can read by name (`Entity.field`), and how
TIME_FIELDS = {
    "start": lambda s: s.start, "end": lambda s: s.end, "start_ts": lambda s: s.start_ts,
    "end_ts": lambda s: s.end_ts, "known_at_ts": lambda s: s.known_at_ts, "trade_sec": lambda s: s.trade_sec,
    "hour_rate": lambda s: s.hour_rate, "dur_bars": lambda s: s.bars, "dur_sec": lambda s: s.seconds,
    "gap_sec": lambda s: s.gap_sec,
    "interval": lambda s: None if s.end is None else (s.start, s.end + 1),
    "interval_ts": lambda s: None if s.start_ts is None or s.end_ts is None else (s.start_ts, s.end_ts),
}
"""`interval` is the half-open bar interval [start, end + 1), `interval_ts` [start_ts, end_ts): the
operands of the interval relations (`intervals.py`)."""


@dataclass(frozen=True)
class Entity:
    """One event (L2) or structure (L3). Attributes are a sorted tuple of pairs so the dataclass
    stays frozen and hashable; read them with `get`."""
    id: str
    type: str
    dir: Dir
    at: int
    known_at: int
    attrs: tuple[tuple[str, Any], ...] = ()
    force: Force | None = None
    parts: tuple[str, ...] = ()  # constituent ids, for structures
    time: Span | None = None  # the time core: its interval in bars and in time (`clocks.stamp`)

    def __post_init__(self) -> None:
        if self.known_at < self.at:
            raise ValueError(f"{self.id}: known_at {self.known_at} before at {self.at}")

    @property
    def layer(self) -> int:
        return LAYER[self.type]

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self.attrs:
            if k == key:
                return v
        return default

    def field(self, key: str) -> Any:
        """A field or an attribute by name - what the grammar's clauses read."""
        if key in ("id", "type", "dir", "at", "known_at"):
            return getattr(self, key)
        if key in TIME_FIELDS:
            return None if self.time is None else TIME_FIELDS[key](self.time)
        if key == "id_suffix":  # what tells apart same-type entities on one bar (`ZONE.U.57.z3` -> z3)
            rest = self.id.split(".", 3)
            return rest[3] if len(rest) > 3 else ""
        return self.get(key)

    @property
    def known_at_ts(self) -> int | None:
        return None if self.time is None else self.time.known_at_ts


@dataclass(frozen=True)
class Relation:
    kind: str
    src: str
    dst: str
    known_at: int


@dataclass(frozen=True)
class Failure:
    """A candidate the grammar refused, and why. Reported, never silently dropped."""
    candidate: str
    rule: str
    slot: str
    clause: str
    known_at: int


@dataclass(frozen=True)
class Transition:
    zone: str
    src: str
    dst: str
    at: int
    known_at: int
    event: str  # the entity whose arrival caused it


@dataclass(frozen=True)
class Chart:
    """A parsed series. `states` is each zone's state at the last bar - a property of where the
    series stops, so unlike everything else it has no `known_at` and is not prefix-invariant."""
    n: int
    entities: tuple[Entity, ...]
    relations: tuple[Relation, ...] = ()
    failures: tuple[Failure, ...] = ()
    transitions: tuple[Transition, ...] = ()
    states: tuple[tuple[str, str], ...] = ()
    pending: tuple[str, ...] = field(default=())  # candidates still FORMING at the last bar
    clock: Any = field(default=None, compare=False, repr=False)  # time core: the bars' `clocks.Clock`

    def by_id(self) -> dict[str, Entity]:
        return {e.id: e for e in self.entities}

    def of(self, *types: str) -> list[Entity]:
        return [e for e in self.entities if e.type in types]


def sort_key(e: Entity) -> tuple:
    """By known_at; within a bar, observations before what is built from them (ORDER), then by bar."""
    return (e.known_at, ORDER[e.type], e.at, e.dir.value, e.id)


def view(e: Entity, key: str, side: int) -> Any:
    """A field of `e` as it reads in the frame of `side`: as is for +1, on the flipped chart for -1.
    Grammar clauses are written for the up side and read their entities through this."""
    if side > 0:
        return e.field(key)
    return flip_value(key, e.field(swap_key(key)))


# relations computed on demand: the temporal pair is too many to materialise
def before(a: Entity, b: Entity) -> bool:
    """BEFORE(a, b): a happened at an earlier bar than b."""
    return a.at < b.at


def after(a: Entity, b: Entity) -> bool:
    """AFTER(a, b): the converse of BEFORE."""
    return a.at > b.at
