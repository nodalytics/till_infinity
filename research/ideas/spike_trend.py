"""Do Boom and Crash spikes follow the higher-timeframe trend?

Boom and Crash are generated instruments with a known asymmetry: Boom drifts
down and spikes **up**, Crash drifts up and spikes **down**. The desk has been
trading them symmetrically and the broker record says what that costs - Crash
500 sold 55 times for -432.15 against 41 buys for +96.37, Boom 1000 sold seven
times and won none of them.

So the question is not "is there a pattern in the price" - that is the question
every rule in `lrc-retest.md` failed. It is whether the instrument's *own*
mechanical asymmetry is modulated by the slower frames: does a 1h, 4h or 1d
downtrend bring more Crash spikes, or bigger ones, or a weaker counter-drift
between them? A generator whose jump rate is constant would say no, and that is
the honest null here - these are simulated instruments and the answer may well
be that the trend carries nothing because there is nothing to carry.

Trend comes from the desk's own channel (`trading/regression.py`) at the
reference constants - 100 bars, r-squared 0.64 - and the five states are its own
arrow: strong up, up, flat, down, strong down.

**The counter-drift is the number that matters, not the spike rate.** A Crash
spike is a known event; what decides whether selling Crash pays is how much the
slow grind up takes back before the next one. So every bucket reports the mean
forward return over several horizons, which is what a position would actually
have captured.

Confidence intervals are block-bootstrapped by day. Trend buckets persist for
hours, so neighbouring bars are not independent and an ordinary standard error
would be far too narrow - which is how a regime study talks itself into a
finding.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
for p in (HERE, HERE.parent, HERE.parents[1]):
    sys.path.insert(0, str(p))

from till_infinity.trading import regression as RG  # noqa: E402

DB = os.environ.get("MT5BT_DB", os.path.expanduser("~/till_infinity/data/mt5bt.db"))
OUT = Path(os.environ.get("OUT", ".data/spike"))

#: (symbol, the direction it spikes). Jump is the control: it spikes both ways,
#: so anything that shows up there is the method and not the asymmetry.
PAIRS = (("Boom 1000 Index", +1), ("Crash 1000 Index", -1), ("Jump 50 Index", 0))
BASE = "15m"
HTFS = ("1h", "4h", "1d")
#: Bars ahead, at the base timeframe: 15m, 1h, 4h, one day.
HORIZONS = (1, 4, 16, 96)
#: A spike is a bar whose move dwarfs the ordinary one. 5x the rolling median
#: absolute return, which on these generators separates the jump from the grind
#: cleanly; `SPIKE_K` is swept below so the answer cannot hang on it.
SPIKE_K = 5.0
SWEEP_K = (3.0, 5.0, 8.0)
DRAWS = 2000


def bars(sym, iv):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT ts, open, high, low, close FROM bars WHERE symbol = ? AND interval = ? "
            "ORDER BY ts", (sym, iv)).fetchall()
    finally:
        con.close()
    if not rows:
        return None
    a = np.array(rows, float)
    ts = a[:, 0] / (1000.0 if a[0, 0] > 1e11 else 1.0)
    return dict(ts=ts, open=a[:, 1], high=a[:, 2], low=a[:, 3], close=a[:, 4])


class _Bar:
    """What `regression.fit` reads, without importing the trading dataclass."""

    __slots__ = ("open", "high", "low", "close")

    def __init__(self, o, h, l, c):
        self.open, self.high, self.low, self.close = o, h, l, c


def arrows(d, span=RG.SPAN):
    """The channel's five-state arrow at every bar, and the slope behind it."""
    n = len(d["close"])
    out = np.array([RG.FLAT] * n, dtype=object)
    slope = np.full(n, np.nan)
    r2 = np.full(n, np.nan)
    rows = [_Bar(o, h, l, c) for o, h, l, c in
            zip(d["open"], d["high"], d["low"], d["close"])]
    for i in range(span, n):
        window = rows[i - span + 1:i + 1]
        ch = RG.fit(window, span)
        if ch is None:
            continue
        unit = RG.atr(window)
        if not unit > 0 or np.isnan(unit):
            continue
        s = RG.slope_vol(ch, unit)
        slope[i], r2[i] = s, ch.r2
        out[i] = RG.arrow(s, ch.r2, span)
    return out, slope, r2


def carry(ts_from, label_from, ts_to):
    """The last HTF label known strictly before each base-timeframe bar.

    Strictly before, because a 4h arrow computed on a bar that has not closed is
    a reading nothing could have acted on - the mistake that makes every regime
    study look profitable.
    """
    idx = np.searchsorted(ts_from, ts_to, side="left") - 1
    ok = idx >= 0
    out = np.array([None] * len(ts_to), dtype=object)
    out[ok] = label_from[idx[ok]]
    return out


