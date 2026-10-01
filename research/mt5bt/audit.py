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
        a = full[full["i"] <= c][["i", "side", "stop", "target", "hold"]].reset_index(drop=True)
        b = part[part["i"] <= c][["i", "side", "stop", "target", "hold"]].reset_index(drop=True)
        same = len(a) == len(b) and np.allclose(a.to_numpy(float), b.to_numpy(float),
                                                rtol=1e-9, atol=1e-12, equal_nan=True)
        if not same:
            merged = a.merge(b, on="i", how="outer", suffixes=("_full", "_cut"), indicator=True)
            diff = merged[(merged["_merge"] != "both")
                          | ~np.isclose(merged.get("stop_full", 0), merged.get("stop_cut", 0))
                          | (merged.get("side_full", 0) != merged.get("side_cut", 0))]
            bad.append(dict(cut=int(c), signals_full=len(a), signals_cut=len(b),
                            first_bar=int(diff["i"].min()) if len(diff) else -1))
    return dict(ok=not bad, cuts=len(points), failures=pd.DataFrame(bad))
