"""The open book, from a snapshot the desk wrote - never from the broker.

**Judge the desk on the broker, not the journal.** The engine's view and the
broker's have diverged here and cost money, so open positions have to come from
the broker. The dashboard still must not hold a credential or make an outbound
call, so the two facts are reconciled by splitting the job:

- `web/api/snapshot.py` runs **where the desk runs**, reads the bridge's GET
  routes, and writes a plain JSON file. It is the only thing that touches a
  terminal.
- This module reads that file. No key, no socket, no retry.

A snapshot has a timestamp and the page shows its age, because a stale panel
that looks live is the exact failure this desk has already paid for: four
health signals read green over a component that could not trade. There is no
fallback to journal positions when the file is missing - the journal is not the
broker, and presenting it as one would be the drift this arrangement exists to
prevent.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from till_infinity.journal import Entry, Kind, read

from .data import LIMIT, ROOT, _finite

#: Beyond this the UI calls the snapshot stale rather than showing it as the
#: book. Five minutes is long enough to survive a writer's interval and short
#: enough that nobody trades off it by accident.
STALE = 300.0


def snapshot_path() -> Path:
    """`TILL_BOOK_SNAPSHOT`, else where `snapshot.py` writes by default."""
    raw = os.environ.get("TILL_BOOK_SNAPSHOT") or ".data/live/book.json"
    found = Path(raw).expanduser()
    return found if found.is_absolute() else (ROOT / found)


@dataclass(frozen=True)
class Position:
    """One open position as the broker reports it.

    `protected` is the whole point of the row: a stop-loss of 0 or absent is
    a position running naked. Three of those ran for hours here on 2026-11-11
    and cost about 22 in account currency to close by hand.
    """

    ticket: str
    symbol: str
    feed: str
    side: str
    volume: float
    entry: float | None
    price: float | None
    stop: float | None
    target: float | None
    profit: float | None
    opened: float | None
    magic: int | None
    protected: bool


@dataclass(frozen=True)
class Account:
    """Account-level figures. **No identifier, ever.**

    Balance, equity and margin are what the exposure panel needs. The login,
    the server name and the broker's name are not here and are not forwarded
    by `snapshot.py` either: this renders in a browser, and an account number
    on a screen is an account number on a screenshot.
    """

    currency: str = ""
    balance: float | None = None
    equity: float | None = None
    margin: float | None = None
    free_margin: float | None = None
    leverage: int | None = None


@dataclass(frozen=True)
class Cap:
    """One configured ceiling, what is against it, and whether it binds."""

    name: str
    used: float
    ceiling: float | None
    unit: str
    binding: bool
    note: str = ""


@dataclass(frozen=True)
class Mismatch:
    """A position one side has and the other does not."""

    where: str
    symbol: str
    side: str
    ticket: str
    detail: str


@dataclass(frozen=True)
class Book:
    """The open book, its age, and what disagrees with it."""

    present: bool
    taken_at: float | None
    age: float | None
    stale: bool
    account: Account
    positions: list[Position]
    unprotected: list[Position]
    engine_open: int
    mismatches: list[Mismatch]
    caps: list[Cap]
    currencies: dict[str, float] = field(default_factory=dict)
    message: str = ""


def _flag(value: Any) -> float | None:
    return _finite(value) if isinstance(value, int | float) else None


def open_intents(path: Path | str) -> list[Entry]:
    """Decisions with no outcome pointing back at them.

    What the engine believes is open, derived the only way the journal allows:
    an outcome is a new entry naming its parent, so a decision nobody has
    judged is a position nobody has closed. A decision whose outcome aged out
    of the read window would look open here, which is why the window is the
    same hundred thousand entries the report uses.
    """
    outcomes = read(path, actor="trading", kind=Kind.OUTCOME, limit=LIMIT)
    judged = {entry.parent for entry in outcomes if entry.parent}
    return [
        entry
        for entry in read(path, actor="trading", kind=Kind.DECISION, limit=LIMIT)
        if entry.id not in judged
    ]


def _positions(rows: list[dict[str, Any]]) -> list[Position]:
    out: list[Position] = []
    for row in rows:
        stop = _flag(row.get("stop"))
        out.append(
            Position(
                ticket=str(row.get("ticket") or ""),
                symbol=str(row.get("symbol") or ""),
                feed=str(row.get("feed") or ""),
                side=str(row.get("side") or ""),
                volume=float(_flag(row.get("volume")) or 0.0),
                entry=_flag(row.get("entry")),
                price=_flag(row.get("price")),
                stop=stop,
                target=_flag(row.get("target")),
                profit=_flag(row.get("profit")),
                opened=_flag(row.get("opened")),
                magic=int(row["magic"]) if isinstance(row.get("magic"), int) else None,
                protected=bool(stop),
            )
        )
    return out


def _mismatches(positions: list[Position], intents: list[Entry]) -> list[Mismatch]:
    """Both directions of the disagreement, keyed on symbol and side.

    **Not on ticket**: a journalled decision carries no ticket - only the close
    record does - so symbol and side is the strongest key the two records
    share. Two positions on one symbol and side therefore collapse to one
    comparison, which is why `max_per_symbol` defaults to 1.

    The engine-only direction is the expensive one. A held refusal can name a
    position the broker closed hours ago, and five instruments stopped trading
    for a day here because the engine kept declining new trades as already
    held against positions that were gone.
    """
    broker = {(p.symbol.lower(), p.side.lower()): p for p in positions}
    engine: dict[tuple[str, str], Entry] = {}
    for entry in intents:
        symbol = str(entry.context.get("symbol") or "").lower()
        side = str(entry.context.get("side") or "").lower()
        if symbol:
            engine.setdefault((symbol, side), entry)

    out: list[Mismatch] = []
    for key, position in broker.items():
        if key not in engine:
            out.append(
                Mismatch(
                    where="broker only",
                    symbol=position.symbol,
                    side=position.side,
                    ticket=position.ticket,
                    detail="the broker holds this and no open decision names it",
                )
            )
    for key, entry in engine.items():
        if key not in broker:
            out.append(
                Mismatch(
                    where="engine only",
                    symbol=str(entry.context.get("symbol") or key[0]),
                    side=key[1],
                    ticket="",
                    detail=(
                        "an open decision with no broker position - this is what blocks "
                        "an instrument as already held"
                    ),
                )
            )
    return out


def _caps(positions: list[Position], account: Account) -> tuple[list[Cap], dict[str, float]]:
    """Exposure against the ceilings `strategies.config` actually configures.

    Read from `Settings.from_env()` rather than re-named here, because a cap
    the dashboard invents is a cap nobody is enforcing. A ceiling the desk does
    not configure is reported with `ceiling=None` and no verdict rather than a
    guessed one.
    """
    from till_infinity.strategies.config import Settings

    # A malformed `TRADING_*` value raises here, and a dashboard that 500s
    # because one setting is a typo is less useful than one that says the caps
    # are unreadable and still shows the positions.
    try:
        settings: Any = Settings.from_env()
    except (TypeError, ValueError):
        settings = None
    gross = sum(abs(p.volume) * (p.price or p.entry or 0.0) for p in positions)
    equity = account.equity or account.balance or 0.0

    currencies: dict[str, float] = {}
    for position in positions:
        name = position.symbol[-3:].upper() if len(position.symbol) >= 6 else ""
        if not name:
            continue
        signed = abs(position.volume) * (1 if position.side.lower() == "buy" else -1)
        currencies[name] = currencies.get(name, 0.0) + signed

    ceiling = getattr(settings, "max_positions", None)
    per_symbol = getattr(settings, "max_per_symbol", None)
    currency_cap = getattr(settings, "max_currency_exposure", None)
    unreadable = " - the desk's settings could not be read" if settings is None else ""

    held: dict[str, int] = {}
    for position in positions:
        held[position.symbol] = held.get(position.symbol, 0) + 1
    worst = max(held.values(), default=0)

    caps = [
        Cap(
            name="concurrent positions",
            used=float(len(positions)),
            ceiling=float(ceiling) if ceiling else None,
            unit="positions",
            binding=bool(ceiling) and len(positions) >= int(ceiling),
            note=f"TRADING_MAX_POSITIONS{unreadable}",
        ),
        Cap(
            name="per instrument",
            used=float(worst),
            ceiling=float(per_symbol) if per_symbol else None,
            unit="positions",
            binding=bool(per_symbol) and worst >= int(per_symbol),
            note=f"TRADING_MAX_PER_SYMBOL{unreadable}",
        ),
        Cap(
            name="gross notional",
            used=gross,
            ceiling=None,
            unit=account.currency or "account currency",
            binding=False,
            note=(
                "no gross cap is configured; sizing is a risk fraction against a "
                "volatility stop, and every scaler clamps at 1.0"
            ),
        ),
        Cap(
            name="margin used",
            used=float(account.margin or 0.0),
            ceiling=float(equity) if equity else None,
            unit=account.currency or "account currency",
            binding=bool(equity) and (account.margin or 0.0) >= equity * 0.5,
            note="against equity; the broker's own call level is not in the snapshot",
        ),
        Cap(
            name="net currency exposure",
            used=max((abs(v) for v in currencies.values()), default=0.0),
            ceiling=float(currency_cap) * equity if currency_cap and equity else None,
            unit="lots, against a fraction of equity",
            binding=False,
            note="TRADING_MAX_CURRENCY_EXPOSURE, stated as a fraction of equity",
        ),
    ]
    return caps, currencies


def book(path: Path | str | None = None, *, journal: Path | str | None = None) -> Book:
    """The open book from the snapshot, reconciled against the journal."""
    from .data import journal_path

    where = Path(path) if path is not None else snapshot_path()
    now = time.time()
    if not where.exists():
        return Book(
            present=False,
            taken_at=None,
            age=None,
            stale=True,
            account=Account(),
            positions=[],
            unprotected=[],
            engine_open=0,
            mismatches=[],
            caps=[],
            message=(
                f"No broker snapshot at {where.name}. Run web/api/snapshot.py where the "
                "desk runs; the dashboard never calls the terminal itself."
            ),
        )

    try:
        payload = json.loads(where.read_text())
    except (OSError, ValueError) as error:
        return Book(
            present=False,
            taken_at=None,
            age=None,
            stale=True,
            account=Account(),
            positions=[],
            unprotected=[],
            engine_open=0,
            mismatches=[],
            caps=[],
            message=f"The snapshot could not be read: {error}",
        )

    taken = _flag(payload.get("taken_at"))
    rows = payload.get("positions")
    positions = _positions(rows if isinstance(rows, list) else [])
    raw = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    account = Account(
        currency=str(raw.get("currency") or ""),
        balance=_flag(raw.get("balance")),
        equity=_flag(raw.get("equity")),
        margin=_flag(raw.get("margin")),
        free_margin=_flag(raw.get("free_margin")),
        leverage=int(raw["leverage"]) if isinstance(raw.get("leverage"), int) else None,
    )

    db = Path(journal) if journal is not None else journal_path()
    intents = open_intents(db) if db.exists() else []
    caps, currencies = _caps(positions, account)
    age = None if taken is None else max(0.0, now - taken)
    return Book(
        present=True,
        taken_at=taken,
        age=age,
        stale=age is None or age > STALE,
        account=account,
        positions=positions,
        unprotected=[p for p in positions if not p.protected],
        engine_open=len(intents),
        mismatches=_mismatches(positions, intents),
        caps=caps,
        currencies=currencies,
        message=str(payload.get("message") or ""),
    )
