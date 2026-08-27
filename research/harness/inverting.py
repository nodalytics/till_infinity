"""When risk exceeds the expected push, is the other side the better trade?

The proposal: if a call's `risk_vol` is larger than its `expected_push_vol`,
the trade has negative expectancy as modelled - so take the opposite side.

**The arithmetic does not carry the argument.** A bad expectancy in one
direction is not a good one in the other; the model's push estimate belongs to
the direction it named, and flipping gives an unknown expectation rather than
the mirror of a known bad one. The premise only holds if the model is
*anti-predictive* specifically on this subset, which is a fact about the data.

So this measures it. For every resolved touch, both trades are scored:

* **with** the call - favourable movement is the realised push, adverse is the
  excursion,
* **against** it - the mirror, favourable is the excursion and adverse is the
  push.

Bucketed by `risk_vol / expected_push_vol`, the ratio the proposal keys on.

**The mirror is an approximation and its limit should be stated.** It ignores
ordering: a touch that ran 2v against before going 3v in favour scores the
same here as one that did the reverse, and the two are different trades - one
is stopped, the other is not. It is the standard way to score a hypothetical
opposite side and it is optimistic about both directions equally, which is
what keeps the *comparison* fair even though neither number is a P&L.

Usage: python -m research.harness.inverting [journal.db]
"""

import json
import sqlite3
import sys


def load(db):
    """Outcomes joined to the signals that produced them.

    `risk_vol` and `expected_push_vol` live on the signal, the realised push
    and excursion on the outcome, so the ratio the proposal keys on and the
    result it has to be judged against are in different records. The journal's
    parent link is the join - every outcome names the observation it came from.
    """
    con = sqlite3.connect(db)
    signals = {}
    q = "select id,context from entries where actor='structures' and kind='observation'"
    for entry_id, ctx in con.execute(q):
        d = json.loads(ctx or "{}")
        risk, expected = d.get("risk_vol"), d.get("expected_push_vol")
        if risk is None or not expected:
            continue
        signals[entry_id] = abs(float(risk)) / abs(float(expected))

    out = []
    q = "select parent,context from entries where actor='structures' and kind='outcome'"
    for parent, ctx in con.execute(q):
        ratio = signals.get(parent)
        if ratio is None:
            continue
        d = json.loads(ctx or "{}")
        push, excursion = d.get("push_vol"), d.get("excursion_vol")
        if push is None or excursion is None:
            continue
        out.append(
            {
                "push": abs(float(push)),
                "excursion": abs(float(excursion)),
                "ratio": ratio,
            }
        )
    return out


def r_of(good, bad, stop=0.5, target=0.75):
    """R for a trade whose favourable move is `good` and adverse is `bad`."""
    if bad >= stop:
        return -1.0
    return (target / stop) if good >= target else 0.0


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else ".data/journal/journal.db"
    rows = load(db)
    print(f"{len(rows):,} resolutions carrying both risk and expected push\n")
    if len(rows) < 1000:
        print("not enough to say anything")
        return

    over = [r for r in rows if r["ratio"] > 1.0]
    under = [r for r in rows if r["ratio"] <= 1.0]
    print(f"risk exceeds expected push on {len(over):,} of {len(rows):,} "
          f"({len(over) / len(rows):.0%})\n")

    print(f"{'subset':>26s} {'n':>8s} {'R with':>8s} {'R against':>10s} {'better':>8s}")
    print("-" * 65)
    for name, group in (
        ("risk > expected push", over),
        ("risk <= expected push", under),
        ("everything", rows),
    ):
        if not group:
            continue
        w = sum(r_of(r["push"], r["excursion"]) for r in group) / len(group)
        a = sum(r_of(r["excursion"], r["push"]) for r in group) / len(group)
        print(f"{name:>26s} {len(group):>8,} {w:>8.3f} {a:>10.3f} "
              f"{'against' if a > w else 'with':>8s}")

    print("\nby how far risk exceeds the push")
    ordered = sorted(rows, key=lambda r: r["ratio"])
    size = len(ordered) // 8
    print(f"{'ratio':>16s} {'n':>8s} {'R with':>8s} {'R against':>10s}")
    print("-" * 46)
    for i in range(8):
        chunk = ordered[i * size : (i + 1) * size] if i < 7 else ordered[7 * size :]
        if not chunk:
            continue
        w = sum(r_of(r["push"], r["excursion"]) for r in chunk) / len(chunk)
        a = sum(r_of(r["excursion"], r["push"]) for r in chunk) / len(chunk)
        print(f"{chunk[0]['ratio']:>7.2f}-{chunk[-1]['ratio']:<8.2f} "
              f"{len(chunk):>8,} {w:>8.3f} {a:>10.3f}")


if __name__ == "__main__":
    main()
