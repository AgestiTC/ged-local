# Plan — Amélioration « Discuter avec l'IA » + étiquette de pertinence

Branche : `feat/amelioration-discussion-ia` · constaté le 09/11/2026 sur la prod v1.159.1.

## Constats

1. **Chat** : « Quel est la licence d'athlétisme de Thomas ? » → « Je ne connais pas », alors que
   la GED contient `2025-2026-2391985.pdf` (Thomas Clement licencié FFA). Cause : l'interrupteur
   **GED est éteint** (`chatStore.useGed: false` par défaut, persisté) → `/generate/chat` n'appelle
   pas `_contexte_ged`. Le modèle n'a aucun moyen de connaître la réponse. Et même interrupteur
   allumé, la consigne système dit « si la réponse n'y figure pas, réponds avec tes
   connaissances » : rien n'empêche une réponse inventée sur une personne.
2. **GED** : « licence athlétisme thomas » → le bon document est étiqueté **Moyenne**. Cause :
   `pertinence.evaluer` ne donne « Élevée » qu'au cosinus ≥ 0,72. Une requête courte de mots-clés
   (3 mots) plafonne en dessous, même quand `plainto_tsquery` trouve **tous** les termes — signal
   pourtant très fort pour une requête de plusieurs mots.

## Step 1 — Chat : aller chercher dans la GED quand la question porte sur les documents

Implémenter côté backend une détection « question sur mes documents » (personne nommée, pièce
administrative, « mon/ma/mes », numéro de licence/contrat…) réutilisant `qa_service.comprendre` :
si l'intention est documentaire et le mode GED vaut « auto », faire la récupération et, si des
extraits pertinents existent, les injecter **et** le signaler au frontend (en-tête
`X-Ged-Auto: 1` + noms des sources). Côté UI : bandeau « Réponse appuyée sur vos documents » +
liste cliquable des sources. Interrupteur GED à trois états : « auto » (défaut), « toujours »,
« jamais » (aucun appel à la GED).

Acceptance :
- la question témoin, en « auto », renvoie le n° de licence en citant `2025-2026-2391985.pdf` ;
- une question générale (« écris un mail de relance ») ne déclenche aucune récupération ;
- mode « jamais » : aucun appel à `qa_service`.

## Step 2 — Chat : consigne anti-invention sur les données personnelles

Ajuster la consigne système RAG : quand la question porte sur une personne/pièce de la GED et
qu'aucun extrait ne contient la réponse, répondre « Je n'ai pas trouvé ce document dans la GED »
plutôt que des connaissances générales. Tests sur le texte de la consigne et le chemin « contexte vide ».

Acceptance :
- contexte vide + intention documentaire → message explicite « pas trouvé dans la GED » ;
- intention générale → comportement inchangé.

## Step 3 — Pertinence : « Élevée » quand tous les termes d'une requête multi-mots sont trouvés

Faire évoluer `services/pertinence.evaluer` : ÉLEVÉE si cosinus ≥ haut, **ou** si la requête
compte ≥ 2 termes significatifs, que le match lexical (tous les termes, `plainto_tsquery`) est
vrai et que cosinus ≥ bas. Requête d'un seul mot : règle actuelle inchangée (le match d'un mot
est un signal faible sur 56 k docs). Mettre à jour `routers/search.py` et `routers/assistant.py`
(deux appelants), tests `test_pertinence.py`.

Acceptance :
- « licence athlétisme thomas » : le document 2025-2026 étiqueté Élevée ;
- « facture » seul : étiquettes inchangées ; « dossier de mariage » / « recette » : toujours 0 pertinent ;
- suite backend verte.

## Step 4 — Vérification de bout en bout et livraison

`/verify` sur pile jetable (chat auto + GED), puis CHANGELOG/ROADMAP et `/livrer`.

Acceptance :
- scénarios des steps 1-3 rejoués dans l'appli qui tourne ;
- CHANGELOG + ROADMAP à jour, prod vérifiée par `verifier-deploiement.ps1`.

Out of scope : changer les seuils cosinus calibrés (0,72 / 0,65), refondre `qa_service`.
