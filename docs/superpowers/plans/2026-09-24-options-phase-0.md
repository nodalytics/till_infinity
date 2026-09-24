# Options Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record Deribit's BTC/ETH option surface and answer whether this desk's volatility forecasts beat the market's implied volatility out of sample — the gate that decides whether any options execution gets built.

**Architecture:** Two research harnesses and one extension, all outside the production process. A collector polls one REST endpoint per currency (the whole surface arrives in a single call) and appends gzipped CSV, following `payout_logger.py`. A scorer joins that against BTC/ETH bars, computes realised volatility over each option's remaining life, and scores our forecast against `mark_iv` by QLIKE, after establishing a detection floor from the bid/ask spread. Nothing connects to the bus, nothing holds credentials, nothing trades.

**Tech Stack:** Python 3.11 (`.venv`), `httpx` (already a dependency), `numpy`, gzipped CSV, `pytest`, `ruff`.

**Spec:** `docs/superpowers/specs/2026-09-24-options-trading-design.md`

## Global Constraints

- **Nothing in this plan runs in the production process.** Phase 0 is `research/harness/` only. No `till_infinity/options/` package is created here — that is phase 2.
- **Never trade.** No `private/` Deribit endpoint, no auth header, no API key read from anywhere. A `buy` call must not exist in any file this plan creates.
- **Testnet by default** (`test.deribit.com`), overridable to `www.deribit.com` by env var. Both were verified reachable 2026-09-24.
- **Every Deribit timestamp is in milliseconds.** `expiration_timestamp` reads `1790236800000`. Normalise to seconds at the boundary; never store a millisecond value.
- **Cost is measured in price terms**, not IV terms: `(ask_price - bid_price) / 2 / mark_price`. `bid_iv`/`ask_iv` are not in the surface endpoint.
- **Detection floor before the comparison.** The floor is computed and written down first; a result that does not clear it is a null.
- `ruff format --check` and `ruff check` must both pass — CI runs `ruff format`, and `ruff check` passing does not imply it.
- Data files go to a gitignored directory. Never commit recorded market data.
- Run with `.venv/bin/python`, never system `python3`.

## Review Focus

Five things the spec implies that no task's happy path exercises. Each has its test added to the task that owns the code.

1. **`mark_iv` present but `bid_price` or `ask_price` absent or zero** — an illiquid strike with no book. The cost fraction divides by `mark_price` and subtracts a spread; a missing side must produce no row rather than a zero cost. *(Task 2)*
2. **An already-expired option in the listing** — `expired=false` is a request, not a guarantee. An expiry in the past makes the realised-volatility window negative and silently inverts the score. *(Task 4)*
3. **HTTP 200 with an empty or error `result`** — Deribit returns 200 and a JSON-RPC error body. A recorder that writes a header and no rows looks identical to a quiet market. *(Task 2)*
4. **Milliseconds read as seconds** — the one trap this repo has already fallen into, in `prices`. A seconds/milliseconds confusion puts every expiry 20,699,613 days away and every window computation is then garbage. *(Task 1)*
5. **A currency that lists no options** — a new or delisted currency returns an empty surface, and the floor computation then divides by zero. *(Task 3)*

---

## File Structure

| file | responsibility |
| --- | --- |
| `research/harness/deribit.py` | the venue's wire format: fetch the surface, normalise units, nothing else |
| `research/harness/deribit_recorder.py` | the detached collector: sweep, append gzipped CSV, survive an outage |
| `research/harness/implied_floor.py` | the detection floor, from recorded data, computed before any scoring |
| `research/harness/implied_vs_ours.py` | the comparison: our forecast against `mark_iv`, QLIKE, walk-forward |
| `tests/test_deribit.py` | units, missing fields, error bodies, expiry sanity |
| `tests/test_implied_floor.py` | the floor's arithmetic and its empty-input behaviour |
| `research/docs/implied-vs-ours.md` | the result, written when there is one |

`research/harness/payout_logger.py` is extended in Task 6 rather than replaced.

---

### Task 1: The Deribit wire format, with units normalised at the boundary

**Files:**
- Create: `research/harness/deribit.py`
- Test: `tests/test_deribit.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `BASE_TESTNET`, `BASE_LIVE`, `base() -> str`, `Row` (dataclass), `parse_summary(payload: dict) -> list[Row]`, `FIELDS: tuple[str, ...]`.

`Row` fields, exactly: `instrument: str`, `underlying: str`, `kind: str` (`"call"`/`"put"`), `strike: float`, `expiry: float` (**seconds**), `mark_iv: float`, `mark_price: float`, `bid_price: float`, `ask_price: float`, `underlying_price: float`, `open_interest: float`, `volume: float`, `at: float` (**seconds**).

- [ ] **Step 1: Write the failing test for millisecond normalisation**

```python
# tests/test_deribit.py
"""Deribit's wire format, and the one unit that has already bitten this repo.

Every timestamp Deribit sends is in milliseconds. `prices` already carries a
seconds/milliseconds split between `bars.ts` and `quotes.ts`, and a query written
against both without knowing that is wrong in a way that looks plausible. So the
boundary normalises, and these tests are what hold it there.
"""

from __future__ import annotations

from research.harness.deribit import FIELDS, parse_summary

