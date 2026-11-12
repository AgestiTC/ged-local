# Plan — lots IA groupés par modèle (désaturer la carte graphique de PC-GAME)

> **Statut** : proposé le 12/11/2026, **non commencé**. Aucune ligne du worker modifiée.
> Origine : diagnostic de la session `migration-nmp-44` (12/11), à la demande de Thomas.

## 1. Le constat

Sur 24 h, la passerelle AIGUILLEUR a relayé ~20 300 appels de Matothèque, tous en `batch` :
~13 500 embeddings (`qwen3-embedding:8b`), ~5 500 enrichissements (`llama3.1`), ~1 300 vision
(`qwen2.5vl:7b`). Ollama ne garde que **deux** modèles chargés (`OLLAMA_MAX_LOADED_MODELS=2`) et les
trois ne tiennent pas ensemble dans 16 Go → **~1 840 chargements de modèle le 11/11** (un toutes les
30 s aux heures pleines), carte à 99-100 %, bureau de Thomas ralenti, et des appels qui finissent en
erreur 500 après ~4 min 50 s d'attente, puis sont relancés.

**Pourquoi** (vérifié dans le code) :

- un job `analyze` traite **un document de bout en bout** : Tika → vision si le texte est vide →
  enrichissement → embeddings (`ExtractionService.analyze_existing`, `process_file`,
  `reprendre_contenu_stocke`) ;
- `concurrence_gpu = 2` : deux documents en vol, chacun à une étape différente → deux modèles
  demandés en même temps, le troisième attend son tour et en évince un ;
- `_claim` prend les jobs en FIFO : réordonner la file ne change rien tant que chaque job contient
  les trois modèles ;
- les embeddings partent **un morceau de texte par appel** (`/api/embeddings`), d'où le volume.

## 2. Partage des rôles avec AIGUILLEUR

AIGUILLEUR est la passerelle IA locale partagée (Matothèque, Foulée, JARVIS) ; tous les appels IA
de la prod passent par elle. Ce plan **ne réimplémente rien de ce qui est à elle** :

| Sujet | Qui | Pourquoi |
| --- | --- | --- |
| Routage, repli, keep-alive, arbitrage **entre projets** (JARVIS > Foulée > batch), arbitrage voix/texte | **AIGUILLEUR** (son plan d'arbitrage GPU, étapes T3/T4) | elle seule voit tous les clients |
| **Ordre** de nos propres lots (grouper par modèle) | **Matothèque** | la passerelle voit une requête à la fois ; elle ne peut pas réordonner une file qu'elle ne possède pas |
| **Volume** de nos lots (plage horaire, reprises) | **Matothèque** | relevé AIGUILLEUR du 30/09 : sous contention, *seule la régulation de la demande tient* |
| Dire **quoi** on demande | **Matothèque** déclare, AIGUILLEUR journalise | en-têtes `X-AI-Project`, `X-AI-Priority`, et `X-AI-Usage` à ajouter |

Conséquences concrètes :

- `X-AI-Priority` reste posé par le worker (`batch` pour les lots, `interactif` pour « Créer »).
  AIGUILLEUR le **journalise sans l'appliquer** aujourd'hui ; ce plan ne dépend pas de son
  application, et ne la gênera pas le jour où elle arrive.
- On ajoute **`X-AI-Usage`** (`embedding`, `vision`, `enrichissement`, `rapport`…) : le journal de
  la passerelle dira enfin *quelle étape* charge la carte, ce qui sert à mesurer l'effet du plan.
- Le jour où AIGUILLEUR appliquera « batch à zéro » (pause, ou voix en cours), elle pourra répondre
  « réessaie plus tard ». Matothèque doit le traiter comme **un report**, pas comme un échec
  (étape 5).
- Pas de `num_gpu=0` sur les embeddings (recommandation 3 écartée) : la recherche en direct
  utilise le même modèle sur la carte ; deux réglages pour un même modèle exposent au rechargement
  à chaque bascule (même piège que `num_ctx`). On y reviendra si les étapes 3 et 4 ne suffisent pas.
- Pas de réduction de `num_ctx` (recommandation 5) dans ce plan : gain faible, même risque.

## 3. Étapes

Une branche par étape, un commit par item, ROADMAP tenue en `[ ]/[~]/[x]`. Déploiement vérifié
(`scripts/deployer.ps1`) après les étapes 2, 4 et 5 au minimum.

### Étape 1 — Mesure de référence et en-tête `X-AI-Usage`

Ajouter `X-AI-Usage` à `entetes_projet()` via une `ContextVar` posée au point d'appel (embedding,
vision, enrichissement, rapport, chat), sur le modèle de `priorite_ia`. Consigner une **mesure de
référence** datée dans `docs/mesures/` : chargements de modèle par jour, appels par usage, nombre
d'erreurs 500 et de dépassements de délai.

