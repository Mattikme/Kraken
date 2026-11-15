-- Schéma Neon du bot Kraken. Idempotent : peut être rejoué sans risque.

-- Bougies 1 h (une ligne par paire et par heure, pas de doublon possible).
CREATE TABLE IF NOT EXISTS candles (
  pair   text        NOT NULL,
  ts     timestamptz NOT NULL,          -- début de la bougie (UTC)
  open   numeric     NOT NULL,
  high   numeric     NOT NULL,
  low    numeric     NOT NULL,
  close  numeric     NOT NULL,
  volume numeric     NOT NULL,
  PRIMARY KEY (pair, ts)
);

-- Signaux émis en direct (simulation puis réel). Vide pendant le backtest.
CREATE TABLE IF NOT EXISTS signals (
  strategy text        NOT NULL,
  ts       timestamptz NOT NULL,
  signal   text        NOT NULL CHECK (signal IN ('BUY', 'SELL', 'HOLD')),
  price    numeric     NOT NULL,
  PRIMARY KEY (strategy, ts)
);

-- Trades exécutés. mode : 'backtest' (rejoué), 'paper' (fictif en direct), 'live' (réel).
CREATE TABLE IF NOT EXISTS trades (
  strategy text        NOT NULL,
  ts       timestamptz NOT NULL,
  side     text        NOT NULL CHECK (side IN ('buy', 'sell')),
  price    numeric     NOT NULL,        -- prix d'exécution, glissement inclus
  qty      numeric     NOT NULL,        -- quantité de BTC
  fee      numeric     NOT NULL,        -- frais en EUR
  mode     text        NOT NULL CHECK (mode IN ('backtest', 'paper', 'live')),
  PRIMARY KEY (strategy, ts, mode)
);

-- Valeur du portefeuille dans le temps.
CREATE TABLE IF NOT EXISTS equity (
  strategy  text        NOT NULL,
  ts        timestamptz NOT NULL,
  value_eur numeric     NOT NULL,
  mode      text        NOT NULL CHECK (mode IN ('backtest', 'paper', 'live')),
  PRIMARY KEY (strategy, ts, mode)
);

-- Résumé du dernier backtest (une ligne par stratégie, hypothèse de frais et durée).
CREATE TABLE IF NOT EXISTS backtest_results (
  strategy         text        NOT NULL,
  fee_model        text        NOT NULL,   -- 'kraken_tiers' (réel) ou 'flat_0.80' (pire cas)
  period_days      integer     NOT NULL,   -- 730 = période jugée, 3650 = contrôle sur 10 ans
  run_at           timestamptz NOT NULL,
  start_ts         timestamptz NOT NULL,
  end_ts           timestamptz NOT NULL,
  start_eur        numeric     NOT NULL,
  final_eur        numeric     NOT NULL,
  return_pct       numeric     NOT NULL,
  n_trades         integer     NOT NULL,   -- nombre d'ordres exécutés
  n_round_trips    integer     NOT NULL,   -- achats suivis d'une vente
  win_rate_pct     numeric,                -- NULL si aucun aller-retour clôturé
  fees_eur         numeric     NOT NULL,
  max_drawdown_pct numeric     NOT NULL,
  beats_buy_hold   boolean,                -- NULL pour le buy & hold lui-même
  params           jsonb       NOT NULL,
  PRIMARY KEY (strategy, fee_model, period_days)
);
