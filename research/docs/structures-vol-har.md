# Structures Vol Har

Rationale moved out of `till_infinity/structures/vol/har.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Har._split`

        **A jump and a busy hour are not the same thing and do not persist the
        same way.** Realised volatility pools them, so a model fitted on the
        pooled series learns one memory for two processes - and the jump part
        has almost none, which drags the diffusive coefficients down after any
        violent bar.

        The separation is Andersen-Bollerslev-Diebold's bipower idea at bar
        resolution: `sqrt(x_t * x_{t-1})` multiplies *adjacent* bars, so a
        single large bar inflates only one of the two factors and the product
        stays near the continuous level. The excess of the bar over that is the
        jump.

        Scaled by `pi/2`, which is the constant that makes the product an
        unbiased estimator of the continuous scale for a Gaussian diffusion -
        the same `E|X| = sigma sqrt(2/pi)` that `consensus_vol` converts with,
        appearing here as its reciprocal squared.


## `Har.published`

        **On the generated half of this book there is nothing for a rolling
        model to track and it should not pretend otherwise.** Those feeds have
        no volatility clustering at all - largest `|acf|` of the absolute 1m
        return is 0.017 against 0.219 to 0.453 on real controls - so the three
        horizons this model averages are three windows onto the same constant,
        and every study run against them this week put a fitted forecast at
        *negative* out-of-sample R-squared where the published number is right
        to a median 1.0020 of itself.

        `None` for every instrument whose name claims nothing, which is every
        real market and the Boom, Crash, Step and Range Break families.


## `Har.predict`

        **The published constant wins outright where there is one.** See
        `published`: on a constant-sigma feed the correct forecast is the
        constant, and it needs no warm-up, cannot misread a regime that does
        not exist, and does not decay when the model has been fed a violent bar.

        Otherwise the fitted value, and the most recent realised reading while
        cold - which is the naive forecast this has to beat.

        **Worth knowing before relying on this at one bar.**
        `research/forecasting.md` measured naive beating HAR in 11 of 12 cells
        at a one-bar horizon while HAR wins at 5, 10 and 20 bars, so this method
        is being asked for a number at the single horizon where the form is
        weakest. `predict_over` is the one to use when the consumer's horizon is
        longer than a bar - which for anything sizing a stop, it is.


## `Har.predict_over`

        A stop sized for the next half hour wants the volatility expected over
        that half hour, not over the next bar, and those are different numbers
        whenever the model has a view at all.

        Scaled by the square root of time, which is exact for the diffusive
        part and the reason this returns a per-bar figure rather than a total:
        every threshold in this package is expressed per bar, and handing them a
        total would silently multiply every distance by `sqrt(bars)`.

        The forecast itself does not change with the horizon - a one-step linear
        model has one view - so what this expresses is the **mean reversion**:
        over more bars the expectation pulls toward the long-horizon term, which
        is exactly what the three-horizon form is for.


