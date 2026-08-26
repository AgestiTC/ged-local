# PLAN — Publication centralisée de la documentation vers BookStack

> **Statut (MAJ 2026-08-05) : Lots 1→3 CODÉS + testés (v1.56.0, branche `feat/zip-contenu`,
> poussée sur GitHub).** Reste : **déployer** (bloqué par une panne `git.agesti.fr` — images 1.56.0
> buildées mais non poussées au registre) ; **Lot 4** (convention propagée par _modele — session
> prévenue) et **Lot 5** (branchement Sapyn) hors GED-LOCAL. Détail par lot : § Décisions verrouillées.
> Rédigé le 2026-08-26 depuis la session Sapyn, **déplacé dans GED-LOCAL le
> jour même** à la demande de Thomas — « pour ne pas mélanger les projets ».
> C'est ici que le travail se fait (lots 1 à 3), donc ici que le plan vit.
> Exemplaire unique : il n'en reste **aucune copie** dans `_modele/`.
>
> **Suite directe de [`../PLAN-bookstak.md`](../PLAN-bookstak.md)** : ce
> dernier a livré la publication *depuis Matothèque*. Celui-ci ouvre la même
> plomberie *aux autres projets du workspace*. La table `publications` de son
> § 6 (backlog Lot 2) devient ici le **lot 1**, sur le chemin critique.
>
> **Question de départ** (Thomas) : « peux-tu voir avec GED-LOCAL s'il peut
> scanner les projets et trouver s'il y a de la doc à pousser sur le wiki ?
> Trouve un moyen de nommage et le mécanisme d'interconnexion entre les
> projets. Ou encore voir avec `_modele`, et/ou créer un dossier où sera
> stockée toute la documentation à pousser sur le wiki par l'intermédiaire de
> GED-LOCAL. »

---

## 0. Décisions prises — 2026-08-26 (Thomas)

| Question | Décision |
|---|---|
| **Principe** | ✅ **Matothèque publie pour tous.** Une seule clé, détenue par elle ; les projets lui apportent leur document. Option **D** du § 4. |
| **Démarrage** | ⏸️ **Pas de publication avant la passerelle.** *« On passera par la passerelle GED-LOCAL quand elle sera prête, pour publier les livres / pages de Sapyn. »* → **le lot 0 est abandonné** : aucun jeton d'écriture propre à Sapyn ne sera créé. |
| **Périmètre** | ✅ **Tous les projets AgestiTC.** Le monde MIS/Geco reste exclu par construction (§ 3.4). |

### Ce que la décision « pas de lot 0 » implique, en clair

C'est un arbitrage assumé, pas un oubli — mais il a deux conséquences qu'il
vaut mieux avoir écrites :

1. **La doc de Sapyn reste absente / périmée sur le wiki** jusqu'à ce que la
   passerelle tourne. Y compris la correction du 26/08 sur l'image GHCR privée,
   qui n'est donc lisible que sur GitHub pour l'instant.
2. **Le chemin critique passe de « 5 minutes » à quatre lots**, dont un chantier
   de sécurité (lot 2). Rien ne sera publié avant qu'il soit fait.

En échange, on évite de créer un secret qu'il faudrait révoquer trois semaines
plus tard, et on ne prend jamais l'habitude du « chacun sa clé » — l'habitude
qui, à 21 projets, est justement le problème qu'on cherche à éviter.

> **Le périmètre « tous les projets AgestiTC » renforce ce choix.** À deux
> projets, 2 jetons se géraient à la main. À l'échelle du workspace, non — la
> passerelle n'est plus un confort, c'est la seule option tenable.

### Où se fait le travail

**Les lots 1 à 3 sont du ressort de ce dépôt** — table `publications`,
authentification entrante, endpoint passerelle. Tout réutilise du code déjà
écrit ici (`bookstack_service.py`).

Les deux derniers lots sortent de GED-LOCAL et devront être menés depuis leur
propre session :

| Lot | Dépôt | Ce qu'il y faut |
|---|---|---|
| 4 — convention `.claude/wiki.yml` + propagation | `_modele/` | s'appuie sur le mécanisme `propagate` existant |
| 5 — branchement d'un projet appelant | `sapyn/` (le premier) | son script change d'URL cible, rien d'autre |

