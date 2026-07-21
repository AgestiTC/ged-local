# ROADMAP — Matothèque

> GED locale intelligente (extraction Tika + IA Ollama + recherche sémantique
> pgvector), 100 % locale. Repo `AgestiTC/ged-local` · cible **NAS-MATO**
> (Synology, 192.168.42.200) · version courante **1.15.0**.

## Statut général

🟢 **Projet avancé** — socle technique complet et fonctionnel (extraction,
indexation, recherche hybride, GED, rapports, comparatif). La suite consiste à
couvrir les besoins métier prioritaires et à brancher les connecteurs cloud.

> **Déploiement prod** *(14/07/2026)* : **v1.15.0 en production** sur le **LXC « docker »
> (Proxmox, 192.168.42.83)**, images tirées du **registre Gitea** `git.agesti.fr/agestitc/docflow-*`
> (build+push manuel depuis Windows). Base d'indexation migrée (~56 k docs). Déploiement :
> `/opt/docflow/docker-compose.yml` + secrets Docker + `.env` (`DOCFLOW_VERSION`).
>
> **Légende des états** : `[ ]` à faire · `[~]` en cours · `[x]` fait.

---

## ✅ Acquis (déjà livré, ≤ v1.7.2)

- [x] Pipeline extraction tous formats (Tika) + enrichissement IA (Ollama)
- [x] Indexation de **dossiers surveillés** (`/api/folders`, scan, browse) + workflow n8n `folder-watcher`
- [x] **Recherche hybride** full-text (pg_trgm/tsvector) + sémantique (pondération 40/60)
- [x] Détection de **doublons exacts** (SHA256) à l'ingestion + `POST /documents/purge-duplicates`
- [x] GED : catégories, tags, résumés IA · filtres par catégorie
- [x] Rapports libres + remplissage de templates + **rapport comparatif multi-groupes**
- [x] Alignement modèle AgestiTC : VERSION, `/api/version` `/healthz` `/api/logs/tail`,
      Dockerfile non-root, CI build+verify, Dependabot, audit hebdo, hooks `.claude`

### Livré en v1.8.0 (taggé · CI → images GHCR)

- [x] **Docker de dev complet** « tout en conteneurs » (pattern NetSight) :
      `Dockerfile.dev` backend+frontend, `docker-compose.dev.yml` autonome, HMR, coexiste avec NetSight
- [x] **Doublons** : page dédiée + quarantaine `DOUBLON-MATOTEQUE` (cf. Phase 2)
- [x] **Paramètres — Services & modèles IA** : URLs Tika/Ollama/n8n **configurables en base**
      (éditables à chaud) + test connexion + statut live ; **liste des modèles dynamique**
      depuis Ollama + bouton rafraîchir (fin du hard-code)
- [x] **Administration des modèles IA** : détection MAJ (⚠️ digest vs registre) + mise à jour
      (`ollama pull` en streaming) depuis l'UI
- [x] **Sources de fichiers (local + SMB NAS)** : déclarer un serveur, lister ses partages SMB,
      parcourir avec **cases à cocher** (tout cocher/décocher), **indexer la sélection** ;
      identifiants **chiffrés (Fernet)** en base. ✅ validé sur le vrai NAS-MATO.
- [x] **Antivirus ClamAV** : scan des fichiers à l'indexation, fichier infecté **non indexé**
      (testé EICAR) ; statut dans le Header + Paramètres
- [x] Page **Doublons** simplifiée + section Sources unifiée (fin de la saisie manuelle / encart docker-compose)
- [x] **Catalogue universel** : extensions élargies (images, audio, vidéo, doc/ppt/xls, rar/7z…)
      et **configurables en base** (ajout perso) ; exclusion fichiers temp `~$` ; logs pysmb réduits
- [~] **Réorganisation d'arborescence par IA** *(plan phasé :
      [docs/plan-reorganisation-arborescence.md](docs/plan-reorganisation-arborescence.md))* — **EN COURS
      (branche `feature/reorganisation`)**. Phasage :
  - [x] **Phase 1 — Proposition + aperçu (virtuel, lecture seule)** : `POST /organize/propose`
        (IA → arbo + mapping + critères) + page « Réorganiser ». Aucun fichier déplacé, aucune écriture DB.
  - [x] **Phase 2 — Plan éditable + vue VIRTUELLE — livré (core)** : table `reorg_plan`
        {document_id, dossier_cible} ; `propose` **persiste** le plan ; `GET /organize/plan` +
        `POST /organize/plan/move` ; page Réorganiser **éditable en drag & drop** (glisser un doc
        vers un dossier, zone « nouveau dossier », reprise du plan au montage). **Aucun fichier
        déplacé** (100% réversible). Validé e2e (522 docs). Restes possibles : renommer/fusionner un
        dossier, navigation GED selon la vue virtuelle.
  - [x] **Phase 3 — Application PHYSIQUE (NAS/SMB) + undo — livré (dry-run validé)** : table
        `reorg_moves` (journal). `POST /organize/apply/dry-run` (simulation, rien déplacé) ;
        `POST /organize/apply` (job `reorg_apply` : `ensure_dir` + collisions `_(n)` + `move_file`
        + MAJ `chemin` + journal) ; `POST /organize/undo` (job `reorg_undo` : remet chaque fichier).
        Jamais de suppression ; **confirmation UI** ; page Réorganiser : Simuler · Appliquer au NAS ·
        Annuler la dernière. Dry-run validé (515/7). ⚠️ **Déplacement réel à tester sur un petit
        périmètre** (destructif mais réversible via Annuler).
  - [ ] **Phase 4 — Polish** : dry-run + rapport (n fichiers/conflits/volume), **tâche durable** (job,
        progression, reprise sur erreur) visible dans « Tâches »/Logs. Contrainte : conserver au
        minimum le **dossier parent** (cf. section dédiée plus bas).

---

## 🔎 Retours d'usage (suivi vivant)

> Consigné **au fil des questions/retours** pendant l'utilisation réelle, pour un suivi
> fiable des deux côtés. On coche/déplace au fur et à mesure.

### Session 2026-07-17 — Réindexation, indexation continue, observabilité

> Retours user du 17/07, numérotés comme dans la conversation.
> Plans : **[docs/plan-indexation-continue.md](docs/plan-indexation-continue.md)** (1 & 2) ·
> **[docs/plan-observabilite-logs.md](docs/plan-observabilite-logs.md)** (3 & 4).

