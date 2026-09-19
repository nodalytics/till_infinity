# Agents Models

Rationale moved out of `till_infinity/agents/models.py` on 2026-09-19.

Each section is the part of a docstring below its summary line: the
measurement, the failure it came from, the thing that was tried and did
not work. The code keeps what the function *is*; this keeps why it is
that way. Nothing was discarded.

## `Finding._strip_calls`

        The prompt asks for figures and says not to cite the call, which the
        model mostly honours and did not here: it published
        `(from default_api.spreads(feed='btc'))` to the channel - a namespace
        belonging to how the model is wired to its tools, not to anything about
        the market. `default_api` is not even ours.

        A prompt is a request. This is the guarantee, and it lives on the model
        rather than at the alert so the journal gets the same treatment: an
        evidence string is read back by `facto` and by a person reviewing a
        call months later, and neither is helped by a function signature.


