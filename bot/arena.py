"""Moteur du tournoi : rejoue un bot jour par jour avec les frais réels de Kraken.

Un bot donne, certains jours, la répartition qu'il veut : {actif: part}, le
reste en EUR. Règles identiques pour tous :
 - décision avec les clôtures du jour J, exécution à la clôture du jour J+1
   (on ne trade jamais à un prix déjà connu au moment de décider) ;
 - au comptant, sans levier ni vente à découvert ;
 - ajustements de moins de 2 % de la valeur du portefeuille ignorés ;
 - ventes d'abord, puis achats dans la limite des EUR disponibles.
"""
import math

from . import config, universe
from .portfolio import FlatFee, TieredFee

MIN_TRADE = 0.02


def fee_models():
    """Frais d'un bot : un seul compteur de volume pour toutes ses cryptos."""
    crypto = TieredFee()
    out = {}
    for asset in universe.ASSETS:
        cat = universe.category(asset)
        out[asset] = crypto if cat == "crypto" else FlatFee(
            universe.XSTOCK_FEE if cat == "etf" else universe.FX_FEE)
    return out


def simulate(days, prices, targets, capital=config.START_CAPITAL_EUR):
    """Renvoie {values, weights, orders, fees} alignés sur `days`.

    values[i]  : valeur du portefeuille à la clôture du jour i ;
    weights[i] : parts détenues à la clôture du jour i ({actif: part}) ;
    orders     : {i, asset, side, price, qty, fee} ; i = jour d'exécution."""
    fees = fee_models()
    cash, qty = capital, {a: 0.0 for a in prices}
    values, weights, orders, paid = [], [], [], 0.0
    pending = None
    for i in range(len(days)):
        price = {a: prices[a][i] for a in prices}
        value = cash + sum(q * price[a] for a, q in qty.items() if q and price[a])
        if pending is not None:
            ts = days[i] * 86400
            deltas = {}
            for a in prices:
                if price[a] is None:
                    continue
                d = pending.get(a, 0.0) * value - qty[a] * price[a]
                if abs(d) >= MIN_TRADE * value or (pending.get(a, 0.0) == 0 and qty[a] > 0):
                    deltas[a] = d
            for a, d in deltas.items():                                 # ventes d'abord
                if d < 0 and qty[a] > 0:
                    sold = min(qty[a], -d / price[a])
                    rate = fees[a].rate(ts) + config.SLIPPAGE
                    notional = sold * price[a]
                    cash += notional * (1 - rate)
                    qty[a] -= sold
                    paid += notional * rate
                    fees[a].record(ts, notional)
                    orders.append({"i": i, "asset": a, "side": "sell", "price": price[a],
                                   "qty": sold, "fee": notional * rate})
            buys = {a: d for a, d in deltas.items() if d > 0}
            scale = min(1.0, cash / sum(buys.values())) if buys else 0.0
            for a, d in buys.items():                                    # puis achats
                spent = d * scale
                if spent <= 0:
                    continue
                rate = fees[a].rate(ts) + config.SLIPPAGE
                got = spent * (1 - rate) / price[a]
                qty[a] += got
                cash -= spent
                paid += spent * rate
                fees[a].record(ts, spent)
                orders.append({"i": i, "asset": a, "side": "buy", "price": price[a],
                               "qty": got, "fee": spent * rate})
            cash = max(0.0, cash)
            value = cash + sum(q * price[a] for a, q in qty.items() if q and price[a])
        values.append(value)
        weights.append({a: q * price[a] / value for a, q in qty.items()
                        if q > 0 and price[a] and value > 0})
        pending = targets[i]
    return {"values": values, "weights": weights, "orders": orders, "fees": paid}


def measure(values, days, orders=(), first=0):
    """Mesures sur values[first:], ramenées à 1 000 € au départ de la fenêtre."""
    window = values[first:]
    scale = config.START_CAPITAL_EUR / window[0] if window and window[0] else 1.0
    curve = [v * scale for v in window]
    n_days = len(curve) - 1
    returns = [b / a - 1 for a, b in zip(curve, curve[1:]) if a]
    mean = sum(returns) / len(returns) if returns else 0.0
    spread = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)) if len(returns) > 1 else 0.0
    peak, worst = curve[0] if curve else 0, 0.0
    for v in curve:
        peak = max(peak, v)
        worst = max(worst, (peak - v) / peak if peak else 0.0)
    final = curve[-1] if curve else config.START_CAPITAL_EUR
    years = n_days / 365.25
    mine = [o for o in orders if o["i"] >= first]
    return {
        "days": n_days,
        "final": final,
        "return_pct": (final / config.START_CAPITAL_EUR - 1) * 100,
        "cagr_pct": ((final / config.START_CAPITAL_EUR) ** (1 / years) - 1) * 100 if years >= 1 else None,
        "drawdown_pct": worst * 100,
        "sharpe": mean / spread * math.sqrt(365) if spread else 0.0,
        "orders": len(mine),
        "fees": sum(o["fee"] for o in mine) * scale,
        "curve": curve,
    }


def yearly(values, days, epoch_year):
    """Rendement de chaque année civile (%)."""
    out, previous, by_year = {}, values[0], {}
    for d, v in zip(days, values):
        by_year[epoch_year(d)] = v
    for year in sorted(by_year):
        out[year] = (by_year[year] / previous - 1) * 100 if previous else 0.0
        previous = by_year[year]
    return out
