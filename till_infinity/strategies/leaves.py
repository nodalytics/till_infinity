"""Every desk this node can build, written out as classes.

A leaf is one **(decision, exit, entry)** triple, and each of the three is a
mixin or a base that knows nothing about the other two:

    class StatespaceLongResting(StatespaceLong, ManagedExit, RestingEntry): ...
      #                        ^decision  ^exit        ^entry

That is what "entries and exits are asymmetric" means in code, and the reason
it is three independent pieces rather than one hierarchy with flags: a decision
composes with any entry, and either composes with any exit. `surprise.py` makes
the argument for the first half and `exits.py` for the second.

## Why the classes are written out and not composed at build time

Nautilus derives a `strategy_id` as `ClassName-order_id_tag`, and matches an
external order back to a strategy by it. A name that changed between runs would
orphan every order the previous run left open - which is the same failure
`desks._tag` guards against with `crc32` instead of `hash`, one level up. A
class created by `type()` at build time is one rename away from doing that
silently, so the names live here where a diff shows them.

**This file is what `node/desks.py` builds**, and until it existed that file
built the bare entry classes: `EdgeEntry`, `RestingEntry`, `ArrivalEntry`, with
no decision mixin in front of them. `Desk.decide` raises by design, so every
production desk raised `NotImplementedError` on the first proposal it was
handed - a node that came up, registered, health-checked and could not judge a
signal. The composed leaves existed, were tested, and were built by nothing.

## The exit is a property of the rule, with one override

A thesis owns its exit: how long to hold, whether staleness applies, whether a
stop trails, are all statements about *the idea*, not about how the order was
placed. So each leaf below names its exit, and the only configuration is
`TRADING_EXITS`, which replaces it everywhere at once.

That override exists for one real case rather than for symmetry. `manage.py`
records the hazard: the MT5 bridge runs its own trailing-stop handler on a
twenty-second timer, Nautilus has native trailing orders, and `advance` is
ours - three things that can move a stop and exactly one that may. A deploy
that cannot switch the bridge's handler off needs `TRADING_EXITS=venue`, and
the alternative to being able to say so is a desk with two policies racing on
one order.
"""

from __future__ import annotations

import sys
from functools import cache
from typing import ClassVar

from ..statespace.deciding import LongProfile, LongSide, ShortProfile, ShortSide

#: `bands.py` owns eleven estimators and two signal forms, which is a
#: module's worth of rules rather than three classes in this one.
from .bands import BandsArrival, BandsEdge, BandsResting
from .desk import Desk
from .entries import (
    ArrivalEntry,
    ArrivalEntryConfig,
    EdgeEntry,
    EdgeEntryConfig,
    RestingEntry,
    RestingEntryConfig,
)
from .exits import ExitMechanism, ManagedExit, VenueExit
from .profile import Profile
from .structure import StructureEdge
from .surprise import SurpriseArrival, SurpriseEdge, SurpriseResting

# --------------------------------------------------- the statespace side leaves

#: One leaf per side, not a `side` flag inside one class.
#:
#: `deciding.py` makes the argument and it is the magic-number argument again,
#: one level down: a flag would give one `strategy_id` across both sides, so
#: *which side took this trade* would be something to remember rather than
#: something the engine records. Two classes make it a fact.
#:
#: The long and the short carry the **same numbers** today - `LongProfile` and
#: `ShortProfile` are written out separately and are identical - because no
#: long/short asymmetry has been measured in a dispersion trigger. The shape is
#: a capability, not a claim.


class StatespaceLongProfile(LongProfile, Profile):
    """`LongProfile`'s numbers, carried on a `Profile`.

    **The seam `SideProfile` said would be needed, and the desk then needed.**
    `statespace` may not import `strategies`, so the side profiles there are
    plain classes of `ClassVar`s - and `Desk` sizes an accepted intent through
    `profile.multipliers`, which only a `Profile` has. A leaf built on the bare
    `SideProfile` therefore decided correctly and raised `AttributeError` on the
    way to a size, which is one gate past where any unit test was looking.

    The side's values win, so the mixin comes first: `Profile.name` is `""` and
    `Profile.shape` is `"level"`, and either of those shadowing the side's
    would put the leaf on the wrong signals under the wrong name.
    """


class StatespaceShortProfile(ShortProfile, Profile):
    """`ShortProfile`'s numbers, carried on a `Profile`. See the long one."""


class StatespaceLong(LongSide):
    """`LongSide`, with its numbers on a `Profile` the desk can size with.

    Built with `__new__` and no `__init__`, exactly as `Surprise` builds its
    own: a profile is configuration, and two instances of one strategy on two
    instruments share it. The consequence is that `self.settings` is absent,
    which is harmless on the path production runs - `Profile.multipliers`
    returns before reading it while `SIZING_MULTIPLIERS` names nothing - and
    would raise if the multipliers were switched on. That hazard is
    `Surprise`'s too, and is worth one fix in `Profile` rather than two copies
    of a different answer here.
    """

    profile: ClassVar[Profile] = StatespaceLongProfile.__new__(StatespaceLongProfile)


class StatespaceShort(ShortSide):
    """`ShortSide`, with its numbers on a `Profile`. See the long one."""

    profile: ClassVar[Profile] = StatespaceShortProfile.__new__(StatespaceShortProfile)


class StatespaceLongEdge(StatespaceLong, ManagedExit, EdgeEntry):
    """The long side of a statespace surprise, taken at market."""


class StatespaceLongResting(StatespaceLong, ManagedExit, RestingEntry):
    """The long side, left as a limit at the entry it named."""


