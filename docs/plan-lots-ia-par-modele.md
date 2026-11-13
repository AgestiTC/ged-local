# Plan — lots IA groupés par modèle (désaturer la carte graphique de PC-GAME)

> **Statut** : validé par Thomas le 12/11/2026 (« go »), plage des lots 22h00 → 06h00 par défaut.
> Étape 1 en cours.
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
- les embeddings partent **un morceau de texte par appel** (`/api/embeddings`), d'où le volume ;
- **les replis de modèle aggravent la saturation** : sur un appel en échec (délai dépassé compris),
  l'enrichissement et la vision basculent sur « le modèle suivant installé » → un quatrième modèle
  se charge ; côté embeddings, un seul morceau en échec fait passer **tout le reste du document**
  sur le modèle de repli, qui n'a pas la même dimension (cohérence des vecteurs à vérifier) ;
- **la vision fait jusqu'à deux passes par page** (lecture du texte, puis description si rien n'en
  sort), plafonnées à 10 pages : un PDF de photos = 20 appels.

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

### Étape 0 — Tout de suite, sans code (Thomas, dans l'interface)

Bouton **« Pause IA »** en journée et `concurrence_gpu` à **1** dans les Paramètres, le temps que
les étapes 3 et 4 soient livrées. À défaire ensuite (l'étape 4 remplace la pause manuelle ;
l'étape 3 rend de nouveau utile une concurrence de 2).

### Étape 1 — Mesure de référence et en-tête `X-AI-Usage`

Ajouter `X-AI-Usage` à `entetes_projet()` via une `ContextVar` posée au point d'appel (embedding,
vision, enrichissement, rapport, chat), sur le modèle de `priorite_ia`. Consigner une **mesure de
référence** datée dans `docs/mesures/` : chargements de modèle par jour, appels par usage, nombre
d'erreurs 500 et de dépassements de délai.

*Critères* : chaque appel IA porte un `X-AI-Usage` non vide (test) ; une pile de test ne mélange pas
son trafic à la prod (`AI_PROJECT`) ; relevé de référence écrit.

### Étape 2 — Moins d'appels : embeddings par paquets, vision en une passe

Remplacer l'appel unitaire `/api/embeddings` par `/api/embed` (champ `input` = liste de morceaux),
par paquets bornés (ex. 32 morceaux), dans `embedding_service.embed_document`. **Pas de réindexation** :
`/api/embed` renvoie des vecteurs normalisés, et la recherche et les doublons utilisent la distance
cosinus (`<=>`), insensible à la norme — à **revérifier** pour toute autre requête vectorielle avant
de livrer. Repli sur l'appel unitaire si le serveur refuse `/api/embed`. Garder `/api/*`, jamais
`/v1/*` (options perdues en silence).

