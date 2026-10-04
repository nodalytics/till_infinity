"""v2 item 10: multiple timeframes.

AGGREGATION. A higher-timeframe (HTF) bar is built from the lower timeframe's (LTF) CANDLE tokens: the
first token's open, the highest high, the lowest low, the last close, the summed volume (and taker
volumes). Bars are grouped by time (`ts // htf_sec`) when there are timestamps, else by count
(`factor`, from bar 0). An HTF bar is COMPLETE, and everything read from it known, at the LTF bar that
closes its period (its `ts` + the LTF bar's length reaches the period's end), or, when bars are
missing at the period's end, at the first LTF bar of the next period; by count, at its last bar. The
incomplete last bar is never used. The HTF chart is then parsed as any chart (`parse`), so its CANDLE
words are fuzzy classes of the HTF bars against the HTF history. `parse_mtf(df, htf=...)` parses a
given HTF chart instead (the broker's 4h bars, say), mapped onto the LTF bars by time.

Every HTF entity is read in LTF time: its bar spans the LTF bars of its HTF bar(s) and it is known at
the LTF bar at which its HTF `known_at` bar is complete (`MTF.known`). HTF ids are prefixed with the
label (`4h:BREAK.U.66.o57`).

RELATIONS (`MTF.relations`), each known when both ends are:
    CONTAINS_TF(H, L)  the HTF entity spans L's bar. Materialised for HTF CANDLE -> its LTF CANDLEs (the
                       aggregation's derivation); computed on demand for any pair (`MTF.contains`). An
                       HTF entity's span is its own bar, a BREAK's its leg (origin to break), a LEG's
                       origin to end, a ZONE's origin to break, a RANGE's window
    ALIGN / CONFLICT   an LTF ZONE or BREAK against (a) the HTF STRUCTURE state known when the LTF
                       entity is (ALIGN when it is the entity's direction, CONFLICT when opposite; MIXED
                       gives neither) - dst the HTF STRUCTURE_SHIFT that set the state; (b) the leg of an
                       HTF BREAK that spans the LTF entity's bar and is KNOWN by the LTF entity's
                       known_at - ALIGN same direction, CONFLICT opposite.

NESTED (L3), the desk's strongest finding as one production (`zone_nested.py`, "inside_4h"): an LTF
ZONE whose ORIGIN lies inside the leg of an HTF BREAK of the same direction,

    NESTED_UP := ZONE_UP@LTF  where ZONE.at in span(BREAK_UP@HTF) and known(BREAK) <= ZONE.known_at

The CAUSAL form above is the default: the relation holds only once the HTF break is known in LTF time
at or before the LTF zone is. The research flag (`nested_flags(mode="research")`) did not ask that: it
read any HTF break whose leg spans the origin, including breaks that happen, or are confirmed, after
the LTF zone formed - and only breaks `zone_events` had recorded, which are those whose own zone was
later returned to (a selection by the future). That form reproduces `inside_4h` exactly and exists for
that test; it is not a relation of the language.

MULTI-TIMEFRAME CRT (`MTF.entities`): an HTF CANDLE as the RANGE_CANDLE, its PURGE seen on the LTF: the
first LTF candle inside the next HTF bar (CONTAINS_TF) whose high is beyond the HTF candle's high and
whose close is back inside the HTF range (PURGE, at that LTF bar); DISTRIBUTION the first LTF candle,
before the end of HTF bar j + CRT_N, reaching the HTF range's other side; CRT3 the three.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from mcfl.core import SIDES, Chart, Dir, Entity, Relation, attrs_of, make_id
from mcfl.crt import CRT_N
from mcfl.parse import parse

ZONE_EVENTS_EXPIRE, ZONE_EVENTS_BUF, ZONE_EVENTS_LIVE = 500, 0.1, 5
"""zone_events' EXPIRE, BUF and the 5 bars after the break before a zone is live - only for the
research form's selection of HTF breaks (`zone_events_recorded`)."""