#: One row shaped exactly like `get_book_summary_by_currency` returns, with the
#: field set observed on 2026-09-24.
SUMMARY = {
    "instrument_name": "BTC-24SEP26-71000-C",
    "mark_iv": 40.6,
    "mark_price": 0.0123,
    "bid_price": 0.0120,
    "ask_price": 0.0126,
    "mid_price": 0.0123,
    "underlying_price": 84000.0,
    "open_interest": 12.0,
    "volume": 958.2,
    "creation_timestamp": 1789891252000,
}


def test_the_expiry_is_seconds_not_milliseconds():
    rows = parse_summary({"result": [SUMMARY]}, instruments={
        "BTC-24SEP26-71000-C": {
            "instrument_name": "BTC-24SEP26-71000-C",
            "expiration_timestamp": 1790236800000,
            "strike": 71000.0,
            "option_type": "call",
            "base_currency": "BTC",
        }
    }, at=1790233483.0)
    assert len(rows) == 1
    # 1790236800000 ms is 1790236800 s. Read as seconds it would be 20,699,613
    # days away, which is the shape of the mistake.
    assert rows[0].expiry == 1790236800.0
    assert 0 < rows[0].expiry - rows[0].at < 86400 * 2
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_deribit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'research.harness.deribit'`

- [ ] **Step 3: Write the module**

```python
# research/harness/deribit.py
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

import os
from dataclasses import dataclass, fields

BASE_TESTNET = "https://test.deribit.com"
BASE_LIVE = "https://www.deribit.com"

#: Milliseconds to seconds. Named so the division is never a bare 1000.
MS = 1000.0


def base() -> str:
    """Testnet unless told otherwise. A recorder cannot trade, but it can be wrong
    about which venue it described, and the default should be the harmless one."""
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
    return out if out == out and abs(out) != float("inf") else None


def parse_summary(
    payload: dict, *, instruments: dict[str, dict], at: float
) -> list[Row]:
    """Rows from a `get_book_summary_by_currency` payload.

    `instruments` is the `get_instruments` listing keyed by name, because the
    summary carries no strike, expiry or option type - they are only in the
    instrument record, and joining them here keeps the two shapes out of
    everything downstream.

    A row missing anything the comparison needs is **dropped rather than
    defaulted**. A strike with no book has no bid, and a zero bid would be
    recorded as a free option.
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
        if expiry_ms is None or strike is None or mark_iv is None or mark is None:
            continue
        if bid is None or ask is None:
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
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `.venv/bin/python -m pytest tests/test_deribit.py -q`
Expected: PASS, 1 test.

- [ ] **Step 5: Add the Review-Focus test for a missing book side**

```python
def test_a_strike_with_no_book_is_dropped_not_zeroed():
    """A zero bid recorded as a number is an option that looks free."""
    thin = dict(SUMMARY, bid_price=None, ask_price=None)
    rows = parse_summary({"result": [thin]}, instruments={
        "BTC-24SEP26-71000-C": {
            "instrument_name": "BTC-24SEP26-71000-C",
            "expiration_timestamp": 1790236800000,
            "strike": 71000.0,
            "option_type": "call",
            "base_currency": "BTC",
        }
    }, at=1790233483.0)
    assert rows == []


def test_an_instrument_absent_from_the_listing_is_dropped():
    """The summary and the listing are fetched separately and can disagree."""
    rows = parse_summary({"result": [SUMMARY]}, instruments={}, at=1790233483.0)
    assert rows == []


def test_an_error_body_yields_no_rows_and_does_not_raise():
    """Deribit answers 200 with a JSON-RPC error. That must not look like a quiet market."""
    rows = parse_summary(
        {"error": {"code": 10028, "message": "too_many_requests"}},
        instruments={}, at=1790233483.0,
    )
    assert rows == []


def test_fields_matches_the_dataclass():
    """`FIELDS` is the CSV header, so drift here silently reorders stored columns."""
    assert FIELDS[0] == "instrument"
    assert "expiry" in FIELDS
    assert len(FIELDS) == 13
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_deribit.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 7: Lint and commit**

```bash
.venv/bin/ruff format research/harness/deribit.py tests/test_deribit.py
.venv/bin/ruff check research/harness/deribit.py tests/test_deribit.py
git add research/harness/deribit.py tests/test_deribit.py
git commit -m "research: Deribit's option surface as rows, with milliseconds fixed at the boundary"
```

---

### Task 2: The recorder

**Files:**
- Create: `research/harness/deribit_recorder.py`
- Test: `tests/test_deribit_recorder.py`

**Interfaces:**
- Consumes: `deribit.base`, `deribit.parse_summary`, `deribit.Row`, `deribit.FIELDS`.
- Produces: `CURRENCIES: tuple[str, ...]`, `SWEEP_SECONDS: int`, `writer(out_dir: Path) -> Callable[[list[Row]], None]`, `sweep(client, currency: str, at: float) -> list[Row]`, `main() -> int`.

- [ ] **Step 1: Write the failing test for the error-body case**

```python
# tests/test_deribit_recorder.py
"""The recorder, against a fake transport.

It is the third collector in this repository and it inherits their rule: a
failure is written down, not skipped, so an outage in the data reads as an
outage rather than a gap of unknown cause. What it must never do is write a
file that looks like a successful sweep of a quiet market when the venue
actually refused.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import httpx
import pytest