**Vision** : une seule demande par page (« transcris le texte ; s'il n'y en a pas, décris l'image »)
au lieu d'une passe de lecture puis d'une passe de description (`ExtractionService._ocr_fallback`).
La sentinelle « (aucun texte) » et le plafond de 10 pages sont conservés.

*Critères* : même nombre de vecteurs, mêmes dimensions (4096 + préfixe 1024) ; un document de 100
morceaux = ≤ 4 appels ; résultats de recherche inchangés sur un jeu de test ; un PDF image de 10
pages = 10 appels vision au plus.

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

**État (13/11/2026)** : faite, après l'étape 5. Réglages `lots_ia_plage_debut` / `lots_ia_plage_fin`
(« HH:MM », heure de Paris ; fonctions pures `runtime_config.lire_heure` et `dans_plage`). Le worker
retient les lots quand `runtime_config.lots_ia_suspendus()` est vrai (pause IA **ou** hors plage) ;
motif `hors_plage` dans `file_ia`, voyant dans l'en-tête, réglage dans Paramètres › Maintenance.
**Écart voulu** : défaut VIDE (à toute heure) et non 22h00 → 06h00 — un défaut actif aurait arrêté
l'indexation de jour en prod dès le déploiement. Réglage incomplet ou illisible, ou fuseau
indisponible : pas de plage (on ne retient jamais les lots sur un doute).
Vérifié sur pile jetable avec le vrai worker : hors plage, un `ia_enrich` reste en attente pendant
qu'un rapport se termine ; dans la plage, il est pris dans les 10 s.

### Étape 5 — Reprises sans tempête

Trouver **d'où vient le délai de ~4 min 50 s** (ni le délai de lecture de Matothèque, 1 800 s, ni
celui d'AIGUILLEUR, 1 800 s : une borne propre à un appel, à identifier). Puis : un échec
transitoire (500, 503, 429, délai dépassé) remet le job **en fin de son étape** avec un report
croissant et un nombre d'essais borné, au lieu d'un échec définitif suivi d'une relance immédiate
qui provoque un nouveau changement de modèle. Un « réessaie plus tard » d'AIGUILLEUR est un report,
pas une erreur.

**Replis de modèle** : ne basculer sur un autre modèle que si le modèle demandé est **absent**
(404, « model not found »), jamais sur un échec transitoire — sinon la saturation fait charger un
modèle de plus (`_enrich`, `_ocr_fallback`). **Embeddings** : un document n'a jamais de vecteurs de
deux modèles ; un échec transitoire reporte le job entier au lieu de passer le reste du document
sur le modèle de repli.

*Critères* : test du calcul de report ; un job en échec transitoire ne repart pas avant son délai ;
au-delà du nombre maximal d'essais, il passe `failed` avec un message lisible dans « Tâches » ;
un délai dépassé ne déclenche aucun appel à un autre modèle (test) ; un document n'a qu'un seul
`modele_embedding`.

**État (12/11/2026)** : faite, avant l'étape 4. Le délai de ~4 min 50 s est celui de la passerelle
(premier octet attendu 300 s, réponse 504). Classement des échecs en un seul endroit
(`services/classement_echecs.py` : passager, modèle absent, définitif) ; seule l'exception typée
`EchecPassager`, levée aux points d'appel de l'IA, est reportée par le worker
(`job_worker._gerer_incident_passager`, écriture atomique, colonnes `jobs.essais` et
`jobs.pas_avant`). Fusion avec l'IA GECO : un refus ou un échec GECO ne se rejoue jamais
(`ollama_service._rejouable`), sinon le contenu repartirait une seconde fois.
Vérifié sur PostgreSQL jetable : colonnes ajoutées sur une base créée par la v1.168.0, ordre de
prise de tâche, report, abandon, annulation. **Non vérifié** : un 504 réel traversant toute la
chaîne (couvert par les tests à transport simulé seulement).

### Étape 6 — Mesure après, et documentation

Refaire le relevé de l'étape 1 sur 24 h de prod et le comparer. Mettre à jour `CLAUDE.md` (flux
d'extraction : trois jobs ; piège « un job = un modèle »), `docs/ia-locale-pc-game.md`, la ROADMAP,
et **prévenir la session AIGUILLEUR** (la forme du trafic change : paquets d'embeddings, `X-AI-Usage`).

*Critères* : chargements de modèle par jour divisés au moins par 10 ; zéro erreur 500 par délai
dépassé sur 24 h ; documentation à jour.

**État (13/11/2026)** : faite en partie. Relevé : [mesures/lots-ia-apres-2026-11-13.md](mesures/lots-ia-apres-2026-11-13.md).
Sur les 9 heures de charge qui ont suivi la livraison de l'étape 3 (12/11, 11 h à 20 h) : 64
chargements de modèle pour 17 709 appels, contre 1 888 pour 62 005 la veille (÷ 8 à appels égaux,
÷ 29 en valeur absolue), et plus aucune erreur 500 par délai dépassé. Documentation mise à jour
(`CLAUDE.md`, `docs/ia-locale-pc-game.md`, ROADMAP). **Reste** : la file s'est vidée le 12/11 à
20 h, donc pas de relevé sur 24 h sous charge ; la plage horaire et les reprises différées n'ont
pas encore servi en production ; la ventilation par `X-AI-Usage` demande le journal de la passerelle.

## 3-bis. Orchestration — une commande par étape

Découpage produit par `/ecc:plan-orchestrate` le 12/11/2026. Une commande par étape, à lancer
**dans l'ordre et une par une** : la 3 s'appuie sur les mesures de la 1, la 5 sur les jobs créés par
la 3. La commande est `/orchestrate` (compétence du projet ; `/ecc:orchestrate` n'existe pas dans
ECC 2.2.2). Cocher l'étape dans la ROADMAP après chaque commit.

| # | Étape | Chaîne d'agents |
|---|---|---|
| 1 | Mesure de référence et en-tête `X-AI-Usage` | `ecc:tdd-guide,ecc:python-reviewer` |
| 2 | Embeddings par paquets, vision en une passe | `ecc:tdd-guide,ecc:database-reviewer,ecc:python-reviewer` |
| 3 | Pipeline en étapes, file collante par étape | `ecc:architect,ecc:tdd-guide,ecc:database-reviewer,ecc:python-reviewer` |
| 4 | Plage horaire des lots | `ecc:tdd-guide,ecc:python-reviewer,ecc:typescript-reviewer` |
| 5 | Reprises sans tempête | `ecc:tdd-guide,ecc:python-reviewer` |
| 6 | Mesure après, et documentation | `ecc:doc-updater` |

**Étape 1**

```bash
/orchestrate custom "ecc:tdd-guide,ecc:python-reviewer" "[Plan: docs/plan-lots-ia-par-modele.md#step-1] Ajouter l'en-tête X-AI-Usage à entetes_projet() (backend/services/ollama_service.py) via une ContextVar posée au point d'appel (embedding, vision, enrichissement, rapport, chat), sur le modèle de priorite_ia ; écrire un relevé de référence daté dans docs/mesures/ (chargements de modèle par jour, appels par usage, erreurs 500). Acceptance: chaque appel IA porte un X-AI-Usage non vide (test) ; AI_PROJECT continue de séparer une pile de test de la prod ; relevé écrit sans adresse IP"
```

**Étape 2**

```bash
/orchestrate custom "ecc:tdd-guide,ecc:database-reviewer,ecc:python-reviewer" "[Plan: docs/plan-lots-ia-par-modele.md#step-2] Dans embedding_service.embed_document et OllamaService.embed, envoyer les morceaux par paquets bornés (ex. 32) à /api/embed (champ input = liste), avec repli sur l'appel unitaire /api/embeddings si refusé ; rester sur /api/*, jamais /v1/* ; revérifier que toutes les requêtes vectorielles utilisent la distance cosinus (vecteurs désormais normalisés). Vision (ExtractionService._ocr_fallback) : une seule demande par page (texte, sinon description) au lieu de deux passes. Acceptance: mêmes vecteurs en nombre et dimensions (4096 + préfixe 1024) ; 100 morceaux = 4 appels au plus ; un PDF image de 10 pages = 10 appels vision au plus"
```

**Étape 3**

```bash
/orchestrate custom "ecc:architect,ecc:tdd-guide,ecc:database-reviewer,ecc:python-reviewer" "[Plan: docs/plan-lots-ia-par-modele.md#step-3] Découper le pipeline (ExtractionService.analyze_existing, process_file, reprendre_contenu_stocke) en trois jobs chaînés : ia_contenu (Tika + vision si texte vide), ia_enrich, ia_embed ; chaque étape enfile la suivante, rejouable sans doublon. Dans job_worker._claim, pour les lots GPU, rester sur la même étape tant qu'il en reste, changer si vide ou après un délai maximal réglable ; état de l'étape courante en base (2 workers uvicorn) ; interactif et priorité forcée inchangés. Acceptance: 50 documents en attente = un changement de modèle par étape au plus (test) ; un échec n'arrête pas les autres documents ; analyze, enrich et reprise_texte restent acceptés"
```

**Étape 4**

```bash
/orchestrate custom "ecc:tdd-guide,ecc:python-reviewer,ecc:typescript-reviewer" "[Plan: docs/plan-lots-ia-par-modele.md#step-4] Ajouter un réglage runtime « lots IA autorisés de … à … » (défaut 22h00-06h00, vide = toujours, fuseau Europe/Paris, plage à cheval sur minuit) ; hors plage, job_worker applique interactifs_seulement comme pour la pause IA ; file_ia affiche le motif « en attente de la plage de nuit » ; champ dans la page Paramètres. Acceptance: fonction pure « dans la plage ? » testée (minuit, plage vide) ; un lot en journée reste pending avec le bon motif ; une tâche interactive part en journée"
```

**Étape 5**

```bash
/orchestrate custom "ecc:tdd-guide,ecc:python-reviewer" "[Plan: docs/plan-lots-ia-par-modele.md#step-5] Identifier d'où vient le délai d'environ 290 s qui finit en erreur 500 (ni le délai de lecture Matothèque ni celui d'AIGUILLEUR, 1800 s chacun). Puis : un échec passager (500, 503, 429, délai dépassé, « réessaie plus tard » d'AIGUILLEUR) remet le job en fin de son étape avec un report croissant et un nombre d'essais borné. Repli sur un autre modèle seulement si le modèle est absent, jamais sur un échec passager (_enrich, _ocr_fallback, embed_document) ; un document n'a jamais deux modèles d'embedding. Acceptance: calcul du report testé ; un délai dépassé n'appelle aucun autre modèle (test) ; au-delà du maximum d'essais le job passe failed avec un message lisible dans « Tâches »"
```

**Étape 6**

```bash
/orchestrate custom "ecc:doc-updater" "[Plan: docs/plan-lots-ia-par-modele.md#step-6] Refaire sur 24 h de prod le relevé de l'étape 1 et le comparer dans docs/mesures/ ; mettre à jour CLAUDE.md (flux d'extraction en trois jobs, piège « un job = un modèle »), docs/ia-locale-pc-game.md et ROADMAP.md ; rédiger la note pour la session AIGUILLEUR (paquets d'embeddings, X-AI-Usage). Acceptance: chargements de modèle par jour divisés par 10 au moins ; zéro erreur 500 par délai dépassé sur 24 h ; aucun document poussé ne contient d'adresse IP ni de détail d'infrastructure"
```

## 3-ter. Signalé le 12/11, hors de ce chantier

- **ComfyUI est arrêté** (à la demande de Thomas) : les tuiles vidéo et musique sont injoignables
  jusqu'à sa prochaine ouverture de session.
- **Le conteneur de transcription occupe un cœur à 100 % en permanence**, sans rien journaliser :
  probablement une boucle à vide. Périmètre de la session transcription / PC-GAME, pas de Matothèque.

## 4. Ce qu'on ne sait pas encore

- L'origine exacte du délai de ~4 min 50 s (étape 5).
- Si la vision doit rester dans l'étape « contenu » ou devenir une étape à part (le modèle vision
  ne sert qu'aux documents sans texte ; à trancher sur les chiffres de l'étape 1).
- Le bon délai maximal avant de changer d'étape (20 min proposé), à régler sur les mesures.
