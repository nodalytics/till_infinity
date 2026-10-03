"""v2 item 9: changepoints as events, from the desk's own detectors, called read-only.

FOCUS (UP / DOWN): production's FOCuS detector as the research replays it
(`research/ideas/prims.focus_series`, which runs `till_infinity.structures.learning.focus.Focus`),
fed exactly what `zone_events.py` feeds it:

    x       the close-to-close change, 0 on the first bar
    scale   the EWM (span 100) of |x|, shifted one bar, x sqrt(pi / 2)
    up      FOCUS↑ runs the detector for an increase, FOCUS↓ for a decrease, each resetting after a fire
    threshold  12 + 3 ln(3600 / sec), at least 3 (sec: the bar's length in seconds); FOCUS6 is the
               sensitive variant at 6

Each fire is an event whose `at` is the bar the change started (the detector's `at`) and whose
`known_at` is the bar it fired; parts the CANDLEs from one to the other. Attributes `threshold`,
`lag` (fire - start).

CUSUM_IGNITION (UP / DOWN): `research/ideas/survivors.cusum` with k = 0.5, h = 5 - the first bar
the up (down) sum of log returns, drifting k sigma, crosses h sigma (sigma: the 60-bar sd of log
returns, lagged 30), re-armed when the sum returns to 0. At and known at that bar; attributes `k`,
`h`. Log returns need positive prices: its mirror is the log-price flip (prices inverted), not the
arithmetic flip, so CUSUM_IGNITION↓ of a chart is CUSUM_IGNITION↑ of the chart inverted.

The detectors are optional in a parse (`parse(df, changepoints=True)`): they import production's
package, and CUSUM has no meaning on the flipped (negative) chart the symmetry test parses.

FOCUS_ZONE (L3) uses them in a production, zone_events' `fc_origin` made causal: a ZONE with a FOCUS
of its direction whose change started within 3 bars of the zone's origin and which fired by the time
the zone was known.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from mcfl.core import SIDES, Dir, Entity, attrs_of, make_id
from mcfl.grammar import C, Rule, Slot

_IDEAS = Path(__file__).resolve().parents[1] / "ideas"
_ROOT = Path(__file__).resolve().parents[2]

FOCUS_BASE = 12.0
"""Production FOCuS threshold at 1h; zone_events: max(12 + 3 ln(3600 / sec), 3)."""
FOCUS_SENSITIVE = 6.0
"""zone_events' `focus6`: the sensitive variant, at any bar length."""
CUSUM_K, CUSUM_H = 0.5, 5.0
"""survivors.cusum's drift and line, in sigma (the replicated setting)."""
ORIGIN_BARS = 3
"""FOCUS_ZONE: the change starts within this many bars of the zone's origin (zone_events' fc_origin)."""


def _research():
    for p in (str(_IDEAS), str(_ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    import prims as P
    from survivors import cusum
    return P, cusum


def threshold(sec: float) -> float:
    return max(FOCUS_BASE + 3.0 * math.log(3600.0 / sec), 3.0)


def bar_seconds(df: pd.DataFrame, sec: float | None) -> float:
    """The bar's length: given, or the first two bars' timestamps apart, or an hour."""
    if sec is not None:
        return float(sec)
    if "ts" in df and len(df) >= 2:
        return float(df["ts"].iloc[1] - df["ts"].iloc[0])
    return 3600.0


def focus(df: pd.DataFrame, cid: list[str], sec: float) -> list[Entity]:
    P, _ = _research()
    c = df["close"].to_numpy(float)
    rr = np.r_[0.0, np.diff(c)]
    scale = pd.Series(np.abs(rr)).ewm(span=100).mean().shift(1).to_numpy() * np.sqrt(np.pi / 2)
    out = []
    for kind, th in (("FOCUS", threshold(sec)), ("FOCUS6", FOCUS_SENSITIVE)):
        for d, up in zip(SIDES, (True, False)):
            fired, at = P.focus_series(rr, scale, th, up)
            for i in np.flatnonzero(fired):
                i, a = int(i), int(at[i])
                out.append(Entity(make_id(kind, d, a, f"f{i}"), kind, d, a, i, attrs_of({
                    "threshold": float(th), "lag": i - a}), parts=tuple(cid[a:i + 1])))
    return out


def cusum(df: pd.DataFrame, cid: list[str]) -> list[Entity]:
    P, cus = _research()
    a = P.atr(df, 14)
    cs = cus(df, a, k=CUSUM_K, h=CUSUM_H)
    out = []
    for i, side in zip(cs["i"].to_numpy(int), cs["side"].to_numpy(int)):
        d = Dir.of(int(side))
        out.append(Entity(make_id("CUSUM_IGNITION", d, int(i)), "CUSUM_IGNITION", d, int(i), int(i), attrs_of({
            "k": CUSUM_K, "h": CUSUM_H}), parts=(cid[int(i)],)))
    return out


def _rule(kind: str) -> Rule:
    return Rule(
        head="FOCUS_ZONE", anchor="zone", horizon=None, report=False, suffix=("t", "focus.threshold"),
        attrs=lambda b, d: {"of_zone": b["zone"][0].id, "focus": b["focus"][0].id,
                            "threshold": b["focus"][0].get("threshold"), "lag": b["focus"][0].get("lag")},
        decide="zone.known_at",
        slots=(
            Slot("zone", "ZONE"),
            Slot("focus", kind, where=(
                C("at", ">=", ("+", "zone.at", -ORIGIN_BARS)),
                C("at", "<=", ("+", "zone.at", ORIGIN_BARS)))),
        ),
        sequence=("zone", "focus"),
    )


RULES = {"FOCUS_ZONE": _rule("FOCUS"), "FOCUS6_ZONE": _rule("FOCUS6")}
"""FOCUS_ZONE_UP := ZONE_UP FOCUS_UP    where |FOCUS.at - ZONE.at| <= 3 and FOCUS.known_at <= ZONE.known_at
(and the same with FOCUS6; the id's suffix is the threshold)"""
