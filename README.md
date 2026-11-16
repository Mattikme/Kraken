# Tournoi de bots de trading sur Kraken (crypto, ETF, devises) : simulation d'abord

Objectif : faire s'affronter plusieurs bots sur **1 000 € fictifs chacun**, mesurer
honnêtement lequel gagne après frais, puis faire passer au réel uniquement celui
qui a fait ses preuves. Aucun argent réel, aucune clé API à ce stade.

## Démarrage rapide (ton ordinateur)

Il faut seulement Python 3.10+. Aucune clé API, aucune base de données, aucun compte.

| Système | Commande |
|---|---|
| Windows | double-clic sur `lancer.bat` |
| macOS / Linux | `./lancer.sh` |
| À la main | `pip install -r requirements.txt` puis `python -m bot run` |

Le bot tourne seul : toutes les 15 min il récupère les cours Kraken, rejoue tous
les bots et met à jour `donnees/rapport.html`, une page à ouvrir dans le navigateur
qui se recharge seule. Ctrl+C l'arrête ; relancé plus tard, il reprend et rattrape
la période manquée. Au premier lancement, il calcule aussi le tournoi sur 10 ans.

| Commande | Effet |
|---|---|
| `python -m bot run [--minutes 15]` | tourne en continu |
| `python -m bot once` | un seul passage |
| `python -m bot status` | dernier classement, sans réseau |
| `python -m bot historique` | tournoi 2016 → aujourd'hui (cours longs) |

Fichiers produits dans `donnees/` : `rapport.html`, `ordres.csv` (tous les ordres
simulés depuis le lancement), `etat.json`, `historique.json`, `bot.log`,
`bot.sqlite`. Supprimer ce dossier remet le tournoi à zéro.

## L'univers (`bot/universe.py`)

Actifs tradables au comptant sur Kraken depuis des EUR **et liquides** (échangés
presque tous les jours, plus de 50 000 $ par jour) : un cours sans échange n'est
pas un prix auquel on peut acheter. Sur les 177 ETF et actions tokenisés de
Kraken, seuls trois passent ce filtre (relevé du 2026-11-16).

