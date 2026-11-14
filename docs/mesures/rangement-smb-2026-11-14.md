# Mesure — parcours et lecture du NAS par SMB, contre le montage (14/11/2026)

> Étape 1 de [plan-rangement-sources-smb.md](../plan-rangement-sources-smb.md). S1 étant tranché
> (tout en SMB), la mesure **dimensionne** les réglages, elle ne décide plus.

## Protocole

- **Où** : dans le conteneur `worker` de prod (LXC 102), seul endroit qui voit à la fois le
  montage CIFS (`/mnt/rangement/*`, compte `svc-rangement`) et la Source SMB `svc-rangement`.
  Lecture seule ; aucun nom de fichier affiché, seulement des compteurs.
- **SMB** : pysmb (`smb_service._connect`), **une seule connexion** pour tout le parcours,
  `listPath` dossier par dossier (taille + date de modification comprises) ;
  `retrieveFileFromOffset` pour la lecture.
- **Montage** : `os.scandir` + `stat` sur le montage CIFS du PVE prêté au LXC ; `open/seek/read`.
- **Quand** : 14/11/2026, 14 h 51 – 15 h 10, charge LXC ≈ 1.
- Scripts jetables (hors dépôt) : parcours en pile, empreinte partielle = 64 Kio début + 64 Kio fin.

## Parcours (inventaire)

| Arbre | Mode | Fichiers | Dossiers | Refus | Durée | Fichiers/s |
|---|---|---:|---:|---:|---:|---:|
| `homes/Tom` (1 019 Go) | SMB (1ᵉʳ passage) | 273 610 | 17 421 | 1 | 63,0 s | 4 340 |
| | montage | 273 610 | 17 421 | 1 | 57,4 s | 4 766 |
| | SMB (2ᵉ passage) | 273 610 | 17 421 | 1 | 59,3 s | 4 614 |
| `media` entier (5 897 Go) | SMB | 4 846 | 572 | 0 | 2,6 s | 1 893 |
| | montage | 4 846 | 572 | 0 | 4,5 s | 1 068 |

- **Mêmes nombres, mêmes volumes** par les deux chemins. Le refus unique est
  `homes/Tom/Rapport-PDF`, fermé au compte `svc-rangement` (droit DSM à donner).
- Connexion SMB : 0,1 à 0,2 s. Dossier le plus lent : < 1 s dans les deux modes.
- Pour comparaison, le **scan réel** du Rangement sur `homes/Tom` (même arbre, montage) a pris
  **4 min 25 s** : le parcours n'en fait qu'une minute, le reste est l'écriture en base. Passer en
  SMB ne change donc pas la durée d'un scan.
- **`media` n'est pas un problème de parcours** : 15 To annoncés (5,9 To lus par ce compte) pour
  moins de 5 000 fichiers — des films. La crainte de la décision n° 5 (« parcours SMB trop lent
  sur 15 To ») confondait volume et nombre de fichiers.

## Lecture (copies sur disque)

300 fichiers de `media` de plus de 1 Mo, puis 2 Go lus d'un seul tenant dans le plus gros.

| Passage | Mode | Empreintes partielles | Lecture continue |
|---|---|---:|---:|
| 1 (NAS froid) | SMB | 30 fichiers/s | 45,6 Mo/s |
| | montage | 14,8 fichiers/s | 112,3 Mo/s |
| 2 (NAS chaud) | SMB | 118 fichiers/s | 42,0 Mo/s |
| | montage | 15,3 fichiers/s | 112,6 Mo/s |

- **Empreintes partielles : SMB 2 à 8 fois plus rapide** (une connexion gardée ouverte ; le
  montage paie une ouverture CIFS complète par fichier).
- **Lecture continue : SMB plafonne à ~42-46 Mo/s**, cache du NAS chaud ou froid — c'est pysmb
  (une requête à la fois), pas le NAS. Le montage tient le débit du lien (~112 Mo/s, 1 Gb/s).

## Réglages proposés

