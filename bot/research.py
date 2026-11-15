"""Recherche : d'autres stratégies, testées honnêtement sur 10 ans.

Règles du jeu (pour ne pas se raconter d'histoires) :
 - chaque stratégie vient d'une idée publiée, avec les paramètres d'usage ;
   RIEN n'est ajusté après avoir vu les résultats ;
 - cette liste a été écrite et enregistrée sur GitHub AVANT le premier test ;
 - tout est testé avec les frais preneur Kraken réels et le glissement ;
 - toutes les stratégies testées sont affichées, pas seulement les meilleures ;
 - une stratégie ne « tient » que si elle marche dans les deux moitiés des 10 ans.

Au comptant, sans levier : chaque stratégie détient entre 0 % et 100 % de BTC.
Ce script lit Neon et affiche un rapport ; il n'écrit rien.
"""
import math
from datetime import datetime, timezone

from . import backtest, config, db
from .portfolio import TieredFee
from .strategy import (buy_and_hold, daily_closes, daily_sma_cross, sma, to_hourly,
                       trend_ensemble_daily)

DAY = 86400
SUNDAY = 6


def weekday(day_number):
    """0 = lundi ... 6 = dimanche (le jour 0, 1er janvier 1970, était un jeudi)."""
    return (day_number + 3) % 7


def realized_vol(closes, n=30):
    """Volatilité annualisée sur n jours (écart-type des rendements journaliers)."""
    returns = [0.0] + [math.log(b / a) for a, b in zip(closes, closes[1:])]
    out = [None] * len(closes)
    for i in range(n, len(closes)):
        window = returns[i - n + 1:i + 1]
        mean = sum(window) / n
        out[i] = math.sqrt(sum((r - mean) ** 2 for r in window) / (n - 1) * 365)
    return out


# ---------- les candidates (décisions journalières, sur les clôtures UTC) ----------

def trend_sma200(days, closes):
    """Filtre de tendance classique : en BTC si le cours est au-dessus de sa
    moyenne 200 jours, sinon en EUR. (Faber 2007, règle « 10 mois ».)"""
    average = sma(closes, 200)
    return [None if m is None else c > m for c, m in zip(closes, average)]


def tsmom_4w(days, closes):
    """Momentum sur 4 semaines, décidé une fois par semaine (dimanche soir) :
    en BTC si le cours a monté sur 28 jours. (Moskowitz, Ooi, Pedersen 2012 ;
    horizon court d'après Liu et Tsyvinski 2021.)"""
    out, current = [], None
    for i, day in enumerate(days):
        if i >= 28 and weekday(day) == SUNDAY:
            current = closes[i] > closes[i - 28]
        out.append(current)
    return out


def trend_ensemble(days, closes):
    """Ensemble de tendances : part de BTC = proportion des moyennes 20, 50, 100
    et 200 jours que le cours dépasse (0, 25, 50, 75 ou 100 %). Évite de parier
    sur une seule durée. (Detzel et al. 2021 testent ces durées sur le bitcoin.)"""
    return trend_ensemble_daily(closes)


def fixed_mix_50(days, closes):
    """Moitié BTC, moitié EUR, rééquilibré quand l'écart dépasse 10 points
    (le « démon de Shannon »). Pas de prévision : uniquement du contrôle du risque."""
    return [0.5] * len(closes)


def vol_target(days, closes, target=0.50):
    """Volatilité cible : moins de BTC quand le marché s'agite. Part de BTC =
    50 % / volatilité des 30 derniers jours, plafonnée à 100 %.
    (Moreira et Muir 2017, sans levier.)"""
    return [None if v is None else min(1.0, target / v) for v in realized_vol(closes)]


def trend_vol(days, closes):
    """Ensemble de tendances × volatilité cible : la combinaison que la
    littérature et les praticiens donnent comme la plus robuste."""
    trend, vol = trend_ensemble(days, closes), vol_target(days, closes)
    return [None if t is None or v is None else t * v for t, v in zip(trend, vol)]


def daily(fn):
    """Transforme une règle journalière en cible pour les bougies 1 h."""
    def target(candles):
        days, closes, day_of = daily_closes(candles)
        return to_hourly(fn(days, closes), day_of)
    return target


CANDIDATES = {
    "buy_and_hold": lambda candles: buy_and_hold([c["close"] for c in candles]),
    "sma_cross_daily_20_50": daily_sma_cross,          # déjà testée, pour comparaison
    "trend_sma200": daily(trend_sma200),
    "tsmom_4w": daily(tsmom_4w),
    "trend_ensemble": daily(trend_ensemble),
    "fixed_mix_50": daily(fixed_mix_50),
    "vol_target": daily(vol_target),
    "trend_vol": daily(trend_vol),
}


