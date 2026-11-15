# Bot de trading BTC/EUR sur Kraken — simulation d'abord

Objectif : mesurer honnêtement si une stratégie simple bat le « buy & hold »
(acheter et garder) après frais. Aucun argent réel, aucune clé API à ce stade.

## Fonctionnement

| Élément | Rôle | Où |
|---|---|---|
| `bot/collector.py` | bougies 1 h BTC/EUR → Neon, toutes les 15 min | GitHub Actions `collector` |
| `bot/history.py` | 10 ans d'historique (archive officielle Kraken + API) | GitHub Actions `backtest` |
| `bot/strategy.py` | A : moyennes mobiles 20/50 (1 h) · B : momentum 24 h · C : moyennes mobiles 20/50 (1 jour) · D : ensemble de tendances · référence : buy & hold | — |
| `bot/research.py` | test de six stratégies candidates sur 10 ans (lecture seule) | GitHub Actions `research` |
| `bot/portfolio.py` | portefeuille fictif : frais preneur Kraken + glissement 0,05 % | — |
| `bot/backtest.py` | rejoue les stratégies, écrit les résultats dans Neon | GitHub Actions `backtest` |
| `bot/paper_trader.py` | simulation en direct sur 1 000 € fictifs, après chaque collecte | GitHub Actions `collector` |
| `dashboard/` | tableau de bord (Next.js) qui lit Neon | Vercel |
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

## Résultat de l'étape 1

Backtest lancé par GitHub Actions le 2026-11-15, frais Kraken réels.

**2 ans (2024-11-15 → 2026-11-15) — période jugée**

| Stratégie | Capital final | Ordres | Taux de réussite | Frais payés | Drawdown max | Bat le buy & hold ? |
|---|---|---|---|---|---|---|
| Moyennes mobiles 20/50, 1 h | 48,14 € | 402 | 17,9 % | 732,43 € | 95,4 % | non |
| Momentum 24 h | 73,79 € | 374 | 19,3 % | 721,71 € | 92,7 % | non |
| Moyennes mobiles 20/50, 1 jour | 734,55 € | 20 | 40,0 % | 143,80 € | 43,9 % | oui, de 37 € |
| Buy & hold | 697,18 € | 1 | — | 7,94 € | 52,4 % | — |

**10 ans (2016-11-17 → 2026-11-15) — contrôle**

| Stratégie | Capital final | Ordres | Drawdown max | Bat le buy & hold ? |
|---|---|---|---|---|
| Moyennes mobiles 20/50, 1 jour | 28 464 € | 80 | 77,4 % | non |
| Buy & hold | 83 433 € | 1 | 82,9 % | — |

**Verdict : pas d'avantage démontré.** Les stratégies horaires sont détruites par
les frais. La stratégie journalière passe le critère des 2 ans, mais de justesse
et par hasard de calendrier : elle n'a été devant le buy & hold que 371 jours
sur 731, elle était encore derrière le 10 novembre 2026, et sur 10 ans elle ne
garde qu'un tiers du gain du buy & hold (elle perd moins les années de baisse,
mais rate l'essentiel des hausses).

Les chiffres à jour sont dans la table `backtest_results` de Neon.

## Recherche : six autres stratégies (10 ans, frais réels)

Liste fixée et enregistrée avant le premier test (`bot/research.py`), paramètres
d'usage tirés de la littérature, aucune optimisation. Lancé par GitHub Actions
(`research`) le 2026-11-15, période 2016-11-17 → 2026-11-15, départ 1 000 €.

| Stratégie | Capital final | Par an | Pire baisse | Sharpe | Ordres | Frais |
|---|---|---|---|---|---|---|
| Buy & hold | 83 433 € | +55,7 % | 82,9 % | 1,00 | 1 | 8 € |
| Ensemble de tendances (moyennes 20/50/100/200 j) | 65 890 € | +52,1 % | 59,6 % | 1,17 | 712 | 22 999 € |
| Filtre moyenne 200 jours | 50 824 € | +48,2 % | 66,6 % | 1,02 | 80 | 10 923 € |
| Momentum 4 semaines (hebdo) | 41 856 € | +45,3 % | 79,2 % | 1,01 | 120 | 13 847 € |
| Volatilité cible 50 % | 28 766 € | +40,0 % | 71,7 % | 0,93 | 169 | 1 938 € |
| Moyennes 20/50 · 1 jour | 28 464 € | +39,8 % | 77,4 % | 0,93 | 80 | 9 157 € |
| Tendances × volatilité cible | 26 201 € | +38,7 % | 50,0 % | 1,14 | 740 | 11 020 € |
| Moitié BTC / moitié EUR | 18 278 € | +33,7 % | 51,3 % | 1,03 | 33 | 191 € |

**Aucune ne rapporte plus que le buy & hold sur 10 ans**, et aucune ne le bat
dans les deux moitiés de la période. Toutes réduisent la pire baisse. Sur les
5 dernières années (BTC ×1,04), les règles de tendance font mieux que le buy &
hold (×1,18 à ×1,50) ; sur les 5 premières (BTC ×80), elles font nettement moins
bien. L'ensemble de tendances est le meilleur compromis mesuré ; il a été choisi
après coup parmi six, donc son avantage est probablement surestimé.

## Étape 2 : simulation en direct

Démarrée le 2026-11-15 à 03:00 UTC avec quatre stratégies (les trois premières
et l'ensemble de tendances) et le buy & hold, chacun sur 1 000 € fictifs. Mêmes règles que le backtest : décision à la clôture
d'une bougie 1 h, exécution à l'ouverture de la suivante, frais preneur Kraken,
glissement de 0,05 %. Le calcul est rejoué à chaque passage : pas de doublon, et
une panne se rattrape toute seule. Tables : `signals`, `trades`, `equity`
(mode `paper`) et `paper_results`.

## Tableau de bord (Vercel)

1. Sur <https://vercel.com/new>, importer le dépôt `Mattikme/Kraken`.
2. **Root Directory** : `dashboard`.
3. **Environment Variables** : `DATABASE_URL` = chaîne de connexion Neon.
4. Deploy.

Le tableau de bord ne fait que lire Neon ; une donnée absente s'affiche « — ».

## Tests

`python -m pytest -q` (aucun accès réseau nécessaire).
