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
from and `from ..shared import env` would hand back the function - which it
did, and the test written to prove the module worked was the thing that
tripped on it. Import the module (`from ..shared import env`) or the function
(`from ..shared.env import env`), and let the import say which.
"""
