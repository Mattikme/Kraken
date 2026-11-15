"""Stratégies : à partir des cours de clôture, dire si on veut être en BTC ou en EUR.

Chaque stratégie renvoie une liste `target` de même longueur que `closes` :
  True  -> on veut détenir du BTC
  False -> on veut être en EUR
  None  -> pas encore assez d'historique pour décider
La valeur à l'indice i n'utilise QUE les clôtures 0..i (jamais le futur).
"""
from . import config


def sma_cross(closes, fast=config.SMA_FAST, slow=config.SMA_SLOW):
    """Stratégie A : en BTC quand la moyenne mobile courte est au-dessus de la longue."""
    target = [None] * len(closes)
    sum_fast = sum_slow = 0.0
    for i, price in enumerate(closes):
        sum_fast += price
        sum_slow += price
        if i >= fast:
            sum_fast -= closes[i - fast]
        if i >= slow:
            sum_slow -= closes[i - slow]
        if i >= slow - 1:
            target[i] = (sum_fast / fast) > (sum_slow / slow)
    return target


def momentum(closes, hours=config.MOMENTUM_HOURS,
             enter=config.MOMENTUM_ENTER, exit_=config.MOMENTUM_EXIT):
    """Stratégie B : on achète si le rendement sur 24 h dépasse +2 %,
    on vend s'il repasse sous 0 %, sinon on ne change rien."""
    target = [None] * len(closes)
    in_btc = False
    for i in range(hours, len(closes)):
        ret = closes[i] / closes[i - hours] - 1
        if ret > enter:
            in_btc = True
        elif ret < exit_:
            in_btc = False
        target[i] = in_btc
    return target


def daily_sma_cross(candles, fast=config.DAILY_SMA_FAST, slow=config.DAILY_SMA_SLOW):
    """Stratégie C : croisement de moyennes mobiles sur des bougies d'un jour (UTC).

    Les bougies 1 h sont regroupées par jour. La décision d'un jour n'est
    utilisée qu'à partir du jour SUIVANT (quand sa clôture est définitive) :
    l'ordre part donc peu après minuit UTC, au plus une fois par jour.
    """
    day_closes, day_of, current = [], [], None
    for c in candles:
        day = c["ts"] // 86400
        if day != current:
            day_closes.append(c["close"])
            current = day
        else:
            day_closes[-1] = c["close"]          # dernière clôture connue du jour
        day_of.append(len(day_closes) - 1)
    daily = sma_cross(day_closes, fast, slow)
    return [daily[d - 1] if d > 0 else None for d in day_of]


def buy_and_hold(closes):
    """Référence : toujours en BTC."""
    return [True] * len(closes)


def signal(previous_target, target):
    """Traduit un changement de cible en signal ACHETER / VENDRE / RIEN."""
    if target is None or bool(previous_target) == target:
        return "HOLD"
    return "BUY" if target else "SELL"


def _closes(candles):
    return [c["close"] for c in candles]


# Nom en base -> (fonction recevant les bougies 1 h, paramètres affichés)
STRATEGIES = {
    "sma_cross_20_50": (lambda candles: sma_cross(_closes(candles)),
                        {"fast": config.SMA_FAST, "slow": config.SMA_SLOW, "candle": "1h"}),
    "momentum_24h": (lambda candles: momentum(_closes(candles)),
                     {"hours": config.MOMENTUM_HOURS, "enter": config.MOMENTUM_ENTER,
                      "exit": config.MOMENTUM_EXIT, "candle": "1h"}),
    "sma_cross_daily_20_50": (daily_sma_cross,
                              {"fast": config.DAILY_SMA_FAST, "slow": config.DAILY_SMA_SLOW,
                               "candle": "1d"}),
    "buy_and_hold": (lambda candles: buy_and_hold(_closes(candles)), {}),
}
