"""What is worth sending, and what is just true.

A channel people actually read is one that is quiet most of the time. The
detectors are not quiet: a stale feed re-fires every few seconds for as long as
it stays stale, and a wide spread does the same. All of that belongs in the
journal, where it is evidence. Very little of it belongs on a phone.

Level routing was the only filter there was - `info`, `warning`, `critical` -
and it is the wrong axis on its own. A stale feed and a level call can both be
`warning` while being completely different things to a reader.

Four filters, each answering a question the others cannot:

- **shape** - a kind of finding. "I want level calls, not every wide spread."
- **instrument** - "gold and BTC only."
- **repeat** - the same finding again inside a cooling-off window. A stale feed
  is one situation, not one situation per second.
- **rate** - a ceiling per hour, whatever else got through. The backstop for
  the case nobody predicted, because the failure being guarded against is a
  channel nobody reads any more.

Everything is allowed by default. A filter that silently drops things nobody
configured would be worse than the noise.
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from ..logging import get_logger

log = get_logger(__name__)

#: How long the same finding stays suppressed after being sent.
DEFAULT_COOLDOWN = 900.0

#: Ceiling per hour. Roughly one every three minutes at the worst.
DEFAULT_MAX_PER_HOUR = 20

#: Findings remembered for the repeat check.
MEMORY = 500


def _names(raw: str) -> frozenset[str]:
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


#: Shapes the hourly cap may not drop.
#:
#: The cap is one budget shared by everything, and the noisiest producer wins
#: it: level signals arrive continuously and a trade happens a few times a day,
#: so an hour of ordinary chatter can exhaust the allowance and the alert that
#: gets dropped is the one saying money moved. That is the wrong way round. A
#: level call is information and can wait for the next hour; a position opening
#: is a thing that has already happened to the account.
#:
#: They still *count* toward the hour, so the tally stays honest and a burst of
#: trading correctly quietens everything else.
UNCAPPED: frozenset[str] = frozenset({"trade"})


@dataclass(slots=True)
class Filter:
    """Decides what reaches a channel. Empty allowlists allow everything."""

    #: Shapes to accept - `level`, `stale`, `spread`, `dislocation`, `drift`.
    shapes: frozenset[str] = frozenset()
    #: Instruments to accept - `gold`, `btc`, …
    feeds: frozenset[str] = frozenset()
    cooldown: float = DEFAULT_COOLDOWN
    max_per_hour: int = DEFAULT_MAX_PER_HOUR
    _sent: OrderedDict[tuple[str, str, str], float] = field(default_factory=OrderedDict)
    _recent: list[float] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Filter:
        def number(name: str, fallback: float) -> float:
            try:
                return float(os.environ[name])
            except (KeyError, ValueError):
                return fallback

        return cls(
            shapes=_names(os.environ.get("NOTIFY_SHAPES", "")),
            feeds=_names(os.environ.get("NOTIFY_FEEDS", "")),
            cooldown=number("NOTIFY_COOLDOWN_S", DEFAULT_COOLDOWN),
            max_per_hour=int(number("NOTIFY_MAX_PER_HOUR", DEFAULT_MAX_PER_HOUR)),
        )

    def key(self, payload: dict[str, Any]) -> tuple[str, str, str, str]:
        """What makes two alerts "the same finding" for the repeat check.

        `event` is part of it, and leaving it out was a real fault rather than
        an omission. Opening a trade and closing it share a shape, an
        instrument and a venue, so a position opened and closed inside the
        cooldown had its **close** dropped as a repeat of its own fill.

        The bias that produced is the reason this is worth a paragraph. A trade
        that closes within fifteen minutes is usually one that was stopped out,
        so the alerts that vanished were disproportionately the losses, and the
        channel read as a record of wins. A filter that silently changes what a
        feed appears to say is worse than one that is merely too quiet.
        """
        fields = payload.get("fields") or {}
        # The source is `agents/analyst`, not `agents`, so the fallback takes
        # the part before the slash: a filter naming `agents` should match every
        # role rather than none of them.
        source = str(payload.get("source") or "").split("/")[0]
        return (
            str(fields.get("shape") or source),
            str(fields.get("instrument") or ""),
            str(fields.get("venue") or ""),
            str(fields.get("event") or ""),
        )

    def rejects(self, payload: dict[str, Any], when: float | None = None) -> str:
        """Why this should not be sent, or "" if it should.

        A reason rather than a bool, because a channel that goes quiet is
        indistinguishable from a channel that is broken unless the logs can say
        which finding was dropped and on what grounds.
        """
        when = time.time() if when is None else when
        shape, feed, _venue, _event = self.key(payload)

        if self.shapes and shape.lower() not in self.shapes:
            return f"shape {shape!r} not in {sorted(self.shapes)}"
        if self.feeds and feed and feed.lower() not in self.feeds:
            return f"instrument {feed!r} not in {sorted(self.feeds)}"

        last = self._sent.get(self.key(payload))
        if last is not None and when - last < self.cooldown:
            return f"same finding {when - last:.0f}s ago"

        self._recent = [at for at in self._recent if when - at < 3_600]
        if (
            self.max_per_hour
            and len(self._recent) >= self.max_per_hour
            and shape.lower() not in UNCAPPED
        ):
            return f"{len(self._recent)} already sent this hour"
        return ""

    def accept(self, payload: dict[str, Any], when: float | None = None) -> bool:
        """Decide, and remember the decision. Call once per alert."""
        when = time.time() if when is None else when
        why = self.rejects(payload, when)
        if why:
            log.debug("notify: dropped %r - %s", payload.get("title"), why)
            return False

        key = self.key(payload)
        self._sent[key] = when
        self._sent.move_to_end(key)
        while len(self._sent) > MEMORY:
            self._sent.popitem(last=False)
        self._recent.append(when)
        return True

    def describe(self) -> str:
        parts = []
        if self.shapes:
            parts.append(f"shapes {'/'.join(sorted(self.shapes))}")
        if self.feeds:
            parts.append(f"instruments {'/'.join(sorted(self.feeds))}")
        parts.append(f"one per {self.cooldown / 60:.0f}m")
        parts.append(f"max {self.max_per_hour}/hour")
        return ", ".join(parts)
