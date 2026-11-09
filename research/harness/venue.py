"""The venue's own quoted round trip, in one place.

**Why this file exists.** Five harnesses grew their own copy of `quoted` -
`clockfloor`, `fivevsfifteen`, `fastimpulse`, `itb1h` and `synthma` - and every
copy had the same defect: the symbol went into the URL path unencoded. This
venue's index, energy and synthetic names carry spaces ("US SP 500", "Volatility
75 (1s) Index"), so the request returned nothing and the cost column read `nan`
for exactly those instruments.

It was fixed three times, in three files, and bit a fourth. The bug is not the
missing `quote()`; the bug is five vocabularies for one question, which is the
shape `adapters/mt5/proxy.TIMEFRAMES` warns about in its own comment and which
a consistency test now guards in the package. This is the research side of the
same lesson.

**The failure mode is quiet, which is why it kept recurring.** A missing spread
does not raise. It becomes `nan`, `nan` propagates into a cost ratio, and the
ratio prints as `nan%` beside a perfectly healthy-looking row count - so a
screen whose whole purpose is cost reports every spaced instrument as
unmeasured and nothing says why. The first version of `synthma` went further
and used `np.nansum`, which **dropped** the affected bars instead of carrying
the nan, producing a `net` larger than its own `gross`.
"""

from __future__ import annotations

import json
import os
import urllib.parse as parse
import urllib.request as request
from pathlib import Path

BASE = os.environ.get("BRIDGE", "http://localhost:8000") + "/api/v1"

#: Round trips recorded by `btccost.py` on 2026-11-07, used only when the
#: bridge will not answer. **Per symbol**, because costing one instrument with
#: another's spread invents the result: ETHUSD's round trip is 1.58 px against
#: BTCUSD's 18.86.
FALLBACK_PX: dict[str, float] = {"BTCUSD": 18.86, "ETHUSD": 1.58}


def quoted(symbol: str, *, timeout: float = 30.0) -> float:
    """The terminal's own bid-ask spread in price, or `nan`.

    `nan` rather than a guess, and never a zero: a zero would read as a free
    round trip and make every cost ratio pass. A caller that cannot proceed
    without a cost must check `isfinite`.

    The per-bar `spread` column on stored bars is deliberately **not** a
    fallback. This repository measured it as unusable as a level - zero on
    7-35% of bars and a median 3-8x below the terminal's quote, 2.7x on ETHUSD
    - so a cost taken from it is the one number that looks like a measurement
    and is not.
    """
    try:
        key = (Path.home() / ".mt5key").read_text().strip()
        req = request.Request(  # noqa: S310 - a fixed https-less local bridge
            f"{BASE}/symbols/info/{parse.quote(symbol)}",
            headers={"X-API-Key": key},
        )
        with request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            spec = json.loads(response.read().decode())
        bid, ask = float(spec.get("bid") or 0.0), float(spec.get("ask") or 0.0)
        if ask > bid:
            return ask - bid
    except Exception:  # noqa: BLE001 - any failure means "it did not say"
        pass
    return float(FALLBACK_PX.get(symbol, float("nan")))
