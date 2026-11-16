"""Tests du tournoi local (aucun accès réseau : cours synthétiques)."""
import math

import pytest

from bot import arena, bots, local, multi, universe
from bot.local_store import Store

DAY = 86400
NOW_DAY = 20_000                                     # jour arbitraire (2024-10-04)


def candle(ts, price):
    return {"ts": ts, "open": price, "high": price, "low": price, "close": price, "volume": 1.0}


BASE = {"XBTEUR": 60000, "ETHEUR": 3000, "SOLEUR": 150, "SPYxUSD": 600, "QQQxUSD": 500,
        "GLDxUSD": 300, "EURUSD": 1.1, "EURGBP": 0.85, "EURJPY": 160, "EURCHF": 0.95,
        "EURAUD": 1.6, "EURCAD": 1.5}


def price_at(pair, day):
    k = list(BASE).index(pair)
    return BASE[pair] * math.exp(0.25 * math.sin(day / (30 + 7 * k)) + 0.0004 * (day - 19000) * (k % 3 - 1))


def fake_fetch(today):
    """L'API Kraken vue le jour `today` : 720 bougies d'un jour terminées."""
    def fetch(pair, interval, asset_class=None):
        return [candle(d * DAY, price_at(pair, d)) for d in range(today - 720, today)]
    return fetch


def synthetic(n=900):
    days = list(range(NOW_DAY - n, NOW_DAY))
    by_pair = {pair: {d: price_at(pair, d) for d in days} for pair in BASE}
    return days, universe.to_eur(by_pair, days, multi.forward_fill)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(local, "DATA_DIR", tmp_path)
    return Store(tmp_path / "bot.sqlite")


def test_store_upsert_no_duplicates(store):
    store.upsert("XBTEUR", 1440, [candle(0, 1.0), candle(DAY, 2.0)])
    store.upsert("XBTEUR", 1440, [candle(DAY, 3.0)])
    assert [c["close"] for c in store.candles("XBTEUR", 1440)] == [1.0, 3.0]
    store.set("k", 5)
    assert store.get("k") == "5" and store.get("absent") is None


def test_to_eur_conversions():
    days = [0, 1]
    by_pair = {"EURUSD": {0: 1.25}, "XBTEUR": {0: 50000.0}, "SPYxUSD": {1: 500.0}, "EURJPY": {0: 160.0}}
    prices = universe.to_eur(by_pair, days, multi.forward_fill)
    assert prices["BTC"] == [50000.0, 50000.0]
    assert prices["SP500"] == [None, 400.0]          # 500 USD / 1,25 ; absent le premier jour
    assert prices["USD"] == [0.8, 0.8]               # 1 USD = 1 / 1,25 EUR
    assert prices["JPY"][0] == pytest.approx(1 / 160)
    assert prices["ETH"] == [None, None]


def test_simulate_fees_and_lag():
    days = [0, 1, 2, 3]
    prices = {a: [None] * 4 for a in universe.ASSETS}
    prices["SP500"] = [100.0, 100.0, 110.0, 110.0]
    targets = [{"SP500": 1.0}, None, {}, None]       # achat décidé jour 0, vente décidée jour 2
    r = arena.simulate(days, prices, targets)
    buy, sell = r["orders"]
    assert (buy["i"], buy["side"], sell["i"], sell["side"]) == (1, "buy", 3, "sell")
    rate = universe.XSTOCK_FEE + 0.0005
    assert r["values"][-1] == pytest.approx(1000 * (1 - rate) * 1.10 * (1 - rate))
    assert r["values"][0] == 1000 and r["weights"][-1] == {}


def test_bots_use_only_the_past():
    """Changer les cours après le jour i ne change aucune décision prise jusqu'au jour i."""
    days, prices = synthetic()
    cut = 700
    altered = {a: p[:cut + 1] + [x * 3 if x else x for x in p[cut + 1:]] for a, p in prices.items()}
    for name, (fn, _, _) in bots.BOTS.items():
        assert fn(days, prices)[:cut + 1] == fn(days, altered)[:cut + 1], name


def test_targets_are_valid_allocations():
    days, prices = synthetic()
    results = bots.run_all(days, prices)
    assert set(results) == set(bots.BOTS) | {bots.META}
    for name, r in results.items():
        assert all(v > 0 for v in r["values"]), name
        for w in r["weights"]:
            assert sum(w.values()) <= 1.0 + 1e-9 and all(x >= 0 for x in w.values()), name


def test_readiness_rules():
    live = {"days": 120, "return_pct": 8.0, "drawdown_pct": 6.0}
    bench = {"return_pct": 3.0}
    assert local.readiness(live, bench, {"drawdown_pct": 25.0}) == (True, [])
    ok, reasons = local.readiness(dict(live, days=10, return_pct=1.0), bench, None)
    assert not ok and len(reasons) == 3


def test_tick_fixes_start_and_is_replayable(store):
    state = local.tick(store, fake_fetch(NOW_DAY), pause=0)
    start = store.get("start_day")
    assert all(b["live"]["final"] == pytest.approx(1000.0) for b in state["board"].values())

    later = NOW_DAY + 30
    state = local.tick(store, fake_fetch(later), pause=0)
    assert store.get("start_day") == start
    assert state["board"][bots.BENCHMARK]["live"]["days"] == 30
    again = local.tick(store, fake_fetch(later), pause=0)
    for name, b in state["board"].items():
        assert again["board"][name]["live"]["final"] == pytest.approx(b["live"]["final"])
    assert (local.DATA_DIR / "rapport.html").exists()
    assert (local.DATA_DIR / "etat.json").exists()


def test_history_from_cached_series(store):
    def fetch(symbol):
        pair = next(p for _, p, _, _, s, _ in universe.ASSETS.values() if s == symbol)
        return [(local.to_date(d).isoformat(), price_at(pair, d)) for d in range(15700, NOW_DAY)]
    local.download_history(store, fetch, pause=0)
    hist = local.run_history(store)
    assert set(hist["bots"]) == set(bots.BOTS) | {bots.META}
    assert all(m["cagr_pct"] is not None for m in hist["bots"].values())