class StatespaceLongArrival(StatespaceLong, ManagedExit, ArrivalEntry):
    """The long side, parked until price comes to it and a bar confirms."""


class StatespaceShortEdge(StatespaceShort, ManagedExit, EdgeEntry):
    """The short side of a statespace surprise, taken at market."""


class StatespaceShortResting(StatespaceShort, ManagedExit, RestingEntry):
    """The short side, left as a limit at the entry it named."""


class StatespaceShortArrival(StatespaceShort, ManagedExit, ArrivalEntry):
    """The short side, parked until price comes to it and a bar confirms."""


# ------------------------------------------------------------- the registries

#: The entry mechanisms and their configs, by the name an operator writes in
#: `TRADING_ENTRIES`.
ENTRIES: dict[str, tuple[type[Desk], type]] = {
    "edge": (EdgeEntry, EdgeEntryConfig),
    "resting": (RestingEntry, RestingEntryConfig),
    "arrival": (ArrivalEntry, ArrivalEntryConfig),
}

#: The exit mechanisms, by the name an operator writes in `TRADING_EXITS`.
EXITS: dict[str, type[ExitMechanism]] = {
    "managed": ManagedExit,
    "venue": VenueExit,
}

#: Every leaf, by the `(rule, entry)` an operator names.
#:
#: A rule that is listed for one entry and not another is a rule that cannot be
#: run that way, and `desks.build` says so rather than skipping it: a desk set
#: silently smaller than the one asked for is the shape of bug this repository
#: has paid for repeatedly.
LEAVES: dict[tuple[str, str], type[Desk]] = {
    ("statespace-surprise", "edge"): SurpriseEdge,
    ("statespace-surprise", "resting"): SurpriseResting,
    ("statespace-surprise", "arrival"): SurpriseArrival,
    ("statespace-long", "edge"): StatespaceLongEdge,
    ("statespace-long", "resting"): StatespaceLongResting,
    ("statespace-long", "arrival"): StatespaceLongArrival,
    ("statespace-short", "edge"): StatespaceShortEdge,
    ("statespace-short", "resting"): StatespaceShortResting,
    ("statespace-short", "arrival"): StatespaceShortArrival,
    # **One entry, deliberately.** `smc_bos_c_L50|M15|N20|time` says "at
    # market, on the open of the first minute after the M15 close", so a rest
    # at a named price and a wait for an arrival are both a different rule.
    # Listed for the edge alone, `desks.build` refuses the other two by name -
    # which is the behaviour this table exists for.
    ("smc-bos-causal", "edge"): StructureEdge,
    ("bands", "edge"): BandsEdge,
    ("bands", "resting"): BandsResting,
    ("bands", "arrival"): BandsArrival,
}

#: The rules a deployment may name in `TRADING_STRATEGIES`.
RULES: tuple[str, ...] = tuple(dict.fromkeys(rule for rule, _ in LEAVES))


def leaf(rule: str, entry: str, exits: str = "") -> type[Desk]:
    """The strategy class for one `(rule, entry)`, with its exit replaced if asked.

    `exits` empty means *the one the rule declared*, which is the case every
    existing deploy runs and the one that keeps the class names in this file.
    """
    try:
        found = LEAVES[(rule, entry)]
    except KeyError:
        raise ValueError(
            f"there is no {rule!r} desk on the {entry!r} entry. "
            f"Known pairings: {', '.join(f'{r}/{e}' for r, e in sorted(LEAVES))}."
        ) from None
    if not exits:
        return found
    try:
        wanted = EXITS[exits]
    except KeyError:
        raise ValueError(
            f"TRADING_EXITS names {exits!r}, which is not an exit mechanism. "
            f"Known: {', '.join(sorted(EXITS))}."
        ) from None
    return found if issubclass(found, wanted) else _with_exit(found, wanted)


@cache
def _with_exit(found: type[Desk], wanted: type[ExitMechanism]) -> type[Desk]:
    """`found` with its exit mixin swapped for `wanted`.

    Cached so the same override gives the same class object on every call: two
    classes of one name would be two `strategy_id` namespaces for one desk, and
    Nautilus would refuse the second registration rather than merge them.

    The name is derived and not invented, so it is stable across restarts for
    the reason `desks._tag` gives at length - a tag that changes orphans every
    open order. `SurpriseEdge` with `VenueExit` is `SurpriseEdgeVenue`.
    """
    bases = tuple(
        wanted if isinstance(base, type) and issubclass(base, ExitMechanism) else base
        for base in found.__bases__
    )
    name = f"{found.__name__}{wanted.__name__.removesuffix('Exit')}"
    built = type(
        name,
        bases,
        {"__doc__": f"{found.__name__}, with the exit held by {wanted.__name__}."},
    )
    # **Bound into this module, or a backtest cannot find it.**
    # `desks.importable` serialises a desk as `module:ClassName` for
    # `BacktestNode`, which imports the module and looks the name up. A class
    # that exists only inside this function's cache resolves in the live node
    # and raises in the backtest - and a backtest that cannot build the desk
    # production runs is the one failure the whole port was for.
    setattr(sys.modules[__name__], name, built)
    return built


__all__ = [
    "ENTRIES",
    "EXITS",
    "LEAVES",
    "RULES",
    "StatespaceLong",
    "StatespaceLongArrival",
    "StatespaceLongEdge",
    "StatespaceLongProfile",
    "StatespaceLongResting",
    "StatespaceShort",
    "StatespaceShortArrival",
    "StatespaceShortEdge",
    "StatespaceShortProfile",
    "StatespaceShortResting",
    "StructureEdge",
    "leaf",
]
