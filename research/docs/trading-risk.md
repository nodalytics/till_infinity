# Trading Risk

Rationale moved out of `till_infinity/trading/risk.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Guard.restore`

        **The halt is the reason this exists.** `roll`'s docstring rejects
        carrying a halt "until someone restarts the process", because that lets
        the size of the loss decide how long trading stops. The implementation
        had the opposite failure and nobody had noticed: a fresh `Guard` has
        `day = ""`, so the first roll after *any* restart cleared `realised`,
        cleared `halted`, and reset `opening_equity` to whatever equity was
        showing - a lower base, from which a further full daily loss was
        allowed. There were ten deploys on 2026-09-04.

        Returns whether anything was taken. A saved day that is not today is
        ignored: the halt is meant to end at the date change and this must not
        resurrect it.


