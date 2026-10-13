# The maker fee is zero, and the absorption edge still cannot be made

`statespace-absorption-delay.md` closed the directional line on cost and named
exactly one open number:

> Absorption pays the side that **absorbs**, which is a resting order rather
> than a crossing one. A maker is not paying the 1 to 5 basis points, it is
> **earning** them... unknown is now the single number standing between this
> result and a different answer.

The number is now known, and the answer is still no - for a reason that is
structural rather than numerical, which is a better place to stop.

## Polymarket's maker fee is zero, from its own documentation

Not inferred from a trade. Polymarket's fee page states **"Makers are never
charged fees"**, and the schedule carries a maker rate of `0` in every category
against taker rates of 0.04 to 0.07, applied as

    fee = C * rate * p * (1 - p)

so the fee peaks at a price of 50 cents and is symmetric around it. Makers are
also **paid**: a rebate programme redistributes 15 to 25 per cent of collected
taker fees to market makers daily, by category. Geopolitical markets are
fee-free on both sides.

This replaces the figure this desk had recorded as unknown. It also sharpens
what was already measured: the taker fee is **3.5 per cent** measured twice
on-chain, against a schedule of 4 to 7 per cent of `p(1-p)`, which at a 50-cent
price is 1 to 1.75 per cent of notional - so the measured 3.5 per cent was a
round trip plus slippage rather than the posted rate.

## And it does not unlock the absorption edge, because of where that edge is

The absorption signal was measured on **MT5 bars** - FX majors, metals, crude -
and the venue those come from is a **dealer**. There is no maker side to take:
a retail account cannot post a resting order that another participant fills. It
crosses the dealer's spread in both directions, which is exactly the 1 to 5
basis points the delay sweep charged it.

Polymarket has a genuine central limit order book and a zero maker fee, and has
no FX pairs, no metals and no crude. It has event contracts.

So the two halves do not meet:

| | the venue with the signal | the venue with the maker side |
| --- | --- | --- |
| instrument | FX, metals, crude | event contracts |
| market structure | dealer, cross the spread | CLOB, rest an order |
| maker fee | no maker side exists | **0, plus a rebate** |
| absorption measured? | **yes**, 8 of 8 | not measured |

**The blocker was never the fee.** It is that the measured mechanism and the
fee structure that would pay for it are at different venues, and nothing about
the fee schedule changes that.

## What this leaves, stated precisely so it is not re-opened

Two things would change the answer, and neither is a signal problem.

**Measure absorption on a CLOB venue.** The statistic needs only OHLCV, so any
venue with bars and a resting-order book can be tested - and the fingerprint in
`behaving.TRAITS` says what to expect, since every traded class absorbs and the
sign is what separates a book from a generator. If absorption holds on an
instrument that can be made, the arithmetic is a zero fee against a 0.2 basis
point edge plus a rebate, which is a different calculation entirely.

**Or test whether Polymarket's own contracts absorb.** They have the book and
the zero fee already. This desk has prior there and it is discouraging - the
up-and-down edge was measured at -98 per cent on good fills, and an hourly
window priced off the wrong feed - but **absorption was never the thing that was
tested**, and a prediction market's book has market makers in it like any other.

The second is cheaper and the venue is already connected. It is also the one
where a negative result is most informative, because a CLOB with zero maker
fees and no absorption would say the mechanism needs a dealer's inventory rather
than merely a book.
