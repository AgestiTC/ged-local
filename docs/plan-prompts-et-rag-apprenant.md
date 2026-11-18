# Plan — Gestion des prompts et RAG qui apprend

> **État au 18/11/2026** : **A1 et A2 livrés** (registre des prompts, lecteur JSON unique — v1.175.x) ; **A3 terminé hors consignes communes** (v1.199.0 : liste fermée de catégories ; v1.200.0 : plus aucun appel en « autre » ; A3c : les 26 prompts écrits en dur migrés dans le registre `services/prompts.py`, texte envoyé identique à l'octet près — `tests/test_prompts_a3c.py` contre la capture d'avant migration) ; outil de mesure B0 codé, jeu de questions validé hors dépôt (le point zéro attend un jeton). **A4-A5 livrés** (écran Paramètres › Prompts : versions `prompts_versions` servies à chaud aux 2 processus, contrat vérifié à l'enregistrement, « Essayer » et « Faire relire » sur l'IA locale — branche `feat/prompts-a4a5`). Reste : consignes communes, A6, B1 et suivants.

> **Statut** : plan validé, rien n'est codé (13/11/2026) — décisions Q1 à Q7 tranchées (§ 5). Demande de Thomas relayée par la session
> AIGUILLEUR : instruire deux pistes, (A) la gestion des prompts, (B) un RAG « qui apprend ».
>
> **Pourquoi dans Matothèque et pas dans l'AIGUILLEUR** : la passerelle relaie les corps de requête
> sans les réécrire (seul `model` peut changer). Choisir un prompt ou injecter des extraits, c'est
> réécrire ce que le client envoie : ça appartient au client. Côté AIGUILLEUR, rien ne change ;
> un nouvel usage (ex. `reclassement`) ne demanderait qu'une entrée dans sa table des intentions.
>
> **Relevé** : lecture du code de `feat/ia-geco` (≈ `main` v1.171), références `fichier:ligne`.

---

## 1. État des lieux

### 1.1 Prompts

- **Une trentaine de prompts en dur**, dans ~25 fichiers : constantes de module
  (`PROMPT_ENRICHISSEMENT` `services/extraction.py:40`, `PROMPT_COMPRENDRE` /
  `PROMPT_EXTRAIRE` `services/qa_service.py:37/50`, `SYSTEM_RAPPORT` et `CONSIGNE_GED_*`
  `routers/generate.py:123-137/377`, `PROMPT_REMPLISSAGE`, `PROMPT_PRESENTATION`…) et surtout
  des f-strings inline (comparatif, grille d'analyse, fiches candidats, jalons, dossiers, wiki…).
- **Tous passent par `OllamaService`** (`generate` `:325`, `generate_stream` `:390`,
  `chat_stream` `:448`) : un passage obligé existe déjà.
- **L'en-tête `X-AI-Usage` n'est posé que pour 5 usages** (vision, enrichissement, rapport, chat,
  embeddings). Les ~25 autres appels arrivent à l'AIGUILLEUR en « autre ». `routers/bookstack.py:229`
  n'indique même pas de modèle (il prend celui de l'environnement, pas `runtime_config`).
- **Trois prompts sont construits dans le frontend** (`utils/promptAnalyseReference.ts`,
  `IAInternetPage.tsx`, `AideDossiersPage.tsx`).
- **Deux mécanismes partiels existent** :
  - `prompts_presets` : presets **utilisateur** de la page Créer, sans version, **jamais lus par
    le backend** ; son seed cite des modèles supprimés (`mistral:latest`, `mixtral:latest`) ;
  - `consignes_versions` (`models/consigne.py`, `routers/consignes.py`) : **versionné, sans
    écrasement, origine = le code** — mais limité à 2 clés et consommé par le frontend seulement.
    **C'est le bon modèle, à généraliser.**
- **Duplications** : « Réponds UNIQUEMENT par un JSON » dans 15+ fichiers, **6 parseurs JSON
  tolérants** différents, « N'invente rien » ~20 fois, « en français » répété sans consigne
  système commune, 7 constructeurs de contexte `--- Document : … ---`, la règle « consignes en
  tête puis rappelées en fin » réimplémentée 3 fois.
- **Tests** : une dizaine de tests vérifient des morceaux de prompts (grille, comparatif, chat
  GED, relecture, vision) ; la plupart des prompts n'en ont aucun.
