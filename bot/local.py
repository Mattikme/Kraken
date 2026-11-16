"""Bot autonome en local : collecte Kraken + simulation sur 1 000 € fictifs.

Aucune clé API, aucune base externe : les bougies sont gardées dans un fichier
SQLite (dossier `donnees/`). Mêmes règles que le backtest : décision à la
clôture d'une bougie, exécution à l'ouverture de la suivante, frais preneur
Kraken réels et glissement de 0,05 %.

Le départ de la simulation est fixé au premier lancement, puis tout est rejoué
depuis ce départ à chaque passage : relancer le bot ne crée aucun doublon et
une coupure se rattrape toute seule (dans la limite des 720 dernières bougies
1 h que fournit Kraken ; au-delà, les jours manquants passent en bougies d'un jour).

Stratégie principale : le portefeuille multi-actifs « tendance pondérée par le
risque » (actions, or, bitcoin), le meilleur compromis rendement / pire baisse
mesuré sur 10 ans. Les stratégies bitcoin tournent à côté pour comparaison,
chacune avec ses propres 1 000 € fictifs.
"""
import csv
import html
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import backtest, config, kraken_api, multi, multi_paper, paper_trader
from .local_store import Store
from .portfolio import TieredFee
from .strategy import STRATEGIES, sma_cross, trend_ensemble_daily

HOUR, DAY = 3600, 86400
DATA_DIR = Path(os.environ.get("KRAKEN_BOT_DIR", Path(__file__).resolve().parent.parent / "donnees"))
MAIN = multi.RETAINED

# (paire Kraken, bougie en minutes, classe d'actif pour l'API)
SOURCES = [
    (config.PAIR, 60, None),
    (config.PAIR, 1440, None),
    ("SPYxUSD", 1440, "tokenized_asset"),
    ("GLDxUSD", 1440, "tokenized_asset"),
    ("EURUSD", 1440, None),
]

LABELS = {
    MAIN: "Portefeuille actions + or + bitcoin (principal)",
    "trend_ensemble": "Bitcoin · ensemble de tendances",
    "sma_cross_daily_20_50": "Bitcoin · moyennes 20/50 jours",
    "sma_cross_20_50": "Bitcoin · moyennes 20/50 heures",
    "momentum_24h": "Bitcoin · momentum 24 h",
    "buy_and_hold": "Bitcoin · acheter et garder (référence)",
}

log = logging.getLogger("bot")


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------- données ----------

def collect(store, fetch=kraken_api.fetch_ohlc):
    """Récupère les bougies terminées de chaque source et les enregistre."""
    for pair, interval, asset_class in SOURCES:
        store.upsert(pair, interval, fetch(pair, interval, asset_class=asset_class))


