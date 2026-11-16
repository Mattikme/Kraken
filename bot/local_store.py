"""Stockage local (SQLite, fourni avec Python) : aucune base externe nécessaire.

Contient les bougies Kraken et quelques réglages fixés au premier lancement
(date de départ de la simulation). Tout le reste est recalculé à chaque passage.
"""
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS candles (
              pair TEXT NOT NULL, interval INTEGER NOT NULL, ts INTEGER NOT NULL,
              open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
              close REAL NOT NULL, volume REAL NOT NULL,
              PRIMARY KEY (pair, interval, ts));
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)

    def upsert(self, pair, interval, candles):
        """Enregistre des bougies sans doublon (une bougie déjà présente est remplacée)."""
        self.conn.executemany(
            "INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?)",
            [(pair, interval, c["ts"], c["open"], c["high"], c["low"], c["close"], c["volume"])
             for c in candles])
        self.conn.commit()

    def candles(self, pair, interval):
        rows = self.conn.execute(
            "SELECT ts, open, high, low, close, volume FROM candles "
            "WHERE pair = ? AND interval = ? ORDER BY ts", (pair, interval))
        return [{"ts": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
                for r in rows]

    def get(self, key):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def set(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))
        self.conn.commit()
