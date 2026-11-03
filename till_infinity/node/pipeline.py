"""The loop: discovery to live capital, and back out again, unattended.

Every other module here is a function. This is what drives them, because a
system that needs somebody to call the functions is not automated.

    discover -> gate -> small capital -> full capital
                 |              |              |
                 +-- rejected   +------ retired -> back to the gate

**State is persisted, not held.** An unattended loop restarts - on a deploy, a
crash, a power event - and a ladder that lives in memory loses every
candidate's position and its history. `restore-drops-deque-maxlen` is the
warning about how that goes wrong quietly: a capped field came back unbounded
from a restore and the declaration still looked right.

**Every decision is logged with its evidence.** Not for audit theatre: a
promotion whose reason cannot be read later cannot be reviewed when the same
candidate reappears, and an automated system will produce the same candidate
again. ADR 0005 puts that record in the journal.

**There is one bound the loop cannot raise.** `CEILING` is the largest share
of the account the ladder may ever allocate without a person changing it.
Full automation and unbounded capital escalation are two different decisions,
and an automated promoter with no ceiling has no fixed point - it will keep
climbing as long as its gates keep passing, and its gates are statistical.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .promotion import Allocation, Candidate, Gate, Retirement, Rung, promote, retire, revive

#: The most the ladder may allocate, ever, without a person editing this.
#:
#: **Deliberately below 1.0.** `Allocation.full` is what a candidate earns by
#: passing every gate; this is what the *system* is allowed to reach in total.
#: The gates are statistical, so they will eventually pass something that
#: should not have passed, and the cost of that needs an upper bound that no
#: amount of passing can lift.
CEILING = 0.60

#: How long a candidate may sit at a rung without producing its episodes
#: before the loop gives up on it. An automated system otherwise accumulates
#: candidates that neither pass nor fail.
STALE_DAYS = 90.0


@dataclass(slots=True)
class Decision:
    """One thing the loop did, and why. Written before it is acted on."""

    at: float
    candidate: str
    action: str
    reason: str
    evidence: str = ""

    def line(self) -> str:
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.at))
        tail = f" | {self.evidence}" if self.evidence else ""
        return f"{when} {self.candidate}: {self.action} - {self.reason}{tail}"


def _gates(saved: Any) -> list[Gate]:
    """The gates on a saved candidate, dropping any that will not rebuild.

    `Gate` refuses one naming no control, so a hand-edited file can hold a
    gate that cannot exist. Dropped one at a time and the rest kept: losing a
    gate costs a hold for want of evidence, where raising would lose every
    candidate in the file. The float sequences come back from JSON as lists
    and are restored as the tuples the dataclass declares.
    """
    found: list[Gate] = []
    for entry in saved or []:
        if not isinstance(entry, dict):
            continue
        try:
            found.append(
                Gate(
                    name=str(entry["name"]),
                    criterion=str(entry["criterion"]),
                    control=str(entry["control"]),
                    candidates=int(entry["candidates"]),
                    episodes=int(entry["episodes"]),
                    passed=entry.get("passed"),
                    reading=entry.get("reading"),
                    note=str(entry.get("note", "")),
                    trial_sharpes=tuple(float(v) for v in entry.get("trial_sharpes") or ()),
                    returns=tuple(float(v) for v in entry.get("returns") or ()),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return found


@dataclass(slots=True)
class Ladder:
    """Every candidate the loop knows about, and what it has done.

    Serialised as JSON rather than through the persistence codec, on purpose:
    `codec` keys state on `basename.ClassName`, which couples a file on disk
    to a module's position - and this file has to be readable by a person
    deciding whether to intervene.
    """

    candidates: dict[str, Candidate] = field(default_factory=dict)
    log: list[Decision] = field(default_factory=list)
    #: Episodes seen per candidate since it entered its current rung.
    episodes: dict[str, int] = field(default_factory=dict)
    #: When each candidate entered its current rung.
    entered: dict[str, float] = field(default_factory=dict)
    #: The last reason each candidate was held, so the same reason is not
    #: logged on every pass. **An unattended loop has to be able to say why
    #: nothing is happening** - a loop that logs only its promotions is
    #: indistinguishable from one that has stopped - but a loop that logs the
    #: same hold every minute buries the pass that matters.
    holding: dict[str, str] = field(default_factory=dict)

    # ──── allocation ────
    def allocated(self) -> float:
        """Total share of the account currently committed."""
        return sum(c.allocation for c in self.candidates.values())

    def headroom(self) -> float:
        return max(0.0, CEILING - self.allocated())

    # ──── persistence ────
    def save(self, path: Path) -> None:
        """Write atomically, because a half-written ladder is unreadable.

        Temp file and rename, the same discipline the tick store uses: a
        process killed mid-write leaves the previous ladder intact rather than
        a truncated one that the next start would refuse or, worse, parse.

        **The gates are written, and that is what makes the loop a loop.**
        They were excluded, and `load` built every candidate without them, so
        a candidate passing at DSR 1.0 came back from its own file reporting
        "no gate has been run" - the words a node discovery had never reached
        reports. Nothing could climb off `DISCOVERED`, whatever was delivered.

        The returns and trial Sharpes are written whole because
        `Gate.deflated` recomputes the DSR from them on every verdict; a gate
        without them falls back to the `passed` flag, which is a weaker test
        substituted silently at the restart.
        """
        payload = {
            "candidates": {
                name: {
                    **{k: v for k, v in asdict(c).items() if k != "rung"},
                    "rung": c.rung.value,
                }
                for name, c in self.candidates.items()
            },
            "log": [asdict(d) for d in self.log[-500:]],
            "episodes": self.episodes,
            "entered": self.entered,
            "holding": self.holding,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        temp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Ladder:
        """Read a ladder, or start an empty one. Never raises on a bad file.

        A corrupt ladder must not stop the desk: it means the loop forgets its
        candidates, which is recoverable, where a node that will not start is
        not. The loss is logged by the caller.
        """
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls()
        ladder = cls(
            episodes=dict(raw.get("episodes") or {}),
            entered=dict(raw.get("entered") or {}),
            # Restored so a restart does not re-log every hold it had already
            # reported. The field was written and never read back, which made
            # the de-duplication the docstring describes last exactly as long
            # as the process did.
            holding=dict(raw.get("holding") or {}),
        )
        for name, data in (raw.get("candidates") or {}).items():
            try:
                ladder.candidates[name] = Candidate(
                    name=data["name"],
                    rung=Rung(data.get("rung", "discovered")),
                    origin=data.get("origin", ""),
                    gates=_gates(data.get("gates")),
                    allocation=float(data.get("allocation", 0.0)),
                    decide_after=int(data.get("decide_after", 200)),
                    history=list(data.get("history") or []),
                )
            except (KeyError, ValueError, TypeError):
                continue  # one unreadable candidate is not a reason to lose the rest
        for entry in raw.get("log") or []:
            try:
                ladder.log.append(Decision(**entry))
            except TypeError:
                continue
        return ladder

    # ──── the loop's own bookkeeping ────
    def record(self, decision: Decision) -> None:
        self.log.append(decision)

    def note_episodes(self, name: str, count: int) -> None:
        self.episodes[name] = self.episodes.get(name, 0) + count

    def enter(self, name: str, now: float | None = None, *, keep_episodes: bool = False) -> None:
        """Mark a candidate as having entered a rung now.

        **Zeroes the episode count**, because the sample is fixed when a rung
        is entered and carrying the previous rung's episodes over would let a
        candidate promote twice on one sample. `keep_episodes` is for a caller
        seeding a ladder from history, which is the one case where the count
        predates the entry.
        """
        if not keep_episodes:
            self.episodes[name] = 0
        self.entered[name] = now if now is not None else time.time()

    def stale(self, name: str, now: float | None = None) -> bool:
        started = self.entered.get(name)
        if started is None:
            return False
        at = now if now is not None else time.time()
        return (at - started) > STALE_DAYS * 86_400


def deliver(
    ladder: Ladder,
    name: str,
    gate: Gate,
    *,
    origin: str = "",
    now: Callable[[], float] | None = None,
) -> Decision:
    """Put a measured gate on the ladder, for `step` to judge on its next pass.

    **The entry point a discovery run had nowhere to deliver to.** The loop
    says candidates "arrive by being written to the ladder file - by a
    discovery run, or by a person", and no function wrote one.

    Delivering evidence is not promoting: a new candidate lands at
    `DISCOVERED` with no allocation, where `_seed` puts a configured leg, and
    climbs only if `step` reads the gate as passing. An existing candidate
    keeps its rung, allocation and episode count, because a fresh backtest is
    evidence for the next decision rather than a re-run of the ones taken.

    A gate replaces one of the same name. `Candidate.blocking` reads every
    gate, so a superseded failure left beside a pass would hold a candidate
    for ever on a number its own harness has withdrawn.
    """
    clock = now or time.time
    at = clock()
    candidate = ladder.candidates.get(name)
    if candidate is None:
        candidate = Candidate(name=name, origin=origin or "delivered by a discovery run")
        ladder.candidates[name] = candidate
        ladder.enter(name, at)
    elif origin and not candidate.origin:
        candidate.origin = origin

    replaced = any(existing.name == gate.name for existing in candidate.gates)
    candidate.gates = [existing for existing in candidate.gates if existing.name != gate.name]
    candidate.gates.append(gate)

    dsr = gate.deflated()
    reading = f"DSR {dsr:.3f}" if dsr is not None else f"passed={gate.passed}"
    candidate.record(
        f"{gate.name}: {reading} on {gate.episodes} episodes, "
        f"chosen from {gate.candidates}, against {gate.control}"
    )
    # Cleared so the next pass states its hold against the new evidence rather
    # than keeping the deduplicated reason the old gate produced.
    ladder.holding.pop(name, None)

    decision = Decision(
        at=at,
        candidate=name,
        action="gated" if replaced else "delivered",
        reason=f"{gate.name} {reading}",
        evidence=(
            f"{gate.criterion} against {gate.control}; {gate.episodes} episodes, "
            f"{gate.candidates} candidates, {len(gate.trial_sharpes)} trial Sharpes"
        ),
    )
    ladder.record(decision)
    return decision


def step(
    ladder: Ladder,
    *,
    allocation: Allocation | None = None,
    now: Callable[[], float] | None = None,
) -> list[Decision]:
    """One pass over every candidate. Returns what it decided.

    Deliberately synchronous and side-effect-free apart from the ladder: the
    node holds the `Trader`, so this decides and the caller acts. A function
    that both decides and places orders cannot be tested without a kernel, and
    this is the function that must never be wrong.
    """
    clock = now or time.time
    at = clock()
    share = allocation or Allocation()
    decided: list[Decision] = []

    for name, candidate in list(ladder.candidates.items()):
        seen = sample_seen(candidate, ladder.episodes.get(name, 0))

        # Stale first: a candidate that has neither passed nor failed in three
        # months is not pending, it is forgotten, and an automated loop
        # accumulates those until they are the whole ladder.
        if candidate.rung in (Rung.DISCOVERED, Rung.BACKTESTED) and ladder.stale(name, at):
            decision = Decision(
                at=at,
                candidate=name,
                action="dropped",
                reason=f"stale at {candidate.rung.value} for over {STALE_DAYS:.0f} days",
                evidence=f"{seen} of {candidate.decide_after} episodes",
            )
            candidate.rung = Rung.REJECTED
            ladder.record(decision)
            decided.append(decision)
            continue

        if candidate.rung in (Rung.REJECTED, Rung.RETIRED):
            continue

        before = candidate.rung
        wanted = share.of(_next_rung(before))
        # **The ceiling is checked before the gates, not after.** A candidate
        # that would pass but does not fit is held rather than promoted and
        # then trimmed, because trimming an allocation after announcing it is
        # how a position ends up sized by a race.
        if wanted > 0.0 and wanted - candidate.allocation > ladder.headroom():
            # Deduped like every other hold. The first version logged this
            # branch unconditionally, so a ladder sitting at its ceiling wrote
            # one line per candidate per pass - the same flood the gate holds
            # were deduped to avoid, in the branch that fires most often.
            why = "at the ceiling"
            if ladder.holding.get(name) != why:
                ladder.holding[name] = why
                decision = Decision(
                    at=at,
                    candidate=name,
                    action="held",
                    reason=why,
                    evidence=(
                        f"wants {wanted:.0%}, {ladder.headroom():.0%} headroom of a "
                        f"{CEILING:.0%} ceiling, {ladder.allocated():.0%} already allocated"
                    ),
                )
                ladder.record(decision)
                decided.append(decision)
            continue

        promote(candidate, share, episodes_seen=seen)
        if candidate.rung is not before:
            ladder.enter(name, at)
            ladder.holding.pop(name, None)
            decision = Decision(
                at=at,
                candidate=name,
                action="promoted",
                reason=f"{before.value} -> {candidate.rung.value}",
                evidence=candidate.history[-1] if candidate.history else "",
            )
            ladder.record(decision)
            decided.append(decision)
            continue

        # Held. Logged once per distinct reason, so the log answers "why is
        # nothing happening" without drowning the entries that matter.
        why = "; ".join(candidate.blocking()) or (f"{seen} of {candidate.decide_after} episodes")
        if ladder.holding.get(name) != why:
            ladder.holding[name] = why
            decision = Decision(at=at, candidate=name, action="held", reason=why)
            ladder.record(decision)
            decided.append(decision)
    return decided


#: The rungs a candidate occupies before it has any allocation. `Allocation.of`
#: is zero at both, so neither can trade or close a position.
BEFORE_CAPITAL = (Rung.DISCOVERED, Rung.BACKTESTED)


def sample_seen(candidate: Candidate, live: int) -> int:
    """The episodes that gate this candidate's next climb.

    **The sample has to be in the currency the rung is decided in.** `step`
    passed the live closed-position count to all four, and the two before
    capital have no allocation - so a candidate there could not trade, could
    not close a position, and could not reach the 200 episodes it needed to
    reach the rung where trading is allowed. The hold read "0 of 200
    episodes", which is true and silent about the deadlock.

    `sample_for` already names the resolution: backtested keeps
    `MIN_EPISODES` because "backtest episodes are cheap" - cheap because they
    are a backtest's. So the rungs before capital are judged on `Gate
    .episodes` and the live rungs on what the account closed.

    The largest gate, not the sum: two gates on one backtest are two readings
    of one sample, and adding them would let a second opinion stand in for a
    longer record.
    """
    if candidate.rung in BEFORE_CAPITAL:
        return max((gate.episodes for gate in candidate.gates), default=0)
    return live


def _next_rung(rung: Rung) -> Rung:
    return {
        Rung.DISCOVERED: Rung.BACKTESTED,
        Rung.BACKTESTED: Rung.SMALL,
        Rung.SMALL: Rung.FULL,
    }.get(rung, rung)


def take_off(
    ladder: Ladder,
    name: str,
    reason: Retirement,
    *,
    evidence: str = "",
    now: Callable[[], float] | None = None,
) -> tuple[Decision, str]:
    """Retire a candidate and say what the node must do about it."""
    clock = now or time.time
    candidate = ladder.candidates.get(name)
    if candidate is None:
        decision = Decision(
            at=clock(), candidate=name, action="unknown", reason="not on the ladder"
        )
        ladder.record(decision)
        return decision, "none"
    candidate, action = retire(candidate, reason, evidence=evidence)
    decision = Decision(
        at=clock(),
        candidate=name,
        action="retired" if candidate.rung is Rung.RETIRED else "retirement refused",
        reason=reason.value,
        evidence=candidate.history[-1] if candidate.history else evidence,
    )
    ladder.record(decision)
    return decision, action


def put_back(ladder: Ladder, name: str, *, now: Callable[[], float] | None = None) -> Decision:
    """Return a retired candidate to the gate, with its gates cleared."""
    clock = now or time.time
    candidate = ladder.candidates.get(name)
    at = clock()
    if candidate is None:
        decision = Decision(at=at, candidate=name, action="unknown", reason="not on the ladder")
        ladder.record(decision)
        return decision
    revive(candidate)
    ladder.enter(name, at)
    decision = Decision(
        at=at,
        candidate=name,
        action="revived",
        reason="back to the gate, gates cleared",
        evidence="must pass again on the data that refuted it",
    )
    ladder.record(decision)
    return decision


def report(ladder: Ladder) -> list[str]:
    """What a person reads when they look in on an unattended loop."""
    by_rung: dict[str, int] = {}
    for candidate in ladder.candidates.values():
        by_rung[candidate.rung.value] = by_rung.get(candidate.rung.value, 0) + 1
    out = [
        f"{len(ladder.candidates)} candidates: "
        + (", ".join(f"{n} {r}" for r, n in sorted(by_rung.items())) or "none"),
        f"allocated {ladder.allocated():.0%} of a {CEILING:.0%} ceiling "
        f"({ladder.headroom():.0%} headroom)",
    ]
    out.extend(d.line() for d in ladder.log[-8:])
    return out


def pending(ladder: Ladder) -> list[tuple[str, list[str]]]:
    """Why each live-eligible candidate is not climbing.

    The question an unattended loop has to be able to answer about itself. A
    loop that cannot say why nothing is happening is indistinguishable from
    one that has stopped.
    """
    out = []
    for name, candidate in ladder.candidates.items():
        if candidate.rung in (Rung.REJECTED, Rung.RETIRED):
            continue
        blocking = candidate.blocking()
        seen = ladder.episodes.get(name, 0)
        if seen < candidate.decide_after:
            blocking.append(f"{seen} of {candidate.decide_after} episodes")
        if blocking:
            out.append((name, blocking))
    return out
