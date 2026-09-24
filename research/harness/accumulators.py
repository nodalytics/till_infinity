"""Is Deriv's accumulator a bet this desk can win, and can `chi` time it?

    python research/harness/accumulators.py

## The hypothesis, and why it was worth asking

An accumulator pays for the market being **quiet**, not for it going a particular way. That is the
one shape this desk's research fits: `crash-timing.md`'s big-move score reaches AUC 0.65-0.81,
`news-volatility.md` measures 2.4x normal volatility on a release bar, and `implied.md` is the only
positive result in the folder - all of them about *size*. Nothing here predicts direction, and
`directional-questions.md` spent a 92-view ensemble establishing that.

More specifically, `susceptibility.md` found that a loud Ising susceptibility `chi = var(M)` is
followed by volatility **falling**, +5 to +9 points on five of seven instruments, and the lift
survived a control within deciles of trailing volatility. A forecast that volatility will fall,
pointed at an instrument that pays for volatility being low, is a real pairing rather than an
analogy.

## What the contract actually is, which is not what it sounds like

    "After the entry spot tick, your stake will grow continuously by 3% for every tick that the
     spot price remains within the +- 0.05369% from the previous spot price."

**From the previous spot price, not from the entry.** So it is not a range bet over a window; it is
a bet that **no single tick jumps** more than a fixed fraction. That matters for the hypothesis: the
quantity to forecast is per-tick volatility, not the width of an excursion, and `chi` is computed
from bar returns over a window. They are related through volatility clustering but they are not the
same thing, and the distinction is the difference between testing the hypothesis and testing
something adjacent to it.

Deriv labels the contract `sentiment: "low_vol"`, which agrees.

## The break-even condition is exact, which is unusual and useful

Stake grows by `g` per surviving tick and a breach ends the contract at zero. Exit after `n`
surviving ticks and the payout is `stake * (1+g)^n`, so with per-tick survival probability `p`:

    E[payout] = p**n * stake * (1+g)**n      ->     break-even at   p * (1+g) = 1

    p_fair = 1 / (1+g)

**Independent of `n` and of the exit rule.** There is no optimal holding period to find and no
take-profit level to tune: either the per-tick survival probability exceeds `1/(1+g)` or the
contract loses, and how you manage it cannot change that. It is the cleanest fair-value condition
of any instrument this repository has looked at.

So the whole question is one number, and it is measured two independent ways below.

## Two estimators, because each can be wrong on its own

**1. Analytic, from the barrier and the index's own sigma.** A Volatility index is GBM at the sigma
its name states - `deriving.md` and `twins.md` confirm it to within two standard errors - so with
`b` the barrier as a fraction and `s` the per-tick standard deviation:

    p = 2 * Phi(b / s) - 1

This needs no data from Deriv beyond the barrier it quotes, which is why it is the primary estimate.

**2. From Deriv's own `ticks_stayed_in`**, a published history of how long recent contracts lasted.
Two corrections matter:

* **Censoring.** Contracts are capped at `maximum_ticks`, so the naive `E[n] = p/(1-p)` understates
  `p` - which would bias the answer toward "unfavourable", the direction this study is looking for,
  and is therefore exactly the bias to remove. The right estimator treats a value at the cap as
  right-censored and is a one-liner: with `S` total surviving ticks and `B` breaches,
  `p_hat = S / (S + B)`.
* **Voluntary exits.** If that history includes contracts closed early by a trader taking profit,
  it understates survival by an unknown amount. Deriv does not document which, so this estimator is
  reported as corroboration and never alone.

## What would have to be true for `chi` to rescue it

The bar is stated before the measurement, because a bar chosen afterwards is not a bar. If the
analytic `p` falls short of `p_fair`, the volatility reduction needed to close the gap is

    x_fair = Phi_inverse((1 + p_fair) / 2)          the barrier in sigmas that would break even
    needed = 1 - (b / x_fair) / s                   the fractional fall in sigma required

If that number is small, the hypothesis is live and worth a tick-level study. If it is large, it is
not, and no amount of signal engineering changes it.
"""

from __future__ import annotations

import asyncio
import json
import math
import statistics

import httpx
from httpx_ws import aconnect_ws

URL = "wss://api.derivws.com/trading/v1/options/ws/public"

#: The growth rates Deriv offers. Each carries its own barrier and tick cap.
RATES = (0.01, 0.02, 0.03, 0.04, 0.05)

#: Seconds between ticks. The `R_*` family ticks every two seconds and the `1HZ*` family every
#: second, which is what the "(1s)" in their display names means. Verified below against
#: `last_tick_epoch` rather than trusted, because the whole analytic estimate scales with it.
TICK_SECONDS = {"R_": 2.0, "1HZ": 1.0}

#: Seconds in a year for these generators. They run continuously - no weekends, no sessions - so
#: this is a plain calendar year rather than a trading one. Using 252 trading days here would
#: overstate per-tick sigma by about 1.9x and invert the conclusion.
YEAR_SECONDS = 365.0 * 24.0 * 3600.0


