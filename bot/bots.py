"""Les bots du tournoi. Chacun part de 1 000 € fictifs et trade le même univers.

Liste et paramètres fixés AVANT le premier test (2026-11-16), tirés de règles
publiées et connues ; aucun réglage après avoir vu les résultats.

Chaque bot est une fonction (jours, cours) -> liste de décisions : pour chaque
jour, None (ne rien changer) ou {actif: part du portefeuille}, le reste en EUR.
La décision du jour i n'utilise que les cours des jours 0..i.

Le « sélectionneur » est un méta-bot : chaque fin de mois il classe les autres
bots sur leurs 6 derniers mois et copie les positions des 3 meilleurs. C'est
la sélection naturelle du tournoi, mesurée avec la même honnêteté (il ne voit
que le passé et paie ses propres frais).
"""
import math

from . import arena, universe
from .multi import month_ends, monthly_vol, trend, trend_is_up
from .strategy import trend_ensemble_daily

CRYPTO = universe.in_category("crypto")
DEVISES = universe.in_category("devise")


# ---------- outils ----------

def available(prices, i):
    return [a for a in prices if prices[a][i] is not None]


def slots(assets):
    """Part maximale de chaque actif : un tiers par catégorie présente,
    partagé à égalité entre ses actifs (évite que les 6 devises pèsent la moitié)."""
    by_cat = {}
    for a in assets:
        by_cat.setdefault(universe.category(a), []).append(a)
    return {a: 1 / len(by_cat) / len(by_cat[universe.category(a)]) for a in assets}


def monthly_closes(prices, asset, ends, k):
    return [prices[asset][j] for j in ends[:k + 1]]


def change(out, i, target, last):
    """N'émet une décision que si elle diffère de la précédente."""
    if target != last:
        out[i] = target
    return target


# ---------- bots ----------

def tout_un_peu(days, prices):
    """Référence : un tiers crypto, un tiers ETF, un tiers devises, rééquilibré chaque mois."""
    out, ends, last = [None] * len(days), set(month_ends(days)), None
    for i in range(len(days)):
        avail = available(prices, i)
        if avail and (i in ends or set(avail) != last):
            out[i], last = slots(avail), set(avail)
    return out


def tendance(days, prices):
    """Faber (2007) : chaque actif n'est détenu que si sa clôture de fin de mois
    dépasse la moyenne de ses 10 dernières fins de mois. Revu chaque mois."""
    out, ends = [None] * len(days), month_ends(days)
    for k, i in enumerate(ends):
        s = slots(available(prices, i))
        out[i] = {a: w for a, w in s.items() if trend_is_up(monthly_closes(prices, a, ends, k))}
    return out


def tendance_risque(days, prices):
    """Comme « tendance », mais la part de chaque actif est inversement
    proportionnelle à sa volatilité (12 mois) : un actif nerveux pèse moins."""
    out, ends = [None] * len(days), month_ends(days)
    for k, i in enumerate(ends):
        vols = {a: monthly_vol(monthly_closes(prices, a, ends, k)) for a in available(prices, i)}
        vols = {a: v for a, v in vols.items() if v}
        total = sum(1 / v for v in vols.values())
        out[i] = {a: (1 / v) / total for a, v in vols.items()
                  if trend_is_up(monthly_closes(prices, a, ends, k))}
    return out


def momentum_top3(days, prices):
    """Momentum relatif (Jegadeesh-Titman, Antonacci) : chaque mois, les 3 actifs
    qui ont le plus monté sur 6 mois, à condition d'avoir monté ; sinon EUR."""
    out, ends = [None] * len(days), month_ends(days)
    for k, i in enumerate(ends):
        perf = {}
        for a in available(prices, i):
            closes = monthly_closes(prices, a, ends, k)[-7:]
            if len(closes) == 7 and None not in closes:
                perf[a] = closes[-1] / closes[0] - 1
        best = [a for a in sorted(perf, key=perf.get, reverse=True)[:3] if perf[a] > 0]
        out[i] = {a: 1 / 3 for a in best}
    return out


