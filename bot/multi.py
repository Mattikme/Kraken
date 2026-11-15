"""Recherche multi-actifs : au-delà du bitcoin, avec ce que Kraken permet de trader.

Kraken propose aussi des ETF tokenisés (SPYx = actions américaines S&P 500,
GLDx = or), avec des frais bien plus bas que les cryptos. On teste ici des
portefeuilles simples mêlant actions, or et bitcoin, vus par un investisseur en EUR.

Règles du jeu, comme pour bot/research.py :
 - liste et paramètres fixés et enregistrés sur GitHub AVANT le premier test ;
 - règles publiées et connues, aucun réglage après coup ;
 - tout est affiché, y compris ce qui déçoit.

Hypothèses (prudentes) :
 - actions et or : historique des ETF d'origine (table daily_prices), convertis
   en EUR ; frais = 0,08 % (preneur xStocks) + 0,20 % (conversion EUR/USD) ;
 - bitcoin : bougies Kraken, frais preneur réels selon le volume 30 jours ;
 - glissement 0,05 % sur chaque ordre ; les EUR non investis rapportent 0 % ;
 - décision avec les cours de clôture d'un jour, exécution à la clôture du lendemain.
Ce script lit Neon et affiche un rapport ; il n'écrit rien.
"""
import math
from datetime import date, timedelta

from . import config, db
from .portfolio import FlatFee, TieredFee

XSTOCK_FEE = 0.0008 + 0.0020      # preneur xStocks + conversion EUR/USD (kraken.com/pro/fees, 2026-11-15)
MIN_TRADE = 0.02                  # on ignore les ajustements de moins de 2 % du portefeuille
TREND_MONTHS = 10                 # règle de Faber (2007) : moyenne des 10 dernières fins de mois
VOL_MONTHS = 12                   # volatilité mesurée sur 12 rendements mensuels
EPOCH = date(1970, 1, 1)


def to_date(day_number):
    return EPOCH + timedelta(days=day_number)


# ---------- données ----------

def forward_fill(days, by_day):
    """Aligne une série sur tous les jours du calendrier ; un jour sans cotation
    (week-end, férié) reprend le dernier cours connu. None avant le premier cours."""
    out, last = [], None
    for day in days:
        last = by_day.get(day, last)
        out.append(last)
    return out


def load_prices(first_day, last_day):
    """Cours en EUR de chaque actif pour chaque jour de [first_day, last_day]."""
    days = list(range(first_day, last_day + 1))
    raw = {}
    for row in db.query("SELECT symbol, (day - DATE '1970-01-01') AS d, close::float8 AS close FROM daily_prices"):
        raw.setdefault(row["symbol"], {})[int(row["d"])] = float(row["close"])
    btc = dict(raw.get("BTCEUR", {}))                            # avant 2016 : archive Kraken journalière
    for row in db.query(
            """SELECT DISTINCT ON (ts::date) (ts::date - DATE '1970-01-01') AS d, close::float8 AS close
               FROM candles WHERE pair = $1 ORDER BY ts::date, ts DESC""", [config.PAIR]):
        btc[int(row["d"])] = float(row["close"])
    eurusd = forward_fill(days, raw["EURUSD"])
    prices = {"BTC": forward_fill(days, btc)}
    for name, symbol in (("ACTIONS", "SPY"), ("OR", "GLD")):
        usd = forward_fill(days, raw[symbol])
        prices[name] = [None if p is None or fx is None else p / fx for p, fx in zip(usd, eurusd)]
    return days, prices


# ---------- outils mensuels ----------

def month_ends(days):
    """Indices des derniers jours de chaque mois."""
    return [i for i in range(len(days) - 1) if to_date(days[i]).month != to_date(days[i + 1]).month]


def trend_is_up(monthly_closes):
    """Faber : en tendance haussière si le dernier cours de fin de mois dépasse
    la moyenne des 10 dernières fins de mois. None s'il manque de l'historique."""
    window = monthly_closes[-TREND_MONTHS:]
    if len(window) < TREND_MONTHS or any(p is None for p in window):
        return None
    return window[-1] > sum(window) / TREND_MONTHS


def monthly_vol(monthly_closes):
    """Écart-type des 12 derniers rendements mensuels. None s'il manque de l'historique."""
    window = monthly_closes[-(VOL_MONTHS + 1):]
    if len(window) < VOL_MONTHS + 1 or any(p is None for p in window):
        return None
    returns = [b / a - 1 for a, b in zip(window, window[1:])]
    mean = sum(returns) / len(returns)
    return math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))


