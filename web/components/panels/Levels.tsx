import { Empty } from "@/components/bits";
import { money, percent } from "@/lib/format";
import type { Levels as LevelsData } from "@/lib/types";

/**
 * What each level made or lost, from `journal/ledger.py`.
 *
 * **A level's price is not its name** - the filter moves it whenever it learns
 * something - so the ledger groups by `Intent.level_id`. Nothing in the ported
 * desk sets that yet, so every trade currently groups under one unnamed
 * record. The panel says so rather than presenting one row as a finding, and
 * does not regroup by price, which is exactly the mistake the ledger exists to
 * avoid.
 */
export default function Levels({ levels }: { levels: LevelsData }) {
  const named = levels.records.filter((row) => row.named);
  const totals = levels.totals;

  if (levels.message || levels.records.length === 0) {
    return <Empty>{levels.message || "No closed trades recorded."}</Empty>;
  }

  return (
    <>
      <div className="stats">
        <div className="stat">
          <b>{(totals.trades ?? 0).toLocaleString("en-GB")}</b>
          <span>closed trades</span>
        </div>
        <div className="stat">
          <b>{(totals.levels ?? 0).toLocaleString("en-GB")}</b>
          <span>grouped records</span>
        </div>
        <div className="stat">
          <b>{(totals.named_levels ?? 0).toLocaleString("en-GB")}</b>
          <span>carry a level id</span>
        </div>
        <div className="stat">
          <b className={(totals.net ?? 0) >= 0 ? "up" : "down"}>{money(totals.net ?? 0)}</b>
          <span>net, account currency</span>
        </div>
        <div className="stat">
          <b>{percent(totals.hit_rate ?? 0)}</b>
          <span>hit rate</span>
        </div>
      </div>

      {named.length === 0 ? (
        <p className="note">
          No trade carries a level id yet, so all of them group under one unnamed record. Grouping
          by price instead would invent levels: the Kalman filter moves a level whenever it learns
          something, so one level traded twice is journalled at two prices, and grouped by price its
          two trades become two levels with one trade each.
        </p>
      ) : (
        <table className="grid">
          <thead>
            <tr>
              <th>level</th>
              <th>feed</th>
              <th className="r">trades</th>
              <th className="r">won</th>
              <th className="r">net</th>
              <th>endings</th>
            </tr>
          </thead>
          <tbody>
            {named.slice(0, 40).map((row) => (
              <tr key={row.level_id}>
                <td className="num">{row.level_id}</td>
                <td>
                  {row.feed} {row.interval}
                </td>
                <td className="r num">{row.trades}</td>
                <td className="r num">{percent(row.hit_rate)}</td>
                <td className={`r num ${row.net >= 0 ? "up" : "down"}`}>{money(row.net)}</td>
                <td className="dim">
                  {Object.entries(row.endings)
                    .map(([name, count]) => `${name} ${count}`)
                    .join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
