"""Every declared topic has a schema, and the producers satisfy it.

`shared/contracts/bus/*.json` is the artefact a Go service reads to know what
is on the bus. **A schema nobody validates against is documentation**, and
documentation drifts into a description of what the bus used to carry - which
is the same failure `test_service_boundaries.py` guards against for imports.

So this file does three things:

* every topic in `bus.TOPICS` either has a schema or is named here as a gap,
  so a new topic cannot arrive undeclared;
* a payload built by the real producer validates against its schema, which is
  what makes the schema true rather than plausible;
* the two **debts** ADR 0004 names are listed by name, so removing them from
  the producer is a change that shows up here rather than being forgotten.
"""

from __future__ import annotations

import pytest

from till_infinity import bus as bus_module
from till_infinity.shared import contracts

#: Topics with no schema yet, and why.
#:
#: Every entry is a gap, not a permission - the same bargain as
#: `test_service_boundaries.py`'s `DEBTS`: the list can only shrink, and a
#: stale entry is a failure too.
UNDECLARED: dict[str, str] = {
    "structures.signals": "the structures service is being retired; see docs/specs",
    "structures.resolutions": "retiring with structures",
    "statespace.signals": "producer switched off 2026-10-28 when its only consumer retired",
    "news.articles": "news internals, no cross-language consumer yet",
    "news.events": "wanted, not yet written",
    "news.macro": "news internals, no cross-language consumer yet",
}

#: Fields a producer still publishes that ADR 0004 says it must not: risk
#: **decisions** rather than measurements. Named so that removing one from
#: `proposing.py` fails here and the schema gets tightened in the same change.
RISK_DEBTS: dict[str, tuple[str, ...]] = {
    "statespace.proposals": ("stop_vol", "target_r"),
}


def test_every_topic_is_declared_or_named_as_a_gap():
    """A new topic cannot arrive without a schema or an entry saying why not."""
    known = set(contracts.declared()) | set(UNDECLARED)
    missing = sorted(set(bus_module.TOPICS) - known)
    assert not missing, (
        f"{', '.join(missing)} on the bus with no schema and no entry in UNDECLARED. "
        "Write the schema, or record the gap with its reason."
    )


def test_a_paid_gap_is_deleted():
    """A topic that has gained a schema must leave `UNDECLARED`.

    Without this the list stops describing anything, which is exactly how the
    coupling lists this repository keeps rot.
    """
    stale = sorted(set(UNDECLARED) & set(contracts.declared()))
    assert not stale, f"{', '.join(stale)} now has a schema - delete it from UNDECLARED."


@pytest.mark.parametrize("topic", contracts.declared())
def test_the_schema_names_the_topic_it_is_filed_under(topic):
    """`$id` and the file name are checked against each other, because a
    renamed file with a stale `$id` would load and validate the wrong thing."""
    assert contracts.schema_for(topic)["$id"] == topic


def test_a_real_bar_notice_satisfies_its_schema():
    """Built by `prices.service._notice`, not by hand - a schema validated
    against a payload written in the test is a schema that agrees with the
    test."""
    import time

    from till_infinity.prices.models import Bar, SeriesKey, Symbol, WriteResult
    from till_infinity.prices.service import _notice

    key = SeriesKey(
        source="broker",
        feed="eurusd",
        symbol=Symbol(venue="deriv", ticker="EURUSD"),
        interval="5m",
    )
    bar = Bar(
        time=time.time() - 600,
        open=1.085,
        high=1.0855,
        low=1.0845,
        close=1.0851,
        volume=120.0,
    )
    # `touched` is derived from inserted + updated, not passed.
    contracts.check("prices.bars", _notice(key, bar, WriteResult(inserted=1, updated=0)))