def btc_series(store):
    """Bougies 1 h de BTC/EUR. Un jour sans aucune bougie 1 h (avant le premier
    lancement, ou après une longue coupure) est représenté par sa bougie d'un
    jour, placée à 23 h : les stratégies journalières n'utilisent que la clôture."""
    hourly = store.candles(config.PAIR, 60)
    covered = {c["ts"] // DAY for c in hourly}
    filler = [dict(c, ts=c["ts"] + 23 * HOUR) for c in store.candles(config.PAIR, 1440)
              if c["ts"] // DAY not in covered]
    if hourly:   # pas de bougie d'un jour après la dernière bougie 1 h (jour en cours incomplet)
        filler = [c for c in filler if c["ts"] < hourly[-1]["ts"]]
    return sorted(hourly + filler, key=lambda c: c["ts"])


def daily_prices(store, first_day, last_day):
    """Cours journaliers en EUR (actions, or, bitcoin) au format de bot.multi."""
    days = list(range(first_day, last_day + 1))
    by_day = lambda pair: {c["ts"] // DAY: c["close"] for c in store.candles(pair, 1440)}
    fx = multi.forward_fill(days, by_day("EURUSD"))
    prices = {"BTC": multi.forward_fill(days, by_day(config.PAIR))}
    for name, pair in (("ACTIONS", "SPYxUSD"), ("OR", "GLDxUSD")):
        usd = multi.forward_fill(days, by_day(pair))
        prices[name] = [None if p is None or f is None else p / f for p, f in zip(usd, fx)]
    return days, prices


def last_full_day(store):
    """Dernier jour UTC dont toutes les séries journalières ont une clôture."""
    lasts = []
    for pair, interval, _ in SOURCES:
        if interval == 1440:
            candles = store.candles(pair, interval)
            if not candles:
                return None
            lasts.append(candles[-1]["ts"] // DAY)
    return min(lasts)


# ---------- simulation ----------

def start_points(store):
    """Départ de la simulation, fixé une fois pour toutes au premier passage."""
    if store.get("btc_start_ts") is None:
        hourly = store.candles(config.PAIR, 60)
        store.set("btc_start_ts", hourly[-1]["ts"] + HOUR)       # prochaine bougie 1 h
        store.set("multi_start_day", last_full_day(store))        # clôture du dernier jour complet
        store.set("created_at", datetime.now(timezone.utc).isoformat())
    return int(store.get("btc_start_ts")), int(store.get("multi_start_day"))


def simulate_btc(store, start_ts):
    """Stratégies bitcoin. Renvoie {nom: résultat} (vide si le départ n'est pas atteint)."""
    candles = btc_series(store)
    if not candles or candles[-1]["ts"] < start_ts:
        return {}
    results = backtest.run(candles, TieredFee, start_ts)
    start_index = max(1, next(i for i, c in enumerate(candles) if c["ts"] >= start_ts))
    out = {}
    for name, res in results.items():
        weights = paper_trader.weights_at_close(candles, start_index, res["trades"], res["curve"])
        out[name] = {
            "stats": res["stats"],
            "position": paper_trader.position_label(weights[-1]),
            "curve": res["curve"],
            "trades": [dict(t, pair=config.PAIR) for t in res["trades"]],
        }
    return out


def simulate_multi(store, start_day):
    """Portefeuille principal (cours Kraken uniquement, bougies d'un jour)."""
    end_day = last_full_day(store)
    days, prices = daily_prices(store, start_day - multi_paper.HISTORY_DAYS, end_day)
    curve, orders, paid = multi.replay(multi.CANDIDATES[MAIN], days, prices, start_day)
    values = [v for _, v in curve]
    qty = {}
    for o in orders:
        qty[o["asset"]] = qty.get(o["asset"], 0.0) + (o["qty"] if o["side"] == "buy" else -o["qty"])
    last_price = {a: prices[a][-1] for a in prices}
    return {
        "stats": {"final_eur": values[-1],
                  "return_pct": (values[-1] / config.START_CAPITAL_EUR - 1) * 100,
                  "n_trades": len(orders), "fees_eur": paid,
                  "max_drawdown_pct": backtest.max_drawdown_pct(values)},
        "position": multi_paper.position_label(values[-1], qty, last_price) or "EUR 100 %",
        "curve": [(multi.close_ts(d), v) for d, v in curve],
        "trades": multi.trade_rows(orders),
    }


def tick(store, fetch=kraken_api.fetch_ohlc):
    """Un passage complet : collecte, simulation, rapports. Renvoie l'état."""
    collect(store, fetch)
    btc_start, multi_start = start_points(store)
    results = {MAIN: simulate_multi(store, multi_start)}
    results.update(simulate_btc(store, btc_start))
    state = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "btc_start": iso(btc_start), "multi_start": iso(multi.close_ts(multi_start)),
        "btc_price": store.candles(config.PAIR, 60)[-1]["close"],
        "strategies": results,
    }
    write_reports(state)
    return state


# ---------- rapports ----------

def summary_rows(state):
    rows = []
    for name, res in state["strategies"].items():
        s = res["stats"]
        rows.append({"name": name, "label": LABELS.get(name, name), "value": s["final_eur"],
                     "return": s["return_pct"], "orders": s["n_trades"], "fees": s["fees_eur"],
                     "drawdown": s["max_drawdown_pct"], "position": res["position"]})
    return rows


def print_status(state):
    print(f"\nMis à jour : {state['updated_at']}  ·  BTC/EUR : {state['btc_price']:,.1f}".replace(",", " "))
    print(f"Départ : portefeuille {state['multi_start']} · bitcoin {state['btc_start']}")
    if len(state["strategies"]) == 1:
        print("Stratégies bitcoin : démarrage à la clôture de la prochaine bougie 1 h.")
    print(f"{'stratégie':<48}{'valeur':>11}{'résultat':>10}{'ordres':>8}{'frais':>9}{'pire baisse':>13}  position")
    for r in summary_rows(state):
        print(f"{r['label']:<48}{r['value']:>9.2f} €{r['return']:>+9.2f}%{r['orders']:>8}"
              f"{r['fees']:>7.2f} €{r['drawdown']:>12.1f}%  {r['position']}")


def svg_chart(state, width=860, height=300):
    """Courbes de valeur (SVG en ligne, sans bibliothèque)."""
    series = {n: r["curve"] for n, r in state["strategies"].items() if len(r["curve"]) > 1}
    if not series:
        return "<p class='muted'>Pas encore assez de points pour tracer une courbe.</p>"
    ts = [t for c in series.values() for t, _ in c]
    vs = [v for c in series.values() for _, v in c] + [config.START_CAPITAL_EUR]
    t0, t1, v0, v1 = min(ts), max(ts), min(vs), max(vs)
    t1, v1 = max(t1, t0 + 1), max(v1, v0 + 1)
    pad = 40
    x = lambda t: pad + (t - t0) / (t1 - t0) * (width - 2 * pad)
    y = lambda v: height - pad - (v - v0) / (v1 - v0) * (height - 2 * pad)
    colors = ["#2563eb", "#16a34a", "#ea580c", "#9333ea", "#0891b2", "#64748b"]
    parts = [f"<line x1='{pad}' x2='{width - pad}' y1='{y(config.START_CAPITAL_EUR):.1f}' "
             f"y2='{y(config.START_CAPITAL_EUR):.1f}' class='base'/>",
             f"<text x='4' y='{y(v1) + 4:.0f}'>{v1:.0f} €</text>",
             f"<text x='4' y='{y(v0) + 4:.0f}'>{v0:.0f} €</text>"]
    legend = []
    for color, (name, curve) in zip(colors, series.items()):
        step = max(1, len(curve) // 600)
        pts = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in curve[::step] + [curve[-1]])
        width_px = 3 if name == MAIN else 1.5
        parts.append(f"<polyline fill='none' stroke='{color}' stroke-width='{width_px}' points='{pts}'/>")
        legend.append(f"<span><i style='background:{color}'></i>{html.escape(LABELS.get(name, name))}</span>")
    return (f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Valeur des portefeuilles'>"
            + "".join(parts) + "</svg><div class='legend'>" + "".join(legend) + "</div>")


def write_reports(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    compact = {k: v for k, v in state.items() if k != "strategies"}
    compact["strategies"] = summary_rows(state)
    (DATA_DIR / "etat.json").write_text(json.dumps(compact, indent=2, ensure_ascii=False))

    trades = sorted(((n, t) for n, r in state["strategies"].items() for t in r["trades"]),
                    key=lambda x: x[1]["ts"])
    with open(DATA_DIR / "ordres.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["date_utc", "strategie", "paire", "sens", "prix_eur", "quantite", "frais_eur"])
        for name, t in trades:
            w.writerow([iso(t["ts"]), name, t["pair"], "achat" if t["side"] == "buy" else "vente",
                        f"{t['price']:.4f}", f"{t['qty']:.8f}", f"{t['fee']:.4f}"])

    rows = "".join(
        f"<tr{' class=main' if r['name'] == MAIN else ''}><td>{html.escape(r['label'])}</td>"
        f"<td>{r['value']:.2f} €</td><td class='{'up' if r['return'] >= 0 else 'down'}'>{r['return']:+.2f} %</td>"
        f"<td>{r['orders']}</td><td>{r['fees']:.2f} €</td><td>{r['drawdown']:.1f} %</td>"
        f"<td class='l'>{html.escape(r['position'])}</td></tr>" for r in summary_rows(state))
    recent = "".join(
        f"<tr><td>{iso(t['ts'])}</td><td class='l'>{html.escape(LABELS.get(n, n))}</td><td>{t['pair']}</td>"
        f"<td>{'achat' if t['side'] == 'buy' else 'vente'}</td><td>{t['price']:.2f}</td>"
        f"<td>{t['fee']:.2f} €</td></tr>" for n, t in reversed(trades[-30:])) \
        or "<tr><td colspan=6 class='muted'>Aucun ordre pour l'instant.</td></tr>"
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300">
<title>Bot Kraken · simulation</title><style>
:root{{--bg:#f8fafc;--fg:#0f172a;--muted:#64748b;--card:#fff;--line:#e2e8f0;--up:#15803d;--down:#b91c1c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1120;--fg:#e2e8f0;--muted:#94a3b8;--card:#111827;--line:#1f2937;--up:#4ade80;--down:#f87171}}}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:960px;margin:auto}}h1{{font-size:22px;margin:0 0 4px}}.muted{{color:var(--muted)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}td,th{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}
td:first-child,th:first-child,td.l,th.l{{text-align:left}}td:last-child{{white-space:normal}}tr.main td{{font-weight:600}}.up{{color:var(--up)}}.down{{color:var(--down)}}
svg{{width:100%;height:auto}}svg text{{fill:var(--muted);font-size:11px}}svg .base{{stroke:var(--line);stroke-dasharray:4}}
.legend{{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:var(--muted)}}.legend i{{display:inline-block;width:12px;height:3px;margin-right:6px;vertical-align:middle}}
</style></head><body><main>
<h1>Bot Kraken · simulation sur 1 000 € fictifs</h1>
<p class="muted">Mis à jour {state['updated_at']} · BTC/EUR {state['btc_price']:.1f} · départ portefeuille {state['multi_start']},
bitcoin {state['btc_start']} · aucune somme réelle engagée. La page se recharge toute seule.</p>
<div class="card"><table><tr><th>Stratégie</th><th>Valeur</th><th>Résultat</th><th>Ordres</th><th>Frais</th><th>Pire baisse</th><th class='l'>Position</th></tr>{rows}</table></div>
<div class="card">{svg_chart(state)}</div>
<div class="card"><table><tr><th>Date</th><th class='l'>Stratégie</th><th>Paire</th><th>Sens</th><th>Prix €</th><th>Frais</th></tr>{recent}</table></div>
</main></body></html>"""
    (DATA_DIR / "rapport.html").write_text(page, encoding="utf-8")


# ---------- backtest rapide (données Kraken journalières) ----------

def quick_backtest(store):
    """Rejoue les stratégies journalières sur les ~720 derniers jours de Kraken
    (moins 200 jours de préchauffage pour la moyenne 200 jours)."""
    daily = store.candles(config.PAIR, 1440)
    closes = [c["close"] for c in daily]
    start = 200
    if len(daily) <= start + 30:
        raise SystemExit("Pas assez de bougies journalières : lance d'abord « python -m bot once ».")
    targets = {
        "trend_ensemble": trend_ensemble_daily(closes),
        "sma_cross_daily_20_50": sma_cross(closes, config.DAILY_SMA_FAST, config.DAILY_SMA_SLOW),
        "buy_and_hold": [True] * len(closes),
    }
    print(f"\nBacktest {iso(daily[start]['ts'])[:10]} -> {iso(daily[-1]['ts'] + DAY)[:10]}, "
          f"1 000 €, frais Kraken réels, décision à la clôture, exécution à l'ouverture du lendemain")
    print(f"{'stratégie':<48}{'final':>10}{'résultat':>10}{'ordres':>8}{'frais':>9}{'pire baisse':>13}")
    for name, target in targets.items():
        pf, curve = backtest.simulate(daily, target, start, TieredFee())
        s = backtest.summarize(pf, curve, config.START_CAPITAL_EUR)
        print(f"{LABELS[name]:<48}{s['final_eur']:>8.2f} €{s['return_pct']:>+9.1f}%{s['n_trades']:>8}"
              f"{s['fees_eur']:>7.2f} €{s['max_drawdown_pct']:>12.1f}%")
    print("Période courte : indicatif seulement. Résultats sur 10 ans : voir README.")


# ---------- boucle ----------

def setup_logging():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(DATA_DIR / "bot.log", encoding="utf-8"),
                                  logging.StreamHandler()])


def open_store():
    return Store(DATA_DIR / "bot.sqlite")


def run_forever(minutes):
    setup_logging()
    store = open_store()
    log.info(f"Bot démarré (simulation, aucune somme réelle). Passage toutes les {minutes} min. "
             f"Rapport : {DATA_DIR / 'rapport.html'}  ·  Ctrl+C pour arrêter.")
    while True:
        try:
            state = tick(store)
            main = state["strategies"][MAIN]["stats"]
            log.info(f"OK · portefeuille principal {main['final_eur']:.2f} € "
                     f"({main['return_pct']:+.2f} %) · BTC {state['btc_price']:.1f}")
            print_status(state)
        except Exception as exc:   # réseau coupé, API Kraken indisponible... on réessaie au prochain passage
            log.warning(f"Passage échoué, nouvel essai dans {minutes} min : {exc}")
        time.sleep(minutes * 60)
