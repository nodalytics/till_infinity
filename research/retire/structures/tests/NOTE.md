# tests moved with their subject, 2026-10-31

These exercise `structures/` internals - `Watcher`, `Call`, `har`, `cycles`,
`alert_payload`, `Learned`, the package's own codec - and moved here when the
package did.

**One of them is worth re-homing rather than leaving.**
`test_state.py::test_an_unbounded_stored_deque_is_given_the_bound` is the
`restore-drops-deque-maxlen` lesson: a capped deque field came back unbounded
from a restore while the declaration still looked correct. That failure is
available to any persisted dataclass, including the ones `statespace` and
`strategies` still keep - so the assertion belongs wherever the state codec
ends up, not in a retired package's tests.
