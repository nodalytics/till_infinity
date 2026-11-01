"""The journal's store and its entries: append-only, point-in-time, pairable.

What the Actor does with them is `test_journal_actor.py`. What `service.py`'s
helpers and the `Carrier` transport did is
`research/retire/journal/tests/test_journal_service.py`, with the code.

These used to be written through `jr.decide`, `jr.note` and `jr.observe`, which
retired on 2026-11-01. They construct an `Entry` and call `Journal.write`
instead - which is what the store's own tests should always have done: a test
of a tag filter that went through three modules to reach the filter was
measuring the helpers too.
"""

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


def decision(title: str = "d", **fields) -> Entry:
    base = {"title": title, "kind": Kind.DECISION, "rationale": "r"}
    return Entry(**(base | fields))


# --------------------------------------------------------------- appending


async def test_a_decision_keeps_its_reasoning(book):
    entry = decision(
        "Alerted on OANDA gold spread",
        rationale="30bps against a 0.3bps 24h average, nothing on the calendar",
        actor="EdgeEntry-GOLD",
        context={"venue": "OANDA", "spread_bps": 30.0, "avg_bps": 0.3},
        tags=("gold", "OANDA"),
        confidence=0.9,
    )
    await book.write(entry)

    stored = jr.get(book.path, entry.id)
    assert stored.rationale.startswith("30bps against")
    assert stored.context["spread_bps"] == 30.0
    assert stored.tags == ("gold", "OANDA")
    assert stored.confidence == 0.9
    assert stored.kind is Kind.DECISION


async def test_recording_the_same_decision_twice_is_one_entry(book):
    """A watcher that restarts and re-judges a window must not double-record."""
    entry = Entry(title="same", actor="agents/risk", kind=Kind.DECISION, time=1_000.0)
    assert await book.write(entry) == 1
    assert await book.write(entry) == 0
    assert len(jr.read(book.path)) == 1


async def test_there_is_no_update_path(book):
    """Append-only is enforced, not promised - a journal you can edit is not one."""
    assert not [name for name in dir(book) if "update" in name or "delete" in name]
    await book.write(Entry(title="original"))
    with jr.read_only(book.path) as conn, pytest.raises(sqlite3.OperationalError):
        conn.execute("UPDATE entries SET title = 'rewritten'")


async def test_context_is_copied_in_not_referenced(book):
    """The stores move on; an entry must still describe the world it decided in.

    The copy lived in `service.decide` until 2026-11-01 and is now in
    `Entry.__post_init__`, which matters more than it did: an entry waits on the
    Actor's buffer for up to `flush_seconds` before the JSON is written, where
    `record` wrote it on the next line.
    """
    state = {"spread_bps": 30.0}
    entry = decision(context=state)
    state["spread_bps"] = 0.3  # the market moved, and the caller's dict with it

    await book.write(entry)
    assert jr.get(book.path, entry.id).context["spread_bps"] == 30.0


async def test_an_unserialisable_context_does_not_lose_the_entry(book):
    entry = decision(context={"when": object()})
    await book.write(entry)
    assert jr.get(book.path, entry.id) is not None


# ---------------------------------------------------------------- outcomes


async def test_an_outcome_pairs_with_its_decision(book):
    made = decision("Alerted on gold", tags=("gold",))
    await book.write(made)
    await book.write(
        Entry(
            title="Spread normalised in 4 minutes",
            kind=Kind.OUTCOME,
            parent=made.id,
            context={"spread_bps": 0.31},
        )
    )

    followed = jr.read(book.path, parent=made.id)
    assert len(followed) == 1
    assert followed[0].kind is Kind.OUTCOME
    assert followed[0].context["spread_bps"] == 0.31


async def test_an_observation_is_kept_as_a_negative_example(book):
    """A model trained only on the times we acted learns nothing about when not to."""
    await book.write(
        Entry(
            title="Looked at a wide spread and did not alert",
            kind=Kind.OBSERVATION,
            rationale="stale feed",
        )
    )
    assert jr.read(book.path, kind=Kind.OBSERVATION)[0].kind is Kind.OBSERVATION


# ----------------------------------------------------------------- reading


