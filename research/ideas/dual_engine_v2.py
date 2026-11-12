"""v2's attention feature: a softmax-weighted price z-score, against its own flip.

`research/docs/dual-engine-confluence.md` closed v1 - no direction, no cost
problem, and about 0.2R a trade lost to the exit stack - and left exactly one
thing open. v2 replaces the trigger with a different feature, and a result on
v1's trigger is not evidence about it.

* **v1 asked "is the market unusually volatile right now"** - a z-score of true
  range against a rolling mean and standard deviation, mixed half from the
  execution timeframe and half from the structure one.
* **v2 asks "is price unusually far from an attention-weighted mean"** - a
  z-score of *price*, where the mean and deviation are weighted by a softmax
  over recent absolute returns, computed on four timeframes and combined by a
  second softmax over the absolute z-scores themselves.

Those are different questions. This measures the second one.

## Only the attention feature changes, and that is deliberate

v2 also moves the breakout body ratio from 0.50 to 0.60 and replaces v1's
*decline* on a sub-ATR stop with a *floor* on the risk. Both are left at v1's
values here. Three changes measured together produce one number that attributes
to none of them, and the attention feature is the substantive one - the other
two are a threshold nudge and a sizing change. If the feature shows something,
they are the next run, not this one.

## The formulation, as implemented

For each timeframe in {15m, 1H, 4H, 1D}, over the last `N = 70` closes, newest
first:

    r_i      = |P_i / P_{i+1} - 1|
    w_i      = exp(r_i) / sum_j exp(r_j)
    mu_w     = sum_i w_i P_i
    sigma_w  = sqrt(sum_i w_i (P_i - mu_w)^2)
    Z_tf     = (P_0 - mu_w) / sigma_w

then across the four:

    alpha_tf = exp(|Z_tf|) / sum_k exp(|Z_k|)
    Z_MTF    = sum_tf alpha_tf * Z_tf

and the gate is `|Z_MTF| > Percentile_85(H_Z)` over the last 200 readings.

**Two things the formulation leaves open, decided here and stated so the next
reader is not guessing.**

1. **How often `Z_MTF` is recorded.** The spec names a 200-reading history but
   not its cadence. Recorded **once per structure bar**, which at a 4H
   structure is about 33 days of history - long enough for a percentile to mean
   something and matched to the bar the signal is evaluated on. Sampling it per
   execution bar would make 200 readings about 17 hours, which is a threshold
   that tracks the thing it is thresholding.
2. **`exp(r_i)` is applied to a raw return**, which for a 5-minute FX bar is
   order 1e-4, so `exp(r_i) ~ 1 + r_i` and the softmax is very nearly uniform.
   That is what the formulation says, so that is what runs - but it means the
   weighting is a far weaker effect than it looks, and the feature is close to
   a plain price z-score over 70 bars. Worth knowing before reading the result
   either way: `only-the-sign-survives-into-a-weighted-sum` is a standing
   finding here that activation and scale choices are usually rank identities.

## The bar it has to clear

From the v1 work, and fixed before this run:

* **Beat its own flip by more than two standard errors.** Same bars, same
  pivots, same stops, same exits, direction reversed. Anything both arms earn
  is geometry, not direction.
* **On the 464-day span**, not an 86-day one. Every positive reading on v1 sat
  on n <= 13 and reversed as the sample grew.
* **Clear the exits.** The measured exit stack costs about 0.2R a trade on a
  direction-free entry, so a feature whose edge is smaller than that does not
  reach the account even if it is real. The rule-minus-flip gap is the entry's
  own contribution and is what this reports; the 0.2R is what it would then
  have to cover.

Run it as `uv run python research/ideas/dual_engine_v2.py`.
"""

from __future__ import annotations

import argparse
import math
from collections import deque
from pathlib import Path
from typing import Any

from nautilus_trader.model.data import Bar

from dual_engine_grid import load_all, measure, span_days
from dual_engine_port import DualEngine, DualEngineConfig

#: The lookback for one timeframe's z-score, in that timeframe's own bars.
LOOKBACK = 70

#: How many consensus readings the percentile is taken over.
HISTORY = 200

