"""State keyed by field name rather than by import path."""

import pickle
from collections import deque
from dataclasses import dataclass, field

import pytest

from till_infinity.structures import store
from till_infinity.structures.codec import TAG, key_for, pack, registry, unpack
from till_infinity.structures.state import Restorable


@dataclass(slots=True)
class Holder(Restorable):
    n: float = 0.0
    tags: tuple[str, ...] = ()
    seen: dict = field(default_factory=dict)
    window: deque = field(default_factory=lambda: deque(maxlen=4))


def test_a_class_is_keyed_by_its_file_and_name_not_its_import_path():
    """The basename is the whole trick: moving `anomaly.py` into a subpackage
    keeps the key `anomaly.Detector`, so the package can be reorganised - which
    is the thing pickle made unsafe."""
    from till_infinity.structures.learning.breaking import Breaks

    assert key_for(Breaks) == "breaking.Breaks"
    assert "till_infinity" not in key_for(Breaks)


def test_the_registry_finds_every_persisted_class():
    got = registry()
    assert len(got) > 40
    assert got["breaking.Breaks"].__name__ == "Breaks"
    assert got["levels.Level"].__name__ == "Level"


def test_a_bare_class_name_would_not_have_worked():
    """Walking the package finds `Ensemble` in two modules, `Book` in three.
    Keyed on the name alone, state for one would restore as the other and the
    failure would be wrong numbers rather than a traceback."""
    names = [k.split(".", 1)[1] for k in registry()]
    assert len(names) != len(set(names))


def test_a_tuple_keyed_mapping_survives():
    """`(feed, venue, interval)` keys are everywhere here and msgpack cannot
    express them, so mappings travel as pairs."""
    got = unpack(pack({("gold", "OANDA", "5m"): 1.5}))
    assert got == {("gold", "OANDA", "5m"): 1.5}


def test_a_deque_keeps_its_bound():
    """A deque restored unbounded grows until the box runs out, which is how
    this project has been OOM-killed."""
    got = unpack(pack(deque([1, 2, 3], maxlen=4)))
    assert isinstance(got, deque)
    assert got.maxlen == 4


#: `Holder` lives in this module rather than in `structures`, so the package
#: walk cannot find it. Supplying the registry is what a caller does anyway.
HERE = {"test_state_codec.Holder": Holder}


def test_state_written_before_a_field_existed_still_loads():
    """The same defaulting `Restorable.__setstate__` does."""
    written = pack(Holder(n=2.0))
    del written["f"]["tags"]
    got = unpack(written, HERE)
    assert got.n == 2.0
    assert got.tags == ()


def test_a_round_trip_keeps_every_field():
    got = unpack(pack(Holder(n=1.5, tags=("a", "b"), seen={"k": 2})), HERE)
    assert got.n == 1.5
    assert got.tags == ("a", "b")
    assert got.seen == {"k": 2}


def test_an_unknown_class_costs_itself_and_not_the_file():
    """A model removed from the build should not make weeks of everything else
    unloadable."""
    written = pack(Holder(n=1.0))
    written[TAG] = "gone.Vanished"
    got = unpack(written)
    assert got == {"n": 1.0, "tags": (), "seen": {}, "window": deque(maxlen=4)}


def test_a_river_model_is_carried_opaquely():
    """river objects have no serialisation format. Pickling *river's* classes
    records *river's* paths, which this project does not move - unlike its
    own, which is what made a refactor unsafe."""
    from river import anomaly

    written = pack({"scorer": anomaly.GaussianScorer()})
    inner = written["v"][0][1]
    assert inner[TAG] == "raw"
    assert isinstance(inner["b"], bytes)
    assert type(unpack(written)["scorer"]).__name__ == "GaussianScorer"


def test_a_saved_file_carries_no_import_path_of_ours(tmp_path):
    """The defect this replaces: `till_infinity.structures.learning.anomaly` was in the
    bytes of the old file, so the directory layout was part of the format."""
    store.save({"holder": Holder(n=3.0)}, tmp_path)
    raw = (tmp_path / store.STATE_FILE).read_bytes()
    assert b"till_infinity.structures" not in raw
    assert b"holder" in raw


def test_it_reads_the_old_pickle_once_and_writes_the_new_one(tmp_path):
    """A one-way migration, leaving the old file where it is so a rollback has
    something to roll back to."""
    legacy = tmp_path / store.LEGACY_FILE
    payload = {**store._fingerprint(), "state": {"holder": Holder(n=7.0)}}
    # The format the *old* file was written with. Checking this against the new
    # number is what discarded 58MB of live state on the first deploy - the
    # container version is the one thing migration exists to change.
    payload["format"] = store.FORMAT - 1
    legacy.write_bytes(pickle.dumps(payload))

    got = store.load(tmp_path)
    assert got is not None
    # Read back through pickle, so it is the real object rather than a mapping.
    assert got["holder"].n == 7.0

    store.save(got, tmp_path)
    assert (tmp_path / store.STATE_FILE).exists()
    assert legacy.exists(), "the old file must survive for a rollback"


