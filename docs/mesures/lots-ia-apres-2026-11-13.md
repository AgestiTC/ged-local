# Lots IA — relevé après correction, 13/11/2026

Plan : [plan-lots-ia-par-modele.md](../plan-lots-ia-par-modele.md), étape 6.
Point de comparaison : [relevé de référence du 12/11](lots-ia-reference-2026-11-12.md).

> **Provenance.** Mesuré par cette session le 13/11/2026 à 11 h 45, dans le journal d'Ollama du
> PC-GAME (`%LOCALAPPDATA%\Ollama\server*.log`), en lecture seule. Un chargement de modèle = une
> ligne `starting llama-server` ; un appel = une ligne `[GIN] … POST "/api/…"` (embeddings,
> générations, discussion). Le journal de la passerelle n'a pas été lu (accès fermé à cette
> session) : **pas de ventilation par `X-AI-Usage`**.

## Ce que le relevé permet de dire

**La correction tient sous charge, mais sur 9 heures et non sur 24.** La file de fond s'est vidée
le 12/11 vers 20 h : depuis, il n'y a plus de trafic de lots à mesurer (aucun appel de fond le 13/11
au matin). Le critère « 24 h de production » du plan n'est donc pas rempli ; il le sera à la
prochaine grosse indexation.

| Indicateur | Avant — 11/11 (journée entière) | Après — 12/11 de 11 h à 20 h |
| --- | --- | --- |
| Appels IA | 62 005 | 17 709 |
| Chargements de modèle | 1 888 | 64 |
| Chargements pour 1 000 appels | 30 | 3,6 |
| Pire heure | 467 chargements (20 h) | 37 chargements (13 h) |
| Erreurs 500 | 18 | 3 |

- **Chargements de modèle** : divisés par 8 à nombre d'appels égal, par 29 en valeur absolue. Le
  critère du plan (« divisés au moins par 10 sur une journée ») est atteint en valeur absolue, pas
  encore démontré à charge égale sur 24 h.
- **Délais dépassés** : ils baissent, **ils ne disparaissent pas**. Côté Ollama, 67 erreurs 500
  après 4 min 50 s à 5 min d'attente le 12/11 entre minuit et 10 h (6 à 9 par heure), aucune
  ensuite (les trois erreurs 500 de l'après-midi ont duré 1,3 s, 1,4 s et 1 min 20 s). Mais **la
  passerelle a coupé 51 appels à 300 s** l'après-midi du 12/11, en trois vagues (13 h 49 à 14 h 45,
  16 h 08 à 16 h 28, 18 h 36 à 18 h 57, heure de Paris) — relevé de la session AIGUILLEUR, invisible
  dans le journal d'Ollama, qui ne note pas ces coupures comme des erreurs 500. La dernière vague
  s'achève un quart d'heure après la livraison des reprises différées (v1.169.0, 18 h 41).
- **Embeddings par paquets** : `/api/embed` remplace `/api/embeddings` à partir du 12/11 à 11 h
  (6 271 appels par paquets ce jour-là, contre 41 674 appels unitaires la veille).

Le relevé de référence donnait 1 843 chargements le 11/11 ; celui-ci en compte 1 888 avec un autre
marqueur du journal. L'écart (2 %) ne change pas la comparaison.

## Détail par heure, 12/11

| Heure | 00 à 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Appels | 832 | 1 502 | 2 640 | 1 629 | 301 | 2 367 | 1 006 | 3 853 | 1 203 | 3 206 |
| Chargements | 202 | 0 | 6 | 37 | 0 | 4 | 4 | 6 | 0 | 7 |

Entre minuit et 10 h, l'ancien code tourne encore : un chargement tous les quatre appels.

## Retours de la session AIGUILLEUR (13/11)

Lus dans le journal de la passerelle, vérifiés ensuite dans le code et dans la base de production.

- **Les paquets d'embeddings ne contiennent presque toujours qu'un texte** (99,4 % des appels
  `/api/embed`). Le regroupement se fait **par document** (`embedding_service.calculer`, 32
  morceaux au plus), et les documents indexés ce jour-là sont courts : sur 7 573 documents
  vectorisés depuis le 12/11 à 11 h 54, 7 560 tiennent en un seul morceau. Le gain de l'étape 2 est
  donc réel pour les longs documents (4 documents de plus de 32 morceaux : 856 morceaux en 28
  appels) et nul pour les autres. Regrouper **entre** documents demanderait que le worker prenne
  plusieurs tâches `ia_embed` d'un coup : non fait, à décider.
- **Le repli d'embedding changeait de modèle** : 19 des 51 appels coupés visaient
  `nomic-embed-text`. C'était le code d'avant la v1.169.0, qui basculait sur le modèle de repli au
  premier échec. Un succès n'aurait **rien écrit** : `nomic-embed-text` rend 768 dimensions et la
  colonne est `halfvec(4096)`, l'insertion aurait été refusée et la tâche serait passée en échec.
  Vérifié en production : les 157 351 vecteurs (48 318 documents) sont tous de `qwen3-embedding:8b`.
  Depuis la v1.169.0 il n'y a plus de repli d'embedding du tout.

## Ce qui n'est pas mesuré

- **Une journée complète sous charge** avec le pipeline en trois étapes (voir plus haut).
- **La plage horaire** (étape 4) : aucune plage n'est réglée en production au 13/11.
- **Les reprises différées** (étape 5) : elles ont servi une fois. 14 tâches reportées en
  production (8 `ia_enrich`, 4 `ia_embed`, 2 `analyze`), toutes terminées au premier report. Trop
  peu pour juger de leur tenue sous une vraie saturation.
- **La ventilation par usage** (`X-AI-Usage`) et la part de la vision : lisibles seulement dans le
  journal de la passerelle.
- **L'occupation de la carte graphique** pendant les lots : non relevée.

## Pour refaire ce relevé

Compter, par jour et par heure, les lignes `starting llama-server` et les lignes `[GIN]` en `POST
/api/…` des fichiers `server*.log`, puis les erreurs 500 avec leur durée. À faire sur une journée
où la file de fond a tourné 24 h (après l'ajout d'une source, par exemple).
