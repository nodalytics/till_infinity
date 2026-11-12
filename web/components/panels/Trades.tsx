"use client";

import { useMemo, useState } from "react";
import { duration, money, signedR, stamp, tone } from "@/lib/format";
import type { Trade } from "@/lib/types";

type Key = "opened" | "feed" | "rule" | "side" | "r" | "profit" | "seconds" | "ended" | "closer";
type Order = "asc" | "desc";

const COLUMNS: { key: Key; label: string; num?: boolean }[] = [
  { key: "opened", label: "opened, UTC" },
  { key: "feed", label: "feed" },
  { key: "rule", label: "took it" },
  { key: "side", label: "side" },
  { key: "ended", label: "ended" },
  { key: "closer", label: "closed by" },
  { key: "seconds", label: "held", num: true },
  { key: "profit", label: "money", num: true },
  { key: "r", label: "R", num: true },
];

/**
 * `exit_kind` is the specific ending - stop, target - and `reason` is the
 * close record's own word. The specific one wins and the general one is the
 * fallback; a trade carrying neither reads `unrecorded`, which is the truth,
 * rather than a default that would make a filter on "time stop" quietly wrong.
 */
export function ending(trade: Trade): string {
  return trade.exit_kind || trade.reason || "unrecorded";
}

/** `desk` when a rule intervened, `venue` when a resting order filled. */
export function closer(trade: Trade): string {
  return trade.exit_source || "unrecorded";
}

function value(trade: Trade, key: Key): string | number {
  switch (key) {
    case "opened":
      return trade.opened;
    case "r":
      return trade.r;
    case "profit":
      return trade.profit;
    case "seconds":
      return trade.seconds;
    case "ended":
      return ending(trade);
    case "closer":
      return closer(trade);
    case "rule":
      return trade.rule || trade.strategy;
    default:
      return trade[key];
  }
}

/** Every closed trade in the window, sortable and filterable. */
export default function Trades({ trades }: { trades: Trade[] }) {
  const [key, setKey] = useState<Key>("opened");
  const [order, setOrder] = useState<Order>("desc");
  const [outcome, setOutcome] = useState<"all" | "won" | "lost">("all");
  const [exit, setExit] = useState("");
  const [needle, setNeedle] = useState("");

  const endings = useMemo(
    () => [...new Set(trades.map(ending))].sort((a, b) => a.localeCompare(b)),
    [trades],
  );

  const rows = useMemo(() => {
    const text = needle.trim().toLowerCase();
    const kept = trades.filter((trade) => {
      if (outcome === "won" && !trade.won) return false;
      if (outcome === "lost" && trade.won) return false;
      if (exit && ending(trade) !== exit) return false;
      if (!text) return true;
      return `${trade.feed} ${trade.strategy} ${trade.rule} ${trade.side} ${trade.symbol} ${ending(trade)} ${closer(trade)} ${trade.why}`
        .toLowerCase()
        .includes(text);
    });
    const sign = order === "asc" ? 1 : -1;
    return [...kept].sort((a, b) => {
      const left = value(a, key);
      const right = value(b, key);
      if (typeof left === "number" && typeof right === "number") return (left - right) * sign;
      return String(left).localeCompare(String(right)) * sign;
    });
  }, [trades, key, order, outcome, exit, needle]);

  function sortBy(next: Key) {
    if (next === key) {
      setOrder(order === "asc" ? "desc" : "asc");
    } else {
      setKey(next);
      setOrder(typeof value(trades[0] ?? ({} as Trade), next) === "number" ? "desc" : "asc");
    }
  }

  return (
    <>
      <div className="stats" style={{ gap: 8, alignItems: "center", marginBottom: 10 }}>
        <span className="group">
          {(["all", "won", "lost"] as const).map((option) => (
            <button
              key={option}
              type="button"
              className="btn"
              aria-pressed={outcome === option}
              onClick={() => setOutcome(option)}
            >
              {option}
            </button>
          ))}
        </span>
        <select
          className="pick"
          aria-label="Exit reason"
          value={exit}
          onChange={(event) => setExit(event.target.value)}
        >
          <option value="">every ending</option>
          {endings.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <input
          className="field"
          type="search"
          value={needle}
          placeholder="feed, rule, ending, reason"
          aria-label="Filter trades"
          onChange={(event) => setNeedle(event.target.value)}
        />
        <span className="note" style={{ margin: 0 }}>
          {rows.length === trades.length
            ? `${trades.length} closed`
            : `${rows.length} of ${trades.length} closed`}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="note">
          {trades.length === 0 ? "No closed trades in this window." : "Nothing matches that filter."}
        </p>
      ) : (
        <table className="grid sticky">
          <thead>
            <tr>
              {COLUMNS.map((column) => (
                <th
                  key={column.key}
                  className={column.num ? "r sortable" : "sortable"}
                  onClick={() => sortBy(column.key)}
                  aria-sort={
                    key === column.key
                      ? order === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  {column.label}
                </th>
              ))}
              <th>why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((trade) => (
              <tr key={trade.key}>
                <td className="num dim">{stamp(trade.opened)}</td>
                <td>{trade.feed || "—"}</td>
                <td>{trade.rule || trade.strategy}</td>
                <td className={trade.side === "sell" ? "down" : "up"}>{trade.side || "—"}</td>
                <td>{ending(trade)}</td>
                <td className="dim">{closer(trade)}</td>
                <td className="r num">{duration(trade.seconds)}</td>
                <td className={`r num ${tone(trade.profit)}`}>{money(trade.profit)}</td>
                <td className={`r num ${tone(trade.r)}`}>{signedR(trade.r)}</td>
                <td className="wrap" title={trade.exit_why}>
                  {trade.why}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
