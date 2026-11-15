// Lecture de Neon. Le tableau de bord n'écrit jamais : DATABASE_URL pointe
// vers un rôle Postgres en lecture seule. Tout ce qui est affiché vient d'ici.
import { neon } from "@neondatabase/serverless";

export type Mode = "paper" | "backtest";

export type Result = {
  strategy: string;
  final_eur: number;
  return_pct: number;
  n_trades: number;
  n_round_trips: number;
  win_rate_pct: number | null;
  fees_eur: number;
  max_drawdown_pct: number;
  beats_buy_hold: boolean | null;
  start_eur: number;
  start_ts: number;
  end_ts: number;
  run_at: number;
  position: string | null;
};

export type Point = { ts: number; v: number };
export type Trade = { strategy: string; ts: number; side: string; price: number; qty: number; fee: number; pair: string };
export type Candle = { ts: number; close: number };
export type Signal = { strategy: string; ts: number; signal: string };

export type Data = {
  results: Result[];
  equity: Record<string, Point[]>;
  trades: Trade[];
  lastCandle: Candle | null;
  signals: Signal[];
};

const RESULT_COLUMNS = `strategy, final_eur::float8 AS final_eur, return_pct::float8 AS return_pct,
  n_trades, n_round_trips, win_rate_pct::float8 AS win_rate_pct, fees_eur::float8 AS fees_eur,
  max_drawdown_pct::float8 AS max_drawdown_pct, beats_buy_hold, start_eur::float8 AS start_eur,
  extract(epoch FROM start_ts)::float8 AS start_ts, extract(epoch FROM end_ts)::float8 AS end_ts,
  extract(epoch FROM run_at)::float8 AS run_at`;

export async function loadData(mode: Mode, strategies: string[]): Promise<Data> {
  const url = process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL manquante");
  const sql = neon(url);

  const resultsQuery =
    mode === "paper"
      ? sql.query(`SELECT ${RESULT_COLUMNS}, position FROM paper_results`)
      : sql.query(
          `SELECT ${RESULT_COLUMNS}, NULL AS position FROM backtest_results
           WHERE fee_model = 'kraken_tiers' AND period_days = 730`,
        );

  const [results, equityRows, trades, candles, signals] = await Promise.all([
    resultsQuery,
    sql.query(
      `SELECT strategy, extract(epoch FROM ts)::float8 AS ts, value_eur::float8 AS v
       FROM equity WHERE mode = $1 AND strategy = ANY($2) ORDER BY ts`,
      [mode, strategies],
    ),
    sql.query(
      `SELECT strategy, extract(epoch FROM ts)::float8 AS ts, side, price::float8 AS price,
              qty::float8 AS qty, fee::float8 AS fee, pair
       FROM trades WHERE mode = $1 ORDER BY ts DESC, strategy, pair LIMIT 12`,
      [mode],
    ),
    sql.query(
      `SELECT extract(epoch FROM ts)::float8 AS ts, close::float8 AS close
       FROM candles WHERE pair = 'XBTEUR' ORDER BY ts DESC LIMIT 1`,
    ),
    sql.query(
      `SELECT DISTINCT ON (strategy) strategy, extract(epoch FROM ts)::float8 AS ts, signal
       FROM signals ORDER BY strategy, ts DESC`,
    ),
  ]);

  const equity: Record<string, Point[]> = {};
  for (const row of equityRows as { strategy: string; ts: number; v: number }[]) {
    (equity[row.strategy] ??= []).push({ ts: row.ts, v: row.v });
  }
  return {
    results: results as Result[],
    equity,
    trades: trades as Trade[],
    lastCandle: (candles[0] as Candle) ?? null,
    signals: signals as Signal[],
  };
}
