"""Does streaming the save actually remove the transient that was killing us?

`research/starving.md` measured the cause: holding production's 206MB state
costs 1.33GB resident, and `store.save` adds **+0.58GB** on top of it. Against a
2.6GB container limit and a 1.45GB baseline, that is the whole margin - and it
is why the desk was OOM-killed 23 times between 1 and 10 September while hourly
sampling showed a flat baseline. The spike lives entirely between samples.

`codec.pack_into` replaces `write_bytes(msgpack.packb(pack(state)))`, which
holds three copies of everything at the moment of the write: the live state, the
plain-dict tree `pack` builds, and the contiguous `bytes` `packb` renders. This
measures whether walking and emitting instead actually costs one buffer.

Two things are being asked, and the second is the one that could quietly undo
the first:

1. **Peak resident memory**, old path against new, each in its own process so
   `ru_maxrss` means what it says.
2. **Time.** Streaming makes hundreds of thousands of small `pack()` calls
   where the old path made one. A save that no longer spikes but takes a minute
   is not obviously better on a service that saves periodically.

And one correctness check that has to pass before either number matters: the
bytes must be **identical**. If they are not, this is a migration rather than an
optimisation, and the 206MB of learned state on disk is what pays for the
difference.

Usage:
    STATE=~/till_infinity/data/models.msgpack python3 -m research.harness.savestream
"""

from __future__ import annotations

import gc
import hashlib
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATE = Path(os.environ.get("STATE", "~/till_infinity/data/models.msgpack")).expanduser()


def peak_gb() -> float:
    """Peak resident set for this process, in GB. Monotonic, hence one per run."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576


def load_state():
    """The real state, restored into real objects - which is what a save holds."""
    import msgpack

    from till_infinity.structures.codec import unpack

    raw = STATE.read_bytes()
    payload = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    del raw
    gc.collect()
    state = unpack(payload.get("state") or {})
    del payload
    gc.collect()
    return state


def run_old(state, out: Path) -> tuple[float, float]:
    """What `store.save` did until now: pack the whole tree, render, write."""
    import msgpack

    from till_infinity.structures.codec import pack
    from till_infinity.structures.store import _fingerprint

    began = time.monotonic()
    payload = {**_fingerprint(), "state": pack(state)}
    blob = msgpack.packb(payload, use_bin_type=True)
    out.write_bytes(blob)
    took = time.monotonic() - began
    del payload, blob
    gc.collect()
    return peak_gb(), took


def run_new(state, out: Path) -> tuple[float, float]:
    """What it does now: walk the structure and emit as it goes."""
    from till_infinity.structures.store import _fingerprint, _stream

    began = time.monotonic()
    with out.open("wb") as handle:
        _stream(state, _fingerprint(), handle)
    took = time.monotonic() - began
    gc.collect()
    return peak_gb(), took


def child(which: str) -> None:
    """One path, in its own process, so the peak belongs to it alone."""
    base = peak_gb()
    state = load_state()
    held = peak_gb()
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory) / "out.msgpack"
        peak, took = (run_old if which == "old" else run_new)(state, out)
        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        size = out.stat().st_size
    print(
        f"RESULT {which} base={base:.3f} held={held:.3f} peak={peak:.3f} "
        f"added={peak - held:.3f} secs={took:.1f} size={size} sha={digest}"
    )


def run() -> None:
    if not STATE.exists():
        print(f"no state at {STATE}")
        sys.exit(1)
    print(f"state file: {STATE.stat().st_size / 1048576:.0f} MB\n")

    got = {}
    for which in ("old", "new"):
        proc = subprocess.run(
            [sys.executable, "-u", __file__, which],
            capture_output=True,
            text=True,
            check=False,
            # **Pinned, or the byte comparison is meaningless.** `pack` walks
            # sets, and a `frozenset` of strings iterates in an order that
            # depends on string hashing, which is salted per process. Without
            # this the two children write the same 216,000,789 bytes in a
            # different order and the check reports a difference that is not
            # one - the same two writers in a single process are identical.
            env={
                **os.environ,
                "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
                "PYTHONHASHSEED": "0",
            },
        )
        line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT")), None)
        if line is None:
            print(f"{which} failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
            sys.exit(1)
        got[which] = dict(part.split("=", 1) for part in line.split()[2:])
        print(f"  {which}: {line.split(' ', 2)[2]}")

    print()
    same = got["old"]["sha"] == got["new"]["sha"]
    print(f"identical bytes: {same}  ({got['old']['size']} vs {got['new']['size']})")
    if not same:
        print("  ** STOP ** - this would be a migration, not an optimisation")

    added_old = float(got["old"]["added"])
    added_new = float(got["new"]["added"])
    print(f"\n  {'path':>8s} {'held GB':>9s} {'peak GB':>9s} {'added GB':>9s} {'secs':>7s}")
    for which in ("old", "new"):
        g = got[which]
        print(
            f"  {which:>8s} {float(g['held']):9.3f} {float(g['peak']):9.3f} "
            f"{float(g['added']):9.3f} {float(g['secs']):7.1f}"
        )
    print(
        f"\n  the transient falls from {added_old:.3f} GB to {added_new:.3f} GB "
        f"({added_old - added_new:+.3f})"
    )
    slower = float(got["new"]["secs"]) - float(got["old"]["secs"])
    print(f"  and the save takes {slower:+.1f}s longer")
    print("\nAgainst a 2.6GB limit on a 1.45GB baseline, the margin was 1.15GB and")
    print("the old save spent half of it. What is left is the cost of *holding*")
    print("the state, which is a different problem and the next one.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("old", "new"):
        child(sys.argv[1])
    else:
        run()
