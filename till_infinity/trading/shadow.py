"""The five confirmation gates from `research/docs/confirm.md`, shadowed: they record, never act.

`confirm.md` searched 45 TA gates across nine higher-to-lower timeframe pairings for a layer that
confirms a structures signal before a trading model takes over. It found no general layer; 17 of
8,366 cells passed every control, and they reduce to five narrow gates, each resting on a few
hundred trades. That is a candidate, not a basis for trading decisions, so here they are
**shadowed**:
- when a level signal arrives that matches a gate's family and timeframe, a plan is recorded;
- once the gate's window has closed, its lower-timeframe bars are fetched through the service's
  own `execution.bars`, the gate's verdict is worked out exactly as the harness did, and one
  `observation` by `trading` goes in the journal.

Nothing is taken, refused, resized or delayed because of any of this. The journal is how the
research side reads it back (`research/harness/shadowreport.py`), and after about 200 live signals
per gate the question is whether each still beats the plain entry.

## The gates, as measured (`confirm.md`, the passing cells)

| gate | family | level -> confirm on | rule | stop | target |
|---|---|---|---|---|---|
| `fx_1h_candle` | FX | 1h -> 15m | production's `candles.confirms` | HTF | 2R |
| `deriv_1h_sweep` | Deriv | 1h -> 15m | through the level, then a close back | HTF | 1R |
| `deriv_pivot_mfi` | Deriv | pivot -> 1h | MFI(14) back through 20 (80) | HTF, 1d | 2R |
| `fx_4h_chop` | FX | 4h -> 1h | Choppiness(14) > 61.8 at the window's start | LTF | 1R |
| `crypto_1h_trix` | crypto | 1h -> 1h | TRIX(15) turning | HTF | 1R |

Each gate's measured cell (net R, trades, pass rate) is on it, as `Gate.cell`.

For crypto, TRIX is the one of the five momentum turns with the strongest evidence (t 5.4 against
the plain entry; change of character, MACD, PSAR and Vortex were weaker and faded in the second
half), and it is what `confirm.md` names for production.

Every trade fades the arrival: long at a level price came down to, short at one it came up to.
That is the side the harness traded, published by `structures` as `arrived_above`.

## The harness's timing, reproduced on purpose

A structures touch is stamped with the close of the bar that made it. The harness matched that
stamp as if it were a bar's *open* and added one 1h bar, so every measured window opened **one
hour after the signal was known** (`WINDOW_OFFSET_S`). The shadow uses the same offset, because
that is what the passing cells measured. Each record also carries the plain entry at that window's
first bar, so the offset's cost can be judged later.

`TRADING_SHADOW_GATES=0` turns it off.
"""

from __future__ import annotations

import math
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from till_platform.logging import get_logger

from ..structures import rollover
from . import candles
from .sizing import price_distance

log = get_logger(__name__)

