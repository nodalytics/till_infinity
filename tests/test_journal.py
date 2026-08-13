"""The journal: append-only, point-in-time, and paired with what happened next."""

from __future__ import annotations

import json
import sqlite3

import pytest

from till_infinity import journal as jr
from till_infinity.journal import Entry, Journal, Kind


@pytest.fixture
async def book(tmp_path):
    async with Journal(tmp_path / "journal.db") as journal:
        yield journal


# --------------------------------------------------------------- appending


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


async def test_recording_the_same_decision_twice_is_one_entry(book):
    """A watcher that restarts and re-judges a window must not double-record."""
    entry = Entry(title="same", actor="agents/risk", kind=Kind.DECISION, time=1_000.0)
    assert await book.write(entry) == 1
    assert await book.write(entry) == 0
    assert len(jr.read(book.path)) == 1


async def test_there_is_no_update_path(book):
    """Append-only is enforced, not promised — a journal you can edit is not one."""
    assert not [name for name in dir(book) if "update" in name or "delete" in name]
    await jr.note(book, "original")
    with jr.read_only(book.path) as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("UPDATE entries SET title = 'rewritten'")


async def test_context_is_copied_in_not_referenced(book):
    """The stores move on; an entry must still describe the world it decided in."""
    state = {"spread_bps": 30.0}
    ref = await jr.decide(book, "d", rationale="r", context=state)
    state["spread_bps"] = 0.3  # the market moved, and the caller's dict with it
    assert jr.get(book.path, ref).context["spread_bps"] == 30.0


async def test_an_unserialisable_context_does_not_lose_the_entry(book):
    ref = await jr.decide(book, "d", rationale="r", context={"when": object()})
    assert jr.get(book.path, ref) is not None


# ---------------------------------------------------------------- outcomes


async def test_an_outcome_pairs_with_its_decision(book):
    ref = await jr.decide(book, "Alerted on gold", rationale="wide", tags=("gold",))
    await jr.outcome(book, ref, "Spread normalised in 4 minutes", context={"spread_bps": 0.31})

    followed = jr.read(book.path, parent=ref)
    assert len(followed) == 1
    assert followed[0].kind is Kind.OUTCOME
    assert followed[0].context["spread_bps"] == 0.31


async def test_an_outcome_with_no_parent_is_refused(book):
    """It could never be paired, so it is not a training example — just noise."""
    assert await jr.outcome(book, "", "something happened") == ""
    assert jr.read(book.path) == []


async def test_an_observation_is_kept_as_a_negative_example(book):
    await jr.observe(book, "Looked at a wide spread and did not alert", rationale="stale feed")
    assert jr.read(book.path, kind=Kind.OBSERVATION)[0].kind is Kind.OBSERVATION


# ----------------------------------------------------------------- reading


async def test_filters_compose(book):
    await jr.decide(book, "gold thing", rationale="r", actor="agents/risk", tags=("gold",))
    await jr.decide(book, "btc thing", rationale="r", actor="agents/risk", tags=("btc",))
    await jr.note(book, "human thing", actor="human")

    assert len(jr.read(book.path)) == 3
    assert len(jr.read(book.path, actor="agents/risk")) == 2
    assert len(jr.read(book.path, tag="gold")) == 1
    assert len(jr.read(book.path, kind=Kind.NOTE)) == 1
    assert len(jr.read(book.path, actor="agents/risk", tag="btc")) == 1


async def test_a_tag_filter_does_not_match_a_longer_tag(book):
    await jr.decide(book, "a", rationale="r", tags=("golden-cross",))
    assert jr.read(book.path, tag="gold") == []


async def test_reads_are_newest_first_and_capped(book):
    await book.write([Entry(title=f"e{n}", time=float(n)) for n in range(10)])
    entries = jr.read(book.path, limit=3)
    assert [e.title for e in entries] == ["e9", "e8", "e7"]
    assert len(jr.read(book.path, limit=10_000)) <= jr.MAX_ROWS


async def test_hours_filters_by_age(book):
    import time as clock

    await book.write(
        [
            Entry(title="old", time=clock.time() - 7200),
            Entry(title="new", time=clock.time() - 60),
        ]
    )
    assert [e.title for e in jr.read(book.path, hours=1)] == ["new"]


