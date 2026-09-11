"""Every feed comparison in the rebuild, in one command.

`.secrets/lab.sh` runs one script and writes one flag, so five studies is five
launches and five waits. This is the one launch:

    ./.secrets/lab.sh run research/harness/rebuildall.py

It runs `rebuildvol`, `rebuildstep`, `rebuildspike`, `rebuildjudge` and
`rebuildpower` in that order, in one process, and keeps going when one of them
raises - a broken study should cost its own results and not the other four. Each
study writes its own JSON exactly as it does when run alone; this adds one more,
`rebuildall.json`, holding the pooled failure ledger and the wall time of each.

The order matters in one place only: `rebuildpower` and `rebuildjudge` import the
others for their simulators, so nothing here may be run in a subprocess that does
not share the same `research.db`.

**This file states no failure conditions of its own.** Every condition belongs to
the study that owns it and is in that study's docstring, written before any
number. What this adds is that they all run on one sample, on one machine, on one
invocation, so the ledger at the end is a single count over a single experiment
rather than five counts that might not be comparable.

## Cost

Roughly forty minutes of one core at the defaults, dominated by `rebuildjudge`'s
discriminator arms and `rebuildvol`'s twelve feeds at ten times the real sample.
Every knob is an environment variable and `lab.sh run` passes them through:

    ./.secrets/lab.sh run research/harness/rebuildall.py MULT=4 BMULT=1 TREES=80

halves it at some cost in resolution, and the resolution is the point, so prefer
the defaults unless the machine cannot carry them.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rebuildgen as G

OUT = os.environ.get("OUT", os.path.expanduser("~/till_infinity/logs/rebuildall.json"))
ONLY = [s for s in os.environ.get("ONLY", "").split(",") if s]

STUDIES = ("rebuildvol", "rebuildstep", "rebuildspike", "rebuildjudge", "rebuildpower")


def main() -> None:
    print("=" * 120)
    print("THE WHOLE REBUILD, ONE INVOCATION")
    print(f"  db {G.DB}   {G.machine()}")
    print("=" * 120)
    results = []
    for name in STUDIES:
        if ONLY and name not in ONLY:
            print(f"\n### skipping {name} (ONLY={','.join(ONLY)})")
            continue
        print("\n" + "#" * 120)
        print(f"### {name}")
        print("#" * 120, flush=True)
        t0 = time.time()
        try:
            mod = __import__(name)
            mod.main()
            ok, err = True, None
        except Exception:
            ok, err = False, traceback.format_exc()
            print(err, flush=True)
        results.append({"study": name, "ok": ok, "seconds": time.time() - t0,
                        "error": (err or "")[-2000:]})
        print(f"\n### {name} {'finished' if ok else 'FAILED'} in "
              f"{results[-1]['seconds']:.0f}s", flush=True)

    print("\n" + "=" * 120)
    print("THE POOLED LEDGER - every pre-registered condition across the five studies")
    print("=" * 120)
    pooled = []
    logs = os.path.dirname(OUT)
    for name in STUDIES:
        path = os.path.join(logs, f"{name}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path) as fh:
                blob = json.load(fh)
        except Exception:
            continue
        for e in blob.get("ledger", []):
            e = dict(e)
            e["study"] = name
            pooled.append(e)
    by: dict[str, list] = {}
    for e in pooled:
        by.setdefault(f"[{e['study']}] {e['test']}", []).append(e)
    print(f"{'condition':74s} {'cells':>6s} {'fired':>6s}")
    nf = 0
    for cond, es in sorted(by.items()):
        fired = [e for e in es if e.get("fired")]
        nf += len(fired)
        if fired:
            print(f"{cond:74s} {len(es):6d} {len(fired):6d}   <- fired")
        else:
            print(f"{cond:74s} {len(es):6d} {len(fired):6d}")
    print(f"\n{len(pooled)} pre-registered comparisons across "
          f"{len({e['study'] for e in pooled})} studies, {nf} fired.")
    print("\ntiming:")
    for r in results:
        print(f"  {r['study']:14s} {'ok' if r['ok'] else 'FAILED':>7s} "
              f"{r['seconds']:8.0f}s")

    os.makedirs(logs, exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump({"studies": results, "ledger": pooled}, fh, indent=1, default=float)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
