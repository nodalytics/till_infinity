"""Topic names. Strings, and nothing else.

**All that survived `bus.py`.** The bus is retired - Nautilus owns the message
bus - but the *names* are still the contract: `shared/contracts/bus/*.json` is
keyed on them, and a publisher and a subscriber have to agree on a string
whichever engine carries it.

Kept as a module of constants rather than an enum, because they are written
into JSON schema filenames and read by a Go service. A name that only Python
can spell is not a contract.
"""

from __future__ import annotations

# ──── prices ────
BARS = "prices.bars"
QUOTES = "prices.quotes"

# ──── news ────
ARTICLES = "news.articles"
EVENTS = "news.events"
MACRO = "news.macro"

# ──── the retired structures engine ────
#: Kept so a stored journal entry or a schema file still resolves. The engine
#: is in `research/retire/structures/`, and nothing publishes these now.
SIGNALS = "structures.signals"
RESOLUTIONS = "structures.resolutions"

# ──── statespace ────
DISPERSION = "statespace.dispersion"
STATESPACE_SIGNALS = "statespace.signals"
#: What the fold proposes, which `strategies` decides on. The one topic that
#: still carries a live trading path.
PROPOSALS = "statespace.proposals"

# ──── sinks ────
ALERTS = "alerts"
JOURNAL = "journal"

#: Every declared topic, for the contract tests. A schema file with no name
#: here, or a name here with no schema, is a mismatch worth failing on.
DECLARED: tuple[str, ...] = (
    BARS,
    QUOTES,
    ARTICLES,
    EVENTS,
    MACRO,
    SIGNALS,
    RESOLUTIONS,
    DISPERSION,
    STATESPACE_SIGNALS,
    PROPOSALS,
    ALERTS,
    JOURNAL,
)
