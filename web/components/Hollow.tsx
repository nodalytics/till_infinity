import { Command } from "@/components/Fault";
import { day } from "@/lib/format";
import type { Health } from "@/lib/types";

/**
 * What to show when there is nothing to show.
 *
 * It names what the journal actually holds, because an empty dashboard over a
 * journal full of `structures` rows is a different problem from an empty
 * dashboard over a missing file, and a reader should not have to guess which.
 * Nothing here is a placeholder figure: a fabricated trading number is worse
 * than a blank panel.
 */
export default function Hollow({ health }: { health: Health }) {
  return (
    <div className="state">
      <div className="card card-wide">
        <h2>
          <span className="card-glyph" aria-hidden="true">
            <Nil />
          </span>
          No trades to score
        </h2>
        <p>{health.message || "The journal carries no trading entries."}</p>
        <p>
          Point <code>TILL_JOURNAL_DB</code> at the desk&apos;s journal and restart the API. A
          relative path resolves against the repository root.
        </p>
        <Command text="TILL_JOURNAL_DB=.data/journal/journal.db bash web/dev.sh" />

        {health.entries.length > 0 && (
          <table className="grid" style={{ marginTop: 12 }}>
            <caption>What this journal does hold</caption>
            <thead>
              <tr>
                <th>actor</th>
                <th>kind</th>
                <th className="r">entries</th>
                <th>first</th>
                <th>last</th>
              </tr>
            </thead>
            <tbody>
              {health.entries.slice(0, 12).map((row) => (
                <tr key={`${row.actor}-${row.kind}`}>
                  <td className="num">{row.actor || "—"}</td>
                  <td className="dim">{row.kind}</td>
                  <td className="r num">{row.entries.toLocaleString("en-GB")}</td>
                  <td className="dim">{day(row.first)}</td>
                  <td className="dim">{day(row.last)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

const Nil = () => (
  <svg
    width="13"
    height="13"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.5"
    strokeLinecap="round"
  >
    <circle cx="8" cy="8" r="5.5" />
    <path d="M4.6 11.4l6.8-6.8" />
  </svg>
);
