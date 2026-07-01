# ROADMAP — Matothèque

> GED locale intelligente (extraction Tika + IA Ollama + recherche sémantique
> pgvector), 100 % locale. Repo `AgestiTC/ged-local` · cible **NAS-MATO**
> (Synology, 192.168.42.200) · version courante **1.8.0**.

## Statut général

🟢 **Projet avancé** — socle technique complet et fonctionnel (extraction,
indexation, recherche hybride, GED, rapports, comparatif). La suite consiste à
**brancher sur le NAS** et à couvrir les besoins métier prioritaires.

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
- [~] **Réorganisation d'arborescence par IA** — incrément 1 livré (proposition + aperçu) ;
      reste l'**incrément 2** : édition drag & drop + application (virtuel → NAS) — cf. plan dédié.
      **Planifié (décision 27/06 : à faire dans un créneau dédié)**. ✅ Plomberie prête : l'**écriture
      SMB** (`ensure_dir`/`move_file`, validée via la corbeille) couvre déjà l'« Appliquer au NAS » ;
      réutiliser aussi le **journal + restauration** de la corbeille pour l'undo. Contrainte :
      conserver au minimum le **dossier parent** (cf. section dédiée plus bas).

---

## 🔎 Retours d'usage (suivi vivant)

> Consigné **au fil des questions/retours** pendant l'utilisation réelle, pour un suivi
> fiable des deux côtés. On coche/déplace au fur et à mesure.

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
- [ ] **Assistant « Trouver des documents » — LENTEUR** (retour user 29/06 « Matothèque le trouvait plus
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
- [ ] **🔴 BUG — l'indexation GÈLE tout le backend** (découvert 29/06 en testant) : pendant une indexation
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
      dossier indexé, sera-t-il indexé automatiquement ? »).
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
- [ ] **Connecteurs de sources externes en LECTURE — section dédiée dans Paramètres** (question user 29/06 :
      « peut-on prévoir une connexion Drive ? en lecture » + « prévoir les connecteurs / section dans
      Paramètres »).
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
    - [x] **`fill-template` migré (01/07)** : `POST /generate/fill-template` enqueue un job `fill_template`
          (→ `job_id`) ; nouveau `GET /generate/fill-template/download/{job_id}` sert le DOCX une fois
          `completed`. *(Endpoint non encore câblé dans l'UI — le mode « Remplir un modèle » reste à brancher.)*
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
- [ ] **Page Doublons — refonte (2 retours user)** :
  - [ ] **3a — Vue « tree » pour choisir le dossier à scanner** : aujourd'hui pas de sélection de
        périmètre ; ajouter un **arbre** (browse SMB/local déjà existant) pour **choisir le dossier**
        sur lequel chercher les doublons (au lieu d'un scan global figé).
  - [ ] **3b — Doublons des fichiers INDEXÉS proposés par l'IA** : détecter les doublons **parmi les
        documents déjà indexés** (exacts par `hash_sha256`, et **quasi-doublons** via similarité des
        embeddings) et les **proposer** dans l'UI → réutiliser le flux **déplacer/supprimer**
        (quarantaine `DOUBLON-MATOTEQUE` / corbeille). Complète le scan disque actuel.
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
- [ ] **Statut « en cours d'analyse »** lisible : pour un doc pas encore enrichi par l'IA
      (`pending`/`extracted`), afficher un libellé clair type « ⏳ en cours d'analyse » au lieu de
      « pas de tags » (qui ressemble à un bug).
- [ ] **Bouton « 🤖 Relancer l'IA » dans la fiche** (`DocumentCard`) : forcer/relancer
      l'**enrichissement IA** d'un document à la demande (résumé, idée/thème, catégorie, tags,
      entités). Utile pour les fiches **pauvres** — ex. constaté sur **`L1-P.4 DPGF.xlsx`** : fiche
      quasi vide (pas d'idée/thème). Maintenant fiable grâce au fix `format=json`. Mise en œuvre :
      endpoint dédié `POST /documents/{id}/enrich` (ré-exécute `_enrich` sur le texte déjà extrait,
      sans re-télécharger) **ou** réutiliser `POST /extract/{id}` (relance pipeline complet) ;
      bouton avec état « en cours » (spinner) + rafraîchissement de la fiche au retour.
- [ ] **Déplacer un fichier vers une corbeille « À supprimer »** (depuis n'importe quel fichier
      de la GED) : **icône discret mais sans équivoque** sur la carte + **confirmation** avant
      déplacement (2 boutons **Annuler / Confirmer**). Étend la **quarantaine des doublons**
      (`DOUBLON-MATOTEQUE`) à **tous** les fichiers. Dossier cible type `A-SUPPRIMER-MATOTEQUE/`
      à la racine du partage ; retirer aussi de l'index ; idéalement **journal + annulation**.
      ⚠️ **Prérequis : écriture SMB** (déplacer un fichier sur le NAS) — capacité nouvelle
      (`pysmb` rename/createDirectory/deleteFiles), aujourd'hui on ne fait que **lire**.
      **Destructif** → garde-fous. Mutualisable avec **Réorganisation incrément 2** (même
      plomberie SMB-write + undo).
- [ ] **🐞 Fiabilité enrichissement IA — `enriched` sans `metadonnees_ia`** : ~51 docs ont du
      texte (>500 car) mais **aucune fiche IA**. Cause : le modèle rapide renvoie parfois une
      réponse **non-JSON** → `JSONDecodeError` attrapé (extraction.py:394), méta **ignorée
      silencieusement**, mais le doc reste marqué `enriched`. Fix : forcer **`format=json`**
      côté Ollama + **1 retry**, et **ne pas marquer `enriched`** si la méta a échoué (statut
      distinct / re-enrichissable). Concerne **toutes** extensions (pas spécifique XLSX/TXT/ZIP).
- [ ] **Extraction des ZIP — détail (à arbitrer avant code)** : `process_zip` (Tika `/rmeta`,
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
- [ ] **Indexation continue / planifiée** d'une source (watcher n8n ou cron) — actuellement à la demande
- [ ] **Première indexation complète** du volume NAS + suivi de progression
- [ ] Activer le **watcher n8n en continu** (détection nouveaux/modifiés) + cron de réindexation
- [ ] **Première indexation complète** du volume + suivi de progression
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

## 🚀 Phase 4 — Mise en production sur NAS-MATO (v2.0.0)

- [ ] Release CI (`scripts/release.ps1`) → images GHCR `docflow-backend` / `docflow-frontend`
- [ ] Déploiement Container Manager (Synology) — cf. [docs/synology-deployment.md](docs/synology-deployment.md)
- [ ] `.env.nas` validé (volumes NAS, Ollama hôte) + smoke test `scripts/validate.ps1`
- [ ] Plan de sauvegarde (bind-mounts `./bdd-` / `./data-`) validé

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

---

## Changelog versionné

Le détail des versions est tenu dans [CHANGELOG.md](CHANGELOG.md).
Chaque release passe par `scripts/release.ps1 -Version X.Y.Z -Message "…"`
(bump `VERSION` + tag `vX.Y.Z` → CI build + verify → images GHCR).
