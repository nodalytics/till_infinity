# Monetary policy: a feature, a model, and a differential that means something

`news/fred.py` collected thirteen series of central-bank policy for weeks and
nothing read them - 2,174 rows in the store, zero consumers. Collection without
consumption is a cost with no benefit that looks like progress from the
outside, which is the failure this note is about as much as the data is.

`structures/macro.py` is the consumer, and it is two things deliberately.

## The cheap half: features on a signal that already exists

Every level call carries a float dictionary of the conditions it was found in.
A rate differential belongs there: it costs nothing, it decides nothing, and it
lands in the journal beside the outcome - so "does the carry gap predict which
way a level breaks" becomes a query rather than a rebuild.

| feature | what it is |
| --- | --- |
| `macro_carry_gap` | base rate minus quote rate, percentage points |
| `macro_carry_gap_change` | how that gap moved over 90 days |
| `macro_curve_gap` | base (10y − overnight) minus the quote's |
| `macro_liquidity_gap` | base balance-sheet change minus the quote's, relative |
| `macro_liquidity` | the quote's balance sheet, for an instrument with no carry |
| `macro_us_real_yield`, `_change` | `DFII10` - the discount rate the whole book is priced against |
| `macro_us_breakeven`, `_change` | `T10YIE` - inflation the market is pricing, daily |
| `macro_us_curve` | `DGS10 − DGS2` |

An absent series leaves its key out rather than writing a zero. A zero here is
indistinguishable from a rate of zero, and the yen would read as the flattest
curve in the book.

## The expensive half: policy as its own shape

`Shape.MACRO`, emitted by `Macro.calls()`. Two rules, and both require the level
and the change to **agree**:

* a currency pair follows the carry - the base is favoured when it pays more
  *and* the gap is widening;
* a dollar-quoted asset with no carry of its own (gold, the crypto, the
  indices) follows the discount rate - up when the US real yield is falling and
  the balance sheet is expanding.

Disagreement is silence, and that is the design rather than a gap in it. A gap
that has been wide for a year is priced; what is not priced is the change. The
signal fires on a **stance change** and stays quiet in between, so a feed
already announced in one direction says nothing until it flips.

Scored against its own history: the size of the move divided by the median
90-day move in that series. Scale-free, because half a point is enormous for
the yen and ordinary for sterling, and a threshold in percentage points would
be right for one of them.

## Why the differential is built out of families

A differential is only meaningful when both legs are the **same measurement**.
An overnight policy rate for one currency against a ten-year yield for another
moves with the shape of one curve rather than with the gap between two
countries, and it will look like signal because it moves.

So the cross-country rates come from two OECD families - `IRSTCI01xx`
(overnight) and `IRLTLT01xx` (ten-year) - which are one definition with the
country swapped. Verified against the live API rather than assumed:

| family | US | EUR (DE) | GBP | JPY | CAD | AUD | CHF | NZD |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| overnight | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | – | – |
| ten-year | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| daily policy | `DFF` | `ECBDFR` | `IUDSOIA` | – | – | – | – | – |

The OECD families are monthly and about two months behind - on 2026-08-30 the
newest observation was 2026-06-01. That is what a comparable cross-country rate
costs. The daily policy rates are the fast read where one exists, and are used
for the **level** only: the trend always comes from the monthly family, so a
trend never compares a daily series against a monthly one.

Germany stands in for the euro area. The euro-area aggregates exist and stop in
January 2026, which is worse than a proxy that is current.

## What it does not claim

Nothing here is fast. The best of these series moves once a day and most move
once a month, so a macro call is context for a trade rather than a trade. It is
published, journalled and scored so the outcome machinery can say whether it is
worth anything, which is the only thing that can settle it.

`trading` ignores `Shape.MACRO` - `context.py` acts on `drift` and `spread` and
nothing else - so this changes no behaviour until something is written to read
it. That is the intended first state.
