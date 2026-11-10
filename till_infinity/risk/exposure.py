"""What is actually at risk, as opposed to how many tickets are open.

`max_positions` counts positions. Long EURUSD, long GBPUSD and long AUDUSD is
**three positions and one trade**: all three are short dollars, they will be
right together and wrong together, and a limit that reads "3 of 4 used" has
authorised triple the risk it thinks it has.

So exposure is decomposed into the currencies behind it and limited there. The
decomposition is the only interesting part, and it is deliberately crude:

* a pair is long the base and short the quote - a long EURUSD is +EUR, -USD;
* gold and the crypto are treated as long the instrument, short USD, because
  that is what they are quoted as. XAUUSD rising and EURUSD rising share a
  dollar, and pretending gold is uncorrelated with the majors is how a book
  ends up all one way;
* an index is long the index and short USD for the same reason.

**Weighted by risk, not by lots.** A 0.01-lot gold position and a 1-lot EURUSD
position are not comparable in lots, in notional, or in anything except what
they lose if they are wrong. Every position here contributes the money it has
at risk, which is the number the limits are already written in.

What this does **not** do is estimate correlation from data. It is a structural
decomposition: EURUSD and GBPUSD share a dollar leg by construction, and that
is true regardless of what the last month's returns say. A measured
correlation matrix would be better on the day it was fitted and would need
refitting, monitoring, and a decision about what to do when it says gold and
the yen are now the same trade. This is the version that cannot go stale.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from ..domain.models import Intent, Position, Side


#: Base and quote per instrument. `USD` on the right for everything that is
#: quoted in dollars, which is all of them except the two dollar-first pairs.
def _slug(name: str) -> str:
    """`Volatility 75 Index` -> `volatility_75_index`, as the feed is keyed."""
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()


def _token(name: str) -> str:
    """`Volatility 75 Index` -> `VOLATILITY_75`, the instrument's own leg."""
    return _slug(name).removesuffix("_index").upper()


LEGS: dict[str, tuple[str, str]] = {
    # ---------------------------------------------------------------------
    # **The MT5 symbol names, added 2026-11-10 because the table had gone
    # stale at the migration and nobody noticed.** The keys below this block
    # are the retired service's feed names - `gold`, `btc`, `us100` - and the
    # live desk calls those feeds `xauusd`, `btcusd`, `us tech 100`. So
    # `legs()` returned `("", "")` for **22 of the 30 deployed symbols** and
    # `scaling.crowding` returned 1.0 for every one of them: a concentration
    # limit that could only see the eight USD majors.
    #
    # Found the day `statespace-surprise` opened eight positions on one bar
    # close, every one of them long USD, three of which (gold, BTC, ETH) this
    # table could not see at all.
    #
    # The convention is the one the index entries below already set: **the
    # instrument's own risk factor is the base and its settlement currency is
    # the quote.** The broker reports `currency_base` as the *settlement*
    # currency for an index or a crypto CFD - `BTCUSD` comes back
    # `base=USD` - which is true of the contract and false of the risk, so
    # the quote half is taken from the broker and the base half is the thing
    # being traded. Every quote currency here was read off
    # `/symbols/info/{symbol}` rather than assumed.
    "xauusd": ("XAU", "USD"),
    "xagusd": ("XAG", "USD"),
    "xptusd": ("XPT", "USD"),
    "xcuusd": ("XCU", "USD"),
    "us oil": ("WTI", "USD"),
    "uk brent oil": ("BRENT", "USD"),
    "btcusd": ("BTC", "USD"),
    "ethusd": ("ETH", "USD"),
    "bnbusd": ("BNB", "USD"),
    "solusd": ("SOL", "USD"),
    "wall street 30": ("WALLST30", "USD"),
    "us sp 500": ("SPX500", "USD"),
    "us tech 100": ("US100", "USD"),
    "us small cap 2000": ("US2000", "USD"),
    # The index entries that genuinely diversify a dollar book, for the reason
    # the older block below gives: a DAX CFD settles in euros and a FTSE CFD in
    # sterling, so mapping them to USD out of habit would make them count
    # against the one limit they do not load.
    "germany 40": ("GER40", "EUR"),
    "france 40": ("FRA40", "EUR"),
    "europe 50": ("EU50", "EUR"),
    "uk 100": ("UK100", "GBP"),
    "japan 225": ("JP225", "JPY"),
    "australia 200": ("AUS200", "AUD"),
    # **HKD is pegged to the dollar**, so this diversifies the currency code and
    # not the risk. Carried with its own code because that is what the broker
    # settles in, and flagged here because a reader counting distinct quote
    # currencies would otherwise score it as diversification.
    "hong kong 50": ("HK50", "HKD"),
    # The three crosses this desk trades that the table never had. The rest -
    # `euraud`, `eurgbp`, `eurjpy`, `eurchf`, `gbpjpy`, `audjpy`, `chfjpy` -
    # were already below and are not repeated here.
    "audcad": ("AUD", "CAD"),
    "audnzd": ("AUD", "NZD"),
    "eurcad": ("EUR", "CAD"),
    # ---------------------------------------------------------------------
    # The retired service's feed names, kept so an older config still resolves.
    "eurusd": ("EUR", "USD"),
    "gbpusd": ("GBP", "USD"),
    "audusd": ("AUD", "USD"),
    "nzdusd": ("NZD", "USD"),
    "usdjpy": ("USD", "JPY"),
    "usdcad": ("USD", "CAD"),
    "usdchf": ("USD", "CHF"),
    "usdcnh": ("USD", "CNH"),
    "gold": ("XAU", "USD"),
    "silver": ("XAG", "USD"),
    "btc": ("BTC", "USD"),
    "eth": ("ETH", "USD"),
    "sol": ("SOL", "USD"),
    "us100": ("US100", "USD"),
    "spx500": ("SPX500", "USD"),
    # The two that are **not** short dollars. A DAX CFD is quoted in euros and
    # a FTSE CFD in sterling, so they load EUR and GBP instead - which is why
    # they are worth carrying at all in a book where everything else shares a
    # dollar leg by construction. Mapping them to USD out of habit would have
    # made them count against the one limit they genuinely diversify.
    "ger40": ("GER40", "EUR"),
    "uk100": ("UK100", "GBP"),
    "fra40": ("FRA40", "EUR"),
    "eu50": ("EU50", "EUR"),
    "jp225": ("JP225", "JPY"),
    "aus200": ("AUS200", "AUD"),
    "hk50": ("HK50", "HKD"),
    # Dollar-quoted like the rest of the US book, so these add to the crowded
    # leg rather than diversifying it. Carried for liquidity, not for balance.
    "us30": ("US30", "USD"),
    "us2000": ("US2000", "USD"),
    "wti": ("WTI", "USD"),
    "brent": ("BRENT", "USD"),
    # The crosses, and the reason they are here. Every other instrument in this
    # table has the dollar on one side by construction, so the currency limit
    # binds on the dollar long before it binds on anything else. These are the
    # only positions that consume a different budget entirely - getting a leg
    # wrong here would quietly delete the one property they were added for.
    "eurgbp": ("EUR", "GBP"),
    "eurjpy": ("EUR", "JPY"),
    "gbpjpy": ("GBP", "JPY"),
    "eurchf": ("EUR", "CHF"),
    "audjpy": ("AUD", "JPY"),
    "chfjpy": ("CHF", "JPY"),
    "euraud": ("EUR", "AUD"),
}

