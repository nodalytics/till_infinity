"use client";

import { ago, percent, stamp } from "@/lib/format";
import type { Activity as ActivityData } from "@/lib/types";

const WINDOWS = [1, 6, 24, 72, 720, 8760];

/**
 * What each strategy is taking and being refused, from the journal.
 *
 * The broker knows what filled. Only this knows what was wanted and declined,
 * and by which gate, which is what "why did nothing trade" is actually asking.
 *
 * **Freshness is stated, not implied.** `age` is seconds since the newest
 * trading entry and it is printed next to the heading in alarm colour once it
 * is old: a panel that looks live while the file underneath it stopped moving
 * is the failure this desk has already paid for, where four health signals
 * read green over a component that could not trade.
 */
export default function Activity({
  activity,
  hours,
  onHours,
  refreshed,
}: {
  activity: ActivityData;
  hours: number;
  onHours: (hours: number) => void;
  refreshed: number | null;
}) {
  const stale = activity.age == null || activity.age > 3600;

  return (
    <>
      <div className="stats" style={{ alignItems: "center", gap: 16 }}>
        <div className="stat">
          <b className={stale ? "alarm" : "up"}>{activity.age == null ? "never" : ago(activity.age)}</b>
          <span>since the desk last wrote anything</span>
        </div>
        <div className="stat">
          <b>{activity.taken}</b>
          <span>taken in this window</span>
        </div>
        <div className="stat">
          <b className="warn">{activity.refused}</b>
          <span>refused in this window</span>
        </div>
        <span className="group">
          {WINDOWS.map((option) => (
            <button
              key={option}
              type="button"
              className="btn"
              aria-pressed={hours === option}
              onClick={() => onHours(option)}
            >
              {option < 24 ? `${option}h` : option < 8760 ? `${option / 24}d` : "1y"}
            </button>
          ))}
        </span>
        <span className="note" style={{ margin: 0 }}>
          {refreshed == null ? "not refreshed yet" : `read ${ago((Date.now() - refreshed) / 1000)}`}
        </span>
      </div>

      {stale && (
        <p className="verdict verdict-thin">
          {activity.age == null
            ? "This journal has no trading entries at all, so there is nothing to be current about."
            : `The newest trading entry in this journal is from ${ago(activity.age)}. Nothing here is live; it is the last thing the desk recorded.`}
        </p>
      )}

      <div className="panel-cols">
        <div>
          <h3 className="heading">
            Per strategy
            <span>what it wanted, and what stopped it</span>
          </h3>
          {activity.strategies.length === 0 ? (
            <p className="note">Nothing recorded in this window.</p>
          ) : (
            <table className="grid">
              <thead>
                <tr>
                  <th>strategy</th>
                  <th className="r">took</th>
                  <th className="r">refused</th>
                  <th>top gates</th>
                  <th>feeds</th>
                  <th className="r">last seen</th>
                </tr>
              </thead>
              <tbody>
                {activity.strategies.map((pulse) => (
                  <tr key={pulse.strategy}>
                    <td>{pulse.strategy}</td>
                    <td className="r num">{pulse.taken}</td>
                    <td className="r num warn">{pulse.refused}</td>
                    <td className="dim">
                      {pulse.gates
                        .slice(0, 2)
                        .map((gate) => `${gate.gate} ${percent(gate.share)}`)
                        .join(", ") || "—"}
                    </td>
                    <td className="dim">{pulse.feeds.slice(0, 4).join(" ") || "—"}</td>
                    <td className="r num dim">
                      {pulse.last_seen == null ? "—" : stamp(pulse.last_seen)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div>
          <h3 className="heading">
            Latest entries
            <span>decisions, outcomes and refusals, newest first</span>
          </h3>
          {activity.recent.length === 0 ? (
            <p className="note">Nothing recorded in this window.</p>
          ) : (
            <table className="grid">
              <thead>
                <tr>
                  <th className="r">when</th>
                  <th>what</th>
                  <th>why</th>
                </tr>
              </thead>
              <tbody>
                {activity.recent.slice(0, 60).map((event, index) => (
                  <tr key={`${event.time}-${index}`}>
                    <td className="r num dim">{stamp(event.time)}</td>
                    <td className={event.gate ? "warn" : undefined}>{event.title}</td>
                    <td className="wrap">{event.why}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}