from research.harness.deribit_recorder import sweep, writer

INSTRUMENTS = [
    {
        "instrument_name": "BTC-24SEP26-71000-C",
        "expiration_timestamp": 1790236800000,
        "strike": 71000.0,
        "option_type": "call",
        "base_currency": "BTC",
    }
]
BOOK = [
    {
        "instrument_name": "BTC-24SEP26-71000-C",
        "mark_iv": 40.6,
        "mark_price": 0.0123,
        "bid_price": 0.0120,
        "ask_price": 0.0126,
        "underlying_price": 84000.0,
        "open_interest": 12.0,
        "volume": 958.2,
    }
]


def transport(instruments, book):
    def handler(request: httpx.Request) -> httpx.Response:
        if "get_instruments" in request.url.path:
            return httpx.Response(200, json={"result": instruments})
        return httpx.Response(200, json={"result": book})

    return httpx.MockTransport(handler)


def test_a_good_sweep_returns_rows():
    with httpx.Client(transport=transport(INSTRUMENTS, BOOK)) as client:
        rows = sweep(client, "BTC", at=1790233483.0)
    assert len(rows) == 1
    assert rows[0].instrument == "BTC-24SEP26-71000-C"


def test_an_error_body_returns_no_rows_rather_than_raising():
    """200 with a JSON-RPC error. The recorder must survive and say nothing was got."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": 10028, "message": "no"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rows = sweep(client, "BTC", at=1790233483.0)
    assert rows == []
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_deribit_recorder.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the recorder**

```python
# research/harness/deribit_recorder.py
"""Record Deribit's option surface, so the implied-volatility question becomes answerable.

    python research/harness/deribit_recorder.py --out ~/options-data --sweeps 1

**This recorder never trades.** It calls two public endpoints - `get_instruments`
and `get_book_summary_by_currency` - and no `private/` route exists in this file.
That is a property of the code, not a promise about how it is invoked.

## Why this is the gate for the whole options programme

An option has to beat the market's **implied** volatility, not a trailing
estimate. Nothing in this repository has ever shown that, because until
2026-09-24 it held no option prices at all. Deribit publishes a `mark_iv` per
instrument and the whole surface arrives in a single REST call, so the comparison
costs a collector and no credentials. If our forecasts cannot beat it, there is no
options edge and no execution path should be built.

## Shape

One HTTP GET per currency per sweep. Gzipped CSV, one file a day, appended - the
same shape as `payout_logger.py`, and for the same reason: a research collector
that needs a schema migration to add a column is a collector that stops
collecting.

Failures are written in as rows, so an outage appears in the data as an outage.
The one thing that must not happen is an empty successful-looking sweep: Deribit
answers **HTTP 200 with a JSON-RPC error body**, so a naive reader records a quiet
market when the venue actually refused.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import signal
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from research.harness import deribit

#: Currencies with a liquid option surface on Deribit.
CURRENCIES: tuple[str, ...] = ("BTC", "ETH")

#: Seconds between sweeps. Five minutes: the surface is 1,050 rows, so this is
#: about 300k rows a day per currency, and an implied vol does not move meaningfully
#: faster than this for a forecast measured over hours.
SWEEP_SECONDS = 300

#: Seconds between the two calls in one sweep, and between currencies. Deribit
#: publishes a rate limit and a research collector should stay far inside it.
REQUEST_PAUSE = 1.0

_stopping = False


def _stop(*_args: object) -> None:
    global _stopping
    _stopping = True


def _get(client: httpx.Client, path: str, params: dict) -> dict:
    """One public call. Returns the payload, or `{}` on anything that went wrong.

    Deribit answers 200 with `{"error": ...}`, so a status check is not enough and
    the caller cannot distinguish a refusal from an empty market without this.
    """
    try:
        reply = client.get(f"{deribit.base()}/api/v2/{path}", params=params, timeout=30.0)
    except httpx.HTTPError:
        return {}
    if reply.status_code != 200:
        return {}
    try:
        body = reply.json()
    except ValueError:
        return {}
    return {} if "error" in body else body


def sweep(client: httpx.Client, currency: str, at: float) -> list[deribit.Row]:
    """The whole surface for one currency, or an empty list."""
    listing = _get(
        client,
        "public/get_instruments",
        {"currency": currency, "kind": "option", "expired": "false"},
    )
    instruments = {
        str(row.get("instrument_name")): row for row in (listing.get("result") or [])
    }
    if not instruments:
        return []
    time.sleep(REQUEST_PAUSE)
    book = _get(
        client,
        "public/get_book_summary_by_currency",
        {"currency": currency, "kind": "option"},
    )
    return deribit.parse_summary(book, instruments=instruments, at=at)


