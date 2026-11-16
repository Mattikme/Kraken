"""Tournoi de bots en local : crypto, ETF et devises, 1 000 € fictifs chacun.

Aucune clé API, aucune base externe : les cours Kraken sont gardés dans un
fichier SQLite (dossier `donnees/`). À chaque passage, tous les bots sont
rejoués depuis le début des données avec les frais réels (bot/arena.py) :
relancer ne crée aucun doublon et une coupure se rattrape toute seule.

Trois fenêtres de mesure, pour chaque bot :
 - « Depuis le lancement » : la vraie simulation, à partir du premier passage
   (départ figé), ramenée à 1 000 € ;
 - « Backtest Kraken » : les ~2 ans de cours Kraken disponibles avant le lancement ;
 - « Historique » : 2016 -> aujourd'hui sur les cours longs (Yahoo Finance),
   calculé par `python -m bot historique`.
Un bot devient « candidat au réel » s'il remplit les critères de PROMOTION.
"""
import csv
import html
import json
import logging
import math
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import arena, bots, kraken_api, multi, proxies, universe
from .local_store import Store

DAY = 86400
EPOCH = date(1970, 1, 1)
DATA_DIR = Path(os.environ.get("KRAKEN_BOT_DIR", Path(__file__).resolve().parent.parent / "donnees"))
HISTORY_FROM = date(2016, 1, 1)          # début de la mesure longue
HISTORY_WARMUP = date(2013, 1, 1)        # données chargées avant, pour les moyennes

# Critères pour qu'un bot passe en argent réel (fixés à l'avance).
PROMOTION = {"min_days": 90, "max_drawdown_live": 15.0, "max_drawdown_history": 40.0}

log = logging.getLogger("bot")


def to_date(day):
    return date.fromordinal(EPOCH.toordinal() + day)


def day_of(d):
    return (d - EPOCH).days


# ---------- données ----------

def collect(store, fetch=kraken_api.fetch_ohlc, pause=0.4):
    """Bougies d'un jour terminées de chaque paire de l'univers."""
    for pair, asset_class in universe.kraken_pairs():
        store.upsert(pair, 1440, fetch(pair, 1440, asset_class=asset_class))
        time.sleep(pause)                 # reste sous la limite de débit de l'API publique


