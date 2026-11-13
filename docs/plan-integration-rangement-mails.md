# Plan — Intégrer « Gestion des dossiers » (rangement) et « Gestion des mails » à Matothèque

> **Statut : cadrage fait (étape 1), rien n'est codé** (10/11/2026). Sources : `Gestion-des-dossiers/` (dépôt
> `AgestiTC/rangement`, socle SEVE, v0.1.0 en prod + phase 2 finie côté code) et
> `Gestion-des-mails/` (cadrage seul, copié dans [cahier-des-charges-mails.md](cahier-des-charges-mails.md)).
> Les deux dossiers sont **ignorés par git** : leur code est **porté** dans `backend/` et `frontend/`,
> jamais versionné tel quel ici.

## Décisions (validées le 10/11/2026)

| Sujet | Décision | Ce que ça annule / implique |
|---|---|---|
| rangement | **Porté dans Matothèque** (module, pas d'appli séparée) | Annule la décision rangement du 12/10/2026 « appli séparée — écarté : module de la GED ». À noter dans le cahier de rangement § 8 et dans la ROADMAP. |
| Qui déplace les fichiers | **Toujours un seul exécutant**, désormais Matothèque, et un **seul journal d'annulation** (`reorg_moves`) | `/organize/apply` (coupé depuis v1.141.1) est rouvert **uniquement** via le module rangement |
| Agent de poste | L'agent **Go** de rangement est gardé, rapatrié dans `agent/`, et pointé vers l'API de Matothèque | Les jetons de poste rejoignent ceux des automates (`jetons_api`) |
| Mails v1 | **Client mail complet d'abord** (réception, lecture, rédaction, dossiers IMAP, recherche) | **Prérequis** : authentification **activée**, car les boîtes sont personnelles |
| IA | Locale uniquement, via `runtime_config.model_for(usage)` (nouveaux usages `classement_plan`, `mail_reponse`) | — |

### Points de vigilance transverses

- **100 % local** : IMAP/SMTP vers un fournisseur externe **sortent sur Internet**. On le déclare
  dans *Demandes Mise à jour internet* (par compte, confirmé à l'ajout). Les **images distantes** d'un
  mail sont **bloquées par défaut** : les charger est une sortie à confirmer, et sert aussi de pisteur.
- **Une seule logique** : les « copies multiples » de rangement et la page *Doublons* de Matothèque
  sont **fusionnées** en un service unique ; de même pour la cloche (`models/notification.py` existant).
- **Contexte non sécurisé (HTTP LAN)** : jeton de poste affiché une seule fois → `copierTexte()`,
  identifiants → `uuid()`. Ne jamais appeler `navigator.clipboard` ni `crypto.randomUUID`.
- **État en base, jamais en mémoire** (uvicorn `--workers 2`) : scan, empreintes, synchro IMAP et
  rangement passent tous par le **worker durable** (`job_worker`), en priorité basse la nuit.
- **Dev ne déplace jamais de vrais fichiers** : NAS en lecture seule, bac à sable en écriture.

---

## Schéma des modules (validé le 10/11/2026)

```text
backend/models/
├── inventaire.py     inv_emplacements, inv_scans, inv_entrees, inv_instantanes,
│                     inv_doublons_passes, inv_postes [jeton_id → jetons_api], inv_envois,
│                     inv_envoi_dossiers (ids serial / bigserial)
├── rangement.py      plan_classement [parent_id, nom, espace commun | perso, membre_id],
│                     regles_classement, lots_rangement [id = batch_id de reorg_moves]
├── mail.py           mail_comptes, mail_compte_acces, mail_dossiers, mail_messages (en-têtes),
│                     mail_corps (table séparée, exclue de la sauvegarde), mail_envois
│                     [statut brouillon | en_file | envoye | echec ; origine humain | ia ;
│                     valide_par], mail_modeles, mail_regles_pj, mail_pj_documents
├── reorg.py          ReorgMove étendu (décision 3)
└── notification.py   + utilisateur_id, + cle ; NotificationPreference

backend/services/
├── deplacements.py   NOUVEAU — seul exécutant des déplacements physiques + journal ;
│                     appelé par rangement, quarantaine, scan papier
├── chemins.py        NOUVEAU — chemin du montage ↔ smb:// canonique de la GED
├── duplicate_service.py   façade unique des doublons ; lit inv_entrees
├── notifier.py       NOUVEAU — applique les préférences et le dédoublonnage
├── rangement/
│   ├── depot.py          Protocol Depot + DepotPostgres (async)
│   ├── scan.py · exclusions.py · carte.py · wiztree.py
│   ├── empreintes.py     3 passes (taille → début/fin → SHA-256 complet)
│   ├── agent.py          revalidation des lots (noms, types, tailles, bombe gzip)
│   ├── plan.py · regles.py · lots.py · alertes.py
└── mail/
    ├── comptes.py · oauth.py (repris de connectors/gdrive.py) · imap_client.py · smtp_client.py
    ├── mime.py · synchro.py · assainissement.py · envoi.py · modeles.py · pj.py · tri.py
    ├── brouillon_ia.py
    └── droits.py         exiger_utilisateur, compte_accessible

backend/routers/
├── inventaire.py     /api/inventaire (admin)
├── agent.py          /api/agent (jeton de poste)
├── rangement.py      /api/rangement
├── mail.py           /api/mail
└── organize.py       garde propose / plan / move / dry-run ; apply et undo retirés à l'étape 10

backend/tests/fakes/depot_memoire.py   dépôt en mémoire (porté) pour les tests unitaires sous SQLite

agent/                            agent Go (rapatrié de Gestion-des-dossiers/agent/)

frontend/src/
├── pages/rangement/{Carte,Postes,PlanClassement,Lots}Page.tsx
├── pages/DuplicatesPage.tsx      onglets « Copies sur disque » | « Fiches en double dans l'index »
├── pages/MailPage.tsx + components/mail/
└── components/settings/{ComptesMailSection,PreferencesNotificationsSection}.tsx
```

**Tâches durables** (`job_worker`) :

- classe **« fond »** (concurrence 1) : `inventaire_scan`, `doublons_passe` ;
- classe **« io »** : `rangement_lot_apply`, `rangement_lot_undo`, `mail_synchro` (bornée, remise en file),
  `mail_envoi` ; `reorg_apply` et `reorg_undo` sont **remplacés** ;
- classe **« gpu »** : `classement_plan_proposer`, `mail_brouillon`.

**Non portés** : `reglages.py`, `format.py`, `ecran.py` du dépôt rangement. Leurs réglages passent
dans `runtime_config._DEFAULTS`, sous les préfixes `inventaire_*`, `rangement_*` et `mail_*`.

## Décisions d'architecture

| n° | Décision | Étape(s) |
|---|---|---|
| 1 | **Rôles.** Les mails v1 sont réservés au foyer ; pas de personne hors foyer avant un droit par espace. Règles dans `acces.py` : `/api/mail/*` en UTILISATEUR, `/api/inventaire/*` et `/api/rangement/*` en ADMIN. Les trois préfixes entrent dans `INTERDIT_AUX_JETONS`. | 2, 13 |
| 2 | **Jeton de poste.** Portée `agent` ajoutée à `jetons_api.PORTEES` ; ce jeton n'atteint que `/api/agent/*`, tout autre jeton reçoit 403 ; aucune session. Le routeur exige aussi le jeton (dépendance `poste_authentifie`), car le middleware laisse tout passer quand l'auth est éteinte. Bloquer un administrateur révoque ses jetons de poste (à documenter). | 2, 5 |
| 3 | **`reorg_moves`.** `document_id` nullable avec FK `ON DELETE SET NULL` ; colonnes `origine` (`ged_reorg`, `scan`, `quarantaine` ou `rangement`, défaut `ged_reorg`), `est_dossier`, `annule_le`, `annule_par`. L'annulation ne supprime plus de lignes ; elle ne vise qu'un `batch_id` désigné explicitement. Les 5 déplacements du 02/07/2026 restent annulables. | 3, 10 |
| 4 | **Notifications.** `utilisateur_id` nullable (NULL = pour tous), `cle` et index unique partiel `(utilisateur_id, cle) WHERE NOT lu` ; table `notification_preferences`. Tout passe par `notifier.py`. | 2, 11 |
| 5 | **Accès NAS.** Montage local dans le **worker seulement** (prod : `/mnt/media` en rw ; dev : ro, plus un bac à sable en rw). Parcours par `os.scandir` ; un déplacement est un renommage. `chemins.py` traduit en `smb://` ; SMB en repli. Droits du uid 10001 à vérifier avant l'étape 4. | 4, 10 |
| 6 | **Nommage.** Module **Rangement**, parcours **Inventaire**, écrans **Carte / Postes / Plan de classement / Lots**. Doublons : « Copies sur disque » / « Fiches en double ». Mails : `/api/mail`. Jamais « Dossiers » ni « Scan » dans l'interface ; pas de fichier `classement*.py`. | 1, 7 |
| 7 | **Écrans en double.** `ReorganizePage` est fusionnée dans `PlanClassementPage`. `/organize/apply` et `/organize/undo` sont supprimés, et le réglage `reorg_application_physique` est retiré, à l'étape 10. La quarantaine passe par `deplacements.py` avec l'origine `quarantaine`. | 6, 8, 10 |
| 8 | **Portage du socle.** `config_store` → `runtime_config` ; `secrets_store` → `crypto.py` ; Jinja2 → React ; argon2 → OIDC ; ordonnanceur et threads → `job_worker` ; psycopg synchrone → async (transactions courtes par dossier) ; logging → structlog ; Python 3.14 → 3.11 (corriger les `except A, B` sans parenthèses et les annotations différées ; `ruff --target-version py311`). DDL `inv_*` en SQL brut dans `database.py`, derrière `pg_advisory_lock`, ignoré sous SQLite. | 3 à 5 |
| 9 | **Sauvegarde.** `backup.py` avec `--exclude-table-data` pour `inv_entrees`, `inv_instantanes`, `inv_envoi_dossiers`, `mail_corps` (constante `TABLES_RECONSTRUCTIBLES`). Rescan après restauration. | 3 |
| 10 | **Mails sans authentification.** `exiger_utilisateur` renvoie 409 si l'auth est éteinte. L'administrateur ne lit pas les boîtes des autres. Le menu Mails est masqué si l'auth est éteinte. | 2, 13 |

### Constats relevés dans le code au cadrage

Vérifiés dans le dépôt Matothèque le 10/11/2026 :

- `POST /organize/undo` annule le **dernier lot du journal, quelle que soit son origine**
  (`backend/routers/organize.py`, sélection du `batch_id` le plus récent sans filtre).
  `services/scan_service.py` écrit aussi dans `reorg_moves` avec `batch_id = scan.id` : une annulation
  peut donc défaire un rangement de scan papier. Corrigé par la décision 3.
- L'annulation **supprime les lignes** du journal (`services/job_handlers.py`, `db.delete(m)`).
- `DOCUMENTS_ROOT` est monté en **rw** (`docker-compose.yml`, lignes 188 et 243), alors que
  l'exemple de `CLAUDE.md` dit `:ro`. Le montage du NAS en écriture est une décision à prendre (décision 5).
- `CONCURRENCE_IO = 3` (`services/job_worker.py`) : il faut une classe « fond » pour les scans.
- Les tests existants `backend/tests/test_reorg_rangement.py` et `test_auth_protection.py` appellent
  `/api/organize/apply` et `/api/organize/undo` : ils seront à réécrire à l'étape 10.
- Les tests backend tournent sous SQLite, incompatible avec le DDL `inv_*` : dépôt mémoire pour
  l'unitaire, PostgreSQL via `/verify`.
- `GET /duplicates` reparcourt le disque à chaque requête (étape 6).

Relevés dans le dépôt rangement, **non revérifiés** par ce cadrage (dépôt ignoré par git) : code en
Python 3.14 ; threads et verrou de schéma en mémoire à transformer en jobs.

### Bibliothèques retenues

- **IMAPClient** (licence BSD-3), appelé via `asyncio.to_thread`.
- **smtplib** (bibliothèque standard), via `to_thread` dans le job `mail_envoi`.
- **email** (bibliothèque standard), avec `policy.default`.
- **nh3** (MIT) pour l'assainissement HTML : retrait de `<style>` ; refus des `style` contenant
  `url(`, `@import` ou `expression` ; `src` distants réécrits en `data-src-bloque` ; `cid:` servis par
  l'API ; CSP propre `default-src 'none'; img-src data: 'self'; style-src 'unsafe-inline'` ; iframe
  `sandbox` sans `allow-scripts` ni `allow-same-origin`.
- **OAuth** via httpx, en reprenant `connectors/gdrive.py`.
- **GreenMail** (Apache-2.0) comme serveur IMAP de test, dans un profil de `docker-compose.dev.yml`
  lié à `127.0.0.1`.
- **Recherche** : tsvector en français (PostgreSQL).

Licences à confirmer à l'ajout (`pip-licenses`).

Pièges : le jeton de rafraîchissement Google expire au bout de 7 jours en mode test, donc préférer un
mot de passe d'application pour Gmail. Outlook.com et Microsoft 365 imposent OAuth2.

## ADR — Rangement porté dans Matothèque (10/11/2026)

- **Contexte.** Rangement v0.1.0 est en prod dans `/opt/rangement`. La décision du 12/10/2026 en
  faisait une appli séparée. Depuis, il y aurait deux exécutants potentiels de déplacements, deux
  journaux, deux écrans de doublons, deux cloches, deux socles et deux authentifications.
- **Décision.** Rangement devient un module de Matothèque. Le code porté n'est jamais versionné tel
  quel. Les tables `inv_*` sont dans la base de Matothèque. Le worker reçoit une classe « fond ».
  `services/deplacements.py` est le seul exécutant. `reorg_moves` porte une origine.
  `duplicate_service.py` est unique, `notifier.py` centralise les notifications. L'agent Go est conservé,
  avec un jeton de portée `agent`. Le NAS est lu par un montage local du worker, traduit en `smb://`.
- **Conséquences positives.** Une interface, un SSO, une sauvegarde, un déploiement. La GED suit les
  déplacements sans réindexation. Plus de double annulation.
- **Conséquences négatives.** Portage async et passage de Python 3.14 à 3.11. Base de +1 à 2 Go, exclue
  du dump. Montage NAS en écriture dans le worker. Tests d'inventaire sur PostgreSQL.
- **Écarté.** Appli séparée appelant l'API de la GED. Parcours du NAS par SMB, trop lent sur 15 To.
- **Statut.** Accepté (10/11/2026).

## Décisions qui restent à Thomas

| Réf | Sujet | Défaut recommandé | Bloque |
|---|---|---|---|
| D1 | Qui utilise les mails ? | Foyer seulement en v1 — **✅ tranché par Thomas le 11/11/2026** | Étape 2 |
| D2 | Fournisseur des boîtes | `mode_auth` `mot_de_passe` ou `oauth2` ; OAuth2 seulement pour Microsoft 365 et outlook.com ; Gmail par mot de passe d'application | Étape 13 |
| D3 | Boîtes personnelles ou partagées | Les deux : propriétaire + `mail_compte_acces` (lecture ou envoi) | Étape 13 |
| D4 | Accès au NAS | Montage `/mnt/media` dans le worker seul — **✅ tranché par Thomas le 13/11/2026, en deux temps** : lecture seule à l'étape 4, écriture à l'étape 10 seulement (voir « Relevé du 13/11/2026 » ci-dessous) | Étape 4 |
| D5 | Rangement visible par qui | Administrateur seulement en v1 ; espaces PERSO repoussés | — |
| D6 | Relève IMAP | 5 min réglable, pas d'IDLE, en-têtes seuls | Étape 14 (défaut appliqué sans réponse) |
| D7 | Conservation (RGPD) | Corps 30 j, en-têtes 365 j, journal d'envoi 1 an, tous réglables | Étape 14 |
| D8 | Tri des pièces jointes | Règles explicites ; l'IA propose, l'humain valide | Étape 17 |
| D9 | `ReorganizePage` et `/organize/apply` ou `undo` | Fusion dans Plan de classement ; apply et undo supprimés à l'étape 10 | Étape 8 |
| D10 | Consentement à la sortie Internet | Confirmation par compte (`sortie_confirmee_le`, `sortie_confirmee_par`) + interrupteur global `mail_releve_active` | Étape 13 |

D1 bloque l'étape 2, D4 l'étape 4, D2 et D3 l'étape 13.

### Relevé du 13/11/2026 — accès au NAS depuis le LXC (D4)

Relevé par Thomas dans le LXC 102 (`mount`, `ls -ldn /mnt/media`) :

- `//192.168.42.200/media` est **déjà monté** sur `/mnt/media` du LXC, en cifs, lecture et écriture,
  avec le compte NAS `srvplex`. Propriétaire vu dans le LXC : 1000:1000 ; dossiers `0775`,
  fichiers `0664`.
- Le worker tourne sous l'uid 10001 : il est « autres », donc **lecture possible, écriture
  impossible**. C'est exactement ce que demande l'étape 4.
- **Étape 4** : ajouter au service `worker` du compose de prod le volume `/mnt/media:/mnt/media:ro`,
  à la livraison de l'étape, pas avant. Rien à changer sur le NAS ni sur le LXC.
- **Étape 10** (déplacements) : passer le volume en `rw` et ajouter `group_add: ["1000"]` au worker
  (le groupe a `rwx`). Geste séparé, à la demande de Thomas, une fois l'annulation par lot en place.
  Les écritures se feront sur le NAS au nom de `srvplex`.
- Le partage contient la médiathèque (Films, Series, DVD, Documentaires, Ebook…). **Non tranché** :
  l'inventaire doit-il aussi couvrir d'autres partages du NAS, qui ne sont pas montés dans le LXC ?
  Par défaut, l'étape 4 se limite à `/mnt/media`.

## Corrections apportées aux étapes

Les étapes 5, 6, 10, 11 et 14 ci-dessous ont été corrigées au cadrage (10/11/2026) pour s'accorder
aux décisions ci-dessus.

---

## Phase A — Préparer

### Étape 1 — Cadrage commun et décisions consignées
Consigner l'annulation de la décision du 12/10 (cahier rangement § 8 et § 9, ROADMAP de
Matothèque), trancher les questions ouvertes des mails (fournisseur des boîtes → OAuth2 si
Microsoft 365 / Google ; boîtes partagées ou personnelles ; nombre d'utilisateurs) et définir le
découpage en modules (`backend/services/rangement/`, `backend/services/mail/`, routeurs, pages).
- **Acceptation** : ROADMAP avec les deux chantiers en `[ ]` ; questions ouvertes des mails répondues ou explicitement repoussées ; schéma des modules validé.

### Étape 2 — Activer l'authentification (prérequis mails et espaces perso)
L'auth OIDC (SSO du NAS) est codée mais éteinte (`oidc_service.auth_active()` faux). L'activer,
fournir une dépendance « utilisateur courant » réutilisée par les deux modules, et vérifier que
l'API agent (jeton) et les jetons d'automates restent accessibles sans session.
- **Acceptation** : avec `auth_active`, toute route mail renvoie 401 sans session ; l'agent passe avec son jeton ; accès de secours LXC documenté et testé.
- **État (11/11/2026)** : code fait — décisions n° 1 et 2 dans `services/acces.py` et `services/jetons_api.py`
  (portée `agent`, `poste_authentifie`), tests `test_acces_modules_rangement_mails.py` ; la dépendance
  « utilisateur courant » existe déjà (`routers/auth.utilisateur_courant`) ; l'accès de secours
  (`python -m outils.auth --eteindre`) a été testé en prod le 04/11. Reste l'**activation** en prod.
  La décision n° 4 (Notification nullable + `cle`) est reportée à l'étape 11, qui seule l'utilise.

## Phase B — Rangement (Gestion des dossiers)

### Étape 3 — Schéma de l'inventaire dans la base de Matothèque
Créer les tables `inv_emplacements`, `inv_scans`, `inv_entrees`, `inv_instantanes`,
`inv_doublons_passes`, `inv_postes`, `inv_envois`, `inv_envoi_dossiers` (reprises de
`Gestion-des-dossiers/app/inventaire/db.py`) en modèles SQLAlchemy async, ajoutées par les
migrations à chaud de `database.py`. Index pensés pour des centaines de milliers de lignes.
- **Acceptation** : le démarrage crée les tables sur une base vide et sur une copie de prod ; le dépôt (`depot_postgres.py`) est porté en service async avec ses tests.
- **État (12/11/2026)** : fait, branche `feat/etape3-inventaire`.
  - Schéma en **SQL brut** dans `backend/models/inventaire.py` (décision n° 8, qui prime sur « modèles
    SQLAlchemy » ci-dessus : index partiels, `text_pattern_ops`, `INCLUDE`, réglages de stockage),
    créé par `database._schema_inventaire` sous verrou d'avis, PostgreSQL seulement. Seul ce qui
    manque est joué (catalogue relu sous le verrou) : un redémarrage ne verrouille rien.
  - `inv_postes.jeton_id → jetons_api` (décision n° 2) remplace l'empreinte du jeton : le contrat
    devient `creer_poste(nom, jeton_id)`, `poste_par_jeton(jeton_id)`, `changer_jeton_poste`.
  - Dépôt : contrat `services/rangement/depot.py`, `DepotPostgres` async
    (`services/rangement/depot_postgres.py`, une transaction courte par opération,
    `synchronous_commit = off` par transaction), double `tests/fakes/depot_memoire.py`.
    `tests/test_inventaire_depot.py` fait passer les **mêmes** tests aux deux ; le passage
    PostgreSQL demande `INVENTAIRE_TEST_DATABASE_URL` (schéma jetable par test).
  - `reorg_moves` (décision n° 3) : colonnes `origine`, `est_dossier`, `annule_le`, `annule_par`
    ajoutées ; le scan papier écrit `origine = 'scan'`. **Reste pour l'étape 10** : `document_id`
    nullable + `ON DELETE SET NULL`, annulation par lot désigné sans suppression de ligne, et
    l'étiquetage des lignes de scan déjà journalisées (elles portent `ged_reorg` par défaut).
  - Sauvegarde (décision n° 9) : `backup.TABLES_RECONSTRUCTIBLES`, `--exclude-table-data`.
  - Vérifié sur piles jetables : base initialisée par la v1.165.0 puis démarrée avec le nouveau
    code (2 process : un seul crée, 19 instructions), base vide, dump sans les données de
    `inv_entrees`. **Non fait** : l'essai sur une copie de la base de prod (pas de dump de prod
    tiré pour cette étape) ; le chemin « base existante » est couvert par l'essai v1.165.0.

### Étape 4 — Scan de l'inventaire, exclusions, import WizTree
Porter `scan.py`, `service.py`, `exclusions.py`, `carte.py`, `wiztree.py` : parcours en
métadonnées seules, comparaison dossier par dossier (un rescan sans changement n'écrit rien),
historique apparu/modifié/disparu, exclusions verrouillées (PBS, `@eaDir`, `#recycle`,
`#snapshot`, `@…`, `DOUBLON-MATOTEQUE`), tâche de nuit via `job_worker`, API `/api/inventaire/*`
(admin), racine confinée sous le montage NAS en lecture seule.
- **Acceptation** : les tests portés de `Gestion-des-dossiers/tests/` passent ; un doute (réseau, encodage) n'est jamais « disparu » ; un import WizTree invalide ne change rien.
- **État (13/11/2026)** : **livrée en v1.172.0**. `services/rangement/` :
  `exclusions.py`, `reglages.py` (clés `inventaire_*` de `runtime_config`, écrites par
  `PUT /api/inventaire/reglages`), `scan.py` (async ; `os.scandir` dans un fil, un dossier à la fois),
  `carte.py`, `wiztree.py`, `agent.py` (partiel : poste sans jeton, déclaration, traitement d'un envoi —
  le reste à l'étape 5), `service.py`, `jobs.py` (tâches `inventaire_scan`, `inventaire_nuit`,
  `inventaire_import`, et l'enfilement de la tournée). Worker : classe **« fond »** (une place, sans
  réglage, indifférente à la pause IA et à la plage des lots), ordonnanceur de la tournée (tick 60 s,
  verrou d'avis, jamais deux tournées). `routers/inventaire.py` : état, réglages, emplacements
  (déclarer, activer), scan (202 + tâche), carte (JSON), import WizTree (202 + tâche).
  **Écart avec l'original** : l'API ne voit pas le NAS (montage du worker seul) ; elle contrôle les
  chemins **sur le texte** (absolu, sans « .. », sous `inventaire_racine_autorisee`, `/mnt/media` par
  défaut) et le worker les recontrôle **sur le disque** (chemin réel, lien, existence) au moment de
  lire. L'import WizTree est donc entièrement fait par le worker : un fichier refusé se lit dans le
  résultat de la tâche, pas dans la réponse HTTP. Tests portés : `test_inventaire_{scan,carte,wiztree,api}.py`.
  **À la livraison** : ajouter `- /mnt/media:/mnt/media:ro` au service `worker` du compose de PROD
  (`/opt/docflow`, LXC 102), puis `up -d worker`.
  **v1.172.1 — deux NAS** : `/mnt/media/nas-media` est un AUTRE NAS monté par le Synology dans la
  médiathèque (Thomas, 13/11/2026). Il est déclaré comme son propre emplacement (« NAS 2 ») ; le parent
  saute la racine des emplacements placés dedans (`scan.exclusions_de`). **Pour l'étape 10** : un
  déplacement entre la médiathèque et `nas-media` n'est PAS un renommage, mais une copie réseau puis
  une suppression, à traiter comme telle (vérification de la copie, reprise après coupure).

### Étape 5 — API agent et agent Go rapatrié
Porter `routes_agent.py` (`/api/agent/config|envois|lots|fin|empreintes`) : jeton par poste
stocké en SHA-256 (jeton `jetons_api` de portée `agent`, décision 2), lots revalidés (noms, types, tailles, bombe gzip).
Rapatrier `Gestion-des-dossiers/agent/` dans `agent/`, rendre l'URL du serveur configurable et
garder la vérification TLS.
- **Acceptation** : l'agent de PC-GAME envoie un inventaire complet au dev Matothèque ; un jeton révoqué est refusé ; un lot gzip piégé est rejeté sans charger la mémoire.
- **État (13/11/2026)** : fait, les trois critères vérifiés sur une pile jetable PostgreSQL (agent
  construit et lancé sur PC-GAME → scan « agent » terminé ; jeton révoqué → 401 ; bombe gzip → 413).
  Serveur : `services/rangement/agent.py` (complété), `services/rangement/postes.py` (poste + jeton
  `agent` émis par `admin_identifie`, nom unique horodaté, renouvellement qui révoque l'ancien),
  `routers/agent.py` (`poste_authentifie`, corps lu en flux plafonné à 10 Mo), tâche worker
  `inventaire_envoi` (classe « fond »), routes admin `/api/inventaire/postes*`. Agent : `agent/`
  (jetons `mato_`, version 0.2.0). Doc : [agent-de-poste.md](agent-de-poste.md). Le rapprochement
  des empreintes côté serveur reste à l'étape 6 ; l'écran Postes à l'étape 7.

### Étape 6 — Une seule logique de doublons
Faire de `duplicate_service.py` la **façade unique** des doublons. Les **copies multiples** y entrent
en 3 passes (taille → début/fin → SHA-256 complet, empreintes gardées, limite de lecture par nuit),
lues depuis `inv_entrees`. Le parcours disque à chaque `GET /duplicates` est supprimé. Page *Doublons*
conservée, avec ses onglets (décision 6) ; la quarantaine passe par `deplacements.py` (décision 7).
- **Acceptation** : un seul service de doublons appelé par la page et par la cloche ; tests existants de Doublons verts ; plus de code mort de l'ancien scan.
- **État (13/11/2026)** : fait. `services/rangement/copies.py` (3 passes portées de rangement, lectures
  dans un fil dédié en priorité basse, limite `inventaire_copies_limite_nuit_go` = 200 Go) ; la tournée
  de nuit enchaîne scans puis passe (même tâche « fond ») ; tâche `inventaire_copies` et
  `POST /api/inventaire/copies` pour une passe à la demande. `duplicate_service.py` est la façade :
  `copies_sur_disque` (inventaire) ; `GET /api/duplicates` ne parcourt plus rien ; `find_duplicates`
  (ancien scan de `DOCUMENTS_ROOT`, vide en prod) supprimé avec ses deux tests H6/M3, remplacés.
  Onglets renommés « Fiches en double » / « Copies sur disque » (décision 6). **Écarts** : la
  quarantaine des copies de l'inventaire n'est pas offerte (NAS en lecture seule → étape 10) ; la
  « cloche » n'existe pas encore (étape 11) — la façade est prête pour elle. **Trouvé à l'essai** : un
  emplacement déclaré DANS un autre faisait compter ses fichiers deux fois tant que le parent n'était
  pas rescanné → la déclaration relance le scan du parent, et la façade dédoublonne par chemin.

### Étape 7 — Écrans React : Carte, Copies multiples, Postes
Remplacer les écrans Jinja2 (`/carte`, `/carte/doublons`, `/carte/postes`) par des pages React :
répartition par emplacement et dossier (barres + pourcentages écrits), familles de types,
50 plus gros fichiers, évolution, postes (jeton affiché une fois, copie par `copierTexte()`).
- **Acceptation** : les trois écrans fonctionnent par la route HTTP du LAN ; ils restent lisibles de 390 à 1920 px ; `npm run build` et vitest verts.
- **État (13/11/2026)** : fait. Page **Rangement** (`/rangement`, admin) : onglet **Carte**
  (`components/rangement/CarteInventaire.tsx` — emplacements avec leur part du total, navigation
  dossier par dossier, barres + pourcentages écrits, familles de types, plus gros fichiers, ce qui a
  grossi, déclarer / scanner / désactiver) et onglet **Postes** (`PostesInventaire.tsx` — créer un
  poste, jeton affiché une fois et copié par `copierTexte()`, confier un dossier, nouveau jeton,
  désactiver, import WizTree). Le 3ᵉ écran (copies) est l'onglet « Copies sur disque » de *Doublons*
  (étape 6) : pas de second écran pour la même chose. Mise en forme : `utils/formatInventaire.ts`
  (portée de `format.py`, testée). Vérifié sur pile jetable PAR L'IP DU LAN (contexte non sécurisé :
  la copie du jeton marche) à 390, 1440 et 1920 px, sans débordement ni erreur console ; `npm run build`,
  `tsc` et 479 tests vitest verts. Pas de changement backend.

### Étape 8 — Conception du plan de classement
Concevoir l'arborescence cible (modèle § 5 du PLAN de rangement : `00-A-TRIER` … `PERSO/<membre>`),
les règles d'affectation (« `.exe` → 50-LOGICIELS », « photos → 20-FAMILLE/Photos/{année} »),
la partie commune et les espaces personnels, et la façon dont `organize/propose` + `reorg_plan`
deviennent la source des propositions IA.
- **Acceptation** : un document de conception validé (modèle de données, règles, flux IA → validation humaine) ; le recouvrement avec `ReorganizePage` est tranché.
- **État (13/11/2026)** : fait — [conception-plan-classement.md](conception-plan-classement.md),
  **validé par Thomas** (C1 à C8) : les partages Synology restent le 1er niveau et le plan s'applique
  dedans ; `media` d'abord (noms de 1er niveau verrouillés à cause de Plex), puis `Partage-Nas-Mato`,
  `photo`, `music`, `homes` ; *Réorganiser* fusionné au plan (D9 tranchée) ; l'IA propose, Thomas
  valide tout. Modèle : `plan_noeuds`, `plan_regles`, `plan_propositions` (reprend `reorg_plan`).
  **Aligné le même jour sur le plan [réorganisation du NAS-MATO](plan-reorganisation-nas-mato.md)**
  (C9 : `fam-documents` par personne puis par thèmes ; C10 : l'étape 10 commence par un petit dossier
  de `homes/Tom` → `fam-documents/Thomas/`, D6). **Prérequis de l'étape 9** : inventorier `homes/Tom`
  (montage en lecture seule, compte `svc-rangement` à créer côté NAS par Thomas).

### Étape 9 — Plan de classement : implémentation
Tables plan/règles, éditeur (reprendre le glisser-déposer de `ReorganizePage.tsx`), propositions
IA à partir de la carte (usage `classement_plan`), affectation de chaque grand dossier.
- **Acceptation** : pour chaque grand dossier de la carte, l'outil dit où il irait ; aucune proposition n'est appliquée sans validation.
- **État (13/11/2026)** : fait pour `media`. Tables `plan_noeuds`, `plan_regles`, `plan_propositions`
  (ORM, créées au démarrage) ; `services/rangement/plan.py` (modèle de départ de `media` : rubriques de
  1er niveau verrouillées avec une description, `00-A-TRIER`, 3 règles ; candidats = grands dossiers ;
  règles d'abord, puis l'IA locale, usage `classement_plan`, choix limité aux nœuds du plan ; décision
  humaine gardée tant que le dossier ne change pas) ; tâche worker `plan_propositions` (classe GPU) ;
  onglet *Rangement › Plan de classement* (propositions à valider / corriger / refuser, arbre, règles) ;
  « irait dans … » sur la Carte ; bandeau de renvoi dans *Réorganiser*. **Essai avec la vraie IA**
  (llama3.1, 13 éléments, 6 s) : sans descriptions ni contexte, toute vidéo partait dans « Films » ;
  avec, 12 réponses sur 13 sensées, la 13ᵉ se corrige d'un clic. Une IA en panne n'est plus attendue
  qu'une fois par calcul. **Reste** : `homes/Tom` (compte `svc-rangement`), règles `categorie_ged` et
  `etiquette_musique`, migration de `reorg_plan`, « apprendre des validations » — repoussés avec
  l'arrivée des partages correspondants (C8/C10).

### Étape 10 — Ranger par lots, avec annulation
Rouvrir le rangement physique **seulement** dans ce module : lots (un dossier, un type…), aperçu
obligatoire (`apply/dry-run`), déplacement sans jamais supprimer, collisions `_(n)`, sans place →
`00-A-TRIER`, journal unique `reorg_moves` (colonne `origine`), annulation d'un lot désigné **sans suppression de
lignes** (décision 3). Le déplacement passe par `services/deplacements.py`, seul exécutant. Ne jamais renommer **et** déplacer
en une opération (sinon la GED ré-extrait le document).
- **Acceptation** : un lot de 1 000 fichiers (bac à sable) est rangé, vérifié puis annulé en un clic ; zéro suppression dans le journal ; la synchro GED voit « déplacé », sans réindexation.
- **État (13/11/2026)** : fait, **NAS de prod encore en lecture seule** (le lot y est refusé proprement).
  `services/rangement/deplacements.py` = seul exécutant : `os.rename` dans le même montage (jamais
  copier + effacer ; autre disque → refusé), nom suffixé `_(n)` seulement si la place est prise, aperçu
  calculé dans l'inventaire puis revérifié sur le disque, lien jamais suivi, montage `:ro` détecté.
  Table `plan_lots` ; journal `reorg_moves` (origine `rangement`, `document_id` facultatif, FK `SET NULL`)
  écrit ligne à ligne ; annulation d'un lot désigné, sans supprimer de ligne. Tâches worker
  `rangement_appliquer` / `rangement_annuler` (classe « fond ») ; rescan de l'emplacement après coup.
  Bloc « Ranger ce qui est validé » dans *Plan de classement* (aperçu, confirmation, historique, annuler).
  **`/organize/apply`, `/organize/undo`, `reorg_apply`, `reorg_undo` et `reorg_application_physique`
  retirés** ; *Réorganiser* garde son plan virtuel et sa simulation. Vérifié : 1 000 fichiers rangés puis
  annulés (bac à sable, 1 000 lignes gardées) ; de bout en bout sur PostgreSQL, lecture seule → refus,
  écriture → rangé puis annulé. **Reste** : ouvrir l'écriture en prod (geste de Thomas : montage `rw` +
  `group_add: ["1000"]` sur le worker), puis le 1er vrai lot (C10 : un petit dossier de `homes/Tom`, après
  `svc-rangement`) ; « la synchro GED voit déplacé » sera vérifié avec ce 1er lot de `homes` (la
  médiathèque n'a pas de fiches GED).
- **13/11/2026, v1.177.1** : écran *Réorganiser* retiré (D9) ; `/reorganiser` → `/rangement`. L'API
  `/organize/*` et `reorg_plan` restent jusqu'à leur reprise dans le plan de classement. **Écriture : le
  NAS refuse l'écriture au compte `srvplex`** (essai du 13/11) — ouvrir l'écriture demande un montage
  par l'hôte Proxmox avec `svc-rangement`, qui a le droit d'écrire ; voir le compte rendu du 13/11.
- **13/11/2026 (nuit) — ÉCRITURE OUVERTE en prod** : l'hôte PVE monte `//192.168.42.200/media` avec
  `svc-rangement` (lecture/écriture) sur `/mnt/rangement/media` (fstab du PVE, credentials
  `/root/.smb-svc-rangement`), prêté au LXC 102 en `mp1` ; le worker le voit en `/mnt/rangement/media`
  (rw, `group_add: ["1000"]`, compose sauvegardé en `docker-compose.yml.avant-ecriture`). Racine
  autorisée = `/mnt/rangement` ; les 2 emplacements ont suivi (rescan : 0 ajout, 0 disparu). `mp0`
  (`srvplex`, `/mnt/media`, lu par Plex) inchangé. **Reste** : `homes/Tom` (`mp2`, monté mais refusé
  -13 : il manque à `svc-rangement` un droit sur le partage `homes` lui-même, côté DSM).

### Étape 11 — Cloche du rangement
Brancher sur `models/notification.py` existant, via le nouveau `services/notifier.py` (seul point
d'entrée : préférences, dédoublonnage ; décision 4) : fichier hors plan, place disque (seuil 80 %), croissance
anormale, nouveaux doublons, fin de tâches ; préférences par personne (alertes, seuils, heures
de silence).
- **Acceptation** : un fichier déposé hors plan dans le bac à sable apparaît dans la cloche le jour même, avec une proposition ; les préférences d'un utilisateur ne touchent pas celles d'un autre.

### Étape 12 — Bascule de la prod et retrait de l'appli rangement
Inventaire = reconstructible : rescanner plutôt que migrer. Repointer les agents, arrêter
`/opt/rangement` sur le LXC, archiver le dépôt `AgestiTC/rangement` (README « intégré à
Matothèque vX.Y »), déployer par `scripts/deployer.ps1`.
- **Acceptation** : `verifier-deploiement.ps1` vert ; la Carte de prod montre le NAS et les postes ; le conteneur rangement est arrêté sans perte (journal de rangement vide avant bascule).

## Phase C — Mails

### Étape 13 — Comptes mail et secrets
Modèle `mail_comptes` (IMAP + SMTP, par utilisateur ou partagé), mots de passe chiffrés par
`services/crypto.py` (Fernet), **jamais renvoyés par l'API** ; OAuth2 si M365/Google ; écran
*Paramètres › Comptes mail* inspiré de *Mail & Impression*, bouton « Tester ». Chaque compte est
une sortie Internet déclarée et confirmée.
- **Acceptation** : un compte de test (IMAP local de dev, ex. GreenMail/Dovecot jetable) se connecte ; le secret n'apparaît ni dans les réponses API ni dans les journaux ; un autre utilisateur ne voit pas ce compte.

### Étape 14 — Synchronisation IMAP
Cache des en-têtes et dossiers en base (UID/UIDVALIDITY, drapeaux), relève incrémentale par le
worker (relève périodique bornée, réglable, 5 min par défaut ; pas d'IDLE en v1), corps chargés à la demande, recherche (plein texte
sur le cache + `SEARCH` IMAP). Durée de conservation du cache réglable (RGPD).
- **Acceptation** : une relève sans nouveauté n'écrit rien ; un changement d'UIDVALIDITY reconstruit le dossier sans doublon ; 10 000 en-têtes synchronisés sans bloquer l'interface.

### Étape 15 — Boîte de réception et lecture sécurisée
Page React *Mails* : comptes, dossiers, liste, lecture. HTML **assaini** côté serveur et affiché
dans une iframe isolée (`sandbox`, CSP), images distantes bloquées par défaut, PJ téléchargeables
(et passées par ClamAV).
- **Acceptation** : un mail piégé (script, `onerror`, CSS externe) ne s'exécute pas ; aucune requête externe n'est émise à l'ouverture ; une PJ infectée est refusée.

### Étape 16 — Rédaction, réponse, transfert, modèles
Éditeur, réponse/réponse à tous/transfert, envoi SMTP par le worker (journal d'envoi), copie dans
« Envoyés », modèles avec marqueurs (`[[MAIL_LOGO_ENTETE]]`…) et bouton ↺ « revenir au défaut »
(réglages en base).
- **Acceptation** : un mail envoyé arrive et se range dans « Envoyés » ; un échec SMTP est visible et rejouable ; ↺ restaure le modèle par défaut.

### Étape 17 — PJ vers la GED et tri automatique
Bouton « Ajouter à la GED » (pipeline d'import existant : Tika, IA, embeddings), règles de tri
(expéditeur, objet, type de fichier, ou laissé à l'IA), lien PJ ↔ document dans la fiche.
- **Acceptation** : sur 20 mails réels de test, une facture arrive dans la GED classée sans action manuelle ; une PJ déjà indexée devient une copie liée (`doublon_de`), pas un doublon.

### Étape 18 — Brouillon de réponse IA, validé par un humain
Usage `mail_reponse` (IA locale), brouillon proposé dans l'éditeur, **aucun envoi sans clic**,
contexte borné (`num_ctx`), cloche « mail important en attente ».
- **Acceptation** : aucun chemin de code n'envoie un brouillon IA sans action utilisateur (test dédié) ; le journal d'envoi indique « brouillon IA validé par X ».

### Étape 19 — Tests de bout en bout et documentation
Parcours e2e (carte → plan → lot rangé → annulé ; compte mail → lecture → réponse → PJ vers GED),
`CHANGELOG`, `README-UTILISATEUR`, aide dans l'appli + BookStack (doc **mixte** décidée au cadrage
mails), mise à jour de `CLAUDE.md` (structure, nouveaux pièges).
- **Acceptation** : e2e verts sur la pile jetable (`/verify`) ; doc utilisateur des deux modules publiée ; CLAUDE.md à jour.