@dataclass(frozen=True)
class MTF:
    ltf: Chart
    htf: Chart
    label: str
    first: tuple[int, ...]  # per HTF bar: its first LTF bar
    last: tuple[int, ...]  # its last LTF bar
    known: tuple[int, ...]  # the LTF bar at which it is complete
    keys: tuple[int, ...]  # its period's number (ts // htf_sec, or bar // factor)
    pkey: tuple[int, ...]  # per LTF bar: the number of the period it falls in (complete or not)
    htf_df: pd.DataFrame = field(compare=False, repr=False)
    relations: tuple[Relation, ...] = ()
    entities: tuple[Entity, ...] = ()

    def hid(self, e: Entity) -> str:
        return f"{self.label}:{e.id}"

    def known_ltf(self, e: Entity) -> int:
        """The LTF bar at which an HTF entity is known."""
        return self.known[e.known_at]

    def span(self, e: Entity) -> tuple[int, int]:
        """The LTF bars an HTF entity spans."""
        a, b = e.at, e.at
        if e.type == "BREAK":
            a = int(e.get("origin").split(".")[2])
        elif e.type == "LEG":
            b = e.get("end") if e.get("end") is not None else e.at
        elif e.type == "ZONE":
            b = e.get("break_at")
        elif e.type == "RANGE":
            b = e.known_at
        return self.first[a], self.last[b]

    def contains(self, h: Entity, lt: Entity) -> Relation | None:
        """CONTAINS_TF(h, lt), on demand: h's span holds lt's bar."""
        a, b = self.span(h)
        if a <= lt.at <= b:
            return Relation("CONTAINS_TF", self.hid(h), lt.id, max(self.known_ltf(h), lt.known_at))
        return None

    def by_id(self) -> dict[str, Entity]:
        out = self.ltf.by_id()
        out.update({self.hid(e): e for e in self.htf.entities})
        out.update({e.id: e for e in self.entities})
        return out


# ---------------------------------------------------------------- aggregation

def _lexemes(ch: Chart) -> pd.DataFrame:
    c = sorted(ch.of("CANDLE"), key=lambda e: e.at)
    return pd.DataFrame({k: [e.get(k) for e in c] for k in ("open", "high", "low", "close", "volume")})


def period_keys(df: pd.DataFrame, htf_sec: int | None, factor: int | None) -> np.ndarray:
    """Per LTF bar, the number of the HTF period it falls in."""
    if htf_sec is not None and "ts" in df:
        return df["ts"].to_numpy(np.int64) // htf_sec
    return np.arange(len(df)) // factor


