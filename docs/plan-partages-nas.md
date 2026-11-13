# Plan — Gestion des partages NAS dans la GED

> **Statut** : réflexion, rien n'est codé (13/11/2026). Demande de Thomas : (1) voir ce qui est
> indexé aujourd'hui et le résumer ; (2) prévoir comment récupérer ces informations dans une
> indexation organisée partage par partage.
>
> Relevé fait en lecture seule sur la prod v1.171.0 : comptages SQL uniquement, aucun document lu.

## 1. Ce qui est indexé aujourd'hui

### Les sources

| Source | Type | Périmètre | Synchro auto |
|---|---|---|---|
| NAS-MATO | SMB | **tout le NAS** `192.168.42.200` (aucun partage précisé) | toutes les 60 min |
| Google Drive | cloud | racine du Drive | aucune |

Aucune fréquence particulière n'est réglée par dossier. Les documents portent tous
`source = 'watch'` : cette colonne ne distingue rien.

### Les documents, par partage

**283 394 fiches, 1 025 Go de fichiers décrits, base de 3,7 Go.**

| Partage | Fiches | Volume | Enrichies (IA) | Cataloguées (sans texte) | Avec vecteurs | Copies | Remarque |
|---|---:|---:|---:|---:|---:|---:|---|
| `homes` | 185 041 | 621 Go | 27 729 | 157 023 | 9 398 | 18 946 | 5 comptes ; surtout des images (99 230 jpg, 30 335 png) |
| `home` | 69 892 | 91 Go | 23 888 | 43 184 | 16 539 | 6 494 | **vue du même contenu que `homes`** (voir constat C1) |
| `music` | 23 668 | 289 Go | 23 222 | 342 | 19 530 | 3 697 | 22 984 mp3, presque tous passés par l'IA |
| `photo` | 2 593 | 11 Go | 2 500 | 82 | 2 499 | 0 | |
| `Partage-Nas-Mato` | 1 921 | 13 Go | 295 | 1 345 | 286 | 28 | **193 fiches « absentes »** |
| `Scan` | 25 | 15 Mo | 21 | 0 | 17 | 4 | |
| `Scans_Epson` | 4 | 0,7 Mo | 4 | 0 | 4 | 0 | synchro en échec (C4) |
| `Associations` | 2 | 0,4 Mo | 1 | 1 | 1 | 0 | |
| `Formation` | 1 | 0,1 Mo | 1 | 0 | 1 | 0 | |
| Google Drive | 239 | 204 Mo | 233 | 0 | 35 | 0 | |
| Divers (exemples locaux, 1 fiche Synology) | 8 | — | 8 | 0 | 8 | 0 | restes d'essais |

`homes` par compte : Tom 132 000 fiches (302 Go), tclement 51 505 (316 Go), MLB 1 525 (3 Go),
admin 6, julie 5.

Le partage `media` (films, séries) n'est **pas** indexé : aucune fiche.

### Ce que le relevé apprend

- **C1 — `home` et `homes` se recouvrent.** Sur un Synology, `home` est le dossier personnel du
  compte connecté, et `homes` contient les dossiers de tous les comptes. 15 519 fiches de `home`
  ont la même empreinte **et** le même chemin relatif qu'une fiche de `homes` ; 16 792 fiches de
  `homes` sont déjà marquées « copie » d'une fiche de `home`. Les 54 000 autres fiches de `home`
  n'ont pas (encore) leur jumelle sous `homes`. Le même fichier est donc indexé, synchronisé et
  parfois traité par l'IA sous deux adresses.
- **C2 — Les trois quarts de l'index sont des images sans texte** (201 000 fiches « cataloguées »),
  presque toutes dans `homes` et `home`.
- **C3 — La musique est passée par l'IA** : 23 222 fichiers enrichis et 19 530 avec vecteurs. À
  décider si c'est voulu : c'est du temps de carte graphique et des vecteurs pour des chansons.
- **C4 — 181 synchronisations en échec sur 1 127 en trois jours (16 %).** Deux causes, toujours
  les mêmes :
  - `photo` : cinq **fichiers posés à la racine du partage** sont pris pour des dossiers
    (« Unable to open directory »), 29 échecs chacun ;
  - `Scans_Epson` : le partage ne répond plus (« Unable to connect to shared device »), 36 échecs.

