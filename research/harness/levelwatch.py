"""Watch one level somebody called, and record what price actually did.

**Why a file rather than an opinion.** A call is only worth something if the
outcome is written down before it is known, and the failure mode this exists to
prevent is the one every desk has: the winners get remembered and the losers get
explained. So the claim is stamped once, with its source, and every later run
appends what happened without being able to alter it.

This is deliberately not the level book. `structures` draws its own levels and
records its own outcomes; this records a level drawn by **somebody else** - a
human, another desk, an indicator - so the two can be compared on the same
instrument over the same hours. Where they agree is worth knowing; where they
disagree is worth more.

## What counts as what

* **approach** - price came within `NEAR_VOL` volatility units of the level.
* **touch** - price traded through the level's zone.
* **held** - after a touch, price moved `HOLD_VOL` away on the called side
  without first moving `FAIL_VOL` against it.
* **broke** - the opposite.

All distances are in volatility units, because a fixed number of points is a
claim about one instrument on one day - and this instrument is a volatility
index running twice its own long-run scale, where points mean nothing.

Nothing here decides anything. It is a notebook with a timestamp.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, "/app")

#: **Not `JOURNAL`.** The container already sets `JOURNAL=1` as a boolean -
#: journalling on - so reading that name as a path made this try to open a file
#: called "1". A generic environment variable name is a collision waiting for a
#: second reader, and this was the second reader.
JOURNAL = os.environ.get("LEVELWATCH_DB", "/app/.data/journal/journal.db")
BOOK = Path(os.environ.get("LEVELWATCH_FILE", "/app/.data/watching.json"))

#: How close counts as an approach, in volatility units.
NEAR_VOL = 1.0
#: How far price must travel the called way, after a touch, to count as held.
HOLD_VOL = 1.5
#: And against it, to count as broken. Asymmetric on purpose: a level that has
#: to survive the same distance it is credited for is a coin flip by
#: construction, and the stop on a real trade sits closer than the target.
FAIL_VOL = 1.0


def load() -> list[dict]:
    if not BOOK.exists():
        return []
    try:
        return json.loads(BOOK.read_text())
    except Exception:
        return []


def save(rows: list[dict]) -> None:
    BOOK.parent.mkdir(parents=True, exist_ok=True)
    BOOK.write_text(json.dumps(rows, indent=2, sort_keys=True))


def add(feed: str, level: float, side: str, interval: str, source: str) -> dict:
    """Stamp a claim. Refuses to restate one already being watched."""
    rows = load()
    for row in rows:
        if row["feed"] == feed and abs(row["level"] - level) < 1e-9 and row["side"] == side:
            print(f"already watching {feed} {level} {side} since {row['stamped']}")
            return row
    row = {
        "feed": feed,
        "level": float(level),
        "side": side,
        "interval": interval,
        "source": source,
        "stamped": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stamped_at": time.time(),
        "state": "waiting",
        "closest_vol": None,
        "notes": [],
    }
    rows.append(row)
    save(rows)
    print(f"watching {feed} {level} {side} ({interval}) from {source}")
    return row


def _prices(feed: str, since: float) -> list[tuple[float, float, float, float]]:
    """(time, high, low, close) for this feed, from what structures published.

    Read from the journal rather than the price store on purpose: the price
    store is not carrying bars for the 1s indices, and the journal is what the
    engine actually saw. A watcher that silently reads an empty table is worse
    than one that reads a partial one.
    """
    # The journal is approaching a gigabyte, so this reads a bounded window
    # rather than everything since the stamp - a watcher that gets slower every
    # day it runs is one nobody runs.
    conn = sqlite3.connect(f"file:{JOURNAL}?mode=ro", uri=True, timeout=180.0)
    out = []
    for when, ctx in conn.execute(
        "SELECT time, context FROM entries WHERE actor='structures' AND time>=? "
        "ORDER BY time ASC LIMIT 200000",
        (since,),
    ):
        try:
            got = json.loads(ctx or "{}")
        except Exception:
            continue
        if str(got.get("feed") or "") != feed:
            continue
        price = got.get("price") or got.get("level")
        vol = got.get("vol_bps")
        if isinstance(price, int | float) and isinstance(vol, int | float):
            out.append((when, float(price), float(vol), str(got.get("interval") or "")))
    return out


def check() -> None:
    rows = load()
    if not rows:
        print("nothing being watched")
        return
    for row in rows:
        seen = _prices(row["feed"], row["stamped_at"])
        if not seen:
            print(f"{row['feed']} {row['level']}: no readings since {row['stamped']}")
            continue
        level = row["level"]
        closest = min(seen, key=lambda r: abs(r[1] - level))
        unit = closest[2] * level / 10_000 or 1.0
        away = abs(closest[1] - level) / unit
        row["closest_vol"] = round(away, 3)
        touched = away <= NEAR_VOL
        if touched and row["state"] == "waiting":
            row["state"] = "approached"
            row["notes"].append(
                f"{time.strftime('%m-%d %H:%M', time.gmtime(closest[0]))} came within "
                f"{away:.2f}v at {closest[1]:.4f}"
            )
        sign = 1 if row["side"] == "buy" else -1
        after = [r for r in seen if r[0] >= closest[0]]
        best = max(((r[1] - level) * sign / unit) for r in after) if after else 0.0
        worst = min(((r[1] - level) * sign / unit) for r in after) if after else 0.0
        print(
            f"{row['feed']} {level:.4f} {row['side']} ({row['interval']}, {row['source']})\n"
            f"  state {row['state']}   closest {away:.2f}v   "
            f"best {best:+.2f}v   worst {worst:+.2f}v   readings {len(seen)}"
        )
        if row["state"] == "approached":
            if best >= HOLD_VOL and worst > -FAIL_VOL:
                row["state"] = "held"
            elif worst <= -FAIL_VOL:
                row["state"] = "broke"
            print(f"  -> {row['state']}")
        for note in row["notes"][-3:]:
            print(f"  {note}")
    save(rows)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "add":
        add(sys.argv[2], float(sys.argv[3]), sys.argv[4], sys.argv[5], " ".join(sys.argv[6:]))
    check()