def momentum_crypto(days, prices):
    """Chaque semaine, la crypto qui a le plus monté sur 4 semaines, si elle a
    monté et si son cours dépasse sa moyenne 50 jours ; sinon EUR."""
    out, last = [None] * len(days), None
    for i in range(50, len(days)):
        if days[i] % 7:
            continue
        perf = {}
        for a in CRYPTO:
            window = prices[a][i - 49:i + 1]
            if None in window or prices[a][i - 28] is None:
                continue
            if window[-1] > sum(window) / 50:
                perf[a] = window[-1] / prices[a][i - 28] - 1
        best = max(perf, key=perf.get, default=None)
        last = change(out, i, {best: 1.0} if best and perf[best] > 0 else {}, last)
    return out


def devises(days, prices):
    """Momentum des devises : chaque mois, les 2 devises qui se sont le plus
    appréciées face à l'euro sur 3 mois, si elles se sont appréciées ; sinon EUR."""
    out, ends = [None] * len(days), month_ends(days)
    for k, i in enumerate(ends):
        perf = {}
        for a in DEVISES:
            closes = monthly_closes(prices, a, ends, k)[-4:]
            if len(closes) == 4 and None not in closes:
                perf[a] = closes[-1] / closes[0] - 1
        out[i] = {a: 0.5 for a in sorted(perf, key=perf.get, reverse=True)[:2] if perf[a] > 0}
    return out


def rsi(closes, n=2):
    """RSI de Wilder sur la liste de clôtures ; None s'il manque de l'historique."""
    if len(closes) <= n:
        return None
    changes = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(c, 0) for c in changes[:n]) / n
    loss = sum(max(-c, 0) for c in changes[:n]) / n
    for c in changes[n:]:
        gain = (gain * (n - 1) + max(c, 0)) / n
        loss = (loss * (n - 1) + max(-c, 0)) / n
    return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)


def rsi2_actions(days, prices, assets=("SP500", "NASDAQ")):
    """Retour à la moyenne (Connors) sur les indices actions : achat quand le RSI
    2 jours passe sous 10 dans une tendance haussière (cours > moyenne 200 séances),
    revente dès que le cours repasse au-dessus de sa moyenne 5 séances."""
    out, last = [None] * len(days), None
    sessions = {a: [] for a in assets}             # clôtures des jours où le cours a bougé
    holding = set()
    for i in range(len(days)):
        for a in assets:
            p = prices[a][i]
            if p is None or (sessions[a] and p == sessions[a][-1]):
                continue
            s = sessions[a]
            s.append(p)
            if len(s) < 200:
                continue
            if a in holding and p > sum(s[-5:]) / 5:
                holding.discard(a)
            elif a not in holding and p > sum(s[-200:]) / 200:
                r = rsi(s[-60:])
                if r is not None and r < 10:
                    holding.add(a)
        last = change(out, i, {a: 1 / len(assets) for a in sorted(holding)}, last)
    return out


def cassure(days, prices, enter=55, leave=20):
    """Cassure (règle des « tortues ») : un actif est acheté quand il clôture au-dessus
    de son plus haut des 55 derniers jours, revendu sous son plus bas des 20 derniers."""
    out, last, holding = [None] * len(days), None, set()
    for i in range(enter, len(days)):
        for a in prices:
            window = prices[a][i - enter:i]
            p = prices[a][i]
            if p is None or None in window:
                holding.discard(a)
                continue
            if a in holding and p < min(window[-leave:]):
                holding.discard(a)
            elif a not in holding and p > max(window):
                holding.add(a)
        s = slots(available(prices, i))
        last = change(out, i, {a: s[a] for a in sorted(holding)}, last)
    return out


