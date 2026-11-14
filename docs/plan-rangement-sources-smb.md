# Plan — Brancher le Rangement sur les Sources SMB existantes

> **Statut** : plan écrit le 14/11/2026 ; étape 1 (mesure) faite le jour même ; étapes 2 à 4 codées (session, emplacement SMB, scan SMB) ; prochaine : 5 (copies par SMB). Demande de Thomas : « idéalement, brancher
> le Rangement à ce qui existe » — déclarer depuis l'interface les dossiers à inventorier et ranger,
> sans figer un montage par partage dans le PVE et le compose.
> Lié à : [plan-integration-rangement-mails.md](plan-integration-rangement-mails.md) (décision n° 5),
> [plan-partages-nas.md](plan-partages-nas.md) (une entrée par partage sous la source).

## 1. Point de départ

**Aujourd'hui, deux façons de voir le NAS cohabitent :**

| | GED (*Paramètres › Sources NAS/SMB*) | Rangement (*Rangement › Carte*) |
|---|---|---|
| Accès | SMB direct depuis l'application (pysmb) | Montage CIFS sur l'hôte PVE, prêté au LXC, puis volume du worker |
| Déclarer | Tout depuis l'interface : serveur, compte (secret chiffré), partages, dossiers | Un dossier **sous un montage existant** ; un nouveau partage = fstab PVE + `mp` LXC + compose |
| Compte | Celui de la source (`NAS-MATO` = Tom) | `svc-rangement` (fichier de crédits sur le PVE) |

La décision n° 5 du plan rangement a choisi le montage : parcours par `os.scandir`, déplacement = renommage,
et « parcours du NAS par SMB, trop lent sur 15 To » (**jamais mesuré**).

**Ce qui rend le branchement possible** (relevé du code, 14/11/2026) :
- le scan passe déjà par un protocole `Source` (`verifier`, `lister` un dossier à la fois) — deux
  implémentations : `SourceDisque` et `SourceEnvoi` (agent de poste). Un `SourceSmb` s'y branche ;
- `smb_service` sait déjà lister, renommer (`move_file`, même partage), créer un dossier, tester.

**Ce qui manque côté SMB** : une connexion qui DURE pendant un scan (aujourd'hui une connexion par
appel), la date de modification au parcours (`browse` ne la rend pas), la lecture par morceaux
(`retrieveFileFromOffset`, pour les empreintes des copies), et la place libre d'un partage.

## 2. Décisions à trancher (Thomas)

