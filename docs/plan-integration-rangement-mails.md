# Plan — Intégrer « Gestion des dossiers » (rangement) et « Gestion des mails » à Matothèque

> **Statut : plan, rien n'est codé** (10/11/2026). Sources : `Gestion-des-dossiers/` (dépôt
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

## Phase B — Rangement (Gestion des dossiers)

### Étape 3 — Schéma de l'inventaire dans la base de Matothèque
Créer les tables `inv_emplacements`, `inv_scans`, `inv_entrees`, `inv_instantanes`,
`inv_doublons_passes`, `inv_postes`, `inv_envois`, `inv_envoi_dossiers` (reprises de
`Gestion-des-dossiers/app/inventaire/db.py`) en modèles SQLAlchemy async, ajoutées par les
migrations à chaud de `database.py`. Index pensés pour des centaines de milliers de lignes.
- **Acceptation** : le démarrage crée les tables sur une base vide et sur une copie de prod ; le dépôt (`depot_postgres.py`) est porté en service async avec ses tests.

### Étape 4 — Scan de l'inventaire, exclusions, import WizTree
Porter `scan.py`, `service.py`, `exclusions.py`, `carte.py`, `wiztree.py` : parcours en
métadonnées seules, comparaison dossier par dossier (un rescan sans changement n'écrit rien),
historique apparu/modifié/disparu, exclusions verrouillées (PBS, `@eaDir`, `#recycle`,
`#snapshot`, `@…`, `DOUBLON-MATOTEQUE`), tâche de nuit via `job_worker`, API `/api/inventaire/*`
(admin), racine confinée sous le montage NAS en lecture seule.
- **Acceptation** : les tests portés de `Gestion-des-dossiers/tests/` passent ; un doute (réseau, encodage) n'est jamais « disparu » ; un import WizTree invalide ne change rien.

### Étape 5 — API agent et agent Go rapatrié
Porter `routes_agent.py` (`/api/agent/config|envois|lots|fin|empreintes`) : jeton par poste
stocké en SHA-256 (réutiliser `jetons_api`), lots revalidés (noms, types, tailles, bombe gzip).
Rapatrier `Gestion-des-dossiers/agent/` dans `agent/`, rendre l'URL du serveur configurable et
garder la vérification TLS.
- **Acceptation** : l'agent de PC-GAME envoie un inventaire complet au dev Matothèque ; un jeton révoqué est refusé ; un lot gzip piégé est rejeté sans charger la mémoire.

### Étape 6 — Une seule logique de doublons
Fusionner les **copies multiples** (3 passes : taille → début/fin → SHA-256 complet, empreintes
gardées, limite de lecture par nuit) avec `duplicate_service.py` / page *Doublons* existants :
un service, une nomenclature, la quarantaine actuelle conservée.
- **Acceptation** : un seul service de doublons appelé par la page et par la cloche ; tests existants de Doublons verts ; plus de code mort de l'ancien scan.

### Étape 7 — Écrans React : Carte, Copies multiples, Postes
Remplacer les écrans Jinja2 (`/carte`, `/carte/doublons`, `/carte/postes`) par des pages React :
répartition par emplacement et dossier (barres + pourcentages écrits), familles de types,
50 plus gros fichiers, évolution, postes (jeton affiché une fois, copie par `copierTexte()`).
- **Acceptation** : les trois écrans fonctionnent par la route HTTP du LAN ; ils restent lisibles de 390 à 1920 px ; `npm run build` et vitest verts.

### Étape 8 — Conception du plan de classement
Concevoir l'arborescence cible (modèle § 5 du PLAN de rangement : `00-A-TRIER` … `PERSO/<membre>`),
les règles d'affectation (« `.exe` → 50-LOGICIELS », « photos → 20-FAMILLE/Photos/{année} »),
la partie commune et les espaces personnels, et la façon dont `organize/propose` + `reorg_plan`
deviennent la source des propositions IA.
- **Acceptation** : un document de conception validé (modèle de données, règles, flux IA → validation humaine) ; le recouvrement avec `ReorganizePage` est tranché.

### Étape 9 — Plan de classement : implémentation
Tables plan/règles, éditeur (reprendre le glisser-déposer de `ReorganizePage.tsx`), propositions
IA à partir de la carte (usage `classement_plan`), affectation de chaque grand dossier.
- **Acceptation** : pour chaque grand dossier de la carte, l'outil dit où il irait ; aucune proposition n'est appliquée sans validation.

### Étape 10 — Ranger par lots, avec annulation
Rouvrir le rangement physique **seulement** dans ce module : lots (un dossier, un type…), aperçu
obligatoire (`apply/dry-run`), déplacement sans jamais supprimer, collisions `_(n)`, sans place →
`00-A-TRIER`, journal unique `reorg_moves`, annulation d'un lot. Ne jamais renommer **et** déplacer
en une opération (sinon la GED ré-extrait le document).
- **Acceptation** : un lot de 1 000 fichiers (bac à sable) est rangé, vérifié puis annulé en un clic ; zéro suppression dans le journal ; la synchro GED voit « déplacé », sans réindexation.

### Étape 11 — Cloche du rangement
Brancher sur `Notification` existant : fichier hors plan, place disque (seuil 80 %), croissance
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
worker (IDLE ou relève périodique réglable), corps chargés à la demande, recherche (plein texte
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