| Catégorie | Actifs | Frais preneur Kraken (+ glissement 0,05 %) |
|---|---|---|
| Crypto | Bitcoin, Ether, Solana | 0,80 %, dégressif avec le volume |
| ETF tokenisés | S&P 500 (SPYx), Nasdaq 100 (QQQx), or (GLDx) | 0,08 % + 0,20 % de conversion EUR→USD |
| Devises | USD, GBP, JPY, CHF, AUD, CAD (face à l'euro) | 0,20 % |

## Les bots (`bot/bots.py`)

Liste et paramètres fixés avant le premier test, d'après des règles publiées.
Décision avec les clôtures du jour, exécution à la clôture du lendemain.

| Bot | Règle |
|---|---|
| Tout un peu (référence) | 1/3 crypto, 1/3 ETF, 1/3 devises, rééquilibré chaque mois |
| Tendance | garde chaque actif au-dessus de sa moyenne 10 mois (Faber) |
| Tendance × risque | idem, parts inversement proportionnelles à la volatilité |
| Momentum top 3 | les 3 actifs les plus forts sur 6 mois, s'ils montent |
| Momentum crypto | chaque semaine, la crypto la plus forte sur 4 semaines |
| Devises | les 2 devises les plus fortes face à l'euro sur 3 mois |
| Rebond actions (RSI 2) | achète les creux du S&P 500 et du Nasdaq en tendance haussière (Connors) |
| Cassure 55/20 jours | achète les nouveaux plus hauts, revend sous le plus bas 20 jours |
| Bitcoin · ensemble de tendances | part de BTC selon 4 moyennes mobiles |
| Actions + or + BTC | portefeuille retenu par la recherche multi-actifs |
| **Sélectionneur** | méta-bot : chaque mois, copie les 3 bots les plus réguliers des 6 derniers mois |

Le sélectionneur fait évoluer le tournoi : il suit automatiquement les bots qui
gagnent et abandonne ceux qui perdent, en ne voyant que le passé.

## Résultat du tournoi sur 10 ans

`python -m bot historique`, le 2026-11-16. Cours longs des actifs d'origine
(ETF SPY/QQQ/GLD, crypto en EUR, taux de change ; Yahoo Finance), 2016-01-01 →
2026-11-13, 1 000 € chacun, frais Kraken inclus.

| Bot | Capital final | Par an | Pire baisse | Sharpe | Ordres |
|---|---|---|---|---|---|
| Momentum crypto | 620 823 € | +80,7 % | 82,4 % | 1,14 | 217 |
| Bitcoin · ensemble de tendances | 108 361 € | +53,9 % | 65,2 % | 1,18 | 756 |
| Momentum top 3 | 85 671 € | +50,6 % | 60,7 % | 1,13 | 319 |
| Sélectionneur | 45 345 € | +42,1 % | 34,5 % | 1,31 | 1 396 |
| Tout un peu (référence) | 34 014 € | +38,3 % | 42,1 % | 1,35 | 219 |
| Tendance | 16 290 € | +29,3 % | 26,3 % | 1,39 | 318 |
| Cassure 55/20 jours | 8 251 € | +21,4 % | 21,3 % | 1,35 | 1 035 |
| Actions + or + BTC | 5 016 € | +16,0 % | 13,6 % | 1,35 | 162 |
| Tendance × risque | 1 254 € | +2,1 % | 5,2 % | 0,60 | 267 |
| Rebond actions (RSI 2) | 858 € | −1,4 % | 21,1 % | −0,19 | 382 |
| Devises | 666 € | −3,7 % | 37,4 % | −0,62 | 204 |

À lire avec prudence :
- les gros gains viennent presque tous de la crypto en 2017, 2020 et 2021 ;
  sur 2025-2026, la plupart des bots perdent ;
- **biais du survivant** : Solana et Ether ont été choisis en 2026, en sachant
  qu'ils ont réussi ; un bot de 2016 aurait pu choisir des cryptos disparues
  depuis. Les chiffres du momentum crypto sont donc surestimés ;
- les bots de devises et de rebond actions ne couvrent pas leurs frais ;
- un passé favorable ne garantit rien.

## Du test au vrai bot

1. **Simulation** (maintenant) : le tournoi tourne sur les cours Kraken en direct.
2. **Promotion** : un bot devient « candidat au réel » dans le rapport s'il
   remplit tous ces critères, fixés à l'avance :
   au moins 90 jours de simulation, un gain supérieur à « Tout un peu », une pire baisse
   inférieure à 15 % depuis le lancement et à 40 % sur 10 ans.
3. **Réel, petit montant** : seul un candidat sera branché sur Kraken (clé API
   sans droit de retrait, plafond par ordre, arrêt automatique en cas de perte),
   d'abord avec quelques dizaines d'euros, en parallèle de sa simulation.

## Fonctionnement (version cloud : GitHub Actions + Neon + Vercel)

| Élément | Rôle | Où |
|---|---|---|
| `bot/collector.py` | bougies 1 h BTC/EUR → Neon, toutes les 15 min | GitHub Actions `collector` |
| `bot/history.py` | 10 ans d'historique (archive officielle Kraken + API) | GitHub Actions `backtest` |
| `bot/strategy.py` | A : moyennes mobiles 20/50 (1 h) · B : momentum 24 h · C : moyennes mobiles 20/50 (1 jour) · D : ensemble de tendances · référence : buy & hold | — |
| `bot/research.py` | test de six stratégies candidates sur 10 ans (lecture seule) | GitHub Actions `research` |
| `bot/multi.py` | test de portefeuilles actions + or + bitcoin | GitHub Actions `research` et `backtest` |
| `bot/multi_paper.py` | simulation en direct du portefeuille retenu (cours Kraken) | GitHub Actions `collector` |
| `bot/local.py`, `bot/__main__.py`, `bot/arena.py`, `bot/bots.py`, `bot/universe.py` | tournoi local (SQLite, rapport HTML) | ton ordinateur |
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

## Recherche multi-actifs : actions, or et bitcoin

Kraken permet aussi de trader des ETF tokenisés (SPYx = S&P 500, GLDx = or) avec
0,08 % de frais preneur, et des devises. Portefeuilles fixés avant le test
(`bot/multi.py`), vus en EUR, frais et conversion EUR/USD inclus. Les ETF
tokenisés n'existant que depuis 2025, le test utilise l'historique des ETF
d'origine (table `daily_prices`). Lancé par GitHub Actions le 2026-11-15.

**10 ans (2016-11-16 → 2026-11-14), départ 1 000 €**

| Portefeuille | Final | Par an | Pire baisse | Années positives | Pire année | 2 dernières années |
|---|---|---|---|---|---|---|
| Tendance pondérée par le risque (retenu) | 4 358 € | +15,9 % | 13,6 % | 9 / 11 | −6,1 % | +24,6 % |
| 60 % actions, 30 % or, 10 % bitcoin | 10 117 € | +26,1 % | 27,7 % | 9 / 11 | −12,2 % | +25,4 % |
| Tendance, un tiers chacun | 12 660 € | +28,9 % | 35,0 % | 8 / 11 | −24,3 % | +10,0 % |
| Un tiers chacun, fixe | 17 050 € | +32,8 % | 39,5 % | 8 / 11 | −28,9 % | +13,8 % |
| Actions seules | 3 895 € | +14,6 % | 33,1 % | 9 / 11 | −13,1 % | +24,3 % |
| Bitcoin seul | 83 716 € | +55,7 % | 82,5 % | 7 / 11 | −73,0 % | −29,7 % |

**Contrôle long sans bitcoin (2006 → 2026, crise de 2008 incluse)** : la version
actions + or du portefeuille retenu fait +9,2 % par an, pire baisse 18,6 %,
18 années positives sur 21, pire année −5,8 % (2008 : −4,1 % quand les actions
perdaient 34 %).

Le portefeuille retenu (`tendance_risque`) : chaque actif n'est détenu que si son
cours de fin de mois dépasse la moyenne des 10 dernières fins de mois (règle de
Faber) ; sa part est d'autant plus petite qu'il est volatil ; le reste est en EUR.
Il tourne en simulation avec les seuls cours Kraken (`bot/multi_paper.py`).

Limites : passé favorable aux actions américaines et à l'or ; ETF d'origine et non
jetons Kraken dans le test ; années négatives possibles (2018, 2022) ; les jetons
ajoutent un risque d'émetteur ; rien ne garantit l'avenir.

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
