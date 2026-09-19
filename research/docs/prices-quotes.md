# Prices Quotes

Rationale moved out of `till_infinity/prices/quotes.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `TradingViewQuotes._await_first`

        **`asyncio.wait`, never `wait_for`, and this is the reason the quote
        feed kept dying.** `wait_for` implements its timeout by cancelling the
        *enclosing task* and converting the `CancelledError` back into a
        `TimeoutError` through `uncancel`. The enclosing task here is the whole
        quote poll, and when that conversion does not balance - a cancellation
        arriving from elsewhere in the same moment, an inner frame swallowing
        the first one - the task is left cancelled and simply disappears. No
        exception is recorded, its siblings keep running, and the actor still
        reads as healthy.

        That is precisely what the desk did on 2026-09-16, roughly twice an
        hour, timed to socket drops: a dropped socket means these events never
        fire, which means this waits its full timeout, which is when `wait_for`
        reaches for the cancel. `asyncio.wait` takes a deadline and touches
        nobody's cancellation state.


## `TradingViewQuotes._revive`

        **A reconnect on the polling path must not be able to stop the
        polling.** `poll_once` runs one task group over *every* source, so an
        unbounded connect here does not merely delay tradingview - it holds
        the group open and the broker half of the book stops quoting too. That
        is what happened at 08:58 on 2026-09-16, fifteen minutes after this
        check was first shipped: the socket dropped, the reconnect hung, and
        both transports went dark while `collect` carried on writing bars.

        Failing leaves the cache in place, which is safe now that a cached
        quote is dated when it moved: stale is visible rather than disguised,
        and the next poll tries again.


## `TradingViewQuotes.quote`

        **The reconnect used to be unreachable from here for any symbol that
        had been prepared**, which is every symbol the desk follows. So a
        dropped socket was permanent: the reader task ended, no poll ever
        looked at it again, and this went on answering out of a field map
        nothing was updating. Twice on 2026-09-16 the desk wrote no quote for
        hours - once for 2h34m and once until it was restarted - with no error
        logged, every other actor healthy, and bars still arriving.


## `BrokerQuotes`

    Every other source here is somebody else's opinion of the price. This one
    is the book we actually deal on, and that difference is worth having for
    two separate reasons.

    **Coverage.** The consensus venues carry the majors and nothing else. A
    broker offers hundreds of instruments no venue on TradingView quotes -
    synthetics above all, which have no underlying and therefore no other
    source by construction. Without this they cannot be traded here at all,
    because `structures` builds levels from quotes and there were none to
    build from.

    **Agreement with what we trade.** A level built from six venues' consensus
    and an order filled on one broker's book are answers to slightly different
    questions, and the gap between them is what `dislocation` exists to police.
    A level built from the broker's own quotes has no gap to police.

    **It polls; there is no stream.** The bridge publishes no websocket and no
    SSE - forty-seven routes, and the only `subscribe` is
    `/symbols/book/{symbol}/subscribe`, which is MT5 market *depth* and is
    still read by polling `/symbols/book/{symbol}`. So this is a poller, and
    `streaming` stays False. Worth stating plainly because "stream prices from
    the terminal" is the obvious way to describe the goal and is not what the
    transport does.

    **Off unless asked for.** Not in `DEFAULT_QUOTE_SOURCES`: it needs a bridge
    that only exists where a terminal is reachable, and a deployment without
    one should not be trying and failing on every symbol.


## `BrokerQuotes.prepare`

        **Not optional, and silent when skipped.** MT5 only streams ticks for
        symbols in Market Watch, and an unselected one answers the tick
        endpoint with `bid 0.0, ask 0.0, time 0` - HTTP 200, well-formed, and
        empty. Measured: `Volatility 75 Index` read zero, and 51418.35/51436.01
        one second after a select. Without this the source would poll happily
        and publish nothing, which is the failure that looks like working code.

        Selection sticks for the session, so this runs once per start rather
        than per poll.


## `poll_once.one`

        A task group cancels the task it is running in to unwind it when a
        child fails, so a single symbol throwing does not merely lose that
        symbol - it takes down the whole quote poll, and the cancellation is
        what the poll's caller sees. That is how the desk lost quotes roughly
        twice an hour on 2026-09-16: `prices:quotes` ended cancelled, with no
        exception recorded anywhere, while the bar collector beside it carried
        on and every actor still read as healthy.

        One bad symbol is one bad symbol. It is counted and the book continues.


## `_watch_polls`

    **Two stalls that look identical from outside and need opposite fixes.** A
    poll that never returns is a hung await. Polls that return having written
    nothing is a source gone quiet without saying so. On 2026-09-16 the desk
    suffered the second four times, three fixes were aimed at the first, and
    nothing in the process could tell anyone which it was.

    One report per stall rather than one per check, because a symptom shouting
    buries the cause - `_note_drop` learned that when 132,807 identical
    warnings rotated the real error out of the logs.


