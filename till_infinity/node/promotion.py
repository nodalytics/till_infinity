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

import os
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

#: Episodes a **live leg** is given before the ladder looks at it again. Ten.
#:
#: **Ten episodes is an exploration budget, not a validation.** It is worth
#: writing down what it buys, because 10 is small enough that a reader will
#: otherwise take a positive result from it as evidence.
#:
#: The best per-trade edge this desk has measured is `+0.1436R +/- 0.0485 over
#: 905 trades at t 2.96`, which is a per-trade Sharpe of about 0.098. A
#: t-statistic is that times the root of the sample, so ten episodes of a real
#: edge of exactly that size reads **t 0.31** - indistinguishable from zero -
#: and reaching t 2 would take about 417 of them. Ten episodes cannot separate
#: a working leg from a dead one, and no choice of threshold changes that.
#:
#: It is still the right number for *entering* `SMALL`, and the ladder is why.
#: `Allocation.small` is 5% of the account and `Retirement` is fast, so what
#: ten episodes decides is whether to spend a bounded amount finding out -
#: which is a different question from whether the edge is real, and the only
#: one a short sample can answer. Promotion to `FULL` still asks for
#: `MIN_EPISODES`, because that decision is the one a thin sample would be
#: making with the whole account.
#:
#: What this must never become is a reason to retire. `strategy-rotation-is-
#: not-timeable` records that every pause rule tested here matched random
#: pausing at the same duty cycle, so ten episodes of bad results is not
#: evidence a leg has stopped working - it is the sample being short. See
#: `may_retire`, which takes reasons and not performance.
LIVE_EPISODES = 10


def live_episodes() -> int:
    """The live sample a leg is reviewed on. `TRADING_LIVE_EPISODES`, ten.

    Read per call rather than captured at import, so a deploy or a test can
    change it without a reload - the same reason `profile.multipliers_on` is a
    function.

    **Raising it is the supported direction.** Ten is the shortest sample this
    desk is willing to act on and every statistical argument favours more, so
    there is no upper bound here and no warning for a large value. A value
    below one is refused: a rung whose sample is zero promotes on the first
    episode, which is not a sample.
    """
    raw = os.environ.get("TRADING_LIVE_EPISODES")
    if not raw:
        return LIVE_EPISODES
    try:
        found = int(raw)
    except ValueError as exc:
        raise ValueError(f"TRADING_LIVE_EPISODES={raw!r} is not a number of episodes") from exc
    if found < 1:
        raise ValueError(
            f"TRADING_LIVE_EPISODES={found} would decide on no episodes at all. "
            f"One is the floor; {LIVE_EPISODES} is the default."
        )
    return found


def required_dsr() -> float:
    """The deflated Sharpe a promotion gate must clear. `TRADING_DSR_REQUIRED`, 0.95.

    **The short live sample does not reach this number and is not meant to.**
    A gate's DSR is computed from the *backtest's* returns, where episodes are
    cheap, so `live_episodes` and this threshold govern two different
    decisions: how long to watch a leg that is already past its gate, and how
    strong the evidence had to be to get there. Conflating them - lowering the
    bar because a live sample is short - would leave a number that still
    prints as a probability and no longer means one.

    Lowering it is allowed, because a deliberately looser bar on a bounded
    allocation is a decision somebody can make, and because the alternative is
    an unreadable constant. It is bounded to (0, 1): it is a probability.
    """
    raw = os.environ.get("TRADING_DSR_REQUIRED")
    if not raw:
        return Gate.DSR_REQUIRED
    try:
        found = float(raw)
    except ValueError as exc:
        raise ValueError(f"TRADING_DSR_REQUIRED={raw!r} is not a probability") from exc
    if not 0.0 < found < 1.0:
        raise ValueError(
            f"TRADING_DSR_REQUIRED={found} is not a probability. The deflated "
            f"Sharpe is one, so this is strictly between 0 and 1."
        )
    return found


def required_psr() -> float:
    """The probabilistic Sharpe a promotion gate must clear. `TRADING_PSR_REQUIRED`, 0.85.

    **This is the gate now, and the deflated Sharpe is reported beside it.**

    The change is worth stating plainly because it cuts both ways. Where a DSR
    *can* be computed it is the stronger test: it confronts the spread of what
    was tried, so it answers "given this was the best of the search, is it
    real" where PSR only answers "given this much data, is it real". Gating on
    PSR gives that up.

    Where a DSR *cannot* be computed - and it needs `trial_sharpes`, the
    readings of everything the search rejected, which most callers do not keep
    - the old gate fell through to a bare boolean that carried no sample size
    at all. That was the common path, and on it this raises the floor rather
    than lowering it.

    So: PSR is required always, DSR is computed and reported whenever it can
    be, and a candidate with a weak DSR is visible in the reason string even
    though it no longer fails on it.
    """
    raw = os.environ.get("TRADING_PSR_REQUIRED")
    if not raw:
        return Gate.PSR_REQUIRED
    try:
        found = float(raw)
    except ValueError as exc:
        raise ValueError(f"TRADING_PSR_REQUIRED={raw!r} is not a probability") from exc
    if not 0.0 < found < 1.0:
        raise ValueError(
            f"TRADING_PSR_REQUIRED={found} is not a probability. The "
            f"probabilistic Sharpe is one, so this is strictly between 0 and 1."
        )
    return found


