"""How often can BTCUSD pass the surprise desk's cost gate?

    ./.secrets/lab.sh run research/harness/gatecheck.py

The number a read-only production diagnosis could not get. The gate in
`strategies/surprise.py` refuses when `cost > reward * cost_share`, and with
`cost_share` 0.10, `target_r` 2.0 and `stop_vol` 2.0 the reward is 4 volatility
units, so the pass condition reduces to

    spread_bps <= 0.40 * vol_bps

`vol_bps` is the statespace fold's own per-bar volatility estimate, which on a
quiet weekend is far below its long-run value while the spread is fixed. So
the gate can bind for a completely legitimate reason - the round trip is too
large a share of the expected move - and that is what it exists to do.

This measures the ratio from realised 15-minute volatility over 5.7 years,
and reports what share of bars would clear the gate at the spread the terminal
quotes today. A second limit sits behind it: `costs.too_expensive` caps the
round trip at 0.16 of the risk, which on this geometry is 0.32 volatility
units, so **0.32 binds before 0.40** and is the real threshold.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

DATA = Path.home() / "till_infinity" / "data" / "btc"
#: The terminal's quoted round trip, measured by `btccost.py` on 2026-11-07.
ROUND_TRIP_PX = 18.86
COST_SHARE_LIMIT = 0.40
RISK_LIMIT = 0.32


def main() -> int:
    with np.load(DATA / "BTCUSD.1h.npz") as data:
        time, close = data["time"], data["close"]

    ret = np.diff(np.log(close))
    # The desk folds 15-minute bars; these are hourly, so a 15m return's
    # standard deviation is the hourly one over sqrt(4) under independence.
    # Stated rather than hidden: volatility clustering makes this slightly
    # optimistic at short horizons, which biases the pass rate UP, not down.
    for window in (24, 96, 672):
        rolling = np.full(len(ret), np.nan)
        for i in range(window, len(ret)):
            rolling[i] = np.std(ret[i - window : i])
        vol_bps_15m = rolling / 2.0 * 1e4
        spread_bps = ROUND_TRIP_PX / close[1:] * 1e4
        ratio = spread_bps / vol_bps_15m
        usable = np.isfinite(ratio)
        print(
            f"window {window:4d}h  median vol_bps(15m) {np.nanmedian(vol_bps_15m):6.2f}  "
            f"median spread_bps {np.nanmedian(spread_bps):5.2f}  "
            f"median ratio {np.nanmedian(ratio):6.3f}"
        )
        print(
            f"              passes 0.40 on {np.mean(ratio[usable] <= COST_SHARE_LIMIT):6.1%} "
            f"of bars, passes 0.32 on {np.mean(ratio[usable] <= RISK_LIMIT):6.1%}"
        )

    # The last few days, which is the state the live desk is actually in.
    print("\nmost recent, on a 24h window:")
    tail = 24 * 14
    rolling = np.array([np.std(ret[max(0, i - 24) : i]) for i in range(len(ret) - tail, len(ret))])
    vol_bps = rolling / 2.0 * 1e4
    spread_bps = ROUND_TRIP_PX / close[-tail:] * 1e4
    ratio = spread_bps / vol_bps
    for label, slice_ in (("last 14 days", slice(None)), ("last 48h", slice(-48, None))):
        part = ratio[slice_]
        print(
            f"  {label:12s} median vol_bps {np.nanmedian(vol_bps[slice_]):6.2f}  "
            f"median ratio {np.nanmedian(part):6.3f}  "
            f"passes 0.32 on {np.mean(part <= RISK_LIMIT):6.1%}"
        )

    # ── the conditional that matters: the bars a surprise actually fires on ──
    #
    # A surprise is a move large relative to the *variance state*, and the
    # state is what sets `vol_bps` and therefore the reward. So the trigger
    # selects bars whose pre-move volatility was LOW, while the spread is
    # fixed - which would put the cost gate and the trigger in tension by
    # construction. Unconditional pass rates cannot see that.
    print("\nconditional on a surprise firing (|z| >= 3.0 against the trailing state):")
    for window in (24, 96):
        sd = np.full(len(ret), np.nan)
        for i in range(window, len(ret)):
            sd[i] = np.std(ret[i - window : i])
        # The state is the volatility BEFORE the move, which is what the fold
        # carries into the bar that surprises it.
        z = np.abs(ret) / sd
        vol_bps = sd / 2.0 * 1e4
        spread_bps = ROUND_TRIP_PX / close[1:] * 1e4
        ratio = spread_bps / vol_bps
        fires = np.isfinite(z) & (z >= 3.0) & np.isfinite(ratio)
        allbars = np.isfinite(ratio)
        if not fires.any():
            continue
        print(
            f"  window {window:3d}h  fired on {fires.sum():5d} of {allbars.sum()} bars "
            f"({fires.sum() / allbars.sum():.2%})"
        )
        print(
            f"              median ratio  all {np.median(ratio[allbars]):6.3f}   "
            f"when fired {np.median(ratio[fires]):6.3f}"
        )
        print(
            f"              passes 0.32    all {np.mean(ratio[allbars] <= RISK_LIMIT):6.1%}   "
            f"when fired {np.mean(ratio[fires] <= RISK_LIMIT):6.1%}"
        )

    print(
        "\nA ratio above 0.32 is the desk declining to pay more than 16% of its risk in\n"
        "spread, which is the measured limit and not a fault. But if the `when fired`\n"
        "column is much worse than `all`, the trigger is selecting the bars the cost gate\n"
        "is built to refuse, and no threshold tuning fixes that - the two gates would be\n"
        "reading the same quantity in opposite directions."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
