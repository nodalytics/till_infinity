/**
 * Horizontal lines the viewer places, kept per feed.
 *
 * One drawing tool, not six. `lightweight-charts` has no drawing layer, and a
 * price line is the one shape its series API draws properly - it tracks the
 * price scale, survives a zoom and labels itself on the axis. A trend line
 * would need a custom primitive and two anchors that stay put through a
 * rescale, and a half-working one is worse than none.
 *
 * Stored per feed rather than per feed and interval: a price level means the
 * same thing at 5m and at 1h, and splitting them would lose a line the moment
 * someone changed timeframe.
 *
 * Every `localStorage` call is wrapped. It throws in a private window and can
 * come back empty with site data blocked, and the chart has to draw either
 * way - a missing line is a nuisance, an exception on mount is a blank page.
 */

const KEY = "till-infinity.lines";

type Store = Record<string, number[]>;

function all(): Store {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return {};
    const out: Store = {};
    for (const [feed, values] of Object.entries(parsed as Record<string, unknown>)) {
      if (Array.isArray(values)) {
        out[feed] = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
      }
    }
    return out;
  } catch {
    return {};
  }
}

function save(store: Store): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(store));
  } catch {
    // Not remembered. The lines still draw for this session.
  }
}

export function lines(feed: string): number[] {
  return all()[feed] ?? [];
}

export function addLine(feed: string, price: number): number[] {
  const store = all();
  const kept = [...(store[feed] ?? []), price].sort((a, b) => b - a);
  store[feed] = kept;
  save(store);
  return kept;
}

export function dropLine(feed: string, price: number): number[] {
  const store = all();
  const kept = (store[feed] ?? []).filter((value) => value !== price);
  store[feed] = kept;
  save(store);
  return kept;
}
