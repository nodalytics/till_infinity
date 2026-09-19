# Prices Yahoo

Rationale moved out of `till_infinity/prices/yahoo.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `YahooSource._shape`

        Only the rows that are going to be kept are converted. This used to
        convert the whole frame and then discard all but the last `bars` of it,
        which for a week of 1m candles is ten thousand rows built into `Bar`
        objects to keep five hundred.

        The slice cannot simply be taken first, which is why it was left alone
        the first time: `to_bars` drops rows with a NaN open, so the last
        `bars` *rows* are not the last `bars` *bars*, and the count would
        quietly come up short. Dropping them in pandas first - the same
        condition, applied where it is cheap - makes the two equivalent.

        A row whose open is present but not a number is still dropped by
        `to_bars` alone, so the trimmed result can be short. That is rare
        enough to be worth a second pass rather than a wider margin, and
        converting the rest is what the old code did anyway.


