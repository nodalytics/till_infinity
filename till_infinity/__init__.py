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
frozen.ship(Path(__file__).resolve().parent / "models")

__all__ = ["__version__"]
