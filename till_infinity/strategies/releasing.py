"""Publishes the scheduled-release calendar, so every desk does not read it.

One actor on a timer, exactly as `screening.py` ranks volatility: 38 desks each
opening the same sqlite file every bar would be 38 readers of one slow-moving
fact. The store is the news collector's and is opened **read-only**; this never
writes it.

**The calendar is one of two things measured forecastable here**, and the only
one needing no model of the future - release times are published days ahead.
`news-volatility.md` has the numbers and `risk/releases.py` carries them.

The payload is `{"rows": [...], "at": float}` on `topics.EVENTS`, which was
declared and had no publisher: `news-adapters-have-no-consumers` records
`fred`, `calendar`, `cot` and `imf` as built and unread, and this is the first
of them wired to anything.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from nautilus_trader.common.actor import Actor
from nautilus_trader.config import ActorConfig

from ..risk.releases import upcoming
from ..utils import topics

#: Seconds between reads. A calendar changes when the collector polls, which is
#: hours, so this is deliberately slow: `tis-research-jobs-starve-the-service`
#: is a measured outage on the two-core box this runs on.
EVERY = 1_800.0

#: Days either side to carry. Wide enough that a read is never the reason a
#: release is missed, narrow enough that the payload stays small.
WINDOW = 7.0

#: Where the collector writes. The container sees the volume at `/app/.data`.
PATH = os.environ.get("TILL_NEWS_DB") or "/app/.data/news/news.db"


class ReleaseConfig(ActorConfig, frozen=True):
    """Where the calendar is, and how often to re-read it."""

    path: str = PATH
    every: float = EVERY
    window_days: float = WINDOW


class ReleaseWatch(Actor):
    """Reads the calendar on a timer and publishes what is within reach."""

    def __init__(self, config: ReleaseConfig) -> None:
        super().__init__(config)
        self._cfg = config
        self._published = 0

    def on_start(self) -> None:
        # Read once immediately rather than waiting a full period: a desk that
        # deploys an hour before a print would otherwise size through it blind,
        # which is the shape of the volatility screen's five-hour halt.
        self._read()
        self.clock.set_timer(
            name="release-watch",
            interval=timedelta(seconds=max(60.0, self._cfg.every)),
            callback=lambda _event: self._read(),
        )
        self.log.info(
            f"watching {self._cfg.path} every {self._cfg.every:.0f}s "
            f"for releases within {self._cfg.window_days:.0f} days"
        )

    def _read(self) -> None:
        """Publish the calendar, or say why there is none.

        Never raises: this is a feature, and a desk without a calendar must
        size exactly as it did before rather than stop.
        """
        try:
            rows = upcoming(Path(self._cfg.path), window_days=self._cfg.window_days)
        except Exception as exc:  # pragma: no cover - a locked or absent file
            self.log.warning(f"could not read the calendar at {self._cfg.path}: {exc}")
            return
        if not rows:
            # Said once an hour rather than never: an empty calendar and a
            # missing one look identical to every consumer downstream, and a
            # feature that silently does nothing is the failure this desk keeps
            # finding.
            self.log.warning(
                f"no important release within {self._cfg.window_days:.0f} days at "
                f"{self._cfg.path} - the release band is inert until there is one"
            )
            return
        self._published += 1
        topics.publish(
            self,
            topics.EVENTS,
            {"rows": rows, "at": float(self.clock.timestamp()), "reads": self._published},
        )
        self.log.info(f"calendar: {len(rows)} important release(s) within reach")


def rows_of(payload: Any) -> list[dict]:
    """The calendar rows from an `EVENTS` payload, or an empty list.

    A shape this does not know is nothing rather than an exception: a desk
    folds this inside a handler and a malformed payload must not cost a bar.
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get("rows")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


__all__ = ["EVERY", "PATH", "WINDOW", "ReleaseConfig", "ReleaseWatch", "rows_of"]
