# Structures Learning Facto

Rationale moved out of `till_infinity/structures/learning/facto.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `saturate`

    A factorisation machine's gradients are *quadratic* in feature magnitude -
    the interaction terms multiply two features together - so an unbounded
    input does not merely skew the fit, it diverges it. Feeding the raw values
    took the latent factors non-finite within tens of examples, after which
    `Model.predict` returned zero forever and the model learned nothing while
    reporting nothing wrong.

    Saturating rather than clipping because a clip needs a maximum, and any
    maximum here is a number someone made up: it would treat a four-volatility
    approach and a forty-volatility one as the same event, which is exactly the
    distinction a violent touch consists of. This keeps the ordering everywhere
    and simply stops the tail from dominating - the same instinct as
    `experience_of` log-compressing a touch count, held to a hard bound because
    the FM needs one.


## `encode`

    Categoricals become `name_value: 1.0` rather than an integer code. An
    integer would tell the model that `1h` sits between `15m` and `4h` on some
    scale it should interpolate along, which is true of the durations and not
    of anything the model does with them.

    Everything this returns is bounded, which is the property the FM needs -
    see `saturate`. The volatility-unit features are saturated into [0, 1) on
    the way past; the rest already hold themselves down, `strength`, `regime`,
    `pivot` and `backcheck` in [0, 1] by construction and `experience` growing
    like the log of a touch count, which no market reaches the far end of.


## `Model.predict`

        `FMRegressor.predict_one` raises `AttributeError` - not something
        catchable by intent - in two situations, because its internal dot
        product returns a plain float where river expects a numpy scalar and
        calls `.item()` on it:

        - **nothing learned yet.** Progressive validation predicts *before* it
          learns, so the first example hits this every time. The discipline and
          the library disagree, and this is where they are reconciled.
        - **fewer than two features.** An FM models *pairwise* interactions, and
          one feature has no pairs. Real rows carry several, but a sparse
          journal entry would otherwise take down a running service.

        Zero is also the honest answer in both: a model with no history, or no
        interaction to look at, has no opinion about the next push.


## `fit`

    `since` exists because a measurement bug does not only corrupt the numbers
    it produced - it corrupts every example recorded while it was live. Touch
    counts fed `experience` and `strength`, and a pooled base rate made `edge`
    wrong on every row, so examples from before those were fixed describe a
    model that no longer exists. Fitting across the boundary would teach the FM
    the relationship between features and outcomes *as they were mismeasured*,
    which is worse than having no model, because it would look like one.

    Pass a unix timestamp to count only what was recorded after a known-good
    point. There is no default: where the boundary sits is a judgement about
    this deployment's history, not something the code can know.


