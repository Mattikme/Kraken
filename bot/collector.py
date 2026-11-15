"""Collecteur : récupère les bougies 1 h terminées de BTC/EUR et les stocke dans Neon.

Lancé toutes les 15 min par GitHub Actions. Rejouable sans risque (pas de doublons).
"""
from datetime import datetime, timezone

from . import config, db, kraken_api


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main():
    db.init_schema()
    candles = kraken_api.fetch_ohlc(config.PAIR, config.INTERVAL_MIN)
    if not candles:
        raise SystemExit("Kraken n'a renvoyé aucune bougie.")
    db.upsert_candles(config.PAIR, candles)
    n, first, last = db.candle_range(config.PAIR)
    print(f"Reçu {len(candles)} bougies ({iso(candles[0]['ts'])} -> {iso(candles[-1]['ts'])}).")
    print(f"Neon contient {n} bougies {config.PAIR} ({iso(first)} -> {iso(last)}).")

    # Bougies d'un jour des autres actifs du portefeuille (ETF tokenisés, EUR/USD).
    for pair, asset_class in config.DAILY_PAIRS.items():
        daily = kraken_api.fetch_ohlc(pair, 1440, asset_class=asset_class)
        db.upsert_candles(pair, daily)
        print(f"{pair} : {len(daily)} bougies d'un jour, dernière clôture {daily[-1]['close']} ({iso(daily[-1]['ts'])}).")


if __name__ == "__main__":
    main()