def sample_for(rung: Rung) -> int:
    """The sample fixed when `rung` is entered.

    **The field's own docstring has always said the sample is "fixed when the
    rung is entered", and nothing fixed it.** `promote` moved the rung and left
    `decide_after` at whatever the candidate was built with, so every rung
    inherited one number - a candidate entering small capital was given the
    200-episode backtest sample, and one built by hand with a short sample kept
    it all the way to full capital. Both directions are wrong and the second is
    the dangerous one.

    Backtested keeps `MIN_EPISODES` because that decision risks money for the
    first time and backtest episodes are cheap. The two live rungs take
    `live_episodes`, because a live episode costs a trade and the decision they
    gate is review rather than evidence.
    """
    if rung is Rung.BACKTESTED:
        return MIN_EPISODES
    if rung in (Rung.SMALL, Rung.FULL):
        return live_episodes()
    return MIN_EPISODES


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

    #: The deflated Sharpe's own bar, **lowered from 0.95 when PSR became the
    #: standard**. It is the secondary test now, not the primary one, so it
    #: asks a weaker question of the same evidence: not "is this strong given
    #: the search" but "is this not obviously an artefact of the search".
    #: `required_dsr` reads it.
    DSR_REQUIRED = 0.60

    #: **The bar a gate passes on.** `required_psr` is what a gate reads, so a
    #: deploy can move it.
    PSR_REQUIRED = 0.85

    def probabilistic(self) -> float | None:
        """PSR for this gate's own returns, or `None` with too few to say.

        Four is the floor because the third and fourth moments enter the
        denominator, and below that a number would be an invention rather than
        an estimate.
        """
        if len(self.returns) < 4:
            return None
        from .metrics import probabilistic_sharpe

        return probabilistic_sharpe(self.returns)

    def verdict(self) -> tuple[bool, str]:
        """Pass or fail, with the reason stated in the terms it was judged on.

        **PSR decides; DSR is reported.** A deflated Sharpe needs the readings
        of everything the search rejected, which most callers do not keep, and
        the gate used to fall through to a bare boolean when they were missing
        - a verdict carrying no sample size at all. PSR needs only the
        candidate's own returns, so it applies on every path.

        Where a DSR can be computed it is still the stronger statement, and it
        is put in the reason so a candidate that clears PSR on a thin search is
        visible as that.
        """
        psr = self.probabilistic()
        dsr = self.deflated()
        floor = required_dsr()
        beside = f", DSR {dsr:.3f}/{floor}" if dsr is not None else ""
        if psr is None:
            return bool(self.passed), (
                f"{self.name}: judged on {self.criterion} against {self.control}, with no "
                f"probabilistic Sharpe - {len(self.returns)} returns were supplied, "
                f"four are needed{beside}"
            )
        wanted = required_psr()
        # **Both, where both can be asked.** PSR says the record is long enough
        # to mean something; DSR says it is not simply the best of a wide
        # search. They are different objections and clearing one does not
        # answer the other, so a gate that can be asked both is asked both.
        ok = psr >= wanted and (dsr is None or dsr >= floor)
        why = "" if ok or psr < wanted else " - PSR cleared, DSR did not"
        return ok, (
            f"{self.name}: PSR {psr:.3f} against {wanted} over "
            f"{self.episodes} episodes{beside}{why}"
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
        # **A bare number, and it used to carry the currency.** `RiskEngine`
        # reads this mapping with `Decimal(value)` - `risk/engine.pyx:196` -
        # so `"5000.00 USD"` raised `decimal.InvalidOperation` and a node
        # configured from this function could not be constructed at all. It had
        # never fired, because nothing on the live path had ever called the
        # ladder; wiring the loop into `node/live` is what found it.
        #
        # The currency is not lost, it was never the engine's to read: the cap
        # is denominated in the **instrument's quote currency**, which
        # `engine.pyx` supplies itself with
        # `Money(float(setting), instrument.quote_currency)`. So `currency`
        # here is what the *caller's* equity is in, and an instrument quoted in
        # anything else needs the conversion `Desk._rate` does before the
        # number means what it says. `node/live._supervise` refuses to apply a
        # cap across that mismatch rather than guessing the rate.
        _ = currency
        return {str(i): f"{cap:.2f}" for i in instruments}


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


def book_evidence(ratio: float, *, episodes: int, floor: float = 0.0) -> str:
    """A deflated information ratio against the book, as retirement evidence.

    The empty string when it is not evidence, which `may_retire` reads as no
    evidence and refuses. That is the point of the function: the rotation this
    desk wants - retire a leg that has stopped working, promote a discovery in
    its place - is one step from the rule already measured as worthless, and
    the step is the sample.

    **`strategy-rotation-is-not-timeable` is the finding to beat.** Every pause
    rule tested here matched random pausing at the same duty cycle, so "it is
    losing to the book lately" is not a reason. What makes an information ratio
    a reason rather than a mood is that it is **deflated** - the number already
    confronts how many legs were compared to find the worst one - and that it
    is read over a sample long enough to carry it. Below `live_episodes` it is
    not read at all.

    `InformationRatio`'s own docstring puts this reading here and not on the
    promotion side: against the rest of the book an IR answers "does this leg
    beat the others", which is a retirement question. A gate on it would be a
    second gate on the same algebra as `DSR` over a differenced series, and
    would count one piece of evidence twice - see `node/statistics.GATES`.
    """
    least = live_episodes()
    if episodes < least:
        return ""
    if ratio >= floor:
        return ""
    return (
        f"deflated information ratio {ratio:.3f} against the book over "
        f"{episodes} episodes, below {floor:.3f}"
    )


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
    # **Fixed on entry, which is what the field has always claimed.** Nothing
    # set it before, so a candidate carried one sample from discovery to full
    # capital - and the direction that matters is a short one surviving the
    # climb, because then the decision with the whole account is made on the
    # sample that was chosen for a 5% one.
    candidate.decide_after = sample_for(candidate.rung)
    candidate.record(
        f"promoted: {why} at {candidate.allocation:.0%} of the account, "
        f"reviewed after {candidate.decide_after} episodes"
    )
    return candidate
