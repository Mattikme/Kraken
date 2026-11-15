"""Portefeuille fictif : exécute des ordres avec frais Kraken et glissement de prix.

Utilisé à l'identique par le backtest et (plus tard) par la simulation en direct.
Au comptant uniquement : on ne peut vendre que ce qu'on possède (pas de levier).
"""
from collections import deque

from . import config


class TieredFee:
    """Frais preneur réels de Kraken : le taux dépend du volume des 30 derniers jours."""
    name = "kraken_tiers"

    def __init__(self, tiers=config.TAKER_FEE_TIERS, window=config.FEE_WINDOW_SECONDS):
        self.tiers, self.window = tiers, window
        self.history = deque()      # (ts, montant) des ordres récents
        self.volume = 0.0           # volume cumulé sur la fenêtre

    def rate(self, ts):
        while self.history and self.history[0][0] <= ts - self.window:
            self.volume -= self.history.popleft()[1]
        rate = self.tiers[0][1]
        for min_volume, tier_rate in self.tiers:
            if self.volume >= min_volume:
                rate = tier_rate
        return rate

    def record(self, ts, notional):
        self.history.append((ts, notional))
        self.volume += notional


class FlatFee:
    """Taux fixe (sert au scénario « pire cas » : palier 1 en permanence)."""

    def __init__(self, rate):
        self._rate = rate
        self.name = f"flat_{rate * 100:.2f}"

    def rate(self, ts):
        return self._rate

    def record(self, ts, notional):
        pass


class Portfolio:
    def __init__(self, cash_eur, fee_model, slippage=config.SLIPPAGE):
        self.cash, self.btc = cash_eur, 0.0
        self.fee_model, self.slippage = fee_model, slippage
        self.trades = []            # ordres exécutés
        self.round_trips = []       # gain net (EUR) de chaque achat+vente clôturé
        self._entry_cost = 0.0      # EUR dépensés (frais inclus) au dernier achat

    def value(self, price):
        """Valeur totale en EUR au prix donné."""
        return self.cash + self.btc * price

    def buy(self, ts, price):
        """Achète du BTC avec tout le cash disponible."""
        if self.cash <= 0:
            return None
        fill = price * (1 + self.slippage)          # on paie un peu plus cher
        rate = self.fee_model.rate(ts)
        notional = self.cash / (1 + rate)           # montant investi, hors frais
        fee = notional * rate
        qty = notional / fill
        self._entry_cost = self.cash
        self.cash, self.btc = 0.0, qty
        return self._log(ts, "buy", fill, qty, fee, notional)

    def sell(self, ts, price):
        """Vend tout le BTC détenu."""
        if self.btc <= 0:
            return None
        fill = price * (1 - self.slippage)          # on vend un peu moins cher
        rate = self.fee_model.rate(ts)
        notional = self.btc * fill
        fee = notional * rate
        qty = self.btc
        self.cash, self.btc = notional - fee, 0.0
        self.round_trips.append(self.cash - self._entry_cost)
        return self._log(ts, "sell", fill, qty, fee, notional)

    def rebalance(self, ts, price, weight):
        """Ramène la part de BTC à `weight` (entre 0 et 1) de la valeur du portefeuille."""
        delta = weight * self.value(price) - self.btc * price   # EUR de BTC à acheter (+) ou vendre (-)
        rate = self.fee_model.rate(ts)
        if delta > 0:
            fill = price * (1 + self.slippage)
            notional = min(delta, self.cash / (1 + rate))
            if notional <= 0:
                return None
            fee = notional * rate
            self.cash = max(0.0, self.cash - notional - fee)
            self.btc += notional / fill
            return self._log(ts, "buy", fill, notional / fill, fee, notional)
        if delta < 0 and self.btc > 0:
            fill = price * (1 - self.slippage)
            qty = min(self.btc, -delta / price)
            notional = qty * fill
            fee = notional * rate
            self.btc -= qty
            self.cash += notional - fee
            return self._log(ts, "sell", fill, qty, fee, notional)
        return None

    def _log(self, ts, side, price, qty, fee, notional):
        self.fee_model.record(ts, notional)
        trade = {"ts": ts, "side": side, "price": price, "qty": qty, "fee": fee}
        self.trades.append(trade)
        return trade