| Réglage | Aujourd'hui | Proposé en SMB | Pourquoi |
|---|---|---|---|
| Fenêtre de la tournée de nuit | inchangée | inchangée | Parcours `homes/Tom` + `media` ≈ 1 min ; le scan reste dominé par la base. |
| `inventaire_pause_ms` | 0 | 0 | Aucun dossier lent ; rien à ménager côté NAS au parcours. |
| `inventaire_copies_limite_nuit_go` | 200 Go | **200 Go** (garder) | En SMB : 200 Go ≈ **1 h 20** de lecture continue (contre ≈ 30 min par le montage). Tient dans la nuit ; à baisser seulement si la nuit est déjà chargée. |
| Découpage de `media` sur plusieurs nuits | — | **inutile** | 2,6 s de parcours. |

**À reprendre à l'étape 5** : si 42 Mo/s pèse un jour (empreintes complètes de gros films), lire
par plusieurs requêtes en vol ou en morceaux plus gros ; à mesurer alors, pas avant.

## Constats annexes

- L'emplacement « Home-TOM » a été déclaré avec la racine **`/mnt/rangement`** (le préremplissage
  de la v1.178.1, non complété) et non `/mnt/rangement/homes-Tom`. Le scan est juste (`media`,
  emplacement imbriqué, est exclu), mais son plan de classement s'appellerait « rangement » et
  serait décalé d'un niveau. Aucun plan ni aucune proposition n'en dépend (vérifié le 14/11). Il
  sera redéclaré en SMB aux étapes 7-8 ; d'ici là, ne pas lui bâtir de plan.

## Étape 4 — scan complet par SMB contre le montage (14/11/2026, soir)

Le code de l'étape 4 (`SourceSmb`) injecté dans le worker de prod, les deux scans écrits dans le dépôt
EN MÉMOIRE des tests (aucune écriture en base), mêmes exclusions que la prod, arbre `homes/Tom`.

| Mode | Statut | Fichiers | Dossiers | Volume | Refus | Durée |
|---|---|---:|---:|---:|---:|---:|
| montage | terminé | 272 375 | 17 337 | 452,1 Go | 1 | 395 à 460 s |
| SMB | terminé | 272 375 | 17 337 | 452,1 Go | 1 | 491 à 493 s |

- Le refus est `Tom/Rapport-PDF` dans les deux cas : le scan le compte et **continue** (il n'échoue plus).
- **Même inventaire, à 6 noms près** (4 fichiers, 2 dossiers vides) : des noms qui contiennent des
  caractères interdits sous Windows (retour à la ligne, `?`, 0x1F). Le Synology les stocke sous des codes
  de la zone privée Unicode (U+F00A, U+F025, U+F01F) ; le client CIFS de Linux les retraduit en vrais
  caractères, SMB les rend tels quels. **On garde la forme SMB** : c'est elle qu'il faudra employer pour
  agir sur ces fichiers par SMB (étape 6). Effet : au passage d'un emplacement du montage au SMB
  (étape 8), ces éléments apparaîtront une fois comme disparus puis ajoutés. Dates : aucun écart.
- Le scan SMB est 10 à 25 % plus long (le passage par la session) : sans effet sur la tournée de nuit.

## Étape 5 — passe des copies par SMB contre le montage (14/11/2026, soir)

Code de l'étape 5 dans le worker de prod, dépôts EN MÉMOIRE (aucune écriture en base), partage `media`
(4 844 fichiers), réglages de la prod (taille minimale 1 Mo), limite de lecture 6 Go par passe.

| Mode | Passe | Partielles | Complètes | Lu | Durée | Débit |
|---|---|---:|---:|---:|---:|---:|
| montage | limite | 158 | 2 | 5,99 Go | 108 s | 56,7 Mo/s |
| SMB | limite | 158 | 2 | 5,99 Go | 224 s | 27,4 Mo/s |

- **Mêmes empreintes au bit près** : 158 partielles et 2 complètes comparées, 0 différence ; mêmes groupes.
- **Débit SMB : 27 Mo/s** dans la passe (42 Mo/s en lecture brute à l'étape 1 : s'y ajoutent le calcul
  de l'empreinte et les relectures de taille/date). La limite de 200 Go par nuit prend donc **≈ 2 h** en
  SMB. Acceptable ; à reprendre (plusieurs lectures en vol) si la nuit devient trop courte.