async def test_filters_compose(book):
    await book.write(
        [
            decision("gold thing", actor="agents/risk", tags=("gold",)),
            decision("btc thing", actor="agents/risk", tags=("btc",)),
            Entry(title="human thing", kind=Kind.NOTE, actor="human"),
        ]
    )

    assert len(jr.read(book.path)) == 3
    assert len(jr.read(book.path, actor="agents/risk")) == 2
    assert len(jr.read(book.path, tag="gold")) == 1
    assert len(jr.read(book.path, kind=Kind.NOTE)) == 1
    assert len(jr.read(book.path, actor="agents/risk", tag="btc")) == 1


async def test_a_tag_filter_does_not_match_a_longer_tag(book):
    await book.write(decision("a", tags=("golden-cross",)))
    assert jr.read(book.path, tag="gold") == []


async def test_reads_are_newest_first(book):
    await book.write([Entry(title=f"e{n}", time=float(n)) for n in range(10)])
    entries = jr.read(book.path, limit=3)
    assert [e.title for e in entries] == ["e9", "e8", "e7"]


async def test_an_explicit_limit_is_honoured_past_the_display_ceiling(book):
    """`limit` used to be clamped to MAX_ROWS, silently.

    `facto.dataset` asked for its 200,000 rows, got 500, and reported a few
    hundred usable examples from a journal holding thousands - a truncation
    that read as missing data. The count here is deliberately past MAX_ROWS:
    the old assertion wrote ten entries and checked they numbered under five
    hundred, which was true however the clamp behaved.
    """
    total = jr.MAX_ROWS * 2
    await book.write([Entry(title=f"e{n}", time=float(n)) for n in range(total)])

    assert len(jr.read(book.path, limit=total)) == total
    assert len(jr.read(book.path, limit=jr.MAX_ROWS)) == jr.MAX_ROWS
    # The oldest entry is reachable, which is the point: a fit that cannot see
    # past the recent window is validating itself inside one afternoon.
    assert jr.read(book.path, limit=total)[-1].title == "e0"


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
    entry = decision(
        "Alerted",
        rationale="why",
        actor="agents/risk",
        context={"spread_bps": 30.0},
        tags=("gold",),
        confidence=0.8,
    )
    await book.write(entry)

    out = tmp_path / "j.jsonl"
    jr.export(book.path, target=out)
    row = json.loads(out.read_text().splitlines()[0])
    assert row == {
        "id": entry.id,
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


async def test_writing_to_a_journal_that_was_never_opened_raises_here(tmp_path):
    """The store is blunt about it; **the Actor is what must not be.**

    `service.record` swallowed this so a full disk cost the record and not the
    collector. That guarantee moved to `JournalActor`, which is now the only
    thing on a path that decides trades - see
    `test_a_write_failure_does_not_take_the_desk_down`. A script calling the
    store directly wants the exception.
    """
    broken = Journal(tmp_path / "j.db")  # never opened
    with pytest.raises(RuntimeError, match="not open"):
        await broken.write(Entry(title="d"))


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


# ------------------------------------------------------- off the wire


def test_a_sender_cannot_claim_an_id_that_is_not_its_content():
    payload = Entry(title="real", actor="a", time=1.0).to_dict()
    payload["id"] = "deadbeefdeadbeef"
    assert Entry.from_message(payload).id != "deadbeefdeadbeef"


@pytest.mark.parametrize(
    "payload",
    [None, "text", 42, {}, {"title": "  "}, {"kind": "decision"}],
)
def test_junk_on_the_wire_is_dropped_not_written(payload):
    assert Entry.from_message(payload) is None


def test_hostile_fields_are_coerced_rather_than_trusted():
    rebuilt = Entry.from_message(
        {"title": "x", "context": ["not", "a", "dict"], "tags": "gold", "confidence": "high"}
    )
    assert rebuilt.context == {}
    assert rebuilt.tags == ()
    assert rebuilt.confidence is None


def test_a_full_entry_survives_the_round_trip_through_a_dict():
    """`to_dict` is what a publisher puts on the bus and `from_message` is what
    the Actor reads off it, so the pair has to be lossless or the record is a
    subset of what was decided.
    """
    entry = Entry(
        title="Alerted on gold",
        kind=Kind.DECISION,
        actor="EdgeEntry-GOLD",
        rationale="30bps against a 0.3bps average",
        context={"spread_bps": 30.0},
        tags=("gold",),
        confidence=0.9,
        time=1_000.0,
    )
    rebuilt = Entry.from_message(entry.to_dict())
    assert rebuilt == entry
    assert rebuilt.id == entry.id
