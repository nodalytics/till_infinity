"""When a model stops working, said by the system rather than noticed by a person.

Every model-decay finding in `research/` was found the same way: somebody ran a
measurement and read the answer. `breaking.py` is badly calibrated - log loss
0.3624 against 0.2493 for a constant - and that was a person looking.
`calibration.Platt` was added to correct it and publishes `improvement` so the
record can say whether it helped, which is a person looking. `baseline.Bench`
scores every model against its controls on every observation, which is the
closest thing here to continuous supervision and is still **a comparison rather
than an alarm**: it says which model is better today, not that one of them
stopped working on Tuesday.

`river.drift.DDM` and `EDDM` are the missing piece, and what makes them
different from everything in `drift.py` is that they watch a **model's error
stream** rather than a price. They take a sequence of 1s and 0s - wrong, right -
and say when the rate of wrongness has changed by more than sampling explains.

## Both, because they fail at opposite things

**DDM** models errors as a binomial and alarms when the error rate rises past a
confidence bound on its own best-ever rate. It is sharp on a **step**: a model
that breaks.

**EDDM** watches the *distance between* errors rather than their rate, which is
what catches a **gradual** slide - and gradual is what decay here looks like. A
model whose edge erodes over a month never has a bad enough day to trip DDM.

Running both and recording which fires is cheaper than choosing, and the choice
is not obvious enough to make from a docstring.

## Warning before drift, and why both are kept

Each detector has two levels: a **warning** zone where the error rate has moved
but not conclusively, and a **drift** alarm. The warning is the useful one for a
desk - it arrives earlier and costs nothing to observe - so both are exposed
rather than only the alarm.

## Both fire on a stream with no change in it, and that is the headline

Run against the null this repository insists on - a **stationary** error stream,
where the right number of alarms is zero - over 3,000 observations, averaged
across five seeds:

| true error rate | DDM alarms | EDDM alarms |
| --- | --- | --- |
| 5% | 1.0 | 3.2 |
| 10% | 1.0 | 5.4 |
| 20% | 0.6 | 8.8 |
| 35% | 0.6 | 9.4 |
| 50% | 0.4 | **11.2** |

**EDDM alarms roughly once every 270 to 940 observations on a model that has
not changed**, and the rate climbs with the error rate rather than the drift.
DDM is far better and still not zero.

So neither is usable as a bare alarm, and "EDDM fired" means nothing on its own.
What is informative is the count **against the stationary baseline for that
model's error rate**, which is why `Reading` carries `error_rate` beside the
counts: an alarm at 50% wrong has to clear a bar five times higher than one at
5%, and a reader who does not know that will act on noise.

That is the same shape as every other lesson here - `slowing` at AUC 0.5237 was
only worth keeping because it was uncorrelated, and 84-88% accuracy was
reproducing a definition. A detector is worth what it beats the null by.

## This decides nothing

Deliberately, and for the reason `drift.py` gives at length about its own second
detector: a false alarm here would discount a model that was working - and the
table above says false alarms are not hypothetical. So this records, and
something reads it only once the record says it is worth reading.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from river import drift as river_drift

from ...logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class Reading:
    """What the two detectors say about one model right now."""

    name: str
    seen: int = 0
    #: Observations since each last raised an alarm. The number a reader wants
    #: first: "how long has this been fine".
    since_ddm: int = 0
    since_eddm: int = 0
    ddm_warning: bool = False
    eddm_warning: bool = False
    ddm_drift: bool = False
    eddm_drift: bool = False
    #: How many times each has fired over the model's life.
    ddm_alarms: int = 0
    eddm_alarms: int = 0
    #: The running error rate, so an alarm can be read against a level rather
    #: than trusted on its own.
    error_rate: float = 0.0

    @property
    def unhappy(self) -> bool:
        """Either detector past a warning. The cheap thing for a log line."""
        return self.ddm_warning or self.eddm_warning or self.ddm_drift or self.eddm_drift

    def to_dict(self) -> dict[str, float]:
        return {
            "seen": float(self.seen),
            "error_rate": round(self.error_rate, 4),
            "ddm_alarms": float(self.ddm_alarms),
            "eddm_alarms": float(self.eddm_alarms),
            "since_ddm": float(self.since_ddm),
            "since_eddm": float(self.since_eddm),
        }


@dataclass(slots=True)
class Decay:
    """Watches one or more models' error streams and says when one changed.

    Keyed by a name the caller chooses, so several models can be watched by one
    instance and the log line says which.
    """

    #: Decayed error rate, matching `online`'s horizon so the two are readable
    #: against each other.
    memory: float = 2000.0
    _ddm: dict[str, object] = field(default_factory=dict, repr=False)
    _eddm: dict[str, object] = field(default_factory=dict, repr=False)
    _state: dict[str, Reading] = field(default_factory=dict)

    def observe(self, name: str, wrong: bool) -> Reading:
        """One prediction's outcome. `wrong` is True when the model missed.

        Returns the reading rather than a bare alarm, because "it fired" is not
        actionable without the error rate it fired against - a detector alarming
        on a model that is right 90% of the time is saying something different
        from one alarming at 51%.
        """
        got = self._state.get(name)
        if got is None:
            got = self._state[name] = Reading(name=name)
            self._ddm[name] = river_drift.binary.DDM()
            self._eddm[name] = river_drift.binary.EDDM()

        got.seen += 1
        keep = max(0.0, 1.0 - 1.0 / self.memory)
        got.error_rate = got.error_rate * keep + (1.0 - keep) * (1.0 if wrong else 0.0)
        got.since_ddm += 1
        got.since_eddm += 1

        # Wrapped for the reason `drift.py` wraps its second opinion: a watcher
        # that decides nothing must not be able to stop the thing it watches.
        for which, book, warn_at, drift_at in (
            ("ddm", self._ddm, "ddm_warning", "ddm_drift"),
            ("eddm", self._eddm, "eddm_warning", "eddm_drift"),
        ):
            detector = book.get(name)
            if detector is None:
                continue
            try:
                detector.update(1 if wrong else 0)
                warned = bool(getattr(detector, "warning_detected", False))
                drifted = bool(getattr(detector, "drift_detected", False))
            except Exception as exc:
                log.debug("decay: %s failed on %s: %s", which, name, exc)
                continue
            setattr(got, warn_at, warned)
            setattr(got, drift_at, drifted)
            if drifted:
                if which == "ddm":
                    got.ddm_alarms += 1
                    got.since_ddm = 0
                else:
                    got.eddm_alarms += 1
                    got.since_eddm = 0
                log.info(
                    "decay: %s says %s changed - error rate %.1f%% over %d observations",
                    which.upper(),
                    name,
                    got.error_rate * 100,
                    got.seen,
                )
        return got

    def reading(self, name: str) -> Reading | None:
        return self._state.get(name)

    def report(self) -> str:
        """One line per watched model, for the save log.

        Says the error rate beside the alarm count, because an alarm on a model
        that is right nine times in ten is a different event from one at
        break-even and a bare count cannot tell them apart.
        """
        if not self._state:
            return "no model error streams watched yet"
        rows = []
        for name, got in sorted(self._state.items()):
            flag = " **" if got.unhappy else ""
            rows.append(
                f"  {name}: {got.error_rate:.1%} wrong over {got.seen}, "
                f"DDM {got.ddm_alarms} / EDDM {got.eddm_alarms} alarm(s){flag}"
            )
        return "\n".join(rows)
