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

from collections import defaultdict
from dataclasses import dataclass

from .models import Intent, Position, Side

#: Base and quote per instrument. `USD` on the right for everything that is
#: quoted in dollars, which is all of them except the two dollar-first pairs.
LEGS: dict[str, tuple[str, str]] = {
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


def legs(feed: str) -> tuple[str, str]:
    """Base and quote for an instrument, or ("", "") if it is not mapped."""
    return LEGS.get(feed, ("", ""))


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
