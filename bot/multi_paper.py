"""Simulation en direct du portefeuille multi-actifs (argent fictif, aucune clé API).

Portefeuille « tendance pondérée par le risque » : actions américaines (SPYx),
or (GLDx) et bitcoin ; chaque actif n'est détenu que s'il est en tendance
haussière (cours de fin de mois au-dessus de la moyenne des 10 dernières fins
de mois), avec une part d'autant plus petite qu'il est volatil. Le reste est
en EUR. Décision en fin de mois, exécutée à la clôture du jour suivant.

Uniquement des cours Kraken (bougies d'un jour collectées dans Neon). Le calcul
est rejoué depuis le départ à chaque passage : pas de doublon, rattrapage automatique.
"""
import json
from datetime import date, datetime, timezone

from . import backtest, config, db, multi

NAME = multi.RETAINED
HISTORY_DAYS = 480        # assez de fins de mois pour la tendance (10) et la volatilité (13)


def position_label(curve_value, qty, price):
    """Ex. « Actions 45 % · Or 40 % · EUR 15 % »."""
    labels = {"ACTIONS": "Actions", "OR": "Or", "BTC": "Bitcoin"}
    parts, invested = [], 0.0
    for asset, label in labels.items():
        weight = qty.get(asset, 0.0) * price[asset] / curve_value if curve_value else 0.0
        invested += weight
        if round(weight * 100) > 0:
            parts.append(f"{label} {round(weight * 100)} %")
    cash = round((1 - invested) * 100)
    if cash > 0:
        parts.append(f"EUR {cash} %")
    return " · ".join(parts)


def main():
    db.init_schema()
    start_day = (date(*config.MULTI_START) - multi.EPOCH).days
    # Dernier jour complet commun à toutes les séries.
    _, _, last_btc = db.candle_range(config.PAIR)
    last_days = [last_btc // 86400 - 1]
    for pair in config.DAILY_PAIRS:
        _, _, last = db.candle_range(pair)
        if last is None:
            print(f"Pas encore de bougies pour {pair} : le collecteur doit passer d'abord.")
            return
        last_days.append(last // 86400)
    end_day = min(last_days)
    if end_day < start_day:
        print("La simulation du portefeuille n'a pas encore commencé.")
        return

    days, prices = multi.load_prices(start_day - HISTORY_DAYS, end_day, kraken_only=True)
    curve, orders, paid = multi.replay(multi.CANDIDATES[NAME], days, prices, start_day)
    values = [v for _, v in curve]
    qty = {}
    for o in orders:
        qty[o["asset"]] = qty.get(o["asset"], 0.0) + (o["qty"] if o["side"] == "buy" else -o["qty"])
    last_price = {a: prices[a][-1] for a in prices}
    now = datetime.now(timezone.utc).isoformat()

    statements = [(
        """INSERT INTO paper_results (strategy, run_at, start_ts, end_ts, start_eur, final_eur, return_pct,
             n_trades, n_round_trips, win_rate_pct, fees_eur, max_drawdown_pct, beats_buy_hold, position)
           VALUES ($1,$2,to_timestamp($3),to_timestamp($4),$5,$6,$7,$8,0,NULL,$9,$10,NULL,$11)
           ON CONFLICT (strategy) DO UPDATE SET
             run_at = EXCLUDED.run_at, end_ts = EXCLUDED.end_ts, final_eur = EXCLUDED.final_eur,
             return_pct = EXCLUDED.return_pct, n_trades = EXCLUDED.n_trades, fees_eur = EXCLUDED.fees_eur,
             max_drawdown_pct = EXCLUDED.max_drawdown_pct, position = EXCLUDED.position""",
        [NAME, now, multi.close_ts(start_day), multi.close_ts(end_day), config.START_CAPITAL_EUR, values[-1],
         (values[-1] / config.START_CAPITAL_EUR - 1) * 100, len(orders), paid,
         backtest.max_drawdown_pct(values), position_label(values[-1], qty, last_price) or "EUR 100 %"]), (
        """INSERT INTO equity (strategy, ts, value_eur, mode)
           SELECT $1, to_timestamp(e.ts), e.v, 'paper'
           FROM jsonb_to_recordset($2::jsonb) AS e(ts bigint, v numeric)
           ON CONFLICT DO NOTHING""",
        [NAME, json.dumps([{"ts": multi.close_ts(d), "v": v} for d, v in curve])]), (
        """INSERT INTO trades (strategy, ts, side, price, qty, fee, mode, pair)
           SELECT $1, to_timestamp(t.ts), t.side, t.price, t.qty, t.fee, 'paper', t.pair
           FROM jsonb_to_recordset($2::jsonb)
                AS t(ts bigint, pair text, side text, price numeric, qty numeric, fee numeric)
           ON CONFLICT DO NOTHING""",
        [NAME, json.dumps(multi.trade_rows(orders))])]
    db.transaction(statements)
    print(f"Portefeuille {NAME} : {values[-1]:.2f} EUR à la clôture du {multi.to_date(end_day).isoformat()}, "
          f"{len(orders)} ordre(s), position : {position_label(values[-1], qty, last_price) or 'EUR 100 %'}")


if __name__ == "__main__":
    main()
