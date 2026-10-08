# Agent de trading IA & Tech

Agent qui scanne ~280 actions (IA et tech en priorité, sur tous les continents, plus une sélection hors tech) et produit un rapport chaque matin : notes court/moyen/long terme, analyse technique, figures chartistes, régime de marché, obligations, secteurs et régions, watchlist dynamique.

## Comment ça tourne (gratuit)

| Heure (Paris) | Qui | Quoi |
|---|---|---|
| ~8 h 20, du lundi au vendredi | **GitHub Actions** (`.github/workflows/rapport.yml`) | Scan chiffré complet, rapport HTML, notification **ntfy** sur le téléphone |
| ~8 h 55 | **Tâche planifiée Claude** (abonnement Claude, pas de clé API) | Lit `rapports/dernier.json`, cherche l'actualité, écrit `rapports/analyse_DATE.md`, propose des ajouts/retraits (`propositions_claude.json`), notification dans l'app Claude |
| juste après | **GitHub Actions** (`analyse.yml`) | Publie l'analyse de Claude sur le site |

Le lendemain, l'agent vérifie avec les chiffres les ajouts proposés par Claude avant de les accepter.

## Fichiers

- `trading_agent.py` : l'agent (listes d'actions et réglages en haut du fichier)
- `etat_agent.json` : mémoire de la watchlist dynamique (mise à jour automatiquement)
- `cache_fondamentaux.json` : fondamentaux gardés 7 jours
- `rapports/` : rapports HTML et CSV, `dernier.json` (données pour Claude), `analyse_*.md` (analyses de Claude)
- `CONSIGNES_CLAUDE.md` : consignes d'analyse données à Claude (générées par le script)

## Réglages GitHub

- **Secret** `NTFY_TOPIC` : nom du canal de notification ntfy (à garder pour toi)
- **Variable** `RAPPORT_URL` : adresse du site GitHub Pages (dépôt public). Vide = rapport joint à la notification.

## Lancer à la main

- Sur GitHub : onglet **Actions** → **Rapport du matin** → **Run workflow**
- Sur ton PC : `py trading_agent.py --sans-ia` (gratuit) ou `py trading_agent.py` (avec clé API)

Outil d'aide à la décision, pas un conseil en investissement.