## 2. Comment le code rattache un document à sa source

Lu dans `main` (v1.171.0) :

- **Un document ne connaît pas sa source.** Il n'y a pas de colonne `source_id`. Le lien est son
  adresse : `smb://<hôte>/<partage>/<chemin>`. Le partage est donc déjà inscrit dans chaque fiche.
- **Supprimer une source ne supprime aucun document** (`DELETE /api/sources/{id}` efface la ligne
  de la source, rien d'autre).
- **La synchronisation travaille déjà par (partage, dossier de 1er niveau)** : un job
  `sync_source` par dossier, délimité par le préfixe de l'adresse.
- **Le planificateur déduit ces dossiers de l'index** (`_scopes_indexes`) : il relit l'adresse des
  283 000 fiches à chaque passage et n'en retient que les dossiers de 1er niveau qui contiennent
  déjà un document. Trois conséquences :
  - un **nouveau dossier** créé à la racine d'un partage n'est jamais découvert par la synchro
    automatique ;
  - un **fichier à la racine** d'un partage est traité comme un dossier (cause de C4) ;
  - un partage sans aucune fiche n'existe pas pour Matothèque.
- **Le compte rendu de synchro est rangé par dossier, sans le partage** (`dernier_sync_recap` a
  pour clés `/`, `/MLB`, `/Tom`) : deux dossiers de même nom dans deux partages s'écrasent.
- **Plusieurs fonctions raisonnent par hôte** (`_libelles_sources`, `_scopes_indexes`, le filtre
  de `organize.py`) : deux sources sur le même NAS seraient confondues.

## 3. Cible proposée

### Le principe

Le **NAS reste une source** (une connexion : hôte et compte). On lui ajoute la notion explicite
de **partage suivi** : une ligne par partage, qui porte ce qu'on règle aujourd'hui en bloc.

| Réglage | Aujourd'hui | Cible |
|---|---|---|
| Suivi ou non | implicite (il y a des fiches, ou pas) | une case par partage |
| Fréquence de synchro | une pour tout le NAS | une par partage, dossier par dossier si besoin |
| Compte rendu de synchro | par dossier, sans le partage | par partage, puis par dossier |
| Découverte | dossiers déjà indexés seulement | depuis la racine du partage, fichiers de racine compris |
| Traitement | le même partout | un profil par partage (C2, C3) |
| Panne | noyée dans les échecs | « ce partage ne répond plus », visible |

### Pourquoi pas « une source par partage »

C'était la première réponse donnée à Thomas ; la lecture du code la corrige. Neuf sources sur le
même NAS, ce serait neuf fois le même compte à saisir et à tenir à jour, et surtout le code qui
raisonne par hôte ferait rescanner **tous** les partages par **chaque** source. Il faudrait le
réécrire de toute façon. Une table de partages sous la source donne le même résultat pour
l'utilisateur, avec un seul compte. Rien n'empêche de créer plus tard une seconde source, avec un
autre compte, pour un partage sensible.

## 4. Récupérer l'existant

C'est le point rassurant du relevé : **il n'y a rien à réindexer**.

1. **La liste des partages se déduit de l'index.** Le partage est le 4ᵉ segment de l'adresse de
   chaque fiche. Une requête donne les neuf partages et leurs compteurs (le tableau du § 1).
2. **Rétro-remplissage.** À la création de la table, une ligne par partage trouvé dans l'index,
   marquée « suivi », avec la fréquence actuelle de la source (60 min) et la date de la dernière
   synchro connue, reprise des jobs `sync_source` qui portent déjà le partage.
3. **Les partages jamais indexés** (`media` et les autres) viennent de la liste que le NAS rend
   déjà (`GET /api/sources/{id}/shares`) : affichés « non suivis », sans rien indexer.
4. **Les fiches ne bougent pas.** Mêmes adresses, donc la première synchro par partage doit les
   reconnaître toutes comme « inchangées ». C'est le critère de réussite de la bascule : par
   partage, **zéro nouveau et zéro absent** qui ne s'explique pas par un vrai changement sur le NAS.
5. **Ce qui est attaché à la fiche suit** sans rien faire : texte, fiche IA, vecteurs, versions,
   liens, étiquettes de copie.

### Le cas `home` / `homes`

C'est la seule vraie reprise de données. Proposition : **suivre `homes` et cesser de suivre
`home`**, puis ramener les fiches de `home` sous leur adresse `homes/<compte>/…` :

- les 15 519 fiches en double exact : on garde une fiche, on fusionne ce qui manque à l'autre
  (fiche IA, vecteurs), on retire le doublon **de l'index** — aucun fichier n'est touché ;
- les 54 000 autres : simple réécriture de l'adresse, comme un déplacement (aucun retraitement) ;
- les liens « copie de » qui pointent vers une fiche retirée sont recalculés.

À établir avant : **quel compte se cache derrière `home`** (celui de la source), et vérifier
qu'aucune adresse réécrite n'entre en collision avec une fiche existante.

## 5. Décisions qui reviennent à Thomas

**Tranchées par Thomas le 13/11/2026.**

| Réf | Question | Décision |
|---|---|---|
| P1 | Table de partages sous la source, ou une source par partage ? | **Table de partages.** Thomas veut « plusieurs sources, et plus le NAS en entier » : à l'écran, **une entrée par partage**, et plus d'entrée « tout le NAS ». *Lecture de Claude : la table de partages sous une seule connexion donne ce résultat ; à reprendre s'il fallait des comptes distincts par partage.* |
| P2 | `home` : cesser de le suivre et tout ramener sous `homes` ? | **Oui.** |
| P3 | Quels partages suivre ? | **Ceux déjà indexés** ; `media` non suivi. `Scans_Epson` (il ne répond plus) reste à trancher à l'étape 1. |
| P4 | Musique : continuer à la passer par l'IA ? | **Non**, catalogue seul. **Mais** le module Rangement devra pouvoir **renommer fichiers et dossiers d'après les albums**, avec une recherche par l'IA (voir ci-dessous). |
| P5 | Images : description par l'IA automatique ou à la demande ? | **À la demande.** |
| P6 | Les 193 fiches absentes de `Partage-Nas-Mato` : purger ? | **Les regarder d'abord** (relevé ci-dessous). |
| P7 | Un utilisateur (MLB) doit-il voir les fiches des autres comptes de `homes` ? | Non posée — hors de ce plan ; la table de partages est le bon endroit pour le régler plus tard. |

### P8 — Un compte NAS dédié, `SVR-GED`, pour la lecture (décision de Thomas, 13/11/2026)

Aujourd'hui la source lit le NAS avec le compte personnel **Tom**. Thomas créera un compte
**`SVR-GED`** réservé à la GED, pour la lecture des dossiers. Conséquences à tenir dans le plan :

- **Ordre des opérations.** `home` désigne le dossier personnel du compte connecté. Tant que la
  source est en « Tom », `home` = `homes/Tom` ; une fois en `SVR-GED`, `home` deviendrait le dossier
  (vide) de `SVR-GED`, et la synchro marquerait **69 892 fiches absentes**. La fusion de `home`
  dans `homes/Tom` (étape 5) doit donc être faite **avant** de changer de compte — ou, au minimum,
  `home` doit avoir cessé d'être suivi (étape 4).
- **Ce que `SVR-GED` doit voir.** Lecture sur chaque partage suivi, et sur `homes` **avec** les
  sous-dossiers des comptes à indexer (Tom, tclement, MLB…). Sur un Synology, lire `homes/<compte>`
  avec un autre compte demande un droit explicite : sans lui, ces fiches tomberaient en « absent ».
  Le garde-fou existant (« la source ne renvoie rien alors que l'index contient des documents »)
  bloque le cas d'un dossier entier illisible, pas celui d'un sous-dossier.
- **Ce qui écrit aujourd'hui avec le compte de la source.** La boîte à scans (`scan_service.py`,
  classement des PDF vers `smb://…`), la corbeille (`routers/corbeille.py`) et la réorganisation
  (`routers/organize.py`, coupée depuis le 13/10) utilisent les identifiants de la source. Un compte
  en lecture seule les ferait échouer. À trancher à l'étape 2 : un second compte pour ces écritures,
  ou des droits d'écriture limités aux seuls dossiers concernés (`Scan`, dossier corbeille).
- **Le Rangement** lit le NAS par le montage du LXC (compte `srvplex`, plan rangement D4), pas par
  ce compte : les deux sont indépendants.
- **Bascule sans réindexation.** Changer d'identifiant ne change pas les adresses `smb://…` : les
  fiches restent valables, à condition que `SVR-GED` voie les mêmes fichiers. Vérification avant
  bascule : une synchro « à blanc » de chaque partage avec le nouveau compte, sur une source de
  test, doit rendre zéro absent.

### Relevé complémentaire du 13/11 — `home` est `homes/Tom`

Le compte de la source est « Tom ». **69 891 des 69 892 fiches de `home` ont le même chemin relatif
sous `homes/Tom`** : ce n'est pas un recouvrement partiel (constat C1), c'est le même dossier
indexé deux fois. Seules 15 519 paires portent la même empreinte, parce que les autres ont été
traitées d'un côté et seulement cataloguées de l'autre ; pour 11 711 fichiers, c'est la fiche de
`home` qui a le texte ou la fiche IA.

La reprise (§ 4 et étape 5) est donc une **fusion de paires**, pas une réécriture d'adresses : on
garde la fiche de `homes/Tom`, on y reporte ce que celle de `home` a de plus (texte, fiche IA,
vecteurs, versions, liens, liens de copie), puis on retire la fiche de `home` de l'index.
**L'index perd environ 69 900 fiches, un quart, sans perdre un document** — et non 15 500 comme
écrit plus bas avant ce relevé.

### Ce que P4 demande au catalogue de la musique

« Catalogue seul » ne veut pas dire « rien » : pour renommer plus tard d'après les albums, la fiche
d'un morceau doit garder ses **étiquettes** (titre, artiste, album, année, numéro de piste), que
Tika lit sans IA. Le renommage lui-même appartient au **Rangement**
(`docs/plan-integration-rangement-mails.md`) : l'IA propose le bon album quand les étiquettes
manquent ou se contredisent, un humain valide, et le déplacement passe par les lots annulables. À
inscrire dans ce plan-là à son étape 8 (conception du plan de classement). Les 23 222 morceaux
déjà enrichis gardent leur fiche : rien n'est effacé.

### P6 — ce que montrent les 193 fiches absentes

- **191 fiches** sont dans un seul dossier, `[MaTo]/Dossier mariage`, et ont **toutes été marquées
  absentes le 12/11/2026**. Trois seulement ont leur contenu présent ailleurs dans l'index.
- **2 fiches** dans `[MaTo]/MLB`, absentes depuis le 12/10/2026.

Un dossier entier qui disparaît en un jour, sans réapparaître ailleurs, ressemble à un dossier
renommé, déplacé hors des partages suivis, ou supprimé. **Ne rien purger** tant que Thomas n'a pas
dit ce qu'il est advenu de ce dossier le 12/11 : s'il a été renommé, ses fiches (texte, fiche IA)
sont à rattacher à la nouvelle adresse, pas à effacer.

## 6. Étapes

### Étape 1 — Relevé contradictoire : l'index face au NAS réel

Comparer, partage par partage, ce que l'index contient et ce que le NAS expose : partages visibles
par le compte de la source, dossiers de 1er niveau jamais indexés, fichiers posés à la racine,
compte derrière `home`, détail des 193 absents et des 54 000 fiches de `home` sans jumelle.
Lecture seule, comptages et noms de dossiers seulement, aucun document ouvert.
- **Acceptation** : un tableau par partage (indexé / présent / écart) ajouté à ce plan ; le compte
  de `home` est identifié ; P2, P3 et P6 peuvent être tranchées sur des chiffres.

### Étape 2 — Conception du partage suivi

Arrêter le modèle : table des partages sous la source, ses réglages (suivi, fréquence, profil de
traitement), ce qui devient de `sync_dossiers` et de `dernier_sync_recap`, et la liste des
fonctions qui raisonnent par hôte à corriger. Dire comment l'inventaire du Rangement
(`inv_emplacements`, étape 4 de son plan) partage la même liste de partages.
- **Acceptation** : une décision d'architecture écrite dans ce plan, avec ce qu'elle écarte ;
  chaque réglage actuel a une place dans le nouveau modèle ; P1 tranchée.

### Étape 3 — Schéma et rétro-remplissage depuis l'index

Créer la table des partages par les migrations à chaud de `database.py` et la remplir depuis les
adresses des documents et les jobs `sync_source` existants. Les partages non indexés viennent de
la liste du NAS, marqués non suivis.
- **Acceptation** : sur une copie de la base de prod, la table contient les neuf partages avec les
  compteurs du § 1 ; un second démarrage ne change rien ; aucune fiche n'est modifiée.

### Étape 4 — Synchronisation par partage

Le planificateur part de la table des partages et de la racine de chaque partage, plus de
l'index : il découvre les nouveaux dossiers, traite les fichiers de racine comme des fichiers, et
range le compte rendu par partage. Un partage injoignable est signalé une fois, pas à chaque
passage. Le garde-fou « la source ne renvoie rien alors que l'index contient des documents » est
conservé par dossier et ajouté au niveau du partage.
- **Acceptation** : sur une copie de prod, la première synchro par partage rend zéro nouveau et
  zéro absent inexpliqués ; un dossier créé à la racine est découvert ; les cinq fichiers de
  racine de `photo` ne font plus échouer de job ; un partage éteint ne marque aucune fiche absente.

### Étape 5 — Reprise de `home` vers `homes`

Après P2 : réécrire les adresses de `home` sous `homes/<compte>`, fusionner les doublons exacts,
recalculer les liens de copie, puis cesser de suivre `home`. D'abord en simulation qui ne rend que
des compteurs, ensuite pour de bon, par lots annulables.
- **Acceptation** : la simulation annonce le nombre de fiches réécrites, fusionnées et en
  collision ; après application, plus aucune fiche sous `home`, aucune fiche IA ni vecteur perdu,
  aucun fichier touché sur le NAS ; le nombre de fiches baisse d'environ 69 900 (fusion de paires,
  voir le relevé complémentaire du § 5).