#: The percentile the gate fires above.
PERCENTILE = 0.85

#: The attention timeframes, as execution bars per bar of that timeframe, on a
#: **5-minute** execution feed: 15m, 1H, 4H, 1D. The spec names these four.
ATTENTION_SPANS: tuple[int, ...] = (3, 12, 48, 288)

#: The structure the signals themselves are drawn on, in execution bars. 4H,
#: as the spec's pivots, origin candle and cluster all are.
STRUCTURE = 48

CATALOGUE = Path.home() / "till-data" / "mt5"
SPEC = "5-MINUTE-LAST-EXTERNAL"


def weighted_z(prices: list[float]) -> float | None:
    """One timeframe's softmax-weighted price z-score, newest first.

    Returns None where it is not computable - too few prices, or a zero
    weighted deviation, which happens on a dead feed and must not become a
    division that quietly yields an infinity.
    """
    if len(prices) < LOOKBACK:
        return None
    window = prices[:LOOKBACK]
    returns = [
        abs(window[i] / window[i + 1] - 1.0) if window[i + 1] else 0.0
        for i in range(len(window) - 1)
    ]
    returns.append(0.0)  # the oldest has no predecessor inside the window
    # Shifted before exponentiating: the values are tiny here, but a raw
    # `exp` on an unshifted vector is how a softmax overflows on a feed with
    # one large move in it.
    top = max(returns)
    weights = [math.exp(r - top) for r in returns]
    total = sum(weights)
    if total <= 0:
        return None
    weights = [w / total for w in weights]
    mean = sum(w * p for w, p in zip(weights, window, strict=True))
    variance = sum(w * (p - mean) ** 2 for w, p in zip(weights, window, strict=True))
    deviation = math.sqrt(variance)
    if deviation <= 0:
        return None
    return (window[0] - mean) / deviation


def consensus(zs: list[float]) -> float | None:
    """The softmax-over-|Z| combination of several timeframes' z-scores."""
    if not zs:
        return None
    top = max(abs(z) for z in zs)
    weights = [math.exp(abs(z) - top) for z in zs]
    total = sum(weights)
    if total <= 0:
        return None
    return sum(w * z for w, z in zip(weights, zs, strict=True)) / total


class V2Config(DualEngineConfig, frozen=True):
    attention_spans: tuple[int, ...] = ATTENTION_SPANS


class DualEngineV2(DualEngine):
    """v1's geometry with v2's trigger.

    Everything below the attention feature is inherited unchanged - the pivots,
    the origin candle, the cluster, the retest, the sizing, the protection and
    the exits - so the only difference between this and the measured v1 is the
    question the gate asks.
    """

    def __init__(self, config: V2Config) -> None:
        super().__init__(config)  # type: ignore[arg-type]
        self._closes: dict[int, deque[float]] = {
            span: deque(maxlen=LOOKBACK) for span in config.attention_spans
        }
        self._counts: dict[int, int] = dict.fromkeys(config.attention_spans, 0)
        self._readings: deque[float] = deque(maxlen=HISTORY)
        self._latest: float | None = None
        #: How often the gate was asked and how often it passed, so a feature
        #: that never fires is visible as that rather than as a rule with no
        #: edge.
        self.asked = 0
        self.passed = 0

    def _attend(self, tr15: float) -> None:
        """Fold the execution bar's close into each attention timeframe.

        `on_bar` sets `_prev15` to this bar's close before calling here, so it
        is the current price and not the previous one. Checked rather than
        assumed, because a one-bar lag in a feature is invisible in a plot and
        is the difference between a reading and a forecast.
        """
        price = self._prev15
        if price is None:
            return
        for span in self._closes:
            self._counts[span] += 1
            if self._counts[span] >= span:
                self._counts[span] = 0
                self._closes[span].appendleft(price)

    def _close_4h(self) -> None:
        """Record one consensus reading, then run v1's structure logic."""
        zs = [z for span in self._closes if (z := weighted_z(list(self._closes[span]))) is not None]
        if len(zs) == len(self._closes):
            found = consensus(zs)
            if found is not None:
                self._latest = found
                self._readings.append(abs(found))
        super()._close_4h()

    def _attention_strong(self) -> bool:
        """`|Z_MTF|` above the 85th percentile of its own recent history."""
        self.asked += 1
        if self._latest is None or len(self._readings) < HISTORY:
            return False
        values = sorted(self._readings)
        position = PERCENTILE * (len(values) - 1)
        lower = int(math.floor(position))
        upper = min(lower + 1, len(values) - 1)
        threshold = values[lower] + (values[upper] - values[lower]) * (position - lower)
        if abs(self._latest) <= threshold:
            return False
        self.passed += 1
        return True


