"use client";

import { useState } from "react";
import Equity from "@/components/Equity";
import { Empty, Groups, Stat, Ticker, Verdict } from "@/components/bits";
import { duration, money, percent, signedR, span, tone } from "@/lib/format";
import type { Measured, Overview } from "@/lib/types";

/**
 * The summary numbers, the curve, and who is winning or losing.
 *
 * Three breakdowns, because they answer three different questions: which
 * entry rule took it, what closed it, and whether the close beat letting the
 * stop run. `exit_source` is the one that matters most - a venue exit means
 * the resting stop or target did the work, a desk exit means a rule stepped
 * in - and anything the record does not carry is shown as `unrecorded` rather
 * than folded into a default, because those fields only started being written
 * recently and labelling the older trades would make the mix wrong invisibly.
 */
export default function Performance({ overview, theme }: { overview: Overview; theme: string }) {
  const [unit, setUnit] = useState<"r" | "money">("r");
  const { overall, window } = overview;

  return (
    <>
      {/*
        The six figures travel to their new values rather than jumping, which
        is only safe because `Ticker` reserves the destination's width first:
        counting 0 to 1,486 across a row of six would otherwise push the five
        beside it along as the digits arrived. An em dash is a string and
        stays one - there is nothing to count to.
      */}
      <div className="stats">
        <Stat
          value={<Ticker value={overall.count} format={(n) => String(Math.round(n))} />}
          label={`closed, ${span(window.first, window.last)}`}
        />
        <Stat
          value={
            overall.count ? <Ticker value={overall.win_rate} format={(n) => percent(n)} /> : "—"
          }
          label={`won, ${overall.wins} of ${overall.count}`}
        />
        <Stat
          value={
            overall.count ? <Ticker value={overall.mean_r} format={(n) => signedR(n)} /> : "—"
          }
          label={overall.se_r == null ? "mean R a trade" : `mean R a trade, ± ${overall.se_r.toFixed(2)}`}
          colour={tone(overall.mean_r)}
        />
        <Stat
          value={
            overall.count ? <Ticker value={overall.total_r} format={(n) => signedR(n, 1)} /> : "—"
          }
          label="realised, in units of risk"
          colour={tone(overall.total_r)}
        />
        <Stat
          value={overall.count ? <Ticker value={overall.profit} format={(n) => money(n)} /> : "—"}
          label="realised, account currency"
          colour={tone(overall.profit)}
        />
        <Stat value={duration(overall.median_seconds)} label="median hold" />
      </div>

      <Verdict
        group={overall}
        extra={
          overall.enough
            ? "Pooled over every strategy and feed in this window."
            : "The figures above are the sample, not an estimate of one."
        }
      />

      <div className="section">
        <h3 className="heading">
          Realised, cumulative
          <span className="group">
            <button
              type="button"
              className="btn"
              aria-pressed={unit === "r"}
              onClick={() => setUnit("r")}
            >
              R
            </button>
            <button
              type="button"
              className="btn"
              aria-pressed={unit === "money"}
              onClick={() => setUnit("money")}
            >
              money
            </button>
          </span>
        </h3>
        {overview.equity.length > 0 ? (
          <>
            <Equity points={overview.equity} unit={unit} theme={theme} />
            <p className="note">
              Ordered by close, because a trade contributes nothing until it closes.
            </p>
          </>
        ) : (
          <Empty>No closed trades in this window.</Empty>
        )}
      </div>

      <div className="section panel-cols">
        <div>
          <h3 className="heading">Entry rule</h3>
          <Groups
            rows={overview.by_rule}
            label="rule"
            pooled={overall.win_rate}
            enough={overview.enough}
          />
          <p className="note">
            `context[&quot;rule&quot;]` is not written by the desk yet, so these are the strategy
            names. When a profile starts labelling its trades this splits away from the strategy
            breakdown on its own.
          </p>
        </div>
        <div>
          <h3 className="heading">How it ended</h3>
          <Groups
            rows={overview.by_exit}
            label="reason"
            pooled={overall.win_rate}
            enough={overview.enough}
          />
          <h3 className="heading" style={{ marginTop: 16 }}>
            Who closed it
          </h3>
          <Groups
            rows={overview.by_exit_source}
            label="exit source"
            pooled={overall.win_rate}
            enough={overview.enough}
          />
        </div>
      </div>

      <div className="section">
        <h3 className="heading">Live against measured</h3>
        <Compare overview={overview} />
      </div>

      <div className="section">
        <h3 className="heading">
          Realised entry cost
          <span>per feed, never pooled</span>
        </h3>
        {overview.costs.length === 0 ? (
          <Empty>No decision in this window recorded a spread at entry.</Empty>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>feed</th>
                <th className="r">n</th>
                <th className="r">median spread</th>
                <th className="r">mean</th>
                <th className="r">worst</th>
                <th className="r">median slippage</th>
              </tr>
            </thead>
            <tbody>
              {overview.costs.map((row) => (
                <tr key={row.feed}>
                  <td>{row.feed}</td>
                  <td className="r num">{row.trades}</td>
                  <td className="r num">{row.median_spread?.toFixed(2) ?? "—"}</td>
                  <td className="r num dim">{row.mean_spread?.toFixed(2) ?? "—"}</td>
                  <td className="r num">{row.worst_spread?.toFixed(2) ?? "—"}</td>
                  <td className="r num dim">{row.median_slippage?.toFixed(2) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="note">
          In the units the journal recorded, which for an MT5 feed is points and not price. Not
          compared against the modelled median: the only implementation of that lives in{" "}
          <code>node/corpus.py</code>, and <code>node/</code> is deliberately outside this
          service&apos;s import graph.
        </p>
      </div>
    </>
  );
}

/**
 * Live figures beside research ones, per strategy.
 *
 * A blank where no research figure exists, never a zero: a zero reads as "the
 * backtest said this does not work", which is a different claim from "nobody
 * has measured it". Both sides carry their count and their standard error,
 * because two means without them cannot be compared at all.
 */
function Compare({ overview }: { overview: Overview }) {
  const measured = new Map<string, Measured>(
    overview.measured.map((row) => [row.strategy, row] as const),
  );
  const source = overview.measured.find((row) => row.source)?.source;
  const rows = [...overview.by_strategy].sort((a, b) => b.count - a.count);

  return (
    <>
      <table className="grid">
        <thead>
          <tr>
            <th>strategy</th>
            <th className="r">live n</th>
            <th className="r">live won</th>
            <th className="r">live mean R</th>
            <th className="r">live hold</th>
            <th className="r">measured n</th>
            <th className="r">measured won</th>
            <th className="r">measured mean R</th>
            <th className="r">gap</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((live) => {
            const found = measured.get(live.name);
            const gap = found?.mean_r == null ? null : live.mean_r - found.mean_r;
            return (
              <tr key={live.name} title={live.verdict}>
                <td>{live.name || "unrecorded"}</td>
                <td className="r num">
                  {live.count}
                  {!live.enough && <span className="warn">&#8224;</span>}
                </td>
                <td className="r num">{percent(live.win_rate)}</td>
                <td className={`r num ${tone(live.mean_r)}`}>
                  {signedR(live.mean_r)}
                  {live.se_r != null && <span className="dim"> ±{live.se_r.toFixed(2)}</span>}
                </td>
                <td className="r num dim">{duration(live.median_seconds)}</td>
                <td className="r num dim">{found?.trades ?? "—"}</td>
                <td className="r num dim">
                  {found?.win_rate == null ? "—" : percent(found.win_rate)}
                </td>
                <td className="r num dim">
                  {found?.mean_r == null ? "—" : signedR(found.mean_r)}
                  {found?.se_r != null && <span className="dim"> ±{found.se_r.toFixed(2)}</span>}
                </td>
                <td className={`r num ${gap == null ? "dim" : tone(gap)}`}>
                  {gap == null ? "—" : signedR(gap)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="note">
        {source ? (
          <>
            Measured figures from <code>{source}</code>, via <code>TILL_MEASURED_JSON</code>.
          </>
        ) : (
          <>
            No research figures on this machine. Point <code>TILL_MEASURED_JSON</code> at a file
            mapping each strategy to <code>{"{trades, win_rate, mean_r, se_r, hold_seconds}"}</code>{" "}
            and this column fills. Nothing in the repository writes one yet, so the blanks are
            honest.
          </>
        )}
      </p>
    </>
  );
}