def phi(x: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def phi_inverse(p: float) -> float:
    """Standard normal quantile, by bisection. Good to 1e-12 and needs no dependency."""
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if phi(mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def tick_seconds(symbol: str) -> float:
    for prefix, seconds in TICK_SECONDS.items():
        if symbol.startswith(prefix):
            return seconds
    return 2.0


def sigma_annual(symbol: str) -> float:
    """The sigma the index's name states, as a fraction. `R_100` is 100%."""
    digits = "".join(c for c in symbol if c.isdigit())
    return float(digits) / 100.0 if digits else 0.0


def survival_mle(stayed: list[int], cap: int) -> tuple[float, int]:
    """Per-tick survival from a censored survival history.

    A value at `cap` is a contract that ran out of contract rather than breaching, so it
    contributes surviving ticks and no breach. Returns `(p_hat, breaches)`.
    """
    total = sum(stayed)
    breaches = sum(1 for n in stayed if n < cap)
    if total + breaches == 0:
        return (0.0, 0)
    return (total / (total + breaches), breaches)


async def ask(ws, request: dict, timeout: float = 20.0) -> dict:
    await ws.send_text(json.dumps(request))
    try:
        return json.loads(await asyncio.wait_for(ws.receive_text(), timeout=timeout))
    except TimeoutError:
        return {"error": {"code": "timeout"}}


async def menu(ws, symbol: str) -> set[str]:
    reply = await ask(ws, {"contracts_for": symbol})
    available = (reply.get("contracts_for") or {}).get("available") or []
    return {row.get("contract_type") for row in available}


async def main() -> int:
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0", retries=3)
    async with (
        httpx.AsyncClient(transport=transport, timeout=40.0) as client,
        aconnect_ws(URL, client=client) as ws,
    ):
        listing = await ask(ws, {"active_symbols": "brief"})
        symbols = [row["underlying_symbol"] for row in (listing.get("active_symbols") or [])]

        print("=== which instruments sell an accumulator at all")
        offers: list[str] = []
        for symbol in symbols:
            kinds = await menu(ws, symbol)
            if "ACCU" in kinds:
                offers.append(symbol)
        synthetic = [s for s in offers if not s.startswith(("frx", "cry"))]
        real = [s for s in offers if s.startswith(("frx", "cry"))]
        print(f"  {len(offers)} of {len(symbols)} instruments offer ACCU")
        print(f"  synthetic: {synthetic}")
        print(f"  real:      {real or 'NONE'}")

        print("\n=== fair value, two ways")
        print(
            f"{'symbol':8s} {'g':>5s} {'bar%':>8s} {'sig/tick%':>10s} {'p_ana':>8s} "
            f"{'p_mle':>8s} {'p_fair':>8s} {'edge_ana':>9s} {'vol fall needed':>16s}"
        )
        print("-" * 92)
        rows = []
        for symbol in [s for s in ("R_10", "R_25", "R_50", "R_75", "R_100") if s in offers]:
            annual = sigma_annual(symbol)
            per_tick = annual * math.sqrt(tick_seconds(symbol) / YEAR_SECONDS)
            for rate in RATES:
                reply = await ask(
                    ws,
                    {
                        "proposal": 1,
                        "amount": 10,
                        "basis": "stake",
                        "contract_type": "ACCU",
                        "currency": "USD",
                        "underlying_symbol": symbol,
                        "growth_rate": rate,
                    },
                )
                proposal = reply.get("proposal")
                if not proposal:
                    print(f"{symbol:8s} {rate:5.2f}  {reply.get('error', {})}")
                    continue
                detail = proposal.get("contract_details", {})
                barrier = float(str(detail.get("tick_size_barrier_percentage", "0")).rstrip("%"))
                cap = int(detail.get("maximum_ticks") or 0)
                stayed = [int(x) for x in (detail.get("ticks_stayed_in") or [])]

                b = barrier / 100.0
                p_analytic = 2.0 * phi(b / per_tick) - 1.0
                p_fair = 1.0 / (1.0 + rate)
                p_mle, _breaches = survival_mle(stayed, cap) if stayed else (float("nan"), 0)

                x_fair = phi_inverse((1.0 + p_fair) / 2.0)
                needed = 1.0 - (b / x_fair) / per_tick

                rows.append((symbol, rate, p_analytic, p_mle, p_fair, needed))
                print(
                    f"{symbol:8s} {rate:5.2f} {barrier:8.5f} {100 * per_tick:10.5f} "
                    f"{p_analytic:8.5f} {p_mle:8.5f} {p_fair:8.5f} "
                    f"{p_analytic - p_fair:+9.5f} {100 * needed:15.2f}%"
                )

        if rows:
            edges = [p_a - p_f for _s, _g, p_a, _m, p_f, _n in rows]
            needs = [n for *_rest, n in rows]
            favourable = sum(1 for e in edges if e > 0)
            print(
                f"\n  {favourable} of {len(rows)} cells favourable "
                f"(analytic edge {min(edges):+.5f} to {max(edges):+.5f})"
            )
            print(
                f"  volatility fall needed to break even: "
                f"{100 * min(needs):.2f}% to {100 * max(needs):.2f}%, "
                f"median {100 * statistics.median(needs):.2f}%"
            )
            print(
                "\n  The two estimators are independent: the analytic one uses only the"
                "\n  barrier Deriv quotes and the sigma its own name states; the MLE uses"
                "\n  only its published survival history. They should agree, and where they"
                "\n  do the answer is not an artefact of either."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
