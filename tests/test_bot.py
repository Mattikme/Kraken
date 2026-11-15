"""Tests unitaires : aucune connexion réseau ni base de données nécessaire."""
import pytest

from bot import backtest, config, history, kraken_api, strategy
from bot.portfolio import FlatFee, Portfolio, TieredFee


# ---------- stratégies ----------

def test_sma_cross_attend_assez_d_historique_puis_suit_la_tendance():
    closes = [100.0] * 5 + [110.0, 120.0, 130.0] + [90.0, 80.0, 70.0, 60.0]
    target = strategy.sma_cross(closes, fast=2, slow=4)
    assert target[:3] == [None, None, None]          # pas assez de données
    assert target[3] is False                        # moyennes égales -> pas en BTC
    assert target[6] is True                         # hausse -> en BTC
    assert target[-1] is False                       # baisse -> en EUR


def test_momentum_entre_au_dessus_du_seuil_et_sort_sous_zero():
    closes = [100.0, 100.0, 103.0, 104.0, 104.5, 103.0]
    target = strategy.momentum(closes, hours=2, enter=0.02, exit_=0.0)
    assert target[:2] == [None, None]
    assert target[2] is True                         # +3 % sur 2 h -> achat
    assert target[4] is True                         # +1,5 % : entre les seuils -> on garde
    assert target[5] is False                        # -1 % -> vente


@pytest.mark.parametrize("fn", [strategy.sma_cross, strategy.momentum])
def test_les_strategies_ne_regardent_jamais_le_futur(fn):
    closes = [100 + (i * 37 % 23) - 0.1 * i for i in range(300)]
    full = fn(closes)
    for cut in (60, 150, 299):
        assert fn(closes[:cut + 1])[cut] == full[cut]


def _hourly(day_closes, hours_per_day=24):
    """Bougies 1 h : chaque jour reste au même prix (sa clôture)."""
    return [{"ts": d * 86400 + h * 3600, "open": p, "high": p, "low": p, "close": p, "volume": 1.0}
            for d, p in enumerate(day_closes) for h in range(hours_per_day)]


def test_strategie_journaliere_decide_avec_les_jours_termines_seulement():
    candles = _hourly([100, 100, 100, 100, 130, 140, 60, 50, 40])
    target = strategy.daily_sma_cross(candles, fast=2, slow=4)
    by_day = [target[d * 24:(d + 1) * 24] for d in range(9)]
    assert all(len(set(day)) == 1 for day in by_day)           # une seule décision par jour
    daily = [day[0] for day in by_day]
    assert daily[:4] == [None, None, None, None]               # il faut 4 jours terminés
    assert daily[4] is False                                   # jours 0-3 plats
    assert daily[5] is True                                    # la hausse du jour 4 compte au jour 5
    assert daily[8] is False                                   # la chute est prise en compte


def test_strategie_journaliere_ne_regarde_jamais_le_futur():
    candles = _hourly([100 + (d * 37 % 23) - 0.3 * d for d in range(120)])
    del candles[500:505]                                       # quelques heures manquantes
    full = strategy.daily_sma_cross(candles)
    for cut in (24 * 60 + 5, 24 * 90, len(candles) - 1):
        assert strategy.daily_sma_cross(candles[:cut + 1])[cut] == full[cut]


def test_signal():
    assert strategy.signal(False, True) == "BUY"
    assert strategy.signal(True, False) == "SELL"
    assert strategy.signal(True, True) == "HOLD"
    assert strategy.signal(None, None) == "HOLD"


# ---------- frais, glissement, portefeuille ----------

def test_achat_puis_vente_applique_frais_et_glissement():
    pf = Portfolio(1000.0, FlatFee(0.008), slippage=0.0005)
    buy = pf.buy(0, 50_000.0)
    assert buy["price"] == pytest.approx(50_025.0)               # +0,05 %
    assert buy["fee"] == pytest.approx(1000 / 1.008 * 0.008)
    assert buy["qty"] * buy["price"] + buy["fee"] == pytest.approx(1000.0)
    sell = pf.sell(3600, 50_000.0)                               # prix inchangé
    assert sell["price"] == pytest.approx(49_975.0)              # -0,05 %
    # Aller-retour à prix constant : on perd environ 2 x (0,80 % + 0,05 %).
    assert pf.cash == pytest.approx(1000 / 1.008 / 50_025 * 49_975 * 0.992)
    assert pf.cash < 1000 and pf.round_trips[0] < 0


def test_pas_de_vente_a_decouvert_ni_d_achat_sans_cash():
    pf = Portfolio(1000.0, FlatFee(0.008))
    assert pf.sell(0, 50_000.0) is None
    pf.buy(0, 50_000.0)
    assert pf.buy(1, 50_000.0) is None


