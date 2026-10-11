"""Alert cards: what to watch, never how it was found.

A card leaves the building - Discord, Telegram, a phone screen anyone can see -
so it carries the signal and nothing of the method:

    📈 ₿ BTC 4h · Bullish reversal · long
    Context · an exit alert will follow
    paper alert, not a trade instruction
    Entry ref: 61,230 (next open)
    Stop: 59,880
    Risk: 1,350
    Venue: BINANCE:BTCUSDT
    Bar: 2026-10-05 00:00 UTC

**Visible:** the direction icon, symbol, timeframe, a generic label from
`registry.LABELS` (bullish / bearish reversal, break of structure, liquidity
sweep, exit), the reference entry, stop and risk in price, the venue and bar
time, an opaque tier (`registry.tier`: Tier A or Context) and the footer.

**Never visible:** pattern or token names, lookbacks, ATR multiples, the exit
logic, evidence numbers, sample sets or doc names. Those stay machine-side in
`payload["meta"]` - which `notifications.from_message` does not read, so no
transport can render it - and in the logs. The routing field `ref` is a hash
of the dedupe key, for the same reason: Discord shows every field.

`tests/test_mcfl_service.py::test_no_card_leaks_the_method` holds every card
and chart title to that list.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import registry
from .chart import ENTRY, STOP, Line, Spec
from .detect import Finding
from .tokens import Bars
from .trade import Exit, Open

#: The source a card names. Generic: the footer of a Discord embed shows it.
SOURCE = "signals"

FOLLOWS = "an exit alert will follow"


@dataclass(slots=True)
class Card:
    """One alert: the bus payload, what to draw for it, and its dedupe key."""

    key: str
    payload: dict
    chart: Spec | None = None
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Machine-side only: the notification layer never reads `meta`.
        self.payload["meta"] = {"key": self.key, **self.meta}

    def attach(self, png: bytes | None) -> None:
        if png:
            self.payload["image"] = {
                "name": f"{_ref(self.key)}.png",
                "data": base64.b64encode(png).decode("ascii"),
            }


def when(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M UTC")


def px(value: float | None) -> str:
    if value is None:
        return "-"
    a = abs(value)
    if a >= 1000:
        return f"{value:,.1f}"
    if a >= 1:
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return f"{value:.6g}"


def _ref(k: str) -> str:
    """An opaque, stable id for a dedupe key - safe to show, useless to read."""
    return hashlib.sha1(k.encode(), usedforsecurity=False).hexdigest()[:12]


def side_word(side: int, trade: bool) -> str:
    if trade:
        return "long" if side > 0 else "short"
    return "bullish" if side > 0 else "bearish"


def key(rule: str, symbol: str, timeframe: str, bar_ts: int, *extra: object) -> str:
    """The dedupe key: rule, symbol, timeframe and bar time (plus what tells two
    events of one rule on one bar apart). Machine-side only."""
    return "|".join(str(x) for x in (rule, symbol, timeframe, bar_ts, *extra))


def _routing(symbol: str, timeframe: str, k: str, *, side: int | None, shape: str) -> dict:
    fields = {"shape": shape, "instrument": symbol.lower(), "interval": timeframe, "ref": _ref(k)}
    if side is not None:
        fields["direction"] = "up" if side > 0 else "down"
    return fields


def _body(*lines: str) -> str:
    return "\n".join((*lines, registry.FOOTER))


def finding(
    f: Finding, symbol: str, timeframe: str, klass: str, bars: Bars, *, venue: str = ""
) -> Card:
    """The card for a pattern firing on the newest bar of `bars`."""
    p = registry.PATTERNS[f.pattern]
    bar_ts = int(bars.ts[f.known_at])
    k = key(f.pattern, symbol, timeframe, bar_ts, f.kind, int(bars.ts[f.at]), f.side)
    name = registry.label(f.kind, f.side)
    side = side_word(f.side, p.trade)
    tier = registry.tier(f.pattern, timeframe, klass)
    fields = _routing(symbol, timeframe, k, side=f.side, shape="pattern")
    spec = Spec(bars, f"{symbol} · {timeframe} · {name} · {side}", highlight=(f.known_at,))
    lines = [tier]
    if f.signal is not None:
        s = f.signal
        fields.update(
            {
                "Entry ref": f"{px(s.close)} (next open)",
                "Stop": px(s.stop),
                "Risk": px(abs(s.close - s.stop)),
            }
        )
        spec.levels += [
            Line(s.close, "entry ref", ENTRY, dashed=True, start=f.at),
            Line(s.stop, "stop", STOP, dashed=True, start=f.at),
        ]
        lines = [f"{tier} · {FOLLOWS}"]
    elif f.kind in ("STRUCTURE_SHIFT", "MAJOR_BOS") and f.level is not None:
        # The broken level, as a plain line: where, not how it was chosen.
        spec.levels.append(Line(f.level, ""))
    if venue:
        fields["Venue"] = venue
    fields["Bar"] = when(bar_ts)
    proof = registry.evidence(f.pattern, timeframe, klass)
    meta = {"pattern": f.pattern, "kind": f.kind, "evidence": proof.text, "tier": tier}
    title = f"{symbol} {timeframe} · {name} · {side}"
    return Card(k, _payload(title, _body(*lines), fields), spec, meta)


def mirror_day(day_ts: int, count: int, broad: bool, btc: float | None) -> Card:
    """The market mirror's one card for a daily close: BTC long, M1 and B together.

    The alts behind it stay machine-side; the card carries their number only.
    """
    k = key("M1", "BTC", "1d", day_ts)
    fields = _routing("BTC", "1d", k, side=1, shape="pattern")
    entry = "next daily open" + (f" (last close {px(btc)})" if btc is not None else "")
    fields.update(
        {
            "Entry ref": entry,
            "Breadth": f"{count}" + (" · wide" if broad else ""),
            "Bar": when(day_ts),
        }
    )
    tier = registry.tier("M1", "1d", "crypto")
    meta = {
        "pattern": "M1+B" if broad else "M1",
        "signals": count,
        "evidence": registry.evidence("M1", "1d", "crypto").text,
    }
    title = f"BTC 1d · {registry.label('M1', 1)} · long"
    return Card(k, _payload(title, _body(f"{tier} · {FOLLOWS}"), fields), None, meta)


def _exit_card(
    symbol: str,
    timeframe: str,
    k: str,
    result: str,
    opened: str,
    bar_ts: int,
    meta: dict,
    spec: Spec | None = None,
) -> Card:
    fields = _routing(symbol, timeframe, k, side=None, shape="exit")
    fields.update({"Result": result, "Opened by": opened, "Bar": when(bar_ts)})
    title = f"{symbol} {timeframe} · {registry.EXIT}"
    return Card(k, _payload(title, _body(), fields), spec, meta)


def exited(
    rule: str,
    symbol: str,
    timeframe: str,
    signal_key: str,
    trade: Open,
    out: Exit,
    bars: Bars,
    exit_at: int,
    signal_at: int | None,
) -> Card:
    """The exit of a paper trade: its result in R, and the alert that opened it."""
    bar_ts = int(bars.ts[exit_at])
    k = key(f"{rule}:exit", symbol, timeframe, bar_ts, signal_key)
    if out.reason == "void":
        result = "no trade (opened beyond the stop)"
    else:
        result = f"{out.r:+.2f}R" + (" (at the next open; marked here)" if out.at_next_open else "")
    opened = f"the {symbol} {timeframe} alert of {when(trade.signal_ts)} (ref {_ref(signal_key)})"
    spec = Spec(bars, f"{symbol} · {timeframe} · {registry.EXIT}", highlight=(exit_at,))
    if trade.entry is not None:
        spec.levels.append(Line(trade.entry, "entry", ENTRY, dashed=True, start=signal_at))
    spec.levels.append(Line(trade.stop, "stop", STOP, dashed=True, start=signal_at))
    spec.levels.append(Line(out.price, "exit", start=exit_at))
    meta = {"pattern": rule, "reason": out.reason, "r": out.r, "mfe": out.mfe, "bars": out.bars}
    return _exit_card(symbol, timeframe, k, result, opened, bar_ts, meta, spec)


def mirror_exited(
    day_ts: int, day_key: str, mean_bps: float | None, count: int, bar_ts: int
) -> Card:
    """The daily mirror card's exit: the last of its trades has ended.

    The result is the mean over the day's signals - M1's per-signal mean, so the
    paper record compares with the research - marked at this BTC close.
    """
    k = key("M1:exit", "BTC", "1d", bar_ts, day_ts)
    result = (
        f"{mean_bps:+.0f} bps net, mean of {count} (marked at this close)"
        if mean_bps is not None
        else f"no BTC reference, mean of {count}"
    )
    opened = f"the BTC 1d alert of {when(day_ts)} (ref {_ref(day_key)})"
    return _exit_card("BTC", "1d", k, result, opened, bar_ts, {"pattern": "M1", "day": day_ts})


def _payload(title: str, body: str, fields: dict) -> dict:
    return {
        "title": title,
        "body": body,
        "level": "info",
        "fields": {str(k): str(v) for k, v in fields.items()},
        "source": SOURCE,
    }
