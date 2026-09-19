# Trading Strategies Opportunity

Rationale moved out of `till_infinity/trading/strategies/opportunity.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Opportunity.consider`

        **Spelled out rather than `**kw`.** A test walks `STRATEGIES` asserting
        every `consider` accepts what the service passes, and it exists because
        widening the base signature once left two overrides behind and stopped
        the desk trading for two hours. `**kw` passes at runtime and fails that
        test, which is the right way round.

        Safe to set instance attributes here: `consider` is synchronous, so one
        signal is shaped and decided before the next is looked at. The async
        wrapper is around this, not inside it.


## `Ride`

    The same entry, the same frame, the same gates - only the exit differs,
    which is what makes the pair a comparison rather than two strategies.

    **Measured before it was written**, on 31,820 touches replayed from 1m bars
    with each exit policy scored on identical entries:

    | policy | mean R | median | win |
    | --- | ---: | ---: | ---: |
    | **trail 0.5v, no target** | **+0.404** | -0.037 | 47% |
    | trail 1v, no target | +0.228 | -0.271 | 41% |
    | target 1x the push | -0.041 | -1.000 | 35% |
    | target 2x | -0.132 | -1.000 | 23% |
    | target 3x | -0.235 | -1.000 | 17% |
    | trail 2v, no target | -0.135 | -1.000 | 29% |

    Every fixed target loses; every tight trail wins; tighter is better. That
    holds at each entry timeframe separately, not only pooled.

    **Two things this is not.** The mean rides on the right tail - the median is
    **negative for every policy including this one**, so most trades lose a
    little and a few win a lot. And the replay models no spread, which is
    precisely what sinks fast entries live, so the entry floor stays at 15m on
    the strength of the money rather than of this table.

    **The target is moved, not removed.** `lots` and the reward-to-risk gate
    both need one to exist, and a trade with no stated objective cannot be
    sized or refused - the same reason `runner` keeps one. Six times the
    modelled push is far past the p99 of what touches reach, so it bounds the
    trade without being what ordinarily ends it.

    Listed beside `opportunity` rather than replacing it, so `_also_wanted`
    scores both on the same signals and the argument settles itself.


