import { percent, signedR, tone } from "@/lib/format";
import type { Group } from "@/lib/types";

/** One figure with its label under it. */
export function Stat({
  value,
  label,
  colour,
}: {
  value: string;
  label: string;
  colour?: string;
}) {
  return (
    <div className="stat">
      <b className={colour}>{value}</b>
      <span>{label}</span>
    </div>
  );
}

/**
 * `Group.verdict`, straight from `strategies/report.py`.
 *
 * Under thirty closed trades it is a refusal to characterise a rate, and the
 * dashboard shows the refusal rather than a confident percentage over nine
 * trades. The amber is for that case and nothing else.
 */
export function Verdict({ group, extra }: { group: Group; extra?: string }) {
  return (
    <p className={group.enough ? "verdict" : "verdict verdict-thin"}>
      {group.verdict}
      {extra ? ` ${extra}` : ""}
    </p>
  );
}

/**
 * Count, win rate, mean R with its standard error, and total R.
 *
 * The standard error is printed beside the mean because a mean without one is
 * a number nobody can judge, and a dagger marks a row too thin to characterise
 * rather than quietly rounding it into a percentage.
 */
export function Groups({
  rows,
  label,
  pooled,
  enough,
  onPick,
  picked,
}: {
  rows: Group[];
  label: string;
  pooled: number;
  enough: number;
  onPick?: (name: string) => void;
  picked?: string;
}) {
  const ranked = [...rows].sort((a, b) => b.count - a.count);
  const widest = ranked.reduce((most, row) => Math.max(most, row.count), 1);
  const thin = ranked.some((row) => !row.enough);

  if (ranked.length === 0) return <p className="note">Nothing closed in this window.</p>;

  return (
    <>
      <table className="grid">
        <thead>
          <tr>
            <th>{label}</th>
            <th aria-label="share of trades" />
            <th className="r">n</th>
            <th className="r">won</th>
            <th className="r">mean R</th>
            <th className="r">± se</th>
            <th className="r">total R</th>
          </tr>
        </thead>
        <tbody>
          {ranked.map((row) => (
            <tr
              key={row.name || "unrecorded"}
              title={row.verdict}
              onClick={onPick ? () => onPick(row.name) : undefined}
              style={onPick ? { cursor: "pointer" } : undefined}
              aria-selected={picked === row.name ? true : undefined}
            >
              <td className={picked === row.name ? "" : undefined}>{row.name || "unrecorded"}</td>
              <td style={{ width: 70 }}>
                <span className="rail-bar">
                  <span style={{ width: `${(row.count / widest) * 100}%` }} />
                </span>
              </td>
              <td className="r num">
                {row.count}
                {!row.enough && <span className="warn">&#8224;</span>}
              </td>
              <td className={`r num ${row.win_rate >= pooled ? "up" : "down"}`}>
                {percent(row.win_rate)}
              </td>
              <td className={`r num ${tone(row.mean_r)}`}>{signedR(row.mean_r)}</td>
              <td className="r num dim">{row.se_r == null ? "—" : row.se_r.toFixed(2)}</td>
              <td className={`r num ${tone(row.total_r)}`}>{signedR(row.total_r, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {thin && (
        <p className="note">
          <span className="warn">&#8224;</span> fewer than {enough} closed trades, so the rate is
          the sample and not an estimate of one. Win rates are coloured against the pooled{" "}
          {percent(pooled)}.
        </p>
      )}
    </>
  );
}