- **Code mort** : `services/report_generator.py` n'est importé nulle part.

### 1.2 RAG

- **Index** : `embeddings` en `halfvec(4096)` + préfixe Matryoshka `halfvec(1024)` indexé HNSW ;
  chunks de ~2 000 caractères ; remplacement complet par document.
- **Recherche hybride** (`routers/search.py`) : somme pondérée `0,4 × texte + 0,6 × sémantique`
  normalisée par le max du lot — **pas de RRF, pas de reclassement** ; le 4096-d ne sert pas au
  classement. **La formule est recopiée** dans `routers/assistant.py:75` et
  `services/qa_service.py:157`. Gate de pertinence absolu calibré (`services/pertinence.py`).
- **Les documents `absent` ne sont pas exclus de la recherche** (seul `doublon_de` l'est) : bug à
  corriger au passage.
- **Chat avec la GED** (`generate._contexte_ged` `:226-270`) : top 5 documents, **les 1 500
  premiers caractères de chaque document**, pas les chunks proches de la question. Une réponse
  dont l'information est en page 4 ne peut pas être trouvée.
- **Mode « Question »** : phase 1 livrée (2 intentions emploi/paie) ; cache de faits **en
  mémoire de processus** (500 entrées, perdu au redémarrage, distinct entre les 2 workers) ;
  `faits_emploi` (phase 2) **n'existe pas**.
- **Ce qui apprend déjà** :
  - l'**index suit les fichiers** (`sync_service` : nouveau, modifié, déplacé, absent, revenu ;
    réembedding sur changement d'empreinte) — **c'est acquis** ;
  - `grille_apprise` mémorise une structure validée et la réutilise sans IA ;
  - `idees_evolution` propose des prompts à enregistrer à partir des rapports ;
  - `ia_echecs` trace les réponses inexploitables par modèle.
- **Ce qui manque** : aucun retour utilisateur (pas de 👍/👎, pas de « ce document n'est pas
  pertinent »), conversations seulement dans le `localStorage` du navigateur, réponses du chat et
  du mode Question non conservées, corrections manuelles des métadonnées **sans trace** (et
  écrasées au prochain réenrichissement), **aucun jeu de questions de référence ni métrique**.

---

## 2. Piste A — Gestion des prompts

### 2.1 Trois familles, trois traitements

| Famille | Exemples | Qui les écrit | Traitement |
|---|---|---|---|
| **Prompts système** | enrichissement, vision, comprendre / extraire, consignes GED, grille, comparatif | le code | **registre versionné** (§ 2.2) |
| **Presets utilisateur** | « Résumé exécutif », prompts enregistrés de la page Créer | l'utilisateur | `prompts_presets` tel quel ; ajouter la version et nettoyer le seed |
| **Prompts portés par un objet** | `regroupements.prompt`, `rapports.prompt`, ressources « prompt » | l'utilisateur, dans l'objet | inchangés |

### 2.2 Le registre (généraliser `consignes_versions`)

- **Une clé par prompt** : `enrichissement`, `vision`, `qa.comprendre`, `qa.extraire`,
  `chat.ged.extraits`, `chat.ged.vide`, `rapport.systeme`, `grille.critere`, `comparatif.colonnes`…
  et des **fragments communs** : `commun.json_strict`, `commun.francais`,
  `commun.ne_rien_inventer`.
- **L'origine reste dans le code** (version 0, revue et testée par git). La base ne porte que les
  versions modifiées depuis l'interface ; on revient à l'origine en un clic. **Jamais
  d'écrasement** : chaque enregistrement crée une version (comme `consignes_versions`).
- **Contrat déclaré par clé** : variables obligatoires (`{texte}`, `{nom}`…), format de sortie
  (JSON + clés attendues, ou texte), usage IA (`X-AI-Usage`), modèle recommandé, longueur max.
  **Une version qui casse le contrat est refusée à l'enregistrement** (variable manquante,
  accolade orpheline).
- **Une seule fonction pour s'en servir** : `prompts.rendre(cle, **variables)` renvoie le texte
  composé (fragments + gabarit) **et** l'usage à poser ; `OllamaService` reçoit la clé et pose
  `X-AI-Usage` lui-même.
