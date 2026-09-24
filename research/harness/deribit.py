"""Deribit's option surface, as rows with the units fixed.

## Why one REST call and no websocket

`get_book_summary_by_currency` returns **the entire option surface in one
response** - 1,050 live BTC options on 2026-09-24, every one carrying a
`mark_iv`. So the recorder is one HTTP GET per currency per sweep, and the
subscription budget the design worried about does not apply to it.

What that call does **not** carry is `bid_iv` or `ask_iv`; those need
`get_order_book`, one call per instrument. Cost is therefore taken in price
terms from `bid_price` and `ask_price`, which is what is actually paid.

## Milliseconds

Every timestamp Deribit sends is in milliseconds. This module divides by 1,000
at the boundary and everything downstream is in seconds, because `prices`
already holds `bars.ts` in seconds beside `quotes.ts` in milliseconds and a
query spanning both is wrong in a way that looks reasonable.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, fields

BASE_TESTNET = "https://test.deribit.com"
BASE_LIVE = "https://www.deribit.com"

#: Milliseconds to seconds. Named so the division is never a bare 1000.
MS = 1000.0


def base() -> str:
    """Testnet unless told otherwise.

    A recorder cannot trade, but it can be wrong about which venue it described,
    and the default should be the harmless one.
    """
    return BASE_LIVE if os.environ.get("DERIBIT_LIVE") == "1" else BASE_TESTNET


@dataclass(frozen=True, slots=True)
class Row:
    """One instrument's quote at one instant. Seconds, not milliseconds."""

    instrument: str
    underlying: str
    kind: str
    strike: float
    expiry: float
    mark_iv: float
    mark_price: float
    bid_price: float
    ask_price: float
    underlying_price: float
    open_interest: float
    volume: float
    at: float


FIELDS: tuple[str, ...] = tuple(f.name for f in fields(Row))


def _number(value: object) -> float | None:
    """A finite float, or `None`. `None` is not zero - see `parse_summary`."""
    if value is None:
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def parse_summary(payload: dict, *, instruments: dict[str, dict], at: float) -> list[Row]:
    """Rows from a `get_book_summary_by_currency` payload.

    `instruments` is the `get_instruments` listing keyed by name, because the
    summary carries no strike, expiry or option type - they are only in the
    instrument record, and joining them here keeps the two shapes out of
    everything downstream.

    A row missing anything the comparison needs is **dropped rather than
    defaulted**, and "missing" includes **zero**. Deribit sends `null` for a strike
    with no book today, so an earlier version that only refused `None` looked
    correct - but `_number(0.0)` is a perfectly good float, so a book quoted at zero
    would have survived and produced a cost of exactly zero. That is not harmless:
    the detection floor this feeds is what the whole phase is gated on, and mixing
    empty books into real ones drags its median down by half.
    """
    out: list[Row] = []
    for entry in payload.get("result") or []:
        name = entry.get("instrument_name")
        spec = instruments.get(str(name))
        if not name or not spec:
            continue
        expiry_ms = _number(spec.get("expiration_timestamp"))
        strike = _number(spec.get("strike"))
        mark_iv = _number(entry.get("mark_iv"))
        mark = _number(entry.get("mark_price"))
        bid = _number(entry.get("bid_price"))
        ask = _number(entry.get("ask_price"))
        if expiry_ms is None or strike is None or mark_iv is None:
            continue
        # Zero is refused as firmly as absent, for all three prices. `mark` is what
        # the cost fraction divides by; `bid` and `ask` are the spread it measures.
        if mark is None or mark <= 0.0:
            continue
        if bid is None or ask is None or bid <= 0.0 or ask <= 0.0:
            continue
        out.append(
            Row(
                instrument=str(name),
                underlying=str(spec.get("base_currency") or ""),
                kind=str(spec.get("option_type") or ""),
                strike=strike,
                expiry=expiry_ms / MS,
                mark_iv=mark_iv,
                mark_price=mark,
                bid_price=bid,
                ask_price=ask,
                underlying_price=_number(entry.get("underlying_price")) or 0.0,
                open_interest=_number(entry.get("open_interest")) or 0.0,
                volume=_number(entry.get("volume")) or 0.0,
                at=at,
            )
        )
    return out