def test_a_real_quote_notice_satisfies_its_schema():
    from till_infinity.prices.models import Quote, QuoteKey, Symbol
    from till_infinity.prices.quotes import announce_quote

    key = QuoteKey(source="broker", feed="eurusd", symbol=Symbol(venue="deriv", ticker="EURUSD"))
    quote = Quote(bid=1.08500, ask=1.08505, time=1767323045.0)
    contracts.check("prices.quotes", announce_quote(key, quote))


def test_the_proposal_debts_are_still_there_and_still_named():
    """**ADR 0004: a proposal carries measurements, not decisions.**

    `stop_vol` and `target_r` are risk decisions and `proposing.py` still
    publishes them; `strategies/dispersing.py` already holds its own, so they
    are duplication waiting to diverge. The schema documents them as debts and
    this asserts they are exactly the two known ones - so a *third* cannot be
    added quietly, and removing one fails here until the schema is tightened
    with it.
    """
    schema = contracts.schema_for("statespace.proposals")
    features = schema["properties"]["features"]
    declared_debts = tuple(
        name
        for name, spec in features["properties"].items()
        if str(spec.get("description", "")).startswith("DEBT")
    )
    assert declared_debts == RISK_DEBTS["statespace.proposals"], (
        f"the schema's debts are {declared_debts}, the test expects "
        f"{RISK_DEBTS['statespace.proposals']} - if a producer stopped sending one, "
        "remove it from the schema's required list and from RISK_DEBTS together"
    )
    for name in declared_debts:
        assert name in features["required"], (
            f"{name} is marked a debt but is optional - a debt that is already "
            "optional is paid, and should be removed rather than described"
        )


def test_a_real_journal_entry_satisfies_its_schema():
    """Built by the real `to_message`, which is `Entry.to_dict` - so the wire
    format and the record's own format are the same thing, and `id` travels
    even though the reader recomputes it."""
    from till_infinity.journal.bus import from_message, to_message
    from till_infinity.journal.models import Entry, Kind

    entry = Entry(
        title="paper: buy 0.05 eurusd @ 1.08505",
        kind=Kind.DECISION,
        actor="trading",
        rationale="a 4.2 sigma bar",
        context={"strategy": "statespace-surprise", "risk_money": 25.0},
        tags=("eurusd", "statespace-surprise"),
        confidence=0.3,
    )
    payload = to_message(entry)
    contracts.check("journal", payload)

    # And the id really is recomputed rather than honoured, which is the one
    # property of this topic a consumer must not get wrong.
    claimed = dict(payload, id="not-the-real-id")
    rebuilt = from_message(claimed)
    assert rebuilt is not None
    assert rebuilt.id == entry.id, "a sender must not be able to claim an id"


def test_a_real_trading_alert_satisfies_its_schema():
    """The shape `Trader._shout_state` publishes - title, body, level - which is
    the minimum an alert can be."""
    contracts.check(
        "alerts",
        {
            "title": "paper: autotrading is off",
            "body": "the terminal will refuse every order with 10027",
            "level": "warning",
        },
    )


def test_a_real_structures_alert_satisfies_its_schema():
    """The other producer on this topic, until it retires. Two producers on one
    topic is the case a schema is most worth having: if their shapes had
    drifted, this is where it would show."""
    from till_infinity.structures.models import Shape, Signal
    from till_infinity.structures.service import alert_payload

    signal = Signal(
        feed="eurusd",
        venue="deriv",
        interval="5m",
        shape=Shape.LEVEL,
        direction="up",
        score=0.25,
        detail="up from above at 1.0850",
    )
    contracts.check("alerts", alert_payload(signal))


def test_an_alert_with_no_title_is_refused_by_the_schema_as_well_as_the_consumer():
    """`from_message` drops it with a warning; the schema says so too, so a
    producer finds out in a test rather than by an alert never arriving."""
    import jsonschema

    from till_infinity.notifications.service import from_message

    assert from_message({"body": "no title"}) is None
    with pytest.raises(jsonschema.ValidationError):
        contracts.check("alerts", {"body": "no title"})