#: Minutes per bar. Daily and weekly pivots are one class, measured against the daily bar.
MINUTES: dict[str, int] = {"15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440, "piv": 1440}
PIVOTS = ("daily", "weekly")
#: See the module docstring: the harness's windows opened one 1h bar after the signal.
WINDOW_OFFSET_S = 3600.0
#: Harness constants (`research/harness/confirm.py`).
CAP_WINDOW, SAME_WINDOW = 32, 8
LIMIT_HTF, CAP_LIMIT = 10, 400
MIN_R = 0.25
#: History the indicators need before the window: the harness required 210 bars before it on the
#: confirming timeframe and 60 on the stop's.
HISTORY_LTF, HISTORY_HTF = 210, 60
FETCH_LTF, FETCH_HTF = 300, 120
#: Round-trip cost in five-minute volatilities, as `indicators.COST_V` charged.
COST_V = {"fx": 0.8, "deriv": 0.15, "crypto": 0.5}
#: Plans waiting for their window. The oldest goes first when full, and is counted.
MAX_PENDING = 500
#: Seconds after a window's last bar closes before it is evaluated, for the bar to reach the
#: broker's history.
SETTLE_S = 60.0
TAG = "shadow-gate"

#: The Deriv indices `confirm.md` measured (Volatility 25/75, Jump 50, Step, Boom and Crash 1000),
#: by family name. Range Break, DEX, Drift Switch and the Step variants were not in the test.
DERIV_WORDS = ("volatility", "jump", "boom", "crash")


@dataclass(frozen=True, slots=True)
class Gate:
    name: str
    family: str
    signals: tuple[str, ...]
    ltf: str
    rule: str
    stop: str
    target_r: int
    cell: str

    @property
    def level_tf(self) -> str:
        return "piv" if self.signals[0] in PIVOTS else self.signals[0]

    @property
    def vol_tf(self) -> str:
        """The timeframe whose last closed bar sizes an HTF stop (1d for pivots)."""
        return "1d" if self.level_tf == "piv" else self.level_tf

    @property
    def ratio(self) -> int:
        return max(MINUTES[self.level_tf] // MINUTES[self.ltf], 1)

    @property
    def window(self) -> int:
        same = self.level_tf == self.ltf
        return SAME_WINDOW if same else min(self.ratio, CAP_WINDOW)

    @property
    def limit(self) -> int:
        return min(LIMIT_HTF * self.ratio, CAP_LIMIT)


GATES: tuple[Gate, ...] = (
    Gate(
        "fx_1h_candle",
        "fx",
        ("1h",),
        "15m",
        "candle",
        "htf",
        2,
        "FX 1h->15m production candle, 2R: +0.114R net, n 223, pass 5.7%",
    ),
    Gate(
        "deriv_1h_sweep",
        "deriv",
        ("1h",),
        "15m",
        "sweep",
        "htf",
        1,
        "Deriv 1h->15m sweep-and-reclaim, 1R: +0.082R net, n 832, pass 33%",
    ),
    Gate(
        "deriv_pivot_mfi",
        "deriv",
        PIVOTS,
        "1h",
        "mfi",
        "htf",
        2,
        "Deriv pivot->1h MFI back above 20, 2R: +0.174R net, n 1,043, pass 10%",
    ),
    Gate(
        "fx_4h_chop",
        "fx",
        ("4h",),
        "1h",
        "chop",
        "ltf",
        1,
        "FX 4h->1h Choppiness > 61.8 (LTF stop), 1R: +0.041R net, n 251, pass 4.7%",
    ),
    Gate(
        "crypto_1h_trix",
        "crypto",
        ("1h",),
        "1h",
        "trix",
        "htf",
        1,
        "crypto 1h->1h TRIX turn, 1R: +0.033R net, n 570, pass 30%",
    ),
)


def family(feed: str) -> str:
    """fx, deriv, crypto or "" - the families the gates were measured on."""
    if rollover.is_fx(feed):
        return "fx"
    name = "_".join(re.findall(r"[a-z0-9]+", feed.lower()))
    if name.startswith(("btc", "eth")):
        return "crypto"
    if any(word in name for word in DERIV_WORDS) or name == "step_index":
        return "deriv"
    return ""


# -------------------------------------------------------------------------------- indicators
# Ports of `research/harness/indicators.py` and `confirm.py`, over closed bars oldest first.
# `tests/test_shadow.py` checks each against the harness on the same synthetic bars.

NAN = float("nan")


def _ewm(values: Sequence[float], alpha: float) -> list[float]:
    """pandas' `ewm(adjust=False)`: starts at the first finite value, skips none after it."""
    out, state = [], NAN
    for v in values:
        if math.isnan(state):
            state = v
        elif not math.isnan(v):
            state = state + alpha * (v - state)
        out.append(state)
    return out


def vol(closes: Sequence[float]) -> list[float]:
    """The bar's volatility as a log-return sd: EWMA(14) of |log return| x sqrt(pi/2)."""
    moves = [NAN] + [abs(math.log(b / a)) if a > 0 and b > 0 else NAN for a, b in pairwise(closes)]
    return [v * math.sqrt(math.pi / 2) for v in _ewm(moves, 2 / 15)]


def trix(closes: Sequence[float], span: int = 15) -> list[float]:
    alpha = 2 / (span + 1)
    t = _ewm(_ewm(_ewm(closes, alpha), alpha), alpha)
    return [NAN] + [100 * (b / a - 1) if a else NAN for a, b in pairwise(t)]


def _rolling_sum(values: Sequence[float], n: int) -> list[float]:
    return [sum(values[i - n + 1 : i + 1]) if i >= n - 1 else NAN for i in range(len(values))]


def mfi(bars: Sequence[candles.Bar], n: int = 14) -> list[float]:
    """Money-flow index. Missing or zero volume counts as 1, as the harness did."""
    tp = [(b.high + b.low + b.close) / 3 for b in bars]
    volume = [v if (v := float(getattr(b, "volume", 0.0) or 0.0)) > 0 else 1.0 for b in bars]
    flow = [a * v for a, v in zip(tp, volume, strict=True)]
    dtp = [0.0] + [b - a for a, b in pairwise(tp)]
    pos = _rolling_sum([f if d > 0 else 0.0 for f, d in zip(flow, dtp, strict=True)], n)
    neg = _rolling_sum([f if d < 0 else 0.0 for f, d in zip(flow, dtp, strict=True)], n)
    return [
        100 - 100 / (1 + p / q) if q and not math.isnan(q) else NAN
        for p, q in zip(pos, neg, strict=True)
    ]


def chop(bars: Sequence[candles.Bar], n: int = 14) -> list[float]:
    """Choppiness index: log10(sum of true range / n-bar range) / log10(n), in percent."""
    tr = []
    for i, b in enumerate(bars):
        span = b.high - b.low
        if i:
            pc = bars[i - 1].close
            span = max(span, abs(b.high - pc), abs(b.low - pc))
        tr.append(span)
    out = []
    for i in range(len(bars)):
        if i < n - 1:
            out.append(NAN)
            continue
        box = bars[i - n + 1 : i + 1]
        rng = max(b.high for b in box) - min(b.low for b in box)
        total = sum(tr[i - n + 1 : i + 1])
        out.append(100 * math.log10(total / rng) / math.log10(n) if rng > 0 and total > 0 else NAN)
    return out


def _through(a: Sequence[float], j: int, level: float, up: bool) -> bool:
    if j < 1 or math.isnan(a[j]) or math.isnan(a[j - 1]):
        return False
    return a[j - 1] < level <= a[j] if up else a[j - 1] > level >= a[j]


def _turn(a: Sequence[float], j: int, up: bool) -> bool:
    if j < 2 or any(math.isnan(a[m]) for m in (j, j - 1, j - 2)):
        return False
    if up:
        return a[j] > a[j - 1] and a[j - 1] <= a[j - 2]
    return a[j] < a[j - 1] and a[j - 1] >= a[j - 2]


# -------------------------------------------------------------------------------- the verdict


@dataclass(slots=True)
class Plan:
    gate: Gate
    feed: str
    symbol: str
    level: float
    side: int  # +1 long, -1 short: the fade of the arrival
    interval: str
    signal_time: float
    level_id: str
    closes_at: float = 0.0
    due: float = 0.0

    def __post_init__(self) -> None:
        self.closes_at = self.signal_time + WINDOW_OFFSET_S
        length = MINUTES[self.gate.ltf] * 60
        self.due = self.closes_at + self.gate.window * length + SETTLE_S


def _last_closed(bars: Sequence[candles.Bar], minutes: int, by: float) -> int:
    """The index of the last bar that has closed by `by`, or -1."""
    length = minutes * 60
    found = -1
    for i, b in enumerate(bars):
        if b.time + length <= by:
            found = i
    return found


def fired_at(
    rule: str,
    ltf: Sequence[candles.Bar],
    v: Sequence[float],
    k0: int,
    end: int,
    side: int,
    level: float,
    stop: float,
) -> int | None:
    """The first bar in `k0 .. end` where the gate's rule fires for a trade on `side`, or None."""
    closes = [b.close for b in ltf]
    up = side > 0
    if rule == "candle":
        tol = price_distance(level, v[k0] * 10_000, 0.25)
        return next(
            (
                j
                for j in range(max(k0, 2), end + 1)
                if candles.confirms(list(ltf[j - 2 : j + 1]), level, up, tol)
            ),
            None,
        )
    if rule == "sweep":
        swept = False
        for j in range(k0, end + 1):
            if side * (closes[j] - stop) <= 0:
                return None
            swept = swept or (ltf[j].low < level if up else ltf[j].high > level)
            if swept and side * (closes[j] - level) > 0 and j > k0:
                return j
        return None
    if rule == "mfi":
        m = mfi(ltf)
        return next(
            (j for j in range(k0, end + 1) if _through(m, j, 20.0 if up else 80.0, up)), None
        )
    if rule == "trix":
        t = trix(closes)
        return next((j for j in range(k0, end + 1) if _turn(t, j, up)), None)
    if rule == "chop":
        c = chop(ltf)
        return k0 if not math.isnan(c[k0]) and c[k0] > 61.8 else None
    raise ValueError(rule)


def _stop(plan: Plan, ltf: Sequence[candles.Bar], htf: Sequence[candles.Bar], v, k0: int) -> float:
    """Anchored to the level: 1 x the stop timeframe's bar volatility beyond it. NaN if unknown."""
    if plan.gate.stop == "ltf":
        return plan.level - plan.side * v[k0] * ltf[k0].close
    hi = _last_closed(htf, MINUTES[plan.gate.vol_tf], plan.closes_at)
    if hi < HISTORY_HTF:
        return NAN
    return plan.level - plan.side * vol([b.close for b in htf])[hi] * htf[hi].close


def evaluate(plan: Plan, ltf: Sequence[candles.Bar], htf: Sequence[candles.Bar]) -> dict[str, Any]:
    """The gate's verdict and the hypothetical trade, exactly as `confirm.py` worked them out."""
    gate, s = plan.gate, plan.side
    lmin = MINUTES[gate.ltf]
    k0 = _last_closed(ltf, lmin, plan.closes_at)
    end = k0 + gate.window
    if k0 < HISTORY_LTF or end >= len(ltf):
        return {"verdict": "unavailable", "why": "not enough closed bars to confirm on"}
    v = vol([b.close for b in ltf])
    stop = _stop(plan, ltf, htf, v, k0)
    if not math.isfinite(stop):
        return {"verdict": "unavailable", "why": "not enough closed bars for the stop"}
    fired = fired_at(gate.rule, ltf, v, k0, end, s, plan.level, stop)
    unit = COST_V[gate.family] * math.sqrt(5 / lmin)

    def trade(j: int) -> dict[str, Any]:
        entry = ltf[j].close
        risk = s * (entry - stop)
        tradeable = risk > MIN_R * v[j] * entry
        return {
            "entry": entry,
            "entry_time": ltf[j].time + lmin * 60,
            "risk": risk,
            "tradeable": bool(tradeable),
            "targets": {str(k): entry + s * k * risk for k in (1, 2)},
            "cost_r": unit * v[j] * entry / risk if tradeable else None,
        }

    out: dict[str, Any] = {
        "verdict": "pass" if fired is not None else "fail",
        "stop": stop,
        "window_start": ltf[k0].time,
        "window_bars": gate.window,
        "plain": trade(k0),  # the no-gate entry at the window's first bar, for the comparison
    }
    if fired is not None:
        out.update(fired_at=ltf[fired].time, delay_bars=fired - k0, **trade(fired))
    return out


# -------------------------------------------------------------------------------- the shadow


Fetch = Callable[[str, str, int], Awaitable[Sequence[candles.Bar]]]
Record = Callable[[str, dict[str, Any], tuple[str, ...]], Awaitable[Any]]


@dataclass
class ShadowGates:
    """Plans waiting for their window, and the evaluations that settle them. Records only."""

    fetch: Fetch
    record: Record
    enabled: bool = True
    cap: int = MAX_PENDING
    now: Callable[[], float] = time.time
    pending: deque = field(default_factory=deque)
    dropped: int = 0
    planned: int = 0
    evaluated: int = 0
    no_side: int = 0

    def consider(self, payload: dict[str, Any], symbol: str | None) -> list[Plan]:
        """Record a plan for each gate this signal matches. Never raises into the caller."""
        if not self.enabled or not symbol:
            return []
        try:
            return self._consider(payload, symbol)
        except Exception as exc:
            log.debug("trading: shadow gates could not read a signal: %s", exc)
            return []

    def _consider(self, payload: dict[str, Any], symbol: str) -> list[Plan]:
        if str(payload.get("shape") or "") != "level":
            return []
        feed = str(payload.get("feed") or "")
        interval = str(payload.get("interval") or "")
        fam = family(feed)
        gates = [g for g in GATES if g.family == fam and interval in g.signals]
        if not gates:
            return []
        features = payload.get("features") or {}
        above = features.get("arrived_above")
        level = features.get("level")
        when = payload.get("time")
        if not isinstance(above, int | float) or not isinstance(level, int | float):
            self.no_side += 1
            return []
        if not isinstance(when, int | float):
            when = self.now()
        made = []
        for gate in gates:
            plan = Plan(
                gate=gate,
                feed=feed,
                symbol=symbol,
                level=float(level),
                side=1 if above >= 0.5 else -1,
                interval=interval,
                signal_time=float(when),
                level_id=str(payload.get("level_id") or ""),
            )
            if len(self.pending) >= self.cap:
                self.pending.popleft()
                self.dropped += 1
                if self.dropped == 1 or self.dropped % 100 == 0:
                    log.warning(
                        "trading: shadow gates dropped %d plan(s), queue full at %d",
                        self.dropped,
                        self.cap,
                    )
            self.pending.append(plan)
            made.append(plan)
        self.planned += len(made)
        return made

    async def due(self) -> int:
        """Evaluate and record every plan whose window has closed. Returns how many."""
        if not self.enabled or not self.pending:
            return 0
        now = self.now()
        ready = [p for p in self.pending if p.due <= now]
        if not ready:
            return 0
        self.pending = deque(p for p in self.pending if p.due > now)
        for plan in ready:
            try:
                await self._settle(plan, now)
            except Exception as exc:  # a fault here must never reach trading
                log.debug(
                    "trading: shadow gate %s on %s failed: %s", plan.gate.name, plan.feed, exc
                )
            self.evaluated += 1
        return len(ready)

    async def _settle(self, plan: Plan, now: float) -> None:
        gate = plan.gate
        lmin = MINUTES[gate.ltf]
        since = plan.closes_at - FETCH_LTF * lmin * 60
        ltf = await self._bars(plan.symbol, gate.ltf, math.ceil((now - since) / (lmin * 60)) + 2)
        htf: Sequence[candles.Bar] = ()
        if gate.stop == "htf":
            if gate.vol_tf == gate.ltf:
                htf = ltf
            else:
                hmin = MINUTES[gate.vol_tf]
                hsince = plan.closes_at - FETCH_HTF * hmin * 60
                htf = await self._bars(
                    plan.symbol, gate.vol_tf, math.ceil((now - hsince) / (hmin * 60)) + 2
                )
        got = evaluate(plan, ltf, htf) if ltf else {"verdict": "unavailable", "why": "no bars"}
        context = {
            "gate": gate.name,
            "cell": gate.cell,
            "feed": plan.feed,
            "symbol": plan.symbol,
            "family": gate.family,
            "signal_interval": plan.interval,
            "ltf": gate.ltf,
            "level": plan.level,
            "side": "buy" if plan.side > 0 else "sell",
            "signal_time": plan.signal_time,
            "window_opens": plan.closes_at,
            "window_offset_s": WINDOW_OFFSET_S,
            "level_id": plan.level_id,
            "stop_kind": gate.stop,
            "target_r": gate.target_r,
            "limit_bars": gate.limit,
            **got,
        }
        await self.record(
            f"shadow {gate.name} {got['verdict']} on {plan.feed}",
            context,
            (plan.feed, TAG, gate.name),
        )

    async def _bars(self, symbol: str, interval: str, count: int) -> Sequence[candles.Bar]:
        try:
            return list(await self.fetch(symbol, interval, max(count, 1)))
        except Exception as exc:
            log.debug("trading: shadow gates got no %s bars for %s: %s", interval, symbol, exc)
            return []
