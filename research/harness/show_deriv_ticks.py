"""Print deriv_ticks.py's results compactly (run on the lab)."""
import json
import sys

d = json.load(open(sys.argv[1]))
for sym, c in d.items():
    print("==", sym, "| fresh compressed bars:", c.get("fresh_compressed_bars"))
    for part in ("held_out_bars", "held_out_ticks", "fresh_ticks"):
        for arm, v in c.get(part, {}).items():
            print(f"  {part:15s} {arm:10s} n={v.get('n', 0):5d} R={v.get('R')} halves={v.get('halves')} ticks={v.get('tick_fills')}")
    print("  survives:", c["survives"])