- **La clé de prompt n'est pas l'usage.** La clé est fine (une par fonction : `comparatif.colonnes`,
  `jalon`…) ; l'usage est une **famille de besoin de modèle**, liste courte et stable, convenue
  avec l'AIGUILLEUR le 13/11 : `chat`, `enrichissement`, `vision`, `embeddings`, `rapport`,
  `resume`, `analyse` (comparatif, grille, fiches, recommandation). « autre » reste possible, et
  sa baisse dans le journal de l'AIGUILLEUR mesure l'avancement d'A3. Un usage nouveau n'a pas à
  être déclaré à la passerelle tant que Matothèque nomme le modèle dans la requête. Le détail par
  fonction reste dans le journal de Matothèque (clé + version), pas dans `X-AI-Usage`.
- **Lecture à chaud** comme `runtime_config` (cache court rafraîchi) : modifier un prompt depuis
  Paramètres **ne demande pas de redéploiement**, et les 2 workers voient la même version.
- **Traçabilité** : chaque appel journalise `cle` + `version` (dans `ia_echecs`, les jobs, et les
  réponses conservées de la piste B). On peut alors comparer le taux d'échec d'une version à
  l'autre.

### 2.3 Ce qui va avec

- **Un parseur JSON unique** (`utils/json_ia.py`) à la place des 6 ; les lecteurs spécialisés
  (critères, valeurs, recommandation) gardent leur validation par-dessus.
- **Un constructeur de contexte unique** (`--- Document : nom ---`, budget de caractères, consignes
  en tête et rappelées en fin) à la place des 7.
- **Les prompts du frontend redescendent dans le backend** (le frontend envoie une clé et des
  variables, plus un texte).
- **Écran Paramètres › Prompts** : liste par usage, version active, historique, différence entre
  deux versions, « revenir à l'origine », bouton **« Faire relire par l'IA »** (déjà codé :
  `relecture_prompt.py`) et **« Essayer »** sur un document choisi, avant d'activer.
- **Tests** : un test par clé vérifie que l'origine respecte son contrat ; les tests existants
  qui comparent des morceaux de texte passent par le registre.

### 2.4 Étapes

| # | Étape | Acceptation |
|---|---|---|
| A1 | Registre + fragments communs + `rendre()` ; migrer les **5 prompts les plus utilisés** (enrichissement, vision, qa ×2, consignes GED) | sorties identiques à l'octet près avant/après pour ces 5 clés ; `X-AI-Usage` posé |
| A2 | Parseur JSON unique et constructeur de contexte unique | les tests de grille, comparatif, chat GED passent sans modification de comportement |
| A3 | Migrer les ~25 autres prompts vers les 7 usages (`report_generator.py` déjà supprimé en v1.175.3) ; **liste fermée de catégories** dans le prompt `enrichissement` + regroupement des catégories existantes (voir ci-dessous) | « autre » quasi absent du journal de l'AIGUILLEUR sur 24 h ; plus de nouvelle catégorie hors liste |

> **Constat du 13/11/2026 (relevé des catégories en prod)** : l'enrichissement invente ses
> catégories, qui se dispersent — `livre audio` / `livre_audio` / `livre-audio`, `presentation` /
> `présentation`, `image` / `photo` / `photographie` / `document photographique` / `document visuel`,
> `audio` / `document audio` / `document sonore` / `son`, `manuel` / `manuel d'utilisation` /
> `manuel utilisateur`, `roman` / `roman policier` / `policier`… Le filtre par catégorie de la GED en
> est fragmenté. À faire en A3 : une liste fermée dans le prompt (et refus d'une catégorie hors
> liste à la lecture), puis une table de correspondance appliquée aux fiches existantes, en
> simulation d'abord. **Attention** : les catégories `candidature`, `CV`, `lettre de motivation`,
> `lettre de candidature` existent — elles restent hors de tout jeu de test.

> **État de B0 (13/11/2026)** : outil livré (`scripts/mesurer_rag.py`, `backend/utils/mesure_rag.py`).
> Jeu de 30 questions validé par Thomas, rangé HORS DU DÉPÔT :
> `C:\Users\User\Documents\code-claude-\matotheque-mesures\rag-jeu-reference.json`. **Point zéro pas
> encore mesuré** : la recherche en prod exige un jeton d'automate (401 sans).
| A4 | Écran Paramètres › Prompts (lecture, historique, origine) | on voit la version active de chaque clé, par les deux routes (https et http) |
| A5 | Édition, contrat vérifié, « Essayer », « Faire relire » | une version qui casse le contrat est refusée ; une version valide est servie aux 2 workers en moins de 5 s |
| A6 | Rapatrier les prompts du frontend ; `prompts_presets` versionné, seed nettoyé | aucun texte de prompt dans `frontend/src` hors presets utilisateur |