def block_ci(values, days, draws=DRAWS, seed=5):
    """Mean with a day-block bootstrap interval."""
    if len(values) < 30:
        return float(np.mean(values)) if len(values) else np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    # Per-day sums and counts, so a draw is two gathers and a divide rather than
    # eight hundred array concatenations. The resampled mean is identical.
    uniq, inv = np.unique(days, return_inverse=True)
    sums = np.bincount(inv, weights=values, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    pick = rng.integers(0, len(uniq), size=(draws, len(uniq)))
    got = sums[pick].sum(axis=1) / np.maximum(cnts[pick].sum(axis=1), 1.0)
    return float(np.mean(values)), float(np.percentile(got, 5)), float(np.percentile(got, 95))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    lines = []
    for sym, direction in PAIRS:
        d = bars(sym, BASE)
        if d is None:
            print(f"{sym}: no {BASE} bars")
            continue
        close = d["close"]
        ret = np.zeros_like(close)
        ret[1:] = np.diff(close) / close[:-1]
        absr = np.abs(ret)
        # Rolling median of |return| over a day of 15m bars, shifted so the
        # threshold at bar i uses only bars before it.
        win = 96
        med = np.full(len(ret), np.nan)
        for i in range(win, len(ret)):
            med[i] = np.median(absr[i - win:i])
        day = (d["ts"] // 86400).astype(np.int64)

        htf_labels = {}
        for iv in HTFS:
            h = bars(sym, iv)
            if h is None:
                continue
            lab, _s, _r = arrows(h)
            htf_labels[iv] = carry(h["ts"], lab, d["ts"])

        print("=" * 92)
        print(f"{sym}   spikes {'up' if direction > 0 else 'down' if direction < 0 else 'both ways'}"
              f"   {len(close)} {BASE} bars")

        for k in SWEEP_K:
            big = (absr > k * med) & np.isfinite(med)
            up = big & (ret > 0)
            dn = big & (ret < 0)
            print(f"  k={k:g}: {int(big.sum())} spikes "
                  f"({int(up.sum())} up, {int(dn.sum())} down), "
                  f"{big.sum() / max(1, np.isfinite(med).sum()) * 1000:.2f} per 1000 bars")
        big = (absr > SPIKE_K * med) & np.isfinite(med)

        for iv in HTFS:
            lab = htf_labels.get(iv)
            if lab is None:
                continue
            print(f"\n  --- {iv} trend (channel span {RG.SPAN}, r2 floor {RG.MIN_R2}) ---")
            print(f"    {'trend':<8}{'bars':>8}{'spikes':>8}{'per1k':>8}{'spike sz':>10}"
                  + "".join(f"{'fwd' + str(h):>18}" for h in HORIZONS))
            for state, name in ((RG.RISING_FAST, "up++"), (RG.RISING, "up"),
                                (RG.FLAT, "flat"), (RG.FALLING, "down"),
                                (RG.FALLING_FAST, "down--")):
                m = (lab == state) & np.isfinite(med)
                nb = int(m.sum())
                if nb < 500:
                    continue
                sp = int((m & big).sum())
                # Spike size in the instrument's own spike direction.
                sz = ret[m & big]
                szm = float(np.mean(sz * (direction or 1))) * 1e4 if len(sz) else np.nan
                cells = []
                for hz in HORIZONS:
                    fwd = np.full(len(close), np.nan)
                    fwd[:-hz] = (close[hz:] - close[:-hz]) / close[:-hz]
                    mm = m & np.isfinite(fwd)
                    v = fwd[mm] * 1e4
                    mean, lo, hi = block_ci(v, day[mm])
                    cells.append(f"{mean:>7.2f}[{lo:>5.1f},{hi:>5.1f}]")
                print(f"    {name:<8}{nb:>8}{sp:>8}{sp / nb * 1000:>8.2f}{szm:>10.1f}"
                      + "".join(f"{c:>18}" for c in cells))
                lines.append(dict(sym=sym, htf=iv, trend=name, bars=nb, spikes=sp,
                                  per1k=sp / nb * 1000, size_bps=szm))
            # The unconditional row every bucket must be read against.
            m = np.isfinite(med)
            cells = []
            for hz in HORIZONS:
                fwd = np.full(len(close), np.nan)
                fwd[:-hz] = (close[hz:] - close[:-hz]) / close[:-hz]
                mm = m & np.isfinite(fwd)
                v = fwd[mm] * 1e4
                mean, lo, hi = block_ci(v, day[mm])
                cells.append(f"{mean:>7.2f}[{lo:>5.1f},{hi:>5.1f}]")
            print(f"    {'ALL':<8}{int(m.sum()):>8}{int((m & big).sum()):>8}"
                  f"{(m & big).sum() / m.sum() * 1000:>8.2f}{'':>10}"
                  + "".join(f"{c:>18}" for c in cells))

    import json
    (OUT / "spike_trend.json").write_text(json.dumps(lines, indent=1))
    print("\nforward returns are in basis points, [5%,95%] day-block bootstrap.")
    print("spike done", flush=True)


if __name__ == "__main__":
    main()
