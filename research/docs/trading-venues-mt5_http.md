# Trading Venues Mt5_Http

Rationale moved out of `till_infinity/trading/venues/mt5_http.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `HttpBroker.trading_allowed`

        **A connected terminal with AutoTrading off rejects every order and
        answers every health check.** On 2026-09-12 that state lasted nine hours
        and cost **171 rejected orders** - pending and market, across the whole
        book - while `/terminal/ping` stayed green, the container reported
        healthy and the desk went on publishing signals and deciding to trade.
        Not one order filled in the entire session.

        It is `trade_allowed` on `/terminal/info`, and it is a **toggle in the
        terminal's own interface**: the bridge exposes info, ping, version and
        disconnect, and no route to set it. So this cannot fix the condition -
        it can only make sure nobody has to notice it from a P&L of zero.

        None rather than False when the field is missing, because a bridge that
        does not publish it is a different thing from a terminal that has it off,
        and refusing to trade on an absent field would ground the desk on every
        bridge that spells it differently.


## `HttpBroker.close_position`

        **The volume has to be sent.** This method took the argument and threw
        it away, posting only the ticket - so every partial close was a full
        close that reported success, and the scale-out rule silently shut whole
        positions while logging that it had taken half off. Caught on the first
        live scale-out, by the broker's own deal history showing one close of
        3.0 lots where the log claimed 1.5.

        Zero means all of it, which is what the bridge does with the parameter
        absent, so the full-close path is unchanged.


## `_bar_time`

    The bridge is not consistent with itself: `/symbols/ticks/` sends epoch
    seconds and `/symbols/rates/` sends an ISO string like
    `2026-08-07T15:00:00`. The string carries no zone and is the broker's
    server time, which is UTC here - Wall Street 30's last Friday bar opens at
    20:45 and its last tick was 20:44:58 UTC, so the two agree.

    `Bar.time` defaulted to 0.0 for every bar the bridge returned until this
    existed, because `float("2026-08-07T15:00:00")` raises and the whole row
    was skipped.


## `_point_value`

    **What one point of price is worth per lot is `contract_size`**, when the
    instrument settles in the account's own currency. That holds across every
    symbol on this account: Volatility 25 has a contract of 1 and
    `tick_value / tick_size` of 1; Step Index 10 and 10; XAUUSD 100 and 100;
    EURUSD 100,000 and 100,000.

    `Volatility 75 Index` reports `tick_size 0.01` with `tick_value 0.0001` -
    a ratio of 0.01 against a contract size of 1. **It is wrong by a hundred**,
    and the trade that proved it moved 115.56 points on 5.277 lots and paid
    622.63, which is 1.021 per point per lot rather than the 0.01 claimed.

    Sizing believed it was risking 9.47 and was risking about 886 - 9.5% of the
    account on one position against an intended 0.25%. It won. The arithmetic
    was right and the input was not.

    Only checked when the profit currency **is** the account currency. For
    anything else the tick value carries a conversion - USDJPY settles in yen
    and its ratio is nowhere near its contract size - and correcting there
    would break the instruments that are right.


