# Agents Tools

Rationale moved out of `till_infinity/agents/tools.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `spreads`

    Use this to judge whether a spread is unusual. A venue whose average is
    3bps sitting at 9bps is news; a venue whose average is 9bps sitting at 9bps
    is not.

    `latest_bps` is the most recent reading. `samples`, `avg_bps`, `min_bps`
    and `max_bps` describe the window **before** it, and `latest_pctile` is the
    share of those earlier samples at or below it.

    Compare against `latest_pctile`, not against `max_bps`. The two used to be
    the same number whenever the latest reading was the widest - the reading
    counted in its own history - so "this is at the maximum" was true by
    construction and said nothing. 100 now means genuinely wider than anything
    else in the window. `latest_pctile` is null when the venue has quoted only
    once, which means there is no history to judge it against, not that it is
    ordinary.


## `events`

    `released=False` gives what is still to come, `True` what has already
    printed (with its `actual`), and omitting it gives both. `min_importance`
    is 1 to 3, where 3 is the releases that actually move price.

    Two calendars are stored side by side on purpose, so the same release may
    appear twice from different `source` values. That is corroboration, not two
    separate events - do not report it as two.


## `levels`

    Where price has repeatedly turned, how wide the zone is, and what it did on
    arrival **from each side** - the same level often behaves oppositely
    depending on which direction price came from, so `sides` is keyed that way.

    `touches` are *effective* counts, decayed by age: a level tested ten times
    last quarter is weaker evidence than one tested twice this week, and the
    number already accounts for that.

    `trap_rate` is the share of breakouts here that were taken back. A level
    where half the breakouts fail is not a level to trade a breakout at.

    `interval` filters to 5m, 15m, 1h, 4h, 1d or 1w. Leave it empty for all.


## `level_at`

    The question levels exist to answer. Returns, for the nearest levels:
    which way price got pushed given the side it arrived from
    (`probability_up`, `expected_push_vol` in volatility units), and the
    `base_rate_up` beside it.

    **Compare the two.** A level whose `probability_up` matches `base_rate_up`
    has told you nothing, however confident it looks - `edge` is the difference
    and `actionable` is whether it clears the bar for evidence, edge and size
    together. `mixed` means the win rate and the expected move disagree, which
    is a real shape and not a call.


## `next_levels`

    Ordered by time rather than distance: a level on a fast timeframe can be
    reached long before a nearer one on a slow timeframe.

    `median` is the typical time to get there and `slow` the unlucky case;
    `within_window` is the chance of reaching it inside the next 24 bars of
    that timeframe. Time goes as the **square** of distance, so a level twice
    as far away takes four times as long, not twice.

    There is deliberately no average - the first-passage distribution has an
    infinite mean, so an average would grow with the length of the sample. Use
    the median.

    This is a null model from distance and volatility alone; it says nothing
    about direction. Pair it with `level_at` for that.


## `recent`

    Read this before reporting something as new. Each entry carries the
    reasoning at the time and the figures it was based on, so you can tell
    whether a situation is the same one continuing or a genuinely new one.

    `tag` filters to an instrument or venue. Entries of kind `outcome` say what
    actually happened after an earlier decision - those are the ones worth
    weighing most, because they are the only ones that were checked.


