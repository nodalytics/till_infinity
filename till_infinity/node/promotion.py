"""The ladder a candidate climbs, and what it has to pass at each rung.

    discovery -> backtest -> small capital -> full capital

**The ladder is not the hard part; the gates are.** A search that generates
candidates and a threshold that promotes them will promote noise at the rate
of the threshold, and this desk has measured that happening: a block of eight
found structure in 27 of 36 *placebo* pools. So every gate here carries the
number of candidates it was selected from, and a criterion fixed before the
run rather than read off it.

Three findings shape the rules below, all of them ours and all of them
measured rather than reasoned:

- **`strategy-rotation-is-not-timeable`**: every pause rule we tested matched
  random pausing at the same duty cycle. So a promotion may never be decided
  on recent performance - that is the rule we already know does not work.
- **`the-placebo-arm-selects-the-null`**: a null that the placebo arm also
  passes is not a null. Each gate therefore names what it was compared
  against, and a candidate whose placebo passes is rejected, not promoted.
- **`overlapping-outcome-windows-leak`**: a short skip rule with a long
  forward window gave direction AUC 0.79 that collapsed to 0.51. Episode
  count, not bar count, is what a gate counts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class Rung(StrEnum):
    """Where a candidate is. Order matters: nothing skips a rung."""

    DISCOVERED = "discovered"
    BACKTESTED = "backtested"
    SMALL = "small"
    FULL = "full"
    REJECTED = "rejected"
    #: Was live, is not, and could be again. **Retired, not deleted** - a
    #: retired candidate returns to `BACKTESTED` rather than to nothing, so
    #: reviving it means passing the gate again rather than arguing from
    #: memory.
    RETIRED = "retired"


class Retirement(StrEnum):
    """Why a strategy came off a live node.

    **None of these is "it has been losing lately", and that is deliberate.**
    `strategy-rotation-is-not-timeable` is measured on this desk: every pause
    rule we tested matched random pausing at the same duty cycle. Retiring on
    recent performance is the one rule already shown to be worth nothing, so
    each reason below is either a *measurement* that can be rerun or a *limit*
    that was breached.
    """

    #: A null test it previously passed now fails on newer data. A
    #: measurement, repeatable, and the strongest reason there is.
    REFUTED = "refuted"
    #: `minimum_track_record` exceeds the history that will ever exist for it.
    #: Not a failure - unmeasurable, which is a cheaper decision made early.
    UNMEASURABLE = "unmeasurable"
    #: The cost it needs has outgrown the edge it has. Measurable and not a
    #: timing call: `exotic-spreads-are-a-whole-bar-range` priced several
    #: ideas out of existence this way, and the spread column is in *points*,
    #: not price - reading it as price made EURUSD look like a 476% round trip.
    COST = "cost"
    #: A risk limit was breached. The engine's decision, not a view: Nautilus
    #: has `TradingState.HALTED` and `REDUCING` for exactly this.
    LIMIT = "limit"
    #: Something better answers the same question. The only comparative
    #: reason, and it needs the replacement to have passed its own gate.
    SUPERSEDED = "superseded"
    #: A person decided. Recorded as such rather than dressed as a measurement.
    MANUAL = "manual"


#: Years of history a backtest gate reads by default.
#:
#: Two is the default asked for, and it is worth knowing what two years buys
#: on this desk: on 1m bars it is a few hundred thousand bars but far fewer
#: *independent episodes*, and episodes are the sample size. A strategy that
#: trades twice a week has about two hundred of them in two years, which is
#: thin for anything whose effect is a fraction of a spread.
DEFAULT_YEARS = 2.0

#: Minimum independent episodes before a backtest result means anything.
#:
#: Not a bar count. `overlapping-outcome-windows-leak` is the reason: a long
#: forward window over a short skip rule makes one event look like many, and
#: the inflated version of that study read 0.79 where the truth was 0.51.
MIN_EPISODES = 200


@dataclass(frozen=True, slots=True)
class Gate:
    """One pre-registered test, with what it was measured against.

    **`candidates` is not bookkeeping.** It is how many things were tried to
    find this one, and a threshold that ignores it is not a threshold. Twenty
    candidates at p < 0.05 produce one pass from noise alone.
    """

    name: str
    #: What the candidate must beat, stated before the run.
    criterion: str
    #: What it was compared against: a shuffled twin, a distance-matched
    #: placebo, a walk through the same detector. Never "nothing".
    control: str
    #: How many candidates this one was selected from.
    candidates: int
    #: Independent episodes behind the number.
    episodes: int
    passed: bool | None = None
    reading: float | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if not self.control:
            raise ValueError(
                f"gate {self.name!r} names no control - a reading with nothing to "
                f"beat is not a gate. See `null-structure-claims-on-the-same-detector`."
            )
        if self.candidates < 1:
            raise ValueError(f"gate {self.name!r} must say how many candidates it chose from")

    #: The Sharpes of every candidate the search produced, including the
    #: losers. Required for the deflation, and the reason it is the *readings*
    #: rather than a count: `Var(SR_trials)` only exists if the search kept
    #: what it rejected.
    trial_sharpes: tuple[float, ...] = ()
    #: The candidate's own per-period returns, for the Sharpe being deflated.
    returns: tuple[float, ...] = ()

    def deflated(self) -> float | None:
        """DSR for this gate, or `None` if it was not given what it needs.

        **This replaced a Bonferroni division.** `0.05 / candidates` confronts
        the number of trials and nothing else; the deflated Sharpe confronts
        the *spread* of what was tried, the length of the record, and the
        non-normality of the returns - and the third is the one that matters
        most here, because traded markets on this desk run kurtosis between 20
        and 74 against a Gaussian's 3.
        """
        if len(self.trial_sharpes) < 2 or len(self.returns) < 4:
            return None
        from .metrics import deflated_sharpe

        return deflated_sharpe(self.returns, self.trial_sharpes)

    @property
    def underpowered(self) -> bool:
        return self.episodes < MIN_EPISODES

    #: A gate passes on the deflated Sharpe, where one can be computed.
    DSR_REQUIRED = 0.95

    def verdict(self) -> tuple[bool, str]:
        """Pass or fail, with the reason stated in the terms it was judged on."""
        dsr = self.deflated()
        if dsr is None:
            return bool(self.passed), (
                f"{self.name}: judged on {self.criterion} against {self.control}, with no "
                f"deflated Sharpe - {len(self.trial_sharpes)} trial Sharpes and "
                f"{len(self.returns)} returns were supplied"
            )
        ok = dsr >= self.DSR_REQUIRED
        return ok, (
            f"{self.name}: DSR {dsr:.3f} against {self.DSR_REQUIRED} over "
            f"{len(self.trial_sharpes)} trials and {self.episodes} episodes"
        )


@dataclass(slots=True)
class Candidate:
    """A strategy on its way up, or out."""

    name: str
    rung: Rung = Rung.DISCOVERED
    #: How it was found: which harness, which search, which model.
    origin: str = ""
    gates: list[Gate] = field(default_factory=list)
    #: Fraction of the account this rung allows. See `Allocation`.
    allocation: float = 0.0
    #: Episodes required before the *next* decision, fixed when the rung is
    #: entered. Reading a live run until it looks good is not a test.
    decide_after: int = MIN_EPISODES
    history: list[str] = field(default_factory=list)

    def record(self, line: str) -> None:
        self.history.append(line)

    def blocking(self) -> list[str]:
        """Why this candidate cannot climb, in the order that matters."""
        reasons = []
        if not self.gates:
            reasons.append("no gate has been run")
        for gate in self.gates:
            if gate.passed is None and gate.deflated() is None:
                reasons.append(f"{gate.name}: not yet measured")
                continue
            ok, why = gate.verdict()
            if not ok:
                reasons.append(why)
            elif gate.underpowered:
                reasons.append(
                    f"{gate.name}: passed on {gate.episodes} episodes, under {MIN_EPISODES}"
                )
        return reasons


@dataclass(frozen=True, slots=True)
class Allocation:
    """How much of the account each rung may use.

    **Small capital is a bounded loss, not a smaller test.** At a fraction of
    size a strategy's P&L is a fraction too, so the *time* to tell edge from
    noise is unchanged - `decide_after` is in episodes for that reason. What
    small capital buys is a cap on being wrong, and nothing else.

    **Enforced by the engine, not by our arithmetic.** `limits()` produces the
    `max_notional_per_order` mapping Nautilus's risk engine already takes, so
    the cap is applied where every order passes rather than wherever we
    remembered to multiply. A limit we apply ourselves is a limit a new code
    path can miss.
    """

    small: float = 0.05
    full: float = 1.0

    def of(self, rung: Rung) -> float:
        return {Rung.SMALL: self.small, Rung.FULL: self.full}.get(rung, 0.0)

    def limits(
        self, rung: Rung, equity: float, instruments: Sequence[str], currency: str = "USD"
    ) -> dict[str, str]:
        """`max_notional_per_order` for `RiskEngineConfig`, at this rung.

        Returns an empty mapping for a rung that may not trade, which the risk
        engine reads as no permission rather than no limit - so a candidate
        off the ladder cannot place an order by default.
        """
        share = self.of(rung)
        if share <= 0.0:
            return {}
        cap = equity * share
        return {str(i): f"{cap:.2f} {currency}" for i in instruments}


def may_promote(candidate: Candidate, *, episodes_seen: int) -> tuple[bool, str]:
    """Whether a candidate may climb one rung, and why not if it may not.

    **Never on recent performance.** `strategy-rotation-is-not-timeable`
    records that every pause rule we tested matched random pausing at the same
    duty cycle, so "it has been doing well" is the one criterion we have
    already measured as worthless. What is allowed is a pre-registered gate
    over a pre-registered sample.
    """
    blocking = candidate.blocking()
    if blocking:
        return False, "; ".join(blocking)
    if episodes_seen < candidate.decide_after:
        return False, (
            f"{episodes_seen} of {candidate.decide_after} episodes - the sample was "
            f"fixed when this rung was entered, and stopping early is choosing"
        )
    nxt = {Rung.DISCOVERED: Rung.BACKTESTED, Rung.BACKTESTED: Rung.SMALL, Rung.SMALL: Rung.FULL}
    if candidate.rung not in nxt:
        return False, f"{candidate.rung.value} is not a rung that climbs"
    return True, f"{candidate.rung.value} -> {nxt[candidate.rung].value}"


def may_retire(candidate: Candidate, reason: Retirement, *, evidence: str = "") -> tuple[bool, str]:
    """Whether this reason is sufficient to take a strategy off a live node.

    Every reason but `MANUAL` needs evidence, because every one of them is a
    claim that can be checked - and a retirement recorded without its evidence
    cannot be reviewed when the same candidate is proposed again.
    """
    if candidate.rung not in (Rung.SMALL, Rung.FULL):
        return False, f"{candidate.name} is not live - it is at {candidate.rung.value}"
    if reason is Retirement.MANUAL:
        return True, f"manual: {evidence or 'no reason given'}"
    if not evidence:
        return False, (
            f"{reason.value} is a claim and needs its evidence - a refutation without "
            f"the test, or a cost without the measurement, cannot be reviewed later"
        )
    if reason is Retirement.SUPERSEDED and "gate" not in evidence.lower():
        return False, (
            "superseded needs the replacement's own gate result - otherwise it is a "
            "preference, and preferring the newer thing is how rotation gets timed"
        )
    return True, f"{reason.value}: {evidence}"


def retire(
    candidate: Candidate, reason: Retirement, *, evidence: str = ""
) -> tuple[Candidate, str]:
    """Take a strategy off the ladder, and say how to take it off the node.

    The *mechanism* is Nautilus's and this does not reimplement it: a wind-down
    is `TradingState.REDUCING` so nothing new opens while positions close, then
    `Trader.stop_strategy`, then `remove_strategy`. A breached limit skips
    straight to `HALTED`, because that is what a breach means.

    Returns the candidate and the action to take, rather than acting: the node
    holds the `Trader`, and a function that both decides and executes cannot be
    tested without one.
    """
    ok, why = may_retire(candidate, reason, evidence=evidence)
    if not ok:
        candidate.record(f"retirement refused: {why}")
        return candidate, "none"
    was = candidate.rung
    candidate.rung = Rung.RETIRED
    candidate.allocation = 0.0
    candidate.record(f"retired from {was.value}: {why}")
    action = "HALTED" if reason is Retirement.LIMIT else "REDUCING"
    return candidate, action


def revive(candidate: Candidate) -> Candidate:
    """Put a retired candidate back on the ladder at the backtest rung.

    **Not back where it was.** Retired, not deleted - but a strategy that
    comes back has to pass the gate again on the data that refuted it, which
    is the difference between reviving an idea and arguing from memory.
    """
    if candidate.rung is not Rung.RETIRED:
        candidate.record(f"revival refused: {candidate.name} is at {candidate.rung.value}")
        return candidate
    candidate.rung = Rung.BACKTESTED
    candidate.allocation = 0.0
    candidate.gates = []
    candidate.record("revived to backtested; gates cleared, must pass again")
    return candidate


def promote(candidate: Candidate, allocation: Allocation, *, episodes_seen: int) -> Candidate:
    """Climb one rung, or record why not. Promotion is never silent."""
    ok, why = may_promote(candidate, episodes_seen=episodes_seen)
    if not ok:
        candidate.record(f"held at {candidate.rung.value}: {why}")
        return candidate
    nxt = {Rung.DISCOVERED: Rung.BACKTESTED, Rung.BACKTESTED: Rung.SMALL, Rung.SMALL: Rung.FULL}
    candidate.rung = nxt[candidate.rung]
    candidate.allocation = allocation.of(candidate.rung)
    candidate.record(f"promoted: {why} at {candidate.allocation:.0%} of the account")
    return candidate