⚠️ **Sessions concurrentes** : la mémoire de ce projet signale que plusieurs
sessions Claude peuvent écrire dans GED-LOCAL en même temps. Vérifier la
branche courante avant de commiter quoi que ce soit sur ce chantier.

---

## 1. Le point de départ, et pourquoi la question est bonne

Sapyn a besoin d'un **jeton BookStack en écriture** pour publier sa doc. La
première idée — réutiliser celui de GED-LOCAL — se heurte à trois objections
(révocation croisée, historique du wiki attribué au mauvais compte, droits par
livre incertains). La question posée ici est meilleure : **plutôt que dupliquer
un jeton par projet, pourquoi ne pas centraliser la publication ?**

Elle l'est parce qu'elle déplace le problème au bon endroit. À ~21 projets dans
le workspace, « un jeton par projet » signifie 21 secrets à créer, ranger,
faire tourner et révoquer. Ça ne tient pas.

---

## 2. Ce que j'ai vérifié dans le code (pas supposé)

### GED-LOCAL / Matothèque — beaucoup plus avancé que je ne le pensais

| Brique | État | Où |
|---|---|---|
| Client BookStack **en écriture** | ✅ livré | `backend/services/bookstack_service.py` — `create_book`, `create_chapter`, `create_page`, `update_page` |
| Helpers **idempotents** | ✅ livré | `ensure_book()` / `ensure_chapter()` — réutilisent un livre/chapitre de même nom (casse et espaces ignorés) |
| Endpoint de publication | ✅ livré | `POST /api/bookstack/publish` — accepte du markdown direct **ou** un `document_id`, et `new_book` / `new_chapter` |
| Suggestion de cible par IA | ✅ livré | `POST /api/bookstack/suggest` → titre + livre + chapitre proposés par rapprochement thématique |
| Compte de service dédié | ✅ en place | `Support-matotheque` (Editor + rôle « API Matotheque » limité à `access-api`) |
| **Surveillance de dossiers** | ✅ livré | `backend/routers/folders.py` + `services/folder_watcher.py` — chemin, récursif, filtre d'extensions, intervalle de scan |
| Indexation du wiki **vers** la GED | ✅ livré | `backend/services/wiki_jobs.py` (job `index_wiki`) |
| Table `publications` (traçabilité) | ❌ **backlog Lot 2** | `PLAN-bookstak.md` § 6 — c'est précisément la pièce qui manque |
| Étagères (shelves) | ❌ Lot 1b non fait | lister / créer / rattacher |
| **Authentification entrante de l'API** | ❌ **absente** | aucune garde sur les routers — l'appli est pensée 100 % locale |

**Deux découvertes qui changent la donne :**

1. **La surveillance de dossier existe déjà.** L'option « un dossier où l'on
   dépose ce qui doit partir au wiki » n'est pas à construire : c'est une
   fonctionnalité livrée. Deux réserves seulement — les extensions indexées
   sont `pdf, docx, pptx, xlsx, odt, ods, odp`, **`.md` n'en fait pas partie**,
   et ce que le watcher fait aujourd'hui c'est *indexer dans la GED*, pas
   *publier sur le wiki*.
2. **L'API de GED-LOCAL n'a aucune authentification entrante.** Tant qu'elle
   n'est appelée que depuis son propre frontend, c'est cohérent. Dès qu'un
   autre projet l'appelle, ça devient un prérequis, pas un détail.

### Sapyn — un publieur autonome qui marche déjà

`_local-dev/scripts/push_docs_bookstack.py` : pousse `docs/*.md` vers un livre,
**idempotent par titre de page** (met à jour si le titre existe, crée sinon),
**simulation par défaut** (`--apply` pour écrire), pur stdlib, bandeau
automatique « page publiée depuis le dépôt, toute modification ici sera
écrasée ». Il lui manque uniquement le jeton.

### `_modele` — le mécanisme d'interconnexion existe, et il est bon

C'est la réponse à « trouve un mécanisme d'interconnexion entre les projets » :
**il ne faut pas l'inventer, il faut s'y brancher.**

- `.claude/.propagate` — marqueur par projet (`enabled`, `model`,
  `model_version`, `last_propagated`)
- `propagate-manifest.json` — liste autoritaire « ceci est du framework / ceci
  est ton code », avec une section `never_touch`