def writer(out_dir: Path) -> Callable[[list[deribit.Row]], None]:
    """Append rows to today's gzipped CSV, writing the header once."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def write(rows: list[deribit.Row]) -> None:
        if not rows:
            return
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        path = out_dir / f"deribit_{day}.csv.gz"
        fresh = not path.exists()
        with gzip.open(path, "at", newline="") as handle:
            out = csv.DictWriter(handle, fieldnames=list(deribit.FIELDS))
            if fresh:
                out.writeheader()
            for row in rows:
                out.writerow({name: getattr(row, name) for name in deribit.FIELDS})

    return write


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.environ.get("OUT", "deribit"))
    parser.add_argument(
        "--sweeps",
        type=int,
        default=int(os.environ.get("SWEEPS", "0")) or None,
        help="stop after this many sweeps; omit to run until stopped",
    )
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    write = writer(Path(args.out).expanduser())
    done = 0
    print(f"recording {deribit.base()}", flush=True)
    with httpx.Client() as client:
        while not _stopping and (args.sweeps is None or done < args.sweeps):
            got = 0
            for currency in CURRENCIES:
                rows = sweep(client, currency, at=time.time())
                write(rows)
                got += len(rows)
                time.sleep(REQUEST_PAUSE)
            done += 1
            print(
                f"{datetime.now(UTC):%H:%M:%S} sweep {done}: {got} rows",
                flush=True,
            )
            if args.sweeps is not None and done >= args.sweeps:
                break
            for _ in range(SWEEP_SECONDS):
                if _stopping:
                    break
                time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_deribit_recorder.py -q`
Expected: PASS, 2 tests.

- [ ] **Step 5: Add the write-path tests**

```python
def test_the_header_is_written_once(tmp_path):
    with httpx.Client(transport=transport(INSTRUMENTS, BOOK)) as client:
        rows = sweep(client, "BTC", at=1790233483.0)
    write = writer(tmp_path)
    write(rows)
    write(rows)
    path = next(tmp_path.glob("deribit_*.csv.gz"))
    text = gzip.open(path, "rt").read()
    assert text.count("instrument,underlying") == 1
    assert text.count("BTC-24SEP26-71000-C") == 2


def test_no_rows_writes_no_file(tmp_path):
    """An empty sweep must not create a file that reads as a quiet market."""
    writer(tmp_path)([])
    assert list(tmp_path.glob("*.csv.gz")) == []


def test_there_is_no_private_endpoint_anywhere_in_this_file():
    """The 'never trades' property, asserted rather than promised."""
    source = Path("research/harness/deribit_recorder.py").read_text()
    assert "private/" not in source
    assert "api_key" not in source.lower()
```

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_deribit_recorder.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 7: Run one live sweep against testnet**

Run: `.venv/bin/python research/harness/deribit_recorder.py --out /tmp/deribit-check --sweeps 1`
Expected: `recording https://test.deribit.com` then a sweep line with roughly 2,000 rows (about 1,050 BTC plus ETH). If it reports 0, the parse is dropping rows — check the instrument join before going further.

- [ ] **Step 8: Lint and commit**

```bash
.venv/bin/ruff format research/harness/deribit_recorder.py tests/test_deribit_recorder.py
.venv/bin/ruff check research/harness/deribit_recorder.py tests/test_deribit_recorder.py
git add research/harness/deribit_recorder.py tests/test_deribit_recorder.py
git commit -m "research: record Deribit's option surface, one REST call a currency"
```

---

### Task 3: The detection floor, computed before any scoring

**Files:**
- Create: `research/harness/implied_floor.py`
- Test: `tests/test_implied_floor.py`

**Interfaces:**
- Consumes: `deribit.FIELDS` (column names only).
- Produces: `cost_fraction(bid: float, ask: float, mark: float) -> float | None`, `floor(rows: Iterable[dict]) -> dict[str, float]`.

`floor` returns keys: `n`, `median_cost`, `mean_cost`, `p90_cost`, `iv_points_needed`.

- [ ] **Step 1: Write the failing tests, including the empty case**

```python
# tests/test_implied_floor.py
"""What a forecast has to beat before it means anything.

Computed and written down **before** the comparison, because a floor chosen after
seeing the result is not a floor. Half the bid/ask spread as a fraction of mark is
what a round trip costs; a forecast that beats `mark_iv` by less than that is a
forecast that loses money being right.
"""

from __future__ import annotations

import math

from research.harness.implied_floor import cost_fraction, floor


def test_half_the_spread_over_mark():
    # bid 0.0120, ask 0.0126 -> half-spread 0.0003, mark 0.0123
    got = cost_fraction(0.0120, 0.0126, 0.0123)
    assert got is not None
    assert math.isclose(got, 0.0003 / 0.0123, rel_tol=1e-9)


def test_a_zero_mark_has_no_cost_fraction():
    """Dividing by it would report an infinite or absurd cost as a number."""
    assert cost_fraction(0.0, 0.0, 0.0) is None


def test_a_crossed_book_is_refused():
    """ask below bid is bad data, not a negative cost."""
    assert cost_fraction(0.0126, 0.0120, 0.0123) is None


def test_an_empty_surface_does_not_divide_by_zero():
    """A delisted or brand-new currency returns nothing, which is an answer."""
    got = floor([])
    assert got["n"] == 0
    assert math.isnan(got["median_cost"])
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_implied_floor.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the module**

```python
# research/harness/implied_floor.py
"""The bar a volatility forecast has to clear on Deribit, from recorded data.

## Why this is its own file, and runs first

The result of phase 0 is a comparison, and a comparison needs a threshold decided
in advance. Every null in `research/docs/` that survived scrutiny had its
detection floor computed before the study; the ones that did not are the ones that
had to be retracted.

## What the cost actually is

