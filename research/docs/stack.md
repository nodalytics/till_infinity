# Stack

Rationale moved out of `till_infinity/stack.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Status.publish`

        Called on every change rather than once at start-up, because the case
        this exists for is a service that dies *after* the stack came up - which
        is what happened on 2026-09-11 and what `--version` could not see.

        **And on a timer, which the first version of this got wrong.** Publishing
        only on change means a stack where nothing changes - the healthy case -
        writes once and never again, so the file ages past `health --max-age` and
        a working container is marked unhealthy. That happened within nine hours
        of shipping it: seven services running, `failed` empty, and the file
        33,138 seconds old. See `HEARTBEAT`.

        Swallows its own errors: a status file that cannot be written is worth a
        debug line, not a stack that stops because it could not describe itself.


## `_forever`

    **This does not claim to know why it stops.** Six fixes went to the cause
    of one collector's death on 2026-09-16: an unreachable reconnect, then an
    unbounded one, then a reconnect on the polling path, then exceptions in a
    child task, then the task group itself, then `cancelling()` asked of the
    wrong task. Every one was a real defect and every one was verified fixed,
    and the collector kept dying - which is a strong signal that the seventh
    explanation would have been wrong as well.

    So the claim here is smaller and holds whatever the cause: a collector that
    ends gets started again, loudly. A silent permanent outage becomes a logged
    blip, and that works against a library cancelling something deep inside
    httpx exactly as well as against a bug in this repository.

    **A cancellation nobody requested is a death, not a shutdown**, which is
    the failure exactly as observed: the task ends cancelled, no exception is
    recorded anywhere, its siblings keep running, and every gauge reads
    healthy. `cancelling()` counts requests made against *this* task, so zero
    means nobody here asked - and a real shutdown, which did ask, still stops.

    Backs off so a collector that cannot start does not spin: `settle` per
    attempt, capped at a minute.


## `_forever.survive`

        **Used for the backoff as well as the collector**, which is not a
        tidiness point. The first version guarded only the collector and left
        the wait between attempts bare, so a cancellation landing in that
        window killed the supervisor outright - caught in production within
        half an hour of shipping, as `restarting (attempt 1)` followed
        immediately by `was cancelled - it should run forever`. Every await in
        here is a place a library can cancel this task, so every await has to
        be guarded the same way.


## `_forever.attempt`

        **The collector cannot share this task, and that is the whole fix.**
        An anyio cancel scope - which is how httpx implements every timeout -
        belongs to the task that entered it, and once its deadline has passed
        it re-delivers cancellation at *every* checkpoint until the scope is
        exited. Catching the `CancelledError` here and calling `uncancel` does
        not exit that scope, so the next await was cancelled too, and the next:
        the backoff below never elapsed and the loop spun.

        It is not a theory. On 2026-09-18 this logged 105,021 restarts in four
        and a half hours - about six a second - and 96% of the container's log
        was this one line, which buried everything else on a two-core box.

        Given a task of its own, a scope entered inside `make` dies with that
        task. Nothing can reach this one but a real shutdown, so the wait
        between attempts is an ordinary `sleep` again.


## `_watch_end`

    **A child of a task group that returns takes nothing with it.** The group
    only reacts to an exception, so a collector that simply *ends* leaves its
    siblings running, the actor marked healthy, and nothing at all in the log.
    That is the shape the quote feed kept failing in on 2026-09-16: quotes
    stopped, bars carried on, every actor read as running, and the task was
    absent from a dump with no explanation anywhere for where it had gone.

    Named tasks for the same reason - `Task-532` in a dump of 248 says nothing
    about which collector went quiet.


## `_arm_task_dump`

    **Because inference has a poor record here.** On 2026-09-16 the quote feed
    went dark roughly every forty minutes; five deploys were aimed at whichever
    await seemed likeliest, and the process could not be asked which one it was
    actually standing on. A watchdog answers that after its patience expires
    and only for the condition it was written to notice. This answers it now,
    for whatever is actually happening, without a deploy in between.

    Scheduled on the loop rather than run in the handler, so it sees the loop's
    own view of its tasks - and so a loop that is genuinely wedged is diagnosed
    by the *absence* of this output, which is itself the answer.


## `Stack.run`

        Returns once `duration` has elapsed, `once` has finished a collection
        pass, or the caller cancels. A service that raises takes itself down and
        is recorded; the rest keep running.

        `once` waits for the **collectors** and then stops the rest. The
        consumers have no notion of a pass - they run until stopped - so
        waiting for everything would wait forever, which is exactly what it did
        before this knew the difference.


## `Stack._backfill`

        Ordered deliberately: the collectors publish notices and `structures`
        warms from the *store*, so history has to be there before the level
        engine looks. Starting first and backfilling after would mean the
        engine warms from an empty store, saves that emptiness, and restores it
        on every restart afterwards.

        Skipped when the store already has enough, so a restart costs nothing.


