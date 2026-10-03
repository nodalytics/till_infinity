"""v2 item 5: RANGE as a structure (replacing v0's reserved RANGE).

A RANGE is detected causally: at bar t, the RANGE_BARS (k = 10) bars ending at t are confined within
a band of at most RANGE_ATR (x = 2) x ATR(14) at t - high to low. Its box is that window's highest
high (`high`) and lowest low (`low`); it is known at t and its bar is the window's first. One range
is live at a time; after it ends, the next window must start after the bar its escape was confirmed.

While it is live, bar by bar:

    RANGE_TEST↑ / ↓   a bar whose high comes within TEST_ATR (0.1 ATR) of the top (low of the bottom)
                      and whose close stays inside, the first of each run of such bars - a test of
                      that edge (`count`, the edge's tests so far)
    a close beyond    starts an excursion; then
      ESCAPE↑ / ↓     ESCAPE_HOLD (m = 3) consecutive closes beyond the edge, the first of them
                      included: the range ends. At the first close beyond, known at the m-th
      FAILED_ESCAPE   a close back inside (at or within the edge) before that: at the first close
                      beyond, known at the close back. The range lives on, and the failed escape
                      counts as a test of that edge

A RANGE has no direction (Dir.NONE); its events have the direction of the edge. Attributes: RANGE
`high`, `low`, `height_atr`, `atr`, `bars`; the events `range`, `level` (the edge), and ESCAPE the
edges' test counts `upper_tests` and `lower_tests`. Parts: the RANGE its window's CANDLEs, a test
its bar's, an escape (failed or not) the CANDLEs from the first close beyond to the bar that decided
it.
"""
from __future__ import annotations

import numpy as np

from mcfl.candles import Table
from mcfl.core import Dir, Entity, attrs_of, make_id

RANGE_BARS = 10
"""k: bars the box must hold."""
RANGE_ATR = 2.0
"""x: the box is at most this many ATR(14) (at the detecting bar) tall."""
TEST_ATR = 0.1
"""A bar whose extreme comes within this many ATR of an edge, closing inside, tests it."""
ESCAPE_HOLD = 3
"""m: consecutive closes beyond an edge, the first included, that make an ESCAPE."""


def run(T: Table, cid: list[str]) -> list[Entity]:
    h, l, c, a = T["high"], T["low"], T["close"], T["atr"]
    n = len(c)
    out: list[Entity] = []
    start_ok, live = 0, None
    t = 0
    while t < n:
        if live is None:
            s = t - RANGE_BARS + 1
            if s >= start_ok and a[t] > 0:
                top, bot = float(h[s:t + 1].max()), float(l[s:t + 1].min())
                if top - bot <= RANGE_ATR * a[t]:
                    rid = make_id("RANGE", Dir.NONE, s)
                    out.append(Entity(rid, "RANGE", Dir.NONE, s, t, attrs_of({
                        "high": top, "low": bot, "height_atr": float((top - bot) / a[t]), "atr": float(a[t]),
                        "bars": RANGE_BARS}), parts=tuple(cid[s:t + 1])))
                    live = {"id": rid, "top": top, "bot": bot, "tol": TEST_ATR * float(a[t]), "tests": {1: 0, -1: 0},
                            "touch": {1: True, -1: True}, "out": 0, "e": -1, "k": 0}
            t += 1
            continue
        L = live
        top, bot = L["top"], L["bot"]
        if L["out"]:
            side, e = L["out"], L["e"]
            edge = top if side > 0 else bot
            beyond = c[t] > top if side > 0 else c[t] < bot
            d = Dir.of(side)
            if beyond:
                L["k"] += 1
                if L["k"] >= ESCAPE_HOLD:
                    out.append(Entity(make_id("ESCAPE", d, e, f"r{L['id'].split('.')[2]}"), "ESCAPE", d, e, t, attrs_of({
                        "range": L["id"], "level": edge, "upper_tests": L["tests"][1], "lower_tests": L["tests"][-1]}),
                        parts=tuple(cid[e:t + 1])))
                    live, start_ok = None, t + 1
                t += 1
                continue
            out.append(Entity(make_id("FAILED_ESCAPE", d, e, f"r{L['id'].split('.')[2]}"), "FAILED_ESCAPE", d, e, t,
                              attrs_of({"range": L["id"], "level": edge, "bars_out": t - e}), parts=tuple(cid[e:t + 1])))
            L["tests"][side] += 1
            L["out"], L["k"] = 0, 0
            L["touch"][side] = True
            # this bar closed back inside the range: read it again as an inside bar (it may close beyond
            # the other edge)
        if c[t] > top or c[t] < bot:
            L["out"], L["e"], L["k"] = (1 if c[t] > top else -1), t, 1
            t += 1
            continue
        for side, near in ((1, h[t] >= top - L["tol"]), (-1, l[t] <= bot + L["tol"])):
            if near and not L["touch"][side]:
                L["tests"][side] += 1
                d = Dir.of(side)
                out.append(Entity(make_id("RANGE_TEST", d, t, f"r{L['id'].split('.')[2]}"), "RANGE_TEST", d, t, t,
                                  attrs_of({"range": L["id"], "level": top if side > 0 else bot,
                                            "count": L["tests"][side]}), parts=(cid[t],)))
            L["touch"][side] = bool(near)
        t += 1
    return out