def test_a_corrupt_file_starts_cold_rather_than_raising(tmp_path):
    (tmp_path / store.STATE_FILE).write_bytes(b"not msgpack at all")
    assert store.load(tmp_path) is None


@pytest.mark.parametrize("value", [None, True, 1, 2.5, "x", b"y", [1, [2]], {"a": {"b": 1}}])
def test_plain_values_pass_through(value):
    assert unpack(pack(value)) == value


def test_a_legacy_file_two_formats_behind_is_not_migrated(tmp_path):
    """Accepting the previous format is a migration; accepting any format is a
    guess about a file this code has never seen."""
    payload = {**store._fingerprint(), "state": {"holder": Holder(n=1.0)}}
    payload["format"] = store.FORMAT - 2
    (tmp_path / store.LEGACY_FILE).write_bytes(pickle.dumps(payload))
    assert store.load(tmp_path) is None


def test_streaming_a_save_writes_what_packing_it_would():
    """`pack_into` must stay a byte-for-byte mirror of `msgpack.packb(pack(x))`.

    This is the test that makes the streaming save safe to put under a live
    206MB state rather than behind a migration. The two code paths walk the same
    structure, and any divergence - a tag spelled differently, a map written
    with the wrong header count, a branch `pack` has and this one does not -
    produces a file that either fails to parse or, worse, parses into the wrong
    shape.

    Every container the codec knows is in the fixture on purpose: dataclass,
    bounded deque, dict with a tuple key, list, tuple, set, and a raw pickle
    node for something the codec cannot describe.
    """
    import io

    import msgpack

    from till_infinity.structures.codec import pack_into
    from till_infinity.structures.context.sessions import Hour

    state = {
        "held": Hour(decisive=1.0, held=2.0, vol_bps=3.0, seen=4.0),
        "ring": deque([1, 2, 3], maxlen=8),
        "mixed": [1, 2.5, "three", None, True, b"four"],
        "pairs": {("gold", "5m"): Hour(decisive=0.5)},
        "grouped": frozenset({1, 2, 3}),
        "shaped": ("a", "b"),
        "opaque": Opaque(9),
    }

    want = msgpack.packb(pack(state), use_bin_type=True)
    buffer = io.BytesIO()
    written = pack_into(state, buffer)
    got = buffer.getvalue()

    assert got == want, "the streamed bytes must equal the packed ones"
    assert written == len(got), "the byte count is what says a save wrote anything"

    back = unpack(msgpack.unpackb(got, raw=False, strict_map_key=False))
    assert back["held"].decisive == 1.0
    assert back["pairs"][("gold", "5m")].decisive == 0.5
    assert back["ring"].maxlen == 8
    assert back["opaque"] == Opaque(9)


def test_a_streamed_save_round_trips_through_load(tmp_path):
    """The end the transient was costing: state written by the streaming path
    has to come back as the same objects, or the saving is free and useless."""
    from till_infinity.structures.context.sessions import Hour

    state = {
        "hour": Hour(decisive=7.0, held=1.0),
        "pairs": {("eurusd", "1m"): Hour(decisive=3.0)},
        "window": deque([1.0, 2.0], maxlen=4),
    }
    store.save(state, tmp_path)
    got = store.load(tmp_path)

    assert got is not None
    assert got["hour"].decisive == 7.0
    assert got["pairs"][("eurusd", "1m")].decisive == 3.0
    assert got["window"].maxlen == 4, "a deque restored unbounded grows until the box dies"


def test_the_save_buffer_is_small_against_the_state_it_writes():
    """`CHUNK` is the whole memory argument: the streaming save's extra cost is
    one buffer, so a buffer that grew to state-sized would give back exactly
    what this change bought. 4MB is ~2% of the live file."""
    from till_infinity.shared import codec

    assert codec.CHUNK <= 8 << 20


def test_a_save_interrupted_partway_leaves_the_last_good_file(tmp_path):
    """A streamed write is only atomic because of the temp-file rename, and it
    spends far longer partially written than a single `write_bytes` did."""
    from till_infinity.structures.context.sessions import Hour

    store.save({"hour": Hour(decisive=1.0)}, tmp_path)
    good = (tmp_path / store.STATE_FILE).read_bytes()

    with pytest.raises(RuntimeError):
        store.save({"hour": Hour(decisive=2.0), "boom": _Exploding()}, tmp_path)

    assert (tmp_path / store.STATE_FILE).read_bytes() == good
    assert store.load(tmp_path)["hour"].decisive == 1.0


class Opaque:
    """Not a dataclass, so it takes the codec's raw-pickle branch."""

    def __init__(self, n):
        self.n = n

    def __eq__(self, other):
        return isinstance(other, Opaque) and other.n == self.n

    def __hash__(self):
        return hash(self.n)


class _Exploding:
    """Raises while being written, partway through the stream."""

    def __reduce__(self):
        raise RuntimeError("no")
