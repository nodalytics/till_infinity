"""What the desk places against what it is paid, reconciled on the broker's own record.

The book loses 2,196 over 1,244 closed trades at a 49.0% win rate, with the
average loss 29% larger than the average win. That is a coin flip paying a
spread, and the question is where in the geometry it goes.

The entry order carries the stop and target **as placed**; the deals carry what
was **paid**. Joining them on `position_id` is the only way to compare intent
with outcome, and the two disagree in a way neither shows alone.

    docker exec till-infinity python geometry.py
"""

import datetime as dt
import json
import os
import statistics
import urllib.parse
import urllib.request
from collections import defaultdict

key = os.environ["TRADING_MT5_API_KEY"]
base = "http://host.docker.internal:8000/api/v1"
since = (dt.datetime.now(dt.UTC) - dt.timedelta(days=180)).strftime("%Y-%m-%d %H:%M:%S")
until = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")


def get(path):
    url = f"{base}/{path}?" + urllib.parse.urlencode({"from_date": since, "to_date": until})
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"X-API-Key": key}), timeout=180
    ) as r:
        return json.loads(r.read())


orders, deals = get("history/orders"), get("history/deals")

# The entry order for a position carries the stop and target as placed.
placed = {}
for o in orders:
    pid = o.get("position_id")
    if pid is None:
        continue
    sl, tp, px = o.get("sl") or 0.0, o.get("tp") or 0.0, o.get("price_open") or 0.0
    if sl and tp and px and pid not in placed:
        placed[pid] = {
            "px": float(px),
            "sl": float(sl),
            "tp": float(tp),
            "sym": str(o.get("symbol") or ""),
        }

by_pos = defaultdict(lambda: {"net": 0.0, "legs": 0, "reasons": set()})
REASON = {3: "expert", 4: "stop loss", 5: "take profit"}
for d in deals:
    pid = d.get("position_id")
    if pid is None or d.get("entry") is None or int(d["entry"]) == 0:
        continue
    profit = d.get("profit")
    if not isinstance(profit, int | float):
        continue
    p = by_pos[pid]
    p["net"] += profit + float(d.get("commission") or 0) + float(d.get("swap") or 0)
    p["legs"] += 1
    p["reasons"].add(REASON.get(int(d.get("reason", -1)), "other"))

rows = []
for pid, out in by_pos.items():
    g = placed.get(pid)
    if not g:
        continue
    stop = abs(g["px"] - g["sl"])
    target = abs(g["tp"] - g["px"])
    if stop <= 0 or target <= 0:
        continue
    rows.append(
        {
            "ratio": target / stop,
            "net": out["net"],
            "legs": out["legs"],
            "reasons": out["reasons"],
            "sym": g["sym"],
        }
    )

print(f"positions with both a placed stop and target: {len(rows):,}\n")
ratios = [r["ratio"] for r in rows]
print(
    f"PLACED target:stop  median {statistics.median(ratios):.2f}   "
    f"mean {statistics.fmean(ratios):.2f}   "
    f"p10 {sorted(ratios)[len(ratios) // 10]:.2f}   "
    f"p90 {sorted(ratios)[9 * len(ratios) // 10]:.2f}"
)

tp = [r for r in rows if "take profit" in r["reasons"]]
sl = [r for r in rows if "stop loss" in r["reasons"] and "take profit" not in r["reasons"]]
if tp and sl:
    aw = statistics.fmean([r["net"] for r in tp])
    al = statistics.fmean([r["net"] for r in sl])
    print(
        f"\nREALISED            target pays {aw:+.2f}   stop costs {al:+.2f}   "
        f"money ratio {abs(aw / al):.2f}"
    )
    print(
        f"                    {len(tp)} targets against {len(sl)} stops "
        f"= {len(tp) / (len(tp) + len(sl)):.1%} hit rate"
    )
    r_med = statistics.median(ratios)
    fair = 1.0 / (1.0 + r_med)
    print(f"\nA {r_med:.2f}:1 geometry needs a {fair:.1%} hit rate to break even on a martingale.")
    print(
        f"It is getting {len(tp) / (len(tp) + len(sl)):.1%}, and paying "
        f"{abs(aw / al):.2f}:1 rather than {r_med:.2f}:1."
    )

print("\nby placed ratio band:")
bands = [(0, 1.0), (1.0, 1.5), (1.5, 2.5), (2.5, 4.0), (4.0, 99.0)]
for lo, hi in bands:
    items = [r for r in rows if lo <= r["ratio"] < hi]
    if len(items) < 15:
        continue
    w = [r["net"] for r in items if r["net"] > 0]
    net = sum(r["net"] for r in items)
    print(
        f"  {lo:>4.1f}-{hi:<5.1f} n={len(items):<5} NET {net:>9.2f}  "
        f"win {len(w) / len(items):>4.0%}  per trade {net / len(items):>7.2f}"
    )
