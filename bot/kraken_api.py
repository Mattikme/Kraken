"""Client minimal de l'API PUBLIQUE de Kraken (aucune clé nécessaire).

Endpoints utilisés (doc : https://docs.kraken.com/api/docs/rest-api/get-ohlc-data
et .../get-recent-trades) :
  GET /0/public/OHLC   -> bougies (720 dernières au maximum)
  GET /0/public/Trades -> transactions (1000 par appel, pagination par `since`)
"""
import time

import requests

BASE_URL = "https://api.kraken.com/0/public"


class KrakenError(RuntimeError):
    pass


def _get(endpoint, params, retries=5):
    """Appel GET avec quelques essais en cas d'erreur réseau ou de limite de débit."""
    last_error = None
    for attempt in range(retries):
        try:
            resp = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                raise KrakenError(str(data["error"]))
            return data["result"]
        except (requests.RequestException, KrakenError, ValueError) as exc:
            last_error = exc
            time.sleep(2 * (attempt + 1))  # attente croissante : 2 s, 4 s, 6 s...
    raise KrakenError(f"{endpoint} a échoué après {retries} essais : {last_error}")


def _rows(result):
    """La réponse contient {nom_de_paire: [...], 'last': ...} : on isole la liste."""
    key = next(k for k in result if k != "last")
    return result[key]


def parse_ohlc(result, drop_last=True):
    """Convertit la réponse OHLC en bougies (dictionnaires).

    Format Kraken d'une ligne : [time, open, high, low, close, vwap, volume, count].
    La DERNIÈRE ligne est la bougie en cours (pas terminée) : on l'écarte par
    défaut pour ne jamais stocker ni utiliser une bougie incomplète.
    """
    rows = _rows(result)
    if drop_last:
        rows = rows[:-1]
    return [
        {"ts": int(r[0]), "open": float(r[1]), "high": float(r[2]),
         "low": float(r[3]), "close": float(r[4]), "volume": float(r[6])}
        for r in rows
    ]


def fetch_ohlc(pair, interval_min, since=None, asset_class=None):
    """Bougies terminées les plus récentes (Kraken en renvoie 720 au maximum).
    Pour un ETF tokenisé (SPYx, GLDx...), passer asset_class="tokenized_asset"."""
    params = {"pair": pair, "interval": interval_min}
    if since is not None:
        params["since"] = since
    if asset_class is not None:
        params["asset_class"] = asset_class
    return parse_ohlc(_get("OHLC", params))


def fetch_trades(pair, since_ns):
    """Une page de transactions à partir de `since_ns` (nanosecondes).

    Renvoie (liste de (timestamp, prix, volume), curseur `last` pour la page suivante).
    Format Kraken d'une ligne : [price, volume, time, side, type, misc, trade_id].
    """
    result = _get("Trades", {"pair": pair, "since": since_ns, "count": 1000})
    trades = [(float(r[2]), float(r[0]), float(r[1])) for r in _rows(result)]
    return trades, int(result["last"])
