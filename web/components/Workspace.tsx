"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Chart, { type Toggles } from "@/components/Chart";
import Fault from "@/components/Fault";
import Hollow from "@/components/Hollow";
import SignIn from "@/components/SignIn";
import { SkeletonChart, SkeletonPanel } from "@/components/Skeleton";
import Watchlist from "@/components/Watchlist";
import { Flash } from "@/components/bits";
import Activity from "@/components/panels/Activity";
import Levels from "@/components/panels/Levels";
import Performance from "@/components/panels/Performance";
import Positions from "@/components/panels/Positions";
import Refusals from "@/components/panels/Refusals";
import Trades from "@/components/panels/Trades";
import {
  fetchActivity,
  fetchBook,
  fetchChart,
  fetchHealth,
  fetchLevels,
  fetchOverview,
  fetchSeries,
  needsSignIn,
} from "@/lib/api";
import { ago, percent, signedR, span, tone } from "@/lib/format";
import * as theme from "@/lib/theme";
import type {
  Activity as ActivityData,
  Book,
  Chart as ChartData,
  Filters,
  Health,
  Levels as LevelsData,
  Overview,
  Series,
} from "@/lib/types";

const WINDOWS: { label: string; days: number | null }[] = [
  { label: "1D", days: 1 },
  { label: "1W", days: 7 },
  { label: "1M", days: 30 },
  { label: "3M", days: 90 },
  { label: "All", days: null },
];

/** How often the activity panel re-reads. A local sqlite file, not a service. */
const PULSE = 15_000;

/** Interval names in seconds, so the buttons run short to long. */
const SECONDS: Record<string, number> = {
  "1m": 60,
  "3m": 180,
  "5m": 300,
  "15m": 900,
  "30m": 1800,
  "1h": 3600,
  "2h": 7200,
  "4h": 14400,
  "1d": 86400,
  "1w": 604800,
};
const STEP = (name: string) => SECONDS[name] ?? 0;

type Tab = "activity" | "performance" | "trades" | "refusals" | "positions" | "levels";

