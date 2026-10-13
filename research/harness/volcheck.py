"""Which cached feeds carry volume, and whose volume is actually constant.

The activity arms need a control group of feeds with a known generator, and
`statespace-volume-clock.md` says the Deriv synthetics post constant tick
volume. "Constant" turned out to be worth checking per feed: `Step Index 200`
reads an activity extent of 1.001 rather than 1.000 at 1h, which is enough to
move a likelihood and so enough to break a control that asserts inertness.
"""

from pathlib import Path

import numpy as np

from till_infinity.structures.statespace.pacing import extent

CACHE = Path.home() / "till_infinity/data/seqlab"

rows = []
for path in sorted(CACHE.glob("*.1h.npz")):
    name = path.name[: -len(".1h.npz")]
    try:
        with np.load(path) as bundle:
            if "volume" not in bundle:
                rows.append((name, 0, float("nan"), float("nan")))
                continue
            volume = np.asarray(bundle["volume"], dtype=float)
    except Exception as exc:  # noqa: BLE001
        rows.append((name, -1, float("nan"), float("nan")))
        print(f"{name}: unreadable: {exc}")
        continue
    if len(volume) < 400:
        continue
    spread = float(np.std(volume) / np.mean(volume)) if np.mean(volume) > 0 else float("nan")
    rows.append((name, len(volume), extent(volume.tolist()), spread))

flat = [r for r in rows if r[1] > 0 and r[2] == 1.0]
near = [r for r in rows if r[1] > 0 and 1.0 < r[2] < 1.05]
busy = [r for r in rows if r[1] > 0 and r[2] >= 1.05]
none = [r for r in rows if r[1] == 0]

print(f"\n{len(rows)} cached at 1h: {len(none)} without volume\n")
print(f"exactly constant activity, extent 1.000 ({len(flat)}) - the control group")
for name, count, ext, spread in flat[:40]:
    print(f"  {name:<28}{count:>8,}  extent {ext:.4f}  cv {spread:.4f}")
print(f"\nnearly constant, 1.000 < extent < 1.05 ({len(near)}) - NOT usable as inert")
for name, count, ext, spread in near[:25]:
    print(f"  {name:<28}{count:>8,}  extent {ext:.4f}  cv {spread:.4f}")
print(f"\nuneven activity ({len(busy)}), the ten most uneven")
for name, count, ext, spread in sorted(busy, key=lambda r: -r[2])[:10]:
    print(f"  {name:<28}{count:>8,}  extent {ext:.4f}  cv {spread:.4f}")
