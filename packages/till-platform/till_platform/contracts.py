"""The bus message schemas, loaded from `shared/contracts/bus/`.

**The schemas live outside the package on purpose.** A Go service has to read
the same files, so they are JSON at the top level rather than Python objects
here - [ADR 0002](../../docs/adr/0002-services-are-self-contained.md) says
`shared/` holds the things both sides of a boundary must agree on, and a
contract only one side can parse is not one of them.

This module is the Python side of that: it finds the files and validates a
payload against one. The files are the contract; this is a reader.

**A schema nobody checks is documentation.** `tests/test_bus_contracts.py`
validates what the producers actually publish, which is the only thing that
stops these drifting into a description of what the bus used to carry - the
same failure `tests/test_service_boundaries.py` guards against for imports.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

#: Where the JSON lives, relative to this file:
#: `packages/till-platform/till_platform/` -> repository root ->
#: `shared/contracts/bus`. Resolved rather than assumed, so
#: a wrong answer is an error here rather than a silently empty schema set.
HOME = Path(__file__).resolve().parents[3] / "shared" / "contracts" / "bus"


class NoSuchContractError(KeyError):
    """No schema is declared for that topic.

    Distinct from a validation failure: an undeclared topic is a gap in the
    contracts, and a payload that fails a declared one is a gap in a producer.
    """


@cache
def declared() -> tuple[str, ...]:
    """Every topic with a schema, in order."""
    if not HOME.is_dir():
        return ()
    return tuple(sorted(path.stem for path in HOME.glob("*.json")))


@cache
def schema_for(topic: str) -> dict[str, Any]:
    """The schema for `topic`, by its bus name."""
    path = HOME / f"{topic}.json"
    if not path.is_file():
        raise NoSuchContractError(f"no schema for {topic!r} in {HOME}")
    loaded = json.loads(path.read_text())
    # The file name is the topic, and `$id` repeats it. They are checked
    # against each other because a renamed file with a stale `$id` would load
    # and validate the wrong thing.
    if loaded.get("$id") != topic:
        raise ValueError(f"{path.name} declares $id {loaded.get('$id')!r}, not {topic!r}")
    return loaded


def check(topic: str, payload: Any) -> None:
    """Raise if `payload` does not satisfy the topic's schema.

    `jsonschema` is imported here rather than at module scope so that reading
    a schema does not require the validator - the Go side needs the files, and
    a Python caller that only wants to know what is declared should not pay for
    a dependency it is not using.
    """
    import jsonschema

    jsonschema.validate(payload, schema_for(topic))