def ensemble_btc(days, prices):
    """Ensemble de tendances sur le bitcoin (meilleur bot BTC de la recherche) :
    part de BTC = proportion des moyennes 20, 50, 100 et 200 jours que le cours dépasse."""
    out, last = [None] * len(days), None
    first = next((i for i, p in enumerate(prices["BTC"]) if p is not None), len(days))
    weights = trend_ensemble_daily(prices["BTC"][first:])
    for i, w in enumerate(weights, start=first):
        if w is not None:
            last = change(out, i, {"BTC": w} if w else {}, last)
    return out


def actions_or_btc(days, prices):
    """Portefeuille retenu par la recherche multi-actifs (bot/multi.py) :
    S&P 500, or et bitcoin, tendance pondérée par le risque."""
    return trend(("SP500", "OR", "BTC"), by_risk=True)(days, prices)


# nom -> (fonction, libellé, description courte)
BOTS = {
    "tout_un_peu": (tout_un_peu, "Tout un peu (référence)", "1/3 crypto, 1/3 ETF, 1/3 devises, chaque mois"),
    "tendance": (tendance, "Tendance", "garde ce qui monte (moyenne 10 mois), chaque mois"),
    "tendance_risque": (tendance_risque, "Tendance × risque", "tendance, parts selon la volatilité"),
    "momentum_top3": (momentum_top3, "Momentum top 3", "les 3 meilleurs sur 6 mois, chaque mois"),
    "momentum_crypto": (momentum_crypto, "Momentum crypto", "la meilleure crypto sur 4 semaines"),
    "devises": (devises, "Devises", "les 2 devises les plus fortes sur 3 mois"),
    "rsi2_actions": (rsi2_actions, "Rebond actions (RSI 2)", "achète les creux du S&P 500 et du Nasdaq"),
    "cassure": (cassure, "Cassure 55/20 jours", "achète les nouveaux plus hauts, tous actifs"),
    "ensemble_btc": (ensemble_btc, "Bitcoin · ensemble de tendances", "BTC selon 4 moyennes mobiles"),
    "actions_or_btc": (actions_or_btc, "Actions + or + BTC", "portefeuille retenu par la recherche"),
}
META = "selectionneur"
LABELS = {name: label for name, (_, label, _) in BOTS.items()}
LABELS[META] = "Sélectionneur (copie les 3 meilleurs)"
DESCRIPTIONS = {name: desc for name, (_, _, desc) in BOTS.items()}
DESCRIPTIONS[META] = "chaque mois, copie les 3 meilleurs bots des 6 derniers mois"
BENCHMARK = "tout_un_peu"


def selectionneur(days, results, lookback=182, top=3):
    """Décisions du méta-bot à partir des résultats (passés) des autres bots."""
    out, ends, chosen = [None] * len(days), set(month_ends(days)), []
    for i in range(len(days)):
        if i in ends and i >= lookback:
            scores = []
            for name, r in results.items():
                window = r["values"][i - lookback:i + 1]
                if window[-1] <= window[0]:
                    continue                                  # n'a pas gagné d'argent : écarté
                rets = [b / a - 1 for a, b in zip(window, window[1:]) if a]
                mean = sum(rets) / len(rets)
                sd = math.sqrt(sum((x - mean) ** 2 for x in rets) / (len(rets) - 1))
                scores.append((mean / sd if sd else 0.0, name))
            chosen = [name for _, name in sorted(scores, reverse=True)[:top]]
            if not chosen:
                out[i] = {}
        if chosen:
            mix = {}
            for name in chosen:
                for a, w in results[name]["weights"][i].items():
                    mix[a] = mix.get(a, 0.0) + w / len(chosen)
            out[i] = mix
    return out


def run_all(days, prices):
    """Rejoue tous les bots puis le sélectionneur. Renvoie {nom: résultat de arena.simulate}."""
    results = {name: arena.simulate(days, prices, fn(days, prices)) for name, (fn, _, _) in BOTS.items()}
    results[META] = arena.simulate(days, prices, selectionneur(days, results))
    return results
