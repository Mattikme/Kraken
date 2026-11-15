"""Backtest : rejoue les stratégies sur l'historique stocké dans Neon.

Règles (identiques pour toutes les stratégies, buy & hold compris) :
 - capital de départ 1 000 EUR, frais preneur Kraken réels, glissement 0,05 % ;
 - la décision est prise à la CLÔTURE d'une bougie et exécutée à l'OUVERTURE
   de la bougie suivante (on ne trade jamais à un prix déjà connu) ;
 - à la fin, le portefeuille est valorisé au dernier cours de clôture.
"""
import json
from datetime import datetime, timezone

from . import config, db
from .portfolio import FlatFee, Portfolio, TieredFee
from .strategy import STRATEGIES

HOUR = 3600


def max_drawdown_pct(values):
    """Pire baisse depuis un sommet, en % (nombre positif)."""
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        worst = max(worst, (peak - v) / peak)
    return worst * 100


def simulate(candles, target, start_index, fee_model, capital=config.START_CAPITAL_EUR):
    """Rejoue une stratégie à partir de `start_index`. Renvoie (portefeuille, courbe)."""
    pf = Portfolio(capital, fee_model)
    curve = []                                   # (ts, valeur) à chaque clôture
    for i in range(start_index, len(candles)):
        candle = candles[i]
        wanted = target[i - 1]                   # décision prise à la clôture précédente
        if wanted is True and pf.btc == 0:
            pf.buy(candle["ts"], candle["open"])
        elif wanted is False and pf.btc > 0:
            pf.sell(candle["ts"], candle["open"])
        curve.append((candle["ts"], pf.value(candle["close"])))
    return pf, curve


def summarize(pf, curve, capital):
    values = [v for _, v in curve]
    wins = sum(1 for g in pf.round_trips if g > 0)
    return {
        "final_eur": values[-1],
        "return_pct": (values[-1] / capital - 1) * 100,
        "n_trades": len(pf.trades),
        "n_round_trips": len(pf.round_trips),
        "win_rate_pct": (wins / len(pf.round_trips) * 100) if pf.round_trips else None,
        "fees_eur": sum(t["fee"] for t in pf.trades),
        "max_drawdown_pct": max_drawdown_pct(values),
    }


def run(candles, fee_factory, start_ts, capital=config.START_CAPITAL_EUR):
    """Lance toutes les stratégies. Renvoie {nom: {stats, trades, curve, params}}."""
    # Premier indice >= start_ts, en gardant au moins une bougie avant (pour la décision).
    start_index = max(1, next(i for i, c in enumerate(candles) if c["ts"] >= start_ts))
    out = {}
    for name, (fn, params) in STRATEGIES.items():
        pf, curve = simulate(candles, fn(candles), start_index, fee_factory(), capital)
        out[name] = {"stats": summarize(pf, curve, capital), "trades": pf.trades,
                     "curve": curve, "params": params}
    reference = out["buy_and_hold"]["stats"]["final_eur"]
    for name, res in out.items():
        res["stats"]["beats_buy_hold"] = (
            None if name == "buy_and_hold" else res["stats"]["final_eur"] > reference)
    return out