#: What a calendar row's `country` means, in currency terms. The field carries
#: **both forms** - checked against the stored events rather than assumed:
#: TradingView writes ISO country codes (`US`, `JP`, `GB`, `DE`, `EU`, `CN`,
#: `CH`, `AU`, `CA`) and ForexFactory writes currency codes (`USD`, `GBP`,
#: `EUR`, `CNY`, `JPY`, `CAD`, `AUD`, `CHF`). Both appear in the same table.
COUNTRY_CURRENCY: dict[str, str] = {
    "US": "USD",
    "USA": "USD",
    "USD": "USD",
    "EU": "EUR",
    "EA": "EUR",
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "ES": "EUR",
    "NL": "EUR",
    "EUR": "EUR",
    "GB": "GBP",
    "UK": "GBP",
    "GBP": "GBP",
    "JP": "JPY",
    "JPY": "JPY",
    "AU": "AUD",
    "AUD": "AUD",
    "CA": "CAD",
    "CAD": "CAD",
    "CH": "CHF",
    "CHF": "CHF",
    "NZ": "NZD",
    "NZD": "NZD",
    "CN": "CNH",
    "CNY": "CNH",
    "CNH": "CNH",
}


def currency_of(country: str) -> str:
    """The currency a calendar row's country field means. "" if unknown."""
    return COUNTRY_CURRENCY.get(country.strip().upper(), "")


#: Synthetics settle in USD and have no underlying, so each gets its own base
#: token and a USD quote leg.
#:
#: A distinct token per instrument on purpose: `Volatility 75 Index` and
#: `Volatility 25 Index` are different generators with no relationship, and
#: giving them a shared base would net a long in one against a short in the
#: other as though they were the same risk. The USD leg is real, though - the
def register_broker_legs(feeds: Sequence[str], quote: str = "USD") -> None:
    """Give broker-only instruments an exposure leg.

    See `trading-exposure.md` in research/docs.
    """
    for feed in feeds:
        if feed and feed not in LEGS:
            LEGS[feed] = (feed.removesuffix("_index").upper(), quote)


def legs(feed: str) -> tuple[str, str]:
    """Base and quote for an instrument, or ("", "") if it is not mapped."""
    return LEGS.get(feed, ("", ""))