# ---------- mesures ----------

def sharpe(curve):
    """Rendement moyen / risque, annualisé, à partir des valeurs de minuit UTC."""
    values = [v for ts, v in curve if ts % DAY == 0]
    returns = [b / a - 1 for a, b in zip(values, values[1:])]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    spread = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))
    return None if spread == 0 else mean / spread * math.sqrt(365)


def evaluate(candles, start_ts):
    """Rejoue toutes les candidates depuis `start_ts` avec 1 000 EUR chacune."""
    start_index = max(1, next(i for i, c in enumerate(candles) if c["ts"] >= start_ts))
    out = {}
    for name, fn in CANDIDATES.items():
        pf, curve = backtest.simulate(candles, fn(candles), start_index, TieredFee())
        stats = backtest.summarize(pf, curve, config.START_CAPITAL_EUR)
        years = (curve[-1][0] - curve[0][0]) / (365.25 * DAY)
        stats["cagr_pct"] = ((stats["final_eur"] / config.START_CAPITAL_EUR) ** (1 / years) - 1) * 100
        stats["sharpe"] = sharpe(curve)
        out[name] = {"stats": stats, "curve": curve}
    return out


def value_at(curve, ts):
    """Valeur du portefeuille à l'instant `ts` (dernier point connu)."""
    return next(v for t, v in reversed(curve) if t <= ts)


def report(title, results):
    reference = results["buy_and_hold"]["stats"]
    print(f"\n=== {title} ===")
    print(f"{'stratégie':<23}{'final EUR':>11}{'par an':>9}{'pire baisse':>13}{'Sharpe':>8}"
          f"{'ordres':>8}{'frais EUR':>11}  plus d'argent ?  moins de baisse ?")
    for name, res in results.items():
        s = res["stats"]
        richer = "—" if name == "buy_and_hold" else ("OUI" if s["final_eur"] > reference["final_eur"] else "non")
        calmer = "—" if name == "buy_and_hold" else (
            "OUI" if s["max_drawdown_pct"] < reference["max_drawdown_pct"] else "non")
        ratio = "—" if s["sharpe"] is None else f"{s['sharpe']:.2f}"
        print(f"{name:<23}{s['final_eur']:>11.0f}{s['cagr_pct']:>+8.1f}%{s['max_drawdown_pct']:>12.1f}%"
              f"{ratio:>8}{s['n_trades']:>8}{s['fees_eur']:>11.0f}  {richer:^15}  {calmer:^16}")


def halves_report(results, start_ts, end_ts):
    """Multiplication du capital dans chaque moitié de la période."""
    middle = start_ts + (end_ts - start_ts) // 2 // DAY * DAY
    iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")
    print(f"\n=== Les deux moitiés : {iso(start_ts)} -> {iso(middle)} puis {iso(middle)} -> {iso(end_ts)} ===")
    print(f"{'stratégie':<23}{'1re moitié':>12}{'2e moitié':>12}  bat le buy & hold dans les deux ?")
    rows = {}
    for name, res in results.items():
        mid = value_at(res["curve"], middle)
        rows[name] = (mid / config.START_CAPITAL_EUR, res["curve"][-1][1] / mid)
    for name, (first, second) in rows.items():
        both = "—" if name == "buy_and_hold" else (
            "OUI" if first > rows["buy_and_hold"][0] and second > rows["buy_and_hold"][1] else "non")
        print(f"{name:<23}{'x' + format(first, '.2f'):>12}{'x' + format(second, '.2f'):>12}  {both}")


def main():
    _, _, last = db.candle_range(config.PAIR)
    if last is None:
        raise SystemExit("Aucune bougie dans Neon : lance d'abord bot.history.")
    end_ts = last // DAY * DAY
    iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    for period_days in (config.ROBUSTNESS_DAYS, config.BACKTEST_DAYS):
        start_ts = end_ts - period_days * DAY
        warmup_start = start_ts - config.WARMUP_DAYS * DAY
        candles = db.load_candles(config.PAIR, warmup_start, end_ts)
        if not candles or candles[0]["ts"] > warmup_start + DAY:
            raise SystemExit("Historique insuffisant : lance d'abord bot.history.")
        results = evaluate(candles, start_ts)
        report(f"{period_days} jours : {iso(start_ts)} -> {iso(end_ts)}, frais Kraken réels", results)
        if period_days == config.ROBUSTNESS_DAYS:
            halves_report(results, start_ts, end_ts)
            backtest.yearly_report(results)


if __name__ == "__main__":
    main()
