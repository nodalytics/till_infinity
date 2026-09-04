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
