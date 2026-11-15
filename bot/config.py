"""Paramètres du bot. Tout ce qui est chiffré ici a une source vérifiable."""
from datetime import datetime, timezone

# Paire tradée (nom « altname » de l'API Kraken) et taille des bougies.
PAIR = "XBTEUR"
INTERVAL_MIN = 60

# Portefeuille fictif.
START_CAPITAL_EUR = 1000.0

# Glissement de prix appliqué à chaque ordre (0,05 %) : on achète un peu plus
# cher et on vend un peu moins cher que le prix théorique.
SLIPPAGE = 0.0005

# Frais PRENEUR au comptant de Kraken Pro, selon le volume échangé sur 30 jours.
# Source : https://www.kraken.com/pro/fees (vérifié le 2026-11-15).
# Format : (volume 30 jours minimum en USD, taux preneur).
# Simplifications prudentes (elles surestiment légèrement les frais) :
#  - le volume en EUR est compté comme du USD (1 EUR vaut plus de 1 USD) ;
#  - la remise de 0,02 % sur certaines paires n'est pas appliquée.
TAKER_FEE_TIERS = [
    (0, 0.0080),
    (2_500, 0.0060),
    (10_000, 0.0038),
    (25_000, 0.0035),
    (50_000, 0.0030),
    (100_000, 0.0025),
    (250_000, 0.0022),
    (500_000, 0.0020),
]
FEE_WINDOW_SECONDS = 30 * 24 * 3600

# Stratégies : paramètres fixés À L'AVANCE, jamais ajustés après avoir vu les
# résultats (sinon on fabrique un backtest flatteur : surajustement).
SMA_FAST = 20            # stratégie A : moyenne mobile courte (heures)
SMA_SLOW = 50            # stratégie A : moyenne mobile longue (heures)
MOMENTUM_HOURS = 24      # stratégie B : fenêtre du rendement
MOMENTUM_ENTER = 0.02    # stratégie B : on achète si rendement 24 h > +2 %
MOMENTUM_EXIT = 0.0      # stratégie B : on vend si rendement 24 h < 0 %

# Stratégie C : la règle A (moyennes 20/50) appliquée à des bougies d'UN JOUR
# au lieu d'une heure, pour passer très peu d'ordres. Mêmes valeurs que A :
# aucun nouveau paramètre n'a été choisi en regardant les résultats.
DAILY_SMA_FAST = 20      # jours
DAILY_SMA_SLOW = 50      # jours

# Stratégie D : ensemble de tendances (retenue après la phase de recherche).
# Part de BTC = proportion de ces moyennes journalières que le cours dépasse.
ENSEMBLE_SMA_DAYS = (20, 50, 100, 200)

# Portefeuille multi-actifs (stratégie E, retenue après la recherche multi-actifs) :
# actions américaines et or via les ETF tokenisés de Kraken, bitcoin, le reste en EUR.
# Nom affiché -> (paire Kraken, classe d'actif pour l'API). Bougies d'un jour.
DAILY_PAIRS = {
    "SPYxUSD": "tokenized_asset",    # S&P 500
    "GLDxUSD": "tokenized_asset",    # or
    "EURUSD": None,                  # pour convertir les cours en EUR
}
# Simulation du portefeuille : départ à la clôture de ce jour (UTC), 1 000 EUR fictifs.
MULTI_START = (2026, 11, 14)

# Backtest : période jugée (2 ans) et période de contrôle plus longue (10 ans),
# qui couvre plusieurs marchés haussiers et baissiers.
BACKTEST_DAYS = 730
ROBUSTNESS_DAYS = 3650
WARMUP_DAYS = 220        # historique nécessaire avant le départ (moyenne 200 jours)
HISTORY_DAYS = ROBUSTNESS_DAYS + WARMUP_DAYS + 10

# Stratégies à exposition partielle : on ne rééquilibre que si la part de BTC
# s'écarte de plus de 10 points de la cible (évite de payer des frais pour rien).
REBALANCE_BAND = 0.10

# Simulation en direct (argent fictif) : première bougie prise en compte.
# Date fixée à l'avance ; ne pas la modifier une fois la simulation lancée.
PAPER_START_TS = int(datetime(2026, 11, 15, 3, 0, tzinfo=timezone.utc).timestamp())
