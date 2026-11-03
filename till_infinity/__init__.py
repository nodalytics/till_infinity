"""till-infinity: a Nautilus trading node, and the pipeline that feeds it."""

__version__ = "0.1.0"

# **Nothing is shipped from here any more.** This module used to call
# `frozen.ship()` to tell the model reader where the trained artefacts were -
# it had guessed a sibling directory, and the guess pointed into the package
# the moment that became installable, so every shipped model silently stopped
# being found.
#
# Both the reader and the artefacts are retired: `frozen` went with
# `till-platform` to `research/retire/`, and the `envelope`, `expansion` and
# `shocks` JSON files went to `research/retire/models/artefacts/` beside the
# scripts that trained them. Every loader was in `structures/`, which is
# retired too.
#
# The lesson is worth more than the code: a `__file__`-relative path is a
# hidden dependency on a module's *position*, and an absent directory reads as
# "nothing found" rather than as an error. Whoever ships files says where they
# are.

__all__ = ["__version__"]