def groups(df: pd.DataFrame, htf_sec: int | None, factor: int | None,
           ltf_sec: int | None = None) -> list[tuple[int, int, int, int, int]]:
    """Complete HTF bars as (first LTF bar, last LTF bar, LTF bar it is known at, HTF open ts, period)."""
    n = len(df)
    out = []
    if htf_sec is not None and "ts" in df:
        ts = df["ts"].to_numpy(np.int64)
        if ltf_sec is None:
            ltf_sec = int(ts[1] - ts[0]) if n >= 2 else htf_sec
        key = ts // htf_sec
        starts = [0] + [i for i in range(1, n) if key[i] != key[i - 1]]
        for j, a in enumerate(starts):
            b = (starts[j + 1] - 1) if j + 1 < len(starts) else n - 1
            end = (key[a] + 1) * htf_sec
            if ts[b] + ltf_sec >= end:
                known = b
            elif j + 1 < len(starts):
                known = starts[j + 1]
            else:
                continue  # the period is not over yet
            out.append((a, b, known, int(key[a] * htf_sec), int(key[a])))
        return out
    if factor is None:
        raise ValueError("give htf_sec (with a ts column) or factor")
    for a in range(0, n - factor + 1, factor):
        out.append((a, a + factor - 1, a + factor - 1, a, a // factor))
    return out


def aggregate(ltf: Chart, df: pd.DataFrame, gs: list[tuple[int, int, int, int, int]]) -> pd.DataFrame:
    """HTF bars from the LTF CANDLE tokens' lexemes."""
    lx = _lexemes(ltf)
    rows = []
    for a, b, _, t0, _ in gs:
        seg = lx.iloc[a:b + 1]
        r = dict(open=seg["open"].iloc[0], high=seg["high"].max(), low=seg["low"].min(), close=seg["close"].iloc[-1],
                 volume=seg["volume"].sum())
        if "ts" in df:
            r["ts"] = t0
        for k in ("taker_buy_volume", "taker_sell_volume"):
            if k in df:
                r[k] = df[k].iloc[a:b + 1].sum()
        rows.append(r)
    return pd.DataFrame(rows, columns=None if rows else ["open", "high", "low", "close", "volume"])


# ---------------------------------------------------------------- the production and the relations

def _break_legs(m: MTF, d: Dir | None = None) -> list[Entity]:
    return [e for e in m.htf.of("BREAK") if d is None or e.dir is d]


def nested(m: MTF) -> list[Entity]:
    """NESTED, causal: LTF ZONEs whose origin is inside a same-direction HTF BREAK's leg known by then."""
    out = []
    for z in m.ltf.of("ZONE"):
        hs = sorted((h for h in _break_legs(m, z.dir)
                     if m.span(h)[0] <= z.at <= m.span(h)[1] and m.known_ltf(h) <= z.known_at),
                    key=lambda h: (m.known_ltf(h), h.at, h.id))
        if hs:
            h = hs[0]
            out.append(Entity(make_id("NESTED", z.dir, z.at), "NESTED", z.dir, z.at, z.known_at, attrs_of({
                "of_zone": z.id, "htf_break": m.hid(h), "htf_breaks": len(hs), "tf": m.label}),
                parts=(z.id, m.hid(h))))
    return out


def nested_flags(m: MTF, mode: str = "causal", htf_df: pd.DataFrame | None = None) -> dict[str, bool]:
    """For every LTF ZONE: is its origin inside a same-direction HTF break's leg?

    causal    (the default, = the NESTED entities) the HTF break known by the zone's known_at
    entry     known by the zone's first REVISIT instead (zone_nested's own later correction, CAUSAL=1:
              known before the entry) - causal for a trade entered at the revisit, not for the zone
    leg       any HTF break whose leg spans the origin, whenever known: NOT causal
    research  `leg`, restricted to the HTF breaks zone_events recorded (`zone_events_recorded`, a
              selection by the future too): zone_nested.py's "inside_4h", exactly. NOT causal
    """
    zones = m.ltf.of("ZONE")
    if mode == "causal":
        hit = {e.get("of_zone") for e in nested(m)}
        return {z.id: z.id in hit for z in zones}
    legs = m.htf.of("BREAK")
    if mode == "research":
        rec = zone_events_recorded(m.htf, m.htf_df if htf_df is None else htf_df)
        legs = [h for h in legs if h.id in rec]
    first_rev: dict[str, int] = {}
    for r in sorted(m.ltf.of("REVISIT"), key=lambda e: e.known_at):
        first_rev.setdefault(r.get("zone"), r.known_at)
    out = {}
    for z in zones:
        by = first_rev.get(z.id, -1) if mode == "entry" else None
        out[z.id] = any(h.dir is z.dir and m.span(h)[0] <= z.at <= m.span(h)[1]
                        and (by is None or m.known_ltf(h) <= by) for h in legs)
    if mode not in ("entry", "leg", "research"):
        raise ValueError(mode)
    return out


def zone_events_recorded(htf: Chart, df: pd.DataFrame) -> set[str]:
    """The HTF BREAKs zone_events.events records a row for: 5 bars after the break exist, and, under
    one of its four bounds (body, candle, wick, cluster), the zone was returned to (a low at the near
    edge) after it went live and before a close through the far edge or EXPIRE bars. A selection that
    reads the future, reproduced only for the research form."""
    out = set()
    for e in htf.of("BREAK"):
        side = 1 if e.dir is Dir.UP else -1
        F = df if side > 0 else df.assign(open=-df["open"], close=-df["close"], high=-df["low"], low=-df["high"])
        o, h, l, c = (F[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        n = len(c)
        p, b = int(e.get("origin").split(".")[2]), e.at
        if b + ZONE_EVENTS_LIVE >= n:
            continue
        ori = htf.by_id()[e.get("origin")]
        A, low = ori.get("atr"), l[p]
        live = max(ori.known_at, b + ZONE_EVENTS_LIVE)
        bounds = ((low, max(o[p], c[p])), (low, h[p]), (low, min(o[p], c[p])),
                  (l[max(0, p - 2):p + 1].min(), max(np.maximum(o, c)[max(0, p - 2):p + 1].max(), low)))
        for far, near in bounds:
            near = max(near, far + 0.05 * A)
            ret = False
            for k in range(live + 1, min(n, live + ZONE_EVENTS_EXPIRE)):
                if c[k] < far - ZONE_EVENTS_BUF * A:
                    break
                if l[k] <= near:
                    ret = True
                    break
            if ret:
                out.add(e.id)
                break
    return out


def _structure(m: MTF) -> tuple[list[int], list[Entity]]:
    sh = sorted(m.htf.of("STRUCTURE_SHIFT"), key=lambda e: (m.known_ltf(e), e.at))
    return [m.known_ltf(e) for e in sh], sh


def align(m: MTF, types: tuple[str, ...] = ("ZONE", "BREAK")) -> list[Relation]:
    """ALIGN / CONFLICT of LTF entities against the HTF structure and the HTF break legs (causal)."""
    ks, sh = _structure(m)
    legs = _break_legs(m)
    out = []
    for e in m.ltf.of(*types):
        i = bisect.bisect_right(ks, e.known_at) - 1
        if i >= 0 and sh[i].get("to") in ("UP", "DOWN"):
            kind = "ALIGN" if sh[i].get("to") == e.dir.value else "CONFLICT"
            out.append(Relation(kind, e.id, m.hid(sh[i]), e.known_at))
        for h in legs:
            a, b = m.span(h)
            if a <= e.at <= b and m.known_ltf(h) <= e.known_at:
                out.append(Relation("ALIGN" if h.dir is e.dir else "CONFLICT", e.id, m.hid(h), e.known_at))
    return out


def contains_candles(m: MTF) -> list[Relation]:
    ltf_c = sorted(m.ltf.of("CANDLE"), key=lambda e: e.at)
    out = []
    for hc in m.htf.of("CANDLE"):
        a, b = m.first[hc.at], m.last[hc.at]
        for lc in ltf_c[a:b + 1]:
            out.append(Relation("CONTAINS_TF", m.hid(hc), lc.id, m.known[hc.at]))
    return out


def crt(m: MTF) -> list[Entity]:
    """Multi-timeframe CRT: an HTF candle's PURGE seen on the LTF candles of the next HTF period, by
    the LTF bars' own periods - so it is found at its LTF bar, before the next HTF bar is complete."""
    hc = sorted(m.htf.of("CANDLE"), key=lambda e: e.at)
    lc = sorted(m.ltf.of("CANDLE"), key=lambda e: e.at)
    pk = np.asarray(m.pkey)
    out = []
    for j, H in enumerate(hc):
        nxt = np.flatnonzero(pk == m.keys[j] + 1)
        if not len(nxt):
            continue
        for side, d in zip((1, -1), SIDES):
            hi, lo = (H.get("high"), H.get("low")) if side > 0 else (-H.get("low"), -H.get("high"))
            u = next((int(t) for t in nxt if t >= m.known[j]
                      and side * (lc[t].get("high") if side > 0 else lc[t].get("low")) > hi
                      and lo <= side * lc[t].get("close") <= hi), None)
            if u is None:
                continue
            pid = make_id("PURGE", d, u, f"{m.label}{j}")
            out.append(Entity(pid, "PURGE", d, u, u, attrs_of({
                "tf": m.label, "range_candle": m.hid(H), "upper_edge": H.get("high"), "lower_edge": H.get("low"),
                "range_mid": (H.get("high") + H.get("low")) / 2}), parts=(m.hid(H), lc[u].id)))
            mid = (hi + lo) / 2
            hit_mid = -1
            for t in range(u + 1, len(lc)):
                if pk[t] > m.keys[j] + 1 + CRT_N:
                    break
                x = side * (lc[t].get("low") if side > 0 else lc[t].get("high"))
                if hit_mid < 0 and x <= mid:
                    hit_mid = t
                if x <= lo:
                    dd = d.flip()
                    did = make_id("DISTRIBUTION", dd, t, f"p{u}{m.label}")
                    out.append(Entity(did, "DISTRIBUTION", dd, t, t, attrs_of({
                        "purge": pid, "bars": t - u, "mid_bars": hit_mid - u if hit_mid >= 0 else -1,
                        "mid_same_bar": hit_mid == t, "tf": m.label}), parts=(lc[t].id,)))
                    out.append(Entity(make_id("CRT3", dd, u, f"{m.label}{j}"), "CRT3", dd, u, t, attrs_of({
                        "purge": pid, "bars": t - u, "tf": m.label}), parts=(m.hid(H), pid, did)))
                    break
    return out


def parse_mtf(df: pd.DataFrame, htf_sec: int | None = None, factor: int | None = None, label: str = "htf",
              htf: pd.DataFrame | None = None, ltf_sec: int | None = None, changepoints: bool = False) -> MTF:
    """Parse the LTF bars, build (or take) the HTF bars, parse them, and relate the two charts."""
    df = df.reset_index(drop=True)
    ltf = parse(df, changepoints=changepoints)
    if htf is None:
        gs = groups(df, htf_sec, factor, ltf_sec)
        hdf = aggregate(ltf, df, gs)
    else:
        gs = _map(df, htf, htf_sec, ltf_sec)
        hdf = htf.iloc[:len(gs)].reset_index(drop=True)
    hch = parse(hdf) if len(hdf) else Chart(n=0, entities=())
    pk = tuple(int(x) for x in period_keys(df, htf_sec, factor))
    m = MTF(ltf, hch, label, tuple(g[0] for g in gs), tuple(g[1] for g in gs), tuple(g[2] for g in gs),
            tuple(g[4] for g in gs), pk, hdf)
    rels = contains_candles(m) + align(m)
    ents = nested(m) + crt(m)
    return MTF(ltf, hch, label, m.first, m.last, m.known, m.keys, m.pkey, hdf,
               tuple(sorted(rels, key=lambda r: (r.known_at, r.kind, r.src, r.dst))),
               tuple(sorted(ents, key=lambda e: (e.known_at, e.at, e.id))))


def _map(df: pd.DataFrame, htf: pd.DataFrame, htf_sec: int, ltf_sec: int | None) -> list[tuple[int, int, int, int, int]]:
    """A given HTF chart's bars onto the LTF bars by time; only HTF bars complete in the LTF data."""
    gs = {g[3]: g for g in groups(df, htf_sec, None, ltf_sec)}
    out = []
    for t0 in htf["ts"].to_numpy(np.int64):
        if int(t0) not in gs:
            break
        out.append(gs[int(t0)])
    return out
