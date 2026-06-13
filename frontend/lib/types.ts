// Typed interfaces for every backend payload the terminal consumes.

export type SessionStatus = "premarket" | "rth" | "after_hours" | "closed";
export type Bias = "long" | "short" | "neutral" | "no_trade";
export type Environment =
  | "continuation"
  | "consolidation"
  | "mean_reversion"
  | "reversal_risk"
  | "event_risk"
  | "no_trade";
export type GexRegimeLabel = "positive" | "negative" | "near_flip" | "unknown";
export type Direction = "UP" | "DOWN" | "NEUTRAL" | "CHOP";

export interface LastPrice {
  symbol: string;
  price: number | null;
  source: string | null;
  timestamp_ny: string | null;
  age_seconds: number | null;
}

export interface Summary {
  symbol: string;
  proxy_symbols: string[];
  session_date: string;
  session_status: SessionStatus;
  now_ny: string;
  last_price: LastPrice;
  scores: {
    bias: Bias | null;
    environment: Environment | null;
    confidence: number | null;
    kronos_respect: number | null;
    kronos_hourly_direction: Direction | null;
    kronos_daily_direction: Direction | null;
    gex_regime: GexRegimeLabel;
    gex_score: number | null;
    cot_score: number | null;
    cot_label: string | null;
    news_score: number | null;
    red_folder: boolean;
  };
  data_health: Record<
    string,
    { ok: boolean; [key: string]: unknown }
  >;
}

export interface KronosSeries {
  timestamps: string[];
  kronos_path: number[];
  band_upper: number[] | null;
  band_lower: number[] | null;
  observed: (number | null)[];
  kalman_estimate: (number | null)[];
  residuals: (number | null)[];
  residual_z: (number | null)[];
}

export interface RespectScore {
  score: number;
  label: string;
  forecast_status: string;
  direction_score: number;
  correlation_score: number;
  band_respect_score: number;
  kalman_residual_score: number;
  invalidation_score: number;
  invalidation_count: number;
  explanation: Record<string, string>;
}

export interface KalmanInfo {
  slider: number;
  slider_label: string;
  tracking_error: number | null;
  mean_abs_z: number | null;
  max_abs_z: number | null;
  direction_agreement: number | null;
  band_respect_fraction: number | null;
  failure_warning: boolean;
  inverted: boolean;
  explanation: Record<string, unknown>;
}

export interface ForecastInfo {
  id: number;
  symbol: string;
  direction: Direction;
  confidence: number | null;
  generated_at_ny: string | null;
  forecast_start_ny: string | null;
  forecast_end_ny: string | null;
  model_version: string | null;
  source: string;
  band_width_avg: number | null;
  metadata: Record<string, unknown> | null;
}

export interface KronosView {
  status: "ok" | "kronos_unavailable";
  message?: string;
  horizon: string;
  forecast?: ForecastInfo;
  series?: KronosSeries;
  kalman?: KalmanInfo;
  respect?: RespectScore;
  deviation?: { points: number | null; percent: number | null };
  daily_direction?: Direction | null;
  availability?: {
    local_runner_enabled: boolean;
    local_runner_available: boolean;
    reason: string;
    manual_import_available: boolean;
  };
  history?: ForecastHistoryRow[];
  live_price?: LastPrice;
}

export interface ForecastHistoryRow {
  id: number;
  horizon: string;
  direction: Direction;
  confidence: number | null;
  source: string;
  generated_at_ny: string | null;
  forecast_start_ny: string | null;
  forecast_end_ny: string | null;
  points: number;
  model_version: string | null;
}

export interface GexRegimeInfo {
  regime: GexRegimeLabel;
  score: number | null;
  distance_to_flip: number | null;
  distance_to_flip_pct: number | null;
  distance_to_call_wall: number | null;
  distance_to_put_wall: number | null;
  guidance: string[];
  explanation: string;
}

export interface GexSnapshotView {
  id: number;
  timestamp_ny: string | null;
  symbol: string;
  proxy_for: string;
  underlying_price: number | null;
  net_gex: number | null;
  net_gex_label: string | null;
  gamma_flip: number | null;
  call_wall: number | null;
  put_wall: number | null;
  largest_positive_gex_strike: number | null;
  largest_negative_gex_strike: number | null;
  status: string;
  error_message: string | null;
  regime: GexRegimeInfo;
  converted_to_trading_symbol: {
    gamma_flip: number | null;
    call_wall: number | null;
    put_wall: number | null;
    largest_positive_gex_strike: number | null;
    largest_negative_gex_strike: number | null;
    method: string;
    factor: number;
    approximate: true;
    disclaimer: string;
  };
  net_gex_change?: number;
  gamma_flip_change?: number;
}

export interface GexView {
  latest: GexSnapshotView | null;
  latest_error: { status: string; error_message: string; timestamp_ny: string } | null;
  todays_snapshots: GexSnapshotView[];
  day_trend: "rising" | "falling" | "flat" | null;
  schedule_ny: string[];
  age_minutes: number | null;
  is_stale: boolean | null;
  stale_threshold_minutes: number;
}

export interface CotGroup {
  report_type: string;
  group: string;
  report_date: string | null;
  long_positions: number | null;
  short_positions: number | null;
  net_position: number | null;
  net_percentile: number | null;
  four_week_change: number | null;
  thirteen_week_change: number | null;
  crowding_score: number | null;
  score: number | null;
  label: string;
  explanation: Record<string, unknown>;
}

export interface CotView {
  market: string | null;
  market_code: string | null;
  proxy_note: string;
  report_date: string | null;
  as_of_date: string | null;
  staleness: {
    is_stale: boolean;
    age_days: number | null;
    newest_report_available: boolean;
    note: string;
  };
  headline: CotGroup | null;
  groups: CotGroup[];
  score_history: {
    report_date: string;
    score: number;
    net_position: number | null;
    net_percentile: number | null;
    four_week_change: number | null;
    thirteen_week_change: number | null;
    crowding_score: number | null;
  }[];
  last_checked_ny: string;
}

export interface NewsItemView {
  id: number;
  timestamp_ny: string | null;
  source: string | null;
  title: string;
  url: string;
  sentiment: number;
  sentiment_label: "bullish" | "bearish" | "neutral";
  volatility: "low" | "medium" | "high";
  relevance: "low" | "medium" | "high";
  urgency: "low" | "medium" | "high";
  red_folder: boolean;
  matched: Record<string, string[]> | null;
}

export interface NewsView {
  risk_score: {
    score: number;
    red_folder_flag: boolean;
    summary: string;
    timestamp_ny: string | null;
    metadata: Record<string, unknown> | null;
  } | null;
  items: NewsItemView[];
  note: string;
}

export interface RegimeSnapshotView {
  id: number;
  timestamp_ny: string | null;
  symbol: string;
  bias: Bias;
  environment: Environment;
  confidence: number;
  kronos_score: number | null;
  gex_score: number | null;
  cot_score: number | null;
  news_score: number | null;
  playbook: string | null;
  reasons: string[];
  invalidations: string[];
  what_would_change_my_mind: string[];
  confidence_terms: string[];
}

export interface RegimeView {
  current: RegimeSnapshotView | null;
  history: RegimeSnapshotView[];
}

export interface AlertView {
  id: number;
  timestamp_ny: string | null;
  alert_type: string;
  severity: "info" | "warn" | "critical";
  title: string;
  message: string;
  metadata: Record<string, unknown> | null;
  acknowledged: boolean;
}

export interface Candle {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

export interface PricesView {
  symbol: string;
  candles: Candle[];
  live: LastPrice;
}
