"""What every service needs and none of them owns.

Each service here is its own package with its own settings, store and loop,
which is the right shape - `prices` should not import `trading` to find out
how to read an environment variable. What that shape does not do on its own is
stop six packages solving the same small problem six times, and this folder is
where those solutions live once.

The bar for putting something here is that it is **shared and boring**: the
same job, in more than one service, with no per-service judgement in it.
Anything carrying a decision belongs to the service that made it.

Nothing is re-exported from here, deliberately. `env.py` holds a function
called `env`, so a package-level re-export would shadow the module it came
from and `from till_platform import env` would hand back the function - which
it did, and the test written to prove the module worked was the thing that
tripped on it. Import the module (`from till_platform import env`) or the
function (`from till_platform.env import env`), and let the import say which.

**This was `till_infinity/shared/` until 2026-10-29.** It became a package when
`services/statespace` had to stand on its own: a service cannot carry its own
dependency manifest while importing the desk it is meant to be separable from.
The JSON contracts stay at the repository root, because Go reads them.
"""
