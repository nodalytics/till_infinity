"""L1: the token layer. Every bar is one CANDLE token, and every bar after the first one
BAR_RELATION token. The bars themselves (L0) are only the input; the language starts here.

A CANDLE is a fuzzy word, CANDLE(direction, size, body, upper wick, lower wick), after the
fuzzy-candlestick scheme of NautilusTrader's `FuzzyCandlesticks` indicator
(crates/indicators/src/volatility/fuzzy.rs), reimplemented here. Each class says where the bar sits
in the rolling distribution of its own measure over the last PERIOD bars:

    size   the range h - l against the rolling mean m and standard deviation s of ranges
    body   |c - o| / range against its own rolling m and s
    upper  (h - max(o, c)) / range, likewise
    lower  (min(o, c) - l) / range, likewise

A token also carries STRENGTH, graded the same way against its own rolling distribution:

    body_conv   |c - o| / range         conviction       conv_g   WEAK MODERATE STRONG DOMINANT
    body_atr    |c - o| / ATR           force            force_g  WEAK MODERATE STRONG DOMINANT
    X_share     wick / range            (X = upper, lower)  X_share_g  NONE WEAK MODERATE STRONG DOMINANT
    X_atr       wick / ATR              the wick's force    X_g        NONE WEAK MODERATE STRONG DOMINANT
    X_body      wick / max(body, eps)   rejection ratio (not graded: a doji's ratio is unbounded
                                        but for eps, so its rolling sd means nothing)
    close_q     (c - l) / range in quartiles Q1..Q4

and WITHIN-BAR point relations (OPEN_AT_HIGH, ...), equality judged with the tolerance below.

A BAR_RELATION token relates a bar to the previous one: INSIDE / OUTSIDE / HH / LL on the ranges,
ENGULF on the bodies, the close against the mother bar's range, and the full point-relation
matrix - current O, H, L, C against previous O, H, L, C, each ABOVE (+), EQUAL (=) or BELOW (-) -
with the named relations built from it (OPEN_AT_PREV_CLOSE, OPEN_GAP_UP, ...).

A token is a lexeme: it carries its raw bar (open, high, low, close, volume), the bar's true range
and its Wilder ATR(14) as attributes. Pattern events read classes and grades only; level events
(EXTREME, VOID, BREAK, ...) also read the prices, which the classes discard.

Choices the scheme leaves open, made here:
- The rolling statistics include the current bar (INCLUDE_CURRENT), as Nautilus does. It is known
  at the bar's close, so this is causal either way. A consequence: with the bar in its own sample
  of PERIOD, its z-score cannot exceed (PERIOD - 1) / sqrt(PERIOD), 2.85 for 10.
- Before PERIOD values exist the token is still emitted, with direction and lexeme, but the classes
  (and grades) without a full window are WARMUP. Level events need every bar's prices from bar 0.
  The ATR-based grades wait for the ATR as well (bar ATR_N + PERIOD - 1).
- Standard deviations are population ones (ddof = 0). When s = 0 (every value in the window equal)
  every threshold collapses onto m, and a literal reading would call the bar VERY_SMALL; it is
  the middle class instead (MEDIUM, MODERATE: z = 0). A zero value is NONE (WEAK for the body
  grades, which have no NONE) before any threshold is looked at.
- A zero-range bar has body and wick shares of 0: all NONE.
- Close quartiles are decided on a = c - l against b = h - c, so the flip (which swaps a and b
  exactly) maps Qk to Q(5-k): Q4 when a > 3b, Q1 when b > 3a, Q3 when b < a <= 3b, else Q2. The one
  exception is an exact midpoint close (a == b, and a zero-range bar), which is Q2 and stays Q2.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from mcfl.core import (COMPOSITE_POINTS, NAMED_POINTS, NEG_FIELD, POINTS, Dir, Entity, attrs_of, flip_value,
                       make_id, swap_key)

PERIOD = 10
"""Bars in the rolling window each class and grade is measured against (Nautilus' default)."""
T1 = 0.5
"""Threshold 1, in standard deviations: SMALL / MEDIUM for every class, WEAK / MODERATE for grades."""
T2 = 1.0
"""Threshold 2: VERY_SMALL and LARGE for size, LARGE for body, MEDIUM's upper edge for wicks,
STRONG's upper edge for grades."""
T3 = 2.0
"""Threshold 3: VERY_LARGE's upper edge for size; above it, EXTREMELY_LARGE."""
T4 = 3.0
"""Threshold 4: kept for parity with Nautilus, which also defines but never uses it. With the
current bar in a window of 10 it could never be reached (z <= 2.85)."""
INCLUDE_CURRENT = True
"""The rolling window ends at the current bar (True, as Nautilus) or the bar before it."""
ATR_N = 14
"""Wilder ATR length of the lexeme's `atr` (`prims.atr`, as v0)."""
EQ_ATR = 0.05
"""Two price points are EQUAL when they differ by at most tol = max(EQ_ATR * ATR(14), one tick)."""
WICK_BODY_EPS = 0.05
"""The rejection ratio's floor on the body, as a share of the range: wick / max(body, 0.05 range),
so a doji's ratio is at most 20."""

WARMUP = "WARMUP"
SIZE = ("NONE", "VERY_SMALL", "SMALL", "MEDIUM", "LARGE", "VERY_LARGE", "EXTREMELY_LARGE")
BODY = ("NONE", "SMALL", "MEDIUM", "LARGE", "TREND")
WICK = ("NONE", "SMALL", "MEDIUM", "LARGE")
GRADE = ("WEAK", "MODERATE", "STRONG", "DOMINANT")
WGRADE = ("NONE",) + GRADE
QUARTILES = ("Q1", "Q2", "Q3", "Q4")
#: each class's upper edge, in standard deviations from the mean; the last class is everything above
SIZE_EDGES = (-T2, -T1, T1, T2, T3)
BODY_EDGES = (-T1, T1, T2)
WICK_EDGES = (-T1, T2)
GRADE_EDGES = (-T1, T1, T2)
ORDINALS = {"size": SIZE, "body": BODY, "upper": WICK, "lower": WICK, "grade": GRADE, "wgrade": WGRADE,
            "close_q": QUARTILES}
"""Ordered value sets, for the grammar's >= and <= qualifiers."""
RELATIONS = ("INSIDE", "OUTSIDE", "HH", "LL")
CODE = {"NONE": "N", "VERY_SMALL": "VS", "SMALL": "S", "MEDIUM": "M", "LARGE": "L", "VERY_LARGE": "VL",
        "EXTREMELY_LARGE": "XL", "TREND": "T", WARMUP: "W"}
GCODE = {"NONE": "N", "WEAK": "W", "MODERATE": "M", "STRONG": "S", "DOMINANT": "D", WARMUP: "-"}
REL_CODE = {"INSIDE": "IN", "OUTSIDE": "OUT", "HH": "HH", "LL": "LL"}

WITHIN = tuple(k for k, v in NAMED_POINTS.items() if v[0] == "inner")
"""Named relations within the bar (the `inner` matrix): CANDLE attribute `within`."""
NAMED_ALL = tuple(k for k, v in NAMED_POINTS.items() if v[0] == "points") + tuple(COMPOSITE_POINTS)
"""Named relations to the previous bar (the `points` matrix): BAR_RELATION attribute `named`."""
NAME_CODE = {
    "OPEN_AT_PREV_CLOSE": "o=pc", "OPEN_GAP_UP": "o>pc", "OPEN_GAP_DOWN": "o<pc", "OPEN_AT_PREV_OPEN": "o=po",
    "OPEN_ABOVE_PREV_HIGH": "o>ph", "OPEN_BELOW_PREV_LOW": "o<pl", "OPEN_AT_PREV_HIGH": "o=ph",
    "OPEN_AT_PREV_LOW": "o=pl", "CLOSE_AT_PREV_CLOSE": "c=pc", "CLOSE_AT_PREV_OPEN": "c=po",
    "CLOSE_ABOVE_PREV_HIGH": "c>ph", "CLOSE_BELOW_PREV_LOW": "c<pl", "CLOSE_AT_PREV_HIGH": "c=ph",
    "CLOSE_AT_PREV_LOW": "c=pl", "HIGH_ABOVE_PREV_HIGH": "h>ph", "HIGH_AT_PREV_HIGH": "h=ph",
    "HIGH_BELOW_PREV_HIGH": "h<ph", "HIGH_AT_PREV_CLOSE": "h=pc", "HIGH_AT_PREV_OPEN": "h=po",
    "HIGH_AT_PREV_LOW": "h=pl", "HIGH_BELOW_PREV_LOW": "h<pl", "LOW_BELOW_PREV_LOW": "l<pl",
    "LOW_AT_PREV_LOW": "l=pl", "LOW_ABOVE_PREV_LOW": "l>pl", "LOW_AT_PREV_CLOSE": "l=pc",
    "LOW_AT_PREV_OPEN": "l=po", "LOW_AT_PREV_HIGH": "l=ph", "LOW_ABOVE_PREV_HIGH": "l>ph",
    "BODY_MIRROR": "mirror", "OPEN_AT_HIGH": "o=h", "OPEN_AT_LOW": "o=l", "CLOSE_AT_HIGH": "c=h",
    "CLOSE_AT_LOW": "c=l", "OPEN_EQ_CLOSE": "o=c"}
REL_FIELDS = frozenset({"rel", "engulf", "beyond", "mother", "points", "named", *NAMED_ALL, "overlap"})
TEXT_HIDE = frozenset({"OPEN_AT_PREV_CLOSE", "HIGH_ABOVE_PREV_HIGH", "HIGH_BELOW_PREV_HIGH",
                       "LOW_BELOW_PREV_LOW", "LOW_ABOVE_PREV_LOW"})
"""Named relations the compact word text leaves out because they hold on most bars (the open at the
previous close) or repeat the range relation (HH, LL); `word(..., points="all")` prints them."""
"""Columns of the token table that belong to the BAR_RELATION token, not the CANDLE."""
LEXEME = ("open", "high", "low", "close", "volume", "atr", "tr", "tol")
STRENGTH = ("body_conv", "body_atr", "upper_share", "upper_atr", "upper_body",
            "lower_share", "lower_atr", "lower_body")
CLASSES = ("size", "body", "upper", "lower", "conv_g", "force_g", "upper_g", "upper_share_g",
           "lower_g", "lower_share_g", "close_q")


# ---------------------------------------------------------------- classification

def classify(x: np.ndarray, m: np.ndarray, s: np.ndarray, edges: tuple[float, ...],
             names: tuple[str, ...], zero: str) -> np.ndarray:
    """`zero` for a zero value; the middle class when s = 0; otherwise the first of `names` whose
    edge m + k * s the value is at or under, and the last name above every edge."""
    x, m, s = np.broadcast_arrays(*(np.asarray(v, float) for v in (x, m, s)))
    conds = [x == 0, s == 0] + [x <= m + k * s for k in edges]
    middle = names[sum(k < 0 for k in edges)]  # the class whose edges straddle the mean
    return np.select(conds, [zero, middle, *names[:-1]], default=names[-1])


def _rolling(x: np.ndarray, period: int, current: bool) -> tuple[np.ndarray, np.ndarray]:
    """Mean and population sd of each bar's window, summed left to right so a window gives the same
    numbers whatever came before it or after (prefix invariance is exact, not approximate)."""
    n = len(x)
    m, s = np.full(n, np.nan), np.full(n, np.nan)
    first = period - 1 if current else period
    if n <= first:
        return m, s
    end = np.arange(first, n) + (1 if current else 0)  # window is x[end - period : end]
    acc = np.zeros(len(end))
    for j in range(period):
        acc = acc + x[end - period + j]
    mu = acc / period
    acc = np.zeros(len(end))
    for j in range(period):
        acc = acc + (x[end - period + j] - mu) ** 2
    m[first:], s[first:] = mu, np.sqrt(acc / period)
    return m, s


def graded(x: np.ndarray, edges: tuple[float, ...], names: tuple[str, ...], zero: str,
           period: int = PERIOD, current: bool = INCLUDE_CURRENT) -> np.ndarray:
    """Each value classed against its own rolling window; WARMUP where the window is not full."""
    m, s = _rolling(x, period, current)
    cls = classify(x, m, s, edges, names, zero).astype(object)
    cls[np.isnan(m) | np.isnan(x)] = WARMUP
    return cls


def quartile(c: np.ndarray, h: np.ndarray, l: np.ndarray) -> np.ndarray:
    a, b = c - l, h - c
    return np.select([a > 3 * b, b > 3 * a, b < a], ["Q4", "Q1", "Q3"], default="Q2").astype(object)


def _atr(df: pd.DataFrame) -> np.ndarray:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ideas"))
    import prims as P
    return P.atr(df, ATR_N)


def tick_estimate(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    """At each bar, the smallest non-zero price difference seen so far - between the bar's own points
    and against the previous close. Running, so it is causal; it can only shrink as bars arrive."""
    pc = np.r_[c[:1], c[:-1]]
    top, bot = np.maximum(o, c), np.minimum(o, c)
    d = np.abs(np.vstack([o - pc, c - pc, h - l, top - bot, h - top, bot - l]))
    d[d == 0] = np.inf
    return np.minimum.accumulate(d.min(0))


# ---------------------------------------------------------------- the token table

Table = dict[str, np.ndarray]


def table(df: pd.DataFrame, period: int = PERIOD, current: bool = INCLUDE_CURRENT,
          tick: float | None = None) -> Table:
    """Every bar's CANDLE and BAR_RELATION token as columns: the lexeme, the classes, the strength,
    the direction, and the relations to the previous bar. `tick`: the series' price increment, if
    known; otherwise the running smallest non-zero price difference (`tick_estimate`)."""
    df = df.reset_index(drop=True)
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    n = len(c)
    v = df["volume"].to_numpy(float) if "volume" in df else np.full(n, np.nan)
    a = _atr(df)
    pc = np.r_[c[:1], c[:-1]]
    tr = np.maximum(h, pc) - np.minimum(l, pc)
    rng = h - l
    top, bot = np.maximum(o, c), np.minimum(o, c)
    body, up, lo = top - bot, h - top, bot - l
    pos = rng > 0
    safe = np.where(pos, rng, 1.0)
    floor = np.maximum(body, WICK_BODY_EPS * rng)
    floor = np.where(floor > 0, floor, 1.0)
    T: Table = {"open": o, "high": h, "low": l, "close": c, "volume": v, "atr": a, "tr": tr, "range": rng}
    T["body_conv"] = np.where(pos, body / safe, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        T["body_atr"] = np.where(a > 0, body / a, np.nan)
        for k, w in (("upper", up), ("lower", lo)):
            T[f"{k}_share"] = np.where(pos, w / safe, 0.0)
            T[f"{k}_atr"] = np.where(a > 0, w / a, np.nan)
            T[f"{k}_body"] = np.where(pos, w / floor, 0.0)
    T["dir"] = np.where(c > o, "BULL", np.where(c < o, "BEAR", "NONE")).astype(object)

    g = lambda x, e, nm, z: graded(x, e, nm, z, period, current)  # noqa: E731
    T["size"] = g(rng, SIZE_EDGES, SIZE[1:], "NONE")
    T["body"] = g(T["body_conv"], BODY_EDGES, BODY[1:], "NONE")
    T["conv_g"] = g(T["body_conv"], GRADE_EDGES, GRADE, "WEAK")
    T["force_g"] = g(T["body_atr"], GRADE_EDGES, GRADE, "WEAK")
    for k in ("upper", "lower"):
        T[k] = g(T[f"{k}_share"], WICK_EDGES, WICK[1:], "NONE")
        T[f"{k}_share_g"] = g(T[f"{k}_share"], GRADE_EDGES, GRADE, "NONE")
        T[f"{k}_g"] = g(T[f"{k}_atr"], GRADE_EDGES, GRADE, "NONE")
    T["close_q"] = quartile(c, h, l)

    tk = np.full(n, float(tick)) if tick is not None else tick_estimate(o, h, l, c)
    tk = np.where(np.isfinite(tk), tk, 0.0)
    T["tol"] = np.maximum(np.where(a > 0, EQ_ATR * a, 0.0), tk)

    # the two point matrices, the only place point relations read prices; names read the matrices
    prev = {k: np.r_[x[:1], x[:-1]] for k, x in zip(POINTS, (o, h, l, c))}
    cur = dict(zip(POINTS, (o, h, l, c)))
    valid = np.arange(n) >= 1
    cells = {}
    for m, other in (("points", prev), ("inner", cur)):
        for x in POINTS:
            for y in POINTS:
                d = cur[x] - other[y]
                cells[m, x, y] = np.where(d > T["tol"], "+", np.where(d < -T["tol"], "-", "="))
        T[m] = np.array(["".join(cells[m, x, y][t] for x in POINTS for y in POINTS) for t in range(n)], object)
    T["points"][~valid] = None
    for name, (m, x, y, want) in NAMED_POINTS.items():
        T[name] = (cells[m, x, y] == want) & (valid if m == "points" else True)
    for name, need in COMPOSITE_POINTS.items():
        T[name] = np.logical_and.reduce([T[k] for k in need])
    T["within"] = _names(T, WITHIN, n)

    ph, pl, po = prev["H"], prev["L"], prev["O"]
    inside = (h <= ph) & (l >= pl)
    outside = (h > ph) & (l < pl)
    rel = np.where(inside, "INSIDE", np.where(outside, "OUTSIDE", np.where(h > ph, "HH", "LL"))).astype(object)
    ptop, pbot = np.maximum(po, pc), np.minimum(po, pc)
    covers = (top >= ptop) & (bot <= pbot) & (body > ptop - pbot)
    engulf = np.where(covers & (c > o) & (pc < po), "BULL",
                      np.where(covers & (c < o) & (pc > po), "BEAR", "NONE")).astype(object)
    mother = np.zeros(n, int)  # the bar t is measured against: t - 1, or, after inside bars, their mother
    for t in range(1, n):
        mother[t] = mother[t - 1] if t >= 2 and rel[t - 1] == "INSIDE" else t - 1
    beyond = np.where(c > h[mother], "ABOVE", np.where(c < l[mother], "BELOW", "NONE")).astype(object)
    for x in (rel, engulf, beyond):
        x[~valid] = "NONE"
    T.update(rel=rel, engulf=engulf, beyond=beyond, mother=mother, rel_valid=valid)
    T["named"] = _names(T, NAMED_ALL, n)
    return T


def _names(T: Table, names: tuple[str, ...], n: int) -> np.ndarray:
    out = np.empty(n, object)
    for t in range(n):
        out[t] = tuple(sorted(k for k in names if T[k][t]))
    return out


_FLIP_KEEP = frozenset({"rel_valid", "mother"})


def frame(T: Table, side: int) -> Table:
    """The token table as the flipped chart's (side = -1) or as is (+1): prices negated, high and
    low swapped, and every field and value that has a mirror (`core.swap_key`, `core.flip_value`)
    swapped with it. Size, body and every body grade do not change. Rules written for the up side
    read the down side through this."""
    if side > 0:
        return T
    F: Table = {}
    for k, x in T.items():
        if k in _FLIP_KEEP:
            F[k] = x
        elif k in NEG_FIELD:
            F[swap_key(k)] = -x
        elif x.dtype == object:
            m = {v: flip_value(k, v) for v in set(x)}  # few distinct values: flip each once
            y = np.empty(len(x), object)
            y[:] = [m[v] for v in x]
            F[swap_key(k)] = y
        else:
            F[swap_key(k)] = x
    return F


# ---------------------------------------------------------------- tokens as entities

def _dir(cls: str) -> Dir:
    return {"BULL": Dir.UP, "BEAR": Dir.DOWN, "HH": Dir.UP, "LL": Dir.DOWN}.get(cls, Dir.NONE)


def ids(T: Table) -> tuple[list[str], list[str | None]]:
    """CANDLE and BAR_RELATION ids by bar (content ids: type, direction, bar)."""
    n = len(T["close"])
    cid = [make_id("CANDLE", _dir(T["dir"][t]), t) for t in range(n)]
    rid = [make_id("BAR_RELATION", _dir(T["rel"][t]), t) if T["rel_valid"][t] else None for t in range(n)]
    return cid, rid


def _num(x: float) -> float | None:
    return float(x) if np.isfinite(x) else None


_NUM = LEXEME + STRENGTH
_CANDLE_KEYS = tuple(sorted(_NUM + CLASSES + ("within", "inner")))


V2_CANDLE: dict[str, bool] = {}
"""v2 attributes of the CANDLE token, `key -> numeric?`, added to its attributes when the token table
has them (`compression`, `volume.columns`, `timing.columns` add them in a v2 parse)."""
V2_RELATION: dict[str, bool] = {}
"""v2 attributes of the BAR_RELATION token, likewise."""


def entities(T: Table) -> list[Entity]:
    cid, rid = ids(T)
    out = []
    keys = sorted(set(_CANDLE_KEYS) | {k for k in V2_CANDLE if k in T})
    cols = [(k, k in _NUM or V2_CANDLE.get(k, False), T[k]) for k in keys]
    rkeys = [(k, V2_RELATION[k], T[k]) for k in V2_RELATION if k in T]
    for t in range(len(cid)):
        a = tuple((k, _num(x[t]) if num else _plain(x[t])) for k, num, x in cols)  # already in key order
        out.append(Entity(cid[t], "CANDLE", _dir(T["dir"][t]), t, t, a))
        if rid[t] is not None:
            mo = int(T["mother"][t])
            parts = tuple(cid[i] for i in sorted({mo, t - 1, t}))
            out.append(Entity(rid[t], "BAR_RELATION", _dir(T["rel"][t]), t, t, attrs_of(
                {"rel": T["rel"][t], "engulf": T["engulf"][t], "beyond": T["beyond"][t], "mother": mo,
                 "points": T["points"][t], "named": T["named"][t],
                 **{k: (_num(x[t]) if num else _plain(x[t])) for k, num, x in rkeys}}), parts=parts))
    return out


def _plain(x):
    """numpy scalars (a bool column, an int) as Python values; everything else as it is."""
    return x.item() if isinstance(x, np.generic) else x


# ---------------------------------------------------------------- v2 item 2: compression and expansion

NR_SHORT, NR_LONG, WR_N = 4, 7, 7
"""NR4 / NR7: the bar's range is strictly the narrowest of the last 4 / 7 bars (itself included);
WR7: strictly the widest of the last 7."""


def compression(T: Table) -> None:
    """Add the v2 compression and expansion qualifiers to a token table, in place: NR4, NR7, WR7
    (CANDLE) and `overlap` (BAR_RELATION) - the share of the bar's range inside the previous bar's
    range, (min(h, ph) - max(l, pl))+ / (h - l); a zero-range bar is 1 inside it, 0 outside."""
    h, l = T["high"], T["low"]
    rng = h - l
    n = len(rng)
    for name, k, cmp in (("NR4", NR_SHORT, np.less), ("NR7", NR_LONG, np.less), ("WR7", WR_N, np.greater)):
        out = np.zeros(n, bool)
        for t in range(k - 1, n):
            prev = rng[t - k + 1:t]
            out[t] = bool(cmp(rng[t], prev).all())
        T[name] = out
    ph, pl = np.r_[h[:1], h[:-1]], np.r_[l[:1], l[:-1]]
    inside = np.clip(np.minimum(h, ph) - np.maximum(l, pl), 0.0, None)
    with np.errstate(invalid="ignore", divide="ignore"):
        ov = np.where(rng > 0, inside / np.where(rng > 0, rng, 1.0), ((h <= ph) & (l >= pl)).astype(float))
    ov[0] = np.nan
    T["overlap"] = ov
    V2_CANDLE.update(NR4=False, NR7=False, WR7=False)
    V2_RELATION.update(overlap=True)


# ---------------------------------------------------------------- words as text

def _cword(d: str, cls: list[str]) -> str:
    return f"{d}(W)" if cls[0] == WARMUP else f"{d}({','.join(CODE[x] for x in cls)})"


def _sword(force: str, up: str, low: str, q: str) -> str:
    return f"{{b:{GCODE[force]},u:{GCODE[up]},l:{GCODE[low]},q{q[1]}}}"


def word(candle: Entity | None, rel: Entity | None = None, strength: bool = True,
         points: bool | str = True) -> str:
    """One bar as text: BULL(L,T,N,S){b:S,u:W,l:N,q4}/HH+E|c=h,c>ph
      direction(size, body, upper, lower)           the fuzzy word; warm-up bars print BULL(W)
      {b: body force, u / l: wick force, q: close quartile}   grades N W M S D, - in warm-up
      /relation to the previous bar (IN OUT HH LL), +E when the body engulfs
      |named point relations, within the bar and to the previous bar, comma-separated; TEXT_HIDE
       left out unless points="all"
    """
    if candle is None:
        return "?"
    d = {"UP": "BULL", "DOWN": "BEAR", "NONE": "NONE"}[candle.dir.value]
    w = _cword(d, [candle.get(k) for k in ("size", "body", "upper", "lower")])
    if strength:
        w += _sword(candle.get("force_g"), candle.get("upper_g"), candle.get("lower_g"), candle.get("close_q"))
    if rel is not None:
        w += "/" + REL_CODE[rel.get("rel")] + ("+E" if rel.get("engulf") != "NONE" else "")
    if points:
        names = tuple(candle.get("within")) + (tuple(rel.get("named")) if rel is not None else ())
        if points != "all":
            names = tuple(x for x in names if x not in TEXT_HIDE)
        if names:
            w += "|" + ",".join(NAME_CODE[x] for x in names)
    return w


DIR1 = {"BULL": "U", "BEAR": "D", "NONE": "N"}
SIZE3 = {"NONE": "s", "VERY_SMALL": "s", "SMALL": "s", "MEDIUM": "m", "LARGE": "l", "VERY_LARGE": "l",
         "EXTREMELY_LARGE": "l"}
BODY3 = {"NONE": "s", "SMALL": "s", "MEDIUM": "m", "LARGE": "l", "TREND": "l"}
FORCE2 = {"WEAK": "w", "MODERATE": "w", "STRONG": "s", "DOMINANT": "s"}
HALF = {"Q1": "lo", "Q2": "lo", "Q3": "hi", "Q4": "hi"}
ALPHABETS = ("full", "full+s", "coarse", "coarse+s", "rel", "points")


def stream(T: Table, alphabet: str = "full") -> list[str]:
    """The bar-level word stream, from the first bar every class and grade it uses exists.
      full      BULL(L,T,N,S)                direction x size x body x upper x lower
      full+s    BULL(L,T,N,S){b:S,u:W,l:N,q4}  with strength
      coarse    U.l.l                        direction x size in 3 x body in 3 (27 symbols); no strength
      coarse+s  U.l.l.s.hi                   coarse x body force weak|strong x close half (108)
      rel       U.l.l/HH                     coarse x the four relations (108)
      points    o=pc,c>ph                    the set of named point relations, within and to the previous bar
    """
    n = len(T["close"])
    out = []
    need_s = alphabet in ("full+s", "coarse+s")
    for t in range(n):
        if T["size"][t] == WARMUP or (need_s and WARMUP in (T["force_g"][t], T["upper_g"][t], T["lower_g"][t])):
            continue
        if alphabet == "points":
            if not T["rel_valid"][t]:
                continue
            out.append(",".join(NAME_CODE[x] for x in T["within"][t] + T["named"][t]) or "-")
            continue
        d, cls = T["dir"][t], [T[k][t] for k in ("size", "body", "upper", "lower")]
        if alphabet in ("full", "full+s"):
            w = _cword(d, cls)
            if alphabet == "full+s":
                w += _sword(T["force_g"][t], T["upper_g"][t], T["lower_g"][t], T["close_q"][t])
        else:
            w = f"{DIR1[d]}.{SIZE3[cls[0]]}.{BODY3[cls[1]]}"
            if alphabet == "coarse+s":
                w += f".{FORCE2[T['force_g'][t]]}.{HALF[T['close_q'][t]]}"
            if alphabet == "rel" and T["rel_valid"][t]:
                w += "/" + REL_CODE[T["rel"][t]]
        out.append(w)
    return out
