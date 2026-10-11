# Retired

Code that ran and has been taken out of the live system. It is moved here
rather than deleted, because the measurements that justified it and the
measurements that ended it are both part of the record, and a reader who finds
a reference to one of these in `research/docs/` should be able to read the
thing being referred to.

**Nothing here is imported by the package.** That is the point of the move: a
retired service that still sits on the import graph is not retired, it is
dormant, and dormant code gets restarted by accident. Each directory keeps its
own tests beside it so that the claim "it worked when it was removed" stays
checkable, but they are out of the suite that gates CI.

| retired | when | why |
|---|---|---|
| `mcfl` | 2026-10-11 | superseded by `structures/statespace`. A pattern detector over a few hundred alt coins, alert-only. The statespace family answers the same question - "is this instrument away from where it should be, and by how much" - as a **predictive distribution** with a likelihood that can be scored against a null, rather than as a pattern that either matched or did not. Retired to the record, not because it broke. |

## What retiring means here

1. The code and its tests move into `research/retire/<name>/`.
2. Every import, CLI command, service entry and setting is removed, so the
   live system has no path to it.
3. The research docs that cite it stay where they are and keep citing it. The
   findings did not stop being true.

## What mcfl left behind

Two things outlived the service and are flagged rather than quietly removed:

* `notifications/models.py` keeps the `pattern` and `exit` alert shapes, which
  now have **no producer**. That is bug shape #4 in the `finding-bugs` skill -
  computed, published and read by nothing - and it is left deliberately,
  because the vocabulary belongs to the notifications layer rather than to
  `mcfl`. If nothing claims them, they should go.
* `research/docs/mcfl.md`, `mcfl-roadmap.md` and the half-dozen studies that
  cite them stay. `docs/img/mcfl/` keeps the example cards, because a document
  describing what the alerts looked like needs them.

Every `MCFL_*` setting is removed from `docs/environment.md`. They are gone
rather than ignored: nothing reads them, so a deployment still setting them is
setting nothing.
