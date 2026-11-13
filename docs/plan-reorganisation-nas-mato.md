# Plan — Réorganisation du NAS-MATO (partages, comptes, groupes, homes)

> **Statut** : proposition, rien n'est appliqué. Relevé fait le 13/11/2026 en lecture seule
> (annexe A, 1 339 lignes) sur DSM **7.4.1**, volume Btrfs de 21 To **rempli à 82 %**.
> Point de vue : architecture et administration système. Le pendant côté GED est
> `docs/plan-partages-nas.md` (décisions P1 à P8) : les deux avancent ensemble, voir le § 8.
>
> **Reste à relever** (annexe B) : volumes par partage et par home, instantanés, détail des
> 17 tâches planifiées, tâches Hyper Backup, chemins du NAS utilisés par les piles Docker.

---

## 1. Ce que montre le relevé

### 1.1 Comptes (14)

| Compte | Admin | Shell SSH | Rôle réel | Constat |
|---|---|---|---|---|
| `Tom` | non | non | Thomas, usage perso quotidien ; source de la GED | **ACE explicite en écriture à la racine de `homes`** → lit et écrit dans **tous** les homes |
| `tclement` | **oui** | **oui** | Thomas, compte pro (mail Agesti) + administration | 316 Go dans son home (`0-Trier-hdd-1TB`) ; seul membre de `matotheque-admin` |
| `MLB` | non | non | personne | membre de `matotheque-utilisateurs` → écriture sur `Applications`, `Partage-Geco`, `media`, `Scan`, `Formation` |
| `admin` | oui | oui | défaut DSM | **désactivé** (expiré) ✅, mais encore cité dans 4 ACL |
| `guest` | non | non | défaut DSM | **désactivé** ✅ |
| `netsight` | **oui** | **oui** | supervision NetSight | refusé sur tous les partages (bien) **sauf** `ha-backups` en écriture ; **propriétaire du home `julie`** (§ 1.4) |
| `ServiceHA` | **oui** | **oui** | intégration DSM de Home Assistant | administrateur avec shell pour de la supervision |
| `HA` | non | non | Home Assistant → `HA-Data` | |
| `srv-ha-reva` | non | non | sauvegardes HA → `ha-backups` | |
| `srvbck` | non | non | sauvegardes → `Bkp`, `TimeMachine` | |
| `proxmoxback` | non | non | Proxmox → `Bkp` (lecture) | **écriture sur `Partage-Geco`** : rien ne la justifie |
| `srvplex` | non | non | LXC → `media` | lecture seule côté NAS (le montage du LXC est déclaré `rw`, mais le NAS refuse l'écriture) |
| `geco-depot` | non | non | dépôt dans `Partage-Geco` | **contrôle total, droit de modifier les ACL compris** |
| `licitis` | non | non | application qui dépose des rapports PDF (transcriptions) → `Rapport-PDF` | |

Il n'y a **pas de compte `julie`**, ni `greg`, `mrobin`, `Pape`, `scan`, `SrvDocker` : ce sont des
homes orphelins (§ 1.4). Aucun compte n'a de description (« Fullname » vide partout).

### 1.2 Groupes (8)

| Groupe | Membres | Usage constaté | Problème |
|---|---|---|---|
| `administrators` | `admin`, `tclement`, `ServiceHA`, `netsight` | administration | **trois comptes sur quatre sont des services ou un compte désactivé** |
| `photo` | `MLB`, `Tom` | sert de groupe « famille » : écriture sur `media` et `Partage-Nas-Mato` | nom d'application utilisé comme groupe de droits ; **n'a même pas accès au partage `photo`** |
| `matotheque-utilisateurs` | `MLB` | écriture sur `Applications`, `Formation`, `media`, `Partage-Geco`, `Scan` | **groupe d'application détourné en groupe de droits fichiers** |
| `matotheque-admin` | `tclement` | (aucun partage) | correct |
| `Drive` | `MLB`, `Tom` | accès Synology Drive | correct |
| `mail-contact-calendar-note` | `MLB`, `Tom` | accès aux applis | correct |
| `http`, `users` | système | | |

**Le défaut de fond** : les groupes servent à la fois à ouvrir une **application** et à donner
des **droits sur des fichiers**. Ajouter MLB à Matothèque lui a donné, sans que personne le
décide, l'écriture sur la logithèque, le partage pro et les médias.

### 1.3 Partages et droits

Les droits passent par les **ACL Windows** (« Skip smb perm = yes ») et sont donnés surtout à
des **personnes** (`Tom` est cité nommément dans 13 partages). Aucun partage n'a de description.

| Partage | Qui y a accès (hors `administrators`) | Constat |
|---|---|---|
| `homes` | `Tom` **écriture sur tout** ; chaque propriétaire sur son dossier | vie privée de MLB inexistante ; c'est aussi ce qui permet à la GED de lire tous les homes |
| `photo` | `Tom` seul | **MLB n'a pas accès à la photothèque partagée** → chacun garde ses photos dans son home |
| `Partage-Nas-Mato` | `Tom`, `MLB`, groupe `photo` | documents familiaux : `[Famille-CLEMENT]`, `[Famille-Berthommé]`, `[MaTo]`, `[Sophie]`, `[CHNITO]`, `[GED]`… |
| `Partage-Geco` | `geco-depot` (total), `Tom`, `proxmoxback`, `matotheque-utilisateurs` (= MLB) | **partage Hybrid Share (C2, 500 Go)** : le contenu vit dans le cloud Synology ; mélange pro (plans, MikroTik) et jeux (Valheim) |
| `Rapport-PDF` | `Tom`, `licitis`, `tclement`, `admin` | sortie de Matothèque (`docflow/`) et de licitis ; noms de fichiers mal formés (`…rapport.pdf<uuid>.pdf`) |
| `Scan` | `Tom`, `admin`, `matotheque-utilisateurs` | pièces sensibles à la racine (CNI, acte, CERFA, échographie) |
| `Associations` | `Tom` + **`everyone` en lecture** | tout compte, service compris, lit ce partage |
| `docker` | **`everyone` en lecture (ACE répétée 6 fois)** | 🔴 **tout compte du NAS lit les piles Docker, donc leurs `.env` et leurs secrets** |
| `Applications` | `Tom`, `matotheque-utilisateurs` (= MLB) | logithèque et fourre-tout (installeurs, pilotes, `A trier`, `tmp`, `Jeux`…) |
| `Formation` | `Tom`, `matotheque-utilisateurs` | 1 dossier (`fiches-memo`) |
| `media` | `Tom`, groupe `photo`, `matotheque-utilisateurs`, `srvplex` (lecture) | contient **`nas-media`, montage CIFS d'un autre NAS** (`192.168.42.201\Multimedia`) en `0777` |
| `music` | `Tom` seul | la GED la lit avec le compte `Tom` |
| `Bkp` | `srvbck`, `proxmoxback` (lecture) | sauvegardes en vrac : infra (Proxmox, GLPI, VPS), perso (`MLB`, `tc`, Outlook), anciens disques (`2024-09-22`) |
| `TimeMachine` | `srvbck`, `Tom` | |
| `HA-Data` | `HA`, groupe propriétaire en écriture | |
| `ha-backups` | `srv-ha-reva`, **`netsight` en écriture** | NetSight n'a besoin que de lire (contrôle de fraîcheur des sauvegardes) |
| `script` | administrateurs seuls | 2 scripts |
| `surveillance` | `Tom`, `admin`, Surveillance Station ; **`netsight` refusé** | mode Linux, pas d'ACL |
| `ActiveBackupforBusiness`, `MailPlus`, `PlexMediaServer` | leur service | `admin` encore cité sur ABB |

**Corbeille désactivée** sur tous les partages de données (activée seulement sur `ha-backups`,
`Rapport-PDF`, `TimeMachine`). Des dossiers `#recycle` existent : elle l'a été autrefois.

### 1.4 Homes orphelins et propriétaires croisés

Les dossiers créés le **22/10/2025** (une migration ou une restauration) appartiennent à des
identifiants numériques **réattribués depuis** à d'autres comptes :

| Dossier | Propriétaire affiché | Compte existe ? | Contenu |
|---|---|---|---|
| `homes/julie` | **`netsight`** | non | `Photos` |
| `homes/Pape` | uid 1034 (aucun compte) | non | `Photos` |
| `homes/greg` | `geco-depot` | non | vide |
| `homes/mrobin` | `proxmoxback` | non | vide |
| `homes/HA` | `licitis` | oui (`HA`), mais n'en est pas propriétaire | vide |
| `homes/srvbck` | `HA` | oui, mais n'en est pas propriétaire | vide |
| `homes/SrvDocker` | `srvbck` | non | vide |
| `homes/scan` | `Tom` | non | vide |

Le propriétaire d'un dossier a le **contrôle total** (ACE `owner::` de `homes`) : **le compte
`netsight`, administrateur avec shell, est propriétaire des photos de julie**, et un compte de
sauvegarde est propriétaire du home d'un autre service. Rien de grave n'est arrivé, mais c'est
exactement le genre de droit que personne n'a décidé.

### 1.5 Ce que contiennent les homes

| Home | Contenu | Lecture |
|---|---|---|
| `Tom` | `[01.Agesti]` (**pro**), `[02-données]`, `[10-medical]`, `[20-Documentations]`, `[30-Infra-Home]`, `[40-Formations]`, `[90-Projets Informatique]`, Google Drive synchronisé, `musiques/`, `Rapport-PDF/`, `@@@-trier URGENT/`… + `Photos` | **le vrai serveur de fichiers de Thomas** : pro et perso mêlés, déjà rangé par numéros |
| `tclement` | `0-Trier-hdd-1TB/`, scripts, `Photos` | vidage d'un ancien disque à trier |
| `MLB` | `Limo/`, `ML/`, `Photos` | |
| `admin` | `rapports_permissions/`, `syno-liste-perm.sh` | un audit de droits a déjà été tenté |
| `julie`, `Pape` | `Photos` | orphelins |

**Sauvegardes de téléphones** (Synology Photos) : `MLB` ← « Redmi Note 11 » ; `Tom` ← « Agesti »,
« agesti iPhone », « iPhone » **et aussi « Redmi Note 11 »** (le téléphone de MLB sauvegardé
deux fois, ou un second Redmi : à vérifier).

### 1.6 Ce qui va bien

SMB2 minimum ; `admin` et `guest` désactivés ; comptes de service sans shell (sauf
`ServiceHA` et `netsight`) ; `netsight` refusé sur les données ; un compte par usage de
sauvegarde ; Hyper Backup, Snapshot Replication et Hyper Backup Vault installés ; Tom et
tclement séparent déjà, sur le principe, le perso et l'administration.

---

## 2. Diagnostic

1. 🔴 **`docker` lisible par tous les comptes.** Le risque le plus concret : n'importe quel compte
   compromis (un service, MLB) lit les secrets de toutes les piles (Gitea, PBS, Matothèque…). À
   corriger **en premier**, indépendamment du reste.
2. 🔴 **`Tom` écrit dans tous les homes** par une ACE posée à la main à la racine de `homes`. La
   vie privée de MLB n'existe pas, et un rançongiciel sur le PC de Tom chiffrerait tous les homes.
3. 🟠 **Trois services administrateurs** (`netsight`, `ServiceHA`, et `admin` désactivé), deux
   avec shell. Un service n'a pas à pouvoir ouvrir une session SSH root.
4. 🟠 **Groupes d'application utilisés comme groupes de droits** (`photo`,
   `matotheque-utilisateurs`) : des droits apparaissent sans décision.
