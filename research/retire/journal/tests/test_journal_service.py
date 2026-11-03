"""The journal's service helpers and its `Carrier` transport, as they were.

Split out of `tests/test_journal.py` on 2026-11-01 when `service.py` and
`bus.py` retired. What stayed in the suite is everything about the store and
the entry; what is here is everything whose subject is one of the two retired
modules - `decide`, `observe`, `outcome`, `note`, `record`, `open_journal`,
`publish`, `listen`, `to_message` and `from_message`.

**These imports no longer resolve**, which is the same state
`research/retire/structures/tests/` is in: the modules beside this file are not
on the import graph, because a retired service that still sits on it is not
retired. They are kept so the claim "it worked when it was removed" stays
readable, and because three of them record a guarantee that had to be
*re-earned* somewhere else rather than simply dropped:

| was here | is now |
|---|---|
| `test_a_broken_journal_costs_the_record_not_the_caller` | `test_journal_actor.py::test_a_write_failure_does_not_take_the_desk_down` |
| `test_an_outcome_with_no_parent_is_refused` | the same name in `test_journal_actor.py`, now enforced by the writer |
| the two tag-inheritance tests | the same names in `test_journal_actor.py`, plus one for a parent still in the batch |

`test_journalling_off_is_a_no_op_not_a_crash` has **no** successor and needs
none: journalling is switched off by not adding the actor, so there is no
`None` to branch on.
"""

from __future__ import annotations

import pytest

from till_infinity import journal as jr
from till_infinity.journal import Entry, Journal, Kind


@pytest.fixture
async def book(tmp_path):
    async with Journal(tmp_path / "journal.db") as journal:
        yield journal


# ------------------------------------------------------------- the helpers


async def test_a_decision_keeps_its_reasoning(book):
    ref = await jr.decide(
        book,
        "Alerted on OANDA gold spread",
        rationale="30bps against a 0.3bps 24h average, nothing on the calendar",
        actor="agents/risk",
        context={"venue": "OANDA", "spread_bps": 30.0, "avg_bps": 0.3},
        tags=("gold", "OANDA"),
        confidence=0.9,
    )
    entry = jr.get(book.path, ref)
    assert entry.rationale.startswith("30bps against")
    assert entry.context["spread_bps"] == 30.0
    assert entry.tags == ("gold", "OANDA")
    assert entry.confidence == 0.9
    assert entry.kind is Kind.DECISION


async def test_context_is_copied_in_not_referenced(book):
    """The stores move on; an entry must still describe the world it decided in.

    `decide` did the copying. That is now `Entry.__post_init__`, which is where
    it belonged: two of the three ways to build an entry copied and the third
    did not, and the third is the one a test uses.
    """
    state = {"spread_bps": 30.0}
    ref = await jr.decide(book, "d", rationale="r", context=state)
    state["spread_bps"] = 0.3  # the market moved, and the caller's dict with it
    assert jr.get(book.path, ref).context["spread_bps"] == 30.0


async def test_an_outcome_pairs_with_its_decision(book):
    ref = await jr.decide(book, "Alerted on gold", rationale="wide", tags=("gold",))
    await jr.outcome(book, ref, "Spread normalised in 4 minutes", context={"spread_bps": 0.31})

    followed = jr.read(book.path, parent=ref)
    assert len(followed) == 1
    assert followed[0].kind is Kind.OUTCOME
    assert followed[0].context["spread_bps"] == 0.31


async def test_an_outcome_with_no_parent_is_refused(book):
    """It could never be paired, so it is not a training example - just noise."""
    assert await jr.outcome(book, "", "something happened") == ""
    assert jr.read(book.path) == []


async def test_an_observation_is_kept_as_a_negative_example(book):
    await jr.observe(book, "Looked at a wide spread and did not alert", rationale="stale feed")
    assert jr.read(book.path, kind=Kind.OBSERVATION)[0].kind is Kind.OBSERVATION


