"""What the lab cache actually holds, for the ideas that name specific assets."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path

CACHE = Path(os.environ.get("SEQLAB_CACHE", str(Path.home() / "till_infinity/data/seqlab")))

WANTED = {
    "carry pairs": r"MXN|TRY|ZAR|HUF|PLN|NOK|SEK|BRL|INR|RUB",
    "indices": r"SPX|US30|US500|NAS|GER|UK100|JP225|AUS200|HK50|DAX|DOW",
    "dollar index": r"DXY|DOLLAR|USDX|USDIndex",
    "deriv synthetics": r"Volatility|Jump|Boom|Crash|Step|Range_|Drift|Hybrid",
    "metals and energy": r"XAU|XAG|XPT|XPD|WTI|BRENT|OIL|NGAS",
    "fx majors": r"^(EUR|GBP|USD|AUD|NZD|CAD|CHF|JPY){2}$",
}


def main() -> None:
    by_name: dict[str, set[str]] = defaultdict(set)
    for path in CACHE.glob("*.npz"):
        name, _, frame = path.stem.partition(".")
        by_name[name].add(frame)
    print(f"{len(by_name)} symbols in {CACHE}\n")
    for label, pattern in WANTED.items():
        hits = sorted(n for n in by_name if re.search(pattern, n, re.I))
        print(f"{label}: {len(hits)}")
        for name in hits[:14]:
            frames = ",".join(sorted(by_name[name]))
            print(f"    {name:<22} {frames}")
        if len(hits) > 14:
            print(f"    ... and {len(hits) - 14} more")
        print()
    frames: dict[str, int] = defaultdict(int)
    for got in by_name.values():
        for frame in got:
            frames[frame] += 1
    print("frames available:", dict(sorted(frames.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