- `propagate.ps1` — applique les nouveautés, **saute ce que le projet a
  modifié**, signale les divergences au lieu d'écraser
- `socle-engine/engine-manifest.json`, `VERSION` = 0.5.0

Le socle sait déjà distribuer une convention à N projets sans écraser leur
travail. Une convention de publication doc est exactement ce genre d'objet.

---

## 3. Les quatre obstacles que l'idée initiale ne voit pas encore

### 3.1 Les projets ne sont pas tous sur la même machine

C'est le blocage principal de « GED-LOCAL scanne les projets ».

- **Sapyn** vit sur un partage NAS : `O:\Github\sapyn` =
  `\\192.168.42.200\applications\Github\sapyn`
- **GED-LOCAL** vit sur le disque Windows local :
  `C:\Users\User\Documents\code-claude-\GED-LOCAL`
- **GED-LOCAL en production** tourne dans un **LXC 102 sur Proxmox**, dans des
  conteneurs Docker

Pour scanner, il faut que le chemin soit visible **depuis le conteneur**. Les
chemins Windows locaux ne le sont pas, et le seront d'autant moins en prod. Il
faudrait tout regrouper sur un partage monté dans le LXC — un chantier
d'infrastructure, pas une fonctionnalité.

> **Or HTTP traverse tout ça sans rien monter.** C'est l'argument central de la
> recommandation en § 5.

### 3.2 Deux des documents de Sapyn sont *générés* — un scan publierait du faux

`docs/PERMISSIONS.md` et `docs/VERSIONS.md` sont dérivés du code et des tags
git. Un scanner qui recopie des fichiers **ne peut pas savoir** qu'un fichier
généré est périmé : il publierait fidèlement une version fausse, sans que rien
ne le signale. Et une page de wiki fausse est plus dangereuse que pas de page —
c'est déjà écrit noir sur blanc dans `docs/PUBLIER-DOC-BOOKSTACK.md`.

**Conséquence :** la régénération doit avoir lieu **dans le projet**, au moment
de la release. Le *déclencheur* appartient donc au projet, même si le
*transport* est centralisé.

### 3.3 Le wiki est une surface publiée — l'opt-in est une barrière de sécurité

C'est le point que je veux mettre le plus en avant.

Publier « tous les `.md` » de 21 projets, ce n'est pas de la plomberie, c'est
une décision de sécurité. Quelques exemples réels, pris ce matin :

| Fichier | Ce qu'il contient |
|---|---|
| `sapyn/docs/audite-intrusion.md` | audit d'intrusion |
| `sapyn/docs/nginx-security-roadmap.md` | failles connues et non encore corrigées |
| `sapyn/AUDIT-2026-07-31.md` | 50 constats de sécurité, dont des trous ouverts |
| `sapyn/PLAN-CORRECTION-AUDIT-2026-07-31.md` | ce qui n'est **pas encore** corrigé, et où |
| `../PLAN-bookstak.md` | un **token_id BookStack en clair** (ligne 62) |

Un scan aveugle publierait la liste des faiblesses non corrigées d'une appli
exposée sur Internet, et un identifiant d'API.

> **Donc : la convention de nommage n'est pas du confort d'organisation. C'est
> la frontière entre « interne » et « publié ».** Elle doit être **explicite et
> opt-in** — jamais « tout sauf une liste d'exclusions », parce qu'un fichier
> sensible ajouté demain serait publié par défaut.

*Au passage : ce `token_id` en clair dans un fichier versionné mérite un coup
d'œil, indépendamment de ce plan. Ce n'est pas le secret — mais BookStack
traite la paire id + secret comme un identifiant, et la règle du workspace est
« aucun secret en clair ».*

### 3.4 La frontière des deux mondes

`PLAN-commun.md` pose une séparation étanche : **BookStack est un outil du
monde 🟦 AgestiTC**. Le monde 🟩 MIS/Geco a ses propres outils, et Thomas n'a
pas la main dessus.

Une publication centralisée doit donc **refuser** de publier un projet Geco sur
`wiki.agesti.fr`. Ça ne peut pas être une consigne dans un document : ça doit
être une vérification dans le mécanisme.

---

## 4. Les options, et ce qui les départage