*Critères* : chaque appel IA porte un `X-AI-Usage` non vide (test) ; une pile de test ne mélange pas
son trafic à la prod (`AI_PROJECT`) ; relevé de référence écrit.

### Étape 2 — Embeddings envoyés par paquets

Remplacer l'appel unitaire `/api/embeddings` par `/api/embed` (champ `input` = liste de morceaux),
par paquets bornés (ex. 32 morceaux), dans `embedding_service.embed_document`. **Pas de réindexation** :
`/api/embed` renvoie des vecteurs normalisés, et la recherche et les doublons utilisent la distance
cosinus (`<=>`), insensible à la norme — à **revérifier** pour toute autre requête vectorielle avant
de livrer. Repli sur l'appel unitaire si le serveur refuse `/api/embed`. Garder `/api/*`, jamais
`/v1/*` (options perdues en silence).

*Critères* : même nombre de vecteurs, mêmes dimensions (4096 + préfixe 1024) ; un document de 100
morceaux = ≤ 4 appels ; résultats de recherche inchangés sur un jeu de test.

### Étape 3 — Pipeline en étapes, file collante par étape (la vraie correction)

Découper le traitement d'un document en **trois jobs chaînés**, chacun limité à un modèle :

1. `ia_contenu` — Tika, puis vision si le texte est vide (modèle vision) ;
2. `ia_enrich` — enrichissement (modèle d'enrichissement) ;
3. `ia_embed` — embeddings (modèle d'embedding).

Chaque étape met la suivante en file en fin de succès ; le statut du document (`extracted` →
`enriched`) reste la source de vérité, et une étape rejouée est idempotente. Dans `_claim`, pour les
**lots GPU** : continuer de prendre la **même étape** tant qu'il en reste en attente ; changer
d'étape seulement quand elle est vide **ou** au-delà d'un délai maximal (réglage, ex. 20 min) pour
qu'aucune étape n'attende indéfiniment. L'interactif et la priorité forcée passent toujours devant,
sans changement. L'état « étape courante » est **en base**, jamais en mémoire (deux workers uvicorn).

*Critères* : avec 50 documents en attente, les deux places GPU tournent sur le même modèle et on
compte au plus un changement de modèle par étape (test) ; un échec à une étape ne bloque pas les
autres documents ; les anciens types (`analyze`, `enrich`, `reprise_texte`) restent acceptés le
temps que la file se vide.

### Étape 4 — Plage horaire des lots

Réglage « Lots IA autorisés de … à … » (défaut proposé : 22h00 → 06h00 ; vide = toujours). En dehors
de la plage, le worker applique la logique de la **pause IA** existante (`interactifs_seulement`) :
« Créer », le chat et la recherche restent servis. L'écran « File IA » explique le motif
(« en attente de la plage de nuit ») comme il le fait pour la pause. Fuseau : Europe/Paris, plage à
cheval sur minuit gérée.

*Critères* : test de la fonction pure « dans la plage ? » (dont minuit et plage vide) ; un lot en
journée reste `pending` avec le bon motif ; l'interactif part en journée.

### Étape 5 — Reprises sans tempête

Trouver **d'où vient le délai de ~4 min 50 s** (ni le délai de lecture de Matothèque, 1 800 s, ni
celui d'AIGUILLEUR, 1 800 s : une borne propre à un appel, à identifier). Puis : un échec
transitoire (500, 503, 429, délai dépassé) remet le job **en fin de son étape** avec un report
croissant et un nombre d'essais borné, au lieu d'un échec définitif suivi d'une relance immédiate
qui provoque un nouveau changement de modèle. Un « réessaie plus tard » d'AIGUILLEUR est un report,
pas une erreur.

*Critères* : test du calcul de report ; un job en échec transitoire ne repart pas avant son délai ;
au-delà du nombre maximal d'essais, il passe `failed` avec un message lisible dans « Tâches ».

### Étape 6 — Mesure après, et documentation

Refaire le relevé de l'étape 1 sur 24 h de prod et le comparer. Mettre à jour `CLAUDE.md` (flux
d'extraction : trois jobs ; piège « un job = un modèle »), `docs/ia-locale-pc-game.md`, la ROADMAP,
et **prévenir la session AIGUILLEUR** (la forme du trafic change : paquets d'embeddings, `X-AI-Usage`).

*Critères* : chargements de modèle par jour divisés au moins par 10 ; zéro erreur 500 par délai
dépassé sur 24 h ; documentation à jour.

## 4. Ce qu'on ne sait pas encore

- L'origine exacte du délai de ~4 min 50 s (étape 5).
- Si la vision doit rester dans l'étape « contenu » ou devenir une étape à part (le modèle vision
  ne sert qu'aux documents sans texte ; à trancher sur les chiffres de l'étape 1).
- Le bon délai maximal avant de changer d'étape (20 min proposé), à régler sur les mesures.