---

## 3. Piste B — Un RAG qui apprend

### 3.1 Ce que « apprendre » veut dire ici

Les poids du modèle ne bougent pas. Un RAG apprend **par ce qu'il garde** : un index qui suit
les documents, des retours qui corrigent le classement, des réponses validées qu'on retrouve, des
faits extraits qu'on ne recalcule pas. **Et il faut le mesurer** : sans jeu de référence, on ne
saura pas s'il apprend ou s'il dérive.

### 3.2 Les briques, dans l'ordre

**B0 — Mesurer d'abord.** Un **jeu de questions de référence** (30 à 50 au départ) : question,
documents attendus, éléments de réponse attendus. Un script (puis un job) calcule le rappel à 5
et 10, le rang moyen du premier bon document (MRR), et — pour le chat — si la réponse cite le bon
document. On part des 8 requêtes témoins de `tests/test_pertinence.py`. Résultat conservé à
chaque passage : **c'est la courbe qui dira si le RAG apprend.** Les questions sont fictives ou
portent sur des documents non sensibles (règle : jamais d'offres ni de documents de candidats).

**B1 — Assainir la récupération** (pas de l'apprentissage, mais le prérequis) :
- une **seule fonction de recherche hybride** au lieu de 3 copies ;
- **exclure les documents `absent`** ;
- dans le chat, injecter **les passages les plus proches de la question** (chunks, comme le fait
  déjà `grille_analyse.passages_pertinents`) au lieu des 1 500 premiers caractères ;
- essayer la fusion **RRF** contre la somme pondérée actuelle, **mesurée par B0**.

**B2 — Garder la trace.** Table `rag_questions` côté serveur : question, réglages, documents et
passages fournis, modèle, clé et version de prompt, réponse, durée. Les conversations ne vivent
plus seulement dans le `localStorage`. Rétention réglable (ex. 180 jours), purge par
l'utilisateur, tout reste local.

**B3 — Recueillir les retours.** Sur chaque réponse : 👍 / 👎 et « corriger la réponse » ; sur
chaque source citée : « pertinent / pas pertinent ». Table `rag_retours`. Coût pour
l'utilisateur : un clic, jamais obligatoire.

**B4 — Réutiliser les retours dans le classement.** Pour une nouvelle question, retrouver les
questions passées **proches** (cosinus de leurs embeddings) et appliquer un bonus aux documents
jugés pertinents, une pénalité à ceux jugés hors sujet. Effet borné (un retour ne fait pas
disparaître un document), réversible, et **gardé seulement si B0 montre un gain**.

**B5 — Réponses validées = connaissances.** Une réponse 👍 ou corrigée devient une **fiche
réponse** interrogeable, avec ses sources. Elle est proposée en tête quand une question proche
revient (« déjà répondu le …, d'après … »). **Elle est invalidée automatiquement** quand une de
ses sources change d'empreinte ou passe `absent` — c'est ce qui la distingue d'un cache.

**B6 — Faits persistés.** Le cache `_FAITS_CACHE` devient une table `faits_documents` (la
`faits_emploi` du plan Questions, généralisée) : faits extraits par document, **indexés par
empreinte du document** et par version du prompt d'extraction. Partagée entre les 2 workers,
survit au redémarrage, invalidée par `_update_version`.

**B7 — Corrections de métadonnées tracées.** Une catégorie ou des étiquettes corrigées à la main
(`PATCH /documents/{id}/metadata`) sont marquées « corrigé par l'utilisateur » et **ne sont plus
écrasées** par un réenrichissement. Elles deviennent aussi des exemples pour l'enrichissement
(quelques corrections proches injectées comme exemples dans le prompt `enrichissement`, via le
registre de la piste A).

**B8 — Reclassement (optionnel).** Un modèle de reclassement sur les 20 premiers candidats,
**seulement si B0 montre que B1 à B4 ne suffisent pas**. Demanderait un nouvel usage
`reclassement` à l'AIGUILLEUR (une entrée dans sa table des intentions) et du temps de carte
graphique.

### 3.3 Étapes

| # | Étape | Acceptation |
|---|---|---|
| B0 | Jeu de référence + mesure | une valeur de référence (rappel@5, MRR) enregistrée sur la prod actuelle |
| B1 | Recherche unique, `absent` exclus, passages au lieu des débuts de documents, essai RRF | B0 ≥ référence ; une question dont la réponse est loin dans un document est trouvée |
| B2 | Journal des questions côté serveur | chaque question du chat et du mode Question est retrouvable avec ses sources et sa version de prompt |
| B3 | Retours 👍/👎 et pertinence des sources | un retour s'enregistre en un clic, par les deux routes d'accès |
| B4 | Bonus / pénalité appris | B0 progresse sur les questions ayant reçu des retours, sans régresser sur les autres |
| B5 | Fiches réponses validées, invalidées au changement de source | une fiche disparaît quand sa source change ; une question proche la retrouve |
| B6 | `faits_documents` persistée | le mode Question ne rappelle pas le LLM pour un document déjà lu, même après redémarrage |
| B7 | Corrections de métadonnées protégées et réutilisées | un réenrichissement ne défait plus une correction |
| B8 | Reclassement (si besoin prouvé) | gain mesuré par B0 supérieur à son coût en temps |

---

## 4. Ordre et dépendances

1. **A1** d'abord : le registre donne la clé et la version de prompt dont B2 a besoin, et règle
   l'en-tête `X-AI-Usage` pour l'AIGUILLEUR.
2. **B0 puis B1** : mesurer, puis réparer la récupération — c'est le plus gros gain de qualité
   immédiat, avant toute « mémoire ».
3. **A2-A3** et **B2-B3** en parallèle.
4. **B6, B7** (indépendants, utiles tout de suite) ; **B4, B5** quand des retours existent ;
   **A4-A6** au fil de l'eau ; **B8** seulement sur preuve.

---

## 5. Décisions (tranchées par Thomas le 13/11/2026, toutes conformes aux recommandations)

| Réf | Question | Recommandation |
|---|---|---|
| Q1 | Les prompts système modifiables depuis l'interface, sans redéploiement ? | ✅ **Oui**, versionnés, contrat vérifié, origine dans le code |
| Q2 | Qui peut les modifier ? | ✅ Rôle **administrateur** seulement ; les utilisateurs gardent leurs presets |
| Q3 | Conserver les questions et réponses côté serveur (B2) ? | ✅ **Oui**, 180 jours par défaut, purge possible |
| Q4 | Retours 👍/👎 ouverts à tous les utilisateurs ? | ✅ Oui pour donner un retour ; seul l'admin voit le tableau des retours |
| Q5 | Une réponse validée par un utilisateur sert-elle aux autres (B5) ? | ✅ Oui **si** l'autre utilisateur a accès à toutes ses sources (à aligner avec les droits par partage) |
| Q6 | Qui écrit le jeu de référence (B0) ? | ✅ Claude propose 30 questions sur des documents non sensibles, Thomas les valide |
| Q7 | Reclassement par un modèle dédié (B8) ? | ✅ Pas maintenant ; décider sur mesure |

---

## 6. Risques

- **Un prompt modifié casse une fonction en silence.** Parade : contrat vérifié à
  l'enregistrement, « Essayer » avant activation, version tracée dans `ia_echecs`, retour à
  l'origine en un clic.
- **Un RAG qui « apprend » de mauvais retours** (un 👎 par erreur, un document mal classé).
  Parade : effet borné et réversible, mesure B0 à chaque passage, tableau des retours pour l'admin.
- **Une fiche réponse périmée.** Parade : invalidation par empreinte des sources (B5).
- **Données personnelles dans le journal** (questions sur les salariés, la santé…). Parade :
  tout reste local, rétention bornée, purge ; même règle que pour les documents (jamais d'offres
  ni de documents de candidats dans les jeux de test).
- **Sessions concurrentes** dans ce dépôt : `generate.py`, `search.py`, `extraction.py` et
  `ollama_service.py` sont touchés par d'autres chantiers (lots IA) — une branche par étape et
  prévenir avant.
