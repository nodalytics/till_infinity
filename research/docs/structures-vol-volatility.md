# Structures Vol Volatility

Rationale moved out of `till_infinity/structures/vol/volatility.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Volatility.mad_to_sigma`

        `sqrt(E[r^2]) / E[|r|]`, measured. Falls back to the Gaussian constant
        until warm, so a cold series behaves exactly as before.

        **Bounded below at 1.0 because no distribution can go under it** -
        Cauchy-Schwarz gives `E[r^2] >= E[|r|]^2`, so the ratio is at least one,
        and a value below it means an arithmetic fault rather than a fat tail.
        Bounded above at 3.0 because a ratio that large is a series with one
        enormous observation in it, and a conversion factor is not the right
        place to express that.


## `Volatility.forecast_ratio`

        **Where volatility is going, not where it is.** Above one the next bar
        is expected to be livelier than the last, whatever level either sits
        at. `stretch` below is the other question - the current scale against
        its own long-run level - and the two are near independent: log
        correlation **+0.033** over 32,362 published touches. An instrument can
        be at twice its usual volatility and expected to stay exactly there.

        Of the two, this is the one that predicts anything. See `stretch`.


## `Book.implied_bps`

        **The fitted value, not the quote.** Measured over 20 years on all four
        indices, the raw quote loses to `har` on every one and scores *worse
        than predicting the mean* on four - R-squared -0.484 on spx500 daily.
        Fitted, it beats `har` on all eight series by +0.10 to +0.28 R-squared,
        and beats `har` combined with itself on all eight too. See `implied.py`.

        None until `MIN_FIT` bars have been seen, so the member is absent rather
        than guessing while its one parameter is still noise.


