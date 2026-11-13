import { percent } from "@/lib/format";
import type { Decline } from "@/lib/types";

/**
 * What the desk declined, and which gate declined it.
 *
 * The half of the record nothing else keeps. The engine persists orders and
 * fills; a trade that was never placed leaves nothing behind but the
 * observation a gate wrote, so without this tally a gate that never fires and
 * a gate that fires constantly look the same from outside - one is doing
 * nothing and the other is mis-set.
 */
export default function Refusals({
  declines,
  taken,
}: {
  declines: Decline[];
  taken: number;
}) {
  const total = declines.reduce((sum, row) => sum + row.count, 0);
  const widest = declines.reduce((most, row) => Math.max(most, row.count), 1);

  if (declines.length === 0) {
    return (
      <p className="note">
        No refusals recorded in this window. Strategy-level refusals are not journalled - there are
        hundreds a day and they are the filter working - so this counts the account saying no to
        something a strategy wanted.
      </p>
    );
  }

  return (
    <>
      <div className="stats">
        <div className="stat">
          <b>{total.toLocaleString("en-GB")}</b>
          <span>refused in this window</span>
        </div>
        <div className="stat">
          <b>{taken > 0 ? (total / taken).toFixed(1) : "—"}</b>
          <span>refused for every one taken</span>
        </div>
        <div className="stat">
          <b>{declines.length}</b>
          <span>gates that fired</span>
        </div>
      </div>

      <table className="grid">
        <thead>
          <tr>
            <th>gate</th>
            <th aria-label="share" />
            <th className="r">refused</th>
            <th className="r">share</th>
          </tr>
        </thead>
        <tbody>
          {declines.map((row) => (
            <tr key={row.gate}>
              <td className="num">{row.gate}</td>
              <td style={{ width: 160 }}>
                <span className="rail-bar signal">
                  <span style={{ width: `${(row.count / widest) * 100}%` }} />
                </span>
              </td>
              <td className="r num">{row.count.toLocaleString("en-GB")}</td>
              <td className="r num dim">{percent(row.share, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