# ---------- portefeuilles candidats ----------
# Chaque fonction renvoie, pour chaque jour, soit None (ne rien faire), soit les
# parts visées {actif: part} ; le reste est en EUR. Décision appliquée le lendemain.

def static(weights, yearly=False):
    """Répartition fixe, rééquilibrée chaque mois (ou chaque année)."""
    def targets(days, prices):
        out = [None] * len(days)
        out[0] = dict(weights)                                   # achat initial
        for i in month_ends(days):
            if not yearly or to_date(days[i]).month == 12:
                out[i] = dict(weights)
        return out
    return targets


def trend(assets, by_risk=False):
    """Portefeuille de tendance (Faber) : chaque actif a sa part ; il n'est détenu
    que s'il est en tendance haussière, sinon sa part reste en EUR. Revu chaque
    fin de mois. Avec by_risk, les parts sont inversement proportionnelles à la
    volatilité de chaque actif (un actif nerveux comme le bitcoin pèse moins)."""
    def targets(days, prices):
        out = [None] * len(days)
        ends = month_ends(days)
        for n, i in enumerate(ends):
            closes = {a: [prices[a][j] for j in ends[:n + 1]] for a in assets}
            up = {a: trend_is_up(closes[a]) for a in assets}
            if any(v is None for v in up.values()):
                continue
            if by_risk:
                vols = {a: monthly_vol(closes[a]) for a in assets}
                if any(v is None or v == 0 for v in vols.values()):
                    continue
                total = sum(1 / v for v in vols.values())
                share = {a: (1 / vols[a]) / total for a in assets}
            else:
                share = {a: 1 / len(assets) for a in assets}
            out[i] = {a: (share[a] if up[a] else 0.0) for a in assets}
        return out
    return targets


ALL = ("ACTIONS", "OR", "BTC")
CANDIDATES = {
    "actions_seules": static({"ACTIONS": 1.0}),                               # référence
    "btc_seul": static({"BTC": 1.0}),                                         # référence
    "mix_60_30_10": static({"ACTIONS": 0.6, "OR": 0.3, "BTC": 0.1}, yearly=True),
    "mix_tiers": static({a: 1 / 3 for a in ALL}),
    "tendance_tiers": trend(ALL),
    "tendance_risque": trend(ALL, by_risk=True),
}
# Contrôle long (2006-2026, crise de 2008 incluse) : sans bitcoin, qui n'existait pas.
CANDIDATES_LONG = {
    "actions_seules": static({"ACTIONS": 1.0}),
    "mix_actions_or": static({"ACTIONS": 0.5, "OR": 0.5}),
    "tendance_actions_or": trend(("ACTIONS", "OR")),
    "tendance_risque_ao": trend(("ACTIONS", "OR"), by_risk=True),
}


# ---------- simulation ----------

def simulate(days, prices, targets, start_index, capital=config.START_CAPITAL_EUR):
    """Rejoue un portefeuille. Renvoie (courbe [(jour, valeur)], nombre d'ordres, frais)."""
    fees = {a: TieredFee() if a == "BTC" else FlatFee(XSTOCK_FEE) for a in prices}
    cash, qty = capital, {a: 0.0 for a in prices}
    orders, paid, curve = 0, 0.0, [(days[start_index], capital)]
    pending = dict(targets[start_index]) if targets[start_index] else None
    for i in range(start_index + 1, len(days)):
        ts = days[i] * 86400
        price = {a: prices[a][i] for a in prices}
        if pending is not None:
            value = cash + sum(qty[a] * price[a] for a in qty if price[a])
            deltas = {a: w * value - qty[a] * price[a] for a, w in pending.items() if price[a]}
            deltas = {a: d for a, d in deltas.items() if abs(d) >= MIN_TRADE * value}
            for a, d in deltas.items():                          # ventes d'abord
                if d < 0:
                    rate = fees[a].rate(ts) + config.SLIPPAGE
                    sold = min(qty[a], -d / price[a])
                    cash += sold * price[a] * (1 - rate)
                    qty[a] -= sold
                    paid += sold * price[a] * rate
                    fees[a].record(ts, sold * price[a])
                    orders += 1
            buys = {a: d for a, d in deltas.items() if d > 0}
            scale = min(1.0, cash / sum(buys.values())) if buys else 0.0
            for a, d in buys.items():                            # puis achats, dans la limite du cash
                rate = fees[a].rate(ts) + config.SLIPPAGE
                spent = d * scale
                qty[a] += spent * (1 - rate) / price[a]
                cash -= spent
                paid += spent * rate
                fees[a].record(ts, spent)
                orders += 1
            cash = max(0.0, cash)
        curve.append((days[i], cash + sum(qty[a] * price[a] for a in qty if price[a])))
        pending = dict(targets[i]) if targets[i] else None
    return curve, orders, paid


