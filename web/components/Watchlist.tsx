"use client";

import { useMemo } from "react";
import { percent, signedR, tone } from "@/lib/format";
import type { Group, Series } from "@/lib/types";

interface Row {
  feed: string;
  group: Group | null;
  chartable: boolean;
}

/**
 * One row per feed: what it traded, and whether there are candles for it.
 *
 * This is the per-feed breakdown. A feed the desk traded that no catalogue on
 * this machine carries is listed and not clickable rather than quietly
 * dropped - the gap between what was traded and what can be charted is itself
 * worth seeing, and here it is eleven traded feeds against six with bars.
 */
export default function Watchlist({
  feeds,
  series,
  picked,
  onPick,
  pooled,
}: {
  feeds: Group[];
  series: Series[];
  picked: string;
  onPick: (feed: string) => void;
  pooled: number;
}) {
  const rows = useMemo<Row[]>(() => {
    const chartable = new Set(series.map((row) => row.feed));
    const traded = new Map(feeds.map((group) => [group.name, group]));
    const names = new Set([...traded.keys(), ...chartable]);
    return [...names]
      .map((feed) => ({
        feed,
        group: traded.get(feed) ?? null,
        chartable: chartable.has(feed),
      }))
      .sort((a, b) => (b.group?.count ?? 0) - (a.group?.count ?? 0) || a.feed.localeCompare(b.feed));
  }, [feeds, series]);

  return (
    <table className="watch">
      <thead>
        <tr>
          <th>feed</th>
          <th>n</th>
          <th>won</th>
          <th>mean</th>
          <th>total</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={row.feed}
            className={row.chartable ? undefined : "nobars"}
            aria-selected={row.feed === picked}
            onClick={row.chartable ? () => onPick(row.feed) : undefined}
            title={row.chartable ? row.group?.verdict : "no candles for this feed on this machine"}
          >
            <td>
              {row.feed}
              {!row.chartable && <span className="dim"> ·</span>}
            </td>
            <td className="num">{row.group?.count ?? "—"}</td>
            <td
              className={
                row.group ? `num ${row.group.win_rate >= pooled ? "up" : "down"}` : "num dim"
              }
            >
              {row.group ? percent(row.group.win_rate) : "—"}
            </td>
            <td className={row.group ? `num ${tone(row.group.mean_r)}` : "num dim"}>
              {row.group ? signedR(row.group.mean_r) : "—"}
            </td>
            <td className={row.group ? `num ${tone(row.group.total_r)}` : "num dim"}>
              {row.group ? signedR(row.group.total_r, 1) : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
