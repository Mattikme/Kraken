"""Accès à Neon (Postgres) par son API HTTP : seul `requests` est nécessaire.

La chaîne de connexion vient de la variable d'environnement DATABASE_URL
(secret GitHub). Elle n'est jamais écrite dans le code ni dans les logs.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import requests

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "schema.sql"


def _database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL manquante : ajoute le secret GitHub DATABASE_URL.")
    return url


def _post(body):
    url = _database_url()
    resp = requests.post(
        f"https://{urlparse(url).hostname}/sql",
        headers={"Neon-Connection-String": url, "Content-Type": "application/json"},
        data=json.dumps(body),
        timeout=120,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Erreur Neon {resp.status_code} : {resp.text[:300]}")
    return resp.json()


def query(sql, params=()):
    """Exécute une requête et renvoie les lignes (liste de dictionnaires)."""
    return _post({"query": sql, "params": list(params)})["rows"]


def transaction(statements):
    """Exécute plusieurs requêtes [(sql, params), ...] en une seule transaction."""
    _post({"queries": [{"query": s, "params": list(p)} for s, p in statements]})


def init_schema():
    """Crée les tables si elles n'existent pas (schema.sql est idempotent)."""
    lines = [l for l in SCHEMA_FILE.read_text().splitlines() if not l.strip().startswith("--")]
    for statement in "\n".join(lines).split(";"):
        if statement.strip():
            query(statement)


def upsert_candles(pair, candles, chunk=5000):
    """Enregistre des bougies sans doublon (clé primaire pair+ts).

    Si la bougie existe déjà, elle est remplacée : rejouer la collecte ne
    crée donc jamais de ligne en double.
    """
    sql = """
        INSERT INTO candles (pair, ts, open, high, low, close, volume)
        SELECT $1, to_timestamp(c.ts), c.open, c.high, c.low, c.close, c.volume
        FROM jsonb_to_recordset($2::jsonb)
             AS c(ts bigint, open numeric, high numeric, low numeric, close numeric, volume numeric)
        ON CONFLICT (pair, ts) DO UPDATE
        SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, volume = EXCLUDED.volume
    """
    for i in range(0, len(candles), chunk):
        query(sql, [pair, json.dumps(candles[i:i + chunk])])


def load_candles(pair, since_ts, until_ts, page=20000):
    """Bougies de [since_ts, until_ts) triées par date (ts en secondes UTC).

    Lecture par pages pour rester sous la taille maximale d'une réponse Neon.
    """
    candles, cursor = [], since_ts
    while True:
        rows = query(
            """SELECT extract(epoch FROM ts)::bigint AS ts, open::float8 AS open,
                      high::float8 AS high, low::float8 AS low, close::float8 AS close,
                      volume::float8 AS volume
               FROM candles
               WHERE pair = $1 AND ts >= to_timestamp($2) AND ts < to_timestamp($3)
               ORDER BY ts LIMIT $4""",
            [pair, cursor, until_ts, page],
        )
        candles += [{k: (int(v) if k == "ts" else float(v)) for k, v in r.items()} for r in rows]
        if len(rows) < page:
            return candles
        cursor = candles[-1]["ts"] + 1


def candle_range(pair):
    """(nombre de bougies, premier ts, dernier ts) ; ts à None si la table est vide."""
    r = query(
        """SELECT count(*) AS n, extract(epoch FROM min(ts))::bigint AS first,
                  extract(epoch FROM max(ts))::bigint AS last
           FROM candles WHERE pair = $1""",
        [pair],
    )[0]
    to_int = lambda v: None if v is None else int(v)
    return int(r["n"]), to_int(r["first"]), to_int(r["last"])


def last_candle_before(pair, ts):
    """ts de la dernière bougie strictement avant `ts` (None s'il n'y en a pas)."""
    r = query("""SELECT extract(epoch FROM max(ts))::bigint AS last FROM candles
                 WHERE pair = $1 AND ts < to_timestamp($2)""", [pair, ts])[0]
    return None if r["last"] is None else int(r["last"])