def test_frais_par_paliers_selon_le_volume_30_jours():
    fee = TieredFee()
    assert fee.rate(0) == 0.0080                     # palier 1
    fee.record(0, 3_000)
    assert fee.rate(10) == 0.0060                    # > 2 500
    fee.record(10, 8_000)
    assert fee.rate(20) == 0.0038                    # > 10 000
    assert fee.rate(config.FEE_WINDOW_SECONDS + 5) == 0.0060   # le 1er ordre sort de la fenêtre
    assert fee.rate(config.FEE_WINDOW_SECONDS + 20) == 0.0080  # tout est sorti


# ---------- backtest ----------

def _candles(prices):
    """Bougies horaires simples : (ouverture, clôture) pour chaque heure."""
    return [{"ts": i * 3600, "open": o, "high": max(o, c), "low": min(o, c), "close": c, "volume": 1.0}
            for i, (o, c) in enumerate(prices)]


def test_drawdown_max():
    assert backtest.max_drawdown_pct([100, 120, 90, 110, 60, 200]) == pytest.approx(50.0)
    assert backtest.max_drawdown_pct([100, 110, 120]) == 0.0


def test_execution_a_l_ouverture_de_la_bougie_suivante():
    candles = _candles([(100, 100), (100, 100), (200, 200), (200, 200)])
    target = [None, True, True, False]               # décision d'achat à la clôture de l'heure 1
    pf, curve = backtest.simulate(candles, target, 1, FlatFee(0.0), capital=1000.0)
    assert pf.trades[0]["ts"] == 2 * 3600            # exécuté à l'ouverture de l'heure 2...
    assert pf.trades[0]["price"] == pytest.approx(200 * 1.0005)   # ...au prix de l'heure 2
    assert curve[:2] == [(3600, 1000.0), (7200, 1000.0)]   # encore en cash pendant l'heure 1


def test_buy_and_hold_sert_de_reference():
    candles = _candles([(100, 100)] * 80 + [(100 + i, 101 + i) for i in range(100)])
    results = backtest.run(candles, lambda: FlatFee(0.008), start_ts=60 * 3600)
    bh = results["buy_and_hold"]
    assert bh["stats"]["n_trades"] == 1 and bh["stats"]["beats_buy_hold"] is None
    assert bh["stats"]["final_eur"] == pytest.approx(1000 / 1.008 / (100 * 1.0005) * 200)
    for name in ("sma_cross_20_50", "momentum_24h", "sma_cross_daily_20_50", "trend_ensemble"):
        assert results[name]["stats"]["beats_buy_hold"] in (True, False)
        assert results[name]["curve"][0] == (60 * 3600, 1000.0)   # même départ pour toutes


def test_compte_les_heures_manquantes():
    candles = _candles([(1, 1)] * 3)
    candles[2]["ts"] = 5 * 3600
    assert backtest.count_gaps(candles) == 3


# ---------- données Kraken ----------

