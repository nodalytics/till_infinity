"""Throwaway probe 2: how deep tick history goes, and what the clock is exactly."""
from __future__ import annotations

import time

import numpy as np

from research.harness import feed

feed.TIMEOUT = 1200.0


def depth(sym: str, hours: float, count: int = 400_000) -> None:
    t0 = time.time()
    try:
        got = feed.ticks(sym, count, hours_back=hours)
    except Exception as exc:  # noqa: BLE001
        print(f"  {sym:26s} hours={hours:6.0f} FAIL {type(exc).__name__} {str(exc)[:60]}", flush=True)
        return
    if len(got) < 10:
        print(f"  {sym:26s} hours={hours:6.0f} {len(got)} rows", flush=True)
        return
    tm = np.array([r["time"] for r in got])
    age = (time.time() - tm[0]) / 3600.0
    print(
        f"  {sym:26s} hours={hours:6.0f} n={len(got):>8,} in {time.time() - t0:5.0f}s "
        f"span={(tm[-1] - tm[0]) / 3600:8.2f}h oldest={age:8.2f}h ago",
        flush=True,
    )


def main() -> None:
    names = feed.symbols()
    for pat in ("Volatility", "Jump", "Step", "Boom", "Crash", "Range", "DEX", "Drift"):
        hits = sorted(n for n in names if pat.lower() in n.lower())
        print(f"{pat:12s} ({len(hits)}): {hits}", flush=True)

    print("\n--- how deep does tick history go ---", flush=True)
    for hours in (168.0, 720.0, 2160.0):
        depth("Volatility 75 Index", hours)
    depth("Volatility 250 (1s) Index", 720.0)

    print("\n--- the clock, exactly (V75, 7 days) ---", flush=True)
    got = feed.ticks("Volatility 75 Index", 400_000, hours_back=168.0)
    tm = np.array([r["time"] for r in got])
    ms = np.round(tm * 1000.0).astype(np.int64)
    gaps = np.diff(ms)
    print(f"n={len(ms):,}  mean gap {gaps.mean():.3f}ms  median {np.median(gaps):.0f}ms", flush=True)
    vals, cnt = np.unique(gaps, return_counts=True)
    order = np.argsort(cnt)[::-1][:15]
    print("most common gaps (ms, count):", [(int(vals[i]), int(cnt[i])) for i in order], flush=True)
    within = ms % 2000
    v2, c2 = np.unique(within, return_counts=True)
    o2 = np.argsort(c2)[::-1][:12]
    print("offset within a 2000ms slot:", [(int(v2[i]), int(c2[i])) for i in o2], flush=True)
    print(f"offset spread: p01={np.quantile(within, 0.01):.0f} p50={np.median(within):.0f} "
          f"p99={np.quantile(within, 0.99):.0f} sd={within.std():.1f}", flush=True)
    slot = ms // 2000
    print(f"slots covered {slot[-1] - slot[0] + 1:,}, ticks {len(ms):,}, "
          f"empty slots {slot[-1] - slot[0] + 1 - len(np.unique(slot)):,}, "
          f"duplicate slots {len(ms) - len(np.unique(slot)):,}", flush=True)


if __name__ == "__main__":
    main()
