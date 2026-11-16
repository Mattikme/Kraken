"""Tests du bot local (aucun accès réseau : Kraken est remplacé par des bougies synthétiques)."""
import math

import pytest

from bot import local
from bot.local_store import Store

HOUR, DAY = 3600, 86400
NOW = 1_800_000_000 // DAY * DAY          # minuit UTC, date arbitraire


def candle(ts, price):
    return {"ts": ts, "open": price, "high": price, "low": price, "close": price, "volume": 1.0}


def fake_fetch(now):
    """Simule l'API Kraken à l'instant `now` : bougies terminées uniquement."""
    def fetch(pair, interval, asset_class=None):
        step = interval * 60
        last = now // step * step - step                  # dernière bougie terminée
        base = {"XBTEUR": 60000, "SPYxUSD": 600, "GLDxUSD": 300, "EURUSD": 1.1}[pair]
        out = []
        for k in range(720):
            ts = last - (719 - k) * step
            out.append(candle(ts, base * (1 + 0.2 * math.sin(ts / (40 * DAY)) + ts / DAY * 1e-4)))
        return out
    return fetch


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "DATA_DIR", tmp_path)
    return Store(tmp_path / "bot.sqlite")


def test_store_upsert_no_duplicates(store):
    store.upsert("XBTEUR", 60, [candle(0, 1.0), candle(HOUR, 2.0)])
    store.upsert("XBTEUR", 60, [candle(HOUR, 3.0)])
    assert [c["close"] for c in store.candles("XBTEUR", 60)] == [1.0, 3.0]
    store.set("k", 5)
    assert store.get("k") == "5" and store.get("absent") is None


def test_btc_series_fills_days_without_hourly_candles(store):
    store.upsert("XBTEUR", 1440, [candle(d * DAY, 10.0 + d) for d in range(5)])
    store.upsert("XBTEUR", 60, [candle(3 * DAY + h * HOUR, 100.0) for h in range(24)])
    series = local.btc_series(store)
    days = [c["ts"] // DAY for c in series]
    assert days[:3] == [0, 1, 2]                          # jours 0-2 : bougie d'un jour, placée à 23 h
    assert series[0]["ts"] == 23 * HOUR
    assert all(d == 3 for d in days[3:])                  # jour 3 : bougies 1 h ; jour 4 (en cours) exclu
    assert len(series) == 3 + 24


def test_tick_starts_flat_then_trades_and_is_replayable(store):
    state = local.tick(store, fake_fetch(NOW))
    main = state["strategies"][local.MAIN]["stats"]
    assert main["final_eur"] == pytest.approx(1000.0)
    assert set(state["strategies"]) == {local.MAIN}       # stratégies bitcoin : pas encore de bougie
    start = store.get("btc_start_ts")

    later = NOW + 40 * DAY
    state = local.tick(store, fake_fetch(later))
    assert store.get("btc_start_ts") == start             # départ figé au premier passage
    assert set(state["strategies"]) == {local.MAIN, *local.STRATEGIES}
    bh = state["strategies"]["buy_and_hold"]
    assert bh["stats"]["n_trades"] == 1 and bh["position"] == "BTC"
    for res in state["strategies"].values():
        assert res["stats"]["final_eur"] > 0

    again = local.tick(store, fake_fetch(later))           # même instant : même résultat
    for name, res in state["strategies"].items():
        assert again["strategies"][name]["stats"] == res["stats"]
    assert (local.DATA_DIR / "rapport.html").exists()
    assert (local.DATA_DIR / "ordres.csv").read_text().count("\n") > 1


def test_quick_backtest_runs(store, capsys):
    local.collect(store, fake_fetch(NOW))
    local.quick_backtest(store)
    assert "acheter et garder" in capsys.readouterr().out
