"""Cours journaliers externes pour la RECHERCHE (jamais pour passer des ordres).

Kraken propose des ETF tokenisés (SPYx, GLDx...) mais seulement depuis 2025 :
trop court pour un test. On utilise donc l'historique des ETF d'origine
(clôture ajustée, dividendes réinvestis) et du taux EUR/USD, pris sur Yahoo
Finance, et on le range dans Neon (table daily_prices) pour que le test soit
rejouable à l'identique. À lancer à la main ; la source est notée dans la table.
"""
import json
from datetime import datetime, timezone

import requests

from . import db

SYMBOLS = {"SPY": "SPY", "GLD": "GLD", "EURUSD": "EURUSD=X"}   # nom en base -> symbole Yahoo
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}"


def fetch(yahoo_symbol):
    """Renvoie [(jour 'AAAA-MM-JJ', clôture ajustée)] depuis 2004."""
    resp = requests.get(URL.format(yahoo_symbol), timeout=60, headers={"User-Agent": "Mozilla/5.0"},
                        params={"period1": 1072915200, "period2": 4102444800, "interval": "1d"})
    resp.raise_for_status()
    result = resp.json()["chart"]["result"][0]
    indicators = result["indicators"]
    closes = (indicators.get("adjclose") or [{}])[0].get("adjclose") or indicators["quote"][0]["close"]
    rows = {}
    for ts, close in zip(result["timestamp"], closes):
        if close is not None and close > 0:
            rows[datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")] = float(close)
    return sorted(rows.items())


def save(symbol, rows, source):
    db.query(
        """INSERT INTO daily_prices (symbol, day, close, source)
           SELECT $1, r.day, r.close, $2
           FROM jsonb_to_recordset($3::jsonb) AS r(day date, close numeric)
           ON CONFLICT (symbol, day) DO UPDATE SET close = EXCLUDED.close, source = EXCLUDED.source""",
        [symbol, source, json.dumps(rows)])
    print(f"{symbol}: {len(rows)} jours ({rows[0]['day']} -> {rows[-1]['day']}), dernier cours {rows[-1]['close']:.4f}")


def main():
    db.init_schema()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Bitcoin avant 2016 : clôtures journalières de l'archive officielle Kraken
    # (les bougies 1 h de Neon ne remontent qu'à 2016 ; elles priment ensuite).
    from .history import candles_from_archive
    btc = [{"day": datetime.fromtimestamp(c["ts"], timezone.utc).strftime("%Y-%m-%d"), "close": c["close"]}
           for c in candles_from_archive(0, interval_min=1440)]
    save("BTCEUR", btc, "Archive OHLCVT officielle Kraken, XBTEUR journalier")
    for symbol, yahoo_symbol in SYMBOLS.items():
        rows = [{"day": d, "close": c} for d, c in fetch(yahoo_symbol)]
        save(symbol, rows, f"Yahoo Finance {yahoo_symbol}, relevé le {today}")


if __name__ == "__main__":
    main()