def count_gaps(candles):
    """Nombre d'heures manquantes dans la série (0 = historique complet)."""
    return sum((b["ts"] - a["ts"]) // HOUR - 1 for a, b in zip(candles, candles[1:]))


def save(results, fee_name, period_days, start_ts, end_ts, store_details):
    """Écrit les résultats dans Neon (remplace ceux du backtest précédent)."""
    now = datetime.now(timezone.utc).isoformat()
    statements = [("DELETE FROM backtest_results WHERE fee_model = $1 AND period_days = $2",
                   [fee_name, period_days])]
    for name, res in results.items():
        s = res["stats"]
        statements.append((
            """INSERT INTO backtest_results (strategy, fee_model, period_days, run_at, start_ts,
                 end_ts, start_eur, final_eur, return_pct, n_trades, n_round_trips, win_rate_pct,
                 fees_eur, max_drawdown_pct, beats_buy_hold, params)
               VALUES ($1,$2,$3,$4,to_timestamp($5),to_timestamp($6),$7,$8,$9,$10,$11,$12,$13,$14,
                       $15,$16::jsonb)""",
            [name, fee_name, period_days, now, start_ts, end_ts, config.START_CAPITAL_EUR,
             s["final_eur"], s["return_pct"], s["n_trades"], s["n_round_trips"], s["win_rate_pct"],
             s["fees_eur"], s["max_drawdown_pct"], s["beats_buy_hold"], json.dumps(res["params"])]))
    if store_details:   # détail (trades + courbe) uniquement pour le scénario principal
        statements.append(("DELETE FROM trades WHERE mode = 'backtest'", []))
        statements.append(("DELETE FROM equity WHERE mode = 'backtest'", []))
        for name, res in results.items():
            trades = [dict(t) for t in res["trades"]]
            daily = [{"ts": ts, "v": v} for ts, v in res["curve"] if ts % 86400 == 0]
            daily.append({"ts": res["curve"][-1][0], "v": res["curve"][-1][1]})
            statements.append((
                """INSERT INTO trades (strategy, ts, side, price, qty, fee, mode)
                   SELECT $1, to_timestamp(t.ts), t.side, t.price, t.qty, t.fee, 'backtest'
                   FROM jsonb_to_recordset($2::jsonb)
                        AS t(ts bigint, side text, price numeric, qty numeric, fee numeric)""",
                [name, json.dumps(trades)]))
            statements.append((
                """INSERT INTO equity (strategy, ts, value_eur, mode)
                   SELECT $1, to_timestamp(e.ts), e.v, 'backtest'
                   FROM jsonb_to_recordset($2::jsonb) AS e(ts bigint, v numeric)
                   ON CONFLICT DO NOTHING""",
                [name, json.dumps(daily)]))
    db.transaction(statements)


def report(title, results):
    print(f"\n=== {title} ===")
    print(f"{'stratégie':<23}{'final EUR':>11}{'rendement':>11}{'ordres':>8}"
          f"{'réussite':>10}{'frais EUR':>11}{'drawdown':>10}  bat B&H ?")
    for name, res in results.items():
        s = res["stats"]
        win = "—" if s["win_rate_pct"] is None else f"{s['win_rate_pct']:.1f} %"
        beats = {None: "—", True: "OUI", False: "NON"}[s["beats_buy_hold"]]
        print(f"{name:<23}{s['final_eur']:>11.2f}{s['return_pct']:>+10.1f}%{s['n_trades']:>8}"
              f"{win:>10}{s['fees_eur']:>11.2f}{s['max_drawdown_pct']:>9.1f}%  {beats}")


def yearly_report(results):
    """Rendement de chaque année civile, pour voir si le résultat tient dans la durée."""
    year_of = lambda ts: datetime.fromtimestamp(ts, timezone.utc).year
    print(f"\n{'année':<8}" + "".join(f"{name:>23}" for name in results))
    curves = {name: res["curve"] for name, res in results.items()}
    years = sorted({year_of(ts) for ts, _ in curves["buy_and_hold"]})
    for year in years:
        line = f"{year:<8}"
        for name, curve in curves.items():
            values = [v for ts, v in curve if year_of(ts) == year]
            before = [v for ts, v in curve if year_of(ts) < year]
            start = before[-1] if before else config.START_CAPITAL_EUR
            line += f"{(values[-1] / start - 1) * 100:>+22.1f}%"
        print(line)


def main():
    db.init_schema()
    _, first, last = db.candle_range(config.PAIR)
    if last is None:
        raise SystemExit("Aucune bougie dans Neon : lance d'abord bot.history.")
    end_ts = last // 86400 * 86400               # on s'arrête au dernier jour UTC complet
    iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
    fee_models = [("frais Kraken réels (paliers selon volume 30 j)", TieredFee),
                  ("pire cas, palier 1 permanent (0,80 %)",
                   lambda: FlatFee(config.TAKER_FEE_TIERS[0][1]))]
    verdicts = {}
    for period_days in (config.BACKTEST_DAYS, config.ROBUSTNESS_DAYS):
        start_ts = end_ts - period_days * 86400
        candles = db.load_candles(config.PAIR, start_ts - config.WARMUP_DAYS * 86400, end_ts)
        if not candles or candles[0]["ts"] > start_ts - (config.WARMUP_DAYS - 1) * 86400:
            raise SystemExit(f"Historique insuffisant pour {period_days} jours : lance bot.history.")
        print(f"\n######## {period_days} jours : {iso(start_ts)} -> {iso(end_ts)} UTC "
              f"({len(candles)} bougies, {count_gaps(candles)} heure(s) manquante(s)) ########")
        for index, (title, factory) in enumerate(fee_models):
            results = run(candles, factory, start_ts)
            report(title, results)
            is_main = index == 0 and period_days == config.BACKTEST_DAYS
            save(results, factory().name, period_days, start_ts, end_ts, store_details=is_main)
            if index == 0:
                verdicts[period_days] = [n for n, r in results.items() if r["stats"]["beats_buy_hold"]]
                if period_days == config.ROBUSTNESS_DAYS:
                    yearly_report(results)

    print()
    for period_days, winners in verdicts.items():
        print(f"VERDICT {period_days} jours (frais réels) : " + (
            f"{', '.join(winners)} bat le buy & hold après frais." if winners
            else "AUCUNE stratégie ne bat le buy & hold après frais."))


if __name__ == "__main__":
    main()
