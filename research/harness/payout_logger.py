"""Log rise/fall payouts, so the one untested hypothesis becomes answerable from history.

Run detached on the research machine:

    python research/harness/payout_logger.py --out ~/till_infinity/data/payouts

**This logger never trades.** It sends `proposal` requests only - a proposal is a price quote -
and the `buy` call is not implemented anywhere in this file. That is a property of the code, not
a promise about how it is invoked.

## Why this exists

`barrier-geometry-is-irrelevant.md` derived that a barrier trade earns `m = mu E[tau]` and
nothing else, which closed most of this research. **A rise/fall binary is the one instrument on
this account that the result does not cover**: it has no stop, no target and no overshoot, so
expectancy is

    E = p * payout - (1 - p) * stake

depending only on `p` and on the payout - and the payout is **quoted by the broker**, which makes
it an observable the price series cannot contain. `a-theory-from-ohlc.md` concludes the binding
constraint here is data rather than method; this is a second sensor that costs nothing to record.

The test could not be run when it was proposed: Deriv's WebSocket endpoint returned HTTP 520 from
three independent hosts, on every app_id and on the bare root, while `api.deriv.com` and
`app.deriv.com` answered normally - an outage on their side rather than a block or a credential
problem. And the journal has never recorded a payout, so there was no history to fall back on.
**That is the gap this closes.** It starts collecting the moment the endpoint returns.

## What is logged, and why both directions

For each symbol and duration, **both CALL and PUT are quoted at the same instant**. That is the
whole design, and quoting one side would waste the exercise.

A payout implies a probability, `implied = stake / payout`. The two sides do not sum to one - they
sum to one plus the broker's margin:

    margin = implied(CALL) + implied(PUT) - 1

so quoting both separates the margin, which is a cost, from the **asymmetry**

    skew = implied(CALL) - implied(PUT)

which is the broker's directional view. The margin is not tradeable and is the same whichever way
you bet. The skew is the only part that could carry information, and it is exactly a forecast of
`sign(m)` over the contract's duration - the quantity `(6)` says is the only one that can pay.

**The outcome is not logged and does not need to be.** A rise/fall contract settles on whether the
close after `duration` exceeds the close at entry, which is recoverable from bars already held. So
this file stays stateless: no contract tracking, no reconciliation, nothing to go stale.

## What the analysis will be, once there is a month of this

Three comparisons, in order of what they can establish:

* **margin** against the costs in `costs.md` - a binary whose margin exceeds any plausible edge is
  dead before the signal question is asked, and that is answerable from the first day of data;
* **calibration** - does `implied(CALL)` match the realised frequency of a rise over the same
  duration, measured from bars? Systematic bias in either direction is the edge;
* **skew against realised drift** - does the asymmetry move with the drift that follows it, or is
  it a fixed spread around one half?

The third is the hypothesis. The first will probably end it.

## Operational care

Quotes are requested on a fixed cadence with a pause between each, because a research collector
that hammers a broker's API is both rude and likely to be throttled into uselessness. Failures are
**written into the log as rows** rather than skipped, so an outage appears in the data as an
outage rather than as a gap of unknown cause - which is the same reasoning that put `repaired`
counts in `candles.read`.

Authentication is not used: a proposal needs none. `DERIV_API_TOKEN` is read from the environment
if present, for symbols that turn out to require it, and is never written to the log or to disk.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import datetime as dt
import json
import os
import signal
import sys
from pathlib import Path

#: Deriv's public endpoints, tried in order. A registered `app_id` belongs in `DERIV_APP_ID`.
#:
#: **Corrected 2026-09-24. The first three were not an outage - they were retired.** This file
#: shipped believing Deriv's API was down, because every `/websockets/v3` host answered HTTP 520
#: from several networks for days. They still do. What actually happened is a migration: the
#: options API now lives on a different host, under a different path, and answers immediately.
#:
#: The lesson is worth keeping next to the list. A 520 from Cloudflare was read as "their origin
#: is broken" when it equally means "nothing is served here any more", and three days were spent
#: waiting for a recovery that was never coming. Two checks would have separated them: an actual
#: WebSocket handshake rather than a plain GET, and a look at the current documentation for the
#: endpoint the docs recommend today.
#:
#: The retired hosts are kept, last, and deliberately. If the new endpoint is itself transitional
#: then the old ones coming back is a thing worth noticing rather than a thing to have deleted.
ENDPOINTS = (
    "wss://api.derivws.com/trading/v1/options/ws/public",
    "wss://ws.derivws.com/websockets/v3?app_id={app_id}",
    "wss://ws.binaryws.com/websockets/v3?app_id={app_id}",
    "wss://green.derivws.com/websockets/v3?app_id={app_id}",
)

#: Symbols to quote, with the shortest duration in minutes each one will actually accept.
#:
#: **Measured against the venue on 2026-09-24, not assumed.** The pairing matters because a
#: request below a symbol's floor is refused, and a refusal written into the log is supposed to
#: mean *something changed* - see the module docstring on failures-as-rows. Thousands of rows
#: saying `ContractValidationError` for a combination known to be impossible would destroy that
#: signal, which is the one thing this file's error handling is for.
#:
#: The volatility indices carry every duration and are also the ones this desk has the deepest bar
#: history for, which is what the outcome is recovered from.
#:
#: **Boom and Crash are absent, and that is a finding rather than an omission.** Both are listed as
#: tradable on the venue and neither quotes a CALL at any duration tried - 1m, 5m, 15m, 60m or 1d.
#: They are the two synthetics with a *designed* asymmetry, which `susceptibility.md` recovered at
#: +0.136 and -0.136 through realised semivariance, so they were the interesting ones to price. The
#: venue does not sell the option. Re-check before concluding anything from their absence here.
SYMBOLS: tuple[tuple[str, int], ...] = (
    ("R_10", 1),
    ("R_25", 1),
    ("R_50", 1),
    ("R_75", 1),
    ("R_100", 1),
    # Gold takes 5m; the two pairs will not go below 15m. No reason for the difference is
    # published, and guessing at one would be worse than recording the floor.
    ("frxXAUUSD", 5),
    ("frxEURUSD", 15),
    ("frxGBPUSD", 15),
)

#: Durations in minutes. Short, because that is where bar data can settle the outcome precisely
#: and where the carry that kills everything else does not have time to accumulate.
#:
#: Each is asked of a symbol only if it clears that symbol's floor above. **60m is not dropped for
#: the pairs**: it clears, and an intraday option on a real instrument is the interesting cell -
#: the desk's own forecasts work at 1m to 1h, so a venue that would only sell days would have been
#: the end of the question.
DURATIONS = (1, 5, 15, 60)

#: Prefixes Deriv gives instruments it did **not** generate itself. The whole
#: accumulator question turns on this distinction: `accumulators.md` found ACCU on
#: 27 of 89 instruments and every one synthetic, where sigma is a published constant
#: and there is nothing to forecast, while the `chi` signal that would time it reads
#: -1.1% to +0.3% there against +5 to +9 points on real markets. One of these
#: prefixes appearing with an accumulator is the event that reopens the study.
REAL_PREFIXES: tuple[str, ...] = ("frx", "cry")

#: Break-even barrier in per-tick sigmas at `g=0.03`, derived in `accumulators.md`:
#: stake grows by `g` per surviving tick and a breach pays zero, so `p*(1+g) = 1`,
#: the fair per-tick survival is `1/(1+g)`, and a two-sided barrier at `x` sigmas
#: survives with probability `2*Phi(x) - 1`. Solving gives 2.18.
#:
#: Deriv quoted **2.132** on 2026-09-24 - constant to 0.0008 across five indices
#: spanning a tenfold range of sigma, so it is a set price rather than an accident.
#: Past 2.18 the arithmetic flips with no signal required, which is the second thing
#: worth watching for.
BREAK_EVEN_SIGMAS = 2.18


def is_real(symbol: str) -> bool:
    """Is this a market Deriv did not generate?

    Prefix rather than a list, because the list changes and the prefixes have not.
    Everything else - `R_*`, `1HZ*`, `BOOM*`, `CRASH*`, `JD*`, `stpRNG*`, `RB*` -
    is one of Deriv's own processes.
    """
    return symbol.startswith(REAL_PREFIXES)


def barrier_favourable(sigmas: float) -> bool:
    """Would an accumulator at this barrier pay, before any signal is applied?"""
    return sigmas > BREAK_EVEN_SIGMAS


#: Stake used for every quote. Fixed, so `implied = stake / payout` is comparable across rows.
STAKE = 10.0

#: Seconds between full sweeps, and between individual requests inside one.
SWEEP_SECONDS = 300
REQUEST_PAUSE = 0.4

#: Seconds to wait before retrying after the endpoint refuses.
BACKOFF = 60

FIELDS = (
    "ts",
    "symbol",
    "duration_min",
    "contract",
    "payout",
    "ask_price",
    "spot",
    "implied",
    "error",
)


def writer(out_dir: Path):
    """Append to a daily CSV, so a long run does not become one unmanageable file."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def write(rows: list[dict]) -> None:
        if not rows:
            return
        day = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
        path = out_dir / f"payouts_{day}.csv"
        fresh = not path.exists()
        with open(path, "a", newline="") as handle:
            out = csv.DictWriter(handle, fieldnames=FIELDS)
            if fresh:
                out.writeheader()
            out.writerows(rows)

    return write