def test_reading_a_journal_that_does_not_exist_says_so(tmp_path):
    with pytest.raises(FileNotFoundError, match="nothing has been recorded"):
        jr.read(tmp_path / "missing.db")


# ------------------------------------------------------------------ export


async def test_export_is_oldest_first_for_a_sequence_model(book, tmp_path):
    await book.write([Entry(title=f"e{n}", time=float(n)) for n in range(3)])
    out = tmp_path / "journal.jsonl"
    assert jr.export(book.path, target=out) == 3

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [row["title"] for row in rows] == ["e0", "e1", "e2"]
    assert rows[0]["context"] == {}  # stays nested, not flattened


async def test_export_round_trips_a_full_entry(book, tmp_path):
    ref = await jr.decide(
        book,
        "Alerted",
        rationale="why",
        actor="agents/risk",
        context={"spread_bps": 30.0},
        tags=("gold",),
        confidence=0.8,
    )
    out = tmp_path / "j.jsonl"
    jr.export(book.path, target=out)
    row = json.loads(out.read_text().splitlines()[0])
    assert row == {
        "id": ref,
        "time": row["time"],
        "kind": "decision",
        "actor": "agents/risk",
        "title": "Alerted",
        "rationale": "why",
        "context": {"spread_bps": 30.0},
        "tags": ["gold"],
        "confidence": 0.8,
        "parent": "",
    }


# ------------------------------------------------------------- resilience


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


def test_a_junk_row_does_not_break_a_read(tmp_path):
    path = tmp_path / "j.db"
    conn = sqlite3.connect(path)
    conn.executescript(jr.store.SCHEMA)
    conn.execute(
        "INSERT INTO entries (id, time, kind, actor, title, context, tags, written)"
        " VALUES ('x', 1.0, 'nonsense', 'a', 't', 'not json', '{}', 1.0)"
    )
    conn.commit()
    conn.close()

    entry = jr.read(path)[0]
    assert entry.kind is Kind.NOTE  # unknown kind degrades rather than raising
    assert entry.context == {}
    assert entry.tags == ()


def test_the_id_ignores_incidental_whitespace():
    a = Entry(title="Gold  dislocated ", actor="x", time=1.0)
    b = Entry(title="gold dislocated", actor="x", time=1.0)
    assert a.id == b.id


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


# ------------------------------------------------------- journal as a service


async def test_an_entry_survives_the_bus_round_trip(book):
    from till_infinity.bus import JOURNAL, Bus

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
    from till_infinity.bus import JOURNAL, Bus

    bus = Bus()
    bus.subscribe(JOURNAL, group="journal")
    await jr.publish(bus, Entry(title="one", actor="structures"))
    await jr.publish(bus, Entry(title="two", actor="agents"))

    assert await jr.listen(bus, book, limit=2) == 2
    assert {entry.title for entry in jr.read(book.path)} == {"one", "two"}


async def test_two_services_publishing_one_decision_is_one_row(book):
    """Ids are recomputed from content, so a duplicate collapses."""
    from till_infinity.bus import JOURNAL, Bus

    bus = Bus()
    bus.subscribe(JOURNAL, group="journal")
    entry = Entry(title="same call", actor="agents/risk", time=1_000.0)
    await jr.publish(bus, entry)
    await jr.publish(bus, entry)

    await jr.listen(bus, book, limit=1)
    assert len(jr.read(book.path)) == 1


async def test_a_sender_cannot_claim_an_id_that_is_not_its_content():
    payload = Entry(title="real", actor="a", time=1.0).to_dict()
    payload["id"] = "deadbeefdeadbeef"
    assert jr.from_message(payload).id != "deadbeefdeadbeef"


@pytest.mark.parametrize(
    "payload",
    [None, "text", 42, {}, {"title": "  "}, {"kind": "decision"}],
)
def test_junk_on_the_wire_is_dropped_not_written(payload):
    assert jr.from_message(payload) is None


def test_hostile_fields_are_coerced_rather_than_trusted():
    rebuilt = jr.from_message(
        {"title": "x", "context": ["not", "a", "dict"], "tags": "gold", "confidence": "high"}
    )
    assert rebuilt.context == {}
    assert rebuilt.tags == ()
    assert rebuilt.confidence is None


async def test_recording_prefers_the_bus_when_there_is_one(book):
    """One writer is the point; a caller passing both should not write twice."""
    from till_infinity.bus import JOURNAL, Bus

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
