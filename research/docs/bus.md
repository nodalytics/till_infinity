# Bus

Rationale moved out of `till_infinity/bus.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Bus._note_unheard`

        **Publishing into a void is silent and looks exactly like working.**
        The publisher's own counters go up, its journal fills, its logs read
        normally, and the consumer sits in its pump with nothing arriving - so
        the failure presents as a desk that has simply gone quiet. On
        2026-09-16 structures published 18,565 signals in twenty-five minutes
        while trading recorded none, and nothing anywhere said the two were not
        connected.

        Throttled on the same widening schedule as `_note_drop`, and for the
        same reason: a line per message would bury the cause under the symptom.


## `Bus._note_drop`

        **A line per drop destroys the evidence for why it is dropping.** On
        2026-09-08 a stalled structures consumer produced 132,807 identical
        warnings, which rotated the supervisor's own error - the one naming the
        fault - out of `docker logs` entirely, three times over. The drops were
        a symptom shouting loudly enough to bury the cause.

        So the count is kept and reported at widening intervals, with the total
        attached. A consumer that stops draining is one event, not a hundred
        thousand.


