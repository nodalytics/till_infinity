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
| `models` | 2026-10-28 | the offline retraining pipeline: `retrain.py`, five `*_train.py` trainers, `bridge.py` and the GitHub Actions workflow that ran it fortnightly. Retired because everything it trained is a **structures** model - the shock forecaster, the boosted FX envelope, the touch models - and structures is being retired. Promoting a challenger into a service that is switched off is work with no reader. The `*.json` models stay in `till_infinity/models/`, because `shared/frozen.py` still reads them. |
| `agents` | 2026-10-28 | an LLM analyst over the stored data, and `council`, the one strategy that asked it for a side. Retired on the product owner's call as part of the move to self-contained services ([ADR 0002](../../docs/adr/0002-services-are-self-contained.md)): it was the only service needing a paid credential, and the desk's measured record is that everything which survived a null predicts **size** and nothing predicts direction, so a panel of models voting on a side was paying for an answer the rest of the desk had already found it could not give. `trading/valuation.py`'s LLM valuer went with it - it had no caller in production. |
| `mcfl` | 2026-10-11 | superseded by `structures/statespace`. A pattern detector over a few hundred alt coins, alert-only. The statespace family answers the same question - "is this instrument away from where it should be, and by how much" - as a **predictive distribution** with a likelihood that can be scored against a null, rather than as a pattern that either matched or did not. Retired to the record, not because it broke. |

## What retiring means here

1. The code and its tests move into `research/retire/<name>/`.
2. Every import, CLI command, service entry and setting is removed, so the
   live system has no path to it.
3. The research docs that cite it stay where they are and keep citing it. The
   findings did not stop being true.
4. **The directory goes, not just the files in it.** `git mv` of every `.py`
   out of `till_infinity/agents/` left `__pycache__` behind, and Python treats
   a bare directory as a namespace package - so `from till_infinity import
   agents` still succeeded, and `test_stack.py`'s entry-point check went on
   passing against a package whose every module had been moved out from under
   it. `tests/test_service_boundaries.py::test_a_retired_package_is_not_importable`
   now asserts this for each name in its `RETIRED` tuple.

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

## What agents left behind

Five things outlived the service. Four are flagged; the fifth had to be fixed.

* **`statespace.signals` lost its only consumer, and that is a bug shape this
  desk had already been bitten by.** `statespace/service.py` publishes a
  transition notice there, gated by a setting whose docstring said it was on
  "because a topic with no traffic teaches a consumer nothing" - and `agents`
  was the consumer. With agents retired, the reason inverted into traffic with
  no reader, which is exactly how `statespace.proposals` went unconsumed for
  weeks: a producer's own tally counts what it *sent*, so nothing looks wrong.
  The setting now defaults to **off**, and the tests that exercise the notice
  name `signals=True` themselves. Either a consumer or silence; this is silence
  until something wants the notice. Every reading is still on
  `statespace.dispersion`.

* `notifications/models.py` keeps the **`agent`** alert shape, which now has no
  producer - the same bug shape as `mcfl`'s `pattern` and `exit` above, and
  left for the same reason: the vocabulary belongs to the notifications layer.
  The live instance still names it in `NOTIFY_SHAPES`, which is harmless and
  should be trimmed on the next environment change.
* `trading/config.py` keeps **`"council"` in `MAGIC_ORDER`**, and must. The
  tuple is append-only and positional: removing an entry shifts every strategy
  after it onto a different magic number, which would relabel live positions as
  their neighbours. A retired strategy keeps its slot forever.
* `README.md`'s architecture diagram still routes `structures.signals` to
  `agents` and `trading`. It is **deliberately not updated yet**: the structures
  service is being retired next, and the diagram would be rewritten twice.
* `docs/journal.md` keeps the `decision` and `observation` entry kinds and
  describes what wrote them, marked as retired. Existing journal entries are
  still readable and still mean what they meant.

`docs/agents.md` moved here with the code, so `docs/README.md` no longer lists
it. `docs/todo.md` keeps its references, which are history rather than
instructions.

## What models left behind

* **`till_infinity/models/` is still a package, and holds only data.** The
  `*.json` files are read by `shared/frozen.py` and by
  `structures/vol/envelope.py` and `structures/learning/shocks.py`, so they
  stay where `frozen.PACKAGED` looks for them. The package's `__init__.py` says
  that nothing in the tree can produce a new one. When structures goes, these
  go with it.
* **`TI_MODELS_DIR` still works and nothing writes to it.** `frozen.py` prefers
  a model found there over the shipped copy and re-reads a changed file within
  five minutes, which is worth keeping - it is how a model gets replaced without
  a deploy. But the thing that used to promote into it is here now, so a model
  arrives by hand or not at all. Said plainly in `docs/environment.md` rather
  than left to be discovered.
* **`bridge.py` went even though it is useful.** It fetches up to 50,000 bars a
  series from the terminal, synchronously and deep, which is exactly the shape
  the tick ingest in [ADR 0003](../../docs/adr/0003-python-and-go.md) needs.
  It is here rather than kept live because its only caller was `retrain.py`,
  and a module with no caller sitting in the package is the same bug shape as a
  topic with no subscriber. Resurrect it from here when the Go service wants
  it, or read it as the reference for what the deep-history route costs.
* **Four test files were split, not moved.** `test_envelope_model.py`,
  `test_deriv_law.py`, `test_expansion.py` and `test_touches.py` each tested
  both halves - training a replacement and reading the shipped model - and the
  reading half is still live. 23 trainer tests came here as `*_trainers.py`;
  34 reader tests stayed in the suite. **One was found by the test run rather
  than by the split**: `test_the_retrain_contest_promotes_passing_cells`
  imported the trainer inside its body instead of at module scope, so a scan of
  module imports said the file was clean. The same shape as the `from .state
  import` relative imports that a package-qualified grep missed.
* `tests/test_envelope_model.py` kept the 50 tests that read the shipped model
  and lost the ten that tested **promotion**: the gates, the contest, and the
  trainer's own replay. Those are in `test_envelope_gates.py` here.
  `test_the_metals_model_conformal_measured_would_not_ship` is the one worth
  reading - the absolute gates were added on 2026-10-07 because the relative
  ones alone would have shipped a metals model whose measured coverage was
  wrong.
