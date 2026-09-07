"""Moved to `shared/state.py`; this keeps the old import path working.

`Restorable` is not a structures idea - `trading.strategies.floors` inherits
it, and every service that persists a dataclass wants the same defaulting. It
lives in `shared` now.
"""

from __future__ import annotations

from ..shared.state import Restorable, restore_enum

__all__ = ["Restorable", "restore_enum"]
