"""Which features are switched on and have never actually done anything.

## The failure this exists for

Six defects in one week shared a shape, and it is not a shape tests catch:
**code that is enabled, correct, and reached by nothing.** Each passed its own
suite, because a test proves the code computes the right answer and nothing
proved it ran.

* A projection hook placed beside `vol.learn`, and therefore gated behind
  `STRUCTURES_VOL_LEARNER` - a flag about a different model entirely.
* A broker-unreachable alarm on a code path that `_attach` never returns to
  when the broker is unreachable at start-up.
* **Every trading alert this desk had ever raised**, dropped by a shape filter
  because `Filter.key` falls back to the source name and the config said
  `trade` where the source is `trading`. Logged at `debug`, in a container that
  runs at INFO.
* A simulator emitting bars the feed cannot produce, inside the null every arm
  scored against.
* A corrected spread feature going non-finite on simulated paths, which dropped
  **every control cell in a six-arm study** and reported it as thin data.
* A forecaster deferral that shipped, was verified against a freshly built
  object, and reached nothing - because production **restores** rather than
  builds, and the field it needed defaulted empty.

The last one is the clearest statement of the problem: it was deployed, checked,
and inert for an afternoon, and what eventually caught it was somebody reading a
number the desk had emitted.

**It recurred three times in one day after this module was written**, which is
the more useful fact. `trading/affordable.py` shipped with no export and no
caller; `STRUCTURES_CYCLES_ACT` shipped read by nothing but its own `to_dict`;
`trading/turning.py` shipped tested and never called from the close path. All
three passed their own suites throughout, and none of them declared an effect -
so this module, which exists precisely to catch them, could not. Writing the
detector is not the same as using it, which is the same mistake one level up.

They declare now: `structures.cycles_cap`, `trading.turn_exit` and
`trading.unaffordable_refusal`. And `tests/test_effects.py` asserts that each
**firing path actually reaches its declaration**, because a declaration nothing
fires is this defect wearing a badge that says it is not.

## What this asks, and how it differs from `liveness.py`

`liveness.py` asks whether a **published field varies** - whether a column that
is being written and consumed carries anything. This asks one step earlier and
one layer down: **did this code run at all.**

Three states, because they want different actions:

* **not declared, or declared off** - nothing to say, and nothing is said.
* **on and firing** - the ordinary case, carried with a count and timestamps so
  a feature that worked and then *stopped* is visible too. That is the same
  failure arriving later.
* **on and never fired** - the state this module exists to name. After a grace
  period it is reported, because before one a feature may simply be waiting for
  its first bar.

## What it deliberately does not do

**It does not fail a healthcheck.** An inert feature is a reason for somebody to
look, not a reason to restart a container - restarting cannot reach a flag that
was wired to the wrong gate, and a restart loop through the problem makes it
worse. `_watch_reachable` draws the same line for the same reason.

**It never raises.** It is diagnostic, and diagnostics that can fail during the
fault they describe are worse than none - `_shout` carries that note too.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

#: How long a declared-and-enabled feature may stay silent before it is
#: reported. Generous, because a feature keyed to a daily bar legitimately waits
#: hours for its first firing, and an alarm that cries wolf on start-up is one
#: nobody reads - which is the failure this module is about.
GRACE = 3_600.0


@dataclass(slots=True)
class Effect:
    """One feature's record: is it on, has it ever run, and when last."""

    name: str
    enabled: bool = False
    declared_at: float = field(default_factory=time.time)
    count: int = 0
    first_at: float = 0.0
    last_at: float = 0.0

    @property
    def inert(self) -> bool:
        return self.enabled and self.count == 0

    def to_dict(self) -> dict:
        now = time.time()
        return {
            "enabled": self.enabled,
            "count": self.count,
            "declared_s": round(now - self.declared_at, 1),
            "first_s": round(now - self.first_at, 1) if self.first_at else None,
            "last_s": round(now - self.last_at, 1) if self.last_at else None,
        }


#: Process-wide, because the services share one process and one in-process bus.
#: A plain dict rather than a lock: every write here is a single assignment or a
#: single increment, the worst a race can cost is one lost count, and taking a
#: lock on a hot path to protect a diagnostic would be the instrument changing
#: what it measures.
_EFFECTS: dict[str, Effect] = {}


def declare(name: str, *, enabled: bool) -> None:
    """Register a feature and whether it is switched on.

    Called where the flag is **read**, not where the work happens, so that a
    feature which is on and never reached still has a record. Declaring at the
    call site would mean an unreached feature is also an undeclared one, which
    is precisely the blind spot.
    """
    try:
        found = _EFFECTS.get(name)
        if found is None:
            _EFFECTS[name] = Effect(name=name, enabled=enabled)
        else:
            found.enabled = enabled
    except Exception:  # pragma: no cover - a reporter must not be the fault
        pass


def fired(name: str, n: int = 1) -> None:
    """Record that the feature actually did its work. Cheap and never raises."""
    try:
        found = _EFFECTS.get(name)
        if found is None:
            found = _EFFECTS[name] = Effect(name=name, enabled=True)
        now = time.time()
        found.count += n
        found.last_at = now
        if not found.first_at:
            found.first_at = now
    except Exception:  # pragma: no cover
        pass


def inert(grace: float = GRACE) -> list[str]:
    """Features that are on, have been on a while, and have never run.

    The grace period is the whole difference between this and a start-up alarm:
    before it, silence is indistinguishable from waiting for the first bar.
    """
    now = time.time()
    return sorted(e.name for e in _EFFECTS.values() if e.inert and now - e.declared_at >= grace)


def report() -> dict[str, dict]:
    """Everything declared, for a status file or a human."""
    return {name: e.to_dict() for name, e in sorted(_EFFECTS.items())}


def summary(grace: float = GRACE) -> str:
    """One line, for a log or a healthcheck."""
    on = [e for e in _EFFECTS.values() if e.enabled]
    quiet = inert(grace)
    parts = [f"{len(on)} enabled", f"{sum(e.count for e in on):,} firings"]
    if quiet:
        parts.append("NEVER FIRED: " + ", ".join(quiet))
    return " · ".join(parts)


def reset() -> None:
    """For tests. Production never calls this."""
    _EFFECTS.clear()
