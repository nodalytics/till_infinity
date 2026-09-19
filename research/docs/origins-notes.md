# Origins Notes

Rationale moved out of `till_infinity/structures/drawing/origins.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `change_in`

    `extremes_in` answers "where was the highest close"; this answers "where
    did the character of the move change", and they are different questions
    about the same minutes. An origin is defined as an extreme, so the extreme
    is what places it - but two estimators built from different statistics
    landing on the same price is worth more than either alone, and
    `CONFIRM_VOL` carries what that agreement is measured to be worth.

    Both directions, because **the impulse has not happened yet.** This runs
    when the bar closes, which is the only moment its minutes are certainly
    still in the window; whether the move that follows is a drop or a rally is
    not knowable for hours. So the fall's change point and the rally's are
    both computed and `refine` takes the one that turned out to matter.

    Returned in `(down, up)` order, matching `extremes_in`'s `(low, high)`:
    the fall's change point is the price a drop began from and sits with the
    high, the rally's with the low.

    **No volatility unit is needed and none is taken.** The statistic scales
    as `1/unit**2` under a change of unit, uniformly across every candidate,
    so the argmax - the only thing read here - is unchanged. The threshold is
    what a unit is for, and this never tests one: it asks where the best
    changepoint is, not whether it is good enough to announce.

    None on the same terms as `extremes_in`: partial cover is not cover.


## `refine`

    **Estimator F of the localization specification, and the one that won.**
    Measured over 406 events on 8 instruments (`research/localising.md`),
    locating the transition at 1m halves the wander a shifted sampling grid
    produces - 0.237v to 0.124v - and the band that follows is worth +0.349R a
    trade becoming **+0.576R** on the swing strategy (`research/swinging.md`).

    The rule is the origin's own definition applied one resolution down: the
    origin is the last price before the impulse took over, so inside the turn
    bar it is the **highest** fine close for a drop and the **lowest** for a
    rally.

    Takes the two extremes rather than a series, because **when** they are
    computed is the whole difficulty. Production first ran this at detection
    time and refined one 4h origin in 924: an origin does not exist until its
    impulse breaks structure, which on 4h is hours to days after the turn, by
    which point the 1m window holding eight hours has moved on. The extremes
    are now captured when the coarse bar closes - the one moment its minutes
    are certainly still there - and stored on the bar. See `Series.note_fine`.

    A `nan` extreme means the bar was never covered, and the origin comes back
    unchanged.


## `_covers`

    **The tolerance is the same at both ends, and it was not.** The right edge
    always allowed being short by one fine step; the left edge allowed nothing
    at all, so a single missing minute at a bar's open discarded the whole bar.

    Measured in production on 2026-09-08, that is what the refinement was
    losing: **57 captures across 258 4h series**, against 2,483 origins on that
    timeframe and 4 of them refined. 4h is the swing strategy's anchor and the
    refinement is worth +0.349R a trade becoming +0.576R there, so an
    asymmetric inequality was holding off the largest improvement ever measured
    on this book.

    The tolerance is one fine step or **2% of the span**, whichever is larger.
    One step alone is right for a 5m bar and absurdly strict for a 4h one,
    where 240 minutes are being thrown away over a boundary minute the venue
    never printed. Two percent of a 4h bar is under five minutes; of a 5m bar
    it is six seconds, which is under one step, so nothing changes there.

    This does **not** relax the argument the docstring above makes: partial
    cover is still not cover, and a refinement computed from two of fifteen
    minutes is still worse than none. A window reaching 98% of a bar is not
    partial cover, it is cover with a hole in it.


## `Origins.remember`

        **Why this exists, and it is a money number.** The band re-derived at
        the finer resolution is 2.6x narrower for 94.8% of the same returns
        (`research/localising.md`), and replaying the swing strategy with those
        walls turns +0.349R a trade into **+0.576R**, winning in all eight
        cells of the sweep (`research/swinging.md`).

        Refinement happens **once, the first time an origin is seen**, and the
        answer is kept - so a band computed today is still there in a month.
        `fine` is asked for the extremes of the origin's own bar and returns
        `(nan, nan)` when they were never captured. It may return two more
        numbers - the change points from `change_in`, in `(down, up)` order -
        and where it does, `unit` lets `refine` say whether they agree with
        where it put the origin. A two-item answer is still accepted: that is
        what every caller returned before the change points existed, and a
        save written then holds pairs.

        Identity is `(when, launched)` - the bar the turn happened on and which
        way the impulse went. The detector returns the same pair for the same
        origin on every pass, so a second sighting finds the stored one and
        keeps it rather than replacing a refined band with a coarse recompute.
        Not price: the refinement *moves* the price, so keying on it would make
        every refined origin look new and double the set.

        Bounded at `keep`, oldest dropped first, because a set that only grows
        is a leak with a long fuse.