async def quote(ws, symbol: str, minutes: int, contract: str) -> dict:
    """One proposal. Returns a row, including a row describing a failure."""
    now = int(dt.datetime.now(dt.UTC).timestamp())
    base = {
        "ts": now,
        "symbol": symbol,
        "duration_min": minutes,
        "contract": contract,
        "payout": "",
        "ask_price": "",
        "spot": "",
        "implied": "",
        "error": "",
    }
    request = {
        "proposal": 1,
        "amount": STAKE,
        "basis": "stake",
        "contract_type": contract,
        "currency": "USD",
        "duration": minutes,
        "duration_unit": "m",
        # **`underlying_symbol`, not `symbol`.** The migrated endpoint renamed it and rejects the
        # old spelling outright with `Properties not allowed: symbol` - which is a good failure,
        # since a silently ignored field would have logged a quote for the wrong instrument.
        "underlying_symbol": symbol,
    }
    try:
        await ws.send(json.dumps(request))
        for _ in range(6):
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            if "error" in msg:
                base["error"] = str(msg["error"].get("code", "error"))[:40]
                return base
            if "proposal" in msg:
                p = msg["proposal"]
                payout = float(p.get("payout") or 0.0)
                base["payout"] = payout
                base["ask_price"] = p.get("ask_price", "")
                base["spot"] = p.get("spot", "")
                # The broker's implied probability for this side. **Not rounded.** The
                # quantity this whole exercise rests on is the skew between the two sides,
                # which is itself of order 0.001 to 0.01, so rounding to six places would
                # discard up to a percent of it for no reason - this is stored data, not a
                # display.
                base["implied"] = (STAKE / payout) if payout > 0 else ""
                return base
        base["error"] = "no_proposal"
    except TimeoutError:
        base["error"] = "timeout"
    except Exception as exc:  # a collector must outlive any single bad response
        base["error"] = type(exc).__name__[:40]
    return base


