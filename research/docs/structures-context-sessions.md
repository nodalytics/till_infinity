# Structures Context Sessions

Rationale moved out of `till_infinity/structures/context/sessions.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Clock.base_rate`

        The thing each hour is shrunk toward, and the thing an hour's rate has
        to be read against. An hour at 70% where the instrument holds 70%
        anyway has said nothing, however many observations are behind it.

        **Itself shrunk, toward a coin.** Shrinking an hour toward a base rate
        computed from the same handful of observations is no protection at all:
        an instrument whose only two interactions both held has a pooled rate
        of 1.0, so the hour is shrunk toward 1.0 and reports 1.0. Caught by
        asking a two-observation clock what it thought and being told
        "certainty". A new instrument now reads near a coin flip until it has
        earned otherwise.


