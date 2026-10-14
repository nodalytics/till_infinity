"""Does the venue sell options on the synthetics that have a designed drift?

This is the re-check `payout_logger.py` asks for in its own docstring, and it
decides a whole line of work.

`payouts` now carries 40 live quotes and they say one thing very clearly: the
implied probability is **0.5120** on every volatility index from `R_10` to
`R_100` and at every duration from 1 to 60 minutes, range 0.5099 to 0.5141. A
flat 1.20 percentage point margin, independent of volatility and of duration.

**That is correct pricing, and it closes those symbols provably.** For a
driftless geometric Brownian motion the probability that the close exceeds the
entry is exactly 0.5 whatever sigma and whatever the horizon, so a rise/fall
has no volatility structure to misprice. `research/generators.md` and
`derivegbm.py` validated those indices as exactly that - H 0.50, kurtosis 3.00,
variance ratios 1.000, no clustering, on 86,411 bars. So the fair price is 0.5,
the venue charges 0.5120, and expectancy is **exactly minus 1.2 points per
trade for every entry rule, filter, duration and sizing scheme** - which is
`deriving.md`'s result that a predictable position on a martingale earns
`-(c/2) x turnover` and nothing else.

**The only synthetics where a directional edge exists by construction are the
ones with a designed asymmetry**: Boom and Crash spike one way and grind the
other, which `susceptibility.md` recovered at `+0.136` and `-0.136` through
realised semivariance, and `Drift_Switch` has a planted drift regime that this
desk's own gate detects. On 2026-09-24 the venue quoted **none** of them.

So: list what the venue will actually sell, and try a proposal on every
asymmetric family. Two outcomes, both worth having.

* **It quotes them.** Then the binary line opens on instruments whose generator
  has a drift that is published rather than hoped for, and the hurdle is a
  known 1.2 points.
* **It does not.** Then the line is closed for a **structural** reason - the
  venue sells the option only where the option is worthless to the buyer - and
  that is a far more useful thing to know than another null.

**Sends `proposal` and `active_symbols` only. There is no `buy` in this file
and no token is read**, so nothing here can touch an account.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ENDPOINT = os.environ.get(
    "DERIV_WS", "wss://api.derivws.com/trading/v1/options/ws/public"
)
FALLBACK = "wss://ws.derivws.com/websockets/v3?app_id={app_id}"
APP_ID = os.environ.get("DERIV_APP_ID", "1089")
#: Durations to try, in minutes. A refusal at every one is the finding.
DURATIONS = (1, 5, 15, 60)
#: Families whose generator has a designed asymmetry, by the words that appear
#: in the venue's own symbol names and display names.
ASYMMETRIC = ("boom", "crash", "dex", "drift", "jump", "range break", "rangebreak")


async def ask(ws, payload: dict) -> dict:
    await ws.send(json.dumps(payload))
    for _ in range(40):
        got = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
        if "error" in got:
            return got
        if set(payload) & set(got):
            return got
    return {"error": {"message": "no matching reply"}}


async def main() -> None:
    import websockets

    for url in (ENDPOINT, FALLBACK.format(app_id=APP_ID)):
        try:
            async with websockets.connect(url, open_timeout=20) as ws:
                print(f"connected to {url}\n")
                got = await ask(ws, {"active_symbols": "brief"})
                if "error" in got:
                    got = await ask(ws, {"active_symbols": "full"})
                if "error" in got:
                    print(f"  active_symbols refused: {got['error'].get('message')}")
                    continue
                symbols = got.get("active_symbols", [])
                print(f"{len(symbols)} symbols offered")
                asym = [
                    s
                    for s in symbols
                    if any(
                        word in (s.get("display_name", "") + s.get("symbol", "")).lower()
                        for word in ASYMMETRIC
                    )
                ]
                print(f"of which asymmetric families: {len(asym)}")
                for s in asym:
                    print(f"  {s.get('symbol', '?'):<18}{s.get('display_name', '?')}")
                if not asym:
                    print(
                        "\n**The venue does not list a single asymmetric synthetic.**\n"
                        "That is the structural answer: the only generators with a\n"
                        "directional edge by construction are not on the option menu."
                    )
                print()
                for s in asym:
                    code = s.get("symbol")
                    for minutes in DURATIONS:
                        reply = await ask(
                            ws,
                            {
                                "proposal": 1,
                                "amount": 10.0,
                                "basis": "stake",
                                "contract_type": "CALL",
                                "currency": "USD",
                                "duration": minutes,
                                "duration_unit": "m",
                                "symbol": code,
                            },
                        )
                        if "error" in reply:
                            print(
                                f"  {code:<18}{minutes:>4}m  refused: "
                                f"{reply['error'].get('code', '?')}"
                            )
                            continue
                        p = reply.get("proposal", {})
                        payout, ask_price = float(p.get("payout", 0)), float(
                            p.get("ask_price", 0)
                        )
                        implied = ask_price / payout if payout else float("nan")
                        print(
                            f"  {code:<18}{minutes:>4}m  payout {payout:>8.2f} "
                            f"ask {ask_price:>6.2f}  implied {implied:.4f}  "
                            f"margin {100 * (implied - 0.5):+.2f}pp"
                        )
                return
        except Exception as exc:  # noqa: BLE001 - every failure is a row
            print(f"{url}: {type(exc).__name__}: {exc}")
    print("no endpoint answered")


if __name__ == "__main__":
    asyncio.run(main())