def cells() -> list[tuple[str, int]]:
    """Every (symbol, duration) this venue will actually quote.

    Computed rather than written out so `SYMBOLS` and `DURATIONS` stay the only two things to
    edit, and so `wanted()` below reports a denominator that means something - a sweep printing
    `48/80 quoted` when 32 of those 80 were never possible reads as a broken collector.
    """
    return [(sym, d) for sym, floor in SYMBOLS for d in DURATIONS if d >= floor]


def wanted() -> int:
    """How many rows a healthy sweep produces. Both directions on every cell."""
    return len(cells()) * 2


async def sweep(ws, write) -> int:
    """One pass over every quotable symbol and duration, both directions, same instant."""
    rows: list[dict] = []
    for symbol, minutes in cells():
        # CALL and PUT back to back, so the pair shares a quoting instant as closely as
        # the API allows. Their implied probabilities are what separate margin from skew.
        for contract in ("CALL", "PUT"):
            rows.append(await quote(ws, symbol, minutes, contract))
            await asyncio.sleep(REQUEST_PAUSE)
    write(rows)
    return sum(1 for r in rows if not r["error"])


async def run(out_dir: Path, sweeps: int | None) -> int:
    import websockets

    write = writer(out_dir)
    app_id = os.environ.get("DERIV_APP_ID", "1089")
    token = os.environ.get("DERIV_API_TOKEN", "")
    headers = {"Origin": "https://app.deriv.com"}
    done = 0
    stopping = False

    def stop(*_args):
        nonlocal stopping
        stopping = True

    with contextlib.suppress(ValueError):
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

    while not stopping and (sweeps is None or done < sweeps):
        connected = False
        for template in ENDPOINTS:
            url = template.format(app_id=app_id)
            try:
                async with websockets.connect(
                    url, open_timeout=20, additional_headers=headers
                ) as ws:
                    connected = True
                    host = url.split("//")[1].split("/")[0]
                    print(f"connected to {host}", flush=True)
                    if token:
                        # Only if a symbol turns out to need it; never logged.
                        await ws.send(json.dumps({"authorize": token}))
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(ws.recv(), timeout=15)
                    while not stopping and (sweeps is None or done < sweeps):
                        good = await sweep(ws, write)
                        done += 1
                        print(
                            f"{dt.datetime.now(dt.UTC):%H:%M:%S} sweep {done}: "
                            f"{good}/{wanted()} quoted",
                            flush=True,
                        )
                        if sweeps is not None and done >= sweeps:
                            break
                        await asyncio.sleep(SWEEP_SECONDS)
                break
            except Exception as exc:
                print(f"  {url.split('//')[1].split('/')[0]}: {type(exc).__name__}", flush=True)
        if not connected and not stopping:
            # The endpoint was down when this was written; record the attempt and wait.
            write(
                [
                    {
                        **dict.fromkeys(FIELDS, ""),
                        "ts": int(dt.datetime.now(dt.UTC).timestamp()),
                        "symbol": "-",
                        "duration_min": 0,
                        "contract": "-",
                        "error": "endpoint_unreachable",
                    }
                ]
            )
            print(f"  all endpoints refused; retrying in {BACKOFF}s", flush=True)
            await asyncio.sleep(BACKOFF)
            if sweeps is not None:
                done += 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.environ.get("OUT", "payouts"))
    ap.add_argument(
        "--sweeps",
        type=int,
        default=int(os.environ.get("SWEEPS", "0")) or None,
        help="stop after this many sweeps; omit to run until stopped",
    )
    args = ap.parse_args()
    try:
        import websockets  # noqa: F401
    except ImportError:
        print("websockets is not installed - pip install websockets", file=sys.stderr)
        return 1
    return asyncio.run(run(Path(args.out).expanduser(), args.sweeps))


if __name__ == "__main__":
    raise SystemExit(main())
