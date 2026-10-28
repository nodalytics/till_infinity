"""Models trained offline and shipped as data.

The `*.json` files here are the shipped models, read by `shared/frozen.py`:
`MODELS_DIR/<name>.json` first, then these. They stay in the package because
`structures/vol/envelope.py` and `structures/learning/shocks.py` still read
them and the structures service is retired next, not now.

**The trainers are gone.** `retrain.py`, the five `*_train.py` scripts and
`bridge.py` moved to `research/retire/models/` on 2026-10-28 with the structures
models they were for. So these files are frozen at the last version promoted
into service, and nothing in the package can produce a new one.
"""
