# Changelog — Matothèque (ex-DocFlow AI)

Toutes les modifications notables de ce projet sont documentées ici.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/)
Versioning : [Semantic Versioning](https://semver.org/lang/fr/)

---

## [v1.59.0] — 2026-08-26 — Gérer le wiki depuis Matothèque (déplacer / renommer)

### Ajouté
- **Wiki → Liste des livres** devient éditable, avec répercussion **directe dans BookStack**
  (aucune étape de synchro séparée) :
  - **Glisser-déposer** un livre d'une étagère à l'autre (ou vers « Sans étagère » = détacher).
    Le déplacement ajoute d'abord à la cible puis retire de la source (jamais de livre orphelin).
  - **Renommer** un livre (✏️ au survol de la carte) ou une étagère (✏️ sur l'en-tête).
- Backend : `bookstack_service.{retirer_livre_etagere,renommer_livre,renommer_etagere}` +
  endpoints `PATCH /wiki/books/{id}`, `PATCH /wiki/shelves/{id}`, `POST /wiki/books/{id}/deplacer`.
  Renommage d'étagère : la liste de livres est réinjectée pour ne pas la vider.

## [v1.58.2] — 2026-08-26 — « Créer » : onglet « Récapitulatif » à vide (plus « Aperçu »)

### Modifié
- Dans « Créer », tant qu'aucun contenu n'est généré, l'onglet (et le titre du panneau résultat)
  s'appelle **« Récapitulatif »** au lieu de « Aperçu » — à vide c'est une check-list de préparation,
  pas un aperçu. Il redevient « Aperçu » une fois le rapport prêt. *(Les onglets Rendu/Source/Éditer
  étaient déjà masqués tant qu'il n'y a pas de contenu.)*
- Rappel : la version affichée dans l'UI vient de `/api/version` (backend) → le backend est désormais
  rebâti à chaque bump pour que l'affiché colle à la version.

## [v1.58.1] — 2026-08-26 — Passerelle : message prêt-à-coller pour le « claude projet »

### Ajouté
- À la création/rotation d'un jeton, un **chevron repliable « Voir le message à donner au claude
  projet »** ouvre une **fenêtre éditable** (textarea) pré-remplie avec le message complet : adresse
  de la passerelle (déduite de l'hôte + port 8008), jeton, livres autorisés, exemple de manifeste
  JSON et étapes de publication. Bouton **« Copier le message »**. Éditable avant copie (ajuster
  l'adresse/port si besoin).

## [v1.58.0] — 2026-08-26 — UI d'administration de la passerelle (projets & jetons)

### Ajouté
- **Paramètres → Wiki BookStack → « Passerelle de publication (projets & jetons) »** : gérer les
  projets externes autorisés à publier sur le wiki, sans passer par `curl`. Créer un projet (nom +
  liste blanche de livres) → **jeton affiché une seule fois** avec bouton « Copier » ; **régénérer**
  le jeton (rotation) ; **révoquer/réactiver** ; **modifier la liste blanche**. Message dédié si
  l'image backend déployée ne contient pas encore le routeur passerelle. `passerelleApi` +
  composant `PasserelleProjets`.

## [v1.57.7] — 2026-08-26 — Version dans l'UI + refresh du widget Tâches à l'ouverture

### Corrigé
- **Version applicative de nouveau affichée** (fini « vdev ») : les images backend étaient bâties
  sans `--build-arg APP_VERSION` → l'image figeait `APP_VERSION=dev` (le fichier `VERSION` n'est pas
  dans le contexte `./backend`). Le backend est désormais bâti en injectant la version.

### Ajouté
- **Rafraîchissement à l'ouverture du menu « Tâches »** : ouvrir le widget force un `poll()` immédiat
  (au lieu d'attendre le prochain tick de 2,5 s) → l'état affiché est toujours frais.

## [v1.57.6] — 2026-08-26 — « Annuler » effectif sur les tâches longues

### Corrigé
- **« Annuler » désormais effectif** sur les jobs longs. Le mécanisme base (drapeau
  `jobs.annulation_demandee` posé par l'API, relu par le worker à chaque tick → `ctx.cancelled`)
  était en place mais **seule l'indexation** le vérifiait. Ajout de la vérification `ctx.cancelled`
  aux autres boucles longues : **réorganisation** (appliquer/annuler), **indexation d'un connecteur
  cloud**, **indexation du wiki** — arrêt propre entre deux éléments (ce qui est fait est committé,
  le résultat porte `annule: true`). *(En prod, le worker est un conteneur séparé : l'ancien drapeau
  en mémoire du process API lui était invisible → le bouton ne faisait rien.)*

## [v1.57.5] — 2026-08-26 — Mode sombre : fin de la sur-brillance des blocs teintés

### Corrigé
- **Cadres/fonds colorés « éblouissants » en mode sombre** (ex. « 1. Choisis un dossier » dans
  Décrire les images) : les surfaces `-50` colorées (bleu/rouge/vert/violet/ambre…) et leurs
  bordures `-100/-200` n'étaient pas remappées (le remap global ne couvrait que gris/blanc) →
  elles restaient très claires. Ajout d'un remap sombre **par teinte** (couleur sémantique
  conservée, faible luminance) dans `index.css` + éclaircissement des textes d'accent `-800`
  pour la lisibilité. Corrige tous ces blocs d'un coup, pas seulement celui signalé.

## [v1.57.4] — 2026-08-26 — Fix : progression > 100 % + sur-brillance du logo (sombre)

### Corrigé
- **Progression d'indexation faussée** (« 40047 / 34290 fichiers » à 100 %) : l'endpoint
  `/sources/{id}/progression` borne désormais `fait ≤ total` et renvoie un `pct` clampé [0,100] ;
  `IndexedSourcesSummary` l'affiche sans dépassement. (Le message côté « Tâches » était déjà borné.)
  Fix de fond — progression PAR job — reste un chantier séparé.
- **Sur-brillance blanche du logo en mode sombre** : le badge (feuilles blanches pleines) sur la
  sidebar sombre était le seul élément « éblouissant » en thème sombre → atténué (`dark:brightness-75`).

## [v1.57.3] — 2026-08-26 — Paramètre : repli par défaut des étagères Wiki

### Ajouté
- **Paramètres → Wiki BookStack → Affichage du menu Wiki** : un **interrupteur** « Replier les
  étagères par défaut ». Quand il est activé, les sections d'étagères de « Wiki → Liste des livres »
  démarrent repliées (chevron ▸) ; on peut toujours en déplier une à la main. Préférence persistée
  en local (store `matotheque-wiki-prefs`, sans réseau).

## [v1.57.2] — 2026-08-26 — Étagère aussi dans « Wiki › Publier »

### Ajouté
- Le sélecteur d'**étagère (optionnel)** manquait sur la page pleine **Wiki › Publier**
  (elle a son propre formulaire, distinct de la modale « Publier sur le wiki »). Ajouté à
  l'identique : étagère existante ou **nouvelle** → le livre de la page y est rangé.

## [v1.57.1] — 2026-08-26 — Étagères : repli menu Wiki + choix à la publication

### Ajouté
- **Étagères pliables/dépliables** dans « Wiki — Liste des livres » : chaque groupe d'étagère se
  replie d'un clic (chevron), pratique quand il y a beaucoup de livres.
- **Choix d'étagère à la publication** : la modale « Publier sur le wiki » (rapports/documents)
  propose désormais un sélecteur d'étagère optionnel (existante ou **nouvelle**) ; le livre de la
  page y est rangé automatiquement. `GET /bookstack/targets` renvoie les étagères ; `POST
  /bookstack/publish` accepte `shelf_id` / `new_shelf` (rattachement résilient — n'invalide jamais
  une page déjà publiée).

## [v1.57.0] — 2026-08-26 — Passerelle wiki : étagères (Lot 1b) + bandeau auto

### Ajouté
- **Étagères BookStack (Lot 1b)** : le manifeste de publication accepte un champ `etagere` ; la
  passerelle rattache (idempotent) les livres du manifeste à cette étagère
  (`ensure_shelf` + `ensure_book_in_shelf`). Le rattachement est résilient — un souci d'étagère
  n'annule pas la publication des pages.
- **Menu Wiki regroupé par étagère** : `GET /wiki/books` renvoie désormais `shelves`
  (`[{id, name, book_ids}]`) et la page « Wiki — Liste des livres » regroupe les livres par
  étagère (section « Sans étagère » pour les livres non rattachés ; affichage à plat conservé
  s'il n'existe aucune étagère).
- **Bandeau « généré automatiquement » (§6.3)** : chaque page publiée par la passerelle est
  préfixée d'un avertissement rappelant qu'elle est gérée par le projet source et qu'une édition
  manuelle sera écrasée à la prochaine synchronisation. La déduplication reste calculée sur le
  markdown d'origine du manifeste (le bandeau ne déclenche pas de fausse mise à jour).

## [v1.47.1] — 2026-07-24 — Fix : route images-count vs {document_id}

### Corrigé
- `GET /documents/images-count` (1 segment) était **intercepté par `/documents/{document_id}`**
  → « ID de document invalide ». Renommé **`/documents/images/count`** (2 segments) → plus de collision.

## [v1.47.0] — 2026-07-24 — Décrire les images : ciblage par DOSSIER

### Ajouté
- **Cibler un dossier** pour la description IA vision des photos : au lieu de tout le NAS (48 000
  images = plusieurs jours de GPU), on sélectionne un **dossier précis** (explorateur de source) →
  seules ses images sont décrites. `analyze-batch?scope=images&prefixe=…` + `GET /documents/images-count?prefixe=`
  (nombre d'images du dossier). Bouton adaptatif « Décrire ce dossier (N) » / « Décrire tout (N) ».

## [v1.46.0] — 2026-07-24 — Badge « Tâches » : vrais chiffres (en cours / en file)

### Corrigé
- **Badge « Tâches · N » trompeur** : il comptait les tâches actives d'une **fenêtre de 20 jobs**
  récupérés → sur un gros lot il affichait « ·22 » (la fenêtre), pas la réalité. Nouveau endpoint
  `GET /jobs/stats` (COUNT en base) → le badge affiche **« N en cours · M en file »** exacts
  (ex. « 2 en cours · 4944 en file »).

## [v1.45.0] — 2026-07-24 — Maintenance : compteurs « Total · Traité · Restant »

### Ajouté / Modifié
- **Compteurs clairs** sous chaque action de maintenance : au lieu du seul « restant » (source de
  confusion), une ligne **Total N · Traité N (%) · Restant N · en file** — auto-actualisée. `maintenance/
  counts` renvoie `enrich_total` (docs enrichissables), `images_total` (toutes les images), `docs_total`.
- **Lots d'images plus gros** : « Décrire les images » enfile jusqu'à **5000** images par clic (au lieu de
  1000) — moins de clics pour un gros corpus ; message de confirmation précisant la taille du lot et le reste.

## [v1.44.0] — 2026-07-24 — Maintenance : avancement des lots en direct

### Ajouté / Modifié
- **Indicateur d'avancement vivant** sous les actions de maintenance (Paramètres) : le chiffre du
  bouton est le **nombre restant** à traiter (candidats), et une ligne sous chaque action affiche
  désormais **« N en file/en cours · M restant »**, **auto-actualisée toutes les 15 s** tant que des
  jobs tournent → le « restant » décroît en direct sans recharger la page. `maintenance/counts`
  renvoie `jobs_enrich` et `jobs_analyze` (files réelles, comptées en base).

## [v1.43.0] — 2026-07-24 — Rendre les photos cherchables (IA vision, ciblé)

### Ajouté
- **Bouton « Décrire les images (IA vision) »** (Paramètres → Maintenance) : génère une
  **description/OCR** des **photos cataloguées** via le modèle vision (qwen2.5vl) → texte +
  embeddings → **cherchables par contenu** (elles ne l'étaient pas — cataloguées nom+taille seuls).
- **Scope `images`** sur `/documents/analyze-batch` : cible **uniquement les images** OCR-ables, pour
  **ne pas rapatrier vidéos/audio** (que `media`/`all` téléchargeraient pour rien → risque disque).
  Compteur `images` ajouté à `/documents/maintenance/counts`.

> Le pipeline `analyze` (fetch → Tika → OCR/description vision → enrichissement → embeddings) existait
> déjà ; il manquait un déclencheur **sûr et ciblé** pour les photos. Traitement **long et GPU-lourd**.

## [v1.42.0] — 2026-07-24 — Recherche : regrouper par type de fichier

### Ajouté
- **Regroupement des résultats de recherche par TYPE** : sélecteur **Grouper : Aucun / Pertinence /
  Type**. « Type » range les résultats par catégorie de fichier (📕 PDF, 📄 Document, 📊 Tableur,
  📑 Présentation, 🖼️ Image, 🎵 Audio, 🎬 Vidéo, 🗜️ Archive) en sections repliables. Chaque résultat
  porte un champ `type_groupe` dérivé de l'extension (aucune réindexation).

### Note
- **Les images/photos n'apparaissent pas dans la recherche par contenu** : elles sont **cataloguées**
  (nom + taille) **sans extraction de texte ni embedding** → introuvables par mots-clés (sauf via leur
  nom de fichier) et absentes du sémantique. Les rendre cherchables nécessiterait une **description IA
  vision** à l'indexation (chantier séparé).

## [v1.41.1] — 2026-07-24 — Fix : l'endpoint /api/search utilise enfin tsv + ANN

### Corrigé
- **🔴 Les optimisations E7 (sémantique ANN) et 1.41.0 (full-text tsv) n'étaient PAS actives via
  l'API** : elles avaient été appliquées à la classe `services/search_service.py`, mais l'endpoint
  `/api/search` utilise ses **propres** fonctions dans `routers/search.py` — restées sur l'ancien
  code (recalcul `to_tsvector`, scan complet 4096). D'où les recherches toujours à ~30 s malgré les
  déploiements. Correctif porté dans `routers/search.py` : full-text via `ts_rank(d.tsv, …)`
  (**5 s → 0,1 s** mesuré API dev) et sémantique via l'**ANN 1024-d indexé HNSW** (**70 ms** hors
  embedding Ollama), avec repli sur l'ancien comportement si `tsv`/`embedding_small` absents.

## [v1.41.0] — 2026-07-24 — Full-text : colonne tsvector stockée (perf)

### Corrigé
- **Recherche texte/hybride encore lente malgré l'index (1.40.x)** : l'index GIN accélère le FILTRE
  (`@@`), mais le CLASSEMENT `ts_rank(to_tsvector(texte || nom), …)` **recalculait le tsvector sur le
  texte COMPLET de chaque document trouvé** → ~30 s sur un terme fréquent (66 k docs). Correctif :
  colonne **`tsv` tsvector STOCKÉE** (générée) + index GIN dédié → `ts_rank(d.tsv, …)` sans recalcul.
  Mesuré : **1800 ms → 4 ms** (terme « chat », dev). L'index d'expression redondant est retiré.
  La colonne est **générée** (auto-maintenue) ; 1ᵉ démarrage = réécriture unique (~70 s, non bloquante
  car le backend n'a pas de healthcheck). Requête avec **repli** sur l'expression si la colonne manque.

## [v1.40.1] — 2026-07-24 — Fix : index full-text créé de façon robuste

### Corrigé
- L'index full-text (1.40.0) était créé **dans la transaction principale d'`init_db`** : si une DDL
  précédente échouait (transaction empoisonnée), sa création était **sautée en silence** → recherche
  texte toujours lente en prod. Il est désormais créé dans **sa propre transaction** + **`ANALYZE
  documents`** (stats du planificateur). Robuste et vérifiable (log si échec).

## [v1.40.0] — 2026-07-24 — Recherche full-text indexée (perf, suite E7)

### Corrigé
- **Recherche texte/hybride ~1000× plus rapide** : la requête cherche sur `texte_extrait || ' ' || nom`,
  mais l'index GIN historique ne couvrait que `texte_extrait` → **expression différente → index jamais
  utilisé → scan séquentiel de tout le corpus** (~30 s sur 66 k docs, d'où les « timeout 30000ms » de
  l'UI). Ajout de l'index GIN sur l'**expression exacte** de la requête → **Seq Scan → Bitmap Index Scan**
  (coût 20260 → 23). Complète l'accélération sémantique (E7, v1.38.0). Index créé au démarrage (idempotent).

## [v1.39.0] — 2026-07-24 — Connecteur reMarkable (E5)

### Ajouté
- **Connecteur reMarkable Cloud** (lecture) : indexe les PDF/EPUB et notes d'un compte reMarkable.
  Appairage par **code à usage unique** (`my.remarkable.com/device/desktop`) → device token durable
  chiffré ; user token dérivé à chaque accès. `services/connectors/remarkable.py` (register/test/
  browse/walk/fetch), arbre reconstruit depuis la liste plate (`parse_docs`/`collect_documents`,
  5 tests). `POST /connectors/remarkable/pair` + UI Paramètres. Réutilise le pipeline connecteur.
  ⚠️ API cloud non officielle → à valider sur un compte réel. Doc `docs/setup-remarkable.md`.

## [v1.38.0] — 2026-07-24 — Recherche sémantique accélérée (E7)

### Ajouté / Modifié
- **Recherche sémantique ~10 000× plus rapide** (mesuré : **41 s → 4 ms** sur 78 k vecteurs, à
  chaud). Cause de la lenteur : les embeddings **4096-d** ne sont **pas indexables** par pgvector
  (plafond 2000 dims) → chaque recherche scannait tous les vecteurs. Solution **Matryoshka** :
  colonne `embedding_small` **1024-d** dérivée du 4096 (préfixe L2-normalisé — `qwen3-embedding`
  est MRL, donc **aucun ré-embed**), **indexée HNSW** ; la recherche fait un **ANN indexé** puis
  agrège par document. **Qualité conservée** (recouvrement top-10 = 9-10/10 vs scan complet).
- **Backfill + index en tâche de fond** (worker, une seule fois, protégé par verrou d'avis ;
  `CREATE INDEX CONCURRENTLY` non bloquant) → aucune interruption au déploiement. Les nouveaux
  embeddings remplissent `embedding_small` **à l'insertion**. Repli automatique sur le scan complet
  tant que le backfill n'est pas terminé.

## [v1.37.0] — 2026-07-24 — Transcription audio (E5 : openplaud)

### Ajouté
- **Transcription audio → texte** : les fichiers audio (dictaphone **Plaud/openplaud**, mémos,
  réunions…) sont **transcrits** puis indexés/enrichis/vectorisés comme un document — donc
  **recherchables** en plein texte ET en sémantique. `services/transcription_service.py` appelle un
  **serveur local compatible OpenAI** `/v1/audio/transcriptions` (faster-whisper-server, LocalAI…) ;
  aucun tiers. Config **Paramètres → Transcription audio** (URL/modèle/langue/clé, test de connexion).
- **Routage média unifié** (`folder_watcher.media_a_cataloguer`) : l'audio est envoyé à l'extraction
  (transcription) dès qu'un serveur est configuré, sinon **catalogué** sans texte comme avant — sur
  tous les points d'indexation (upload, watch local, synchro SMB, connecteurs, restauration corbeille).
- Voyant du service dans **Paramètres → Services**. Doc `docs/setup-transcription.md`. 10 tests.

## [v1.36.0] — 2026-07-24 — Documents liés sur la fiche (E3, suite)

### Ajouté
- **Section « Documents liés »** dans la fiche document (GED) : liste les documents **liés**
  (liens validés partageant une référence — BC ↔ facture…), avec la **référence** et la nature
  du lien. Un clic **ouvre la fiche** du document lié (navigation de proche en proche). Alimentée
  par `GET /links/document/{id}` (déjà livré en v1.33.0) → complète la boucle de la page « Liens ».

## [v1.35.0] — 2026-07-24 — Responsive / smartphone (Phase 2)

### Ajouté / Modifié
- **GED sur mobile** : les filtres (catégories + tags), jusqu'ici **inaccessibles** sous `md`,
  s'ouvrent désormais dans un **tiroir latéral** via un bouton **« Filtres »** (barre de recherche).
  Sélectionner une catégorie/un tag referme le tiroir. Sur bureau, l'aside reste fixe (inchangé).
- **Regroupements sur mobile** : passage au motif **maître-détail « une vue à la fois »** — la liste
  occupe tout l'écran, l'ouverture d'un regroupement affiche le détail en plein écran avec un bouton
  **« ← Retour »**. Les deux volets côte à côte reviennent dès `md` (bureau inchangé).
- **Lecteur Wiki (livres BookStack) sur mobile** : le **sommaire** (256 px fixes) devient un **tiroir**
  ouvert par une icône ☰ ; le clic sur une page le referme. Contenu en pleine largeur.
- **Finitions** : marges de page adoucies sur mobile (Réorganiser `p-3`), formulaire de prompt et
  libellés de modèles empilés sous `sm` au lieu de colonnes trop étroites.

> Suite de la Phase 1 (v1.30.0, menu burger + pages principales). Audit responsive poursuivi
> page par page ; il reste des écrans secondaires à peaufiner au fil de l'usage.

## [v1.34.0] — 2026-07-24 — Connecteur WebDAV générique (E1)

### Ajouté
- **Connecteur WebDAV** (lecture seule, HTTP Basic — **pas d'OAuth**) : indexe **Nextcloud /
  ownCloud**, **Infomaniak kDrive**, **Synology WebDAV**, serveurs `mod_dav`… `services/connectors/
  webdav.py` (test/browse/walk/fetch/stream via `PROPFIND` + `GET`, parsing `multistatus`
  namespacé, gestion des chemins encodés %XX, mot de passe chiffré Fernet). 7 tests de parsing.
- **UI Paramètres → Connecteurs cloud → WebDAV** : formulaire **URL + identifiants** →
  « Connecter et tester » (pastille verte/rouge immédiate), puis **Indexer** (tâche durable) /
  Déconnecter. Un compte = une Source (multi-comptes), documentée dans `docs/setup-webdav.md`.
- Réutilise **tout** le pipeline connecteur existant (indexation durable, synchro périodique,
  « Dossiers indexés » sous `webdav://<id>/…`) sans code spécifique — traitement générique par type.

## [v1.33.0] — 2026-07-24 — Liens documentaires : BC ↔ facture (E3)

### Ajouté
- **Nouvelle page « Liens »** : relie les documents qui **partagent une référence** (n° de bon de
  commande, de facture, de devis…) détectée dans leur texte. **Hybride** (demande utilisateur 01/07) :
  extraction de références par motifs FR + détection du **type documentaire** (BC / facture / devis /
  BL) → un lien entre types complémentaires (**BC ↔ facture**) est proposé avec une confiance plus
  forte. 100 % local, sans IA (rapide et déterministe).
- **Flux de validation** : « Analyser » propose des paires → l'utilisateur **valide**, **rejette** ou
  crée un lien **manuel**. Rien n'est lié automatiquement ; un lien **rejeté n'est jamais reproposé**.
  Périmètre d'analyse optionnel (cibler un dossier via l'explorateur de source).
- API `/api/links` : `scan`, liste par statut, `validate`/`reject`/suppression, création manuelle,
  et `GET /links/document/{id}` (liens validés d'un document, pour une future intégration à la fiche).
- Table `document_links` (paire normalisée, statut suggéré/validé/rejeté, référence, score, origine).

## [v1.32.0] — 2026-07-23 — Doublons avancés (E4)

### Ajouté / Modifié
- **Détection de scan disque en 3 passes** : `taille → hash partiel (4 Ko) → SHA256 complet`. La
  passe intermédiaire écarte les fichiers de même taille mais de début différent **sans lire leur
  contenu entier** → beaucoup moins d'I/O sur un gros volume.
- **Photos floues** (nouvel onglet Doublons) : détecte les images à **faible netteté** via la
  **variance du Laplacien** (numpy + Pillow, sans OpenCV). Seuil réglable, liste triée du plus flou
  au moins flou, mise en **quarantaine réversible** (comme les doublons). `GET /duplicates/blurry`.

## [v1.31.5] — 2026-07-23

### Corrigé
- **🔴 OAuth Google `invalid_client` — LA cause** : le connecteur envoyait à Google le
  `gdrive_client_secret` **encore chiffré** (`enc::…`, valeur Fernet) au lieu du secret en clair
  (`GOCSPX-…`). Google rejetait donc systématiquement (« The provided client secret is invalid »),
  quel que soit le secret saisi. Le connecteur **déchiffre** désormais le secret avant l'échange
  (comme BookStack). Diagnostic de forme du secret ajouté (préfixe + longueur, sans le révéler) et
  `strip()` des identifiants (garde-fou copier-coller).

## [v1.31.3] — 2026-07-23

### Corrigé
- **OAuth Google : `invalid_client` malgré un secret correct** — le flux OAuth lisait le
  `gdrive_client_secret` du cache du process (multi-uvicorn), qui pouvait être périmé après une
  mise à jour de config → échange du code refusé (« The provided client secret is invalid »).
  `oauth/start` et `oauth/callback` **rechargent désormais la config depuis la base** avant usage
  → plus besoin de redémarrer le backend après avoir changé le secret.

---

## [v1.31.2] — 2026-07-23

### Ajouté / Modifié
- **Pastille de connexion** sur les comptes Google Drive (Paramètres → Connecteurs cloud) :
  **verte** = connexion établie, **rouge** = à reconnecter, grise = vérification. Testée à
  l'affichage via `/connectors/{id}/test`.
- **Sources cloud dans « Dossiers indexés »** : un compte Drive indexé apparaît dans le récap
  (icône ☁, libellé « Google Drive ») au même titre que le NAS.
- Les comptes cloud ne s'affichent plus dans « Sources de fichiers » (local/smb) — ils se gèrent
  dans « Connecteurs cloud » (leurs boutons Explorer/Synchroniser ne s'y appliquaient pas).

---

## [v1.31.1] — 2026-07-23

### Corrigé
- **Sources cloud (Google Drive…) invisibles dans « Dossiers indexés »** : l'arbre par source
  cherchait au préfixe `root/` alors que les documents connecteur sont rangés sous
  `{type}://{source_id}/…`. `_prefixe_source` reconnaît désormais les types connecteur → l'arbre
  « Dossiers indexés » affiche bien le contenu d'un Drive (les docs étaient déjà cherchables en GED).

---

## [v1.31.0] — 2026-07-23 — Connecteur Google Drive (OAuth, lecture)

### Ajouté
- **Connecteur Google Drive** (lecture seule, `drive.readonly`) : un **compte Google = une Source**
  (multi-comptes). `services/connectors/gdrive.py` (test/browse/walk/fetch/stream, refresh_token
  chiffré, pagination Drive API v3, **export** des documents Google natifs Docs→PDF / Sheets→xlsx /
  Slides→pptx). Réutilise le pipeline d'indexation durable existant.
- **Flux OAuth** : `GET /connectors/oauth/start` (URL de consentement) + `GET /connectors/oauth/callback`
  (échange du code → refresh_token → création de la Source → retour Paramètres). Config
  `oauth_redirect_uri` (à fixer en prod derrière proxy).
- **UI Paramètres → Connecteurs cloud** : bouton **« Connecter un compte Google »** + liste des
  comptes (Indexer / Déconnecter). Retour OAuth signalé par un toast.

> ⚠️ **Prérequis utilisateur** : créer l'app OAuth Google Cloud (cf. `docs/setup-google-drive-oauth.md`)
> et saisir Client ID/Secret. Connecteur **cloud** (accès réseau sortant vers Google).

---

## [v1.30.0] — 2026-07-23 — Responsive / smartphone (Phase 1)

### Ajouté / Modifié
- **Menu burger** : sous `md` (tablette/smartphone), la barre de navigation latérale devient un
  **tiroir off-canvas** ouvert par un bouton ☰ dans l'en-tête (fond assombri, fermeture au clic
  hors zone ou à la navigation). Au-delà, la sidebar reste fixe (bureau inchangé).
- **Page « Créer » empilée** sous `lg` : les colonnes configuration / résultat se placent l'une
  **sous l'autre** (au lieu de côte à côte illisible sur écran étroit) ; le panneau résultat garde
  une hauteur minimale utilisable.
- **En-tête compact** : les libellés des voyants de services (Tika/Ollama/n8n/Antivirus) se
  réduisent aux pastilles sous `sm`.
- **GED** : les filtres latéraux se masquent sous `md` (recherche + grille de cartes conservées,
  déjà responsive) ; **marges de page** adoucies sur mobile (`p-3` au lieu de `p-6`).

> Premier passage responsive (menu + pages principales). Audit page-par-page complet à poursuivre.

---

## [v1.29.0] — 2026-07-23 — Préparation du modèle (cold-load)

### Ajouté
- **Indicateur « modèle prêt / à préparer »** à côté du sélecteur de modèle (page Créer) : dit si
  le modèle des rapports est **chargé en mémoire** (⚡ prêt — génération instantanée) ou à froid.
- **Bouton « préparer »** : charge le modèle à l'avance, pour éviter l'attente de chargement au clic
  « Générer » (utile pour un gros modèle lent à charger). API `GET /system/model-status` +
  `POST /system/warm-model`. Complète le pré-chargement automatique du worker.

---

## [v1.28.0] — 2026-07-23 — Indexation continue Phase 4

### Ajouté
- **Purge assistée des documents « disparus »** : les fichiers supprimés du NAS sont marqués
  `absent` par la synchro (jamais supprimés d'office). Un **badge « N disparu(s) »** apparaît sur
  la source (Paramètres → Sources) → **modale de revue** listant les documents disparus, avec
  suppression **par sélection** ou **tout**, après confirmation. Ne touche à aucun fichier ;
  l'index se reconstruit si les fichiers reviennent. API `GET /sources/{id}/absents`,
  `POST /sources/{id}/purge-absents`.

### Corrigé
- **Énumération SMB (walk) annulable** : le parcours récursif d'un partage tournait dans un thread
  **non interruptible** → « Annuler » ne prenait effet qu'**après** l'énumération (parfois plusieurs
  minutes sur 65k fichiers). Un `cancel_event` (positionné à l'annulation) l'arrête désormais
  proprement, avant la connexion et à chaque dossier.

---

## [v1.27.0] — 2026-07-23 — Observabilité Phase 2 (traçabilité)

### Ajouté
- **Journal d'activité métier de bout en bout** (`audit_events`) : chaque opération (indexation,
  synchro, génération, analyse, enrich…) est tracée par un **`correlation_id`** commun qui relie
  les couches **API → worker** (`queued` → `start` → `success`/`error`/`cancelled`), avec **acteur**,
  **statut** et **durée** mesurée.
- **Instrumentation automatique** de tous les jobs durables (au cœur du worker) + de la génération
  de rapport — aucun handler à modifier ; le `correlation_id` est injecté à l'enfilement.
- **Page Logs → « Traçabilité »** : liste filtrable par action ; clic sur une ligne → **chaîne
  complète** de la corrélation (tout l'enchaînement d'une même opération, dans l'ordre).
- API `GET /api/audit` (filtres action/statut/acteur/correlation_id) + `GET /api/audit/actions`.

---

## [v1.26.0] — 2026-07-23 — Sprint N+1 (finitions + irritants)

### Corrigé
- **🔴 « Annuler » sans effet sur un job en cours** : le drapeau d'annulation était un `set` en
  mémoire de l'API, alors que le job tourne dans le **worker** (process séparé) → jamais vu.
  Désormais **en base** (`jobs.annulation_demandee`), relu par le worker à chaque tick. Vérifié :
  un job `running` passe bien `cancelled`.
- **Jobs fantômes** : compteur de **reprises** (running→pending après crash) — au-delà de 3, le job
  est déclaré `failed` au lieu de boucler ; et **purge auto des `pending` d'un type sans handler**
  (ex. `rapport`) restés trop longtemps (ce qu'on nettoyait à la main).
- **🐞 % de progression > 100 %** dans le widget Tâches (`40047/34290`) : affichage borné à
  `min(fait, total)` (garde-fou ; le fond — progression par job — reste un chantier séparé).
- **Fiabilité enrichissement** : les sous-documents de ZIP étaient marqués `enriched`
  inconditionnellement (même sans métadonnées IA) → alignés sur le pipeline (`enriched` seulement
  si l'IA a produit des métadonnées, sinon `extracted`).
- **« Ré-analyser » (analyze-batch)** : l'erreur est désormais **journalisée** (type + message +
  scope) et renvoyée clairement, au lieu de « erreur affichée mais rien dans les logs ».

### Modifié
- **Paramètres — navigation persistante** : le fil d'ariane (« Tous les paramètres / … ») **et la
  barre de recherche** restent visibles **en vue détail** d'une section ; chercher en vue détail
  ramène au tableau de bord filtré (plus besoin de ressortir).

---

## [v1.25.1] — 2026-07-23

### Modifié
- **Export PDF nettement plus soigné** : nouveau rendu « document » du Markdown — bandeau de
  titre à accent indigo + sous-titre daté (« Matothèque · Rapport généré le … »), titres de
  section colorés à bordure d'accent, **tableaux à en-tête indigo et lignes zébrées**, listes à
  puces colorées, citations en encart arrondi, bloc **Sources** détaché, **pied de page paginé**
  (« Page N / M »). Rendu vérifié visuellement. Auto-suffisant (aucune ressource externe).

---

## [v1.25.0] — 2026-07-23

### Ajouté — Historique des rapports (persistant)
- **Onglet « Historique »** dans le panneau de la page Créer : liste des rapports générés,
  **archivés en base** (table `rapports`) — survivent au rechargement, à la fermeture du navigateur
  et au redémarrage (l'ancien historique était un tampon de session perdu au F5). Chaque rapport
  garde titre, date, modèle, documents sources et contenu.
- **Rouvrir** un rapport d'un clic (chargé dans l'onglet Rendu).
- **Suppression par cases** : sélection individuelle + « tout sélectionner » + « tout vider »
  (avec confirmation).
- **Purge automatique** réglable (Jamais / 7 / 30 / 90 j / 1 an) — appliquée par le worker
  (`rapports_purge_jours`). Réglage exposé dans l'onglet Historique.
- Endpoints `/api/rapports` (liste, détail, suppression individuelle/lot, purge).

---

## [v1.24.10] — 2026-07-23

### Corrigé
- **🔴 Export PDF cassé** (`'super' object has no attribute 'transform'`) : `pydyf` 0.12 (installé
  faute d'épingle) casse WeasyPrint 62.3. **`pydyf==0.10.0`** épinglé.
- **🔴 Export DOCX cassé** (`Permission denied: /app/storage/exports/…`) : le conteneur (uid 10001)
  ne pouvait pas écrire dans le montage `exports`. **Les deux exports génèrent désormais le fichier
  EN MÉMOIRE** (BytesIO / `write_pdf()` sans cible) et le renvoient directement — **aucune écriture
  disque**, donc plus aucune dépendance aux droits du montage. Nom de fichier encodé UTF-8.

---

## [v1.24.9] — 2026-07-23

### Ajouté
- **Liste des documents sources à la fin du rapport** : un bloc « **Sources** *(N documents)* »
  est ajouté en fin de rapport généré (traçabilité — visible dans tous les exports PDF/DOCX/MD/Wiki).
  Répond au doute « combien de documents ont été traités ? ».
- **Pré-chargement du modèle de rapport** (`ollama_prewarm_enabled`, défaut activé) : le worker
  maintient le gros modèle (Qwen3.6-35B, ~44 Go) **résident** — au démarrage puis périodiquement
  (`ollama_prewarm_minutes`, 20 min < keep_alive). Évite qu'un premier rapport après inactivité
  doive recharger 44 Go **à froid** (lent, risque de 502 via le proxy). Modèle lu dans les
  Paramètres (`model_for("rapport")`), jamais en dur. *Approche à améliorer (cf. suivi).*

---

## [v1.24.8] — 2026-07-23

### Corrigé
- **🔴 « Aucun handler pour le type 'rapport' » — génération de rapport tuée par une course** : le
  rapport crée une ligne `jobs` (type `rapport`) pour le suivi, mais il est traité par une *background
  task* FastAPI, **pas** par le worker durable. Or `_claim` réclamait **tout** job `pending` sans
  filtrer le type → le worker raflait le job `rapport`, ne trouvait pas de handler et le marquait
  `failed`. Masqué tant que la file débordait de synchros (la background task gagnait toujours la
  course) ; dès la file vidée, le worker gagnait et **tuait chaque rapport**. Le worker ne réclame
  désormais **que les types possédant un handler enregistré**.

---

## [v1.24.7] — 2026-07-23

### Ajouté / Modifié — page « Créer », panneau de résultat
- **Nouvel onglet « Rendu »** — les onglets deviennent **Aperçu | Rendu | Source | Éditer**. Le
  document rendu (Markdown → HTML) et les boutons de téléchargement vivent désormais dans « Rendu »,
  séparés de la préparation. **Bascule automatique** sur « Rendu » au clic « Générer ».
- **Export Markdown `.md`** ajouté à côté de PDF / DOCX / Wiki (téléchargement direct, aucun backend).
- **Onglet Aperçu = préparation + avancement** : la check-list « Votre rapport » (Documents / Mode /
  Instruction) est **figée** au lancement, et un bloc **réflexion/avancement** vivant apparaît en
  dessous — « ⏳ le modèle réfléchit… » pendant le silence (`think:false`), puis « ✍️ rédaction —
  N caractères » avec chrono, enfin « ✅ rapport prêt ». Répond à « je le vois où ? à quoi sert
  *Votre rapport* ? ».
- **Onglets conditionnels** : Rendu / Source / Éditer n'apparaissent qu'une fois une génération
  démarrée (avant : seul Aperçu) — corrige l'affichage prématuré des onglets (ROADMAP ④).

---

## [v1.24.6] — 2026-07-21

### Corrigé
- **Le rapport contenait le raisonnement du modèle en anglais** (« Here's a thinking process:
  1. Analyze User Input… ») au lieu d'un résumé propre : les modèles de raisonnement
  (Qwen3.6-35B) déversent leur *chain-of-thought* dans la sortie. Une consigne système seule
  s'est révélée **insuffisante** (testé : le modèle l'ignore). Corrigé via le paramètre Ollama
  **`think: false`**, qui supprime le raisonnement visible. **Agnostique du modèle** : Ollama
  l'ignore pour ceux qui n'en ont pas (vérifié sur llama3.1 et ministral-3, sans erreur) — donc
  valable quel que soit le modèle choisi dans les Paramètres, sans rien coder en dur.

---

## [v1.24.5] — 2026-07-21

### Corrigé
- **`ReadTimeout` sur la génération de rapport** — diagnostiqué grâce au message d'erreur enfin
  nommé (v1.24.4) : le délai client était de **5 min**, insuffisant pour le chargement **à froid**
  d'un modèle de 43 Go, qui reste muet plusieurs minutes avant le premier octet. Porté à **30 min**
  (`config.py`, `docker-compose.yml`, `.env.example`) et délais **dissociés** : `connect` court
  (10 s) pour qu'un hôte injoignable échoue vite, `read` long pour couvrir le chargement.
  ⚠️ Ce délai borne le **silence avant le premier octet**, pas la durée de génération : dès que
  le flux commence, chaque morceau réarme le compteur.

---

## [v1.24.4] — 2026-07-21

### Corrigé
- **« Erreur de génération : » sans aucune cause** : le code journalisait `str(e)`, or plusieurs
  exceptions httpx (timeout, coupure de connexion) ont un message **vide** — impossible de
  distinguer un délai dépassé d'un modèle absent. On journalise désormais le **type**
  d'exception (toujours présent) et la trace complète, et le job stocke `Type: message`.
- **L'interface annonçait le mauvais modèle** : elle affichait `default_model` (« Auto :
  llama3.1 », 4,9 Go) alors que la génération route **par usage** (`usage_models.rapport` =
  Qwen3.6-35B, **43 Go**). L'utilisateur croyait lancer un modèle rapide et se heurtait à des
  attentes interminables. `/system/models` renvoie maintenant `par_usage`, et l'écran affiche
  le modèle **réellement** appliqué.
- **`keep_alive` oublié sur le chemin des rapports** : `generate()` et les embeddings le
  transmettaient, mais **pas** `generate_stream()`. Le modèle des rapports retombait donc sur le
  défaut d'Ollama (5 min) et se faisait décharger entre deux usages — la requête suivante devait
  recharger 43 Go à froid. C'est la cause directe de l'échec constaté (deux rapports réussis,
  puis échec 1 h 45 plus tard, mêmes documents et même modèle).

---

## [v1.24.3] — 2026-07-21

### Corrigé
- **L'estimation avant génération annonçait « 0 doc · 0 Ko »** alors que des documents étaient
  cochés : elle ne regardait que la liste des documents *chargés en mémoire*, or le picker en
  arbre coche des identifiants sans jamais les charger. Les métadonnées des fichiers cochés
  depuis l'arbre sont désormais mémorisées dans le store.
- **L'estimation de tokens se basait sur la TAILLE DU FICHIER**, pas sur le texte réellement
  envoyé au modèle. Deux PDF de 4,9 Mo (36 000 caractères de texte) étaient annoncés à
  **≈ 1 285 k tokens** avec une alerte « le contenu sera tronqué » — au lieu de **≈ 9 k**, soit
  10× *sous* la fenêtre du modèle. `/documents/tree` renvoie maintenant `texte_longueur`
  (calculé en SQL), et l'estimation s'appuie dessus ; la mention « (approx.) » signale les cas
  où la longueur est inconnue.

---

## [v1.24.2] — 2026-07-21

### Corrigé
- **🔴 Les jobs de synchro finissaient en « échec » alors que le travail était fait** :
  `jsonb_build_object($1, …)` sans cast explicite → asyncpg ne peut pas inférer le type du
  paramètre (`IndeterminateDatatypeError`). Seul l'enregistrement du récapitulatif échouait,
  après une synchro pourtant menée à bien (3 912 nouveaux fichiers indexés sur un périmètre).
  Casts `cast(… AS text)` / `cast(… AS jsonb)` ajoutés. Ce chemin n'avait jamais été exécuté
  avant la mise en production — il l'est désormais par un test de bout en bout.
- **Cocher un dossier sans document exploitable** affichait une erreur rouge trompeuse. Message
  passé en information et reformulé ; la case du dossier se **désactive** dès qu'on sait qu'il
  n'y a rien à cocher (après une tentative, ou dès le dépliage si tous ses fichiers sont
  sans texte).

---

## [v1.24.1] — 2026-07-21

### Corrigé
- **L'explorateur de « Créer » ne montrait pas la même chose que « Paramètres → Dossiers
  indexés »** : un filtre `texte=true` était appliqué **en silence**, masquant les médias
  catalogués et les documents sans texte extrait. Conséquence mesurée : `[MaTo]` affichait
  **92** documents au lieu de **1 043**, et deux dossiers entiers (`[Mode-…]`, `[Sophie]`)
  étaient **totalement invisibles**. L'arbre affiche désormais le **même périmètre**, les
  documents sans texte restant visibles mais **grisés et non cochables** (mention « sans texte »
  + explication au survol), avec une case **« Masquer les documents sans texte »** pour
  retrouver l'ancienne vue à la demande.

---

## [v1.24.0] — 2026-07-21

### Ajouté
- **Synchronisation automatique des sources** — l'indexation devient réellement *continue* :
  sélecteur **« Synchro auto »** par source (désactivée / 1 h / 6 h / 24 h), « dernière : il y a … »
  et récapitulatif du dernier écart affiché sous la source. Un tick worker (5 min) déclenche les
  sources dues ; une source déjà occupée par une synchro **ou** une indexation passe son tour.

### Corrigé
- **🔴 `statut='absent'` violait la contrainte `CHECK` de `documents`** : la synchro aurait échoué
  **en production à la première suppression d'un fichier sur le NAS**. Invisible en développement
  (aucun fichier disparu au premier passage). Contrainte élargie, avec garde-fou idempotent au
  démarrage pour les bases existantes.
- **🔴 Fuite de verrou d'avis Postgres** : `pg_try_advisory_lock` suivi d'un `commit()` rendait la
  connexion au pool, si bien que le `pg_advisory_unlock` s'exécutait sur une **autre** connexion et
  ne libérait rien — verrou pris à vie. Conséquences : la planification des synchros renonçait
  **en silence** à chaque tick, et la **reprise des jobs orphelins au démarrage était sautée depuis
  toujours** (d'où des jobs fantômes bloquant la file). Remplacé par un verrou **transactionnel**
  (`pg_try_advisory_xact_lock`), libéré par le commit.

---

## [v1.23.0] — 2026-07-21

### Ajouté
- **Synchronisation incrémentale des sources** (`POST /api/sources/{id}/sync`, bouton
  **« Synchroniser »**) : compare la source à l'index et ne traite que les **écarts** —
  nouveaux, modifiés, **déplacés**, disparus, revenus. Mesuré sur le NAS : **50 910 fichiers
  reconnus inchangés sans transférer un octet** (ni Tika ni Ollama sollicités) et
  **10 459 nouveaux** détectés, ceux qui n'apparaissaient jamais.
  - un **déplacement** = simple mise à jour du chemin (aucun transfert, aucun doublon, historique conservé) ;
  - un fichier disparu passe en `statut='absent'` — **jamais supprimé** ;
  - **garde-fou** : un scan qui ne renvoie rien alors que l'index est peuplé (partage démonté,
    droits perdus) **abandonne** la synchro au lieu de marquer tout le corpus absent ;
  - récapitulatif du diff affiché sous la source ; 13 tests sur la logique de comparaison.

### Corrigé
- **Un fichier NAS modifié créait une 2ᵉ ligne au même chemin** au lieu d'une nouvelle version :
  `process_file` recevait le chemin du *fichier temporaire* de rapatriement, donc la détection de
  version (« même chemin, contenu différent ») ne pouvait jamais correspondre. Nouveau paramètre
  `chemin_logique` (+ `mtime_fichier`), utilisé par l'indexation **et** la synchro.
- Le `walk` SMB remonte désormais la **date de modification** réelle des fichiers.

---

## [Unreleased]

### Ajouté
- **Rebrand Matothèque** (UI + backend) ; alignement sur le modèle docker AgestiTC
  (VERSION racine, `/api/version` `/healthz` `/api/logs/tail`, Dockerfile non-root,
  CI build+verify tag-driven, Dependabot, audit hebdo, hooks `.claude`).
- **Page Doublons** : détection des fichiers en double sur le volume (scan disque
  taille→SHA256), case à cocher par fichier, **déplacement** vers `DOUBLON-MATOTEQUE/`
  avec confirmation (`GET /api/duplicates`, `POST /api/duplicates/quarantine`).
- `ROADMAP.md` (plan projet) + `DEVELOPMENT.md` + `README-UTILISATEUR.md`.

### Modifié
- Volume documents monté en **lecture-écriture** (requis pour déplacer les doublons ;
  aucun contenu de fichier n'est modifié, déplacement uniquement).

### En cours
- Optimisations performances (index pgvector ivfflat tuning)
- Quasi-doublons (similarité sémantique) — Phase 2 ROADMAP

---

## [v1.3.0] — 2026-04-13

### Couverture de tests complète — tous les routers backend + hooks frontend

**Tests backend — nouveaux fichiers :**
- `test_folders_router.py` : 20 tests
  - `TestListFolders` : liste vide, liste peuplée, structure réponse
  - `TestAddFolder` : ajout dossier existant (mock Path), chemin inexistant (422), doublon (409), nom_affichage personnalisé
  - `TestUpdateFolder` : actif, nom, partiel (autres champs conservés), intervalle min 30s (422), inexistant (404), ID invalide
  - `TestRemoveFolder` : suppression OK, absent après, avec documents associés (`supprimer_documents=true`), inexistant, ID invalide
  - `TestForceScan` : dossier actif (200), dossier inactif (422), inexistant (404), ID invalide
  - `TestBrowseFilesystem` : chemin valide (dossiers + fichiers), inexistant (404), chemin_parent, filtre extensions, taille fichier
- `test_upload_router.py` : 12 tests
  - Acceptés : PDF, DOCX, XLSX — rejetés : TXT, JPG (statut="rejeté" + raison)
  - Multi-fichiers en une requête ; mélange acceptés/rejetés dans une même réponse
  - Job créé en DB après upload (statut="pending", type="extraction")
  - ZIP : accepté via `/upload/zip`, rejeté si non-ZIP (400), paramètre type="zip" dans le job
- `test_extract_router.py` : 18 tests
  - `TestGetJobStatus` : pending/completed/failed, structure réponse, inexistant (404), ID invalide
  - `TestRelancerExtraction` : doc existant → job créé, doc repasse en "pending", fichier source manquant (422), inexistant (404), ID invalide
  - `TestListJobs` : liste vide, filtre statut, filtre type, limite, structure, ordre décroissant (plus récent en premier)

- `test_templates_router.py` : 20 tests
  - `TestListTemplates` : liste vide, templates peuplés, structure réponse (sans champs), ordre alphabétique
  - `TestUploadTemplate` : DOCX accepté (201), PDF accepté (nb_champs=0), extension TXT rejetée (400), champs `{{ }}` détectés, nom_affichage généré (title case), template créé en DB
  - `TestGetTemplate` : template existant avec champs, structure champs (nom/type/description), inexistant (404), ID invalide (400)
  - `TestDeleteTemplate` : suppression OK avec message, absent après, fichier physique supprimé, fichier manquant OK, inexistant (404), ID invalide, double suppression (404)

**Tests frontend — nouveau fichier :**
- `useDropZone.test.ts` : 16 tests
  - Types MIME acceptés : PDF, DOCX, XLSX, PPTX+PPSX, ZIP, ODT/ODS/ODP
  - `multiple: true` transmis à react-dropzone
  - `onDrop` délègue à `uploadFiles` du store ; ne l'appelle pas si liste vide
  - Transmet tous les fichiers d'un dépôt multi-fichiers
  - `noClick` : false par défaut, true/false transmis correctement
  - Valeur retournée : `getRootProps`, `getInputProps`, `isDragActive`, `open`

---

## [v1.2.0] — 2026-04-13

### Couverture de tests étendue + hook useSearch mis à jour

**`useSearch.ts` :**
- Expose désormais `hasMore`, `currentOffset`, `loadingMore`, `loadMore` (pagination GED)

**Tests backend nouveaux :**
- `test_documents_router.py` : 22 tests
  - `TestListDocuments` : liste vide, filtres statut/extension/nom, pagination, structure réponse
  - `TestDocumentStats` : base vide, agrégation taille + total, endpoint avant `/{id}` (régression)
  - `TestGetDocument` : doc existant, avec/sans métadonnées, inexistant, ID invalide
  - `TestGetDocumentText` : texte extrait, texte vide (null → ""), doc inexistant
  - `TestPatchMetadata` : tags, catégorie, résumé, sans meta (404), champs non fournis conservés
  - `TestGetVersions` : sans versions, avec versions (ordre décroissant), doc inexistant
  - `TestDeleteDocument` : suppression OK, absent après suppression, inexistant (404), ID invalide
- `test_prompts_router.py` : 17 tests
  - `TestListPrompts` : liste + structure réponse
  - `TestCreatePrompt` : création 201, nom vide (422), prompt_text vide (422), champs optionnels, ID UUID
  - `TestUpdatePrompt` : modification nom, modification partielle (autres champs conservés), inexistant (404), ID invalide
  - `TestDeletePrompt` : suppression OK, absent après suppression, inexistant (404), ID invalide, double suppression (404)

**Tests frontend hooks :**
- `useDocuments.test.ts` : 18 tests — expose documents/total/page/loading/error, selectedCount dérivé, toutes les actions (toggleSelect/selectAll/deselectAll/isSelected/selectDocument/deselectDocument)
- `useSearch.test.ts` : 18 tests — expose query/results/total/loading/error + `hasMore/currentOffset/loadingMore`, toutes les actions + search/loadMore guards

---

## [v1.1.0] — 2026-04-13

### Tests + Onglet texte extrait + Pagination affinée

**gedStore — tests de pagination :**
- `gedStore.test.ts` entièrement reécrit : 20 tests couvrant setters, search(), loadMore(), loadTags/loadCategories
- Mock de base `BASE_SEARCH_RESPONSE` avec `has_more/offset/limit` requis par le nouveau type
- `RESET_STATE` commun (inclut `hasMore/currentOffset/loadingMore`) pour isolation des tests
- `loadMore()` : 6 nouveaux tests (accumulation, offset passé à l'API, guards hasMore/query/loadingMore, reset en erreur)

**DocumentCard — onglet "Texte extrait" :**
- Ajout système d'onglets "Métadonnées" | "Texte extrait" avec indicateur actif (bordure bleue)
- Chargement paresseux du texte : `GET /documents/{id}/text` appelé uniquement à l'activation de l'onglet
- Bouton "Copier" avec feedback "Copié !" (2 secondes) via `navigator.clipboard`
- Compteur de caractères affiché dans la toolbar de l'onglet texte
- Reset de l'état texte quand `documentId` change

**Tests backend — search pagination :**
- `test_search_pagination.py` : 9 tests
  - Champs `has_more/offset/limit` présents dans toute réponse
  - `has_more=false` si résultats < limit
  - `has_more=true` si résultats > limit
  - Décalage correct entre page 1 (offset=0) et page 2 (offset=20) — IDs non-chevauchants
  - Offset négatif rejeté (422)
  - Offset par défaut = 0
  - Total stable entre pages
  - Filtre catégorie appliqué avant pagination (15 rapports sur 25 docs = total=15)

---

## [v1.0.0] — 2026-04-13

### Production-ready : Outillage + Pagination GED + Tests generate

**Makefile :**
- `make help` : liste toutes les cibles avec documentation inline
- `make up / down / logs / build / restart` : cycle de vie Docker
- `make test / test-backend / test-frontend / test-e2e / test-e2e-mocked` : tous les tests
- `make migrate / migrate-create / migrate-history / migrate-downgrade` : gestion Alembic
- `make dev-backend / dev-frontend / install / install-playwright` : développement local
- `make lint / lint-backend / lint-frontend / format / typecheck` : qualité de code
- `make health` : vérification état Tika + Ollama + backend en une commande
- `make clean / clean-docker / reset` : nettoyage environnement

**Pagination GED (backend + frontend) :**
- `GET /search` : ajout paramètre `offset` (ge=0), retourne `has_more`, `offset`, `limit` dans la réponse
- `searchApi.search()` : paramètre `offset` ajouté dans le type TypeScript
- `gedStore` : ajout `hasMore`, `currentOffset`, `loadingMore`, action `loadMore()` (accumulation des résultats)
- `GEDPage` : bouton "Charger plus de résultats" (visible si `hasMore`), spinner pendant `loadingMore`, message "Tous les N résultats" quand complet

**Tests backend — generate router :**
- `test_generate_router.py` : 14 tests
  - `TestListModels` : retour modèles Ollama, fallback si indisponible, format `{name}`
  - `TestGenerateReport` : document_ids vide (400), UUID invalide (400), document inexistant (404), prompt vide (422), rapport avec doc existant (200 + job_id + stream_url), modèle par défaut
  - `TestGenerationStatus` : job inexistant (404), ID invalide (400), statut après création
  - `TestConstruireContexte` : contexte simple, doc sans texte ignoré, troncature marquée, plusieurs documents

**Corrections E2E :**
- `mockModelsAPI` : route corrigée de `**/api/tags` → `**/api/generate/models` (proxy backend, pas Ollama direct)

---

## [v0.5.0] — 2026-04-13

### Migrations Alembic + Tests E2E Playwright

**Migrations Alembic (production-ready) :**
- `alembic.ini` : configuration Alembic avec async, template de nommage daté
- `alembic/env.py` : env async compatible asyncpg, lit `DATABASE_URL` depuis l'environnement
- `alembic/script.py.mako` : template de migration avec type hints
- `alembic/versions/20260413_0001_initial_schema.py` : migration initiale complète
  - Extensions : `vector`, `pg_trgm`
  - Tables : `documents`, `metadonnees_ia`, `embeddings` (colonne `vector(4096)`), `versions`, `templates`, `prompts_presets`, `jobs`, `dossiers_surveilles`
  - Index : trgm pour nom, GIN pour full-text, IVFFlat pour embeddings, GIN pour tags

**Tests E2E Playwright :**
- `playwright.config.ts` : config Chromium, retries CI, webServer Vite auto, reporters HTML
- `package.json` : scripts `test:e2e` et `test:e2e:ui`, dépendance `@playwright/test`

**Tests E2E sans backend (mocked) :**
- `e2e/fixtures.ts` : données mock, helpers `mockDocumentsAPI`, `mockSearchAPI`, `mockFoldersAPI`, `mockTagsAndCategoriesAPI`, `mockModelsAPI`, `mockHealthAPI` + fixture `mockedPage`
- `e2e/mocked/reports-mocked.spec.ts` : documents dans la liste, sélection + compteur, activation bouton générer, tout sélectionner/désélectionner
- `e2e/mocked/ged-mocked.spec.ts` : catégories/tags sidebar, résultats de recherche, score, panneau latéral, effacer, filtre par tag

**Tests E2E avec backend réel :**
- `e2e/navigation.spec.ts` : page par défaut, sidebar, navigation entre pages, layout de base
- `e2e/reports.spec.ts` : prompt editor, modes de sortie (rapport/template/classement), validation formulaire
- `e2e/ged.spec.ts` : barre de recherche, modes, état vide, drag & drop
- `e2e/upload.spec.ts` : zone dropzone, types de fichiers, retour API upload

**Autres :**
- `requirements.txt` : ajout `aiosqlite==0.20.0` pour les tests SQLite async

---

## [v0.4.0] — 2026-04-13

### Phase 4 — Polish : Tests + Templates + n8n

**Tests backend (pytest) :**
- `conftest.py` : fixtures SQLite en mémoire, mocks Tika/Ollama/EmbeddingService, client HTTP de test
- `test_chunker.py` : 9 tests unitaires pour `chunk_text()` (vide, taille, overlap, couverture)
- `test_hash_utils.py` : 6 tests pour `compute_sha256()` (cohérence, format, hash connu, 5 MB)
- `test_extraction.py` : tests `_extraire_json` + 7 tests intégration `ExtractionService` (déduplication, erreurs Tika/Ollama, création MetadonneeIA)
- `test_export_router.py` : endpoints DOCX/PDF + `_nom_export` (sanitisation, troncature, horodatage)
- `test_search_service.py` : pondération fusion 40/60, union IDs, fallback embedding
- `pytest.ini` : `asyncio_mode = auto`, `testpaths = tests`

**Tests frontend (vitest) :**
- `__tests__/setup.ts` : stub `EventSource`, `crypto.randomUUID`, `import.meta.env`
- `stores/documentStore.test.ts` : 13 tests (sélection, fetch, delete, upload jobs)
- `stores/reportStore.test.ts` : 12 tests (setters, streaming, historique, erreurs)
- `stores/gedStore.test.ts` : 13 tests (recherche, filtres, tags, catégories)
- `hooks/useReport.test.ts` : logique `canGenerate` + `generate()` avec selectedIds
- `utils/typeUtils.test.ts` : 16 tests (statuts, poids fusion, pagination, sanitisation, formatTaille)
- `vite.config.ts` : configuration vitest (globals, jsdom, setupFiles, coverage)

**Services backend complétés :**
- `TemplateFiller` : detect_fields → prompt LLM → parse JSON → docxtpl.render → export DOCX
- `FolderWatcher` : polling async, mtime comparison, fichiers cachés filtrés
- `SearchService` : `_fusionner()` 40/60, recherche sémantique avec fallback, `_charger_resultats()`
- `GEDService` : `get_documents()`, `detect_duplicate()`, `get_stats()`
- `ExportService` : CSS complet weasyprint PDF, parser ligne par ligne python-docx DOCX
- `ReportGenerator` : `generate_stream()`, `build_context()`, `_charger_textes()`
- `main.py` : seed prompts idempotent depuis `scripts/seed-prompts.json` au startup

**Workflows n8n :**
- `folder-watcher.json` : ScheduleTrigger (5 min) → GET /api/folders → POST /api/folders/{id}/scan
- `indexer.json` : Cron (2h) → GET documents extracted/error → POST /api/extract/{id} → log
- `report-pipeline.json` : Webhook POST → validate → POST /api/generate/report → respondToWebhook

---

## [v0.3.0] — 2026-04-13

### Phase 3 — GED avancée

**Composants GED :**
- `DocumentCard` : fiche complète (métadonnées, résumé éditable, entités, tags, versions, actions)
- `TagManager` : tags éditables inline (ajout/suppression, `PATCH /api/documents/{id}/metadata`)
- `VersionHistory` : historique des versions avec diff résumé par IA
- `SearchBar` : toggle type (Hybride/Texte/Sémantique), loading state, submit/clear
- `CategoryBrowser` : filtre actif avec ✕, click → setFilters + search()

**Composants reports complétés :**
- `PromptPresets` : dropdown groupé par catégorie, overlay + outside click
- `GenerateButton` : lecture selectedIds + prompt + isGenerating, Loader2 animate-spin
- `OutputMode` : sélecteur 3 modes (rapport libre, remplir template, classement)
- `TemplateUpload` : upload template DOCX + détection champs {{ }} via API

**Composants fichiers complétés :**
- `FileCard` : dot statut coloré, toggle CheckSquare/Square, hover actions (relance/suppression)
- `FolderSelector` : navigation arborescence filesystem via API browse, sélection dossier

**Composants common complétés :**
- `ErrorBoundary` : getDerivedStateFromError, retry button, componentDidCatch

**Hooks :**
- `useDocuments` : wrapper documentStore + `selectedCount`
- `useReport` : wrapper reportStore + `canGenerate` + `generate()`
- `useSearch` : wrapper gedStore
- `useDropZone` : react-dropzone + uploadFiles, 9 types MIME acceptés

**Pages mises à jour :**
- `ReportsPage` : OutputMode selector, TemplateUpload conditionnel, GenerateButton, badge sélection
- `GEDPage` : panneau latéral DocumentCard (w-80, wired avec selectedDocId)

**Backend :**
- Router `search.py` : correction GROUP BY sémantique, endpoint `PATCH /api/documents/{id}/metadata`

---

## [v0.2.0] — 2026-04-13

### Backend — Implémentation complète Phase 1 + 2

**Pipeline d'extraction :**
- `ExtractionService.process_file()` : hash SHA256 → dédup → Tika → enrichissement IA (Ollama) → embeddings pgvector
- `ExtractionService.process_zip()` : extraction de chaque fichier ZIP via Tika `/rmeta`
- `EmbeddingService.embed_document()` : chunking → embed par chunk + fallback modèle
- Prompt d'enrichissement IA → JSON parsé robustement (gère ```json```, texte brut, extraction regex)

**Routers FastAPI implémentés :**
- `/api/upload` — multipart + background tasks + polling jobs
- `/api/extract` — status jobs, relance
- `/api/documents` — CRUD + pagination + filtres (statut, extension, source, nom)
- `/api/generate` — génération rapport + SSE streaming temps réel
- `/api/search` — recherche hybride (PostgreSQL full-text 40% + pgvector cosine 60%)
- `/api/export` — Markdown → PDF (weasyprint) + DOCX (python-docx)
- `/api/folders` — CRUD dossiers surveillés + scan en background + browse filesystem
- `/api/prompts` — CRUD prompts pré-enregistrés
- `/api/templates` — upload DOCX + détection champs `{{ champ }}`
- `main.py` — startup : init DB + health check Tika/Ollama (non bloquant)

### Frontend — Interface complète Phase 2

**Couche données :**
- `api/index.ts` : fonctions typées pour tous les endpoints backend
- `documentStore` : liste, sélection multi, upload + polling jobs, delete, relance
- `reportStore` : prompt, modèle, génération SSE, historique, export
- `gedStore` : recherche hybride, filtres, tags, catégories

**Composants :**
- `Sidebar` : navigation + indicateur version
- `Header` : statut Tika/Ollama (ping toutes les 30s)
- `Toast` : système notifications (success/error/info)
- `DropZone` : drag & drop fichiers/ZIP avec react-dropzone + feedback visuel
- `FileExplorer` : liste documents avec statut coloré, sélection multi, actions
- `PromptEditor` : textarea + dropdown presets + sauvegarde API
- `ModelSelector` : dropdown modèles Ollama chargés dynamiquement
- `ReportPreview` : aperçu Markdown rendu + streaming cursor + export PDF/DOCX

**Pages :**
- `ReportsPage` : layout 3 colonnes (fichiers | config | résultat)
- `GEDPage` : recherche hybride + filtres catégories/tags + grille cartes
- `SettingsPage` : gestion dossiers surveillés + état services + ajout/scan/suppression

---

## [v0.1.0] — 2026-04-10

### Ajouté
- Structure complète du projet (backend, frontend, scripts, documentation)
- Configuration Docker Compose avec volumes mappés sur l'hôte (aucune donnée dans les conteneurs)
- Squelette FastAPI avec tous les modules, routers, services, modèles
- Squelette React + Vite + TailwindCSS avec tous les composants
- Configuration du logging structuré (structlog JSON)
- Schéma PostgreSQL + pgvector (init-db.sql)
- Stubs workflows n8n (folder-watcher, indexer, report-pipeline)
- Documentation initiale (architecture, API, DB, guides)
- .gitignore adapté au projet
- CHANGELOG.md (ce fichier)

### Infrastructure
- PostgreSQL 16 + pgvector : données sur `./data/postgres/` (hôte)
- Uploads : `./storage/uploads/` (hôte)
- Exports : `./storage/exports/` (hôte)
- Templates : `./storage/templates/` (hôte)
- Logs : `./logs/` (hôte)
- Documents surveillés : chemin configurable via `DOCUMENTS_ROOT` dans `.env`

---

## Roadmap versions

| Version | Contenu | Statut |
|---------|---------|--------|
| `v0.1.0` | Scaffold + structure | ✅ |
| `v0.2.0` | Backend complet (Tika + Ollama + DB) + Frontend Phase 2 | ✅ |
| `v0.3.0` | GED avancée (DocumentCard, TagManager, VersionHistory, panneau latéral) | ✅ |
| `v0.4.0` | Polish : tests, services complets, n8n workflows | ✅ |
| `v0.5.0` | Migrations Alembic + tests E2E Playwright | ✅ |
| `v1.0.0` | Makefile + pagination GED + tests generate router | ✅ |
| `v1.1.0` | Onglet texte extrait + tests pagination + gedStore tests | ✅ |
| `v1.2.0` | test_documents_router + test_prompts_router + useDocuments/useSearch tests | ✅ |