`bid_iv` and `ask_iv` are **not** in `get_book_summary_by_currency` - they need one
`get_order_book` call per instrument, and there are 1,050 of them. So cost is taken
in price terms, which is what is paid anyway:

    cost_fraction = ((ask - bid) / 2) / mark

Half the spread, because a single trade crosses half of it. As a fraction of mark,
so it is comparable across strikes whose premiums differ by orders of magnitude.

**This makes phase 0 a weaker test than the ideal one.** The ideal compares our
forecast against `ask_iv` when buying and `bid_iv` when selling. This compares
against `mark_iv` and subtracts a price-terms cost, which is not the same thing,
and the write-up must say so rather than imply a cleaner experiment than was run.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable


def cost_fraction(bid: float, ask: float, mark: float) -> float | None:
    """Half the spread over mark, or `None` when the book cannot say.

    `None` rather than zero throughout. A strike with no book has no cost *that we
    know of*, and recording that as zero is recording a free option.
    """
    for value in (bid, ask, mark):
        if value is None or not math.isfinite(value):
            return None
    if mark <= 0.0 or ask < bid:
        return None
    return ((ask - bid) / 2.0) / mark


def floor(rows: Iterable[dict]) -> dict[str, float]:
    """The floor over a recorded surface.

    `iv_points_needed` converts the median cost into volatility points, the units
    `mark_iv` is quoted in, using the crude local approximation that a relative
    change in premium of `c` needs a relative change in implied volatility of about
    `c` near the money. It is a scale, not a pricing model, and it is here so the
    floor can be stated in the same units as the thing it gates.
    """
    costs = [
        c
        for row in rows
        if (
            c := cost_fraction(
                float(row.get("bid_price") or "nan"),
                float(row.get("ask_price") or "nan"),
                float(row.get("mark_price") or "nan"),
            )
        )
        is not None
    ]
    if not costs:
        nan = float("nan")
        return {
            "n": 0,
            "median_cost": nan,
            "mean_cost": nan,
            "p90_cost": nan,
            "iv_points_needed": nan,
        }
    costs.sort()
    median = statistics.median(costs)
    return {
        "n": len(costs),
        "median_cost": median,
        "mean_cost": statistics.fmean(costs),
        "p90_cost": costs[min(len(costs) - 1, int(0.90 * len(costs)))],
        "iv_points_needed": median * 100.0,
    }
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_implied_floor.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 5: Add the aggregate test**

```python
def test_the_floor_reports_a_median_and_a_count():
    rows = [
        {"bid_price": 0.010, "ask_price": 0.012, "mark_price": 0.011},
        {"bid_price": 0.020, "ask_price": 0.024, "mark_price": 0.022},
        {"bid_price": None, "ask_price": None, "mark_price": 0.030},
    ]
    got = floor(rows)
    assert got["n"] == 2
    assert got["median_cost"] > 0
    assert math.isclose(got["iv_points_needed"], got["median_cost"] * 100.0)
```

- [ ] **Step 6: Run and commit**

```bash
.venv/bin/python -m pytest tests/test_implied_floor.py -q
.venv/bin/ruff format research/harness/implied_floor.py tests/test_implied_floor.py
.venv/bin/ruff check research/harness/implied_floor.py tests/test_implied_floor.py
git add research/harness/implied_floor.py tests/test_implied_floor.py
git commit -m "research: the detection floor for the implied-volatility comparison, computed first"
```

---

### Task 4: The comparison

**Files:**
- Create: `research/harness/implied_vs_ours.py`
- Test: `tests/test_implied_vs_ours.py`

**Interfaces:**
- Consumes: `implied_floor.floor`, `deribit.FIELDS`.
- Produces: `realised_vol(closes: np.ndarray, bars: int) -> np.ndarray`, `annualise(sigma_per_bar: float, bar_seconds: float) -> float`, `horizon_bars(expiry: float, at: float, bar_seconds: float) -> int | None`, `qlike(actual, forecast) -> float`, `main() -> int`.

- [ ] **Step 1: Write the failing test for the expired-option case**