- **Hors périmètre** : aucun déplacement ni suppression de fichier sur le NAS.

### Étape 6 — Paramètres › Sources : un bloc par partage

Afficher sous chaque source la liste de ses partages : suivi ou non, fiches, volume, dernière
synchro et son résultat, fréquence, boutons Synchroniser et Arrêter de suivre. Un partage en panne
se voit d'un coup d'œil.
- **Acceptation** : les neuf partages apparaissent avec les compteurs du relevé ; cesser de suivre
  un partage arrête ses synchros sans retirer ses fiches ; l'écran marche par les deux routes
  d'accès (https et http).

### Étape 7 — Profil de traitement par partage

Après P4 et P5 : un profil par partage (tout traiter, cataloguer seulement, sans IA). Le pipeline
le lit avant de mettre en file les tâches d'IA.
- **Acceptation** : un nouveau fichier d'un partage « catalogue seul » ne crée aucune tâche d'IA ;
  changer le profil ne retraite rien de ce qui est déjà indexé.

### Étape 8 — Vérification sur copie de prod, bascule et documentation

Rejouer les étapes 3 à 7 sur une copie de la base de prod, comparer les compteurs par partage avant
et après, puis livrer. Mettre à jour le guide utilisateur, `CLAUDE.md` et la ROADMAP.
- **Acceptation** : compteurs par partage identiques avant et après, hors `home` ; taux d'échec des
  synchros mesuré sur 24 h et comparé aux 16 % d'aujourd'hui ; documentation à jour.

## 7. Risques

- **Marquer des fiches « absentes » en masse** pendant la bascule. Parade : le garde-fou existant,
  étendu au partage, et le critère « zéro absent inexpliqué » sur copie avant toute livraison.
- **La reprise de `home`** est la seule étape qui modifie des fiches en nombre. Parade : simulation
  d'abord, lots annulables, sauvegarde de la base juste avant.
- **Deux chantiers sur les mêmes fichiers** : le Rangement va inventorier le NAS et, plus tard,
  déplacer des fichiers. Les deux doivent partager la même liste de partages (étape 2).
- **Sessions concurrentes** dans ce dépôt : une branche par étape, et prévenir avant de toucher à
  `job_worker.py` ou `sync_service.py`, déjà modifiés par le chantier des lots IA.
