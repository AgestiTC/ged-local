# Mesure de référence des lots IA — 12/11/2026

Plan : [plan-lots-ia-par-modele.md](../plan-lots-ia-par-modele.md), étape 1.

> **Provenance.** Ces chiffres n'ont pas été mesurés par cette session : ils viennent du
> diagnostic d'une autre session, relevé le 12/11/2026 dans le journal de la passerelle IA et dans
> celui d'Ollama, sur 24 h (sauf mention contraire). Ils servent de point de comparaison, pas de
> mesure rejouable.

## Relevé du 12/11/2026

| Indicateur | Valeur |
| --- | --- |
| Appels IA sur 24 h | 20 294 |
| Priorité déclarée | 100 % en `batch` |
| Appels `qwen3-embedding:8b` | 13 467 |
| Appels `llama3.1:latest` | 5 522 |
| Appels `qwen2.5vl:7b` | 1 305 |
| Chargements de modèle le 11/11 | 1 843 (environ un toutes les 30 s aux heures pleines) |
| Pic de générations le 11/11 | 2 400 à 2 800 par heure, entre 6 h et 9 h |
| Carte graphique | 99 à 100 % d'utilisation |
| Mémoire vidéo | 15,5 à 15,8 Go sur 16 |
| Erreurs 500 le matin du 12/11 | 63, chacune après environ 4 min 50 s d'attente |

Réglages Ollama en vigueur : 2 modèles chargés au plus, 1 requête en parallèle, maintien en
mémoire 30 min.

## Limite : pas de ventilation par usage

La répartition par usage (embeddings, vision, enrichissement, rapport, chat) **n'existe pas
encore** dans ce relevé. Elle ne sera disponible qu'une fois l'en-tête `X-AI-Usage` déployé en
production : jusque-là, seule la répartition par modèle est connue (ci-dessus).

## À refaire après les étapes 3 et 4

Même méthode (journal de la passerelle et journal d'Ollama, 24 h), avec en plus la ventilation par
`X-AI-Usage`.

| Indicateur | Avant (12/11/2026) | Après étapes 3 et 4 |
| --- | --- | --- |
| Appels IA sur 24 h | 20 294 | |
| Priorité déclarée | 100 % `batch` | |
| Appels `qwen3-embedding:8b` | 13 467 | |
| Appels `llama3.1:latest` | 5 522 | |
| Appels `qwen2.5vl:7b` | 1 305 | |
| Chargements de modèle sur une journée | 1 843 (le 11/11) | |
| Pic de générations par heure | 2 400 à 2 800 | |
| Utilisation de la carte graphique | 99 à 100 % | |
| Mémoire vidéo utilisée | 15,5 à 15,8 Go sur 16 | |
| Erreurs 500 sur une matinée | 63 (12/11) | |
| Attente avant chaque erreur 500 | environ 4 min 50 s | |
| Appels par usage (`X-AI-Usage`) | non disponible | |
