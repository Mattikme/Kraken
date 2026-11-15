# Bot de trading BTC/EUR sur Kraken — simulation d'abord

Objectif : mesurer honnêtement si une stratégie simple bat le « buy & hold »
(acheter et garder) après frais. Aucun argent réel, aucune clé API à ce stade.

## Fonctionnement

| Élément | Rôle | Où |
|---|---|---|
| `bot/collector.py` | bougies 1 h BTC/EUR → Neon, toutes les 15 min | GitHub Actions `collector` |
| `bot/history.py` | 2 ans d'historique (archive officielle Kraken + API) | GitHub Actions `backtest` |
| `bot/strategy.py` | A : moyennes mobiles 20/50 · B : momentum 24 h · référence : buy & hold | — |
| `bot/portfolio.py` | portefeuille fictif : frais preneur Kraken + glissement 0,05 % | — |
| `bot/backtest.py` | rejoue les stratégies, écrit les résultats dans Neon | GitHub Actions `backtest` |
| `schema.sql` | tables Neon | — |

Seul secret nécessaire : `DATABASE_URL` (chaîne de connexion Neon) dans
*Settings → Secrets and variables → Actions*.

## Hypothèses du backtest

- Capital 1 000 €, au comptant, sans levier, tout le capital à chaque ordre.
- Frais preneur Kraken Pro selon le volume 30 jours (0,80 % → 0,60 % → 0,38 %…),
  relevés le 2026-11-15 sur <https://www.kraken.com/pro/fees>.
- Glissement de 0,05 % par ordre.
- Décision à la clôture d'une bougie, exécution à l'ouverture de la suivante.
- Paramètres fixés à l'avance, jamais ajustés après coup.

## Résultat de l'étape 1 (2024-11-15 → 2026-11-15)

| Stratégie | Capital final | Ordres | Frais payés | Drawdown max | Bat le buy & hold ? |
|---|---|---|---|---|---|
| Moyennes mobiles 20/50 | 47,81 € | 402 | 727,61 € | 95,4 % | non |
| Momentum 24 h | 73,79 € | 374 | 721,71 € | 92,7 % | non |
| Buy & hold | 676,42 € | 1 | 7,94 € | 52,4 % | — |

**Verdict : aucune stratégie ne bat le buy & hold après frais. Arrêt, comme prévu.**
Les chiffres à jour sont dans la table `backtest_results` de Neon.

## Tests

`python -m pytest -q` (aucun accès réseau nécessaire).
