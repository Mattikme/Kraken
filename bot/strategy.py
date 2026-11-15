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


def buy_and_hold(closes):
    """Référence : toujours en BTC."""
    return [True] * len(closes)


def signal(previous_target, target):
    """Traduit un changement de cible en signal ACHETER / VENDRE / RIEN."""
    if target is None or bool(previous_target) == target:
        return "HOLD"
    return "BUY" if target else "SELL"


# Nom en base -> (fonction, paramètres affichés)
STRATEGIES = {
    "sma_cross_20_50": (sma_cross, {"fast": config.SMA_FAST, "slow": config.SMA_SLOW}),
    "momentum_24h": (momentum, {"hours": config.MOMENTUM_HOURS,
                                "enter": config.MOMENTUM_ENTER, "exit": config.MOMENTUM_EXIT}),
    "buy_and_hold": (buy_and_hold, {}),
}