5. 🟠 **Homes orphelins aux propriétaires croisés** (§ 1.4).
6. 🟡 **Les données vivent dans les homes** (`Tom`, `tclement`) au lieu des partages, et la
   photothèque partagée est fermée à MLB : c'est la conséquence logique, pas une erreur des
   utilisateurs.
7. 🟡 **Rien n'est décrit** : ni les comptes, ni les partages.
8. 🟡 **Pas de corbeille** sur les données ; **82 %** du volume occupé.

---

## 3. Principes retenus

1. **Une personne = un compte personnel sans droits d'administration** ; l'administration se fait
   avec un compte distinct, protégé par la double authentification. *Ça existe déjà : `Tom` /
   `tclement`. On le formalise et on vide `tclement` de ses données.*
2. **Un service = un compte de service** : pas d'administration sauf nécessité prouvée, pas de
   shell, privilèges d'application refusés sauf le strict nécessaire, description renseignée, mot
   de passe dans Bitwarden.
3. **Deux familles de groupes, jamais mélangées** :
   - `app-*` ouvre une **application** (Photos, Drive, Matothèque…) — **aucun droit sur un partage** ;
   - `grp-*` donne des **droits sur des partages** — rien d'autre.
4. **Les ACL citent des groupes, jamais des personnes** (seule exception : un compte de service
   dans le partage qu'il alimente).
5. **Un partage = un domaine et un propriétaire**, nommé et décrit.
6. **`homes` = Synology Photos uniquement** (on ne peut pas le supprimer, § 6).
7. **Ne pas renommer ce dont dépend autre chose** sans plan de bascule (Docker, Plex, LXC, Home
   Assistant, scanners, GED, NetSight, licitis).

---

## 4. Comptes et groupes cibles

### 4.1 Comptes

| Compte | Cible | Action |
|---|---|---|
| `Tom` | personne, non admin | retirer toutes ses ACE nominatives → droits par `grp-*` |
| `tclement` | **compte d'administration** de Thomas | 2FA ; plus de données dans son home (316 Go à ranger) ; pas de lecteur réseau monté avec ; garder `matotheque-admin` |
| `MLB` | personne | droits par `grp-*` uniquement |
| `admin`, `guest` | désactivés | retirer `admin` des ACL de `Rapport-PDF`, `Scan`, `ActiveBackupforBusiness` |
| `netsight` | service, **admin conservé si l'API l'exige** (lecture des paquets DSM) | refuser tous les privilèges d'application sauf DSM ; `ha-backups` en **lecture** ; vérifier qu'il n'est plus propriétaire d'aucun dossier |
| `ServiceHA` | service | **essayer sans `administrators`** (l'intégration DSM de HA lit l'essentiel sans) ; sinon même traitement que `netsight` |
| `HA`, `srv-ha-reva`, `srvbck`, `proxmoxback`, `srvplex`, `geco-depot`, `licitis` | services | renseigner la description (« Service — <application> — <machine> ») ; `proxmoxback` retiré de `Partage-Geco` ; `geco-depot` ramené à lecture/écriture sans changement d'ACL |
| `svc-ged` | **nouveau** (remplace `SVR-GED` de P8, D4) | lecture accordée **dossier par dossier** (D3) |
| `svc-rangement` | **nouveau** (D6) | écriture sur les dossiers que le Rangement réorganise, le temps du chantier |
| `svc-ged-rw` | **nouveau** | écriture limitée à `Scan` (boîte à scans) et à la corbeille GED |

**On ne renomme pas les comptes de service existants** : chaque renommage oblige à reconfigurer
le client (HA, PBS, Plex, licitis…). La convention `svc-<application>` s'applique aux **nouveaux**
comptes ; les anciens sont rendus lisibles par leur description. Les renommer plus tard,
au fil des reconfigurations, si on le souhaite.

### 4.2 Groupes

| Groupe cible | Membres | Remplace |
|---|---|---|
| `administrators` | **`tclement` seul** (+ `netsight`/`ServiceHA` si prouvé nécessaire) | — |
| `grp-famille` | `Tom`, `MLB` | l'usage du groupe `photo` comme groupe de droits |
| `grp-pro` | `Tom` | (les droits pro donnés nommément à `Tom`) |
| `grp-medias` | `Tom`, `MLB` | `photo` + `matotheque-utilisateurs` sur `media` |
| `grp-logitheque` | `Tom` | `matotheque-utilisateurs` sur `Applications` |
| `grp-services` | tous les comptes de service | pour leur **refuser** File Station, Photos, Drive, etc. en un seul endroit |
| `app-photos` *(= `photo` actuel)* | `Tom`, `MLB` | **retirer de toutes les ACL** |
| `app-matotheque-*` *(= `matotheque-*` actuels)* | inchangés | **retirer de toutes les ACL** ; ne pas les renommer si Matothèque s'appuie dessus (SSO) |
| `Drive`, `mail-contact-calendar-note` | inchangés | déjà corrects |

Renommer `photo` en `app-photos` est facultatif ; ce qui compte est qu'il **ne figure plus dans
aucune ACL**.

### 4.3 Matrice des droits cible (É = écriture, L = lecture, — = rien)

| Partage | `grp-famille` | `grp-pro` | `grp-medias` | `grp-logitheque` | `svc-ged` (L = dossiers choisis, D3) | service propre |
|---|---|---|---|---|---|---|
| `Partage-Nas-Mato` (→ `fam-documents`) | É | — | — | — | L | — |
| `Associations`, `Formation` | É | — | — | — | L | — (**retirer `everyone`**) |
| `photo` | **É** (nouveau pour MLB) | — | — | — | L | — |
| `Partage-Geco` | — | É | — | — | — (Hybrid Share) | `geco-depot` É |
| `Rapport-PDF` | — | É | — | — | L | `licitis` É |
| `Scan` | É | É | — | — | L | `svc-ged-rw` É |
| `media` | — | — | É | — | — | `srvplex` L |
| `music` | — | — | É | — | L | — |
| `Applications` | — | — | — | É | — | — |
| `docker`, `script` | — | — | — | — | — | administrateurs seuls (**retirer `everyone`**) |
| `Bkp`, `TimeMachine`, `ha-backups`, `HA-Data` | — | — | — | — | — | leur service ; `netsight` L sur `ha-backups` |
| `homes` | chacun **son** home | — | — | — | — (D3), sauf dossier ouvert explicitement | — (**retirer l'ACE de `Tom`**) |

`administrators` garde l'accès partout (c'est `tclement`, avec 2FA).

---

## 5. Partages cibles

### 5.1 Convention

`<domaine>-<contenu>` en minuscules : `fam-` famille · `pro-` professionnel · `sys-`
infrastructure · `bkp-` sauvegardes. **Restent tels quels** : partages système et paquets
(`homes`, `photo`, `music`, `surveillance`, `MailPlus`, `ActiveBackupforBusiness`,
`PlexMediaServer`, `TimeMachine`), `docker` et `Scan` (trop de dépendances).

**Chaque partage reçoit une description** (propriétaire, contenu, qui écrit, sauvegardé où) :
c'est sans risque et ça règle à lui seul le « mal identifiés ».

### 5.2 Correspondance

| Aujourd'hui | Cible | Action | Dépendances à vérifier |
|---|---|---|---|
| `Partage-Nas-Mato` | `fam-documents` | renommer ; les sous-dossiers `[Famille-…]`, `[MaTo]`, `[Sophie]` restent | GED (1 921 fiches), lecteur `T:` |
| `homes/Tom` hors `Photos` | `fam-documents` (perso) et `pro-agesti` (`[01.Agesti]`) | **déplacer** (§ 6.3) | GED (~132 000 fiches), Google Drive synchronisé |
| `homes/tclement/0-Trier-hdd-1TB` | `fam-a-trier` (temporaire) ou `Bkp` | déplacer, puis trier | GED (~51 500 fiches) |
| `Associations` + `Formation` | `fam-associations`, `fam-formation` | renommer (ou fusionner) | lecteur `X:` |
| `Partage-Geco` | `pro-geco` | renommer ; sortir `Valheim*` et l'installeur | Hybrid Share, `geco-depot`, lecteur `K:` |
| `Rapport-PDF` | `pro-rapports` | renommer **avec** licitis et Matothèque | licitis, Matothèque, lecteur `P:` |
| `Applications` | `sys-logitheque` | renommer ; vider `tmp`, `scoped_dir*`, `A trier` | lecteur `O:` |
| `script` | `sys-scripts` | renommer si aucune tâche planifiée ne l'appelle (annexe B) | tâches DSM |
| `Bkp` | `bkp-divers` puis éclatement par origine | trier : `2024-09-22`, `old-glpi`, `vps-inonos`… | `srvbck`, `proxmoxback`, Hyper Backup |
| `HA-Data` / `ha-backups` | `sys-ha-data` / `bkp-ha` | **en dernier**, avec Home Assistant | HA, NetSight (contrôle des sauvegardes) |
| `docker`, `Scan`, `media`, `music`, `photo` | inchangés | — | — |

Ordre : d'abord ce dont rien ne dépend, en dernier ce qui est branché sur un service. Avant tout
renommage, l'annexe B liste les chemins `/volume1/<partage>` cités par les piles Docker.

---

## 6. `homes` et Synology Photos

### 6.1 Pourquoi on le garde

La sauvegarde des smartphones de Synology Photos écrit dans l'**espace personnel**,
`homes/<compte>/Photos/MobileBackup/<appareil>` (5 appareils sauvegardés aujourd'hui). Couper
« Accueil utilisateur » couperait ces sauvegardes. `homes` reste — **pour ça seulement**.

### 6.2 Le cantonner

1. **Retirer l'ACE `Tom` de la racine de `homes`.** Chacun ne voit que son home. C'est la mesure
   qui compte le plus.
2. **Ouvrir `photo` à `grp-famille` en écriture** : c'est l'absence de photothèque commune qui
   pousse chacun à tout garder dans son home.
3. **Quotas** sur `homes`, dimensionnés pour les photos (après l'annexe B).
4. **Plus de lecteur réseau sur `homes`** : supprimer `L:`, `U:`, `W:` ; masquer `homes` dans
   le voisinage réseau. Les photos se consultent dans Synology Photos.
5. **Homes orphelins** (§ 1.4) : rapatrier `julie/Photos` et `Pape/Photos` dans `photo`
   (dossiers à leur nom), puis supprimer ces dossiers ; supprimer les homes vides des comptes
   disparus (`greg`, `mrobin`, `scan`, `SrvDocker`) ; rendre `homes/HA` et `homes/srvbck` à leur
   compte. **Avant** : vérifier qu'aucune fiche de la GED n'y pointe encore (`homes/julie` en a 5).

### 6.3 Vider les homes de leurs documents

| Home | Garder | Déplacer |
|---|---|---|
| `Tom` | `Photos` | `[01.Agesti]` → `pro-agesti` ; le reste → `fam-documents/Thomas/` (la numérotation existante se garde telle quelle) ; `musiques/` → `music` ; `Rapport-PDF/` → `pro-rapports` |
| `tclement` | `Photos` (ou fusion dans `Tom/Photos`) | tout le reste → `fam-a-trier` |
| `MLB` | `Photos` | `Limo/`, `ML/` → `fam-documents/Marie-Laure/` **avec son accord** |
| `admin` | — | archiver `rapports_permissions/` dans `sys-scripts`, puis vider |

C'est le plus gros chantier (~600 Go, ~185 000 fiches GED) et il est **physique** : voir § 8.

### 6.4 Photothèque

- **Espace personnel** = brut des téléphones, privé.
- **Espace partagé `photo`** = photothèque familiale, rangée `AAAA/AAAA-MM-événement` ; les 5
  photos posées à la racine vont dans `2026/`. On y copie depuis l'espace personnel ce qui doit
  être vu de tous.
- Vérifier pourquoi « Redmi Note 11 » est sauvegardé à la fois chez MLB et chez Tom.

---

## 7. Protection des données (avant tout déplacement)

1. 🔴 **`docker` : retirer les 6 ACE `everyone`** — méthode dans l'annexe C (les conteneurs non root en dépendent : on ne retire pas tout d'un coup).
2. **Corbeille** sur tous les partages de données, réservée aux administrateurs, vidée à 30 jours.
3. **Instantanés Btrfs** planifiés (Snapshot Replication est installé) sur `homes`, `photo`,
   `Partage-Nas-Mato`, `Partage-Geco`, `Scan`, `Rapport-PDF` — vérifier l'existant (annexe B).
4. **Hyper Backup hors du NAS** pour `homes` (photos de téléphones), `photo`, documents
   familiaux et pro (scénario S4 du PRA de NetSight, encore ouvert). `Partage-Geco` est un Hybrid
   Share : sa copie C2 est une synchronisation, **pas** une sauvegarde.
5. **Espace** : 4 To libres sur 21. `Bkp` (anciens disques, vieux GLPI, VPS) et
   `0-Trier-hdd-1TB` sont les premiers candidats au tri.
6. **Journal des transferts SMB** (Log Center) activé pendant la migration.

---

## 8. Ce que ça change pour Matothèque

- **La GED lit aujourd'hui avec `Tom`**, et c'est l'ACE de `Tom` à la racine de `homes` qui lui
  donne `homes/tclement` et `homes/MLB`. **Retirer cette ACE (§ 6.2) fera passer ~53 000 fiches en
  « absent »** (tclement 51 505, MLB 1 525, julie 5) si rien n'est fait avant. Ordre impératif :
  1. créer `svc-ged` et lui donner la lecture **dossier par dossier** (D3) ;
  2. GED : étapes 1 à 5 de `plan-partages-nas.md` (fusion `home` → `homes/Tom`), **puis** bascule
     de la source vers `svc-ged` (P8) ;
  3. seulement ensuite, retirer l'ACE de `Tom`.
- **Renommer un partage ou déplacer un dossier change l'adresse `smb://…` de toutes ses fiches.**
  La synchro reconnaît « même nom + même taille » ; à **vérifier sur une copie de prod** pour un
  changement de partage avant d'en dépendre.
- **Qui déplace** : règle en vigueur, « seul le Rangement déplace des fichiers sur le NAS ». Les
  déplacements du § 6.3 passent par le Rangement, ou par File Station avec la synchro GED
  suspendue (D6).
- `Rapport-PDF` est une **sortie** de Matothèque (`docflow/`) : son renommage se fait avec un
  changement de réglage dans Matothèque. Les noms mal formés (`…rapport.pdf<uuid>.pdf`) sont à
  signaler côté Matothèque / licitis.
- `Partage-Geco` (Hybrid Share) : **ne pas l'indexer** — lire un fichier non mis en cache le
  rapatrie depuis le cloud C2.
- `Scans_Epson` n'existe plus : le retirer de la GED.

---

## 9. Décisions à prendre

| Réf | Question | Recommandation |
|---|---|---|
| D1 | `tclement` et `Tom` ? | ✅ **Tranché par Thomas (13/11)** : même personne, deux rôles — `tclement` = administrateur, `Tom` = utilisateur. Reste à faire : vider le home de `tclement` (316 Go) et lui imposer la 2FA |
| D2 | Renommer les comptes existants ? | ✅ **Non** (13/11) : descriptions + convention `svc-` pour les nouveaux |
| D3 | La GED lit-elle encore les homes ? | ✅ **Non** (13/11). `svc-ged` reçoit la lecture **dossier par dossier**, uniquement là où la GED doit lire ; rien n'est hérité de la racine d'un partage. Conséquence pour P2 : la fusion `home` → `homes/Tom` se fait quand même (elle nettoie l'index), puis ces fiches sortent du périmètre sauf dossier explicitement ouvert |
| D4 | `SVR-GED` (P8) ou `svc-ged` ? | ✅ **`svc-ged`** (13/11) ; P8 du plan GED à mettre à jour |
| D5 | Préfixes `fam-` / `pro-` / `sys-` / `bkp-` ? | ✅ **Oui** (13/11), hors partages système, `docker`, `Scan` |
| D6 | Déplacements des homes : Rangement ou File Station ? | ✅ **Rangement** (13/11) — test grandeur nature. Demande un compte `svc-rangement` en écriture sur les dossiers source et destination (aujourd'hui le Rangement ne lit que `media`, via `srvplex`) ; commencer par un petit dossier, vérifier l'annulation et la synchro GED, puis monter en volume |
| D7 | `netsight` et `ServiceHA` doivent-ils rester administrateurs ? | ⏳ **À établir, dossier par dossier** (13/11) : relever ce que chaque service lit ou écrit réellement, donner ces droits-là, puis tester sans `administrators` |
| D8 | Photos de `julie` et `Pape` (homes orphelins) | ⏳ **À voir** (13/11) : ces homes servaient à **partager des photos**. Une fois `photo` ouvert, le partage passe par les albums partagés / liens de Synology Photos, sans compte ni home ; décider ensuite du sort des dossiers |
| D9 | MLB doit-elle garder l'écriture sur `Applications`, `Partage-Geco`, `media` ? | ✅ **Non** pour les deux premiers (13/11) ; `media` via `grp-medias` |
| D10 | `[01.Agesti]` (pro) dans un partage `pro-agesti` distinct de `pro-geco` ? | ✅ **Oui** (13/11) : une entreprise = un partage |

---

## 10. Étapes

| # | Étape | Impact | Réversible |
|---|---|---|---|
| 0 | Relevé complémentaire (annexe B) | aucun | — |
| 1 | 🔴 `docker` : retirer `everyone` ; `Associations` : retirer `everyone` | aucun pour les usages légitimes (les piles tournent en root) | oui |
| 2 | Corbeille, instantanés, Hyper Backup hors NAS | aucun | oui |
| 3 | `tclement` : 2FA. `netsight` / `ServiceHA` : privilèges d'application refusés, test sans `administrators` (D7) ; `netsight` en lecture sur `ha-backups` | NetSight, HA | oui |
| 4 | Descriptions de tous les comptes et partages | aucun | oui |
| 5 | Créer `grp-*`, y mettre les comptes, **ajouter** les groupes aux ACL (sans rien retirer encore) | aucun | oui |
| 6 | Retirer des ACL : `photo`, `matotheque-utilisateurs`, `admin`, `proxmoxback` (Geco), droits nominatifs de `Tom` — **sauf** l'ACE de `homes` | droits de MLB (D9) | oui |
| 7 | GED : `svc-ged`, plan partages étapes 1-5, bascule de la source (§ 8) | GED | via le plan GED |
| 8 | Retirer l'ACE `Tom` de `homes` ; ouvrir `photo` à `grp-famille` ; homes orphelins (§ 6.2) | vie privée | oui |
| 9 | Renommages sans dépendance : `Partage-Nas-Mato`, `Associations`, `Formation`, `Applications` | lecteurs, GED | oui |
| 10 | Vider les homes (§ 6.3), quotas | GED, volume | instantanés |
| 11 | Renommages branchés : `Partage-Geco`, `Rapport-PDF`, `script`, `Bkp`, `HA-*` avec leur service | services | oui |
| 12 | Bilan : relancer les annexes A et B, comparer, mettre la doc à jour | — | — |

---

## Annexe A — Relevé n° 1 (fait le 13/11/2026)

Comptes, groupes, droits des partages, ACL, 1ᵉʳ niveau des partages et des homes, sauvegardes
mobiles, crontab. Résultat dans `homes/Tom/audit-nas-mato.txt`. La boucle des volumes n'a rien
rendu : `ionice` n'existe pas sur DSM.

## Annexe B — Relevé n° 2 (à lancer)

Lecture seule. Le seul contenu de fichier lu : les `docker-compose` du partage `docker`, dont
on n'extrait **que** les chemins `/volume1/…` (pas les variables ni les secrets). `du -x` ne
descend pas dans le montage CIFS `media/nas-media`. Compter plusieurs minutes.

```bash
sudo -i
OUT=/tmp/audit-nas-mato-2.txt
{
echo "===== Volumes par partage"
for s in ActiveBackupforBusiness Applications Associations Bkp docker Formation ha-backups HA-Data MailPlus media music Partage-Nas-Mato photo PlexMediaServer Rapport-PDF Scan script surveillance TimeMachine; do nice -n 19 du -shx /volume1/"$s" 2>/dev/null; done
echo "===== homes : propriétaires numériques, volumes"
ls -lan /volume1/homes
for d in /volume1/homes/*/ /volume1/homes/*/Photos; do nice -n 19 du -shx "$d" 2>/dev/null; done
echo "===== Instantanés par partage"
for d in /volume1/@sharesnap/*/; do echo "$(basename "$d") : $(ls -1 "$d" | wc -l) instantanés, dernier $(ls -1 "$d" | sort | tail -1)"; done
echo "===== Tâches planifiées DSM"
for i in $(seq 1 17); do echo "--- id=$i"; synoschedtask --get id=$i | grep -viE 'pass|token|secret'; done
echo "===== Hyper Backup (sans secrets)"
grep -iE '^\[|name|backup_folders|remote|target|dest|schedule|share' /var/packages/HyperBackup/etc/synobackup.conf 2>/dev/null | grep -viE 'pass|secret|key|token|cred'
echo "===== Chemins du NAS cités par les piles Docker"
grep -rhoE "/volume1/[A-Za-z0-9_@.-]+" /volume1/docker --include="*compose*.y*ml" 2>/dev/null | sort | uniq -c | sort -rn
echo "===== Nombre de fichiers .env dans docker"
find /volume1/docker -maxdepth 3 -type f \( -name ".env" -o -name "*.env" \) 2>/dev/null | wc -l
} > "$OUT" 2>&1
cp "$OUT" /volume1/homes/Tom/ && chown Tom /volume1/homes/Tom/audit-nas-mato-2.txt
echo "Terminé : $(wc -l < "$OUT") lignes"
```

Les deux fichiers d'audit contiennent la liste des comptes et des droits : les supprimer de
`homes/Tom` une fois le plan arrêté.

## Annexe C — Partage `docker` sans `everyone`

### Pourquoi `everyone` avait été mis

Un conteneur qui tourne avec un utilisateur non root (`PUID=1000`, Postgres en 999, Grafana en
472…) accède à ses dossiers montés avec un identifiant **qui n'est pas un compte DSM**. La seule
règle d'ACL qui le laissait passer était `everyone`. Effet de bord : **tout compte DSM** (MLB, les
services, un compte compromis) lit aussi en SMB les `docker-compose.yml` et les `.env`.

Ce dont un conteneur a besoin, c'est de **ses dossiers de données**. Les `docker-compose.yml` et
les `.env` sont lus par Container Manager, qui tourne en **root** : aucune ACL ne lui est
nécessaire.

### Modèle cible

```
docker/                     administrators É, grp-docker-admin É — rien d'autre
└── <appli>/
    ├── docker-compose.yml  hérite : administrateurs seulement
    ├── .env                hérite : administrateurs seulement
    └── data/               + svc-docker É   (seul dossier ouvert au conteneur)
```

1. **Compte `svc-docker`** (sans shell, toutes applications refusées) et groupe `grp-docker` :
   les conteneurs « linuxserver » et assimilés tournent avec `PUID=<uid svc-docker>` et
   `PGID=<gid grp-docker>` (ou `user: "<uid>:<gid>"` dans le compose).
2. **Images à identifiant figé** (bases de données…) : passer leurs données en **volumes Docker
   nommés** (`/volume1/@docker/volumes`, hors de tout partage, invisibles en SMB — c'est déjà le
   cas de Proxmox Backup Server). Leur sauvegarde se fait alors par un **dump** planifié dans
   `docker/<appli>/backup/`, que Hyper Backup emporte.
3. **Accès d'administration depuis le PC** : groupe `grp-docker-admin`. Deux options :
   - **recommandée** — y mettre `tclement` seul, et monter `N:` avec `tclement` par le **nom**
     du NAS (`\\NAS-MATO\docker`) : Windows refuse deux comptes différents vers la même
     adresse (erreur 1219), mais accepte un nom et une IP comme deux serveurs ;
   - **simple** — y mettre `Tom`. Thomas garde ses habitudes, mais un rançongiciel sur le PC
     atteindrait les piles et leurs secrets.

### Bascule, une pile à la fois

1. Relevé (commande ci-dessous) : qui tourne en quel utilisateur, quels dossiers sont montés.
2. Pour chaque pile : arrêter, attribuer `data/` à `svc-docker` (ou passer en volume nommé),
   régler `PUID`/`PGID`, redémarrer, vérifier les journaux.
3. Quand **toutes** les piles tournent sans `everyone` : retirer `everyone` à la racine de
   `docker`, puis changer les secrets des `.env` les plus sensibles (ils ont été lisibles par
   tous les comptes).
4. Retour arrière d'une pile : remettre `everyone` en lecture sur **son** dossier seulement.

### Relevé des conteneurs (lecture seule, aucune variable secrète affichée)

```bash
sudo -i
for c in $(docker ps -a --format '{{.Names}}'); do
  echo "=== $c"
  docker inspect --format 'image={{.Config.Image}} user="{{.Config.User}}" état={{.State.Status}}' "$c"
  docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$c" | grep -E '^(PUID|PGID|UID|GID|USER_UID|USER_GID)='
  docker inspect --format '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}}{{println}}{{end}}' "$c"
  docker top "$c" -eo uid 2>/dev/null | tail -n +2 | sort -u | tr '\n' ' '; echo
done > /tmp/audit-docker.txt 2>&1
stat -c '%u:%g %a %n' /volume1/docker/*/ /volume1/docker/*/*/ >> /tmp/audit-docker.txt 2>/dev/null
cp /tmp/audit-docker.txt /volume1/homes/Tom/ && chown Tom /volume1/homes/Tom/audit-docker.txt
```

## Annexe D — Cas concret : Zabbix (relevé du 13/11/2026)

**Constats**
- `docker/Zabbix Proxy` a des droits **propres, non hérités** : **`everyone` en modification**.
  N'importe quel compte du NAS peut modifier la base du proxy et sa clé PSK (64 octets, en clair).
- Qui écrit quoi : `mariadb:10.9.8` (utilisateur `mysql`, uid 999) écrit `db_data/` ; le proxy
  (`zabbix`, uid 1997) ne fait que **lire** `zabbix_proxy_psk`. Aucun des deux uid n'est un compte
  DSM : d'où `everyone`.
- Mots de passe MariaDB en clair dans `compose.yml` (lisible par tous).
- `docker/Zabbix Server` semble **abandonné** : il monte `./zabbix/mysql` qui n'existe pas, ses
  dossiers sont vides depuis février, et il publie le port 10051 déjà pris par le proxy.

**Correction** : base et clé dans des **volumes Docker nommés** (hors de tout partage, donc hors
SMB et hors ACL) ; le dossier ne garde que `compose.yml` et `.env`, réservés aux administrateurs.
La base d'un proxy Zabbix n'est qu'un tampon : elle se reconstruit seule, pas de sauvegarde à prévoir.

```bash
sudo -i
cd "/volume1/docker/Zabbix Proxy"
docker run --rm --entrypoint id mariadb:10.9.8 mysql      # attendu : uid=999
docker compose down
docker volume create zbxproxy_db
docker run --rm -v "$PWD/db_data":/from:ro -v zbxproxy_db:/to alpine sh -c 'cp -a /from/. /to/ && chown -R 999:999 /to'
docker volume create zbxproxy_psk
docker run --rm -v "$PWD/zabbix_proxy_psk":/src:ro -v zbxproxy_psk:/to alpine sh -c 'cp /src /to/zabbix-proxy.psk && chmod 444 /to/zabbix-proxy.psk'
```

Dans `compose.yml` : `zabbix-proxy-mysql` → `volumes: [zbxproxy_db:/var/lib/mysql]` ;
`zabbix-proxy` → `volumes: [zbxproxy_psk:/run/zbx-psk:ro]` et
`ZBX_TLSPSKFILE: /run/zbx-psk/zabbix-proxy.psk` (supprimer les blocs `secrets`) ; en bas,
`volumes: {zbxproxy_db: {external: true}, zbxproxy_psk: {external: true}}` ; mots de passe
déplacés dans `.env` (`MYSQL_PASSWORD=${MYSQL_PASSWORD}`).

Puis `docker compose up -d && docker compose logs -f zabbix-proxy` : ni erreur TLS ni erreur de
base, et le proxy « vu récemment » dans l'interface du serveur Zabbix. Alors seulement : dans
File Station, sur `Zabbix Proxy`, supprimer `Tout le monde` et cocher « hériter du parent ».
Garder `db_data/` et l'ancien fichier PSK une semaine (retour arrière = remettre l'ancien
compose), puis les supprimer et **changer la PSK** (côté serveur Zabbix et dans le volume) :
elle a été lisible et modifiable par tous.