def test_parse_ohlc_ecarte_la_bougie_en_cours():
    result = {"XXBTZEUR": [[3600, "10", "12", "9", "11", "10.5", "2.5", 7],
                           [7200, "11", "11", "11", "11", "11", "0.1", 1]], "last": 3600}
    candles = kraken_api.parse_ohlc(result)
    assert candles == [{"ts": 3600, "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 2.5}]


def test_regroupement_des_transactions_en_bougies():
    trades = [(3600.5, 10.0, 1.0), (3700.0, 12.0, 0.5), (7199.9, 9.0, 0.5), (7200.0, 9.5, 2.0)]
    assert history.aggregate_trades(trades) == [
        {"ts": 3600, "open": 10.0, "high": 12.0, "low": 9.0, "close": 9.0, "volume": 2.0},
        {"ts": 7200, "open": 9.5, "high": 9.5, "low": 9.5, "close": 9.5, "volume": 2.0}]


# ---------- simulation en direct ----------

def test_signaux_dates_a_la_cloture_et_coherents_avec_les_ordres():
    from bot import paper_trader
    candles = _candles([(100, 100)] * 5)
    target = [None, True, True, False, False]
    pf, curve = backtest.simulate(candles, target, 1, FlatFee(0.0), capital=1000.0)
    signals = paper_trader.signals_for(candles, 1, target, pf.trades, curve)
    assert [s["signal"] for s in signals] == ["BUY", "HOLD", "SELL", "HOLD"]
    assert signals[0]["ts"] == 2 * 3600 == pf.trades[0]["ts"]    # signal 02:00 -> achat 02:00
    assert signals[2]["ts"] == 4 * 3600 == pf.trades[1]["ts"]    # signal 04:00 -> vente 04:00


def test_simulation_rejouable_sans_doublon():
    from bot import paper_trader
    candles = _candles([(100, 100)] * 80 + [(100 + i, 101 + i) for i in range(100)])
    start_ts = 60 * 3600
    results = backtest.run(candles, lambda: FlatFee(0.008), start_ts)
    done_ts = candles[-1]["ts"]                                   # tout sauf la dernière clôture
    done = {name: done_ts for name in results if name != "trend_ensemble"}   # stratégie ajoutée après coup
    statements = paper_trader.build_statements(results, candles, start_ts, done, "2026-01-01")
    import json
    equity = {p[0]: json.loads(p[1]) for sql, p in statements if "INSERT INTO equity" in sql}
    new = equity.pop("trend_ensemble")
    assert all(len(rows) == 1 and rows[0]["ts"] == done_ts + 3600 for rows in equity.values())
    assert new[0]["ts"] == start_ts and len(new) == len(results["trend_ensemble"]["curve"])   # tout son historique
    assert all("ON CONFLICT" in sql for sql, _ in statements)    # aucune écriture en double
    assert sum("INSERT INTO signals" in sql for sql, _ in statements) == 4   # pas pour le buy & hold


# ---------- recherche : exposition partielle et stratégies candidates ----------

def test_reequilibrage_partiel_respecte_frais_et_cible():
    pf = Portfolio(1000.0, FlatFee(0.01), slippage=0.0)
    pf.rebalance(0, 100.0, 0.5)                                   # viser 50 % de BTC
    assert pf.btc * 100.0 == pytest.approx(500.0)
    assert pf.cash == pytest.approx(1000 - 500 - 5)               # 5 EUR de frais
    pf.rebalance(1, 100.0, 0.0)                                   # tout revendre
    assert pf.btc == 0 and pf.cash == pytest.approx(495 + 500 * 0.99)
    pf.rebalance(2, 100.0, 1.0)                                   # tout investir, frais compris
    assert pf.cash == pytest.approx(0.0, abs=1e-9)
    assert pf.rebalance(3, 100.0, 1.0) is None                    # déjà investi : aucun ordre


def test_simulation_partielle_ne_trade_que_hors_de_la_bande():
    candles = _candles([(100, 100)] * 4 + [(104, 104), (200, 200), (200, 200)])
    target = [None] + [0.5] * 6
    pf, _ = backtest.simulate(candles, target, 1, FlatFee(0.0), capital=1000.0)
    # Achat initial à l'heure 2 ; +4 % ne déclenche rien ; le doublement (BTC = 67 %) déclenche une vente.
    assert [(t["ts"], t["side"]) for t in pf.trades] == [(2 * 3600, "buy"), (5 * 3600, "sell")]
    assert pf.btc * 200.0 / pf.value(200.0) == pytest.approx(0.5, abs=0.001)


def test_les_candidates_ne_regardent_jamais_le_futur():
    from bot import research
    closes = [100 * (1 + 0.3 * ((d * 37 % 23) / 23 - 0.5) + 0.002 * d) for d in range(330)]
    candles = _hourly(closes)
    for name, fn in research.CANDIDATES.items():
        full = fn(candles)
        for cut in (24 * 250 + 7, 24 * 300, len(candles) - 1):
            assert fn(candles[:cut + 1])[cut] == full[cut], name
        assert all(v is None or v is True or v is False or 0.0 <= v <= 1.0 for v in full), name


def test_regles_candidates_sur_des_cas_simples():
    from bot import research
    rising = [100.0 + d for d in range(260)]
    days = list(range(260))
    assert research.trend_sma200(days, rising)[-1] is True
    assert research.trend_sma200(days, rising[::-1])[-1] is False
    assert research.trend_ensemble(days, rising)[-1] == 1.0
    assert research.trend_ensemble(days, rising[::-1])[-1] == 0.0
    assert research.weekday(0) == 3 and research.weekday(3) == 6          # 1970-01-01 = jeudi
    weekly = research.tsmom_4w(days, rising)
    assert weekly[27] is None and weekly[31] is True                      # 1re décision un dimanche
    calm = [100.0 * (1.001 ** d) for d in range(60)]
    assert research.vol_target(days[:60], calm)[-1] == 1.0                # marché calme : 100 %
    wild = [100.0 * (1.2 if d % 2 else 1.0) for d in range(60)]
    assert research.vol_target(days[:60], wild)[-1] < 0.2                 # marché agité : peu de BTC


def test_signaux_et_position_pour_une_exposition_partielle():
    from bot import paper_trader
    candles = _candles([(100, 100)] * 6)
    target = [None, 0.5, 0.5, 0.75, 0.0, 0.0]
    pf, curve = backtest.simulate(candles, target, 1, FlatFee(0.0), capital=1000.0)
    signals = paper_trader.signals_for(candles, 1, target, pf.trades, curve)
    # clôtures 1..5 : acheter (0 -> 50 %), rien, acheter (50 -> 75 %), vendre (75 -> 0 %), rien
    assert [s["signal"] for s in signals] == ["BUY", "HOLD", "BUY", "SELL", "HOLD"]
    weights = paper_trader.weights_at_close(candles, 1, pf.trades, curve)
    assert weights == pytest.approx([0.0, 0.5, 0.5, 0.75, 0.0], abs=0.002)
    assert [paper_trader.position_label(w) for w in (0.0, 0.25, 0.752, 1.0)] == ["EUR", "25 % BTC", "75 % BTC", "BTC"]