| # | Question | Proposition |
|---|---|---|
| S1 | `media` (15 To) passe-t-il aussi en SMB ? | ✅ **Tranché par Thomas le 14/11/2026 : TOUS les emplacements du NAS en SMB, `media` compris.** Le montage du Rangement disparaît à terme ; le mode « disque monté » ne reste que pour un disque local au serveur. Le montage `srvplex` de Plex (`/mnt/media`, `mp0`) n'est pas concerné. |
| S2 | Quel compte pour ranger ? | ✅ **Tranché le 14/11/2026 : une Source dédiée `svc-rangement`**, créée par Thomas dans l'interface (même hôte que la source de la GED, compte de Tom). ⚠️ Deux sources sur un même hôte : la GED retrouvait la source par l'hôte SANS ordre et pouvait lire avec le mauvais compte — corrigé en v1.178.2 (la plus ancienne gagne). L'étape 3 doit marquer la source du Rangement pour qu'elle ne serve JAMAIS à la GED (champ d'usage), au lieu de compter sur l'ancienneté. |
| S3 | Place disque d'un partage SMB | pysmb ne la donne pas : l'alerte « place disque » reste réservée aux emplacements montés, sauf si l'étape 2 trouve une requête fiable. |
| S4 | Ranger d'un partage à l'autre (`homes/Tom` → `fam-documents/Thomas`, C10) | **Hors de ce plan** : un renommage SMB ne traverse pas les partages ; ce serait une copie + vérification + suppression, à concevoir à part. |

## 3. Étapes

### Étape 1 — Mesurer le parcours SMB (dimensionner, plus choisir)
> ✅ **Faite le 14/11/2026** — [docs/mesures/rangement-smb-2026-11-14.md](mesures/rangement-smb-2026-11-14.md). Parcours SMB ≈ montage (`homes/Tom` : 273 610 fichiers en ~60 s ; `media` : 4 846 fichiers en 2,6 s), empreintes partielles plus rapides en SMB, lecture continue plafonnée à ~42 Mo/s par pysmb (montage ~112). Réglages actuels conservés (limite copies 200 Go/nuit ≈ 1 h 20 en SMB) ; pas de découpage de `media`.

S1 est tranché (tout en SMB) : la mesure ne décide plus, elle **dimensionne** — fenêtre de nuit,
pause entre dossiers, limite de lecture des copies. Banc hors production : parcourir `homes/Tom` puis un
sous-arbre de `media` (≥ 50 000 fichiers) par `listPath` sur UNE connexion, dossier par dossier, comparé
à `os.scandir` sur le montage. Relevé dans `docs/mesures/rangement-smb-<date>.md` : fichiers/s, durée
projetée pour 15 To, débit de lecture (copies), charge NAS.
- **Acceptation** : chiffres SMB et montage sur le même arbre ; réglages proposés (fenêtre, pause, limite)
  pour que la tournée de `media` tienne dans la nuit, ou qu'elle se découpe sur plusieurs nuits.
- **Hors périmètre** : aucun changement de code applicatif.

### Étape 2 — Une session SMB qui dure, et `chemins.py`
> ✅ **Codée le 14/11/2026** (branche `feat/rangement-smb-session`) : `services/smb_session.py` et `services/smb_chemins.py` — placé dans `services/` et non `services/rangement/`, car la GED (lecture, corbeille, scans) s'en sert aussi. Les trois anciens parseurs y passent, cas limites figés par `tests/test_smb_chemins.py`. Essai en lecture seule contre le vrai NAS : `homes/Tom` parcouru sur UNE connexion (273 612 fichiers, 83 s — le passage par le thread de la session coûte ~1 ms par dossier), lecture début/fin et `stat` justes sur `media`. Aucun appelant ne l'utilise encore (étape 4).

`services/smb_session.py` : une connexion ouverte pour toute une tâche (thread dédié), avec
`lister(dossier)` → nom, dossier ?, taille, date ; `stat`, `lire(chemin, depuis, longueur)`,
`renommer`, `creer_dossier`, `existe`. `services/rangement/chemins.py` : un seul aller-retour
`smb://hote/partage/rel` ↔ (hôte, partage, chemin relatif), qui remplace les trois `parse_smb` copiés.
- **Acceptation** : tests avec un faux serveur (pas de réseau) ; une session ne se reconnecte pas à
  chaque dossier ; les trois anciens parseurs passent par `chemins.py` sans changement de résultat.

### Étape 3 — Un emplacement « SMB » déclaré depuis l'interface
> ✅ **Codée le 14/11/2026** : colonnes `source_id` (FK `sources`, `ON DELETE RESTRICT`), `partage`, `sous_dossier` ajoutées SEULEMENT si absentes (pas de verrou de table à chaque démarrage) ; CHECK de `source` étendu à `smb`. `sources.usage` (`ged` | `rangement`) : la GED filtre ses six recherches de source par hôte, la synchro planifiée et les dossiers surveillés ; indexer / synchroniser / réindexer une source du Rangement → 409 ; repasser une source utilisée par un emplacement en GED, ou la supprimer → 409. API `POST /api/inventaire/emplacements/smb` (dossier vérifié par SMB). Scan d'un emplacement SMB refusé (`scan_smb_a_venir`) jusqu'à l'étape 4. Écran : case « Réservée au Rangement » et badge dans *Sources* ; « NAS (SMB) » sur la Carte (la déclaration à l'écran = étape 7).

`inv_emplacements` : `source = 'smb'`, `source_id` (la Source), `partage`, `sous_dossier` ; racine
canonique `smb://hote/partage/sous_dossier`. `plan.partage_de` lit le champ `partage` au lieu du dernier
segment de la racine. API : déclarer à partir d'une Source + partage + dossier (le navigateur des
Sources existe déjà). Un emplacement monté reste possible (mode actuel).
- **Acceptation** : un emplacement SMB se déclare sans toucher au PVE ni au compose ; le secret de la
  Source n'apparaît dans aucune réponse ni journal ; les emplacements montés existants ne changent pas.

