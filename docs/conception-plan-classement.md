# Conception — Le plan de classement (module Rangement)

> **Étape 8** du plan [rangement + mails](plan-integration-rangement-mails.md). Statut : **validé par
> Thomas le 13/11/2026** (décisions C1 à C8, § 1 et § 9). Aucune ligne de code ici : ce document dit *quoi* construire à
> l'étape 9 (plan, règles, propositions) et ce que l'étape 10 (ranger) en attend.
>
> Le plan de classement répond à une seule question : **« où devrait aller ce dossier ? »**. Il ne
> déplace rien. Ranger, c'est l'étape 10, par lots, avec aperçu et annulation.

## 1. Décisions de Thomas (13/11/2026)

| Réf | Question | Décision |
|---|---|---|
| C1 | Forme de l'arborescence cible | **Les partages Synology restent le 1er niveau** (droits, sauvegardes, Plex intacts). Le plan s'applique **à l'intérieur** des partages. Chaque membre garde `homes/<compte>` comme espace personnel. |
| C2 | Périmètre de départ | **`media` d'abord** (déjà inventorié), puis les autres partages, chacun monté en lecture seule dans le worker quand son tour vient. Le modèle est pensé pour tout le NAS dès maintenant. |
| C3 | Sort de l'écran *Réorganiser* | **Fusionné au plan de classement** (décision D9 par défaut). Ses propositions IA pour les documents de la GED deviennent des propositions du plan ; l'écran et `/organize/apply` + `/organize/undo` disparaissent à l'étape 10. |
| C4 | Rôle de l'IA | **L'IA propose, Thomas valide tout.** Les règles simples placent l'évident ; l'IA locale propose le reste (et l'album quand les étiquettes manquent, décision P4 du plan [partages NAS](plan-partages-nas.md)). Rien n'est retenu sans validation. |

## 2. Ce que le plan doit couvrir — l'existant

- **Le NAS est découpé en partages**, chacun avec son rôle (relevé du plan partages NAS) :
  `media` (films, séries… ; Plex), `music` (23 668 morceaux), `photo`, `homes/<compte>` (Tom,
  tclement, MLB, julie, admin), `Partage-Nas-Mato` (commun), plus des petits partages.
- **`media` aujourd'hui** (inventaire du 13/11) : `Series` 2,6 To, `Films` 1,3 To, `nas-media`
  994 Go (**un autre NAS** monté par le Synology, inventorié à part), `Dessins Animes` 375 Go,
  `spetacle` 135 Go, `Documentaires`, `Film_neveux`, `DVD`, `Ebook`, `01_Liste`, `01.tmp-torrent`.
- **La GED** indexe `homes`, `music`, `photo`, `Partage-Nas-Mato` (283 000 fiches), **pas** `media`.
- ***Réorganiser*** propose, pour les documents de la GED, un dossier par **catégorie IA** (avec
  sous-dossier par année) dans un plan **virtuel** (`reorg_plan`, une ligne par document), éditable
  par glisser-déposer. Son application physique est coupée depuis la v1.141.1.

## 3. La forme cible, partage par partage

Le plan est une **arborescence par partage**. Les noms de 1er niveau d'un partage peuvent être
**verrouillés** (jamais proposés au renommage) quand un autre logiciel en dépend.

| Partage | Forme cible proposée | Pourquoi |
|---|---|---|
| `media` | **Les dossiers actuels restent** (`Films`, `Series`, `Dessins Animes`, `Documentaires`, `Ebook`…), verrouillés ; ajout de `00-A-TRIER`. Le plan range ce qui est **mal placé** (un film dans `Series`, un fichier isolé à la racine, `01.tmp-torrent`) plutôt que de renommer. | **Plex** lit ces dossiers par leur nom : les renommer casserait ses bibliothèques (question C5). |
| `Partage-Nas-Mato` (commun) | Le modèle numéroté de rangement : `00-A-TRIER`, `10-ADMINISTRATIF` (Banque, Impôts, Santé, Logement, Assurances, Véhicules, Emploi — par année quand c'est utile), `20-FAMILLE`, `40-PRO`, `50-LOGICIELS`, `60-PROJETS`, `90-ARCHIVES`. | Le seul endroit où rien ne dépend des noms actuels. |
| `photo` | `Photos/{année}/` (date de prise de vue, sinon date du fichier). | La règle la plus demandée du cahier de rangement. |
| `music` | `{Artiste}/{Année} - {Album}/{piste} - {Titre}.{ext}` à partir des **étiquettes** ; l'IA propose l'album quand elles manquent ou se contredisent (P4). | Décision P4 : renommer d'après les albums. |
| `homes/<compte>` | Espace **personnel** : aucun plan imposé. Plus tard, chacun pourra se donner le sien (espaces perso repoussés, D5). | La vie privée de chacun. |

`nas-media` (l'autre NAS) a **son propre plan** le jour où on s'en occupe : un déplacement entre
les deux NAS est une copie réseau suivie d'une suppression (noté pour l'étape 10).

## 4. Le modèle de données (étape 9)

Trois tables, dans la base de Matothèque (SQL brut comme les tables `inv_*`, PostgreSQL seulement) :

**`plan_noeuds`** — l'arborescence cible.

| Colonne | Rôle |
|---|---|
| `id`, `parent_id` | l'arbre |
| `partage` | `media`, `music`… (1er niveau, jamais créé par le plan) |
| `nom`, `chemin` | `10-ADMINISTRATIF/Impôts` ; `chemin` calculé, unique par partage |
| `modele` | facultatif : un gabarit de sous-dossier (`{année}`, `{artiste}/{album}`) |
| `verrouille` | nom intouchable (ex. `media/Films`, à cause de Plex) |
| `origine` | `modele` (modèle de départ), `humain`, `ia` (proposé puis validé) |
| `description` | ce qu'on y met — sert aussi d'indication à l'IA |

**`plan_regles`** — où va quoi, explicitement. Évaluées **dans l'ordre de priorité** ; la première qui
répond gagne.

| Type de règle | Exemple |
|---|---|
| `famille` (types de fichiers de la carte) | Logiciels → `Partage-Nas-Mato/50-LOGICIELS` |
| `extension` | `.iso`, `.img` → `50-LOGICIELS/Images disque` |
| `motif_nom` / `motif_chemin` | `*facture*` → `10-ADMINISTRATIF` |
| `categorie_ged` (reprise de *Réorganiser*) | catégorie IA « Impôts » → `10-ADMINISTRATIF/Impôts/{année}` |
| `etiquette_musique` | morceau étiqueté → `music/{artiste}/{année} - {album}` |

Chaque règle a : `cible_noeud_id` (+ gabarit), `priorite`, `active`, `origine`, et **qui l'a validée,
quand**. Une règle proposée par l'IA reste inactive tant qu'elle n'est pas validée.

**`plan_propositions`** — une ligne par **dossier** (ou fichier isolé) à placer.

| Colonne | Rôle |
|---|---|
| `objet` | une entrée d'inventaire (`inv_entrees.id`) ou une fiche de la GED (`documents.id`) |
| `destination` | chemin cible complet calculé (nœud + gabarit appliqué) |
| `par` | la règle qui l'a produite, ou `ia` (avec `raison` et `confiance`) |
| `statut` | `proposee` → `validee` / `refusee` → (étape 10) `rangee` |
| `valide_par`, `valide_le` | trace de la décision humaine |

`reorg_plan` (une ligne par document) **migre** dans `plan_propositions` à l'étape 9 ; la table est
retirée à l'étape 10 avec *Réorganiser*.

## 5. L'unité qu'on place : le dossier, pas le fichier

- On place d'abord les **grands dossiers** (1er et 2e niveau de la carte), puis les **fichiers
  isolés** qui traînent. Un dossier placé part **entier** : on ne découpe pas un album, une saison,
  un projet. C'est ce qui rend 15 To rangeables à la main.
- Un dossier déjà **au bon endroit** (sous le nœud que le plan lui donnerait) n'est pas proposé.
- Ce que rien ne place va dans `00-A-TRIER` du partage — jamais ailleurs « par défaut ».

## 6. Comment une proposition naît — règles d'abord, IA ensuite

```
carte (inventaire) ──► règles actives, par priorité ──► proposition « par règle »
         │                       │ aucune ne répond
         │                       ▼
         └──────────────► IA locale (usage « classement_plan ») ──► proposition « ia »
                                                                        │
                                       Thomas valide / corrige / refuse ◄┘
                                                    │
                                                    ▼
                                   (étape 10) un lot rangé, avec aperçu et annulation
```

- **Ce que l'IA reçoit** : seulement des **métadonnées** — nom et chemin du dossier, familles de
  types et volumes (la carte), quelques noms de sous-dossiers ; pour un document de la GED, sa
  catégorie IA. **Jamais le contenu** des fichiers. Modèle local (`runtime_config.model_for`).
- **Ce qu'elle rend** : `{destination, raison, confiance}` en JSON, **choisie parmi les nœuds du
  plan** ; si aucun ne convient, elle peut proposer un **nouveau nœud**, marqué comme tel et soumis
  à validation comme le reste.
- **Apprendre des validations** : quand Thomas valide plusieurs propositions IA de la même forme,
  l'outil propose d'en faire une **règle** (« les dossiers `*.iso` vont toujours là ? »). Une règle
  ne s'active qu'avec son accord. Le cahier de rangement écarte le rangement automatique ; on
  rediscutera « si une règle a été validée N fois sans correction ».
- **Musique (P4)** : la règle `etiquette_musique` propose renommage **et** emplacement ; l'étape 10
  les applique en **deux opérations distinctes** (renommer, puis déplacer), sinon la GED verrait un
  fichier supprimé et un nouveau, et ré-extrairait tout.

## 7. Les écrans (étape 9)

Un onglet **« Plan de classement »** dans la page *Rangement* :

1. **L'arbre du plan**, par partage : ajouter, renommer, déplacer un nœud (glisser-déposer repris de
   *Réorganiser*) ; nœuds verrouillés signalés.
2. **Les règles**, dans leur ordre : activer, réordonner, tester (« cette règle placerait 312 dossiers »).
3. **Les propositions**, grand dossier par grand dossier : *d'où → où*, par quelle règle ou pourquoi
   l'IA ; **Valider / Corriger / Refuser**, une par une ou toutes celles d'une même règle.
4. Sur la **Carte**, chaque dossier dit **où il irait** (critère d'acceptation de l'étape 9).

*Réorganiser* reste en place jusqu'à l'étape 10, avec un bandeau qui renvoie au plan.

## 8. Garde-fous

- Rien n'est appliqué à l'étape 9 : le plan **propose** seulement.
- Exclusions verrouillées de l'inventaire (`@eaDir`, `#recycle`, sauvegardes PBS…) jamais proposées.
- `homes/<compte>` : jamais de proposition sans demande de son propriétaire.
- Une proposition dont le dossier a changé depuis (taille, date, disparu) **se périme** et redevient
  à recalculer.
- IA locale uniquement ; aucune donnée ne sort.

## 9. Décisions complémentaires (Thomas, 13/11/2026)

| Réf | Question | Décision |
|---|---|---|
| C5 | `media` : que faire des dossiers de 1er niveau que Plex lit par leur nom ? | **Noms gardés et verrouillés.** On ajoute `00-A-TRIER` ; le plan ne range que ce qui est mal placé. |
| C6 | `01.tmp-torrent` et `01_Liste` ? | **Les deux à ranger** : ils entrent dans le plan comme le reste (pas d'exclusion particulière). |
| C7 | Le modèle numéroté de `Partage-Nas-Mato` ? | **Tel quel au départ** ; il s'ajuste ensuite dans l'écran du plan. |
| C8 | Ordre des partages après `media` ? | **`Partage-Nas-Mato`, puis `photo`, puis `music` (P4), `homes` en dernier.** Chaque partage est monté en lecture seule dans le worker à son tour. |

## 10. Ce que l'étape 9 livrera

Tables § 4 · modèle de départ chargé (nœuds § 3) · moteur de règles · propositions IA (usage
`classement_plan`) · onglet « Plan de classement » § 7 · « où irait ce dossier » sur la Carte ·
migration de `reorg_plan`. **Acceptation** (plan rangement) : pour chaque grand dossier de la carte,
l'outil dit où il irait ; aucune proposition n'est appliquée sans validation.
