/**
 * Talking to the read-only Python service.
 *
 * Relative URLs throughout: `next.config.ts` proxies `/api` to the service, so
 * the browser never learns its address and nothing has to be configured in two
 * places. A failed request raises with the status and the body, because a
 * dashboard that silently renders zeros over a service that is down is the one
 * failure mode worth more than a blank panel.
 */

import type {
  Activity,
  Book,
  Chart,
  Filters,
  Health,
  Levels,
  Overview,
  Series,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
  }
}

async function get<T>(path: string, params: Record<string, string> = {}, signal?: AbortSignal) {
  const query = new URLSearchParams(params).toString();
  const response = await fetch(query ? `${path}?${query}` : path, {
    signal,
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.text();
    let detail = body.slice(0, 400);
    try {
      const parsed: unknown = JSON.parse(body);
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        detail = String((parsed as { detail: unknown }).detail);
      }
    } catch {
      // Not JSON. The raw body is the better message anyway.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

/** Only the filters that are actually set; an empty one means "everything". */
function asParams(filters: Filters): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.days) params.days = String(filters.days);
  if (filters.mode) params.mode = filters.mode;
  if (filters.strategy) params.strategy = filters.strategy;
  if (filters.feed) params.feed = filters.feed;
  return params;
}

export function fetchHealth(signal?: AbortSignal) {
  return get<Health>("/api/health", {}, signal);
}

export function fetchOverview(filters: Filters, signal?: AbortSignal) {
  return get<Overview>("/api/overview", asParams(filters), signal);
}

export function fetchActivity(hours: number, signal?: AbortSignal) {
  return get<Activity>("/api/activity", { hours: String(hours) }, signal);
}

export function fetchBook(signal?: AbortSignal) {
  return get<Book>("/api/book", {}, signal);
}

export function fetchLevels(signal?: AbortSignal) {
  return get<Levels>("/api/levels", {}, signal);
}

export function fetchSeries(signal?: AbortSignal) {
  return get<Series[]>("/api/series", {}, signal);
}

export function fetchChart(
  feed: string,
  interval: string,
  source: string,
  filters: Filters,
  signal?: AbortSignal,
) {
  // The chart's own feed decides which markers are drawn, so the page's feed
  // filter is left out: filtering to one feed and charting another would
  // otherwise draw no markers at all and look like missing data.
  return get<Chart>(
    "/api/chart",
    { ...asParams({ ...filters, feed: "" }), feed, interval, source },
    signal,
  );
}