async def test_an_outcome_inherits_its_decision_tags(book):
    """Otherwise a tag filter hides the entry saying the thing resolved itself."""
    ref = await jr.decide(book, "Alerted on gold", rationale="wide", tags=("gold", "OANDA"))
    await jr.outcome(book, ref, "Normalised in 4 minutes")

    tagged = jr.read(book.path, tag="gold")
    assert [str(e.kind) for e in tagged] == ["outcome", "decision"]


async def test_explicit_outcome_tags_win(book):
    ref = await jr.decide(book, "Alerted on gold", rationale="wide", tags=("gold",))
    await jr.outcome(book, ref, "Normalised", tags=("btc",))
    assert jr.read(book.path, tag="gold")[0].kind is Kind.DECISION
    assert jr.read(book.path, tag="btc")[0].kind is Kind.OUTCOME


# ------------------------------------------------------------ the resilience


async def test_journalling_off_is_a_no_op_not_a_crash():
    """Every helper takes None, so a caller never branches on whether it is on."""
    assert await jr.decide(None, "d", rationale="r") == ""
    assert await jr.observe(None, "o") == ""
    assert await jr.outcome(None, "parent", "o") == ""
    assert await jr.note(None, "n") == ""


async def test_a_broken_journal_costs_the_record_not_the_caller(tmp_path):
    """A full disk should lose you the entry, not the collector writing it."""
    broken = Journal(tmp_path / "j.db")  # never opened

    assert await jr.decide(broken, "d", rationale="r") == ""


def test_open_journal_off_is_none():
    assert jr.open_journal(None) is None
    assert jr.open_journal("").path.name == "journal.db"


# ------------------------------------------------------- journal as a service


async def test_an_entry_survives_the_bus_round_trip(book):
    from fake_carrier import FakeCarrier as Bus

    from till_infinity.utils.topics import JOURNAL

    bus = Bus()
    sub = bus.subscribe(JOURNAL, group="journal")
    entry = Entry(
        title="Alerted on gold",
        kind=Kind.DECISION,
        actor="agents/risk",
        rationale="30bps against a 0.3bps average",
        context={"spread_bps": 30.0},
        tags=("gold",),
        confidence=0.9,
    )

    assert await jr.publish(bus, entry)
    rebuilt = jr.from_message((await sub.next()).payload)
    assert rebuilt == entry
    assert rebuilt.id == entry.id


async def test_listen_writes_what_is_published(book):
    from fake_carrier import FakeCarrier as Bus

    from till_infinity.utils.topics import JOURNAL

    bus = Bus()
    bus.subscribe(JOURNAL, group="journal")
    await jr.publish(bus, Entry(title="one", actor="structures"))
    await jr.publish(bus, Entry(title="two", actor="agents"))

    assert await jr.listen(bus, book, limit=2) == 2
    assert {entry.title for entry in jr.read(book.path)} == {"one", "two"}


async def test_two_services_publishing_one_decision_is_one_row(book):
    """Ids are recomputed from content, so a duplicate collapses."""
    from fake_carrier import FakeCarrier as Bus

    from till_infinity.utils.topics import JOURNAL

    bus = Bus()
    bus.subscribe(JOURNAL, group="journal")
    entry = Entry(title="same call", actor="agents/risk", time=1_000.0)
    await jr.publish(bus, entry)
    await jr.publish(bus, entry)

    await jr.listen(bus, book, limit=1)
    assert len(jr.read(book.path)) == 1


async def test_recording_prefers_the_bus_when_there_is_one(book):
    """One writer is the point; a caller passing both should not write twice."""
    from fake_carrier import FakeCarrier as Bus

    from till_infinity.utils.topics import JOURNAL

    bus = Bus()
    sub = bus.subscribe(JOURNAL, group="journal")
    ref = await jr.decide(book, "over the bus", rationale="r", bus=bus)

    assert ref
    assert (await sub.next()).payload["title"] == "over the bus"
    assert jr.read(book.path) == []  # published, not written here


async def test_recording_falls_back_to_writing_when_there_is_no_bus(book):
    """A bus is a dependency; recording a decision must not require one."""
    ref = await jr.decide(book, "written directly", rationale="r", bus=None)
    assert jr.get(book.path, ref) is not None
