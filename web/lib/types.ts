/**
 * The shapes `web/api/data.py` returns.
 *
 * Hand-mirrored from the dataclasses rather than generated, and that is the
 * one thing to keep in mind when changing either side: the service publishes
 * an OpenAPI document at `/api/openapi.json`, so a field renamed in Python and
 * not here shows up as `undefined` in a cell rather than as a build error.
 * `npm run typecheck` cannot catch it; reading the dataclass can.
 */

export interface Window {
  since: number | null;
  until: number | null;
  days: number | null;
  first: number | null;
  last: number | null;
}

/** One `report.Group`. Every field is a property of that class. */
export interface Group {
  name: string;
  count: number;
  wins: number;
  win_rate: number;
  mean_r: number;
  total_r: number;
  profit: number;
  median_seconds: number;
  enough: boolean;
  verdict: string;
  /** Standard error of `mean_r`; `null` under two trades. */
  se_r: number | null;
}

/**
 * One closed trade. `r`, `won`, `profit` and `risk_money` come from
 * `report.Trade`; the prices are read off the journal afterwards and are
 * `null` when the record does not carry them.
 */
export interface Trade {
  key: string;
  strategy: string;
  feed: string;
  side: string;
  mode: string;
  profit: number;
  risk_money: number;
  r: number;
  won: boolean;
  seconds: number;
  reason: string;
  exit_source: string;
  reward_to_risk: number;
  opened: number;
  closed: number | null;
  entry_price: number | null;
  exit_price: number | null;
  stop_price: number | null;
  target_price: number | null;
  level_price: number | null;
  interval: string;
  exit_kind: string;
  symbol: string;
  /** The desk-level label. Empty in every journal read so far. */
  rule: string;
  /** The intent's own reason, from the decision entry. */
  why: string;
  exit_why: string;
  level_id: string;
  scaled: boolean;
  stop_vol: number | null;
  /** In points for an MT5 feed, not price. */
  spread_at_entry: number | null;
  slippage: number | null;
}

export interface EquityPoint {
  index: number;
  time: number;
  r: number;
  profit: number;
  cumulative_r: number;
  cumulative_profit: number;
}

export interface Decline {
  gate: string;
  count: number;
  share: number;
}

export interface TurnExit {
  scored: number;
  reached: number;
  took_r: number;
  suggested_r: number;
  /** `null` until something has been scored. Never zero to mean "unknown". */
  gained_r: number | null;
  summary: string;
}

export interface Overview {
  window: Window;
  overall: Group;
  by_strategy: Group[];
  by_feed: Group[];
  by_rule: Group[];
  by_exit: Group[];
  by_exit_source: Group[];
  declines: Decline[];
  turn_exit: TurnExit;
  equity: EquityPoint[];
  trades: Trade[];
  modes: string[];
  strategies: string[];
  feeds: string[];
  /** `report.ENOUGH`: the count below which no rate is characterised. */
  enough: number;
  measured: Measured[];
  costs: Cost[];
}

/** A research figure beside a live one. Every field is `null` when none exists. */
export interface Measured {
  strategy: string;
  trades: number | null;
  win_rate: number | null;
  mean_r: number | null;
  se_r: number | null;
  hold_seconds: number | null;
  source: string;
}

/** Realised entry cost per feed, in the units the journal recorded. */
export interface Cost {
  feed: string;
  trades: number;
  median_spread: number | null;
  mean_spread: number | null;
  median_slippage: number | null;
  worst_spread: number | null;
}

export interface RefusalMark {
  time: number;
  price: number | null;
  level: number | null;
  gate: string;
  strategy: string;
  side: string;
  feed: string;
  why: string;
}

export interface LevelLine {
  price: number;
  label: string;
  traded: number;
  refused: number;
}

export interface Event {
  time: number;
  kind: string;
  strategy: string;
  feed: string;
  gate: string;
  title: string;
  why: string;
}

export interface Pulse {
  strategy: string;
  taken: number;
  refused: number;
  last_seen: number | null;
  feeds: string[];
  gates: Decline[];
}

export interface Activity {
  hours: number;
  now: number;
  /** Seconds since the newest trading entry. `null` when there are none. */
  age: number | null;
  taken: number;
  refused: number;
  strategies: Pulse[];
  gates: Decline[];
  recent: Event[];
}

export interface Position {
  ticket: string;
  symbol: string;
  feed: string;
  side: string;
  volume: number;
  entry: number | null;
  price: number | null;
  stop: number | null;
  target: number | null;
  profit: number | null;
  opened: number | null;
  magic: number | null;
  protected: boolean;
}

export interface AccountView {
  currency: string;
  balance: number | null;
  equity: number | null;
  margin: number | null;
  free_margin: number | null;
  leverage: number | null;
}

export interface Cap {
  name: string;
  used: number;
  ceiling: number | null;
  unit: string;
  binding: boolean;
  note: string;
}

export interface Mismatch {
  where: string;
  symbol: string;
  side: string;
  ticket: string;
  detail: string;
}

export interface Book {
  present: boolean;
  taken_at: number | null;
  age: number | null;
  stale: boolean;
  account: AccountView;
  positions: Position[];
  unprotected: Position[];
  engine_open: number;
  mismatches: Mismatch[];
  caps: Cap[];
  currencies: Record<string, number>;
  message: string;
}

export interface LevelRecord {
  level_id: string;
  named: boolean;
  feed: string;
  interval: string;
  price: number;
  trades: number;
  wins: number;
  hit_rate: number;
  net: number;
  strategies: string[];
  endings: Record<string, number>;
}

export interface Levels {
  totals: Record<string, number>;
  records: LevelRecord[];
  message: string;
}

export interface Series {
  feed: string;
  interval: string;
  source: string;
  venue: string;
  bars: number | null;
  first: number | null;
  last: number | null;
}

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Marker {
  time: number;
  price: number;
  kind: "entry" | "exit";
  side: string;
  strategy: string;
  r: number;
  label: string;
}

export interface Chart {
  feed: string;
  interval: string;
  source: string;
  venue: string;
  bars: Bar[];
  markers: Marker[];
  refusals: RefusalMark[];
  levels: LevelLine[];
  message: string;
}

export interface SourceState {
  name: string;
  kind: string;
  path: string;
  present: boolean;
  detail: string;
}

export interface JournalRow {
  actor: string;
  kind: string;
  entries: number;
  first: number;
  last: number;
}

export interface Health {
  sources: SourceState[];
  entries: JournalRow[];
  trades: number;
  message: string;
}

/** What the controls at the top of the page are set to. */
export interface Filters {
  days: number | null;
  mode: string;
  strategy: string;
  feed: string;
}