```python
# tests/test_implied_vs_ours.py
"""Scoring our volatility forecast against Deribit's implied, and the traps in it.

The load-bearing test is `test_an_expired_option_is_refused`. `expired=false` is a
request to Deribit, not a guarantee from it, and an expiry already in the past
makes the realised-volatility window negative - which does not raise, it silently
scores the forecast against a window running backwards.
"""

from __future__ import annotations

import numpy as np

from research.harness.implied_vs_ours import annualise, horizon_bars, qlike, realised_vol

HOUR = 3600.0


def test_an_expired_option_is_refused():
    assert horizon_bars(expiry=1_000.0, at=2_000.0, bar_seconds=60.0) is None


def test_an_option_expiring_this_instant_is_refused():
    """A zero-length window is not a forecast horizon."""
    assert horizon_bars(expiry=2_000.0, at=2_000.0, bar_seconds=60.0) is None


def test_the_horizon_is_in_bars():
    assert horizon_bars(expiry=2_000.0 + 2 * HOUR, at=2_000.0, bar_seconds=HOUR) == 2


def test_annualising_scales_with_the_square_root_of_time():
    a = annualise(0.01, 60.0)
    b = annualise(0.01, 240.0)
    # Four times the bar length is half the annualised sigma for the same per-bar value.
    assert np.isclose(a / b, 2.0, rtol=1e-9)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_implied_vs_ours.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Write the module**

```python
# research/harness/implied_vs_ours.py
"""Do this desk's volatility forecasts beat Deribit's implied volatility?

    python research/harness/implied_vs_ours.py --surface ~/options-data --bars ~/bars

**This is the gate for the options programme.** Everything the research folder has
found that works predicts *size*: `crash-timing.md`'s big-move score at AUC
0.65-0.81, `news-volatility.md`'s 2.4x release bar, `implied.md`'s VIX result. None
of it has ever been scored against an option market's own forecast, because there
were no option prices here to score against.

`implied.md` is also the warning. There, the market's volatility index **beat**
our trailing estimates by 12-20 points of R-squared. The opponent in this file is
the same kind of object, and the prior should be that it wins.

## The comparison

For each recorded quote, take the option's remaining life as the forecast horizon,
compute what volatility the underlying **actually** realised over that window from
bars, and score two forecasts against it by QLIKE:

* **Deribit's** `mark_iv`;
* **ours** - a trailing estimate over the same horizon, which is the baseline that
  has already beaten a three-state HMM, a 50-neighbour analogue and persistence
  landscapes elsewhere in this folder.

QLIKE rather than squared error because variance loss is asymmetric and squared
error on a variance rewards under-forecasting; it is the loss `similarity_grid.py`,
`regimes.py` and `susceptibility.py` all use, so the numbers are comparable.

**Walk-forward, and the floor first.** `implied_floor.floor` is printed before any
score, and a win smaller than it is reported as a null.

## What this cannot establish

Deribit lists BTC and ETH. This desk's best-validated volatility work is on indices
and gold through VIX, so a positive result here is on the underlyings where our
forecasts are **least** proven, and a negative one does not transfer to the
instruments IBKR would reach. That asymmetry belongs in the write-up.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import math
import sys
from pathlib import Path

import numpy as np

from research.harness.implied_floor import floor

#: Seconds in a year, calendar. Crypto trades continuously, so a 252-day trading
#: year would overstate annualised sigma by about 1.9x and make every comparison
#: wrong in the same direction.
YEAR_SECONDS = 365.0 * 24.0 * 3600.0

#: Fewest paired observations before a QLIKE is reported. The same 200 the other
#: harnesses use, so a thin cell reads as thin rather than as a result.
MIN_PAIRS = 200


def annualise(sigma_per_bar: float, bar_seconds: float) -> float:
    """A per-bar standard deviation as an annualised fraction."""
    if sigma_per_bar <= 0.0 or bar_seconds <= 0.0:
        return float("nan")
    return sigma_per_bar * math.sqrt(YEAR_SECONDS / bar_seconds)


def horizon_bars(expiry: float, at: float, bar_seconds: float) -> int | None:
    """Bars from the quote to the option's expiry, or `None` if that is not forward.

    `None` for anything at or before `at`. Deribit's `expired=false` is a request
    rather than a guarantee, and a negative window does not raise - it scores the
    forecast against a window running backwards.
    """
    if bar_seconds <= 0.0:
        return None
    seconds = expiry - at
    if seconds <= 0.0:
        return None
    bars = int(seconds // bar_seconds)
    return bars if bars >= 1 else None


def realised_vol(closes: np.ndarray, bars: int) -> np.ndarray:
    """Forward realised per-bar sigma over `bars`, aligned to the window's start."""
    returns = np.diff(np.log(closes))
    out = np.full(len(closes), np.nan)
    if bars < 2 or len(returns) < bars:
        return out
    squared = returns**2
    # A rolling mean of squared returns, then a root. Cumsum rather than a loop
    # because the surface is hundreds of thousands of rows.
    cumulative = np.concatenate([[0.0], np.cumsum(squared)])
    window = cumulative[bars:] - cumulative[:-bars]
    out[: len(window)] = np.sqrt(window / bars)
    return out


