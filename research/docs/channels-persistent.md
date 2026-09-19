# Channels Persistent

Rationale moved out of `till_infinity/channels/persistent.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `wrap_with_outbox`

    Args:
        sender:        the primary Sender to wrap
        path:          SQLite file for the outbox
        channel_name:  used to namespace outbox/DLQ rows
        dlq:           True → auto-create DLQ at same path,
                       or pass a DeadLetterQueue instance, or False to skip
        max_attempts:  how many retries before parking in DLQ
        backoff:       BackoffPolicy for replay spacing (default: exponential)
        metrics:       MetricsHook (default: process-wide default)


