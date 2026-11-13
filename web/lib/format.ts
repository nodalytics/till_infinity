/**
 * Printing numbers the way the desk's own reports print them.
 *
 * R always carries its sign, because the sign is the result and a bare `0.43`
 * in a table of returns reads as a gain. Times are UTC: the journal records
 * unix seconds and the desk's hour-of-day features are in UTC, so rendering a
 * viewer's local midnight would put a trade in the wrong session.
 */

const UTC = "UTC";

export function signedR(value: number, places = 2): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(places)}R`;
}

export function money(value: number, places = 2): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(places)}`;
}

export function percent(value: number, places = 0): string {
  return `${(value * 100).toFixed(places)}%`;
}

/** A duration a person can compare at a glance: 57s, 14m, 3h 20m, 2d. */
export function duration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 90) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 90) return `${Math.round(minutes)}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    const rest = Math.round(minutes - hours * 60);
    return rest ? `${hours}h ${rest}m` : `${hours}h`;
  }
  return `${Math.round(hours / 24)}d`;
}

/** An age in words: "4 minutes ago", "77 days ago". */
export function ago(seconds: number): string {
  if (!Number.isFinite(seconds)) return "unknown";
  if (seconds < 45) return `${Math.max(0, Math.round(seconds))}s ago`;
  const minutes = seconds / 60;
  if (minutes < 90) return `${Math.round(minutes)} min ago`;
  const hours = minutes / 60;
  if (hours < 36) return `${Math.round(hours)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function stamp(seconds: number | null): string {
  if (seconds == null) return "—";
  return new Date(seconds * 1000).toLocaleString("en-GB", {
    timeZone: UTC,
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function day(seconds: number | null): string {
  if (seconds == null) return "—";
  return new Date(seconds * 1000).toLocaleDateString("en-GB", {
    timeZone: UTC,
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** The span the figures cover, said in words rather than as two timestamps. */
export function span(first: number | null, last: number | null): string {
  if (first == null || last == null) return "no trades in this window";
  if (day(first) === day(last)) return day(first);
  return `${day(first)} to ${day(last)}`;
}

export function tone(value: number): "up" | "down" | "flat" {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}