def leg_vector(book: Sequence[tuple[str, int]]) -> dict[str, float]:
    """Signed currency exposure for a set of `(feed, sign)` positions.

    A long of the base is long that currency and short the quote, so each
    position contributes `+sign` to its base and `-sign` to its quote. Feeds
    with no mapping contribute nothing and are not an error - `legs` returns
    `("", "")` for anything unmapped, and a test over the deployed symbol list
    is what keeps that set empty.

    Counted in positions and not in money, deliberately. The question this
    answers is "are these two rules making the same bet", and a money weighting
    would let one large position on a cheap instrument dominate the direction
    of a rule's whole book.
    """
    found: dict[str, float] = {}
    for feed, sign in book:
        base, quote = legs(feed)
        if base:
            found[base] = found.get(base, 0.0) + float(sign)
        if quote:
            found[quote] = found.get(quote, 0.0) - float(sign)
    return found


def agreement(first: dict[str, float], second: dict[str, float]) -> float:
    """Cosine similarity of two currency-exposure vectors, in [-1, 1].

    **Cosine and not Pearson**, because the question is whether two books point
    the same way and not whether they co-vary around their means. Subtracting a
    mean here would make two rules that are both long the dollar against
    everything look uncorrelated, which is the exact case worth catching: on
    2026-11-10 one rule opened eight positions and **every one was long USD**.

    Cosine also needs no history. `relationships-are-contemporaneous` records
    that on this desk the large relationships are contemporaneous and every
    lagged measure is null, so a rolling return correlation would be the weaker
    measure as well as the slower one - and `strategy-switching.md` measured a
    rule's own return record at **+0.009 over 737,691 trades**, which is what a
    short P&L window would mostly be made of.

    Zero when either side holds nothing, which reads as "no agreement" rather
    than as a division by zero.
    """
    shared = set(first) | set(second)
    if not shared:
        return 0.0
    dot = sum(first.get(name, 0.0) * second.get(name, 0.0) for name in shared)
    one = math.sqrt(sum(value * value for value in first.values()))
    two = math.sqrt(sum(value * value for value in second.values()))
    if one <= 0.0 or two <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (one * two)))


def feeds_for(currency: str) -> tuple[str, ...]:
    """Every instrument with this currency on either leg.

    A US release moves gold, BTC and all seven majors, because the dollar is on
    one side of every one of them. That is the correct answer and it is why the
    news blackout is not narrower.
    """
    want = currency.strip().upper()
    return tuple(feed for feed, (base, quote) in LEGS.items() if want in (base, quote))


@dataclass(frozen=True, slots=True)
class Exposure:
    """Money at risk per currency, signed. Positive is long that currency."""

    by_currency: dict[str, float]

    def of(self, currency: str) -> float:
        return self.by_currency.get(currency, 0.0)

    def gross(self) -> float:
        return sum(abs(value) for value in self.by_currency.values())

    def worst(self) -> tuple[str, float]:
        """The currency carrying the most one-way risk."""
        if not self.by_currency:
            return ("", 0.0)
        currency = max(self.by_currency, key=lambda k: abs(self.by_currency[k]))
        return (currency, self.by_currency[currency])

    def __str__(self) -> str:
        parts = sorted(self.by_currency.items(), key=lambda kv: -abs(kv[1]))
        return ", ".join(f"{c} {v:+.0f}" for c, v in parts if abs(v) > 0.005) or "flat"


def measure(
    positions: list[Position],
    risk_of: dict[int, float],
    feed_of: dict[str, str],
) -> Exposure:
    """Decompose open positions into signed currency risk.

    `risk_of` is money at risk per ticket and `feed_of` maps broker symbol back
    to instrument. Both are passed in rather than looked up because a
    `Position` carries neither - the broker does not know what we risked on it,
    and the symbol is the broker's name for the instrument, not ours.
    """
    totals: dict[str, float] = defaultdict(float)
    for position in positions:
        feed = feed_of.get(position.symbol, position.symbol.lower())
        base, quote = legs(feed)
        if not base:
            continue
        risk = abs(risk_of.get(position.ticket, 0.0))
        if risk <= 0:
            continue
        sign = position.side.sign
        totals[base] += sign * risk
        totals[quote] -= sign * risk
    return Exposure(dict(totals))


def would_be(exposure: Exposure, intent: Intent) -> Exposure:
    """The exposure after taking `intent`. Used to test a limit before trading."""
    base, quote = legs(intent.feed)
    if not base:
        return exposure
    totals = dict(exposure.by_currency)
    sign = 1 if intent.side is Side.BUY else -1
    risk = abs(intent.risk_money)
    totals[base] = totals.get(base, 0.0) + sign * risk
    totals[quote] = totals.get(quote, 0.0) - sign * risk
    return Exposure(totals)