export default function Workspace() {
  const [mode, setMode] = useState<string>("");
  const [strategy, setStrategy] = useState("");
  const [days, setDays] = useState<number | null>(null);
  const filters: Filters = useMemo(
    () => ({ days, mode, strategy, feed: "" }),
    [days, mode, strategy],
  );

  const [skin, setSkin] = useState<theme.Theme>("dark");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [series, setSeries] = useState<Series[]>([]);
  const [levels, setLevels] = useState<LevelsData | null>(null);
  const [book, setBook] = useState<Book | null>(null);
  const [activity, setActivity] = useState<ActivityData | null>(null);
  const [activityHours, setActivityHours] = useState(6);
  const [refreshed, setRefreshed] = useState<number | null>(null);
  const [failed, setFailed] = useState("");
  const [locked, setLocked] = useState(false);
  const [attempt, setAttempt] = useState(0);
  /**
   * Has the catalogue listing come back yet?
   *
   * `series` starts empty and is also empty when this machine holds no bars,
   * so the two cannot be told apart from its length. Without this the chart
   * pane asserts "no bar catalogue on this machine" for the second or two
   * before the listing arrives - a settled answer, stated while the question
   * is still open, and `data.series()` groups a 300MB table to answer it.
   */
  const [sourced, setSourced] = useState(false);

  const [feed, setFeed] = useState("");
  const [interval, setInterval] = useState("");
  const [chart, setChart] = useState<ChartData | null>(null);

  const [tab, setTab] = useState<Tab>("performance");
  const [toggles, setToggles] = useState<Toggles>({
    markers: true,
    refusals: false,
    levels: false,
    ma: false,
    bands: false,
    vol: false,
    drawing: false,
  });
  const [showAside, setShowAside] = useState(true);
  const [showBottom, setShowBottom] = useState(true);
  const [bottomHeight, setBottomHeight] = useState(300);
  const [asideWidth, setAsideWidth] = useState(286);
  const stage = useRef<HTMLDivElement>(null);

  // ---- theme -------------------------------------------------------------
  useEffect(() => {
    setSkin(theme.current());
    // Follow the system only while the viewer has made no choice of their own.
    let media: MediaQueryList | null = null;
    const follow = () => {
      if (theme.stored()) return;
      const next = theme.system();
      theme.crossfade(next);
      setSkin(next);
    };
    try {
      media = window.matchMedia("(prefers-color-scheme: dark)");
      media.addEventListener("change", follow);
    } catch {
      media = null;
    }
    return () => media?.removeEventListener("change", follow);
  }, []);

  const flip = useCallback(() => {
    const next: theme.Theme = theme.current() === "dark" ? "light" : "dark";
    // `crossfade` rather than `apply`: it turns a colour transition on for the
    // length of the flip and off again, so the surfaces travel between the two
    // palettes instead of cutting. The chart's canvas recolours in its own
    // effect and lands inside the same window.
    theme.crossfade(next);
    theme.remember(next);
    setSkin(next);
  }, []);

  // ---- first load --------------------------------------------------------
  useEffect(() => {
    const abort = new AbortController();
    Promise.all([
      fetchHealth(abort.signal),
      fetchSeries(abort.signal),
      fetchLevels(abort.signal),
      fetchBook(abort.signal),
    ])
      .then(([state, rows, ledger, open]) => {
        setHealth(state);
        setSeries(rows);
        setLevels(ledger);
        setBook(open);
        setSourced(true);
      })
      .catch((error: unknown) => {
        if (abort.signal.aborted) return;
        if (needsSignIn(error)) setLocked(true);
        else setFailed(describe(error));
      });
    return () => abort.abort();
  }, [attempt]);

  useEffect(() => {
    const abort = new AbortController();
    fetchOverview(filters, abort.signal)
      .then((found) => {
        setOverview(found);
        setLocked(false);
      })
      .catch((error: unknown) => {
        if (abort.signal.aborted) return;
        if (needsSignIn(error)) setLocked(true);
        else setFailed(describe(error));
      });
    return () => abort.abort();
  }, [filters, attempt]);

  // ---- the activity pulse ------------------------------------------------
  useEffect(() => {
    let alive = true;
    const read = () => {
      fetchActivity(activityHours)
        .then((found) => {
          if (!alive) return;
          setActivity(found);
          setRefreshed(Date.now());
        })
        .catch(() => {
          // A failed pulse leaves the last reading and its age on screen,
          // which keeps getting older. That is the honest render.
        });
    };
    read();
    const timer = window.setInterval(read, PULSE);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [activityHours]);

  // ---- which feed and interval ------------------------------------------
  const feeds = useMemo(() => [...new Set(series.map((row) => row.feed))], [series]);
  const traded = useMemo(() => {
    const counts = new Map<string, number>();
    for (const group of overview?.by_feed ?? []) counts.set(group.name, group.count);
    return counts;
  }, [overview]);

  const current =
    feed ||
    [...feeds].sort((a, b) => (traded.get(b) ?? 0) - (traded.get(a) ?? 0) || a.localeCompare(b))[0] ||
    "";
  // One button per interval. Three sources can hold the same feed at the same
  // interval - the sqlite store carries seven venues and both parquet
  // catalogues overlap it - and a row of duplicate labels is unreadable. The
  // source with the latest coverage wins, which is also the one whose candles
  // reach the trades.
  const options = useMemo(() => {
    const best = new Map<string, Series>();
    for (const row of series) {
      if (row.feed !== current) continue;
      const held = best.get(row.interval);
      if (!held || (row.last ?? 0) > (held.last ?? 0)) best.set(row.interval, row);
    }
    return [...best.values()].sort((a, b) => STEP(a.interval) - STEP(b.interval));
  }, [series, current]);
  // The default interval is the one whose best source reaches furthest
  // forward, because that is the one whose candles reach the trades: the
  // sqlite store stops in August and the 5-minute catalogue runs to today, so
  // defaulting to a "nice" interval like 15m lands on an empty chart.
  const picked =
    options.find((row) => row.interval === interval) ??
    [...options].sort((a, b) => (b.last ?? 0) - (a.last ?? 0))[0];

  useEffect(() => {
    if (!picked) {
      setChart(null);
      return;
    }
    const abort = new AbortController();
    fetchChart(current, picked.interval, picked.source, filters, abort.signal)
      .then(setChart)
      .catch((error: unknown) => {
        if (abort.signal.aborted) return;
        if (needsSignIn(error)) setLocked(true);
        else setFailed(describe(error));
      });
    return () => abort.abort();
  }, [current, picked, filters, attempt]);

  // ---- splitters ---------------------------------------------------------
  const dragBottom = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    const box = stage.current?.getBoundingClientRect();
    if (!box) return;
    const move = (e: PointerEvent) => {
      const next = box.bottom - e.clientY;
      setBottomHeight(Math.max(90, Math.min(box.height - 160, next)));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  };

  const dragAside = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    const move = (e: PointerEvent) => {
      setAsideWidth(Math.max(180, Math.min(520, window.innerWidth - e.clientX)));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  };

  // ---- render ------------------------------------------------------------
  const hollow = health != null && health.trades === 0;
  const unprotected = book?.unprotected.length ?? 0;
  const mismatches = book?.mismatches.length ?? 0;
  // Three states, not two. A journal that has not been read yet is neither
  // stale nor current, and colouring it amber while the first read is in
  // flight is a false alarm on a strip whose whole job is to be believed.
  const journalStale = activity != null && (activity.age == null || activity.age > 3600);
  const journalFresh = activity != null && activity.age != null && activity.age <= 3600;

  return (
    <div className="workspace">
      <header className="topbar enter" style={{ "--i": 0 } as React.CSSProperties}>
        <h1 className="wordmark">
          {/* The mark is a CSS background on this span, so the variant follows
              `data-theme` with no React involved and the right one is painted
              first. `aria-label` carries the name the `<svg>`'s own title
              would have, which a background image does not expose. */}
          <span className="mark" role="img" aria-label="Till Infinity" />
          <span>
            till_infinity <span className="soft">/ desk</span>
          </span>
        </h1>

        <span className="sep" />

        <select
          className="pick"
          aria-label="Feed"
          value={current}
          onChange={(event) => {
            setFeed(event.target.value);
            setInterval("");
          }}
        >
          {feeds.length === 0 && (
            <option value="">
              {sourced || failed ? "no catalogue" : "reading catalogues"}
            </option>
          )}
          {[...feeds]
            .sort((a, b) => (traded.get(b) ?? 0) - (traded.get(a) ?? 0) || a.localeCompare(b))
            .map((name) => (
              <option key={name} value={name}>
                {name}
                {traded.get(name) ? ` · ${traded.get(name)}` : ""}
              </option>
            ))}
        </select>

        <span className="group">
          {options.map((row) => (
            <button
              key={`${row.source}:${row.interval}`}
              type="button"
              className="btn"
              aria-pressed={picked?.interval === row.interval}
              onClick={() => setInterval(row.interval)}
              title={`${row.venue.toLowerCase()} · ${row.source}`}
            >
              {row.interval}
            </button>
          ))}
        </span>

        <span className="sep" />

        <span className="group">
          {WINDOWS.map((option) => (
            <button
              key={option.label}
              type="button"
              className="btn"
              aria-pressed={days === option.days}
              onClick={() => setDays(option.days)}
            >
              {option.label}
            </button>
          ))}
        </span>

        {overview && overview.modes.length > 1 && (
          <>
            <span className="sep" />
            <span className="group">
              <button
                type="button"
                className="btn"
                aria-pressed={!mode}
                onClick={() => setMode("")}
              >
                both
              </button>
              {overview.modes.map((name) => (
                <button
                  key={name}
                  type="button"
                  className="btn"
                  aria-pressed={mode === name}
                  onClick={() => setMode(name)}
                >
                  {name}
                </button>
              ))}
            </span>
          </>
        )}

        {overview && (
          <select
            className="pick"
            aria-label="Strategy"
            value={strategy}
            onChange={(event) => setStrategy(event.target.value)}
          >
            <option value="">every strategy</option>
            {overview.strategies.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        )}

        <span className="spacer" />

        <button
          type="button"
          className="btn"
          onClick={flip}
          title="Switch between the light and dark themes"
        >
          {skin === "dark" ? <Sun /> : <Moon />}
          {skin === "dark" ? "light" : "dark"}
        </button>
      </header>

      {book && (
        <div className="alarms enter" style={{ "--i": 1 } as React.CSSProperties}>
          <span
            className={`alarm-cell ${unprotected ? "hot" : "ok"}`}
            title="A position with no stop at the broker"
          >
            <span className="dot" />
            {book.present ? (
              <>
                <b>
                  <Flash on={`${unprotected}/${book.positions.length}`}>
                    {unprotected} of {book.positions.length}
                  </Flash>
                </b>{" "}
                positions carry no stop
              </>
            ) : (
              <>no broker snapshot</>
            )}
          </span>
          <span className={`alarm-cell ${mismatches ? "hot" : "ok"}`}>
            <span className="dot" />
            <b>
              <Flash on={mismatches}>{mismatches}</Flash>
            </b>{" "}
            broker-engine disagreements
          </span>
          <span className={`alarm-cell ${book.present && book.stale ? "warm" : "ok"}`}>
            <span className="dot" />
            snapshot <b>{book.age == null ? "absent" : ago(book.age)}</b>
          </span>
          <span
            className={`alarm-cell ${journalStale ? "warm" : "ok"}`}
          >
            {/* The halo is on this dot alone, and only while the journal is
                current. It is the one thing on the page that says the file
                underneath is still moving - the desk has already paid once for
                a panel that looked live over a component that had stopped. */}
            <span className={journalFresh ? "dot live-dot" : "dot"} />
            journal <b>{activity?.age == null ? "silent" : ago(activity.age)}</b>
          </span>
          {book.caps
            .filter((cap) => cap.binding)
            .map((cap) => (
              <span className="alarm-cell hot" key={cap.name}>
                <span className="dot" />
                <b>{cap.name}</b> binding
              </span>
            ))}
        </div>
      )}

      <div className="middle">
        <nav className="rail enter" aria-label="Chart layers" style={{ "--i": 2 } as React.CSSProperties}>
          <Toggle
            on={toggles.markers}
            label="Trade entries and exits"
            onClick={() => setToggles((t) => ({ ...t, markers: !t.markers }))}
          >
            <Flag />
          </Toggle>
          <Toggle
            on={toggles.refusals}
            label="Where a gate refused a trade"
            onClick={() => setToggles((t) => ({ ...t, refusals: !t.refusals }))}
          >
            <Ban />
          </Toggle>
          <Toggle
            on={toggles.levels}
            label="Levels the desk traded or was refused at"
            onClick={() => setToggles((t) => ({ ...t, levels: !t.levels }))}
          >
            <Rows />
          </Toggle>
          <span className="sep" style={{ width: 20, height: 1, margin: "4px 0" }} />
          <Toggle
            on={toggles.ma}
            label="Means over 20 and 50 bars"
            onClick={() => setToggles((t) => ({ ...t, ma: !t.ma }))}
          >
            <Wave />
          </Toggle>
          <Toggle
            on={toggles.bands}
            label="20-bar mean with a 2x ATR cushion"
            onClick={() => setToggles((t) => ({ ...t, bands: !t.bands }))}
          >
            <Bands />
          </Toggle>
          <Toggle
            on={toggles.vol}
            label="Realised volatility, bps a bar"
            onClick={() => setToggles((t) => ({ ...t, vol: !t.vol }))}
          >
            <Pulse />
          </Toggle>
          <span className="sep" style={{ width: 20, height: 1, margin: "4px 0" }} />
          <Toggle
            on={toggles.drawing}
            label="Click the chart to place a horizontal line"
            onClick={() => setToggles((t) => ({ ...t, drawing: !t.drawing }))}
          >
            <Pen />
          </Toggle>
          <span className="spacer" />
          <Toggle on={showAside} label="Watchlist" onClick={() => setShowAside((v) => !v)}>
            <PanelRight />
          </Toggle>
          <Toggle on={showBottom} label="Bottom panel" onClick={() => setShowBottom((v) => !v)}>
            <PanelBottom />
          </Toggle>
        </nav>

        <div className="stage enter" ref={stage} style={{ "--i": 3 } as React.CSSProperties}>
          <div className="chartwrap">
            {locked ? (
              <SignIn
                onDone={() => {
                  setLocked(false);
                  setFailed("");
                  setAttempt((n) => n + 1);
                }}
              />
            ) : failed ? (
              <Fault
                detail={failed}
                onRetry={() => {
                  setFailed("");
                  setAttempt((n) => n + 1);
                }}
              />
            ) : hollow && health ? (
              <Hollow health={health} />
            ) : chart && chart.bars.length > 0 ? (
              <div className="chart-fade">
                <Chart data={chart} theme={skin} toggles={toggles} />
              </div>
            ) : chart?.message || (sourced && series.length === 0) ? (
              // A named reason, not a skeleton: this is a settled state, and a
              // placeholder that pulses for ever reads as a read that never
              // finishes.
              <div className="state">
                <div className="card">
                  <h2>
                    <span className="card-glyph" aria-hidden="true">
                      <NoBars />
                    </span>
                    No candles to draw
                  </h2>
                  <p>{chart?.message || "No bar catalogue on this machine."}</p>
                </div>
              </div>
            ) : (
              <SkeletonChart caption={`Reading candles for ${current || "this feed"}`} />
            )}
          </div>

          {showBottom && (
            <>
              <div
                className="hsplit"
                onPointerDown={dragBottom}
                role="separator"
                aria-orientation="horizontal"
                aria-label="Resize the bottom panel"
              />
              <section className="bottom" style={{ height: bottomHeight }}>
                <div className="tabs" role="tablist">
                  <TabButton id="activity" tab={tab} set={setTab} label="Activity">
                    {activity && activity.refused > 0 && (
                      <span className="pip">{activity.refused}</span>
                    )}
                  </TabButton>
                  <TabButton id="performance" tab={tab} set={setTab} label="Performance" />
                  <TabButton id="trades" tab={tab} set={setTab} label="Trades">
                    {overview && <span className="pip">{overview.overall.count}</span>}
                  </TabButton>
                  <TabButton id="refusals" tab={tab} set={setTab} label="Refusals" />
                  <TabButton id="positions" tab={tab} set={setTab} label="Positions">
                    {unprotected > 0 ? (
                      <span className="pip pip-alarm">{unprotected}</span>
                    ) : book?.present ? (
                      <span className="pip">{book.positions.length}</span>
                    ) : null}
                  </TabButton>
                  <TabButton id="levels" tab={tab} set={setTab} label="Levels" />

                  <span className="spacer" />
                  {overview && (
                    <span className="tab" style={{ cursor: "default", gap: 12 }}>
                      <span className="dim">
                        <Flash on={overview.overall.count}>{overview.overall.count} closed</Flash>
                      </span>
                      <span className="dim">
                        <Flash on={overview.overall.win_rate}>
                          {percent(overview.overall.win_rate)} won
                        </Flash>
                      </span>
                      <span className={tone(overview.overall.mean_r)}>
                        <Flash on={overview.overall.mean_r}>
                          {signedR(overview.overall.mean_r)} mean
                        </Flash>
                      </span>
                      <span className={tone(overview.overall.total_r)}>
                        <Flash on={overview.overall.total_r}>
                          {signedR(overview.overall.total_r, 1)} total
                        </Flash>
                      </span>
                    </span>
                  )}
                </div>

                {/* Keyed on the tab, so the content fades in rather than
                    cutting. React remounts the subtree on a new key, which is
                    what replays the animation; without the key it plays once
                    on load and never again. */}
                <div className="panel-body" role="tabpanel" key={tab}>
                  {locked ? (
                    <p className="note">Sign in above to read this desk.</p>
                  ) : failed ? (
                    <p className="note alarm">
                      The desk API is not answering, so there is nothing to show here. The chart
                      pane above says what to start.
                    </p>
                  ) : !overview ? (
                    <SkeletonPanel caption="Reading the journal" />
                  ) : (
                    <div className="panel-swap">
                      {tab === "performance" ? (
                        <Performance overview={overview} theme={skin} />
                      ) : tab === "trades" ? (
                        <Trades trades={overview.trades} />
                      ) : tab === "refusals" ? (
                        <Refusals declines={overview.declines} taken={overview.overall.count} />
                      ) : tab === "activity" ? (
                        activity ? (
                          <Activity
                            activity={activity}
                            hours={activityHours}
                            onHours={setActivityHours}
                            refreshed={refreshed}
                          />
                        ) : (
                          <SkeletonPanel caption="Reading the journal" stats={3} rows={5} />
                        )
                      ) : tab === "positions" ? (
                        book ? (
                          <Positions book={book} />
                        ) : (
                          <SkeletonPanel caption="Reading the broker snapshot" stats={0} rows={4} />
                        )
                      ) : levels ? (
                        <Levels levels={levels} />
                      ) : (
                        <SkeletonPanel caption="Reading the ledger" stats={0} rows={6} />
                      )}
                    </div>
                  )}
                </div>
              </section>
            </>
          )}
        </div>

        {showAside && (
          <>
            <div
              className="vsplit"
              onPointerDown={dragAside}
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize the watchlist"
            />
            <aside
              className="aside enter"
              style={{ width: asideWidth, "--i": 4 } as React.CSSProperties}
            >
              <div className="aside-head">
                <span>Feeds</span>
                <span>{overview ? span(overview.window.first, overview.window.last) : ""}</span>
              </div>
              <div className="aside-body">
                {!overview && !failed && (
                  <div style={{ padding: "var(--s-3)" }}>
                    <SkeletonPanel caption="Reading the feeds" stats={0} rows={8} cells={4} />
                  </div>
                )}
                {overview && (
                  <Watchlist
                    feeds={overview.by_feed}
                    series={series}
                    picked={current}
                    pooled={overview.overall.win_rate}
                    onPick={(name) => {
                      setFeed(name);
                      setInterval("");
                    }}
                  />
                )}
              </div>
            </aside>
          </>
        )}
      </div>

      <footer className="status enter" style={{ "--i": 5 } as React.CSSProperties}>
        {picked && (
          <span>
            <b>{current}</b> {picked.interval} · {picked.venue.toLowerCase()} · {picked.source}
          </span>
        )}
        {chart && chart.bars.length > 0 && (
          <span className="dim">
            {chart.bars.length.toLocaleString("en-GB")} candles
            {chart.markers.length > 0 && ` · ${chart.markers.length / 2} trades`}
            {toggles.refusals && chart.refusals.length > 0 && ` · ${chart.refusals.length} refused`}
            {toggles.levels && chart.levels.length > 0 && ` · ${chart.levels.length} levels`}
          </span>
        )}
        {chart?.message && <span className="warn">{chart.message}</span>}
        {overview && <span>{span(overview.window.first, overview.window.last)}</span>}
        {health?.sources.map((source) => (
          <span key={source.name} className={source.present ? undefined : "dim"}>
            {source.name} {source.present ? "✓" : "absent"}
          </span>
        ))}
        <span className="spacer" />
        <span className="dim">
          Read-only. Every figure comes from strategies/report.py and the journal, on this machine.
        </span>
      </footer>
    </div>
  );
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function TabButton({
  id,
  tab,
  set,
  label,
  children,
}: {
  id: Tab;
  tab: Tab;
  set: (tab: Tab) => void;
  label: string;
  children?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      className="tab"
      aria-selected={tab === id}
      onClick={() => set(id)}
    >
      {label}
      {children}
    </button>
  );
}

function Toggle({
  on,
  label,
  onClick,
  children,
}: {
  on: boolean;
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={on ? "btn btn-icon on" : "btn btn-icon"}
      aria-pressed={on}
      aria-label={label}
      title={label}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

// Plain geometric glyphs, drawn here rather than imported, so the page carries
// no third-party icon set and nothing that belongs to anybody else.
const stroke = {
  width: 15,
  height: 15,
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.4,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

const Flag = () => (
  <svg {...stroke}>
    <path d="M4 14V3h8l-1.6 2.5L12 8H4" />
  </svg>
);
const Ban = () => (
  <svg {...stroke}>
    <circle cx="8" cy="8" r="5.5" />
    <path d="M4.2 4.2l7.6 7.6" />
  </svg>
);
const Rows = () => (
  <svg {...stroke}>
    <path d="M2 4.5h12M2 8h12M2 11.5h12" />
  </svg>
);
const Wave = () => (
  <svg {...stroke}>
    <path d="M2 10.5c2 0 2-5 4-5s2 5 4 5 2-5 4-5" />
  </svg>
);
const Bands = () => (
  <svg {...stroke}>
    <path d="M2 4h12M2 12h12" strokeDasharray="2 2" />
    <path d="M2 8h12" />
  </svg>
);
const Pulse = () => (
  <svg {...stroke}>
    <path d="M1.5 8h3l2-4 2.5 8 2-4h3.5" />
  </svg>
);
const Pen = () => (
  <svg {...stroke}>
    <path d="M11.5 2.5l2 2L6 12l-3 1 1-3z" />
  </svg>
);
const PanelRight = () => (
  <svg {...stroke}>
    <rect x="2" y="3" width="12" height="10" rx="1" />
    <path d="M10 3v10" />
  </svg>
);
const PanelBottom = () => (
  <svg {...stroke}>
    <rect x="2" y="3" width="12" height="10" rx="1" />
    <path d="M2 10h12" />
  </svg>
);
const Sun = () => (
  <svg {...stroke}>
    <circle cx="8" cy="8" r="3" />
    <path d="M8 1v1.6M8 13.4V15M1 8h1.6M13.4 8H15M3.1 3.1l1.1 1.1M11.8 11.8l1.1 1.1M12.9 3.1l-1.1 1.1M4.2 11.8l-1.1 1.1" />
  </svg>
);
const Moon = () => (
  <svg {...stroke}>
    <path d="M13 9.6A5.6 5.6 0 016.4 3 5.6 5.6 0 108 14a5.6 5.6 0 005-4.4z" />
  </svg>
);
const NoBars = () => (
  <svg {...stroke} width="13" height="13">
    <path d="M3 13V8.5M7 13V6M11 13v-2.5" />
    <path d="M2 2.4l12 11.2" />
  </svg>
);
