# Channels Redis

Rationale moved out of `till_infinity/channels/redis.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `redis_channel`

    Args:
        key:              Redis stream key
        group:            consumer group name (shared across workers)
        consumer:         consumer id (unique per worker, auto-generated)
        maxlen:           stream cap (approximate)
        url:              Redis URL (defaults to REDIS_URL env var)
        persistent_path:  if set, wrap sender with SQLite outbox so
                          failed sends survive Redis outages and
                          replay when the primary recovers.


