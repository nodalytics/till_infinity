"""Nautilus `Actor`s: things that consume the bus and publish, but do not trade.

An Actor is where a measurement lives. A `Strategy` is where an order comes
from. Keeping `statespace` on this side of that line is deliberate - it folds
variance and publishes a reading, and `direction-is-closed-not-just-null`
records what happened every time we asked it for more than that.
"""
