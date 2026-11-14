import { Empty } from "@/components/bits";
import { ago, money, stamp } from "@/lib/format";
import type { Book } from "@/lib/types";

/**
 * The open book, the disagreements, and the exposure against the caps.
 *
 * Every figure is the broker's, read from a snapshot the desk wrote, because
 * the standing rule here is to judge the desk on the broker and not the
 * journal. There is no fallback to journal positions when the file is
 * missing: the journal is not the broker, and presenting it as one is the
 * drift this arrangement exists to prevent.
 */
export default function Positions({ book }: { book: Book }) {
  if (!book.present) {
    return (
      <div className="hollow">
        <h2>No broker snapshot.</h2>
        <p>{book.message}</p>
        <p>
          Run it where the desk runs:{" "}
          <code>uv run python -m web.api.snapshot --every 30</code>. It reads two GET routes and
          writes a JSON file; the dashboard holds no credential and makes no outbound call.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="stats">
        <div className="stat">
          <b className={book.unprotected.length ? "alarm" : "up"}>
            {book.unprotected.length} of {book.positions.length}
          </b>
          <span>positions with no stop at the broker</span>
        </div>
        <div className="stat">
          <b className={book.stale ? "alarm" : undefined}>
            {book.age == null ? "unknown" : ago(book.age)}
          </b>
          <span>snapshot age{book.taken_at ? `, ${stamp(book.taken_at)}` : ""}</span>
        </div>
        <div className="stat">
          <b className={book.mismatches.length ? "alarm" : "up"}>{book.mismatches.length}</b>
          <span>broker-engine disagreements</span>
        </div>
        <div className="stat">
          <b>{book.engine_open}</b>
          <span>decisions the engine has not closed</span>
        </div>
        {book.account.equity != null && (
          <div className="stat">
            <b>{book.account.equity.toFixed(2)}</b>
            <span>equity, {book.account.currency || "account currency"}</span>
          </div>
        )}
      </div>

      {book.stale && (
        <p className="verdict verdict-thin">
          This snapshot is {book.age == null ? "of unknown age" : `${ago(book.age)} old`}. It is the
          last book the writer managed to read, not the book now.
        </p>
      )}

      <div className="section">
        <h3 className="heading">
          Open positions
          <span>from the broker</span>
        </h3>
        {book.positions.length === 0 ? (
          <Empty>The snapshot says the account is flat.</Empty>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>symbol</th>
                <th>side</th>
                <th className="r">volume</th>
                <th className="r">entry</th>
                <th className="r">now</th>
                <th className="r">stop</th>
                <th className="r">target</th>
                <th className="r">open P&amp;L</th>
                <th className="r">opened</th>
              </tr>
            </thead>
            <tbody>
              {book.positions.map((row) => (
                <tr key={row.ticket || `${row.symbol}-${row.side}`}>
                  <td>{row.symbol}</td>
                  <td className={row.side === "sell" ? "down" : "up"}>{row.side}</td>
                  <td className="r num">{row.volume}</td>
                  <td className="r num dim">{row.entry ?? "—"}</td>
                  <td className="r num">{row.price ?? "—"}</td>
                  <td className={row.stop ? "r num" : "r num alarm"}>{row.stop ?? "none"}</td>
                  <td className="r num dim">{row.target ?? "—"}</td>
                  <td
                    className={`r num ${row.profit == null ? "dim" : row.profit >= 0 ? "up" : "down"}`}
                  >
                    {row.profit == null ? "—" : money(row.profit)}
                  </td>
                  <td className="r num dim">{row.opened == null ? "—" : stamp(row.opened)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="section">
        <h3 className="heading">
          Broker against engine
          <span>matched on symbol and side</span>
        </h3>
        {book.mismatches.length === 0 ? (
          <Empty>The two agree on every open position.</Empty>
        ) : (
          <table className="grid">
            <thead>
              <tr>
                <th>where</th>
                <th>symbol</th>
                <th>side</th>
                <th>what it means</th>
              </tr>
            </thead>
            <tbody>
              {book.mismatches.map((row, index) => (
                <tr key={`${row.where}-${row.symbol}-${index}`}>
                  <td className="alarm">{row.where}</td>
                  <td>{row.symbol}</td>
                  <td>{row.side || "—"}</td>
                  <td className="wrap">{row.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="note">
          A journalled decision carries no ticket - only the close record does - so symbol and side
          is the strongest key the two records share, and two positions on one symbol and side
          collapse to a single comparison.
        </p>
      </div>

      <div className="section">
        <h3 className="heading">
          Exposure against the caps
          <span>ceilings from the desk&apos;s own settings</span>
        </h3>
        <table className="grid">
          <thead>
            <tr>
              <th>cap</th>
              <th className="r">used</th>
              <th className="r">ceiling</th>
              <th>unit</th>
              <th>setting</th>
            </tr>
          </thead>
          <tbody>
            {book.caps.map((cap) => (
              <tr key={cap.name}>
                <td className={cap.binding ? "alarm" : undefined}>
                  {cap.name}
                  {cap.binding && " · binding"}
                </td>
                <td className={`r num ${cap.binding ? "alarm" : ""}`}>
                  {cap.used.toLocaleString("en-GB", { maximumFractionDigits: 2 })}
                </td>
                <td className="r num dim">
                  {cap.ceiling == null
                    ? "none set"
                    : cap.ceiling.toLocaleString("en-GB", { maximumFractionDigits: 2 })}
                </td>
                <td className="dim">{cap.unit}</td>
                <td className="wrap">{cap.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {Object.keys(book.currencies).length > 0 && (
          <p className="note">
            Net by quote currency, in lots:{" "}
            {Object.entries(book.currencies)
              .map(([name, value]) => `${name} ${value >= 0 ? "+" : "−"}${Math.abs(value)}`)
              .join(", ")}
            . Swap does not cancel in a long/short basket - both sides pay - so a flat net is not a
            flat carry.
          </p>
        )}
      </div>
    </>
  );
}
