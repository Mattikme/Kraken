"""Historique : remplit Neon avec 10 ans de bougies 1 h BTC/EUR.

L'API OHLC de Kraken ne donne que les 720 dernières bougies (30 jours).
On assemble donc trois sources, toutes officielles Kraken :
  1. l'archive OHLCVT téléchargeable (historique complet, mise à jour par trimestre)
     https://support.kraken.com/articles/360047124832 ;
  2. l'endpoint public Trades, pour le trou entre la fin de l'archive et
     le début de la fenêtre OHLC (les transactions sont regroupées par heure) ;
  3. l'endpoint public OHLC pour les 30 derniers jours.
Rejouable sans risque : pas de doublons, et rien n'est retéléchargé si c'est déjà là.
"""
import csv
import io
import time
import zipfile

import requests

from . import config, db, kraken_api

ARCHIVE_URL = "https://assets.kraken.com/marketing/institutions/Kraken_OHLCVT_Full.zip.part{:02d}"
ARCHIVE_PARTS = 5
HOUR = 3600


class RemoteParts:
    """Lit l'archive ZIP (10 Go en 5 morceaux) À DISTANCE, sans la télécharger :
    seuls les octets utiles sont demandés au serveur (requêtes HTTP « Range »)."""

    BLOCK = 4 * 1024 * 1024

    def __init__(self, urls):
        self.session = requests.Session()
        self.urls = urls
        self.sizes = [int(self.session.head(u, timeout=60).headers["content-length"]) for u in urls]
        self.total, self.pos, self.cache = sum(self.sizes), 0, {}

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset + (0, self.pos, self.total)[whence]
        return self.pos

    def _download(self, start, end):
        """Octets [start, end) de l'archive complète (peut chevaucher deux morceaux)."""
        data, part_start = b"", 0
        for url, size in zip(self.urls, self.sizes):
            lo, hi = max(start, part_start), min(end, part_start + size)
            if lo < hi:
                rng = f"bytes={lo - part_start}-{hi - part_start - 1}"
                resp = self.session.get(url, headers={"Range": rng}, timeout=120)
                resp.raise_for_status()
                data += resp.content
            part_start += size
        return data

    def read(self, n=-1):
        end = self.total if n < 0 else min(self.total, self.pos + n)
        out = b""
        while self.pos < end:
            index = self.pos // self.BLOCK
            if index not in self.cache:
                lo = index * self.BLOCK
                self.cache[index] = self._download(lo, min(self.total, lo + self.BLOCK))
            offset = self.pos - index * self.BLOCK
            chunk = self.cache[index][offset:offset + end - self.pos]
            out += chunk
            self.pos += len(chunk)
        return out


def candles_from_archive(since_ts):
    """Bougies 1 h de l'archive officielle, à partir de `since_ts`."""
    remote = RemoteParts([ARCHIVE_URL.format(i) for i in range(ARCHIVE_PARTS)])
    wanted = f"{config.PAIR}_{config.INTERVAL_MIN}.csv"
    with zipfile.ZipFile(remote) as archive:
        name = next(n for n in archive.namelist() if n.split("/")[-1] == wanted)
        text = archive.read(name).decode()
    candles = []
    for row in csv.reader(io.StringIO(text)):   # ts, open, high, low, close, volume, trades
        if int(row[0]) >= since_ts:
            candles.append({"ts": int(row[0]), "open": float(row[1]), "high": float(row[2]),
                            "low": float(row[3]), "close": float(row[4]), "volume": float(row[5])})
    return candles


def aggregate_trades(trades):
    """Regroupe des transactions (ts, prix, volume) triées par date en bougies 1 h."""
    candles = {}
    for ts, price, volume in trades:
        hour = int(ts) // HOUR * HOUR
        c = candles.get(hour)
        if c is None:
            candles[hour] = {"ts": hour, "open": price, "high": price, "low": price,
                             "close": price, "volume": volume}
        else:
            c["high"], c["low"] = max(c["high"], price), min(c["low"], price)
            c["close"] = price
            c["volume"] += volume
    return [candles[h] for h in sorted(candles)]


def candles_from_trades(start_ts, end_ts):
    """Bougies 1 h reconstruites depuis les transactions, pour [start_ts, end_ts)."""
    trades, cursor = [], start_ts * 1_000_000_000
    while cursor < end_ts * 1_000_000_000:
        page, new_cursor = kraken_api.fetch_trades(config.PAIR, cursor)
        if not page or new_cursor == cursor:
            break
        trades.extend(page)
        cursor = new_cursor
        time.sleep(1.1)                         # respecte la limite de débit publique
    return aggregate_trades([t for t in trades if start_ts <= t[0] < end_ts])


def main():
    db.init_schema()
    recent = kraken_api.fetch_ohlc(config.PAIR, config.INTERVAL_MIN)        # source 3
    now = recent[-1]["ts"]
    since = now - config.HISTORY_DAYS * 86400

    _, first, _ = db.candle_range(config.PAIR)                              # source 1
    if first is not None and first <= since + 86400:
        print("Archive déjà chargée : rien à télécharger.")
    else:
        archive = candles_from_archive(since)
        db.upsert_candles(config.PAIR, archive)
        print(f"Archive officielle : {len(archive)} bougies.")

    # Trou éventuel entre la dernière bougie stockée et la fenêtre OHLC.   # source 2
    gap_end = recent[0]["ts"]
    gap_start = db.last_candle_before(config.PAIR, gap_end) + HOUR
    if gap_start < gap_end:
        # On reconstruit 3 h de plus que nécessaire pour comparer avec l'API OHLC.
        rebuilt = candles_from_trades(gap_start, gap_end + 3 * HOUR)
        official = {c["ts"]: c for c in recent}
        for c in rebuilt:
            ref = official.get(c["ts"])
            if ref and any(abs(c[k] - ref[k]) > 1e-6 * ref[k] for k in ("open", "high", "low", "close")):
                raise SystemExit(f"Incohérence transactions / OHLC à ts={c['ts']} : {c} vs {ref}")
        db.upsert_candles(config.PAIR, [c for c in rebuilt if c["ts"] < gap_end])
        print(f"Transactions regroupées : {len(rebuilt)} bougies (contrôle de cohérence OK).")

    db.upsert_candles(config.PAIR, recent)
    n, first, last = db.candle_range(config.PAIR)
    print(f"Neon contient {n} bougies {config.PAIR} "
          f"(attendu environ {(last - max(first, since)) // HOUR + 1}).")


if __name__ == "__main__":
    main()