- **⑤ Arbres à cases à cocher — ergonomie** *(livré 17/07)* :
  - [x] **🔴 « il a tout pris »** : l'Explorer **pré-cochait TOUS les dossiers** à chaque navigation
        (`cocherTout` auto) → indexer un partage entier alors qu'on voulait un dossier. **Défaut = rien
        de coché** ; l'utilisateur choisit. *(Constaté en direct : le partage était de toute façon déjà
        indexé — idempotence par hash, pas de doublon créé.)*
  - [x] **Cases devant les partages** *(idée user)* : cocher un partage l'indexe **en entier** d'un clic
        (sélection grossière), affinage ensuite via « Indexés → Gérer » (retrait). Bouton « Indexer N
        partage(s) entier(s) ».
  - [x] **Cascade parent → enfants** sur les arbres récursifs : cocher un dossier coche/décoche tout son
        contenu ; **case indéterminée** si sélection partielle. `IndexedFolders` (Gérer, arbre en mémoire)
        et `IndexedDocsTree` (Créer, cascade paresseuse via `treeFlat` + `flatCache` ; store `deselectMany`).
  - [x] **Position conservée au rafraîchissement** (`IndexedFolders`) : `charger(preserver)` garde
        sélection + dépliages + `scrollTop` au lieu de tout réinitialiser. **« Rafraîchir » honnête**
        (title : « relit l'index, ne rescanne PAS le NAS »).
  - [ ] **Vrai bouton « Réindexer source »** (rescan NAS d'un clic) = **Phase 1 du chantier ② indexation
        continue**. En attendant, le rescan d'un dossier se fait déjà par Explorer → dossier →
        « Indexer ce dossier » (propre maintenant que rien n'est pré-coché).

- **⑥ Corrections UX (retours user 18/07)** :
  - [ ] **🐞 % de progression faux dans le widget « Tâches »** : affiche `100 %` avec un compteur
        **`40047 / 34290 fichiers`** (fait **> total** → dépassement). Cause probable : (a) le **total**
        est l'estimation d'énumération SMB (sous-évaluée / figée), tandis que le **fait** additionne des
        fichiers de **plusieurs jobs/scopes** qui se chevauchent (mêmes dossiers re-walkés) sur un compteur
        de progression **partagé par source** (`_progression[source_id]`) ; (b) pas de borne `min(fait,total)`.
    - **Plan** : ① borner l'affichage à `min(fait, total)` et clamp le % à 100 (garde-fou immédiat) ;
      ② **progression par JOB** et non par source (chaque job a son propre total/fait) → le widget montre
      l'avancement réel de chaque scope au lieu d'un agrégat faussé ; ③ recompter le `total` en fin
      d'énumération (le walk découvre parfois plus de fichiers que l'estimation initiale) ; ④ afficher
      « énumération… » tant que le total n'est pas stabilisé (déjà partiellement fait via `phase`).
      Fichiers : `services/job_handlers.py` (miroir progression), `routers/sources.py` (`_progression`,
      `_prog_*`), `stores/jobsStore.ts` + `layout/JobsIndicator.tsx` (calcul/affichage du %).
  - [ ] **🎯 Navigation persistante en vue détail des Paramètres** : quand une section est ouverte
        (ex. *Sources & indexation*), le **fil d'ariane « Tous les paramètres / <section> »** ET la
        **barre de recherche** des paramètres doivent rester **au-dessus de la section** (aujourd'hui on
        « entre » dans une section et on perd l'accès rapide/recherche → il faut ressortir au tableau de bord).
    - **Plan** : dans `SettingsPage` (mode master-détail `active`/`sectionsVisibles`), sortir l'en-tête
      (breadcrumb + `<input recherche>`) du tableau de bord pour qu'il soit **rendu aussi en vue détail**,
      au-dessus de la `CollapsibleSection` active. Taper une recherche en vue détail → **revient au tableau
      de bord filtré** (ou filtre en place). Garder le bouton « ‹ Tous les paramètres » (retour). Composant :
      `pages/SettingsPage.tsx` (bloc en-tête recherche + `secProps`/`active`).

- **① Réindexation manuelle utilisable** — voir aussi « Indexation dynamique » plus bas.
  - [x] **1a — « Rafraîchir » ne fait rien** *(livré 17/07)* : le bouton relit les **compteurs** depuis
        l'index, il ne relance **aucun scan** → sans changement en base, rien ne bouge. Renommé
        **« Rafraîchir les compteurs »** + `title` explicite. Le vrai besoin (bouton **« Réindexer »**)
        = Phase 1 du plan.
  - [x] **1b — « Aucun partage » sur une source déjà montée** *(livré 17/07)* : le frontend **jetait le
        message du backend** (`catch { toast.error('Exploration impossible') }`) → l'utilisateur voyait un
        « Aucun partage (ou identifiants requis) » qui n'apprend rien, alors que la garde `_secret_clair`
        renvoyait déjà un HTTP 400 explicite. Fix : `extractApiError` exporté depuis `api/index.ts`, utilisé
        par **tous** les `catch` de `SourcesManager` ; cause affichée **dans le panneau** + lien
        **« Modifier la source (re-saisir le mot de passe) »**. ⚠️ **Action prod** : clé Fernet rotée →
        re-saisir une fois le mot de passe du NAS.
- [ ] **② Indexation continue** *(chantier — « faut le mettre en place oui ! »)* : **décision = scan
      incrémental dans le WORKER, pas n8n**. Diff NAS ↔ index (nouveau / modifié / supprimé / **déplacé**),
      hash calculé **seulement** sur les candidats (`taille`+`date_modif` d'abord). Phasage 1→4 dans le plan.
- [ ] **③ « Ré-analyser » : erreur affichée mais RIEN dans les logs** : l'endpoint `analyze-batch` ne logue
      **qu'en cas de succès**. **Écarté par la mesure** : la requête de sélection prend **72 ms** (pas un
      timeout SQL). ⚠️ **Diagnostic bloqué tant que ④ n'est pas fait** — et il manque le **texte exact** de
      l'erreur. → Phase 1 du plan observabilité.
- [~] **④ Une vraie page Logs (debug réel et rapide)** — **PHASE 1 LIVRÉE 21/07 (v1.22.0)** :
      la prod n'est **plus aveugle**. Cause trouvée en 2 s grâce au nouveau diagnostic :
      `/opt/docflow/logs` appartenait à **root** → conteneur uid 10001 → `Errno 13 Permission denied`
      → bascule silencieuse sur stdout. Fix : `chown -R 10001:10001 logs` + restart.
      **Livré** : `logger.etat_fichier_log()` (actif/chemin/erreur) · `/logs/tail` renvoie un
      `diagnostic` (existe / taille / lisible / **aveugle** / erreur_handler / **conseil**) et
      distingue absent≠illisible≠vide · **RotatingFileHandler 10 Mo × 3** (le log montait à 261 Mo,
      778 Mo en dev = 3e « disque plein » évité) · tail **par la fin** (0,02 s vs 261 Mo en RAM) ·
      **erreurs 4xx enfin journalisées** (`StarletteHTTPException`) · **bandeau rouge** dans la page
      Logs nommant la cause. **Reste (Phase 2)** : table `audit_events` + `correlation_id`.
      *(Constat initial ci-dessous, conservé pour l'historique.)*
- [ ] **④ (constat d'origine)** — **la prod est AVEUGLE, mesuré le 17/07** :
      `GET /api/logs/tail` → `{"lines":[],"count":0}` : **zéro log applicatif**.
      **⚠️ RECONFIRMÉ EN PROD 17/07 (soir)** : panneau *Paramètres → Logs → « Debug — log applicatif »* affiche
      **« Aucune ligne de log (fichier non configuré ?) »** — le symptôme est visible pour l'utilisateur.
      Trois causes empilées :
  - `logger.py` **bascule en silence sur stdout** si le fichier n'est pas écrivable (son propre commentaire
    prévoit le cas « conteneur non-root sur bind-mount non chown'é » — le LXC tourne en UID 10001) ;
  - `_tail()` renvoie `[]` si le fichier est **absent** → **indistinguable** de « vide » : la page Logs est
    **incapable de signaler qu'elle est cassée** (même anti-pattern que `crypto.decrypt` → retour vide muet) ;
  - les **`HTTPException` (4xx) ne sont JAMAIS loguées** (le handler global ne capte que les 500).
  - **Cible** : table **`audit_events`** (`acteur`, `action`, `cible`, `statut`, `duree_ms`, `message`,
    `detail` JSONB, **`correlation_id`** reliant UI → API → job worker) + onglet **Activité** (filtres,
    détail, timeline, « copier le rapport ») + onglet **Debug** (santé : log écrivable ? worker ? services).
    Préfigure l'auth (`acteur`). Détail + phasage : plan observabilité.

### Session 2026-07-17 — Q&R : la page « Créer » (trace demandée par l'user)

> **Q2a — « L'Aperçu, c'est pour avoir le rendu avant la création du document final ? »**
>
> **R : OUI — l'intuition de l'user était juste.** (Ma 1ʳᵉ réponse « Non » était trompeuse : on ne parlait
> pas du même « final ». **Il y a DEUX créations**, et l'Aperçu se place entre les deux.)
>
> ```text
> 1. Configurer ①②③            → panneau droit = CHECK-LIST (pas un aperçu)
> 2. Cliquer « Générer »        → l'IA rédige LE CONTENU
> 3. Le rapport s'affiche       → Aperçu · Source · Éditer
> 4. Cliquer PDF / DOCX / Wiki  → LE FICHIER FINAL est créé
> ```
>
> - « document final » = **contenu rédigé par l'IA** (étape 2) → l'Aperçu **ne peut pas** le montrer avant :
>   il n'existe pas encore.
> - « document final » = **fichier PDF/DOCX exporté** (étape 4) → **oui** : l'Aperçu montre le rendu
>   **entre 3 et 4**, pour vérifier (et corriger via « Éditer ») **avant** de produire le fichier.
>
> Le panneau a donc **deux vies** : **à vide** = check-list (`Documents : 0 sélectionné` · `Mode` ·
> `Instruction : à renseigner` + « Prochaine étape ») ; **après génération** = le résultat, avec 3 onglets —
> **Aperçu** (Markdown *rendu*, tel qu'il sortira en PDF) · **Source** (Markdown brut) · **Éditer**
> (modifiable avant export).
>
> ⚠️ **Défaut identifié** : les onglets **Aperçu/Source/Éditer s'affichent TROP TÔT** — dès l'étape 1, alors
> qu'ils ne servent qu'après génération. D'où l'attente légitime que « Aperçu » montre quelque chose tout de
> suite. → masquer les onglets tant qu'il n'y a pas de contenu **et** renommer l'état vide (cf. « À corriger »).
>
> **Q2b — « Il me faut une doc complète de la page Créer : quel bouton fait quoi, comment fonctionnent
> les sections 1/2/3 »**
>
> **R — Le principe central : la page est un parcours guidé DYNAMIQUE.** L'étape ① commande tout le reste,
> et **la numérotation est recalculée** (`num()`) selon la destination choisie. **C'est la cause n°1 de
> confusion : « la section ② » ne désigne pas la même chose d'un mode à l'autre.**
>
> **① « Que veux-tu produire ? »** — barre pleine largeur, 5 destinations (`OutputMode`) :
> `Rapport rédigé` · `Remplir un modèle` (Word .docx à trous) · `Classement / tri` ·
> `Tableau comparatif` (Excel) · `Tuto wiki`.
>
> **Puis la colonne de gauche s'adapte :**
>
> | Mode | ② | ③ | ④ |
> |------|---|---|---|
> | Rapport rédigé · Classement · Remplir un modèle · Tuto wiki | **Quels documents ?** | **Instructions** | — |
> | **Tableau comparatif** | **Template Excel** | **Candidats / Sociétés** (1 groupe = 1 candidat) | Instructions *(optionnel)* |
>
> **Étape « Quels documents ? » — 2 onglets** : **Parcourir** (arborescence des documents indexés, on coche
> les fichiers) · **Assistant IA** (on décrit le besoin → l'IA déduit les *pièces* et **propose** des
> documents, qui s'affichent **à droite** sous l'onglet « Proposés »).
>
> **Panneau de droite — titre adaptatif** : `Documents proposés` (retour Assistant) · `Aperçu` (check-list) ·
> `Génération en cours…` · `Résultat` · `Comparatif — progression`. La bascule **Proposés ⇄ Aperçu**
> n'apparaît **que** si l'Assistant a répondu **et** qu'aucun rapport n'est encore généré.
>
> **Boutons du résultat** (visibles **seulement** une fois le contenu généré) : **Copier** · **PDF** ·
> **DOCX** · **Wiki** (publier sur BookStack) · **Régénérer** (relance avec la sélection + le prompt
> courants) · **Effacer** (↺).
>
> **Spécificités** : en **Tuto wiki** les documents sont **optionnels** (rédaction *from scratch* possible)
> et la **publication reste manuelle**. Le bouton **Générer** est en bas de la colonne de gauche.
>
> **🔴 BUG CRITIQUE trouvé en répondant (capture étape ③/④ du 17/07) — « Modèle IA (mixtral) »** :
> **la génération échoue par défaut**. Chaîne complète :
> 1. `stores/reportStore.ts:55` → état initial **codé en dur** `model: 'mixtral:latest'` ;
> 2. `pages/ReportsPage.tsx:158` → le libellé affiche cette valeur (« Modèle IA (**mixtral**) ») ;
> 3. `pages/ReportsPage.tsx:161` → `{showModele && <ModelSelector/>}` : or **`ModelSelector` SAIT
>    s'auto-corriger** (l.29-31 : si le modèle courant n'est pas installé → bascule sur le défaut)…
>    mais il n'est **monté que si l'utilisateur déplie** le bloc, **replié par défaut** → le correctif
>    ne s'exécute jamais ;
> 4. `routers/generate.py:204` → `model = request.model or runtime_config.model_for("rapport")` :
>    la valeur envoyée par le front **écrase** la config (usage `rapport` = `Qwen3.6-35B:latest`).
>
> **Vérifié en prod le 17/07** : `default_model = llama3.1:latest`, usage `rapport` = `Qwen3.6-35B:latest`,
> et **mixtral n'est PAS dans les modèles installés** (Qwen3.6-35B · Qwythos-9B · llama3.1 · ministral-3 ·
> nomic-embed-text · qwen2.5vl · qwen3-embedding). → page fraîche + « Générer » sans toucher au réglage
> = appel Ollama sur un modèle **supprimé**. Contournement actuel : **déplier « Modèle IA »** (répare le store).
> - [x] **CORRIGÉ (17/07)** — plan : [docs/plan-fix-modele-defaut-generation.md](docs/plan-fix-modele-defaut-generation.md).
>   - **Ph.1** `reportStore.model: ''` = **« Auto »** → falsy → le backend applique `model_for('rapport')`.
>     Réaligne « Créer » sur la sémantique **déjà** en place dans Paramètres (« routage dynamique,
>     Auto = défaut ») — aucun concept nouveau.
>   - **Ph.2** *(cause racine)* : l'auto-réparation vivait dans un composant **monté conditionnellement**
>     → extraite dans **`hooks/useModeles.ts`**, appelé au montage de la **PAGE**. `ModelSelector` reçoit
>     la liste en props (une seule source) + **option « Auto »** (impossible jusqu'ici de revenir au
>     routage par usage après un choix manuel). Libellé : « Modèle IA (**Auto : Qwen3.6-35B**) ».
>   - **Ph.4** purge : table des fenêtres de contexte limitée aux modèles installés · « lourd » déduit de
>     la **taille réelle** (>20 Go) et non du NOM · placeholder · 2 docstrings · **et surtout
>     `config.py::ollama_model_default` qui pointait `mixtral`** (piège latent : install neuve sans config
>     en base → modèle inexistant) → `llama3.1:latest`.
>   - **Ph.3** garde backend **`_resoudre_modele()`** sur `/generate/report` **et** `/fill-template` via
>     `model_candidates('rapport')`. ⚠️ `/generate` **streame** → le motif *try/except → modèle suivant*
>     d'`extraction.py` **ne transpose pas** : on **valide AVANT d'ouvrir le flux**. Tolère Ollama injoignable.
>   - **Testé live** (dev, corpus réel) : `''`→Qwen3.6-35B · `None`→Qwen3.6-35B · `mixtral` (mort)→
>     Qwen3.6-35B **+ warning loggé** · `llama3.1`→respecté. Front : 18/18 sur les tests touchés
>     (leurs fixtures figeaient `mixtral` = elles encodaient le bug) ; 23 échecs restants **pré-existants**.
>
> **À corriger (issu de ces questions)** :
> - [ ] **Masquer les onglets Aperçu/Source/Éditer tant qu'aucun contenu n'est généré** — ils s'affichent dès
>       l'étape 1 alors qu'ils ne servent qu'après génération : c'est **la** source du malentendu Q2a.
> - [ ] **Renommer « Aperçu » à vide** → « Récapitulatif » / « Prêt à générer » : à vide ce n'est pas un aperçu.
> - [ ] **Numérotation dynamique déroutante** : ②/③ changent de sens selon le mode → afficher le **nom** de
>       l'étape plutôt qu'un numéro, ou figer les numéros.
> - [x] **Doc utilisateur de la page « Créer »** *(livré 17/07)* — **choix user : BookStack**. Publiée via
>       l'API (`POST /api/bookstack/publish`) dans **Matotheque - Guide d'utilisation → Utilisation**
>       (livre 162, chapitre 163) → **page 171** : <https://wiki.agesti.fr/link/171>. Couvre le principe
>       des étapes dynamiques, le déroulé en 4 temps (config → générer → Aperçu/Source/Éditer → export),
>       le réglage « Auto » du modèle, tous les boutons, et une FAQ reprenant les questions posées ici.

### Session 2026-07-16 — Sources : renommer, explorer, annuler l'indexation

- [x] **✏️ Renommer / modifier une source** *(retour user : « je ne peux pas renommer nas-mato TOM »)* :
      le backend savait déjà le faire (`PUT /sources/{id}` + `sourcesApi.update`) mais **l'UI n'avait pas
      de bouton** — seulement Explorer/Indexés/Supprimer. Ajouté : bouton **✏️ Modifier** sur chaque source
      → formulaire pré-rempli (mot de passe vide = inchangé), `SourcesManager` gère création **et** édition.
- [x] **🔒 « Aucun partage » alors que les identifiants sont bons** *(retour user : « je ne peux pas explorer
      le partage »)* : cause = le mot de passe SMB stocké **ne se déchiffrait plus** (clé Fernet différente de
      l'enregistrement, cf. déploiement prod avec index migré) et `crypto.decrypt` **retourne `""` sans lever**
      → connexion avec **mot de passe vide** → le NAS n'expose aucun partage, **en silence**. Fix : garde
      `_secret_clair` (routers/sources) qui **détecte** le secret illisible et renvoie un **message clair**
      (« re-saisis le mot de passe ») sur `shares`/`browse` ; même garde dans `handler_indexation` (le job
      échoue proprement au lieu d'indexer à vide). **Correction utilisateur = re-saisir le mot de passe** via
      le nouveau bouton Modifier. *(En dev les identifiants se déchiffrent → 20 partages listés, code OK.)*
- [x] **⏹️ Arrêter une indexation en cours** *(retour user)* : l'indexation tournait comme tâche durable
      annulable, mais `handler_indexation` **ne regardait jamais `ctx.cancelled`** → « Annuler » passait le job
      `cancelled` sans stopper la boucle. Fix : la boucle miroir teste `ctx.cancelled` → `task.cancel()` + coupe
      la barre ; `_index_*` rend déjà la main entre chaque fichier donc l'annulation s'y propage. Testé (arrêt
      à 10/100). ⚠️ l'**énumération initiale** de l'arbre (thread `walk_files`) reste non interruptible.

### Session 2026-07-14 — Wiki lisible/indexé + GED par pertinence

- [x] **🐞 Worker — cache runtime_config périmé après un changement UI** *(constaté 14/07 · corrigé v1.14.0)* : la config
      (URLs, tokens) est mise en cache **par processus** ; `set_many` (API) ne mettait à jour QUE le cache du
      backend, pas celui du **worker** → les jobs du worker (index_wiki, indexation, enrich…) utilisaient
      l'ancienne valeur jusqu'à `docker compose restart worker`. **Fix livré** : le worker **recharge
      `runtime_config.load()` avant chaque job** (`job_worker._run`, best-effort) → plus besoin de redémarrer
      le worker après une modif de config dans l'UI.
- [x] **🟢🟠🔴 Voyant services 3 états (occupé vs éteint)** *(livré v1.14.0 · 14/07)* : le Header distingue
      **🟢 disponible** · **🟠 occupé** (joignable mais lent = Ollama/n8n en pleine tâche) · **🔴 injoignable**
      (PC/conteneur éteint). Backend `system._etat_service` (connect-error→down, timeout→busy, <400→ok) ;
      `services()` renvoie `etat` pour ollama/n8n, `StatusDot` colore vert/ambre/gris/rouge.
- [x] **☁️ Connecteurs cloud — champs OAuth dans Paramètres** *(livré v1.14.0 · 14/07)* : nouvelle section
      **« Connecteurs cloud (Drive / Dropbox) »** — saisie `client_id`/`client_secret` (Google Drive) et
      `app_key`/`app_secret` (Dropbox), **secrets chiffrés en base** (`SECRET_KEYS`). Prépare le branchement
      du flux OAuth + des connecteurs (cf. « Connecteurs de sources externes » plus bas). ⚠️ rien n'est encore
      envoyé — seule la saisie des identifiants est livrée.
  - [x] **Rapatrié dans « Sources & indexation »** *(17/07 · retour user)* : la section autonome est
        supprimée. **Raison** : un compte connecteur = une ligne `Source` côté backend (déjà le cas du
        connecteur Synology) → sa place est avec les autres sources. La page était rangée par
        **intégration** (Wiki, HuggingFace, Connecteurs) au lieu de la **tâche utilisateur**
        (« d'où viennent mes fichiers ? »). Les 4 sous-blocs de Sources & indexation (Import direct ·
        Sources de fichiers · Connecteurs cloud · Dossiers indexés) sont désormais des
        `CollapsibleSection` en **accordéon — un seul bloc ouvert à la fois** (chacun porte un
        formulaire différent → lisibilité). `SETTINGS_SECTIONS` gagne un champ `mots` et
        `sectionMatch` cherche titre **+** mots-clés → « drive »/« dropbox »/« oauth » restent
        trouvables par la recherche de sections malgré la disparition du titre.


> Plan détaillé : [docs/plan-wiki-livres-ged-pertinence.md](docs/plan-wiki-livres-ged-pertinence.md).
> Décisions (Q/R) : ouverture livre = **lecture intégrée + BookStack** · indexation = **1 doc/page** ·
> maquette GED = **Livres épinglés + tranches repliables** (validée) · ordre **①→②→③**.

- [x] **① Wiki — Liste des livres (page + couvertures)** *(livré v1.12.0 · 14/07)* : nouvelle page `/wiki/livres` (grille +
      miniatures de couverture **proxifiées**) + lecture intégrée `/wiki/livres/:id` (sommaire + rendu de
      page + bouton « Ouvrir dans BookStack ↗ »). Backend `routers/wiki.py` (books/pages/cover) + extension
      de `bookstack_service`. Sidebar : sous-menu **« Liste des livres »**.
- [x] **② Wiki — Indexation des livres (cherchables)** *(livré v1.12.0 · 14/07)* : handler `index_wiki` — **1 document par page**,
      `categorie='livre'` forcée, embeddings ; **idempotent** (`updated_at` BookStack), supprime les pages
      retirées. Bouton **« Indexer le wiki »**. Les pages remontent dans la GED sous la section Livres.
- [x] **③ GED — refonte par pertinence (sections repliables)** *(livré v1.13.0 · 14/07)* : « Grouper par : **Pertinence** » →
      📚 **Livres épinglés** · 🟢 100-80 · 🟡 80-50 · 🟠 50-30 · 🔴 30-0 · 📄 **Tous**. ⚠️ tranches sur
      **cosinus absolu** (pas le % normalisé-par-max, qui vaut toujours ~100 pour le top) → **recoupe** le
      « seuil de pertinence » (Session 02/07) : livrer idéalement avec la même normalisation.
  - [x] **Carte « livre » distincte** *(v1.14.0 · 14/07)* : un résultat wiki (`chemin=wiki://…`) porte un `wiki_url` →
        la carte affiche **« Ouvrir dans le wiki ↗ »** (au lieu d'Aperçu/Download du fichier) + Fiche.
  - [x] **Aperçu des documents proposés (Assistant « Créer »)** *(v1.14.1 · 14/07)* : bouton **👁 Aperçu**
        sur chaque proposition (même modale que la GED) → ouvrir le fichier avant de le cocher.
- [x] **④ Recherche « Assistant IA » dans la GED** *(livré v1.15.0 · 14/07 · retour user « la recherche IA de Créer devrait être aussi dans la GED »)* :
      bascule **Simple / Assistant IA** dans la barre GED. En mode Assistant, la phrase en langage naturel
      (« trouve les factures EDF ») passe par `assistantApi.pieces` (même moteur que Créer) → **pièces déduites +
      fichiers regroupés par pièce**, cartes avec **Aperçu / Fiche IA / Télécharger** + sélection. La GED devient
      le **hub unique** (recherche hybride *ou* assistant). Réutilise `DocumentPreview`/`DocumentCard`.

### Session 2026-07-02 — pertinence de la recherche

- [x] **🔎 Recherche : seuil de pertinence + « aucun document / afficher quand même »** *(livré &
      validé sur le corpus NAS le 16/07 · plan : [docs/plan-recherche-pertinence-seuil.md](docs/plan-recherche-pertinence-seuil.md))* :
      répond au retour user « les résultats ne me semblent pas pertinents ; en cas de doute je préférerais
      "pas de document" + un bouton pour afficher tout de même les fichiers proposés ».
  - **Cause** : le score affiché (%) est **normalisé par le meilleur du lot** → le top vaut toujours
    ~100 %, même mauvais. Mesure absolue = **similarité cosinus brute** (`1 - distance`, avant `/max`).
  - **Livré** : nouveau `services/pertinence.py` — gate à DEUX niveaux `pertinent = (cos ≥ HAUT) OU
    (cos ≥ BAS ET match full-text)`, partagé par `GET /api/search` **et** l'Assistant (`assistant.py`).
    La réponse expose `nb_pertinents`/`nb_masques`/`seuils` + par doc `pertinence`(cosinus 0-100)/
    `pertinent`/`etiquette`. **Pertinents triés en tête** (sinon la page 1 filtrée pouvait être vide).
    Front (`GEDPage`) : **état vide « Aucun document pertinent » + bouton « Afficher quand même »**
    (aucun re-fetch), bandeau d'avertissement, **étiquette Élevée/Moyenne/Faible** à la place du %.
    Bypass `inclure_non_pertinents=true` (filet). 43 tests backend (dont les 8 requêtes témoins).
  - **⚠️ Re-calibration NAS (16/07) — le point clé** : sur le vrai corpus (**56 k docs**) le plancher
    cosinus de `qwen3-embedding:8b` est **bien plus haut** que sur les 520 docs dev (icônes/zips ~0.62-0.65
    sur n'importe quelle requête, vs ~0.51 en dev). Deux corrections mesurées : (a) on **mesure** le
    cosinus des candidats trouvés lexicalement mais hors du top sémantique (au lieu de les accepter sur
    le seul match de mots — ce qui faisait remonter thèses/guides sur « dossier de mariage ») ;
    (b) **`SEUIL_BAS` monté 0.60 → 0.65**. Résultat : « recette »/« mariage » → **0 pertinent** (état vide) ;
    « facture »/« contrat »/« attestation » gardent leurs bons résultats. Seuils **configurables en base**
    (`search_cos_haut`/`search_cos_bas`) — testé live. 100 % local.
  - [x] **Phase 3 — curseur « Exigence : souple ↔ stricte »** *(livré 16/07)* : Paramètres →
        section « Recherche & pertinence » → curseur à 5 crans (Très souple → Très stricte) mappant
        sur les 2 seuils cosinus (`search_cos_haut`/`search_cos_bas`). Cran « Équilibré » = calibration
        NAS par défaut ; détection « Personnalisé » si les seuils en base sortent des crans ; bouton
        « Rétablir l'équilibré ». Auto-enregistrement immédiat (effet recherche + Assistant).
  - [ ] **Reste optionnel** : **perf** — la recherche sémantique reste lente (~20 s sur 56 k docs, dominée
        par le scan pgvector) → recoupe l'optim Assistant + un cache d'embedding de requête est déjà en place.
  - Recoupe `[ref] Fonctionnement de la recherche` (ci-dessous) et Phase 1 « Valider la recherche
    hybride ; ajuster la pondération si besoin ».

### Session 2026-07-01 — retours sur l'usage post-tâches durables

- [x] **Barre de sélection collée en haut** : la barre d'actions de masse (GED) passe de
      flottante en bas (`fixed bottom-4`) à **`sticky top-0` pleine largeur** dans la liste —
      reste visible au défilement, sans recouvrir la recherche. (`GEDPage.tsx`)
- [x] **Mini-barre de progression dans le Header** : le widget « Tâches » affiche une fine
      barre + % de la tâche en cours **sans ouvrir le menu**. (`JobsIndicator.tsx`)
- [x] **Bouton IA sur les médias + action groupée** : fiche média → **« Forcer l'analyse »**
      (re-extraction Tika + IA, durable ; message clair si fichier distant). Paramètres →
      Maintenance → **« Relancer l'IA (N) »** en lot sur les documents extraits mais non
      enrichis (`POST /documents/reenrich-batch`). (`DocumentCard.tsx`, `SettingsPage.tsx`)
- [x] **Sections Paramètres indépendantes repliables** : la carte fourre-tout « Système & IA »
      est éclatée en 5 cartes autonomes (Statistiques · Maintenance · Services & modèles IA ·
      Wiki BookStack · À propos), chacune pliable/dépliable. (`SettingsPage.tsx`)
- [x] **Wiki BookStack — 2 actions distinctes dans la sidebar** :
      1. **« Publier »** (ex-« Wiki », route interne `/wiki`) = créer/publier un document vers le
         wiki **depuis Matothèque** (renommé + icône Upload pour lever la confusion).
      2. **« WIKI ↗ »** 🆕 = lien **externe** qui ouvre l'**UI BookStack dans un nouvel onglet**
         (`<a target="_blank">`, URL = `bookstack_url` de la config). Si non configuré → renvoi
         vers Paramètres. 100 % frontend (`Sidebar.tsx`). (NOTE utilisateur 01/07)
- [~] **« Forcer l'analyse » d'un média/doc sans texte — fetch SMB SANS doublon** *(planifié,
      plan détaillé : [docs/plan-analyse-media-smb.md](docs/plan-analyse-media-smb.md))* :
      un mécanisme durable **« Analyser le contenu »** qui, pour un média catalogué ou un doc
      extrait **au texte vide** (local ou SMB), récupère le fichier (**fetch SMB → temporaire
      éphémère**), extrait (Tika ; OCR/vision en phase 2), **met à jour le document EXISTANT**
      (⚠️ **aucune nouvelle entrée, aucun fichier conservé → zéro doublon**) puis **supprime le
      tmp**. Inclut : `analyze_existing`, résolution local/SMB, job `analyze`, endpoints
      unitaire + batch (`scope=media|empty|all`), reformulation Maintenance (« Ré-analyser les
      documents sans texte » vs « Relancer l'IA »), et **correctif barre de progression sur
      gros lots** (widget Tâches aveugle au-delà de 20 jobs → agrégat + priorité aux `running`).
      Phase 1 = Tika ; Phase 2 = OCR glm-ocr / vision llava (rejoint le connecteur Scanner).
  - [x] **Phase 1 (Tika) — livrée & validée e2e** : `analyze_existing`, handler `analyze`,
        `_resoudre_fichier` (local | `smb://` → `fetch_to_temp`), endpoints unitaire + batch +
        `GET /documents/maintenance/counts`, UI (fiche « Forcer l'analyse » ; Paramètres
        « Ré-analyser sans texte (N) » + compteur « Relancer l'IA » corrigé ; mini-barre priorise
        les `running`). **Test réel** : média SMB `catalogued→extracted`, **total docs inchangé
        (zéro doublon)**, vrai hash, **tmp nettoyé**. (`ok:false` sur une image sans texte = normal, cf. Phase 2.)
  - [x] **Phase 2 (OCR/vision) — livrée & validée e2e** : quand Tika ne rend aucun texte,
        `_ocr_fallback` envoie l'**image** (ou chaque page **PDF rastérisée** via pymupdf,
        plafond 10 p.) au modèle vision **glm-ocr** (`ollama.generate(images=[…])`). Filtre
        anti-bruit robuste (sentinelle « (aucun texte) » répétée → vide). **Test réel** :
        scan `AttestationassurCBC.pdf` → texte OCR extrait + `enriched` ; photo → vide (plus de
        faux enrichissement) ; PDF corrompu → échec gracieux ; **zéro doublon** ; tmp nettoyé.
        ⚠️ Nécessite `pymupdf` (ajouté à requirements → **rebuild image** pour la prod ; en dev
        installé à chaud). Qualité OCR variable selon le scan (glm-ocr léger). llava (description)
        non branché pour l'instant.
- [x] **🔒 Confidentialité 100% local — garde-fou sorties Internet** *(règle stricte : toute
      sortie réseau = confirmation + zéro fuite de données)* : (1) **aucun appel réseau au
      chargement** (Paramètres ne sonde plus le registre à l'ouverture) ; (2) **modal de
      confirmation** avant chaque action réseau (vérif MAJ modèles, téléchargement/MAJ modèle),
      rappelant qu'**aucun document/tag/résumé/nom de fichier** n'est envoyé ; (3) **section
      repliable « Demandes Mise à jour internet »** qui **centralise** toutes les actions à accès
      Internet. **Audit code** : seul appel web public = `registry.ollama.ai` avec le **nom du
      modèle** uniquement ; `ollama pull` = téléchargement entrant ; ClamAV = base virale (auto,
      hors UI). **Aucune donnée utilisateur ne sort.** (`SettingsPage.tsx`)
- [~] **Connecteur HuggingFace** *(plan : [docs/plan-connecteur-huggingface.md](docs/plan-connecteur-huggingface.md))* :
  - [x] **Stockage des identifiants (livré)** : section « HuggingFace 🤗 » dans Paramètres —
        **token API** + **identifiant** + **mot de passe**, secrets **chiffrés (Fernet)** et
        **masqués** en lecture (pattern BookStack). **Stockage local**, aucune requête réseau.
        Validé : token → `enc::` en base, masqué en lecture. (`runtime_config`, `system.py`,
        `SettingsPage.tsx`)
  - [ ] **Usage réseau HF (à cadrer)** : recherche/pull de modèles gated via l'API HF côté
        backend. ⚠️ Ollama tourne sur l'hôte → le token stocké ne suffit pas seul au pull gated.
        Toute requête HF devra passer par « Demandes Mise à jour internet » + confirmation.
  - [ ] **Page « Catalogue HuggingFace » (tuiles)** *(plan :
        [docs/plan-catalogue-huggingface.md](docs/plan-catalogue-huggingface.md))* : nouvelle page
        explorant le hub HF en **cartes**, modèles **≤ 2 ans ET maintenus**, **regroupés par
        catégorie/fonction** (LLM · embeddings · vision/OCR · audio), avec **date de mise en ligne**
        + **dernière MAJ**, badge **« maintenu »**, **😈/officiel** (heuristique), gated, popularité,
        bouton **« Installer »** (gguf → `ollama pull`). ⚠️ Sortie Internet → **confirmation** +
        rattachée à « Demandes Mise à jour internet », **zéro donnée doc envoyée**. Phasage :
        (1) backend catalogue+filtres, (2) page+tuiles+badges, (3) installation via Ollama.
- [x] **Catalogue HuggingFace (page tuiles) — livré** : page `/huggingface` (garde-fou d'entrée,
      onglets catégorie, filtres officiel/😈/**installé**, tri) ; clic carte → modal (résumé **FR
      généré par l'IA locale**, licence, badges) ; **bouton Installer** (`ollama pull hf.co/<id>`,
      barre de progression + confirmation) + **commande PowerShell** copiable. Backend
      `routers/huggingface.py` (catalogue + détail, cache, token). (Phases 1-3)
- [x] **Routage dynamique du LLM par usage — livré & validé** *(plan :
      [docs/plan-routage-llm-usage.md](docs/plan-routage-llm-usage.md))* : config `usage_models`
      (JSON) + `runtime_config.model_for(usage)` (override par usage > défaut runtime, remplace le
      défaut env → corrige l'appel à un modèle supprimé) ; câblé sur rapport/enrichissement/
      embeddings/vision/résumé-HF ; UI « 💡 Modèle par usage » (sélecteurs éditables + reco locale).
      Validé : enrichissement routé vers le modèle configuré (logs `modele=ministral-3:14b`).
- [x] **Page Administration — liens externes (Médical / Gouv…) — livré** : page `/admin`, **sections
      pliables** par catégorie (Médical → Doctolib, Mon espace santé ; Gouv → Impôts, ANTS…), liens
      en nouvel onglet ; **gestion dynamique** dans Paramètres → « Administration — liens »
      (ajouter/retirer). Stockage config JSON `admin_links` (pas de nouvelle table). Sidebar + route.
  - [x] **Catalogue de services publics à activer (interrupteur)** *(livré 16/07)* : sous l'éditeur,
        une liste repliable de ~19 services officiels (*.gouv.fr : Service-Public, Impôts, ANTS,
        FranceConnect, Légifrance, Mon Compte Formation, ANTAI, Géoportail, Cadastre… + Ameli / Mon
        espace santé). Chaque ligne = un **interrupteur** : activer ajoute le lien, désactiver le retire.
        Détection par **hôte normalisé** → un service déjà présent (ex. Impôts) s'affiche activé.
  - [x] **Catalogue piloté par config + vérification des liens** *(livré 16/07)* : le catalogue vient
        désormais de la config backend `admin_catalogue` (`GET /system/admin-catalogue`) → **rechargeable /
        extensible sans rebuild** (bouton « Recharger », repli local si hors-ligne). Bouton **« Vérifier
        les liens »** (`POST /system/admin-links/verifier`) : sonde chaque site (HEAD, GET en secours) et
        classe **OK / Déplacé (→ « Appliquer » la nouvelle URL) / Supprimé / Injoignable**. C'est une
        **sortie réseau** → passe par la confirmation « Demandes Mise à jour internet » et **n'envoie que
        les URLs**. Découverte auto de *nouveaux* sites non faisable hors-ligne ; les redirections
        cross-domaine (ex. Pôle emploi → France Travail) et domaines morts sont bien détectés.
- [x] **Classification modèles officiel/😈 PERSISTÉE — livré** : table `model_meta` {name, classe} ;
      la vérif registre (check_updates) enregistre `officiel`/`uncensored` (update=null = hors
      registre → uncensored), garde anti-erreur-réseau ; `/system/models` renvoie `classe`
      (persistée, sinon fallback nom). Badge liste + sélecteur basés sur `classe` (plus d'heuristique
      client). *« On a déjà l'info » — validé : Qwen3.6-35B → uncensored persisté.*
- [ ] **Historique des tâches + purge + page « Logs »** *(NOTE utilisateur 01/07 ; plan :
      [docs/plan-logs-historique.md](docs/plan-logs-historique.md))* : conserver l'historique des
      tâches (`jobs`) ; **purge sur demande** via **fenêtre de confirmation** (tout / **> 365 jours**,
      jamais les pending/running). **Section « Logs » dans Paramètres** → **page `/logs`** avec
      **sections pliables** : **Activité** (qui fait quoi — jobs), **Journal** (que s'est-il passé),
      **Debug** (tail `GET /api/logs/tail`). Phasage : (1) purge + Activité + Debug ; (2) journal métier.
- [ ] **Lier des documents entre eux (ex. bon de commande ↔ facture)** *(NOTE utilisateur 01/07)* :
      « retrouver le BC et la facture qui correspondent et les lier ». **Approche recommandée =
      HYBRIDE** :
  1. **Extraire une référence** (n° de commande/dossier, + montant, fournisseur, dates) à
     l'enrichissement → stockée sur le doc (champ dédié / metadonnees_ia).
  2. **Section « Documents liés » dans la fiche** : affiche les docs partageant la **même référence**
     + des **suggestions de rapprochement** (même n° / même montant / dates proches / même
     fournisseur) **à confirmer** (validation humaine → évite les faux liens).
  3. Stockage des liens validés en base (table `document_liens` : source, cible, type
     « facture-de / commande-de », score). Recherche « trouve le doc lié » via ces liens.
      À cadrer dans un plan dédié.
- [ ] **Connecteur reMarkable** *(NOTE utilisateur 01/07 — pour plus tard)* : connexion avec la
      tablette **reMarkable** (via son API cloud) pour **importer** notes/PDF annotés dans la GED
      (et éventuellement pousser des documents vers l'appareil). À cadrer : auth (token), sens de
      synchro ; sortie Internet → garde-fou « Demandes Mise à jour internet ».
- [ ] **Connecteur openplaud (transcription audio via Voxtral)** : ajouter dans Paramètres une
      **URL openplaud** (service de transcription audio existant) pour que Matothèque envoie les
      **fichiers audio** à transcrire via **Voxtral** — évite de recréer une connexion Voxtral
      côté Matothèque. Flux cible : média audio catalogué → « Transcrire » → openplaud → texte
      → indexation/enrichissement GED. À cadrer comme un **service configurable** (comme Tika/n8n),
      secret chiffré si besoin. *(NOTE utilisateur 01/07)*
- [ ] **Import depuis le scanner (Epson) → GED** : ouvrir le dossier de scan
      (`Scans_Epson` sur le NAS `\\192.168.42.200`), afficher un **aperçu** de chaque scan,
      puis **importer dans la GED avec des tags**. Flux : lister le répertoire scanner →
      prévisualiser (image/PDF) → valider + tagger → indexation GED. À cadrer comme un
      **connecteur « Scanner »** (source dédiée ou action d'import). *(NOTE utilisateur 01/07)*
- [ ] **Rafraîchir la page/les données à l'ouverture d'un menu** : quand l'utilisateur
      **ouvre un menu** (ex. dropdown « Tâches », menus de la fiche/GED…), déclencher un
      **refresh des données sous-jacentes** pour toujours afficher l'état le plus frais
      (pas seulement attendre le prochain tick du polling). À cadrer : quels menus (widget
      Tâches → forcer un `poll()` à l'`open` ; listes GED → refetch React Query ?), éviter
      les requêtes en rafale. *(NOTE utilisateur 01/07)*
- [x] **« Indexations actives » → « Dossiers indexés »** : section renommée, liste les **racines
      indexées par source** (compteur de docs) avec bouton **« Gérer »** qui déplie l'arbre inline
      (cases à cocher + retirer de l'index, réutilise `IndexedFolders`). La surveillance auto
      (dossiers scannés) reste affichée **seulement si** des dossiers sont surveillés.
      (`IndexedSourcesSummary.tsx`)
- [x] **🔴→✅ Indexation média raisonnée (corrigé)** : les **médias (images/audio/vidéo)** sont
      désormais **catalogués par métadonnées** (nom/taille, `statut='catalogued'`) **sans
      téléchargement ni Tika/IA/embeddings** ; les **documents** gardent le pipeline complet.
      `MEDIA_EXTENSIONS`, `ExtractionService.catalogue_media`, `walk_files` renvoie la taille,
      contrainte `documents_statut_check` étendue (garde-fou au démarrage + init-db.sql).
      Validé en conditions réelles : ré-index `home` → **3576 médias `catalogued`** (texte vide,
      sans fetch) + **143 docs `enriched`** (pipeline complet). Dossiers système Synology
      (`#recycle`/`@eaDir`/`#snapshot`) exclus du parcours SMB.
  - [x] **Nettoyage de l'existant** : purge des 9318 docs SMB ingérés en lourd + ré-indexation
        propre de `home` (médias re-catalogués léger). Fait.
  - [ ] **Indexation incrémentale / progression** : la walk SMB est **monolithique** (énumère
        tout l'arbre avant d'insérer → plusieurs minutes sans feedback sur un gros `home`).
        À streamer (insérer au fil du parcours) + barre de progression.
  - [x] **Barre de progression d'indexation dans Paramètres → Dossiers indexés** — ✅ livré :
        `GET /sources/{id}/progression` (tracker mémoire : phase `enumeration`→`indexation`,
        total + fait) sondé toutes les 2,5 s par `IndexedSourcesSummary` → **barre + « X / Y »**
        par source (indéterminée pendant l'énumération, % ensuite). La source en cours apparaît
        même à 0 doc ; le compteur se rafraîchit à la fin. Validé (en_cours/phase/total/fait).
- [x] **GED parcourable par défaut** : la page ouvre directement sur la **liste des documents**
      (mode parcourir) ; les clics **catégorie/tag** du rail **filtrent la liste sans requête**
      (bandeau « Filtré : … ✕ ») ; la recherche bascule en mode résultats, « Tout afficher »/✕
      reviennent à la liste. (`quickFilter` dans GEDPage + prop `filter` d'AllDocumentsView)
- [x] **Page Rapports — écarts vs cahier des charges comblés** :
  - [x] **multi-sélection Shift+clic** (sélection de plage) dans le picker (`selectMany`)
  - [x] indicateur **tokens / temps estimés** (`GenerationEstimate`) + alerte troncature si > fenêtre modèle
  - [x] bouton **« Régénérer »** dans la barre d'outils du résultat
  - [x] picker Rapports **n'affiche plus les médias catalogués** (filtre backend `texte=true`)
  - [x] colonne gauche en **liste plate** : re-scopée et **clôturée** — le picker plat (+ « Sources »)
        remplace l'« arborescence de dossiers surveillés » du plan initial (décision validée).
- Clarifications (pas un bug) : l'**arbre des dossiers indexés** = bouton **« Indexés »** sur la
  source ; l'indexation SMB est un **traitement one-shot** qui alimente la GED + cet arbre.

### Session 2026-06-27 — idées UI GED (pour plus tard)
- [x] **Rapports — RÉSULTAT dynamique** (retour user) : la colonne RÉSULTAT affiche, avant
      génération, un **récap « Votre rapport »** (✅/⬜ Documents N · Mode · Instruction) + une
      **« Prochaine étape »** contextuelle, au lieu d'un placeholder statique. Fait.
- [x] **Rapports — colonne « Documents du rapport » clarifiée** (retour user « je ne comprends pas
      l'intérêt ») : renommée + sous-titre « Cochez les fichiers à analyser, ou laissez l'Assistant
      les proposer ». Reste optionnel (c) : repenser le flux (sélection GED → « Utiliser dans un
      rapport » → la colonne devient un récap repliable). **À trancher si on va plus loin.**
- [x] **Rapports — refonte complète en PARCOURS GUIDÉ (stepper)** (retour user 29/06 « je ne m'y
      retrouve pas du tout, repropose la présentation ») : remplace les 3 colonnes + empilement
      d'accordéons de même poids par une **colonne d'étapes numérotées** (① Que produire ·
      ② Quels documents · ③ Instructions · ④ Générer) + **résultat en grand à droite**. Améliorations :
  - [x] le **Mode** (libre/template/classement/comparatif) devient la **1ʳᵉ décision**, la suite s'adapte ;
  - [x] **fusion** des 2 façons de choisir les documents (ancienne colonne gauche + Assistant central)
        en **une seule étape « Quels documents ? »** à 2 onglets : **Parcourir** / **Assistant IA** ;
  - [x] **Modèle IA** rétrogradé en **réglage avancé replié** (sous les Instructions) au lieu d'être en avant ;
  - [x] étapes **conditionnelles au mode** (ex : Template Excel + Candidats en Comparatif), numérotées
        dynamiquement ; nouveau composant réutilisable `components/reports/Step.tsx` (pastille + trait de liaison).
  - [x] **Étape ① — libellés explicites** (retour user « les boutons ne sont pas explicites ») :
        `Rapport rédigé` (synthèse/analyse libre), `Remplir un modèle` (Word .docx à trous),
        `Classement / tri`, `Tableau comparatif` (candidats/sociétés Excel) — descriptions reformulées.
  - [x] **Étape ② — picker documents DYNAMIQUE** (retour user « il n'y a pas tous les fichiers indexés ! ») :
        le picker chargeait `page_size=50` et filtrait seulement ces 50 → **seuls 50 docs visibles sur 3752**.
        Corrigé : **recherche débouncée côté serveur** (param `q` backend, ilike sur le nom) sur **tous** les
        indexés porteurs de texte, `page_size=100` (plafond backend), + **compteur « X sur N »** et invite à
        affiner quand la liste est tronquée. `documentStore.fetchDocuments` accepte désormais `page_size`.
  - [x] **Étape ② — « Parcourir » en ARBORESCENCE** *(retour user 16/07 · **livré 16/07** · plan :
        [docs/plan-picker-arborescence-creer.md](docs/plan-picker-arborescence-creer.md))* : la **liste plate**
        (`FileExplorer`) est remplacée par un **arbre de dossiers** dont les **feuilles sont les fichiers
        cochables** (→ `documentStore.selectedIds`). Backend `GET /documents/tree` (lazy par dossier ;
        `flat=true` = tous les fichiers sous un préfixe → « tout cocher le dossier ») testé sur le corpus NAS
        (56 k docs). Front `IndexedDocsTree` (dépliage paresseux, filtre → recherche plate transverse en repli).
        **⤺ revient sur** la décision « colonne gauche en liste plate » (Session 27/06). Reste optionnel :
        shift-clic de plage, mémorisation des nœuds dépliés.
- [ ] **Rapports — panneau « Résultat » = sortie DYNAMIQUE UNIFIÉE** (retour user 29/06, capture +
      précision « il faut que TOUS les résultats arrivent dans la section Résultat ; il faut que Résultat
      soit dynamique ») : aujourd'hui les sorties sont éparpillées (propositions de l'Assistant tassées
      dans la colonne d'étapes à gauche ; progression comparatif vs rapport gérées séparément) alors que
      le grand panneau de droite reste souvent vide.
  - **Cible** : **un seul panneau « Résultat » à droite**, dont **le contenu ET le titre s'adaptent à
    l'action en cours** — tout ce que produit l'IA y atterrit. ✅ **Livré (29/06)** — sauf le statut « Remplir
    un modèle » (reporté, lié aux tâches durables).
  - **Plan** (machine à états du panneau, titre adaptatif) :
    - [x] **Propositions Assistant** → l'onglet **Assistant IA** (étape ②) ne contient plus que l'**input** ;
          les pièces s'affichent **en grand à droite** (titre « Documents proposés »), cochables → sélection.
          État **remonté** dans `stores/reportAssistantStore.ts` ; split `AssistantInput` / `AssistantProposals`.
    - [x] **Avant génération, sans assistant** → **récap « Votre rapport »** — titre « Aperçu ».
    - [x] **Génération en cours** → **stream du rapport** — titre « Génération en cours… ».
    - [x] **Comparatif** → **progression** dans le **même** panneau — titre « Comparatif — progression ».
    - [ ] **Remplir un modèle** → **statut + lien de téléchargement** du DOCX (aujourd'hui téléchargement
          direct, aucun retour visuel) — **reporté** (cf. « Tâches IA durables »).
    - [x] **Terminé** → **rapport** + barre d'actions (export, wiki, régénérer).
    - [x] technique : composant **`ResultPanel`** (titre + contenu dérivés de l'état : comparatif /
          propositions / génération / résultat / aperçu) ; **bascule Proposés ⇄ Aperçu** quand pertinent.
- [~] **Assistant « Trouver des documents » — LENTEUR** *(02/07 : débloqué + accéléré — le modèle de
      déduction pointait sur `mistral:latest` SUPPRIMÉ (502/lenteur) → re-routé `runtime_config` ;
      `keep_alive` Ollama (fin du swap VRAM) ; embedding de requête routé via `usage_model`. Reste
      optionnel : cache d'embeddings des libellés, early-stop)* (retour user 29/06 « Matothèque le trouvait plus
      vite avant la mise en place de l'aperçu »).
  - **Diagnostic** : l'aperçu (`ResultPanel`) **n'ajoute aucune latence** (même appel `/assistant/pieces`) —
    il rend l'attente **visible** (grand panneau + spinner). **Vraie cause** : `assistant.py` fait, **en
    séquentiel**, 1 appel LLM (déduction des pièces) **+ jusqu'à 8 recherches hybrides**, chacune avec une
    **génération d'embedding Ollama** (qwen3-embedding) → plusieurs secondes. (La recherche **Parcourir/GED**
    full-text reste instantanée.)
  - **Plan d'optimisation** :
    - [ ] **Paralléliser les recherches par pièce** (`asyncio.gather`, **1 session DB par tâche** —
          l'`AsyncSession` n'est pas concurrente) → somme→max sur la partie DB/full-text.
    - [ ] **Réduire `MAX_PIECES`** (8 → 5) et/ou s'arrêter dès assez de résultats.
    - [ ] **Limiter le swap de modèle Ollama** (mistral ↔ embedding) : garder les modèles chargés
          (`keep_alive`) ou déduire les pièces avec un modèle déjà chaud.
    - [ ] **Feedback d'attente explicite** côté front : étapes « déduction… → recherche… » + compteur de
          secondes (l'attente paraît intentionnelle, pas bloquée).
- [x] **🔴 BUG — l'indexation GÈLE tout le backend** *(02/07 RÉSOLU : (1) dernier blocage event-loop supprimé
      (lecture Tika en `asyncio.to_thread`) ; (2) **worker isolé dans un process/conteneur DÉDIÉ** (flag
      `RUN_WORKER`, service `worker` dans les 3 compose) → l'API n'ENFILE que des jobs, plus aucun handler dans
      sa boucle → une indexation ne peut plus geler les routes ; (3) garde double-worker (verrou d'avis Postgres
      sur la reprise) ; (4) upload Tika en **flux** (blocs 1 Mo) → **pic RAM borné** sur gros fichiers. Testé en
      dev. Les `stat()` locaux sont laissés tels quels (envelopper dans `to_thread` coûterait plus que le stat, et
      le worker isolé ne peut plus geler l'API))* (découvert 29/06 en testant) : pendant une indexation
      NAS/locale, **toutes** les routes API (y compris `/api/version`) **timeout pendant plusieurs minutes**
      (mesuré : un appel resté bloqué **73 min** ; après `restart backend`, `/api/version` répond en 6 ms et
      l'Assistant en 5 s). **Cause** : du **travail synchrone/bloquant dans le pipeline d'indexation** (hash,
      Tika, ClamAV, chunking/embeddings, écritures) tourne **dans l'event loop async** sans être déporté →
      il **affame** toutes les autres requêtes. **Impact** : appli perçue comme figée, IA/génération qui
      « hangent » alors que tout va bien hors indexation.
  - **Plan** :
    - [x] **Déporter les appels bloquants en threadpool** (`asyncio.to_thread`) — **fait & mesuré (30/06)**.
          Audit : Tika (`AsyncClient`), Ollama (`AsyncClient`), ClamAV (`to_thread`) et SMB (`to_thread`)
          étaient **déjà** OK. Corrigé : **`compute_sha256`** (`process_file`), **`chunk_text`**
          (`embed_document`) et la **construction de la liste de fichiers** locale (`rglob`) dans `_index_local`.
          **Preuve** : hash d'un fichier de 250 Mo → blocage event loop **115 ms → 3 ms**.
    - [x] **Rendre la main à l'event loop entre fichiers** (`await asyncio.sleep(0)` dans `_index_local`
          et `_index_smb`).
    - [ ] **Isoler l'indexation du serveur d'API** : la confier au **worker de tâches durables** (process/
          worker séparé) → rattaché au chantier **« Tâches IA durables »**. *(Le gel aigu est résolu par
          l'offload ci-dessus ; cette isolation reste un + d'architecture.)*
- [x] **Dates des fichiers — fiche GED + résultat « Créer »** (demande user 29/06) — **livré & testé** :
  - [x] **Fiche document** : **Créé le** (extrait des `tika_metadata` : `dcterms:created` / `Creation-Date`
        / `meta:creation-date` / `pdf:docinfo:created`) et **Modifié le** (`date_modification_fichier`),
        en plus de « Importé le ». *(« Dernière ouverture »/atime non tracé → création + modification.)*
  - [x] **Backend** : `_doc_to_dict` expose `date_creation` (helper `creation_date_from_tika` dans
        `utils/file_utils.py`) ; type front `Document` étendu (`date_creation`, `date_derniere_extraction`).
        Vérifié : l'API renvoie bien `date_creation` (ex. `2025-11-23T…` issu de Tika).
  - [x] **Résultat « Créer »** : dates injectées dans le **contexte LLM** — en-tête
        `--- Document : nom (créé le X · modifié le Y) ---` (`generate.py / _construire_contexte`).
  - *Note data : pour les fichiers récupérés via SMB, `date_modification_fichier` ≈ date d'import (mtime du
    fichier temporaire) → la date de création Tika reste la plus fiable. À améliorer si besoin.*
- [x] **Mode « Tuto wiki » — ergonomie « où lancer la demande ? »** (retour user 29/06 : « le bouton Tuto
      wiki ne fonctionne pas ? je pensais lancer la demande depuis l'étape ② mais non ! ») — **livré & testé** :
  - **Constat** : en mode wiki, la demande (prompt) était en étape ③ « Sujet / consignes », l'étape ②
    n'étant que les documents (optionnels) → on ne voyait pas **où décrire le tuto**. (Le bouton « marche »,
    mais Générer reste désactivé tant qu'aucun sujet n'est saisi.)
  - [x] **Réordonné en mode wiki** : « **Sujet / consignes du tuto** » = **étape ②**, « Documents sources
        (optionnel) » = **étape ③** (sous-rendus `renderPromptStep`/`renderDocsStep`, numérotation préservée).
  - [x] **Bandeau d'aide** en mode wiki (décrire le tuto → Générer → **publication MANUELLE**).
  - [x] **Publication déjà 100 % manuelle** (point 2 user) : aucune publication auto — bouton « Publier sur
        le wiki » → `PublishBookStackModal` (choix livre/chapitre + clic « Publier »). **Rien à changer**,
        confirmé.
- [ ] **Atelier de création unifié — Wiki = destination de l'étape ① + renommage de la page** (décision
      user 29/06 : « le Wiki doit intégrer l'IA pour aider à créer les docs ; en fait c'est un **bouton de
      l'étape ① dans Rapport**, et il faut changer le nom de la page »). La page « Rapports » est déjà un
      stepper produisant plusieurs sorties (rapport / modèle / classement / comparatif) → le nom est trop
      étroit et le **Wiki n'est pas une page à part** mais une **5ᵉ destination**. La `WikiPage` standalone
      (livrée en Lot 1a) doit **fusionner** dans cet atelier (composition dans l'atelier ; vue arbre du wiki
      conservée en consultation). **Spéc détaillée + maquette : [PLAN-bookstak.md](PLAN-bookstak.md) → Lot 1c.**
  - [x] renommé « Rapports » → **« Créer »** (nav `Sidebar`, icône `PenSquare` ; `/` reste l'index ;
        MAJ CLAUDE.md/README reportée) ;
  - [x] étape ① en **barre horizontale pleine largeur** + destination **`wiki`** (📖 « Tuto wiki ») ;
  - [x] mode `wiki` : ② Documents **optionnel**, ③ **zone de prompt** → l'IA rédige le Markdown (pipeline
        existant) ; backend `/generate/report` accepte un **`document_ids` vide** (tuto « from scratch ») ;
  - [x] `ResultPanel`/`ReportPreview` mode `wiki` : Markdown **éditable** (onglet « Éditer ») + **« Publier
        sur le wiki »** (réutilise `PublishBookStackModal`) ; **`WikiPage` gardée en consultation**.
  - ✅ **Lot 1c livré (29/06)** — `tsc`/`ast` OK ; parcours générer→publier à valider en usage.
- [ ] **Indexation dynamique / automatique ?** (question user 29/06 : « si j'ajoute un fichier dans un
      dossier indexé, sera-t-il indexé automatiquement ? » · **re-remonté le 17/07** : « les nouveaux
      dossiers/fichiers ou ceux modifiés n'apparaissent pas dans les arborescences »).
  > **📋 PLAN DÉTAILLÉ (17/07) : [docs/plan-indexation-continue.md](docs/plan-indexation-continue.md)** —
  > **décision d'archi : scan incrémental dans le WORKER, pas n8n** (n8n ajouterait une dépendance
  > externe au chemin critique, dupliquerait la logique d'indexation et ne connaît ni les secrets
  > SMB chiffrés ni les extensions configurables ; le worker durable existe déjà et sait tout faire).
  > Principe = **diff NAS ↔ index** : nouveau / modifié / supprimé / **déplacé** (hash identique +
  > chemin différent → simple UPDATE du chemin, zéro re-extraction). Perf : comparer d'abord
  > `(taille, date_modif)`, **ne hasher que les candidats**. Phasage 1→4 dans le plan.
  > **Mesuré le 17/07** : `[MaTo]/01-bebe` (modifié le 16/07 = après le dernier scan) → **0 doc en base**.
  - [x] **1a — bouton « Rafraîchir » trompeur** *(livré 17/07)* : il relit les **compteurs** depuis
        l'index et ne relance **aucun scan** → « rien ne se passe ». Renommé **« Rafraîchir les
        compteurs »** + `title` explicite. (Le vrai besoin = bouton « Réindexer » → Phase 1 du plan.)
  - [x] **1b — « Aucun partage » à l'exploration d'une source montée** *(livré 17/07)* : **deux** bugs
        superposés. (i) backend : `crypto.decrypt()` renvoie `""` **sans lever** si la clé Fernet diffère
        → connexion mot de passe VIDE → 0 partage en silence (garde `_secret_clair` → HTTP 400 explicite,
        livrée plus tôt) ; (ii) **frontend** : `catch { toast.error('Exploration impossible') }` **jetait
        le message du backend** → l'utilisateur voyait « Aucun partage (ou identifiants requis) », qui
        n'apprend rien. Fix : helper **`extractApiError`** exporté depuis `api/index.ts` + utilisé par tous
        les `catch` de `SourcesManager` ; la cause s'affiche **dans le panneau** avec un lien
        **« Modifier la source (re-saisir le mot de passe) »**. ⚠️ **Action prod** : la clé Fernet ayant été
        rotée, re-saisir une fois le mot de passe du NAS.
  - **Réponse : NON, pas aujourd'hui.** Les **sources NAS/SMB** s'indexent via un **scan one-shot manuel**
    (bouton « Indexer ») → un fichier ajouté **n'est pas** pris automatiquement ; il faut **relancer
    l'indexation** (idempotente : dédup par `hash_sha256`, les inchangés sont sautés). Le service
    `FolderWatcher` (boucle 60 s sur la table `dossiers_surveilles` **locaux**) existe **en code mais
    n'est pas démarré au startup**, et ne couvre **pas** les sources SMB.
  - **n8n était bien prévu pour ça** (retour user « on n'avait pas mis n8n en place pour ça ? ») : les
    workflows **`n8n/workflows/folder-watcher.json`** + **`indexer.json`** existent déjà (créés le 25/06),
    mais **ne sont pas activés/importés** dans l'instance n8n de l'hôte. → **n8n = mécanisme privilégié**
    pour l'indexation continue (l'archi CLAUDE.md le désigne : Watch Folder · Cron · Webhook).
  - **Plan** (n8n d'abord, watcher backend en repli) :
    - [ ] **Phase 1 — activer le workflow n8n `folder-watcher`** : détecte nouveaux/modifiés dans un dossier
          **accessible à n8n** (local/monté) → appelle l'API d'ingestion (réutilise `process_file`, idempotent
          par `hash_sha256`). **Exposer/figer un endpoint webhook** côté backend pour n8n. **Cron de
          ré-indexation** (`indexer.json`) pour rattraper.
    - [ ] **Phase 2 — couvrir les sources SMB** : n8n ne « watch » pas nativement un partage SMB → soit
          **monter le partage** côté n8n/hôte, soit un **workflow Cron** qui appelle `POST /sources/{id}/index`
          à intervalle. **Nécessite identifiants stockés chiffrés** (`crypto.py`) → **impossible** pour les
          sources à **creds transitoires** (re-saisie requise).
    - [ ] **Phase 3 — repli/alternative interne** : démarrer le `FolderWatcher` backend au startup (local,
          option watchdog/inotify temps réel) si on veut s'affranchir de n8n. **Intervalle configurable par
          source** ; **scan incrémental** (`date_modification` + hash) ; **chaque scan = un Job** (→ chantier
          **« Tâches IA durables »**). UI : indicateur « dernière synchro » + bouton « synchro maintenant ».
- [~] **Connecteurs de sources externes en LECTURE — section dédiée dans Paramètres** *(P0 socle LIVRÉ 12/07 :
      interface `SourceConnector` + registre + **connecteur Synology** (QuickConnect/DSM Auth/FileStation, porté
      de `acces-syno`) + API `/connectors` (créer/tester/parcourir) — **testé en réel** contre le NAS (14 partages,
      navigation+walk). Reste : indexation via le pipeline durable (bloquée tant que `job_handlers.py` = WIP autre
      session), UI Paramètres (multi-comptes), plomberie OAuth pour Drive/Dropbox/OneDrive)* (question user 29/06 :
      « peut-on prévoir une connexion Drive ? en lecture » + « prévoir les connecteurs / section dans
      Paramètres »).
  - **⭐ Multi-comptes dynamique** (demande user 12/07) : **plusieurs comptes par fournisseur** (ex. 2 Google
    Drive perso+pro, plusieurs Dropbox), **1 compte connecté = 1 `Source`**, ajout/retrait **à chaud**, chacun
    **indexé** comme une source SMB. **Synology** : WebDAV ou API DSM FileStation, atteignable en LAN, DDNS
    **ou QuickConnect** (relais Synology, sans ouvrir de port). → **Plan détaillé :
    [docs/plan-connecteurs-cloud-multicomptes.md](docs/plan-connecteurs-cloud-multicomptes.md).**
  - **Réponse : oui, faisable** — le modèle `Source` abstrait déjà le type (`local | smb`) ; on ajoute des
    **connecteurs** implémentant la même interface **test / browse / fetch** que `smb_service.py`, puis le
    pipeline d'indexation existant (`process_file`) traite les fichiers récupérés en local temporaire.
    **Toujours en LECTURE SEULE** (corbeille/quarantaine désactivées pour ces sources).
  - **UI — nouvelle section « Connecteurs » dans Paramètres** (à côté de « Sources NAS/SMB ») : liste des
    connecteurs disponibles, bouton **« Connecter »** (OAuth) par fournisseur, état (connecté / expiré),
    sélection des dossiers à indexer, **déconnexion**. Jetons OAuth **chiffrés en base** (`crypto.py` + refresh).
  - **Liste (non exhaustive) de fournisseurs Drive envisageables** :
    - [ ] **Google Drive** — *prioritaire, le plus simple* : OAuth2 `drive.readonly` (MCP déjà connecté côté
          session pour prototyper).
    - [ ] **Microsoft OneDrive / SharePoint** — Microsoft Graph API (OAuth2, `Files.Read.All`).
    - [ ] **Dropbox** — API v2 (OAuth2, scope `files.content.read`).
    - [ ] **Box** — Box API (OAuth2).
    - [ ] **Nextcloud / ownCloud** — **WebDAV** (souvent en place chez les TPE/collectivités) — *simple*.
    - [ ] **Synology Drive / NAS** — **WebDAV** ou **API DSM FileStation** ; transport **LAN / DDNS / QuickConnect**
          (relais Synology, sans ouvrir de port). *Démarrer WebDAV en LAN.*
    - [ ] **WebDAV générique** — couvre beaucoup de NAS/clouds auto-hébergés (kDrive Infomaniak, etc.).
    - [ ] **pCloud**, **Mega**, **Amazon S3 / compatible (MinIO)** — *selon besoin réel*.
    - [ ] (à écarter pour l'instant : **iCloud Drive**, **Proton Drive** — pas d'API publique exploitable.)
  - **Plan technique** :
    - [ ] **Généraliser le modèle de connecteurs** : interface commune `SourceConnector` (test/browse/fetch),
          `Source.type` étendu, secrets/jetons chiffrés en base, **flux OAuth** (callback) côté backend.
    - [ ] **Connecteur Google Drive** en premier (référence), puis WebDAV (couverture large), puis les autres.
    - [ ] **Cohérence** avec « Indexation dynamique » (synchro périodique/polling) et « Tâches IA durables »
          (chaque synchro = un Job).
- [ ] **Digiposte (coffre-fort numérique La Poste) — à part, lecture** (demande user : « laisse Digiposte
      à part ») : **faisabilité à valider en priorité** — API existante mais **accès partenaire/restreint**
      (programme dev La Poste à demander) ; **pas de repli** propre (ni SMB ni WebDAV public). **Risque :
      accès API non garanti.** → **Étape 0 = vérifier l'éligibilité/les conditions** avant tout dev ; si OK,
      même mécanique de connecteur lecture seule que ci-dessus.
- [ ] **⭐ Tâches IA durables — survivre au changement de page ET à la fermeture du navigateur**
      (retour user 29/06 « les actions IA ou autre doivent pouvoir se faire même si on change de page
      ou qu'on sort du navigateur pour faire autre chose sur l'ordinateur ») — **chantier architecture**.
  - **Constat (audit 29/06)** : seuls `/generate/report` et `/compare` créent un `Job` + tournent en
    `BackgroundTasks` ; **enrich, fill-template, présentations sont SYNCHRONES bloquants** (annulés si on
    quitte) ; l'état de progression vit **en mémoire** (`_rapports_cache`, `_progression` → perdu au reboot
    backend) ; le suivi UI dépend d'un **flux SSE non reconnectable lié à l'onglet** (timeout 5 min) ; **aucun
    indicateur global « tâches en cours »** entre les pages.
  - **Cible** : *toute* action longue → **crée un Job en base immédiatement** → tourne **côté serveur** →
    écrit **progression + contenu partiel + résultat en base** → le frontend s'y **re-raccroche de partout**.
  - **Phase 1 — File de tâches durable (backend)** — ✅ **LIVRÉ & TESTÉ (01/07)** :
    - [x] **worker asyncio unique** (`services/job_worker.py`) démarré au `startup` : consomme les `jobs`
          `pending` (FIFO, `CONCURRENCE=2`, claim atomique `FOR UPDATE SKIP LOCKED`), met
          `running`→`completed/failed/cancelled`, écrit `resultat` + `progress`/`progress_message` **en base**.
          Registre de **handlers par type** (`@register`), `enqueue()`, `JobContext.report()`/`.cancelled`.
    - [x] **reprise au démarrage** : jobs restés `running` après un crash → remis `pending` (testé : log
          « Jobs orphelins remis en attente nb=1 » + re-exécution).
    - [x] **endpoints jobs unifiés** (`routers/jobs.py`) : `GET /api/jobs?statut=&type=&limit=`,
          `GET /api/jobs/{id}` (statut + progression + résultat), `POST /api/jobs/{id}/cancel`,
          `POST /api/jobs/demo` (validation). Colonnes `jobs.progress`/`progress_message` + statut `cancelled`
          + retrait du CHECK `type` (types applicatifs évolutifs) via ALTER idempotents (`database.py`).
    - **Testé bout-en-bout** : `pending→running (25→50→75→100%)→completed` avec résultat en base ; annulation
      (`running`→`cancelled`) ; reprise après restart. *(Handler `demo` fourni ; migration des vraies actions = Phase 2.)*
  - **Phase 2 — Convertir les actions bloquantes en jobs** :
    - [x] **`enrich` migré (pilote, 01/07)** : `POST /documents/{id}/enrich` **enqueue** un job `enrich`
          (`services/job_handlers.py`) et renvoie un **`job_id` immédiatement** (plus de requête bloquante) ;
          front `DocumentCard` « Relancer l'IA » **suit le job** (`jobsApi` + `suivreJob`). Testé :
          `pending→running(30%)→completed {ok:true, statut:'enriched'}`. Ajout `jobsApi` (list/get/cancel/demo).
    - [x] **`présentations` migré (01/07)** : `POST /presentations` enqueue un job `presentation` →
          `job_id` immédiat ; front `GEDPage` suit le job puis ouvre la visionneuse
          (`resultat.presentation_id`). Testé : `completed {presentation_id, nb_slides:5}`. **Gain majeur** :
          avant, l'endpoint bloquait 1–3 min (mixtral) → timeout navigateur probable.
    - [x] **`fill-template` migré (01/07) + câblé UI (16/07)** : `POST /generate/fill-template` enqueue un job
          `fill_template` (→ `job_id`) ; `GET /generate/fill-template/download/{job_id}` sert le DOCX une fois
          `completed`. **UI** : étape « Générer » du mode « Remplir un modèle » → bouton dédié qui suit le job puis
          télécharge le .docx (`generateApi.fillTemplate`). Le mode ne retombe plus sur la génération SSE.
    - [x] **indexation migrée (01/07)** : `POST /sources/{id}/index` **enqueue** un job `indexation`
          (`handler_indexation`) — secret SMB **déchiffré depuis la source** (jamais dans le job) ; réutilise
          `_index_local`/`_index_smb` (barre UI `/progression` inchangée) et **miroir** la progression mémoire
          → job (progress + message). Testé : `completed {total:0, indexes:0}` + `/progression` OK simultanément.
          Robuste au reboot (le handler ré-arme `_prog_demarrer`). *(Progression fine encore en mémoire ; la
          bascule UI → jobs viendra en Phase 3.)*
    - [x] **génération** (`/generate/report`) : **décision user 01/07 = garder le SSE live**. **Garde-fou UI
          livré** (`GenerationGuard`, monté dans `MainLayout`) : pendant `isGenerating`, bandeau « Rapport en
          cours d'écriture — ne fermez pas l'onglet » (toutes pages) + `beforeunload` (confirmation navigateur).
          Migration worker/progression-en-base **non requise** (le stream live est conservé).
    - [ ] streaming rapport : SSE **reconnectable et sans timeout** (reprise à l'offset depuis la base)
          **ou** bascule en **polling** du contenu partiel — au choix techniquement.
  - **Phase 3 — Frontend « tâches en cours » global** — ✅ **cœur livré (01/07)** :
    - [x] **store jobs global** (`stores/jobsStore.ts`) + widget **« Tâches en cours »** (`JobsIndicator`)
          dans le `Header`, monté sur **toutes** les pages : polling `GET /api/jobs` toutes les 2,5 s → badge
          (compteur actifs) + liste déroulante (progression, message, **annulation**) + récents (OK/échec/annulé).
    - [x] **re-raccrochage (base)** : les jobs vivant en base, revenir sur l'appli / **rouvrir le navigateur**
          fait réapparaître les tâches en cours (le widget les repolle). *(Persistance `localStorage` par flux
          — optionnel — non fait.)*
    - [x] **notification de fin** : **toast** à la complétion (succès/échec) même sur une autre page (détection
          de transition actif→terminé). *(Option **Web Notifications** OS — optionnel — non fait.)*
    - [ ] *(reste optionnel)* : persistance `localStorage` des job_id actifs par flux + notifications OS ; option
          **Web Notifications API** (notif OS) pour le cas « j'ai quitté le navigateur ».
  - **Note** : ne couvre pas le cas « PC éteint » (le worker tourne dans le conteneur backend, qui doit
    rester up) — c'est déjà le comportement attendu d'un service local.
- [x] **Page Doublons — refonte (2 retours user)** — ✅ **complet** :
  - [x] **3a — Choix du dossier à scanner** *(livré 02/07)* : `SmbFolderPicker` dans l'onglet
        « Fichiers indexés » scope la détection par préfixe de chemin (`/duplicates/indexed?prefixe=`).
        *(Le scan DISQUE legacy reste un scan global — l'approche indexée l'a supplanté.)*
  - [x] **3b — Doublons des fichiers INDEXÉS (hash + IA)** *(livré 02/07)* : `GET /duplicates/indexed`
        — exacts (`hash_sha256`) **et** quasi-doublons sémantiques (embeddings, seuil réglable) ;
        proposés dans `IndexedDuplicates` → flux corbeille/quarantaine.
  - [x] **3c — Bouton « Tester la présence » (dry-run) avant « Purger »** *(livré 16/07)* : Paramètres ›
        Maintenance → bouton **« Tester la présence »** → `POST /documents/purge-duplicates?dry_run=true`
        **simule** (groupes, nb, volume, aperçu garde/retire) SANS rien supprimer. Logique factorisée
        (`_calcul_purge`) partagée avec la purge réelle. Testé (253 doublons / 127 groupes).
- [ ] **Gros chantiers « à planifier » (demande user — plans inscrits)** : les 4 ont désormais un
      plan dans la ROADMAP :
  - **Réorganisation incrément 2** → section dédiée « Réorganisation d'arborescence par IA » +
    `docs/plan-reorganisation-arborescence.md` (drag&drop + appliquer au NAS via écriture SMB +
    undo ; garde le dossier parent). Plomberie SMB-write prête (corbeille).
  - **Vision images (llava) + OCR (glm-ocr)** → item « Reconnaissance d'images par IA locale »
    (passe vision en option/par lot sur les médias catalogués ; conversion HEIC→jpg ; seuil de taille).
  - **Menu horizontal (norme `_modele`)** → plan détaillé ci-dessous (section Cosmétique).
  - **Extraction ZIP** → item « Extraction des ZIP — détail (A/B) » (A : liste interne dans la fiche +
    bonus stats/résumé IA ; B : extraction du contenu interne via `process_zip`, lourd).
- [x] **Vue cartes (vs lignes) dans la GED** : **bascule cartes ⇄ liste** (toggle en haut, vue
      liste compacte avec actions par ligne) ; **résultats de recherche** dotés des mêmes actions
      (Aperçu / Fiche / Télécharger / Copier ; `chemin_copie` ajouté à la réponse `/search`).
      Actions factorisées dans `DocActions`.
- [x] **Tags éditables** : accessibles via le bouton **✨ Fiche** des cartes → tiroir `DocumentCard`
      (résumé éditable, catégorie, entités, **tags ajout/retrait** via `TagManager`).
      Reste optionnel : édition des tags **directement** sur la carte (sans ouvrir la fiche).
- [x] **Rationaliser la colonne de gauche de la GED** — fait :
  - **MODE** (Hybride/Texte/Sémantique) déplacé **sous la barre de recherche** (« Recherche : … »).
  - **CATÉGORIES / TAGS** masqués quand une **vue groupée** est active (doublon avec « Grouper
    par ») + indice dans le rail.
  - **IMPORTER (déposer/cliquer)** retiré de la GED (l'ajout passe par **Paramètres → Sources** ;
    le drag&drop reste dans **Rapports**).
- [ref] **Fonctionnement de la recherche** (réponse consignée) :
  - **Texte (full-text PostgreSQL fr)** : cherche les **mots** dans le **texte extrait**
    (corps + titres de paragraphes tels qu'extraits par Tika) **+ le nom du fichier** ;
    gère pluriels/conjugaisons (racines) mais reste **mot-à-mot**.
  - **Sémantique (embeddings)** : cherche par **sens/idée** → trouve des docs proches **sans les
    mêmes mots** (« voiture » ≈ « véhicule »). C'est « l'idée du document d'après l'IA ».
  - **Hybride** (défaut) : fusion **40 % texte / 60 % sémantique** (scores normalisés).
  - **Pas** cherchés par la requête : **catégorie / tags / résumé IA** (ce sont des **filtres**,
    pas du plein-texte). → **Décidé : on ne les ajoute PAS au plein-texte** — redondant (le
    sémantique trouve déjà par le sens, catégories/tags = filtres, le résumé reprend le texte
    déjà indexé). « Si inutile, on n'ajoute pas. »

### Cosmétique (pour plus tard)
- [x] **Retirer le titre « Matothèque »** redondant du top bar (déjà présent dans la barre
      latérale) — fait (Header n'affiche plus que les statuts services).
- [ ] **Menu en barre horizontale (haut)** au lieu de la **colonne verticale gauche**, en suivant
      la **norme du `_modele`** (modèle docker AgestiTC). **Plan** : (1) lire le layout du `_modele`
      (header + nav horizontale) ; (2) transformer `Sidebar.tsx` → barre de nav horizontale dans le
      `Header` (mêmes liens Rapports/GED/Doublons/Réorganiser/Paramètres + ←/→ + statuts services) ;
      (3) `MainLayout` : passer de `flex` (sidebar+contenu) à `flex-col` (header pleine largeur +
      contenu) ; (4) retirer la sidebar verticale ; vérif responsive. Pur layout, zéro logique métier.
- [x] **Navigation ← / →** : boutons précédent/suivant dans le **Header** (historique du
      navigateur via react-router) → fait. ⚠️ **Niveau page** (GED↔Rapports↔…) ; l'historique
      **interne fin** (filtre/recherche/fiche/aperçu non dans l'URL) reste un raffinement futur.
- [x] **Refonte page Paramètres — regroupée par fonction en accordéons** : 3 groupes pliables
      (`CollapsibleSection`, état mémorisé) — **Sources & indexation** (ouvert), **Génération**
      (prompts+templates, plié), **Système & IA** (stats+maintenance+services+à propos, plié).
      « v1.7.2 » codé en dur retiré de « À propos ». (détail plan ci-dessous)
      aujourd'hui 9 sections en **un seul long scroll** (Import direct · Sources · Dossiers indexés ·
      Prompts · Templates · Statistiques · Maintenance · Services & modèles IA · À propos).
      **Plan proposé** :
  - Composant réutilisable `CollapsibleSection` (titre + icône + chevron, ouvert/fermé,
    état mémorisé en `localStorage`). Option : mini sous-menu d'ancres en haut pour sauter à un groupe.
  - **Regroupement par fonction** (4 accordéons) :
    1. **📁 Sources & indexation** : Sources de fichiers · Dossiers indexés (+ surveillance auto) · Import direct
    2. **🤖 IA & services** : Services & modèles IA (URLs Tika/Ollama/n8n, test, statut, modèles, MAJ)
    3. **📝 Génération** : Prompts pré-enregistrés · Templates
    4. **⚙️ Système** : Statistiques · Maintenance · À propos
  - Par défaut : **Sources & indexation** ouvert, le reste plié (réduit le scroll).
  - Étapes : créer `CollapsibleSection` → envelopper chaque section existante (aucune logique
    métier modifiée, pur réagencement) → vérif visuelle.
- [ ] **Stats & boutons « rafraîchir » — fiabilité/fraîcheur** (Q/R consignée) :
      **Q : les statistiques sont-elles justes et dynamiques, ou faut-il un bouton rafraîchir ?
      Les boutons rafraîchir du projet sont-ils utiles ?**
      **R (constat)** : les **stats** sont **justes mais figées** — chargées **au montage** de la
      page Paramètres (`getDocumentStats`), re-fetchées après un upload/import sur la même page,
      mais **pas pendant une indexation en arrière-plan** ; **aucun bouton rafraîchir** sur la
      section Statistiques. Les **boutons rafraîchir** existent dans ~10 composants (liste docs,
      dossiers indexés, sources, modèles, services, doublons) → **utiles** là où la donnée change
      en tâche de fond.
      **Plan d'action** :
  - Ajouter un **bouton rafraîchir** (↻) sur la section **Statistiques** (réutilise `getDocumentStats`).
  - Optionnel : **auto-refresh** des stats toutes les N s **uniquement si une indexation est en
    cours** (lié à l'item « barre de progression d'indexation »).
  - **Audit** des boutons rafraîchir : garder ceux sur données dynamiques ; remplacer par
    **auto-refresh ciblé** là où c'est pertinent (ex. liste docs pendant indexation) pour éviter
    le clic manuel ; supprimer les éventuels redondants.
- [x] **Statut « en cours d'analyse »** lisible *(livré — badge ⏳ « Analyse IA en cours »)* : pour un doc pas encore enrichi par l'IA
      (`pending`/`extracted`), afficher un libellé clair type « ⏳ en cours d'analyse » au lieu de
      « pas de tags » (qui ressemble à un bug).
- [x] **Bouton « 🤖 Relancer l'IA » dans la fiche** (`DocumentCard`) *(livré 02/07/2026 — aiguillage auto texte→`enrich` / média→`analyze` (OCR/description) + fallback modèle même famille + message d'erreur honnête)* : forcer/relancer
      l'**enrichissement IA** d'un document à la demande (résumé, idée/thème, catégorie, tags,
      entités). Utile pour les fiches **pauvres** — ex. constaté sur **`L1-P.4 DPGF.xlsx`** : fiche
      quasi vide (pas d'idée/thème). Maintenant fiable grâce au fix `format=json`. Mise en œuvre :
      endpoint dédié `POST /documents/{id}/enrich` (ré-exécute `_enrich` sur le texte déjà extrait,
      sans re-télécharger) **ou** réutiliser `POST /extract/{id}` (relance pipeline complet) ;
      bouton avec état « en cours » (spinner) + rafraîchissement de la fiche au retour.
- [x] **Déplacer un fichier vers une corbeille « À supprimer »** *(livré — `A-SUPPRIMER-MATOTEQUE/` à la racine du partage, journal + restauration, écriture SMB)* (depuis n'importe quel fichier
      de la GED) : **icône discret mais sans équivoque** sur la carte + **confirmation** avant
      déplacement (2 boutons **Annuler / Confirmer**). Étend la **quarantaine des doublons**
      (`DOUBLON-MATOTEQUE`) à **tous** les fichiers. Dossier cible type `A-SUPPRIMER-MATOTEQUE/`
      à la racine du partage ; retirer aussi de l'index ; idéalement **journal + annulation**.
      ⚠️ **Prérequis : écriture SMB** (déplacer un fichier sur le NAS) — capacité nouvelle
      (`pysmb` rename/createDirectory/deleteFiles), aujourd'hui on ne fait que **lire**.
      **Destructif** → garde-fous. Mutualisable avec **Réorganisation incrément 2** (même
      plomberie SMB-write + undo).
- [~] **🐞 Fiabilité enrichissement IA — `enriched` sans `metadonnees_ia`** *(02/07 : en grande partie traité — lot « ré-analyser » élargi aux `enriched`-vides, **nom de fichier** dans le prompt, **description** image/PDF, borne `niveau_confidentialite`, fix octet NUL ; reste : ne pas marquer `enriched` si la méta a échoué)* : ~51 docs ont du
      texte (>500 car) mais **aucune fiche IA**. Cause : le modèle rapide renvoie parfois une
      réponse **non-JSON** → `JSONDecodeError` attrapé (extraction.py:394), méta **ignorée
      silencieusement**, mais le doc reste marqué `enriched`. Fix : forcer **`format=json`**
      côté Ollama + **1 retry**, et **ne pas marquer `enriched`** si la méta a échoué (statut
      distinct / re-enrichissable). Concerne **toutes** extensions (pas spécifique XLSX/TXT/ZIP).
- [~] **Extraction des ZIP — détail** *(Option A LIVRÉE 13/07 : `GET /documents/{id}` expose `contenu_archive`
      (parse best-effort du texte Tika) + section « 📦 Contenu de l'archive » repliable dans `DocumentCard`.
      Reste Option B = extraction interne réelle, plus lourde)* : `process_zip` (Tika `/rmeta`,
      1 doc par fichier interne) **existe déjà mais seulement pour les ZIP UPLOADÉS** ; les ZIP
      **indexés via SMB** passent par `process_file` → uniquement la **liste des noms**. Deux options :
  - **A. Liste des fichiers dans la fiche IA** (léger, = la demande) ← **recommandé en premier**.
    **Plan** : (1) backend — helper qui parse le `texte_extrait` du ZIP en liste propre de
    chemins internes (lignes non vides), exposé dans le détail du doc (`contenu_archive: [...]`)
    quand `extension == zip/rar/7z` ; (2) frontend — dans `DocumentCard`, si ZIP, section
    **« 📦 Contenu de l'archive (N fichiers) »** (liste, voire petit arbre repliable). Aucune
    décompression, zéro risque, le ZIP reste 1 entrée.
    **🎁 Bonus « contexte »** (toujours léger, sur les seuls **noms**) :
    - **Stats d'archive** : répartition par type (`12 PDF · 4 XLSX · 30 images…`), **dossiers de
      1er niveau**, nombre total de fichiers → aperçu immédiat du contenu.
    - **Résumé IA de l'archive** (optionnel) : 1 appel LLM **sur la liste des noms** (pas le
      contenu) → « cette archive contient surtout… » + quelques tags. Corrige le cas actuel où
      un ZIP n'a ni résumé ni tags. Coût négligeable (1 petit appel, pas N).
  - **B. Extraction du contenu interne** (lourd) : router les ZIP SMB vers `process_zip` →
    chaque fichier interne devient cherchable (texte + IA). **Que deviennent les fichiers ?**
    **Rien n'est décompressé** : Tika ne lit que le **texte** de chaque fichier interne, stocké
    comme `Document` **virtuel** (`chemin = …zip::nom_interne`, `taille` = taille du texte). Le ZIP
    reste intact (juste téléchargé en temp le temps de l'analyse). Conséquences : **1 ZIP = N docs**
    (explosion), **gros coût IA**, et sous-fichiers **non ouvrables** tels quels (Aperçu/Téléch. ne
    gèrent pas `zip::` → faudrait extraire à la volée). Garde-fous : taille max, médias internes
    catalogués léger. À faire seulement si on veut chercher **dans** les zips.

---

## 🎯 Besoins prioritaires (le « pourquoi » du projet)

### Phase 1 — Retrouver facilement les fichiers du NAS (v1.8.x)
*Besoin n°1. Le moteur existe ; il faut le brancher sur le vrai volume NAS-MATO et fiabiliser l'usage quotidien.*

- [x] **🔁 Refonte « Dossiers surveillés » → Sources SMB configurables** : ✅ fait — choix du
      serveur (NAS-MATO), **partages SMB listés**, navigation + **cases à cocher**, indexer la
      sélection ; source générique `{type, hôte, chemin, identifiants chiffrés}` en base
      (ajouter un autre serveur sans toucher au compose). Validé sur le vrai NAS.
- [ ] **Indexation continue** → **entrée unique : cf. « ② Indexation continue » (Session 17/07)** +
      plan [docs/plan-indexation-continue.md](docs/plan-indexation-continue.md). *(Fusionne 4 doublons
      qui traînaient ici : « indexation continue/planifiée », « watcher n8n en continu », et 2× « première
      indexation complète ». ⚠️ Ils disaient « watcher n8n ou cron » — **la décision du 17/07 écarte n8n**
      au profit d'un scan incrémental dans le worker.)*
- [x] **Première indexation complète** du volume NAS *(faite — 81 536 doc. sur `nas-mato TOM`,
      56 k+ documents indexés ; barre de progression X/Y livrée)*.
- [ ] Valider la **recherche hybride** sur le vrai corpus (pertinence, vitesse) ; ajuster la pondération si besoin
- [ ] Barre de recherche : aperçu du document + **chemin NAS** + bouton « ouvrir l'emplacement »

### Phase 2 — Identifier et gérer les doublons (v1.9.x) — 🟢 en grande partie livré
*Besoin n°2. Détection disque + déplacement vers DOUBLON-MATOTEQUE (pas de suppression).*

- [x] **Scan disque des doublons** (groupe par taille → SHA256), endpoint `GET /api/duplicates`
- [x] **Écran « Doublons »** : groupes + **case à cocher** par fichier (pré-cochées sauf le « à garder »)
- [x] **Déplacement** (`POST /api/duplicates/quarantine`) vers `DOUBLON-MATOTEQUE/` + **modal de confirmation**
- [x] Garde-fous : jamais de suppression (déplacement réversible), anti path-traversal, exclu de l'indexation
- [ ] **Dédup en 3 passes** (repris d'`ant-tool`) : taille → hash partiel 4 Ko → hash complet,
      pour accélérer le scan sur gros fichiers réseau (NAS)
- [ ] **Quasi-doublons** : détection par similarité sémantique des embeddings (seuil réglable)
- [ ] Bouton « ouvrir l'emplacement » + aperçu du fichier dans chaque ligne
- [ ] **Miniatures / aperçu** des fichiers en double pour faciliter la comparaison visuelle
- [ ] **Photos** : détection des images **floues** (ex. variance du Laplacien) → proposer
      de garder la plus nette et éliminer les floues
- [ ] **Reconnaissance d'images par IA locale** (Q/R consignée) :
      **Q : existe-t-il une IA locale pour reconnaître les photos/images (tout type) ?**
      **R : oui, déjà installées via Ollama** — `llava:latest` (vision : décrit le contenu d'une
      image → description + tags) et `glm-ocr:latest` (OCR : texte dans l'image / scan). 100 % local.
      - Formats **standards** (jpg/png/webp/gif/bmp) lus directement par llava ; **exotiques**
        (heic/raw/cr2/nef/tiff/psd) → **conversion préalable** en jpg/png nécessaire
        (`pillow-heif` / ImageMagick) — le NAS a bcp de **HEIC** (iPhone).
      - **Intégration proposée** : passe **vision en option** (à la demande / par lot) sur les
        médias catalogués → llava = description + tags, glm-ocr = texte. **Pas en masse auto**
        (coût : 1 inférence + téléchargement par image). Étend l'« indexation média raisonnée ».
      - **Remarque utilisateur (constat)** : aujourd'hui un PNG (ex. `help.png`) **n'a aucune
        description** dans sa fiche → **normal** : les images sont cataloguées *léger* (pas d'IA).
        La description type « icône d'aide / bouée de sauvetage » viendra **avec cette passe
        vision** (pas encore codée). NB : utile surtout sur les **vraies photos** ; sur une micro
        icône 48×48 (5 Ko) la valeur est faible → prévoir un **seuil de taille** avant d'appeler llava.
      - **Exemple concret (utilisateur)** : photo avec un chien → tag **`chien`**. ✅ Faisable
        avec **llava** (description du contenu → tags d'objets/scène). C'est le cœur de cette passe.
- [ ] **Reconnaissance faciale — identifier la même personne** (Q/R consignée) :
      **Q : si je tague un visage « moi », Matothèque peut-il me reconnaître sur d'autres photos
      et me taguer d'office ?** **R : oui, faisable 100 % local, mais c'est une capacité SÉPARÉE**
      de llava (qui décrit, mais ne ré-identifie pas les personnes). Stack dédié :
      **détection de visages + embeddings faciaux** (ex. `InsightFace` / `face_recognition`/dlib,
      local, **pas via Ollama**) → on calcule un vecteur par visage, on **étiquette une fois**
      (« moi ») puis on **matche par similarité** sur les autres photos (+ clustering pour
      regrouper les visages inconnus). Chantier à part entière : détection → embeddings → galerie
      de personnes → auto-tag avec seuil de confiance + validation manuelle.
      ⚠️ **Vie privée / RGPD** : reconnaissance de personnes = données biométriques sensibles ;
      OK en usage **perso/local** sur ses propres photos, à cadrer (jamais hors NAS).

### Phase 3 — Grouper / parcourir les documents (v1.10.x)
*Besoin n°3 : grouper par extension, thème/catégorie, …*

- [x] **Liste « tout afficher »** dans la GED : voir tous les documents indexés **sans** lancer
      de recherche (bouton « Tout afficher » + grille paginée « Charger plus »)
- [x] **Ouvrir / consulter un document** depuis la liste (le navigateur ne peut PAS lancer
      l'explorateur Windows ni le logiciel associé → on fournit) :
  - [x] **Aperçu** intégré (`GET /documents/{id}/file` + modal `DocumentPreview` : PDF iframe,
        image, texte/texte extrait ; fallback download pour HEIC/formats non rendus)
  - [x] **Télécharger** l'original (`?download=true`, backend récupère depuis NAS/local)
  - [x] **Copier le chemin** (`chemin_copie` UNC `\\hote\partage\…`) à coller dans l'explorateur
- [x] **Vue groupée** de la GED : regroupement par **extension** (PDF, DOCX, XLSX…)
- [x] Regroupement par **thème / catégorie IA** (avec bucket « non classé ») et par **tags**
  - [x] `GET /documents/groups?by=…` + filtre `?categorie=` ; UI « Grouper par » dans « Tout
        afficher », groupes repliables à chargement paresseux (`AllDocumentsView.tsx`) — testé
- [ ] Regroupement par **dossier source** NAS
- [ ] Facettes combinables (extension × thème × date) + compteurs par groupe

---

### Administration des modèles IA — 🟢 livré
*Gérer les modèles Ollama directement depuis Matothèque (Paramètres).*

- [x] **⚠️ Détection des mises à jour** : digest local vs manifest registre Ollama →
      badge ⚠️ « MAJ », ✓ à jour, ? custom hors registre (`GET /api/system/models?check_updates`)
- [x] **Bouton mettre à jour** un modèle (`ollama pull`) avec progression en streaming
      (`POST /api/system/models/pull`)
- [ ] (option) supprimer / télécharger un **nouveau** modèle depuis l'UI

---

### Réorganisation d'arborescence par IA (plan validé — à coder)

📄 **Plan détaillé : [docs/plan-reorganisation-arborescence.md](docs/plan-reorganisation-arborescence.md)**

En bref : l'IA **propose** une arborescence (hybride, ajustable en drag & drop),
**aperçu virtuel** → bouton **« Appliquer au NAS »** (déplacement physique avec
garde-fous + journal d'annulation). Réutilise classification IA + déplacement
fichiers (doublons) + sources local/SMB.

**Contraintes de proposition (retours utilisateur) :**
- **Conserver au minimum le dossier parent** : ne pas tout aplatir à la racine. La
  réorganisation part **après la racine du partage** (`\\IP\partage\` ou `smb://IP/partage/`)
  et **garde le 1er niveau de dossier** comme base ; l'IA réorganise **à l'intérieur**.
- Toujours **aperçu uniquement** tant que l'utilisateur n'a pas cliqué « Appliquer au NAS ».

---

### 🎬 Épic — Sélection multiple GED + Présentations (diaporama IA) (à coder — plan validé à confirmer)

> Idée utilisateur (27/06). Gros chantier → découpé en **incréments**, **1 branche `feature/*` par
> incrément** (GitFlow strict). Plan d'action détaillé proposé avant de coder.

**Inc. 0 — GED : sélection multiple (cases à cocher) + barre d'actions de masse** — ✅ livré
- [x] **Case à cocher** sur chaque carte/ligne « fichier » (vue cartes ET liste ET résultats de
      recherche). Sélection persistée (`gedSelectionStore` Zustand, set d'ids).
- [x] **Barre d'actions flottante** quand ≥1 sélectionné : compteur + **Désindexer en masse** +
      **Corbeille en masse** (avec confirmation) + Tout désélectionner. Rafraîchit la liste après.
- [x] Base technique (`gedSelectionStore`) réutilisable : présentations (Inc.2c/2), autres actions de masse.

**Inc. 2c — Bouton « Créer une présentation » (dès ≥2 fichiers sélectionnés)** — ✅ livré
- [x] Bouton (icône **+ texte**, violet) dans la **barre d'actions de masse** dès **≥2 sélectionnés**
      → génère la présentation puis ouvre la visionneuse dans un **nouvel onglet**.

**Inc. 1 — Page Rapports en sections pliables ; section « Prompt IA » fixe en 1ʳᵉ** — ✅ livré
- [x] Composant réutilisable **`CollapsibleSection`** (état mémorisé en localStorage).
- [x] **Section « Assistant — Trouver des documents (IA) »** = **première**, pliable, sur Rapports.
  - [x] **1a — Trouver des documents depuis une idée** : besoin en langage naturel → l'IA déduit
        les **pièces attendues** (`POST /assistant/pieces`, mistral) → **recherche hybride** par pièce
        → fichiers proposés **cochables** (rejoignent la sélection du rapport). Validé (« dossier de
        location » → 8 pièces + fichiers).
  - [x] **1b — Synthèse d'un groupe** : couvert par le **mode « Rapport libre »** (multi-docs) —
        raccourci/indication ajouté dans l'assistant.
  - [x] **Toute la config Rapports en sections pliables** (Assistant · Mode · Modèle · Template ·
        Instructions/Candidats), état mémorisé ; section **IMPORTER retirée** de Rapports (upload
        via Paramètres → Import direct ; indexation via Sources).
  - [ ] Reste optionnel : entrée « depuis une **liste** » explicite dans l'assistant.

**Inc. 2 — Génération de présentation (diaporama) par IA locale** — ✅ livré

- [x] **2b** : l'IA (mixtral par défaut) structure le contenu en **slides JSON** (titre + points)
      à partir des docs sélectionnés (résumé/extrait) → modèle `Presentation` + `POST /presentations`.
- [x] **Export PPTX téléchargeable** (`python-pptx`, `GET /presentations/{id}/pptx`) — validé (7 diapos).
- [x] **Visionneuse intégrée** (`reveal.js`, page `/presentation/:id` hors layout) : **nouvel onglet**,
      **plein écran**, navigation **flèches ←/→ + clic**, **Lecture/Pause** (auto-slide), bouton **PPTX**.
- [~] **2a** (renvoyer sur la GED pour sélectionner) : couvert différemment — la sélection se fait
      **dans la GED** (cases à cocher) et le bouton « Créer une présentation » lance le flux. OK.
- [ ] Reste optionnel : montage/édition des slides (réordonner, éditer) ; « Surprends-moi » explicite ;
      images/extraits dans les diapos.

**Décisions prises (27/06)** : viewer = **reveal.js** ; **PPTX + visionneuse lecture seule** d'abord
(montage intégré = plus tard / outil tiers) ; bouton **icône + texte** dans la barre d'actions.
Reste à cadrer : périmètre de l'« assistant de constitution de dossier » (1a) — **Inc. 1** non démarré.

---

## 🚀 Phase 4 — Mise en production ✅ FAITE (autrement que prévu)

> **⚠️ Cette phase décrivait un déploiement qui n'a PAS eu lieu** (NAS Synology + CI GHCR).
> La prod tourne depuis le 14/07 sur le **LXC 102 « docker » de Proxmox (192.168.42.83)**, avec des
> images **buildées à la main depuis Windows** (`build-push.ps1`) et publiées sur le **registre Gitea**
> `git.agesti.fr/agestitc/docflow-{backend,frontend}`. Procédure réelle :
> [docs/proxmox-deployment.md](docs/proxmox-deployment.md).

- [x] **Mise en production — LXC Proxmox** *(v1.15.0 le 14/07 · **v1.16.0 le 17/07**)*.
- [~] **Sauvegarde** : `pg_dump` manuel livré (bouton Paramètres) ; **automatisation à faire**
      (cf. « 💾 Sauvegarde de la base de données »).
- [ ] ~~Release CI (`scripts/release.ps1`) → images **GHCR**~~ — **ABANDONNÉ** : GHCR/GitHub Actions =
      **vestige non utilisé** (le workflow échoue au push, sans impact : ce n'est pas le registre de la
      prod). Le registre réel est **Gitea**, et il **ne build pas** (aucun runner). `release.ps1` suppose
      encore ce rail CI → à réécrire ou supprimer si on veut un jour automatiser le build.
- [ ] ~~Déploiement Container Manager (Synology)~~ · ~~`.env.nas` validé~~ — **ABANDONNÉ** : le NAS
      Synology n'est **pas** la cible de déploiement (il est **source de documents** via SMB).
      `docker-compose.nas.yml` + `docs/synology-deployment.md` conservés à titre de référence.

---

## 📝 Backlog — idées à cadrer (besoins 4+)

Pistes retenues, à prioriser/chiffrer avant d'en faire des phases :

- [ ] **Renommage automatique** des fichiers selon une convention (date, thème, entités IA détectées) — proposition + validation, jamais en écrasant l'original sans confirmation
- [ ] **OCR des scans** : fallback `glm-ocr`/Tesseract quand Tika ne sort pas de texte (PDF images, photos de documents)
- [ ] **Partage & permissions** : auth + rôles (utilisateur / admin / super-admin, cf. modèle), accès par dossier/catégorie, liens de partage internes
- [ ] **Alertes / notifications** : nouveau document, doublon détecté, échec d'indexation (mail + webhook n8n/Discord, cf. modèle)
- [ ] **Réindexation au renommage** : si un dossier est renommé/déplacé sur le NAS, détecter
      (par hash : même contenu, nouveau chemin) et mettre à jour l'index au lieu de créer des
      doublons / laisser des entrées orphelines
- [x] **Gestion des dossiers indexés (persistante)** : après indexation, la Source **reste** et
      affiche un **arbre des dossiers indexés** (SOURCE → dossier parent déplié → sous-dossiers
      pliés) avec **cases à cocher + tout cocher/décocher** pour **ajouter/retirer** des dossiers
      de l'index (désindexer = retirer de la GED, sans toucher aux fichiers du NAS)
  - [x] Backend : `GET /api/sources/{id}/indexed` (arbre dérivé des docs) + `POST .../deindex`
        (retire de l'index) — testé (745 docs, share `home`)
  - [x] Frontend : `IndexedFolders.tsx` — bouton « Indexés » par source, arbre repliable
        (parent déplié / sous-dossiers pliés) + cases à cocher + tout cocher/décocher +
        bouton « Retirer de l'index » (modale de confirmation) — testé (745 docs)
- [ ] **Système de log / audit** : « qui a fait quoi » — journal des actions (indexation,
      déplacement doublons, ajout/suppression source, désindexation…) avec date + acteur,
      consultable dans l'UI (et lié aux rôles une fois l'auth en place)
- [ ] **Indexation média raisonnée** : ne pas télécharger des Go de vidéos via SMB juste pour
      cataloguer — cataloguer par métadonnées (nom/taille/EXIF) sans fetch complet pour les gros médias
- [x] **🧹 Normalisation tags/catégories (accents + casse)** — *backend LIVRÉ 12/07, **UI livrée 16/07*** :
      config `acronymes` éditable (`[{sigle, definition}]`, 31 par défaut) + `POST /api/system/normaliser-metadata`
      (fusionne variantes accent/casse ; acronyme connu → MAJUSCULES ; sauvegarde `storage/backup-normalisation.json`,
      réversible/idempotent). **UI** : Paramètres › Maintenance → bouton « Normaliser » + éditeur du dictionnaire
      d'acronymes (`AcronymesEditor`, auto-save). Testé live (975 tags + 29 catégories normalisés).
- [x] **📚 Regroupements de documents — analyses & rendus formatés** *(demande user 12/07 · backend LIVRÉ 13/07 ·
      **UI livrée 16/07**)* : table `regroupements` + CRUD `/api/regroupements` + `POST /{id}/analyser` (tâche
      durable → rendu markdown stocké, exportable). **UI** : page `/regroupements` (liste + détail : docs, consigne
      + modèle propres au groupe, « Analyser » suivi du job, rendu markdown + export PDF/DOCX) ; **création depuis
      la GED** (bouton « Regroupement » dans la barre d'actions de masse → modale de nommage). Lien sidebar. Testé.
  - Créer un **« regroupement »** nommé = ensemble de documents sélectionnés, **persistant** (réutilisable).
  - **Analyse du regroupement** avec **prompt + choix du modèle** (routage par usage) → **rendu dans un
    document PRÉ-FORMATÉ** (réutilise le pipeline Rapports/génération + export PDF/DOCX).
  - **Analyse SPÉCIFIQUE** propre à ce regroupement (prompt/consigne dédiés au groupe, **rejouable**),
    distincte d'un rapport ad hoc.
  - Base technique déjà présente : sélection multiple GED (`gedSelectionStore`), génération
    (`/generate/report`), export. Manque : **persistance du regroupement** (table + CRUD) + attache
    prompt/modèle/rendu + éventuel template de mise en forme.
- [x] **💾 Sauvegarde de la base de données — Phase 2 AUTO livrée (17/07)** :
  - **🔴 Bug racine corrigé** : ni le backend ni le worker ne montaient `storage/backups` (compose prod)
    → **toute sauvegarde, même MANUELLE, était éphémère** (perdue à chaque recréation de conteneur, donc
    à chaque déploiement) → `/system/backups` vide en prod. Compose : `storage/backups` monté sur
    init+backend+worker via **`${BACKUP_DIR:-./storage/backups}`** (pointer vers un montage **externe**
    NAS/NFS recommandé — survit à la perte du LXC ; idée user).
  - **Auto** : `job_worker._backup_scheduler` — `pg_dump` toutes les N h dans le worker + purge
    (`backup.prune`), config à chaud `backup_auto_heures` (défaut 3, 0=off) / `backup_retention`
    (défaut 8). UI Paramètres → Maintenance (intervalle + rétention). Doc `proxmox-deployment.md` +
    `.env.proxmox.example` (montage NAS). *(auto désactivé en DEV pour ne pas remplir le disque.)*
  - ⚠️ **Incident 17/07 qui l'a motivé** : la base prod a été **réinitialisée** lors du déploiement
    1.17.0 (80k docs perdus). **Restaurée dev→prod le 17/07** (dump v16, 56 081 docs + 72 923 embeddings ;
    pièges : format pg_dump v17≠serveur v16 → restaurer via conteneur backend ; disque LXC saturé →
    `pct resize +10G`). Reconfig post-restau : mot de passe NAS + URLs Ollama/n8n (config venait de dev).
  - [ ] **Montage NAS externe pour les backups** *(user 17/07 — « plus tard, pas besoin aujourd'hui »)* :
    monter un partage NAS (NFS/CIFS) sur le LXC et pointer **`BACKUP_DIR`** dessus (`.env`) → les dumps
    auto atterrissent **hors du LXC** (survivent à une perte du conteneur/LXC). Aujourd'hui : backups sur
    `./storage/backups` (disque LXC, persisté). CIFS → options de montage `uid=10001,gid=10001`.
  - [ ] **Épingler `postgresql-client-16`** dans `backend/Dockerfile` (dépôt PGDG) → les dumps auto
    seront en **v16**, restaurables directement par le conteneur postgres (fin du piège v17/v16).
  - **Évolutions sécurité/stockage demandées (user 17/07 soir)** :
    - [ ] **1 — Chiffrer la sauvegarde** : option « sauvegarde chiffrée » → **demander une passphrase**
      (dump `pg_dump | gpg -c` ou équivalent). La passphrase n'est PAS stockée en clair ; restauration =
      re-saisie. À câbler avec le manuel ET l'auto.
    - [ ] **2 — Suppression d'une sauvegarde protégée par mot de passe** : bouton « Supprimer » par ligne
      du tableau, **garde-fou = mot de passe** (créer d'abord un **mot de passe de protection des backups**
      dédié). Empêche une suppression accidentelle/malveillante d'un dump.
    - [ ] **3 — Sauvegarder sur le NAS / emplacement réseau** : au-delà de `BACKUP_DIR` (montage LXC),
      prévoir une **connexion réseau configurable** (SMB/NFS/…) depuis l'UI pour écrire les dumps sur le
      NAS ou un autre stockage — recoupe « Montage NAS externe » ci-dessus, mais **piloté depuis l'appli**.
      *(⚠️ 100 % local : cette connexion réseau reste sur le LAN — pas de sortie Internet.)*
- [~] **💾 (Phase 1, historique)** *(manuelle livrée 12/07 + **bouton UI livré 16/07** :
      `POST /api/system/backup-db` (pg_dump `-Fc` → `storage/backups/`, ~600 Mo) + `GET /system/backups` ;
      Paramètres › Maintenance → bouton « Sauvegarder » + date/taille de la dernière. Restauration = `pg_restore`
      documentée. Phase 2 auto/planifiée = plus tard)* (donnée critique : index documents, **métadonnées IA**,
      embeddings, plans de réorganisation, journal corbeille…) — *(demande user 02/07)* :
  - **Phase 1 — manuel (d'abord)** : **dump PostgreSQL** (`pg_dump`) déclenchable depuis Paramètres
    (bouton) et/ou script documenté, + **restauration** ; sortie stockée **hors conteneur**
    (volume/host). Inclure au besoin les fichiers `storage/` (ex. `backup-accents.json`).
  - **Phase 2 — automatique (future release)** : sauvegarde **planifiée** (cron / worker durable),
    **rotation + rétention**, éventuellement **chiffrée**. **S'inspirer de `sapyn`** (mécanisme de
    backup déjà en place dans ce projet — cf. `O:\Github\sapyn`).

---

## 💭 Réflexion pour plus tard (idées non planifiées — NE PAS CODER sans validation)

> Pistes à mûrir. Rien ici ne doit être implémenté tant que l'utilisateur ne l'a pas explicitement
> sorti de cette section.

- 🅿️ **Responsive / multi-équipement (PC · tablette · smartphone)** — *⏸️ NE PAS CODER pour le
  moment* : l'utilisateur **préfère la navigation verticale actuelle** (01/07). À reconsidérer plus
  tard uniquement : aujourd'hui **desktop-first** (sidebar fixe `w-52`) ; piste = **menu burger**
  sous une largeur donnée, sidebar repliable, grilles/tuiles adaptatives, champs & modals tactiles,
  audit page par page. **Décision : on garde la nav verticale pour l'instant.**

---

## Changelog versionné

Le détail des versions est tenu dans [CHANGELOG.md](CHANGELOG.md).
Chaque release passe par `scripts/release.ps1 -Version X.Y.Z -Message "…"`
(bump `VERSION` + tag `vX.Y.Z` → CI build + verify → images GHCR).