### Étape 4 — Scanner par SMB (`SourceSmb`)
> ✅ **Codée le 14/11/2026** (`services/rangement/source_smb.py`) : session relue en base au scan, dossier refusé = compté et sauté (le scan continue), coupure = scan en échec sans « disparu », emplacement SMB imbriqué sauté, scan manuel et tournée de nuit. **Acceptation sur le vrai NAS** : `homes/Tom` scanné par SMB et par le montage, même inventaire (272 375 fichiers, 17 337 dossiers, 452,1 Go) à 6 noms près — caractères interdits sous Windows que le client CIFS retraduit (détail : docs/mesures/rangement-smb-2026-11-14.md).

`SourceSmb(session, partage, sous_dossier, exclusions)` implémente `verifier`/`lister` ; exclusions
exprimées en chemins relatifs au partage ; tournée de nuit et scan manuel l'utilisent pour un
emplacement SMB. Un partage injoignable ne marque RIEN disparu (comme un disque absent aujourd'hui).
- **Acceptation** : même inventaire (noms, tailles, dates) qu'un scan par montage sur le même arbre de
  test ; NAS coupé en cours de scan → scan en échec, aucun « disparu ».

### Étape 5 — Copies sur disque par SMB
> ✅ **Codée le 14/11/2026** (`services/rangement/copies_smb.py`) : une session par emplacement SMB pour toute la passe, même formule d'empreinte que le disque et l'agent (`copies.hacher_partielle`), taille et date relues avant ET après la lecture, fichier refusé = compté, coupure = emplacement sauté jusqu'à la fin de la passe (une seule tentative de connexion). Les chemins exclus s'écrivent aussi en `smb://…` (défaut latent de l'étape 4 corrigé). **Acceptation sur le vrai NAS** : `media`, 6 Go lus par le montage puis par SMB — mêmes 158 empreintes partielles et 2 complètes, au bit près ; SMB à 27 Mo/s contre 57 (détail : docs/mesures/rangement-smb-2026-11-14.md).

Les empreintes partielles (64 Kio début + fin) et complètes lisent par `lire(chemin, depuis, longueur)`
dans la même session ; la limite de lecture par nuit compte les octets SMB.
- **Acceptation** : mêmes groupes de copies qu'en local sur un jeu de test ; un fichier modifié pendant
  la lecture est écarté comme aujourd'hui.

### Étape 6 — Ranger et annuler par SMB
`deplacements` : renommage SMB dans le même partage, création des dossiers, nom libre (`nom_(2)`),
journal `reorg_moves` en `smb://` ; annulation par le chemin inverse. Refus si la Source n'a pas le
droit d'écrire (message clair, comme « lecture seule » aujourd'hui).
- **Acceptation** : un lot rangé puis annulé sur un partage de test laisse l'arbre identique ; rien n'est
  jamais supprimé ; un lot vers un autre partage est refusé.

### Étape 7 — Écran : déclarer depuis une Source
*Rangement › Carte › Déclarer* propose « Disque monté » ou « Source NAS » : choisir la Source, le
partage, puis le dossier (réutilise le navigateur de *Sources*). Plus de chemin à taper pour le SMB.
- **Acceptation** : déclarer `homes/Tom` en trois clics, sans chemin saisi ; l'emplacement apparaît sur
  la Carte et se scanne.

### Étape 8 — Bascule de tous les emplacements et ménage
Redéclarer en SMB `homes/Tom`, puis `media` et `NAS 2 (nas-media)` ; comparer chacun à son dernier scan
par montage (le plan de classement, les propositions et le journal suivent l'emplacement). Puis retirer
`mp1` et `mp2` du LXC, les lignes fstab du PVE (`/mnt/rangement/*`), les volumes et `group_add` du
worker. Documenter (aide du Rangement, CLAUDE.md, ce plan).
**Avant** la bascule : réécrire en `smb://hôte/partage/…` les chemins exclus du réglage
`inventaire_pbs_chemins` (datastore PBS… ; vide en prod au 14/11/2026, à revérifier) — un chemin du serveur (`/mnt/…`) ne vaut PAS pour un
emplacement SMB (étape 5) : sans cette réécriture, le scan SMB parcourrait le datastore.
- **Acceptation** : même inventaire avant/après pour chaque emplacement ; plus aucun montage du Rangement
  dans le PVE ni le compose ; Plex (`/mnt/media`, `mp0`) intact.

## 4. Hors périmètre
- Ranger d'un partage à l'autre (S4).
- La refonte des Sources de la GED en « une entrée par partage » ([plan-partages-nas.md](plan-partages-nas.md)) :
  ce plan s'appuie sur la Source telle qu'elle est, et suivra cette refonte quand elle viendra.