| # | Option | Qui décide quoi publier | Qui porte le jeton | Voit-il les fichiers ? |
|---|---|---|---|---|
| **A** | Chaque projet publie lui-même (Sapyn aujourd'hui) | le projet | **N jetons** | oui, nativement |
| **B** | GED-LOCAL scanne les dépôts | GED-LOCAL | 1 jeton | ❌ **non** (§ 3.1) |
| **C** | Dossier « à publier » surveillé par GED-LOCAL | celui qui dépose | 1 jeton | oui, si partage commun |
| **D** | **GED-LOCAL = passerelle ; les projets appellent son API** | le projet | **1 jeton** | pas besoin |

**Ce qui les départage** — deux questions, pas une :

1. *Qui décide qu'un document doit être publié, et quand ?* → **le projet**, à
   cause de § 3.2 (docs générés) et § 3.3 (sensibilité).
2. *Qui détient le secret et garde la trace ?* → **un seul endroit**, sinon on
   revient à 21 jetons.

Les options A à C répondent aux deux avec le même acteur, et se trompent donc
sur l'une des deux. **L'option D est la seule qui sépare les deux réponses.**

---

## 5. Recommandation — GED-LOCAL comme *passerelle*, pas comme *scanner*

> **GED-LOCAL ne va pas chercher la doc. Ce sont les projets qui la lui
> apportent, et lui seul parle à BookStack.**

```
┌──────────┐   POST /api/wiki-publish   ┌───────────────┐   API BookStack  ┌───────────┐
│  Sapyn   ├───────────────────────────▶│               ├─────────────────▶│           │
├──────────┤   { projet, doc, markdown }│  GED-LOCAL    │  jeton unique    │ BookStack │
│ NetSight ├───────────────────────────▶│  passerelle   │  Support-*       │           │
├──────────┤                            │               │                  └───────────┘
│ Dashfav  ├───────────────────────────▶│ + table       │
└──────────┘                            │  publications │
                                        └───────────────┘
```

**Ce que ça règle :**

- **un seul secret**, sur un seul compte de service, révocable sans casser 21 projets ;
- **aucun montage de disque** — les projets sont sur C:, sur le NAS, ou ailleurs, HTTP s'en moque ;
- **la traçabilité** au bon endroit : la table `publications` (déjà au backlog Lot 2 de GED-LOCAL) donne *qui a publié quoi, quand, et sur quelle page*, donc la **mise à jour** au lieu de la recréation ;
- **le projet garde la main** sur ce qu'il publie et quand — donc régénération à jour et rien de sensible qui parte tout seul ;
- **la frontière des mondes** devient vérifiable en un point unique : la passerelle refuse un projet non-AgestiTC.

**Ce que ça coûte :** GED-LOCAL devient une dépendance de la publication (s'il
est éteint, on ne publie pas — acceptable, la publication n'est pas critique),
et il faut lui **ajouter une authentification entrante**, qu'il n'a pas (§ 2).

---

## 6. Convention de nommage proposée

### 6.1 Côté projet — un manifeste explicite

Un fichier `.claude/wiki.yml` par projet, distribué par le socle `_modele` :

```yaml
enabled: true                    # opt-out possible, comme .propagate
monde: agestitc                  # agestitc | geco — geco ⇒ publication refusée
etagere: "Projets AgestiTC"      # shelf BookStack (Lot 1b de GED-LOCAL)
livre: "Sapyn"                   # 1 projet = 1 livre (voir 6.2)
publier:
  - fichier: docs/GUIDE-UTILISATEUR.md
    page: "Guide utilisateur"
    chapitre: "Utilisation"
  - fichier: docs/PERMISSIONS.md
    page: "Rôles et permissions"
    chapitre: "Référence"
    genere_par: "python _local-dev/scripts/gen_permissions_md.py"   # ⚠ régénérer avant
```

Trois propriétés voulues :

- **liste blanche** — rien n'est publié qui ne soit nommé (§ 3.3) ;
- **le titre de page est décidé par le projet**, pas déduit du nom de fichier —
  « GUIDE-UTILISATEUR » n'est pas un titre de page de wiki ;
- **`genere_par` rend le problème des docs générés visible** : la passerelle
  peut refuser de publier un fichier généré si le dépôt est en retard sur son
  générateur.

### 6.2 Côté wiki — un livre par projet

**Un projet = un livre**, dont le nom est la **marque**, pas le dossier.
C'est déjà un piège connu du workspace : `GED-LOCAL` (dossier) ≠ **Matothèque**
(marque) ≠ `docflow-*` (images) — c'est écrit dans la mémoire du projet.

Cette règle règle aussi une collision qui arriverait sans elle : Sapyn publie
par **titre de page unique dans un livre**. Deux projets ayant chacun un
`CONTRIBUTING.md` dans un livre commun s'écraseraient mutuellement, en silence.

| Niveau BookStack | Contenu | Exemple |
|---|---|---|
| Étagère | le monde / la famille | `Projets AgestiTC` |
| **Livre** | **un projet, par sa marque** | `Sapyn`, `Matothèque`, `NetSight` |
| Chapitre | la nature du document | `Utilisation`, `Référence`, `Exploitation` |
| Page | le titre lisible | `Guide utilisateur`, `Déploiement Synology` |

### 6.3 Marquer les pages publiées automatiquement

Sapyn le fait déjà, à garder et à généraliser : un bandeau en tête de page,
« publiée automatiquement depuis le dépôt X, toute modification ici sera
écrasée ». Sans lui, quelqu'un édite la page dans le wiki et perd son travail à
la publication suivante — sans comprendre pourquoi.

---

## 7. Faisabilité, par lot

| Lot | Contenu | Faisabilité | Dépend de |
|---|---|---|---|
| ~~0~~ | ~~Jeton d'écriture dédié Sapyn~~ | ❌ **abandonné** (décision 26/08) | — |
| **1** | Table `publications` dans GED-LOCAL | ✅ facile | déjà spécifiée au Lot 2 de `PLAN-bookstak.md` |
| **2** | Authentification entrante de l'API GED-LOCAL | ⚠️ **prérequis de sécurité** | à concevoir (jeton par projet, en base, haché) |
| **3** | Endpoint passerelle `POST /api/wiki-publish` | ✅ facile | réutilise `ensure_book` / `ensure_chapter` / `update_page` livrés |
| **4** | Convention `.claude/wiki.yml` + propagation par `_modele` | ✅ moyen | le mécanisme `propagate` existe |
| **5** | Étagères (Lot 1b GED-LOCAL) | ✅ moyen | API BookStack dispo, spec déjà écrite |
| **6** | Étape « publier la doc » dans le flux de release de chaque projet | ✅ moyen | après le lot 4 |
| — | *Scan des dépôts par GED-LOCAL* | ❌ **non recommandé** | § 3.1 et § 3.2 |

**Le chemin critique est donc 1 → 2 → 3, puis 4 et 5.** Rien n'est publié
avant le lot 3. Le lot 2 (authentification) est le seul qui demande une vraie
conception ; les autres réutilisent du code déjà écrit.

**Ordre conseillé** — le lot 1 avant le 3, même si le 3 est plus visible : sans
la table `publications`, la passerelle republierait en créant des doublons au
lieu de mettre à jour, et il faudrait nettoyer le wiki à la main.

Le script de Sapyn n'est pas perdu pour autant : au lot 5, il change d'URL
cible (la passerelle au lieu de BookStack) et garde tout le reste — parcours
des `docs/`, bandeau d'avertissement, mode simulation par défaut.

---

## 8. Ce que je ne recommande pas, et pourquoi

- **Le scan des dépôts par GED-LOCAL** — les fichiers ne sont pas visibles
  depuis le conteneur, et un scan ne peut pas distinguer un document généré à
  jour d'un document généré périmé.
- **Le dossier « à publier » comme mécanisme principal** — séduisant parce que
  la surveillance existe déjà, mais il **coupe le lien avec la source**. Un
  fichier déposé est une *copie* : plus de régénération, plus de trace du
  commit d'origine, et deux vérités possibles dès la première divergence. Bon
  candidat en revanche pour du **hors-dépôt** (schémas, procédures manuelles,
  captures) — un usage complémentaire, pas le socle.
- **Réutiliser le jeton de GED-LOCAL depuis Sapyn** — la question initiale. La
  passerelle donne exactement ce qui était cherché (un seul jeton) **sans** le
  copier dans un second projet.

---

## 9. Ce qui reste à trancher

Les trois grandes décisions sont prises (§ 0). Restent des points de
conception, à traiter au moment du lot concerné :

1. **Comment authentifier les projets auprès de la passerelle** (lot 2) — un
   jeton par projet, stocké haché côté Matothèque, semble le plus simple ; à
   confirmer au moment de le faire.
2. **Que fait la passerelle d'un document généré périmé** (§ 3.2) — refuser, ou
   publier en avertissant ? Refuser est plus sûr, mais bloque une publication
   pour une raison que l'appelant ne comprendra peut-être pas.
3. **Qui crée les livres** — la passerelle à la volée (`ensure_book` existe), ou
   une création manuelle préalable dans le wiki ? La création automatique est
   pratique, mais une faute de frappe dans un manifeste créerait un livre
   fantôme.
4. **Où ce plan est référencé** : il vit désormais dans ce dépôt. Un renvoi
   d'une ligne depuis `_modele/PLAN-commun.md` serait utile pour qu'on le
   retrouve depuis le workspace — à ajouter **depuis la session `_modele/`**,
   seule habilitée à éditer ce fichier.

Et un point sans rapport avec le plan, mais trouvé en l'écrivant :
**`../PLAN-bookstak.md` ligne 62 contient un `token_id` BookStack en
clair**, dans un fichier versionné. Ce n'est pas le secret, mais la règle du
workspace est « aucun secret en clair » — à regarder indépendamment.

---

## Annexe — sources vérifiées

| Fait | Où | Vérifié le |
|---|---|---|
| BookStack en écriture, helpers idempotents | `backend/services/bookstack_service.py` | 2026-08-26 |
| Compte `Support-matotheque`, Editor + API | `../PLAN-bookstak.md` § 4 | 2026-08-26 |
| Table `publications` non faite | `../PLAN-bookstak.md` § 6 | 2026-08-26 |
| Surveillance de dossiers livrée, `.md` non indexé | `backend/routers/folders.py` | 2026-08-26 |
| Pas d'authentification entrante | recherche sur `backend/` — aucune garde sur les routers | 2026-08-26 |
| Publieur Sapyn idempotent par titre | `sapyn/_local-dev/scripts/push_docs_bookstack.py` | 2026-08-26 |
| Mécanisme de propagation | `_modele/_modele-claude/PROPAGER.md`, `VERSION` 0.5.0 *(hors dépôt)* | 2026-08-26 |
| BookStack = outil du monde AgestiTC | `_modele/PLAN-commun.md` § 1 *(hors dépôt)* | 2026-08-26 |
| Sapyn sur le NAS, GED-LOCAL sur C: | chemins observés en session | 2026-08-26 |

---

## Décisions de conception — VERROUILLÉES (2026-08-26, validées Thomas via session Matothèque)

> Tranche les 3 points ouverts du § 9. Design prêt à coder. Ordre : **Lot 1 → Lot 2 → Lot 3**.

**① Auth entrante = jeton PAR PROJET, stocké HACHÉ.** Table `projets_publieurs`. Le projet envoie son
jeton en en-tête ; Matothèque le hache et retrouve le projet → révocation + attribution par projet,
aucun secret partagé. **Auth uniquement sur les endpoints de publication** (le reste de l'API,
isolé réseau, est un chantier distinct). Le **jeton porte les livres autorisés** (lien avec ③).

**② Doc périmé = publier + dédup + avertir.** On stocke un **hash de contenu** + un **horodatage de
génération** dans `publications`. Même hash → **no-op** (pas de republication). Horodatage plus ancien
que la version publiée → **avertissement** dans la réponse + log, **mais on publie** (le projet reste
responsable de sa fraîcheur ; on ne bloque pas une republication légitime).

**③ Création des livres = à la volée, BORNÉE à une liste blanche.** `ensure_book` n'est appelé que si
le livre demandé figure dans `projets_publieurs.livres_autorises` du projet appelant. Livre non déclaré
→ **403, jamais de livre fantôme**.

**Impératif — exclusion MIS/Geco par le CODE :** seul un projet **enregistré et actif** peut publier
(un projet MIS/Geco n'est jamais enregistré) ; garde explicite en plus si le nom matche un motif MIS/Geco.

### Schéma (Lot 1 + Lot 2)

```sql
-- Lot 2 : registre des projets autorisés à publier (auth + périmètre)
CREATE TABLE projets_publieurs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nom TEXT NOT NULL UNIQUE,               -- ex. « sapyn »
    token_hash TEXT NOT NULL,               -- SHA-256 du jeton (jeton montré UNE fois à la création)
    livres_autorises TEXT[] NOT NULL DEFAULT '{}',  -- liste blanche pour ensure_book (③)
    actif BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_used_at TIMESTAMPTZ
);

-- Lot 1 : une ligne par document logique d'un projet → l'update vise la MÊME page (pas de doublon)
CREATE TABLE publications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    projet TEXT NOT NULL,                    -- projets_publieurs.nom
    cle TEXT NOT NULL,                       -- identifiant logique du doc chez le projet (slug/chemin)
    livre TEXT NOT NULL,
    chapitre TEXT,
    page_id INTEGER,                         -- id de page BookStack (renseigné à la 1ʳᵉ publication)
    url TEXT,
    contenu_hash TEXT NOT NULL,              -- sha256(markdown) → dédup (②)
    genere_le TIMESTAMPTZ,                   -- horodatage de génération fourni par le projet (②)
    published_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (projet, cle)
);
```

### ④ Protocole = MANIFESTE (le projet déclare son arbre complet) — validé 2026-08-26

Le projet **pousse** sa doc (Matothèque ne scanne jamais) ; quand sa doc évolue (nouveau chapitre,
pages ajoutées/retirées), il **renvoie son arbre courant** et la passerelle **rapproche**.

### Contrat de l'endpoint (Lot 3)

`POST /api/passerelle/publish` — **authentifié** (en-tête `Authorization: Bearer <jeton_projet>`).

Corps = **manifeste** : `{ pages: [ { cle, livre, chapitre?, titre, markdown, genere_le? }, … ] }`. Déroulé :

1. **Auth** : hache le jeton → projet actif, sinon **401**. `last_used_at = now()`.
2. **Périmètre** : projet enregistré (⇒ AgestiTC) ; garde explicite anti-MIS/Geco.
3. **Autorisation livres** : TOUT `livre` du manifeste ∈ `projet.livres_autorises`, sinon **403** (rejet
   ATOMIQUE du manifeste, liste des livres non autorisés dans l'erreur — jamais de livre fantôme).
4. **Pour chaque page** : `h = sha256(markdown)`.
   - `publications(projet, cle)` existante, même hash → **inchangée** ;
   - existante, hash différent → **`update_page(page_id)`** (met à jour LA MÊME page) ; `genere_le` plus
     ancien que le publié → publié quand même **avec avertissement** ;
   - absente → `ensure_book(livre)` [borné] → `ensure_chapter(chapitre)` → **`create_page`**, on stocke
     `page_id`. Réutilise `bookstack_service.py`. Upsert `publications`.
5. **Rapprochement des retraits** : pages de `publications(projet)` **absentes du manifeste** →
   **signalées** comme « retirées » dans la réponse. **Pas de suppression d'office** (« non poussé » ≠
   « supprimer ») ; retrait effectif via un appel explicite (endpoint `DELETE` ou champ `supprimer:true`).
6. **Réponse** : récapitulatif `{ creees[], mises_a_jour[], inchangees[], retraits_candidats[], avertissements[] }`.

Endpoint admin séparé pour **générer un jeton projet** (montré une fois) + déclarer ses `livres_autorises`.

### Cycle de vie des modifications (résumé)

| Évolution côté projet | Comportement passerelle |
|---|---|
| **Page mise à jour** | `update_page(page_id)` sur la même page (dédup hash) — jamais de doublon |
| **Nouveau chapitre / page** | `ensure_chapter` + `create_page` (créés à la volée, livre borné à la liste blanche) |
| **Renommage / déplacement** (même `cle`) | met à jour titre / livre / chapitre de la page existante |
| **Page retirée** (absente du manifeste) | **signalée**, pas supprimée ; suppression explicite requise |
| **Livre supprimé dans BookStack** | recréé au prochain push (`ensure_book` idempotent par slug) |
| **Livre retiré des `livres_autorises`** | publications futures **refusées (403)** ; pages existantes conservées |

> **Édition manuelle d'une page dans BookStack** : le manifeste est **source de vérité** → une
> republication **écrase** l'édition manuelle (le contenu est généré). *Option future* : bandeau/tag
> « généré automatiquement — ne pas éditer » sur les pages gérées. **Point mineur laissé ouvert.**