def run(instruments: list[Any], data: list[Any], *, flip: bool) -> tuple[list[Any], int, int]:
    from decimal import Decimal

    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, RiskEngineConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.enums import AccountType, OmsType
    from nautilus_trader.model.objects import Money

    from dual_engine_port import EQUITY, LEVERAGE

    engine = BacktestEngine(
        config=BacktestEngineConfig(
            trader_id="V2-001",
            logging=LoggingConfig(bypass_logging=True),
            risk_engine=RiskEngineConfig(bypass=False),
        )
    )
    for venue in sorted({i.id.venue for i in instruments}, key=str):
        engine.add_venue(
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            base_currency=USD,
            starting_balances=[Money(EQUITY, USD)],
            default_leverage=Decimal(str(LEVERAGE)),
        )
    built = []
    for n, instrument in enumerate(instruments):
        engine.add_instrument(instrument)
        strategy = DualEngineV2(
            V2Config(
                instrument_id=instrument.id,
                bar_type=BarType.from_str(f"{instrument.id}-{SPEC}"),
                feed=str(instrument.id.symbol),
                bars_per_structure=STRUCTURE,
                flip=flip,
                order_id_tag=f"{n:04d}",
            )
        )
        engine.add_strategy(strategy)
        built.append(strategy)
    engine.add_data(data)
    engine.run()
    closed = [t for s in built for t in s.closed]
    asked = sum(s.asked for s in built)
    passed = sum(s.passed for s in built)
    engine.dispose()
    return closed, asked, passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", default=str(CATALOGUE))
    args = parser.parse_args()

    instruments, data = load_all(Path(args.catalogue), SPEC)
    if not instruments:
        raise SystemExit(f"nothing in {args.catalogue}")
    days = span_days(data)
    bars = sum(1 for row in data if isinstance(row, Bar))
    print(f"{len(instruments)} instruments, {bars} bars, {days:.0f} days, 5m execution")
    print(f"attention on spans {ATTENTION_SPANS} (15m, 1H, 4H, 1D), structure {STRUCTURE} (4H)\n")

    from dual_engine_grid import Cell

    out = {}
    for flip in (False, True):
        closed, asked, passed = run(instruments, data, flip=flip)
        cell = Cell(0.015, 0.85, 0.01, flip, bars_per_structure=STRUCTURE, bar_spec=SPEC)
        found = measure(cell, closed, days)
        money = sum(t.profit for t in closed)
        out[flip] = found
        side = "flip" if flip else "rule"
        rate = f"{passed / asked:.1%}" if asked else "n/a"
        print(
            f"  {side:<5} n {found.trades:>4}  R {found.reward:>+6.3f} +/-{found.reward_se:>5.3f}  "
            f"sharpe {found.sharpe:>+6.2f}  dd {found.drawdown:>5.1%}  "
            f"gross ${money:>+10,.0f}  gate {passed}/{asked} ({rate})"
        )

    rule, null = out[False], out[True]
    if rule.trades and null.trades:
        gap = rule.reward - null.reward
        se = math.sqrt(rule.reward_se**2 + null.reward_se**2)
        print(f"\n  rule - flip {gap:+.3f}R, se {se:.3f} -> {gap / se:+.2f} standard errors")
        print(
            "  the bar was two standard errors and then 0.2R of exit cost on top"
            if abs(gap / se) < 2
            else "  clears two standard errors; the 0.2R exit cost is the next bar"
        )


if __name__ == "__main__":
    main()
