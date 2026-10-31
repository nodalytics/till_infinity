"""till-infinity."""

from pathlib import Path

from till_platform import frozen

__version__ = "0.1.0"

# **Where the shipped models are.** `till_platform.frozen` reads them and does
# not know where they live: it guessed a sibling directory until it became a
# package, at which point the guess pointed into the package and every shipped
# model silently stopped being found. The desk ships them, so the desk says so,
# and it happens here because importing anything under `till_infinity` imports
# this first.
# **The trained artefacts live with the scripts that produced them**, in
# `research/retire/models/`, since every loader is in the retired
# `structures/` package and `STRUCTURES_ENABLED=0` in production. `ship()`
# tolerates an absent directory, which is what the image has - and that is
# correct rather than unfortunate: an image that carries models nothing loads
# is 1.7MB of confusion.
frozen.ship(Path(__file__).resolve().parents[1] / "research" / "retire" / "models" / "artefacts")

__all__ = ["__version__"]
