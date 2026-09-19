# Notifications Filters

Rationale moved out of `till_infinity/notifications/filters.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Filter.key`

        `event` is part of it, and leaving it out was a real fault rather than
        an omission. Opening a trade and closing it share a shape, an
        instrument and a venue, so a position opened and closed inside the
        cooldown had its **close** dropped as a repeat of its own fill.

        The bias that produced is the reason this is worth a paragraph. A trade
        that closes within fifteen minutes is usually one that was stopped out,
        so the alerts that vanished were disproportionately the losses, and the
        channel read as a record of wins. A filter that silently changes what a
        feed appears to say is worse than one that is merely too quiet.