# ---------- mesures ----------

def measure(curve, orders, paid):
    values = [v for _, v in curve]
    years = (curve[-1][0] - curve[0][0]) / 365.25
    returns = [b / a - 1 for a, b in zip(values, values[1:])]
    mean = sum(returns) / len(returns)
    spread = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = max(worst, (peak - v) / peak)
    by_year, previous = {}, values[0]
    for day, v in curve:
        by_year[to_date(day).year] = v
    yearly = {}
    for year in sorted(by_year):
        yearly[year] = (by_year[year] / previous - 1) * 100
        previous = by_year[year]
    two_years_ago = next(v for d, v in curve if d >= curve[-1][0] - 730)
    middle = next(v for d, v in curve if d >= (curve[0][0] + curve[-1][0]) // 2)
    return {
        "final": values[-1], "cagr": ((values[-1] / values[0]) ** (1 / years) - 1) * 100,
        "drawdown": worst * 100, "sharpe": mean / spread * math.sqrt(365) if spread else 0.0,
        "orders": orders, "fees": paid, "yearly": yearly,
        "positive_years": sum(1 for r in yearly.values() if r > 0), "worst_year": min(yearly.values()),
        "last_2y": (values[-1] / two_years_ago - 1) * 100,
        "halves": ((middle / values[0] - 1) * 100, (values[-1] / middle - 1) * 100),
    }


def report(title, results):
    print(f"\n=== {title} ===")
    print(f"{'portefeuille':<21}{'final EUR':>10}{'par an':>8}{'pire baisse':>12}{'Sharpe':>7}"
          f"{'années +':>10}{'pire année':>11}{'2 dern. ans':>12}{'1re moitié':>11}{'2e moitié':>10}"
          f"{'ordres':>7}{'frais':>7}")
    for name, m in results.items():
        print(f"{name:<21}{m['final']:>10.0f}{m['cagr']:>+7.1f}%{m['drawdown']:>11.1f}%{m['sharpe']:>7.2f}"
              f"{str(m['positive_years']) + '/' + str(len(m['yearly'])):>10}{m['worst_year']:>+10.1f}%"
              f"{m['last_2y']:>+11.1f}%{m['halves'][0]:>+10.0f}%{m['halves'][1]:>+9.0f}%"
              f"{m['orders']:>7}{m['fees']:>7.0f}")
    years = sorted(next(iter(results.values()))["yearly"])
    print(f"\n{'année':<7}" + "".join(f"{name:>21}" for name in results))
    for year in years:
        print(f"{year:<7}" + "".join(f"{m['yearly'][year]:>+20.1f}%" for m in results.values()))


def run(candidates, days, prices, start_day):
    start_index = days.index(start_day)
    results = {}
    for name, fn in candidates.items():
        targets = fn(days, prices)
        # Avant le départ, seule compte la dernière décision : elle est exécutée au premier jour.
        last = next((targets[j] for j in range(start_index, -1, -1) if targets[j]), None)
        targets = [None] * start_index + [last] + targets[start_index + 1:]
        results[name] = measure(*simulate(days, prices, targets, start_index))
    return results


def main():
    _, _, last = db.candle_range(config.PAIR)
    end_day = last // 86400 - 1                                   # dernier jour complet
    first_day = (date(2004, 11, 18) - EPOCH).days                 # début de l'historique de l'or
    days, prices = load_prices(first_day, end_day)
    iso = lambda d: to_date(d).isoformat()

    start = end_day - config.ROBUSTNESS_DAYS
    report(f"10 ans : {iso(start)} -> {iso(end_day)}, actions + or + bitcoin, en EUR, frais inclus",
           run(CANDIDATES, days, prices, start))

    long_start = (date(2006, 1, 1) - EPOCH).days
    long_prices = {a: p for a, p in prices.items() if a != "BTC"}
    report(f"Contrôle long : {iso(long_start)} -> {iso(end_day)}, sans bitcoin (crise de 2008 incluse)",
           run(CANDIDATES_LONG, days, long_prices, long_start))


if __name__ == "__main__":
    main()
