"""Hand-built bars. Each bar opens at the last close and carries a WICK-wide wick on both sides of
its body, so the warm-up's true range is exactly 1 and ATR starts at 1."""
from __future__ import annotations

import numpy as np
import pandas as pd

WICK = 0.25
WARMUP = [100.0, 100.5] * 10  # 20 bars, true range 1, no swing (equal highs are not strictly above)


def bars(closes: list[float], first_open: float | None = None) -> pd.DataFrame:
    c = np.asarray(closes, float)
    o = np.r_[c[0] if first_open is None else first_open, c[:-1]]
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + WICK, "low": np.minimum(o, c) - WICK,
                         "close": c, "volume": 1.0})


# a swing high at 102 (high 102.25), a fall to an origin at 99 (low 98.75, body top 99.5), then a
# leg with a gap that closes above the swing high: the canonical up zone
RISE = [101.0, 101.5, 102.0]
FALL = [101.5, 101.0, 100.5, 100.0, 99.5, 99.0]
LEG_GAP = [99.5, 100.5, 102.0, 103.0]
AFTER = [103.5, 104.0, 104.5]
ZONE_UP = WARMUP + RISE + FALL + LEG_GAP + AFTER
ORIGIN_BAR = len(WARMUP + RISE + FALL) - 1
PEAK_BAR = len(WARMUP + RISE) - 1

# the same, but the leg climbs in half steps: no gap, so no VOID
LEG_SMOOTH = [99.5, 100.0, 100.5, 101.0, 101.5, 102.0, 102.5, 103.0]
NO_VOID = WARMUP + RISE + FALL + LEG_SMOOTH + AFTER

# the leg trades under the origin (bar 32, low 98.25) after it is confirmed and before it breaks
LEG_INVALID = [99.5, 100.0, 99.5, 98.5, 100.0, 101.0, 102.0, 103.0]
INVALIDATED = WARMUP + RISE + FALL + LEG_INVALID + AFTER

# a shallow swing high at 100.7 (high 100.95), an origin at 99.95 (low 99.7), and a gapped leg that
# closes above the high at 101.0 having travelled 1.55 (under 2 ATR) from the origin: no DISPLACE
SHALLOW = WARMUP + [100.7, 100.5, 100.3, 100.1, 99.95, 100.2, 100.85, 101.0, 101.1, 101.2]
SHALLOW_ORIGIN = len(WARMUP) + 4
