"""Would taking partial profit have changed the book, or did the desk only slice winners?

**Answered: mostly selection, but the rule is worth +0.047R a trade.**
Applied to all 697 replayable positions rather than the 59 that were sliced:
hold-to-barrier returns -0.068R a trade, slicing 50% at 1R returns -0.020R -
better on 85, worse on 42, unchanged on 570, which is a sign test at about
z = 3.8. The win rate rises 25% to 34% while the average win falls 0.81R to
0.67R, because the breakeven stop scratches trades that would have run; the
net of those two is positive.

**It is not enough.** -0.068R a trade is `E[net] = -(c/2) x turnover` measured
directly, and cutting 70% of a bleed leaves a bleed.

The record says sliced positions returned +836.85 at a 4.24 win/loss ratio with a
90% win rate, against -3,025.73 at 0.80 for the 1,123 that were closed whole.
That is the largest effect in the book - and it is exactly the shape a selection
effect takes, because a desk that slices trades already going well would produce
the same table with slicing doing nothing at all.

**So the policy is applied to every position, not to the ones that were sliced.**
Identical entries, identical stops and targets, identical price paths; the only
difference is the exit rule. A difference that survives that is the rule.

Scored in **R** - multiples of the position's own stop distance - so symbols with
different tick values are comparable and no conversion can go wrong.
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
DAYS = 45
TAKE_AT = 1.0  # R at which half comes off
SHARE = 0.5  # how much comes off

since_dt = dt.datetime.now(dt.UTC) - dt.timedelta(days=DAYS)
since = since_dt.strftime("%Y-%m-%d %H:%M:%S")
until = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")


def get(path, **params):
    url = f"{base}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(
        urllib.request.Request(url, headers={"X-API-Key": key}), timeout=180
    ) as r:
        return json.loads(r.read())


orders = get("history/orders", from_date=since, to_date=until)
deals = get("history/deals", from_date=since, to_date=until)

placed = {}
for o in orders:
    pid = o.get("position_id")
    sl, tp, px = o.get("sl") or 0.0, o.get("tp") or 0.0, o.get("price_open") or 0.0
    if pid is not None and sl and tp and px and pid not in placed:
        placed[pid] = {
            "px": float(px),
            "sl": float(sl),
            "tp": float(tp),
            "sym": str(o.get("symbol") or ""),
        }

pos = defaultdict(lambda: {"open": None, "close": None, "net": 0.0, "legs": 0})
for d in deals:
    pid = d.get("position_id")
    if pid is None:
        continue
    p = pos[pid]
    t = float(d.get("time") or 0)
    if d.get("entry") is not None and int(d["entry"]) == 0:
        p["open"] = t if p["open"] is None else min(p["open"], t)
    else:
        p["close"] = t if p["close"] is None else max(p["close"], t)
        profit = d.get("profit")
        if isinstance(profit, int | float):
            p["net"] += profit + float(d.get("commission") or 0) + float(d.get("swap") or 0)
            p["legs"] += 1

trades = []
for pid, p in pos.items():
    g = placed.get(pid)
    if not g or not p["open"] or not p["close"] or p["legs"] == 0:
        continue
    stop = abs(g["px"] - g["sl"])
    if stop <= 0:
        continue
    trades.append(
        {
            "sym": g["sym"],
            "open": p["open"],
            "close": p["close"],
            "net": p["net"],
            "px": g["px"],
            "sl": g["sl"],
            "tp": g["tp"],
            "stop": stop,
            "long": g["tp"] > g["px"],
            "legs": p["legs"],
            "target_r": abs(g["tp"] - g["px"]) / stop,
        }
    )
print(
    f"replayable positions in {DAYS} days: {len(trades):,} "
    f"across {len({t['sym'] for t in trades})} symbols"
)

# One bar pull per symbol, sliced in memory.
bars: dict[str, list[tuple[float, float, float]]] = {}
for sym in sorted({t["sym"] for t in trades}):
    try:
        rows = get("symbols/rates/range", symbol=sym, timeframe="M1", start=since, end=until)
    except Exception as exc:  # noqa: BLE001
        print(f"  {sym}: bars unavailable ({str(exc)[:40]})")
        continue
    out = []
    for r in rows if isinstance(rows, list) else []:
        try:
            t = dt.datetime.fromisoformat(str(r["time"])).replace(tzinfo=dt.UTC).timestamp()
            out.append((t, float(r["high"]), float(r["low"])))
        except (KeyError, TypeError, ValueError):
            continue
    bars[sym] = sorted(out)
print(f"symbols with bars: {sum(1 for v in bars.values() if v)}")


def path_for(t):
    rows = bars.get(t["sym"]) or []
    return [b for b in rows if t["open"] <= b[0] <= t["close"] + 60]


def replay(t, sliced: bool) -> float | None:
    """Outcome in R. `sliced` takes `SHARE` off at `TAKE_AT` R and moves the
    stop on the remainder to breakeven."""
    rows = path_for(t)
    if len(rows) < 2:
        return None
    sign = 1.0 if t["long"] else -1.0
    stop_at = t["sl"]
    booked = 0.0
    live = 1.0
    took = False
    for _, high, low in rows:
        best = (high - t["px"]) * sign / t["stop"] if t["long"] else (t["px"] - low) / t["stop"]
        worst = (low - t["px"]) * sign / t["stop"] if t["long"] else (t["px"] - high) / t["stop"]
        if sliced and not took and best >= TAKE_AT:
            booked += SHARE * TAKE_AT
            live -= SHARE
            took = True
            stop_at = t["px"]  # breakeven on the remainder
        hit_stop = low <= stop_at if t["long"] else high >= stop_at
        hit_target = high >= t["tp"] if t["long"] else low <= t["tp"]
        if hit_target:
            return booked + live * t["target_r"]
        if hit_stop:
            loss = 0.0 if (sliced and took) else -1.0
            return booked + live * loss
        _ = worst
    # Never resolved inside the window: mark at the last close-ish price.
    return booked + live * 0.0


rows = []
for t in trades:
    a = replay(t, sliced=False)
    b = replay(t, sliced=True)
    if a is None or b is None:
        continue
    rows.append(
        {"actual_r": a, "sliced_r": b, "sym": t["sym"], "net": t["net"], "target_r": t["target_r"]}
    )

print(f"positions replayed with a usable path: {len(rows):,}\n")
if not rows:
    raise SystemExit


def block(label, key):
    vals = [r[key] for r in rows]
    w = [v for v in vals if v > 0]
    losses = [v for v in vals if v < 0]
    aw = statistics.fmean(w) if w else 0.0
    al = statistics.fmean(losses) if losses else 0.0
    print(
        f"  {label:22} total {sum(vals):>9.2f}R   per trade {statistics.fmean(vals):>7.3f}R   "
        f"win {len(w) / len(vals):>4.0%}   avg win {aw:>6.2f}R   avg loss {al:>6.2f}R"
    )


print("replayed on identical paths, every position, same entries and barriers:")
block("hold to barrier", "actual_r")
block(f"slice {SHARE:.0%} at {TAKE_AT:.0f}R", "sliced_r")
diff = statistics.fmean([r["sliced_r"] - r["actual_r"] for r in rows])
better = sum(1 for r in rows if r["sliced_r"] > r["actual_r"])
worse = sum(1 for r in rows if r["sliced_r"] < r["actual_r"])
print(
    f"\n  slicing changes {diff:+.3f}R per trade   better on {better}, worse on {worse}, "
    f"same on {len(rows) - better - worse}"
)
