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
import os
from functools import cache
from pathlib import Path
from typing import Any

#: The environment variable that settles it, for whoever ships the files.
CONTRACTS_DIR = "TILL_CONTRACTS_DIR"

#: Where to look, relative to a starting directory.
_UNDER = Path("shared") / "contracts" / "bus"


def _find() -> Path:
    """Locate `shared/contracts/bus`, by searching rather than by arithmetic.

    **This was `Path(__file__).resolve().parents[3] / "shared" / ...` and it
    worked only in the repository.** Counting parents encodes this module's
    position in a tree, and the position changed the moment the package became
    installable: from
    `.venv/lib/python3.11/site-packages/till_platform/contracts.py`, three
    parents up is `.venv/lib`, so the image looked for
    `/app/.venv/lib/shared/contracts/bus` while the files sat in
    `/app/shared/contracts/bus`. The container shipped the contracts and could
    not find them, and `declared()` answered "nothing is declared" - the exact
    failure the docstring on that line claimed it prevented. It is the same
    mistake `frozen.ship()` was changed to avoid, in the same package, and the
    lesson is written down in ADR 0002.

    The order is: what the environment says, then up from this file, then up
    from the working directory. The first two cover the repository and a
    deployment that declares itself; the third covers a container whose
    WORKDIR is the tree root.
    """
    told = os.environ.get(CONTRACTS_DIR)
    if told:
        return Path(told)
    for start in (Path(__file__).resolve(), Path.cwd().resolve() / "_"):
        for parent in start.parents:
            candidate = parent / _UNDER
            if candidate.is_dir():
                return candidate
    # Nothing found. Returned rather than raised, because importing this module
    # must not fail - `missing()` is how a caller asks whether it worked.
    return Path(__file__).resolve().parents[3] / _UNDER


HOME = _find()


def missing() -> str:
    """Why there are no contracts, or an empty string if there are.

    **`declared()` returning `()` is indistinguishable from a bus that
    declares nothing**, which is how an image that could not find its own
    schemas reported success. Anything that needs the contracts to exist asks
    this first, and the image build does exactly that.
    """
    if not HOME.is_dir():
        return f"{HOME} is not a directory - set {CONTRACTS_DIR} to where the schemas are"
    if not declared():
        return f"{HOME} holds no *.json schemas"
    return ""


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
