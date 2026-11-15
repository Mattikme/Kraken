"""Simulation en direct (« paper trading ») : aucun argent réel, aucune clé API.

À chaque passage (après la collecte), les stratégies sont rejouées depuis le
début de la simulation avec exactement les règles du backtest : décision à la
clôture d'une bougie 1 h, exécution à l'ouverture de la suivante, frais preneur
Kraken et glissement de 0,05 %. Le calcul est déterministe : relancer le script
ne change rien et ne crée aucun doublon ; une panne se rattrape toute seule.

Écrit dans Neon : signals, trades et equity (mode 'paper'), paper_results.
"""
import json
from datetime import datetime, timezone

from . import backtest, config, db
from .portfolio import TieredFee

HOUR = 3600


def signals_for(candles, start_index, target, trades):
    """Signal émis à la clôture de chaque bougie : ACHETER / VENDRE / RIEN.

    Le signal compare ce que veut la stratégie à ce que détient le portefeuille.
    Il est daté de la clôture (= heure d'ouverture de la bougie où il sera exécuté).
    """
    side_at = {t["ts"]: t["side"] for t in trades}
    in_btc, out = False, []
    for i in range(start_index, len(candles)):
        candle = candles[i]
        if candle["ts"] in side_at:                      # ordre exécuté à l'ouverture
            in_btc = side_at[candle["ts"]] == "buy"
        wanted = target[i]
        if wanted is None or wanted == in_btc:
            signal = "HOLD"
        else:
            signal = "BUY" if wanted else "SELL"
        out.append({"ts": candle["ts"] + HOUR, "signal": signal, "price": candle["close"]})
    return out


def build_statements(results, candles, start_ts, done_ts, now_iso):
    """Requêtes d'écriture : seules les lignes plus récentes que `done_ts` sont envoyées."""
    start_index = max(1, next(i for i, c in enumerate(candles) if c["ts"] >= start_ts))
    end_ts = candles[-1]["ts"] + HOUR
    statements = []
    for name, res in results.items():
        s = res["stats"]
        statements.append((
            """INSERT INTO paper_results (strategy, run_at, start_ts, end_ts, start_eur, final_eur,
                 return_pct, n_trades, n_round_trips, win_rate_pct, fees_eur, max_drawdown_pct,
                 beats_buy_hold, position)
               VALUES ($1,$2,to_timestamp($3),to_timestamp($4),$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
               ON CONFLICT (strategy) DO UPDATE SET
                 run_at = EXCLUDED.run_at, end_ts = EXCLUDED.end_ts, final_eur = EXCLUDED.final_eur,
                 return_pct = EXCLUDED.return_pct, n_trades = EXCLUDED.n_trades,
                 n_round_trips = EXCLUDED.n_round_trips, win_rate_pct = EXCLUDED.win_rate_pct,
                 fees_eur = EXCLUDED.fees_eur, max_drawdown_pct = EXCLUDED.max_drawdown_pct,
                 beats_buy_hold = EXCLUDED.beats_buy_hold, position = EXCLUDED.position""",
            [name, now_iso, start_ts, end_ts, config.START_CAPITAL_EUR, s["final_eur"],
             s["return_pct"], s["n_trades"], s["n_round_trips"], s["win_rate_pct"], s["fees_eur"],
             s["max_drawdown_pct"], s["beats_buy_hold"], "BTC" if res["in_btc"] else "EUR"]))
        statements.append((
            """INSERT INTO trades (strategy, ts, side, price, qty, fee, mode)
               SELECT $1, to_timestamp(t.ts), t.side, t.price, t.qty, t.fee, 'paper'
               FROM jsonb_to_recordset($2::jsonb)
                    AS t(ts bigint, side text, price numeric, qty numeric, fee numeric)
               ON CONFLICT DO NOTHING""",
            [name, json.dumps(res["trades"])]))
        equity = [{"ts": ts, "v": v} for ts, v in res["curve"] if ts > done_ts]
        statements.append((
            """INSERT INTO equity (strategy, ts, value_eur, mode)
               SELECT $1, to_timestamp(e.ts), e.v, 'paper'
               FROM jsonb_to_recordset($2::jsonb) AS e(ts bigint, v numeric)
               ON CONFLICT DO NOTHING""",
            [name, json.dumps(equity)]))
        if name != "buy_and_hold":                       # le buy & hold n'émet pas de signal
            signals = [x for x in signals_for(candles, start_index, res["target"], res["trades"])
                       if x["ts"] > done_ts]
            statements.append((
                """INSERT INTO signals (strategy, ts, signal, price)
                   SELECT $1, to_timestamp(x.ts), x.signal, x.price
                   FROM jsonb_to_recordset($2::jsonb) AS x(ts bigint, signal text, price numeric)
                   ON CONFLICT DO NOTHING""",
                [name, json.dumps(signals)]))
    return statements


def main():
    db.init_schema()
    start_ts = config.PAPER_START_TS
    iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    _, _, last = db.candle_range(config.PAIR)
    if last is None or last < start_ts:
        print(f"La simulation démarre avec la bougie de {iso(start_ts)} : pas encore terminée.")
        return
    row = db.query("SELECT extract(epoch FROM max(ts))::bigint AS done FROM equity WHERE mode = 'paper'")[0]
    done_ts = int(row["done"]) if row["done"] is not None else 0
    if done_ts >= last + HOUR:
        print(f"Rien de nouveau depuis la clôture de {iso(done_ts)}.")
        return

    candles = db.load_candles(config.PAIR, start_ts - config.WARMUP_DAYS * 86400, last + 1)
    results = backtest.run(candles, TieredFee, start_ts)
    now_iso = datetime.now(timezone.utc).isoformat()
    db.transaction(build_statements(results, candles, start_ts, done_ts, now_iso))

    print(f"Simulation du {iso(start_ts)} à la clôture de {iso(last + HOUR)} :")
    for name, res in results.items():
        s = res["stats"]
        print(f"  {name:<23}{s['final_eur']:>10.2f} EUR  {s['n_trades']:>3} ordre(s)  "
              f"position : {'BTC' if res['in_btc'] else 'EUR'}")


if __name__ == "__main__":
    main()
