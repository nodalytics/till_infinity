"""Small things with more than one caller and no home of their own.

**Not a drawer.** ADR 0002's rule still holds: code with one consumer travels
to that consumer. What lands here has several and belongs to none of them -
`slugify` is read by the corpus, the store and the strategies' config, and
putting it in any one of those would make the other two import a package they
have no business in.

This is also where `till-platform`'s remnants came when that package was
retired: Nautilus supplies the logger, the cache and the serialisation it
existed to provide, and what was left was small enough not to need a
distribution of its own.
"""

from .text import slugify

__all__ = ["slugify"]
