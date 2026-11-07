"""The look-ahead audit: a signal at bar i must not change when bars after i are removed.

A strategy sees the whole frame, which is convenient and is exactly how look-ahead gets in (a
centred rolling window, a `shift(-1)`, a normalisation over the full sample). This re-runs it on
history cut at random points and compares every signal at or before the cut.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .data import Book
from .engine import _frame


#: **Every field of the signal, not five of eleven.** The audit compared only
#: `i, side, stop, target, hold`, so a strategy that chose its *resting entry
#: level*, its expiry or its trail from future bars passed clean - and
#: `research/ideas/zones.py` emits exactly `entry`, `limit` and `expires`. A
#: guard that checks some of the output is a guard for the fields it checks.
#: `donchian_entry_peek` is the regression: causal in every compared field
#: under the old list, and caught by this one.
COMPARED = ("i", "side", "stop", "target", "hold", "risk", "entry", "expires", "oco",
            "trail", "limit")


def lookahead(strategy, book: Book, cuts: int = 12, seed: int = 3, warmup: int = 200) -> dict:
    full = _frame(strategy(book.bars.copy(), book))
    n = len(book.bars)
    rng = np.random.default_rng(seed)
    points = np.sort(rng.integers(min(warmup, n - 2), n - 1, size=cuts))
    bad = []
    for c in points:
        cut = Book(book.symbol, book.bars.iloc[: c + 1].copy(), book.spec, book.interval,
                   feed=book.feed)
        part = _frame(strategy(cut.bars.copy(), cut))
        a = full[full["i"] <= c][list(COMPARED)].reset_index(drop=True)
        b = part[part["i"] <= c][list(COMPARED)].reset_index(drop=True)
        same = len(a) == len(b) and np.allclose(a.to_numpy(float), b.to_numpy(float),
                                                rtol=1e-9, atol=1e-12, equal_nan=True)
        if not same:
            merged = a.merge(b, on="i", how="outer", suffixes=("_full", "_cut"), indicator=True)
            moved = merged["_merge"] != "both"
            for col in COMPARED[1:]:
                left = merged.get(f"{col}_full")
                right = merged.get(f"{col}_cut")
                if left is None or right is None:
                    continue
                moved = moved | ~np.isclose(
                    left.to_numpy(float), right.to_numpy(float),
                    rtol=1e-9, atol=1e-12, equal_nan=True,
                )
            diff = merged[moved]
            bad.append(dict(cut=int(c), signals_full=len(a), signals_cut=len(b),
                            first_bar=int(diff["i"].min()) if len(diff) else -1))
    return dict(ok=not bad, cuts=len(points), failures=pd.DataFrame(bad))