def series(store, prefix=""):
    """{paire: {jour: clôture}} pour toutes les paires de l'univers."""
    return {pair: {c["ts"] // DAY: c["close"] for c in store.candles(prefix + pair, 1440)}
            for pair, _ in universe.kraken_pairs()}


def kraken_prices(store):
    """(jours, cours en EUR) des données Kraken : du premier jour disponible au
    dernier jour complet commun à toutes les paires."""
    by_pair = series(store)
    if any(not s for s in by_pair.values()):
        raise RuntimeError("Données Kraken incomplètes : relance un passage.")
    first = min(min(s) for s in by_pair.values())
    last = min(max(s) for s in by_pair.values())
    days = list(range(first, last + 1))
    return days, universe.to_eur(by_pair, days, multi.forward_fill)


# ---------- tournoi ----------

def readiness(live, bench, history):
    """(prêt ?, raisons) selon les critères de PROMOTION."""
    reasons = []
    if live["days"] < PROMOTION["min_days"]:
        reasons.append(f"{live['days']}/{PROMOTION['min_days']} jours")
    if live["return_pct"] <= 0:
        reasons.append("pas de gain")
    elif bench and live["return_pct"] <= bench["return_pct"]:
        reasons.append("ne bat pas la référence")
    if live["drawdown_pct"] > PROMOTION["max_drawdown_live"]:
        reasons.append(f"pire baisse > {PROMOTION['max_drawdown_live']:.0f} %")
    if history is None:
        reasons.append("historique non calculé")
    elif history["drawdown_pct"] > PROMOTION["max_drawdown_history"]:
        reasons.append(f"pire baisse historique {history['drawdown_pct']:.0f} %")
    return not reasons, reasons


def load_history():
    path = DATA_DIR / "historique.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def tick(store, fetch=kraken_api.fetch_ohlc, pause=0.4):
    """Un passage : collecte, tournoi, rapports. Renvoie l'état."""
    collect(store, fetch, pause)
    days, prices = kraken_prices(store)
    if store.get("start_day") is None:
        store.set("start_day", days[-1])
        store.set("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    start = days.index(int(store.get("start_day")))
    results = bots.run_all(days, prices)
    history = load_history()

    board = {}
    for name, r in results.items():
        board[name] = {
            "live": arena.measure(r["values"], days, r["orders"], start),
            "backtest": arena.measure(r["values"][:start + 1], days, r["orders"]),
            "history": (history or {}).get("bots", {}).get(name),
            "position": r["weights"][-1],
            "orders": [dict(o, day=days[o["i"]]) for o in r["orders"] if o["i"] > start],
        }
    bench = board[bots.BENCHMARK]["live"]
    for name, b in board.items():
        b["ready"], b["reasons"] = readiness(b["live"], bench if name != bots.BENCHMARK else None, b["history"])
    state = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "start": to_date(days[start]).isoformat(),
        "data_from": to_date(days[0]).isoformat(),
        "last_close": to_date(days[-1]).isoformat(),
        "prices": {a: prices[a][-1] for a in prices},
        "history_period": history and history["period"],
        "board": board,
    }
    write_reports(state)
    return state


# ---------- historique long (Yahoo Finance, recherche uniquement) ----------

def download_history(store, fetch=proxies.fetch, pause=0.5):
    """Cours journaliers longs des actifs d'origine (ETF, crypto en EUR, taux de change)."""
    for _, pair, _, _, symbol, _ in universe.ASSETS.values():
        rows = fetch(symbol)
        store.upsert("yahoo:" + pair, 1440, [
            {"ts": day_of(date.fromisoformat(d)) * DAY, "open": c, "high": c, "low": c, "close": c, "volume": 0}
            for d, c in rows])
        time.sleep(pause)


def run_history(store):
    """Tournoi sur 2016 -> aujourd'hui. Écrit donnees/historique.json et renvoie le résultat."""
    by_pair = series(store, "yahoo:")
    last = min(max(s) for s in by_pair.values() if s)
    days = list(range(day_of(HISTORY_WARMUP), last + 1))
    prices = universe.to_eur(by_pair, days, multi.forward_fill)
    results = bots.run_all(days, prices)
    start = days.index(day_of(HISTORY_FROM))
    out = {"period": f"{HISTORY_FROM.isoformat()} → {to_date(days[-1]).isoformat()}",
           "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "bots": {}}
    for name, r in results.items():
        m = arena.measure(r["values"], days, r["orders"], start)
        m["yearly"] = {str(y): v for y, v in
                       arena.yearly(r["values"][start:], days[start:], lambda d: to_date(d).year).items()}
        m["curve"] = m["curve"][::7]                   # un point par semaine suffit pour le graphique
        out["bots"][name] = m
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "historique.json").write_text(json.dumps(out, ensure_ascii=False))
    return out


def print_history(hist):
    rows = sorted(hist["bots"].items(), key=lambda x: -x[1]["final"])
    print(f"\nTournoi historique {hist['period']}, 1 000 € chacun, frais Kraken inclus")
    print(f"{'bot':<40}{'final':>10}{'par an':>9}{'pire baisse':>13}{'Sharpe':>8}{'ordres':>8}{'frais':>9}")
    for name, m in rows:
        print(f"{bots.LABELS[name]:<40}{m['final']:>8.0f} €{m['cagr_pct']:>+8.1f}%{m['drawdown_pct']:>12.1f}%"
              f"{m['sharpe']:>8.2f}{m['orders']:>8}{m['fees']:>7.0f} €")
    names = [n for n, _ in rows]
    print(f"\n{'année':<7}" + "".join(f"{n[:12]:>13}" for n in names))
    for year in sorted(rows[0][1]["yearly"]):
        print(f"{year:<7}" + "".join(f"{hist['bots'][n]['yearly'][year]:>+12.0f}%" for n in names))


# ---------- affichage ----------

def position_label(weights, limit=None):
    """Ex. « SP500 61 % · BTC 14 % · EUR 25 % » ; au-delà de `limit` actifs, le reste est regroupé."""
    held = [(a, w) for a, w in sorted(weights.items(), key=lambda x: -x[1]) if round(w * 100) > 0]
    shown, rest = (held, []) if limit is None else (held[:limit], held[limit:])
    parts = [f"{a} {round(w * 100)} %" for a, w in shown]
    if rest:
        parts.append(f"{len(rest)} autres {round(sum(w for _, w in rest) * 100)} %")
    cash = round((1 - sum(weights.values())) * 100)
    if cash > 0:
        parts.append(f"EUR {cash} %")
    return " · ".join(parts) or "EUR 100 %"


def ranking(state):
    """Classement : depuis le lancement s'il a commencé, sinon sur le backtest Kraken."""
    key = "live" if any(b["live"]["days"] for b in state["board"].values()) else "backtest"
    return key, sorted(state["board"], key=lambda n: -state["board"][n][key]["final"])


def print_status(state):
    key, order = ranking(state)
    print(f"\nMis à jour {state['updated_at']} · dernière clôture {state['last_close']} · "
          f"lancement {state['start']}")
    print(f"Classement {'depuis le lancement' if key == 'live' else 'du backtest Kraken (simulation pas encore commencée)'}")
    print(f"{'#':<3}{'bot':<40}{'valeur':>10}{'résultat':>10}{'pire':>7}{'ordres':>7}  statut · position")
    for rank, name in enumerate(order, 1):
        b = state["board"][name]
        m = b["live" if key == "live" else "backtest"]
        status = "CANDIDAT AU RÉEL" if b["ready"] else "en test"
        print(f"{rank:<3}{bots.LABELS[name]:<40}{m['final']:>8.2f} €{m['return_pct']:>+9.2f}%"
              f"{m['drawdown_pct']:>6.1f}%{m['orders']:>7}  {status} · {position_label(b['position'], 4)}")


def svg_chart(curves, width=860, height=300, highlight=()):
    """Courbes de valeur (SVG en ligne) ; curves = {nom: [valeurs]} sur une même échelle de temps."""
    curves = {n: c for n, c in curves.items() if len(c) > 1}
    if not curves:
        return "<p class='muted'>Pas encore assez de points : la courbe apparaît après la première clôture.</p>"
    longest = max(len(c) for c in curves.values())
    values = [v for c in curves.values() for v in c] + [1000.0]
    lo, hi = min(values), max(values)
    log_scale = hi / max(lo, 1e-9) > 20
    f = (lambda v: math.log10(max(v, 1e-9))) if log_scale else (lambda v: v)
    flo, fhi = f(lo), max(f(hi), f(lo) + 1e-9)
    pad = 44
    x = lambda k: pad + k / max(1, longest - 1) * (width - 2 * pad)
    y = lambda v: height - pad - (f(v) - flo) / (fhi - flo) * (height - 2 * pad)
    palette = ["#2563eb", "#16a34a", "#ea580c", "#9333ea", "#db2777", "#0891b2"]
    parts = [f"<line x1='{pad}' x2='{width - pad}' y1='{y(1000):.1f}' y2='{y(1000):.1f}' class='base'/>",
             f"<text x='2' y='{y(hi) + 4:.0f}'>{hi:,.0f} €</text>".replace(",", " "),
             f"<text x='2' y='{y(lo) + 4:.0f}'>{lo:,.0f} €</text>".replace(",", " "),
             f"<text x='2' y='{y(1000) - 4:.0f}'>1 000 €</text>"]
    legend, colors = [], iter(palette)
    for name, c in sorted(curves.items(), key=lambda kv: kv[0] not in highlight):
        color = next(colors, "#94a3b8") if name in highlight else "#94a3b8"
        offset = longest - len(c)
        step = max(1, len(c) // 500)
        pts = " ".join(f"{x(offset + k):.1f},{y(v):.1f}" for k, v in list(enumerate(c))[::step] + [(len(c) - 1, c[-1])])
        width_px = 2.5 if name in highlight else 1
        parts.append(f"<polyline fill='none' stroke='{color}' stroke-width='{width_px}' points='{pts}'/>")
        if name in highlight:
            legend.append(f"<span><i style='background:{color}'></i>{html.escape(bots.LABELS[name])}</span>")
    note = " · échelle logarithmique" if log_scale else ""
    return (f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Valeur des bots'>" + "".join(parts)
            + f"</svg><div class='legend'>{''.join(legend)}<span>gris : autres bots{note}</span></div>")


def fmt_pct(v, digits=1):
    if v is None:
        return "—"
    v = 0.0 if abs(v) < 0.5 * 10 ** -digits else v           # pas de « -0,00 % »
    return f"<span class='{'up' if v >= 0 else 'down'}'>{v:+.{digits}f} %</span>"


def write_reports(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    board = state["board"]
    key, order = ranking(state)
    compact = {k: v for k, v in state.items() if k != "board"}
    compact["classement"] = [{
        "bot": n, "libelle": bots.LABELS[n],
        "depuis_lancement": {k: board[n]["live"][k] for k in ("final", "return_pct", "drawdown_pct", "orders")},
        "backtest_kraken": {k: board[n]["backtest"][k] for k in ("final", "return_pct", "drawdown_pct", "orders")},
        "position": position_label(board[n]["position"], 4),
        "candidat_reel": board[n]["ready"], "raisons": board[n]["reasons"]} for n in order]
    (DATA_DIR / "etat.json").write_text(json.dumps(compact, indent=2, ensure_ascii=False))

    trades = sorted(((n, o) for n in board for o in board[n]["orders"]), key=lambda x: x[1]["day"])
    with open(DATA_DIR / "ordres.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["date", "bot", "actif", "paire_kraken", "sens", "prix_eur", "quantite", "frais_eur"])
        for name, o in trades:
            w.writerow([to_date(o["day"]).isoformat(), name, o["asset"], universe.ASSETS[o["asset"]][1],
                        "achat" if o["side"] == "buy" else "vente", f"{o['price']:.6f}", f"{o['qty']:.8f}",
                        f"{o['fee']:.4f}"])

    rows = []
    for rank, n in enumerate(order, 1):
        b, h = board[n], board[n]["history"]
        status = ("<b class='up'>candidat au réel</b>" if b["ready"]
                  else "<span class='muted'>" + html.escape(", ".join(b["reasons"])) + "</span>")
        rows.append(
            f"<tr{' class=meta' if n == bots.META else ''}><td>{rank}</td><td class='l'><b>{html.escape(bots.LABELS[n])}</b>"
            f"<br><small class='muted'>{html.escape(bots.DESCRIPTIONS[n])}</small></td>"
            f"<td>{b['live']['final']:.2f} €</td><td>{fmt_pct(b['live']['return_pct'], 2)}</td>"
            f"<td>{b['live']['drawdown_pct']:.1f} %</td><td>{b['live']['orders']}</td>"
            f"<td>{fmt_pct(b['backtest']['return_pct'])}</td><td>{b['backtest']['drawdown_pct']:.0f} %</td>"
            f"<td>{fmt_pct(h and h['cagr_pct'])}</td><td>{'—' if not h else format(h['drawdown_pct'], '.0f') + ' %'}</td>"
            f"<td class='l pos'><small>{html.escape(position_label(b['position'], 4))}</small></td><td class='l pos'><small>{status}</small></td></tr>")
    top = set(order[:5]) | {bots.BENCHMARK}
    live_chart = svg_chart({n: board[n]["live"]["curve"] for n in board}, highlight=top)
    backtest_chart = svg_chart({n: board[n]["backtest"]["curve"] for n in board},
                               highlight=set(sorted(board, key=lambda n: -board[n]["backtest"]["final"])[:5]) | {bots.BENCHMARK})
    hist = load_history()
    hist_block = ("<p class='muted'>Lance <code>python -m bot historique</code> pour calculer le tournoi sur 10 ans.</p>"
                  if not hist else
                  svg_chart({n: m["curve"] for n, m in hist["bots"].items()},
                            highlight=set(sorted(hist["bots"], key=lambda n: -hist["bots"][n]["final"])[:5]) | {bots.BENCHMARK}))
    recent = "".join(
        f"<tr><td>{to_date(o['day']).isoformat()}</td><td class='l'>{html.escape(bots.LABELS[n])}</td><td>{o['asset']}</td>"
        f"<td>{'achat' if o['side'] == 'buy' else 'vente'}</td><td>{o['price'] * o['qty']:.2f} €</td>"
        f"<td>{o['fee']:.2f} €</td></tr>" for n, o in reversed(trades[-40:])) \
        or "<tr><td colspan=6 class='l muted'>Aucun ordre depuis le lancement pour l'instant.</td></tr>"
    prices = " · ".join(f"{a} {v:,.4g}".replace(",", " ") for a, v in state["prices"].items() if v)
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="300">
<title>Tournoi de bots</title><style>
:root{{--bg:#f8fafc;--fg:#0f172a;--muted:#64748b;--card:#fff;--line:#e2e8f0;--up:#15803d;--down:#b91c1c;--meta:#eff6ff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1120;--fg:#e2e8f0;--muted:#94a3b8;--card:#111827;--line:#1f2937;--up:#4ade80;--down:#f87171;--meta:#172554}}}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}}
main{{max-width:1200px;margin:auto}}h1{{font-size:22px;margin:0 0 4px}}h2{{font-size:16px;margin:0 0 8px}}.muted{{color:var(--muted)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0;overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}td,th{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;vertical-align:top}}
th{{font-size:13px;color:var(--muted);font-weight:600}}.l{{text-align:left}}td.l small{{white-space:normal}}tr.meta td{{background:var(--meta)}}td.pos{{min-width:190px}}
.up{{color:var(--up)}}.down{{color:var(--down)}}svg{{width:100%;height:auto}}svg text{{fill:var(--muted);font-size:11px}}svg .base{{stroke:var(--line);stroke-dasharray:4}}
.legend{{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;color:var(--muted)}}.legend i{{display:inline-block;width:12px;height:3px;margin-right:6px;vertical-align:middle}}
</style></head><body><main>
<h1>Tournoi de bots · 1 000 € fictifs chacun</h1>
<p class="muted">Mis à jour {state['updated_at']} · dernière clôture {state['last_close']} · lancement {state['start']} ·
crypto, ETF tokenisés et devises de Kraken, frais réels · aucune somme réelle engagée · la page se recharge seule.</p>
<div class="card"><table>
<tr><th></th><th class="l">Bot</th><th colspan=4>Depuis le lancement</th><th colspan=2>Backtest Kraken</th><th colspan=2>Historique {html.escape(state['history_period'] or '')}</th><th></th><th></th></tr>
<tr><th>#</th><th></th><th>Valeur</th><th>Résultat</th><th>Pire baisse</th><th>Ordres</th><th>Résultat</th><th>Pire baisse</th><th>Par an</th><th>Pire baisse</th><th class="l">Position</th><th class="l">Passage au réel</th></tr>
{''.join(rows)}</table>
<p class="muted"><small>Passage au réel : au moins {PROMOTION['min_days']} jours de simulation, un gain supérieur à la référence « Tout un peu »,
une pire baisse sous {PROMOTION['max_drawdown_live']:.0f} % depuis le lancement et sous {PROMOTION['max_drawdown_history']:.0f} % sur l'historique.
Backtest Kraken : cours Kraken du {state['data_from']} au lancement (ETF tokenisés seulement depuis 2025).</small></p></div>
<div class="card"><h2>Depuis le lancement</h2>{live_chart}</div>
<div class="card"><h2>Backtest Kraken (avant le lancement)</h2>{backtest_chart}</div>
<div class="card"><h2>Historique long {html.escape(state['history_period'] or '')}</h2>{hist_block}</div>
<div class="card"><h2>Derniers ordres simulés</h2><table><tr><th>Date</th><th class="l">Bot</th><th>Actif</th><th>Sens</th><th>Montant</th><th>Frais</th></tr>{recent}</table></div>
<p class="muted"><small>Derniers cours en EUR : {html.escape(prices)}</small></p>
</main></body></html>"""
    (DATA_DIR / "rapport.html").write_text(page, encoding="utf-8")


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
    log.info(f"Tournoi démarré (simulation, aucune somme réelle). Passage toutes les {minutes:g} min. "
             f"Rapport : {DATA_DIR / 'rapport.html'}  ·  Ctrl+C pour arrêter.")
    if load_history() is None:
        try:
            log.info("Calcul de l'historique long (une seule fois)...")
            download_history(store)
            run_history(store)
        except Exception as exc:
            log.warning(f"Historique long indisponible pour l'instant : {exc}")
    while True:
        try:
            state = tick(store)
            key, order = ranking(state)
            leader = state["board"][order[0]][key]
            log.info(f"OK · en tête : {bots.LABELS[order[0]]} {leader['final']:.2f} € ({leader['return_pct']:+.2f} %)")
            print_status(state)
        except Exception as exc:   # réseau coupé, API indisponible... nouvel essai au prochain passage
            log.warning(f"Passage échoué, nouvel essai dans {minutes:g} min : {exc}")
        time.sleep(minutes * 60)
