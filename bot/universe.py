"""Univers du tournoi : ce que les bots ont le droit d'acheter, avec 1 000 € de départ.

Règle de choix (fixée avant tout test) : actifs tradables au comptant sur
Kraken depuis des EUR et LIQUIDES, c'est-à-dire échangés presque tous les jours
pour plus de 50 000 $ par jour (relevé le 2026-11-16 sur 90 jours). Un actif
peu échangé affiche un cours qui n'est pas un prix auquel on peut vraiment
acheter : il fausserait la simulation. C'est pourquoi seuls 3 des 177 ETF et
actions tokenisés de Kraken sont retenus (VGKx, IWMx, IEMGx... : souvent 0 échange par jour).

Frais preneur Kraken Pro (https://www.kraken.com/pro/fees, relevés le 2026-11-16) :
  crypto        0,80 % puis dégressif selon le volume 30 jours (bot.portfolio.TieredFee)
  devises       0,20 % (paires FX, palier jusqu'à 50 000 $ de volume)
  ETF tokenisés 0,08 % + 0,20 % de conversion EUR -> USD
Glissement de prix de 0,05 % en plus sur chaque ordre.
"""

FX_FEE = 0.0020
XSTOCK_FEE = 0.0008 + FX_FEE

CATEGORIES = {"crypto": "Crypto", "etf": "ETF", "devise": "Devises"}

# nom -> (catégorie, paire Kraken, classe d'actif API, type de cotation, symbole Yahoo, libellé)
#   cotation "EUR" : la paire donne directement le prix en EUR
#   cotation "USD" : prix en USD, converti avec EURUSD
#   cotation "INV" : paire EURxxx ; le prix de la devise en EUR est 1 / cours
ASSETS = {
    "BTC":    ("crypto", "XBTEUR",  None, "EUR", "BTC-EUR", "Bitcoin"),
    "ETH":    ("crypto", "ETHEUR",  None, "EUR", "ETH-EUR", "Ether"),
    "SOL":    ("crypto", "SOLEUR",  None, "EUR", "SOL-EUR", "Solana"),
    "SP500":  ("etf", "SPYxUSD", "tokenized_asset", "USD", "SPY", "S&P 500 (SPYx)"),
    "NASDAQ": ("etf", "QQQxUSD", "tokenized_asset", "USD", "QQQ", "Nasdaq 100 (QQQx)"),
    "OR":     ("etf", "GLDxUSD", "tokenized_asset", "USD", "GLD", "Or (GLDx)"),
    "USD":    ("devise", "EURUSD", None, "INV", "EURUSD=X", "Dollar US"),
    "GBP":    ("devise", "EURGBP", None, "INV", "EURGBP=X", "Livre sterling"),
    "JPY":    ("devise", "EURJPY", None, "INV", "EURJPY=X", "Yen"),
    "CHF":    ("devise", "EURCHF", None, "INV", "EURCHF=X", "Franc suisse"),
    "AUD":    ("devise", "EURAUD", None, "INV", "EURAUD=X", "Dollar australien"),
    "CAD":    ("devise", "EURCAD", None, "INV", "EURCAD=X", "Dollar canadien"),
}


def category(asset):
    return ASSETS[asset][0]


def in_category(cat):
    return [a for a in ASSETS if ASSETS[a][0] == cat]


def kraken_pairs():
    """Paires à collecter : (paire, classe d'actif API)."""
    return [(pair, cls) for _, pair, cls, _, _, _ in ASSETS.values()]


def to_eur(by_pair, days, forward_fill):
    """Cours en EUR de chaque actif, jour par jour (None tant que l'actif n'existe pas).

    by_pair : {paire Kraken: {jour: clôture}}. Un jour sans cotation reprend le
    dernier cours connu (week-end, jour férié)."""
    fx = forward_fill(days, by_pair["EURUSD"])
    prices = {}
    for asset, (_, pair, _, quote, _, _) in ASSETS.items():
        raw = forward_fill(days, by_pair.get(pair, {}))
        if quote == "EUR":
            prices[asset] = raw
        elif quote == "USD":
            prices[asset] = [None if p is None or f is None else p / f for p, f in zip(raw, fx)]
        else:
            prices[asset] = [None if p is None else 1 / p for p in raw]
    return prices
