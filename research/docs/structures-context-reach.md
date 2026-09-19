# Structures Context Reach

Rationale moved out of `till_infinity/structures/context/reach.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Reach.observe`

        Both quantities are distances and arrive signed by which side of the
        level they were on, which is a fact about the approach rather than
        about how far price went.

        **Zero is an observation, not a missing one**, and the first version of
        this discarded it. Many touches resolve with no adverse excursion at
        all - the median resolves in nineteen seconds - and a trade that never
        threatened its stop is the most informative thing a stop estimator can
        see. Dropping those leaves a sample of only the touches that went
        wrong, and a quantile of that puts the stop far wider than the
        instrument warrants. The same holds for depth: a touch that reached a
        level without penetrating it is a real thing price did.

        A field that is genuinely absent is the caller's business, and the
        caller does not call.


## `Reaches.stop_at`

        `share` of past excursions fall short of this, so at 0.8 roughly one
        trade in five is stopped by something the level has done before - which
        is a choice about how much noise to pay for, made where it can be seen.

        **`risk_vol` is added, not maxed against.** The level model's own risk
        distance describes the structure; the excursion quantile describes what
        price has actually done to trades there. They are different evidence
        about the same question and a stop that clears both is not the larger
        of the two, it is the sum - which is also why this returns a distance
        rather than a stop price, and lets the caller decide what to anchor it
        to.


