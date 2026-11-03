"""Names, made safe for a filesystem or a topic.

Moved here when `prices/` was retired on 2026-10-31. It had three callers
across two packages, which is exactly the case this directory is for.
"""

from __future__ import annotations

import re

_SLUG = re.compile(r"[^A-Za-z0-9]+")


def slugify(value: str) -> str:
    """Filesystem-safe form of a venue or ticker: ``GC=F`` becomes ``GC_F``.

    Upper-cased, which matters: the corpus and the store both key on the
    result, and a case difference between a writer and a reader is a cache
    miss that looks like missing data.
    """
    return _SLUG.sub("_", value).strip("_").upper()