def qlike(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Variance loss: `a/f - log(a/f) - 1`. Lower is better."""
    ok = (actual > 0) & (forecast > 0) & np.isfinite(actual) & np.isfinite(forecast)
    if ok.sum() < MIN_PAIRS:
        return float("nan")
    ratio = actual[ok] / forecast[ok]
    return float(np.mean(ratio - np.log(ratio) - 1.0))


def read_surface(directory: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(directory.glob("deribit_*.csv.gz")):
        with gzip.open(path, "rt", newline="") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", required=True, help="where the recorder wrote")
    parser.add_argument("--bars", required=True, help="where the underlying bars are")
    parser.add_argument("--interval-seconds", type=float, default=3600.0)
    args = parser.parse_args()

    rows = read_surface(Path(args.surface).expanduser())
    if not rows:
        print("no recorded surface - run the recorder first", file=sys.stderr)
        return 1

    print(f"{len(rows):,} recorded quotes")
    bar = floor(rows)
    print("\n=== the floor, before any score")
    print(f"  {bar['n']:,} quotes with a usable book")
    print(f"  median round-trip cost: {100 * bar['median_cost']:.2f}% of premium")
    print(f"  which is about {bar['iv_points_needed']:.2f} volatility points")
    print("  a win smaller than this is a null, whatever its sign")
    print(
        "\n=== the comparison is not implemented until there is a surface to run it on."
        "\n    Record for a week, then extend this with the bar join: it needs enough"
        "\n    distinct expiries that the horizons are not all the same number."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_implied_vs_ours.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 5: Add the realised-volatility and QLIKE tests**

```python
def test_realised_vol_of_a_flat_series_is_zero():
    out = realised_vol(np.ones(100), bars=10)
    assert np.nanmax(out) == 0.0


def test_realised_vol_recovers_a_known_sigma():
    rng = np.random.default_rng(7)
    sigma = 0.01
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0, sigma, 20_000)))
    out = realised_vol(closes, bars=200)
    assert np.isclose(np.nanmedian(out), sigma, rtol=0.15)


def test_realised_vol_is_nan_when_the_window_exceeds_the_data():
    out = realised_vol(np.ones(5), bars=50)
    assert np.isnan(out).all()


def test_qlike_is_zero_for_a_perfect_forecast():
    a = np.full(500, 0.01)
    assert np.isclose(qlike(a, a), 0.0)


def test_qlike_is_nan_on_a_thin_sample():
    """A thin cell must read as thin, not as a result."""
    a = np.full(10, 0.01)
    assert np.isnan(qlike(a, a))
```

- [ ] **Step 6: Run and commit**

```bash
.venv/bin/python -m pytest tests/test_implied_vs_ours.py -q
.venv/bin/ruff format research/harness/implied_vs_ours.py tests/test_implied_vs_ours.py
.venv/bin/ruff check research/harness/implied_vs_ours.py tests/test_implied_vs_ours.py
git add research/harness/implied_vs_ours.py tests/test_implied_vs_ours.py
git commit -m "research: the implied-volatility comparison, with the floor printed before any score"
```

---

### Task 5: Start the recorder collecting

**Files:**
- Modify: `.gitignore`
- Modify: `docs/deployment.md`

**Interfaces:**
- Consumes: `deribit_recorder.main`.
- Produces: a running collector and a documented way to check it.

- [ ] **Step 1: Gitignore the data directory**

```bash
grep -q '^options-data/' .gitignore || printf '\n# Recorded option surfaces. Market data, never committed.\noptions-data/\n' >> .gitignore
git add .gitignore && git commit -m "chore: ignore recorded option surfaces"
```

- [ ] **Step 2: Run a single sweep and check the columns**

Run:
```bash
.venv/bin/python research/harness/deribit_recorder.py --out options-data --sweeps 1
.venv/bin/python -c "
import gzip, glob, csv, collections
rows = list(csv.DictReader(gzip.open(sorted(glob.glob('options-data/deribit_*.csv.gz'))[-1], 'rt')))
print(len(rows), 'rows')
print('underlyings:', collections.Counter(r['underlying'] for r in rows))
print('any zero mark_iv:', sum(1 for r in rows if float(r['mark_iv']) <= 0))
"
```
Expected: a few thousand rows, both BTC and ETH present, zero rows with a non-positive `mark_iv`. A count of zero rows means the instrument join failed.

- [ ] **Step 3: Start it detached on the research machine, not on tis**

Production has two cores and 3 GB and has been OOM-killed 63 times; research belongs on the lab. Run:
```bash
./.secrets/lab.sh sync
./.secrets/lab.sh run research/harness/deribit_recorder.py OUT=~/options-data
./.secrets/lab.sh log deribit_recorder
```
Expected: `recording https://test.deribit.com` and a sweep line every five minutes.

- [ ] **Step 4: Document the check**

Append to `docs/deployment.md`, under a new `## The Deribit option-surface recorder` heading, text stating: it runs on the research machine and never on the instance; it is public-data only and cannot trade; `./.secrets/lab.sh done deribit_recorder` says whether it has stopped; and that a week of it is the input to `implied_vs_ours.py`.

- [ ] **Step 5: Commit**

```bash
git add docs/deployment.md
git commit -m "docs: how to run and check the Deribit surface recorder"
```

---

### Task 6: Phase 1 — reduce the Deriv logger to the two things still worth watching

**Files:**
- Modify: `research/harness/payout_logger.py`
- Modify: `tests/test_payout_logger.py`

**Interfaces:**
- Consumes: the existing `SYMBOLS`, `DURATIONS`, `cells`, `quote`.
- Produces: `ACCU_SYMBOLS: tuple[str, ...]`, `accu_quote(ws, symbol: str, growth: float) -> dict`, `REAL_PREFIXES: tuple[str, ...]`.

`deriv-payouts.md` and `accumulators.md` closed the Deriv question. Two triggers remain and both are cheap to watch: `ACCU` appearing on a **real** instrument, and the accumulator barrier widening past break-even.

- [ ] **Step 1: Write the failing test for the trigger**

```python
# appended to tests/test_payout_logger.py
def test_an_accumulator_on_a_real_instrument_is_flagged():
    """The one trigger that would reopen accumulators.

    `accumulators.md` found ACCU on 27 of 89 instruments, all synthetic, and the
    signal that would time it works only on real markets. A real-instrument
    listing is therefore the event to watch for, and it has to be loud.
    """
    from research.harness.payout_logger import is_real

    assert is_real("frxEURUSD")
    assert is_real("cryBTCUSD")
    assert not is_real("R_100")
    assert not is_real("BOOM1000")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/test_payout_logger.py -q`
Expected: FAIL — `ImportError: cannot import name 'is_real'`

- [ ] **Step 3: Add the accumulator sensor**

```python
# added to research/harness/payout_logger.py

#: Prefixes Deriv gives instruments that are not its own generators. The whole
#: accumulator question turns on this distinction: `accumulators.md` found ACCU on
#: 27 of 89 instruments and every one synthetic, where sigma is a published
#: constant and there is nothing to forecast. One of these appearing with an
#: accumulator is the event that reopens the study.
REAL_PREFIXES: tuple[str, ...] = ("frx", "cry")

#: Growth rates to probe. Each carries its own barrier.
ACCU_RATES: tuple[float, ...] = (0.01, 0.03, 0.05)

#: Break-even barrier in per-tick sigmas at `g=0.03`, from `accumulators.md`. The
#: barrier sat at 2.132 when measured; past 2.18 the arithmetic flips with no
#: signal required, which is the second trigger.
BREAK_EVEN_SIGMAS = 2.18


def is_real(symbol: str) -> bool:
    """Is this a market Deriv did not generate?"""
    return symbol.startswith(REAL_PREFIXES)
```

- [ ] **Step 4: Run the test**

Run: `.venv/bin/python -m pytest tests/test_payout_logger.py -q`
Expected: PASS, 15 tests.

- [ ] **Step 5: Add the barrier-widening test**

```python
def test_a_widened_barrier_is_flagged():
    """The second trigger: past break-even the contract pays with no signal."""
    from research.harness.payout_logger import BREAK_EVEN_SIGMAS, barrier_favourable

    assert not barrier_favourable(2.132)   # as measured 2026-09-24
    assert barrier_favourable(BREAK_EVEN_SIGMAS + 0.01)
```

- [ ] **Step 6: Implement it**

```python
# added to research/harness/payout_logger.py
def barrier_favourable(sigmas: float) -> bool:
    """Would an accumulator at this barrier pay, before any signal?

    `accumulators.md` derives the exact break-even: stake grows by `g` per
    surviving tick and a breach pays zero, so `p*(1+g) = 1` and the fair barrier
    is `Phi_inverse((1+1/(1+g))/2)` sigmas - 2.18 at `g=0.03`. Deriv quoted 2.132.
    """
    return sigmas > BREAK_EVEN_SIGMAS
```

- [ ] **Step 7: Run, lint and commit**

```bash
.venv/bin/python -m pytest tests/test_payout_logger.py -q
.venv/bin/ruff format research/harness/payout_logger.py tests/test_payout_logger.py
.venv/bin/ruff check research/harness/payout_logger.py tests/test_payout_logger.py
git add research/harness/payout_logger.py tests/test_payout_logger.py
git commit -m "research: reduce the Deriv logger to the two triggers that would reopen it"
```

---

### Task 7: The write-up, when there is a result

**Files:**
- Create: `research/docs/implied-vs-ours.md`
- Modify: `research/docs/README.md`

Do this only after a week of recording and a run of `implied_vs_ours.py` with a real QLIKE in it.

- [ ] **Step 1: Write the result, floor first**

The document must open with the floor, state the QLIKE for `mark_iv` and for ours side by side, and say plainly which won. It must carry the two limitations the spec names: the comparison is against `mark_iv` rather than `ask_iv`/`bid_iv`, and BTC/ETH are the underlyings where this desk's volatility work is least proven.

- [ ] **Step 2: Add the one-line index entry**

Add a row to `research/docs/README.md`'s table in the existing style, stating the verdict rather than the topic.

- [ ] **Step 3: Commit**

```bash
git add research/docs/implied-vs-ours.md research/docs/README.md
git commit -m "research: whether our volatility forecasts beat Deribit's implied"
```

---

## Self-Review

**Spec coverage.** Phase 0 is Tasks 1–5 and 7; phase 1 is Task 6. Phases 2 (paper book) and 3 (IBKR) are deliberately absent — the spec makes them conditional on phase 0's result, and they get their own plan. The spec's recorder constraints are honoured: bounded cost (one call per currency), `shared/db.py`'s pragmas not needed because phase 0 writes CSV rather than SQLite — **a deliberate narrowing from the spec's `options.db`**, since 1,050 rows every five minutes does not need a database and CSV keeps phase 0 out of the production process entirely. The spec's `catalogue()` requirement is met in spirit by Task 2 fetching `get_instruments` every sweep rather than hardcoding a grid.

**Placeholders.** Task 4's `main` deliberately stops short of the bar join and says so in its own output, because the join needs recorded data with a spread of expiries that does not exist yet; Task 7 is gated on that. That is a stated dependency, not a TODO. Task 5 Step 4 describes documentation content rather than quoting it, which is the one place in this plan where the exact words do not matter.

**Type consistency.** `Row` is defined in Task 1 and consumed in Task 2 by `sweep`/`writer`. `FIELDS` is the CSV header in Task 2 and the column names read back in Tasks 3 and 4. `floor` returns the five keys Task 4's `main` prints. `cost_fraction` returns `float | None` and every caller checks.

**Review Focus.** Items 1, 3 → Task 1 Step 5 and Task 2 Step 5. Item 2 → Task 4 Step 1. Item 4 → Task 1 Step 1. Item 5 → Task 3 Step 1.
