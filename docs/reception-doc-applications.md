# Déposer la documentation d'une application dans la Matothèque

> Convention à suivre par **toute application** qui veut que sa documentation soit rangée, versionnée
> et consultable dans la Matothèque. Décision du 2026-11-16 : **aucune interconnexion entre
> applications** — l'application dépose un fichier, c'est tout. Plan d'origine :
> [plan-reception-doc-applications.md](plan-reception-doc-applications.md).

## 1. Où déposer

```text
\\NAS-MATO\Partage-Nas-Mato\[GED]\Docs-applications\
    <appli>\                    un sous-dossier par application : minuscules, chiffres, tirets
        <nom-stable>.md         ou .pdf — TOUJOURS LE MÊME NOM d'une release à l'autre
```

- Si le nom `NAS-MATO` ne se résout pas depuis le poste, utiliser l'adresse :
  `\\192.168.42.200\Partage-Nas-Mato\[GED]\Docs-applications\` (constaté le 2026-11-16).
- **Même nom = nouvelle version** du même document dans la Matothèque (historique gardé, texte des
  5 dernières versions relisible). Un nouveau nom crée un **autre** document.
- Le nom du sous-dossier devient un **tag** (`composeur-yealink`).
- Retirer un fichier ne l'efface pas de la GED : il passe « absent » (historique conservé).

## 2. En-tête recommandé (Markdown)

En **tout début** de fichier, uniquement des lignes `clé: valeur` :

```markdown
---
appli: composeur-yealink
version: 1.5.18
titre: Guide du Composeur Yealink T54W
---
```

- `titre` → nom affiché dans la page « Doc des applis » ;
- `version` → version affichée, et libellé de la version dans l'historique ;
- `appli` → tag supplémentaire.
- L'en-tête est retiré du texte indexé. Absent ou mal formé : il est ignoré, le fichier est quand
  même importé.

## 3. Comment déposer — sans aucun secret

- **Une simple copie de fichier**, faite avec la **session Windows** de la personne qui publie (elle
  a le droit d'écriture sur le dossier). Exemple PowerShell :

  ```powershell
  $dest = '\\NAS-MATO\Partage-Nas-Mato\[GED]\Docs-applications\mon-appli'
  New-Item -ItemType Directory -Force -LiteralPath $dest | Out-Null
  Copy-Item -LiteralPath .\doc\guide.md -Destination (Join-Path $dest 'guide-mon-appli.md') -Force
  ```

- **Jamais** d'identifiant, de mot de passe ou de jeton dans le script ou le dépôt de l'application.
- Le dépôt est pris en compte au **cycle de synchronisation suivant** (15 min).

## 4. Côté Matothèque (administrateur, une seule fois)

| Réglage | Où | Valeur |
|---|---|---|
| Droits DSM | DSM › Dossier partagé `Partage-Nas-Mato` › `[GED]\Docs-applications` | **lecture** `svc-ged` ; **écriture** pour les comptes qui publient |
| 1. Règle de classement | Paramètres › Sources & indexation › Règles de classement | « Docs des applications », dossier `\\192.168.42.200\Partage-Nas-Mato\[GED]\Docs-applications`, catégorie `Documentation` › `Applications`, tag `doc-appli`, « Ajouter le nom du sous-dossier en tag », classement **fixe** |
| 2. Source SMB | Paramètres › Sources & indexation › Sources de fichiers | hôte `192.168.42.200`, dossier `Partage-Nas-Mato/[GED]/Docs-applications`, identifiant **`svc-ged`**, mot de passe saisi dans l'écran (**stocké chiffré**, jamais dans un fichier), synchro 15 min |

- ⚠️ **Même hôte dans la Source et dans la règle** : les documents sont enregistrés sous
  `smb://<hôte de la Source>/…`. Une Source déclarée avec `NAS-MATO` et une règle écrite avec
  `192.168.42.200` ne se rencontrent jamais (la règle ne s'applique pas).
- Changer de compte de lecture = modifier la **Source** dans les Paramètres (rien à coder).
- La règle « fixe » garantit que l'IA ne reclasse pas la doc à chaque version.
- Les règles ne reclassent pas l'existant : créer la **règle (1) avant la Source (2)**, sinon le premier
  import échappe au classement fixe (il serait rattrapé à la version suivante ou par « Relancer l'IA »).

## 5. Vérifier

1. Déposer le fichier, attendre la synchro (ou « Synchroniser » sur la Source).
2. Menu **Doc des applis** : l'application apparaît avec son titre, sa version et la date du dépôt.
3. Redéposer une version modifiée (même nom) : « 2 versions », l'ancienne est relisible depuis
   **historique**.

## 6. Publier dans BookStack : le dépôt `manifeste.json` du cockpit (16/11/2026)

Même dossier, autre usage : le **cockpit** (`gestion-projet-appli`) ne parle jamais à BookStack. Il
dépose `Docs-applications/<projet>/manifeste.json` (format `cockpit-docs/1`, contrat complet :
`docs/17-docs-ged.md` du cockpit), et la Matothèque le **publie dans BookStack** par sa passerelle
(`services/docs_cockpit.py`, relevé toutes les 15 min, ou *Paramètres › Passerelle › Relever les dépôts
maintenant*).

| Situation | Ce que fait la Matothèque | Dans le dossier du projet |
|---|---|---|
| Publié | pages créées / mises à jour (même clé = même page), étagère, bandeau | `resultat.json` (livres + liens, nombre de pages), manifeste **retiré** |
| Refusé (projet non déclaré, livre hors liste blanche, MIS/Geco, manifeste invalide) | rien n'est publié | `erreur.json` (`code`, `message`), manifeste **retiré** : corriger puis redéposer |
| BookStack non configuré / injoignable | rien n'est publié | `erreur.json` (`statut: en_attente`), manifeste **gardé** : repris au relevé suivant |

- Seul `manifeste.json` est lu ; `manifeste.json.part` (écriture en cours) est ignoré. Un manifeste
  remplacé pendant le traitement n'est pas effacé : il passe au relevé suivant.
- Une copie de chaque manifeste traité est gardée côté Matothèque (`storage/docs-cockpit/<projet>/`).
- Les `.json` ne sont pas des extensions indexées : la Source GED ne les voit pas.
- **Prérequis** : la Source SMB du § 4 (compte `svc-ged`, avec **lecture + suppression** dans DSM) et le
  projet **déclaré** dans *Paramètres › Passerelle de publication* (même nom que le dossier, livres
  autorisés). Le jeton créé à cette occasion ne sert pas au cockpit.

## 7. Proposer une modification d'une page publiée (16/11/2026)

Une page publiée par le cockpit **ne se corrige pas dans BookStack** : le dépôt suivant écraserait la
retouche. Dans **GED › Wiki › Liste des livres**, une telle page porte un bouton **« Proposer une
modification »** (tous les utilisateurs) : on modifie le Markdown (sans le bandeau), on dit pourquoi, et
la Matothèque dépose la proposition **pour le cockpit**, avec son **auteur** (session SSO) :

`Docs-applications/<projet>/propositions/<clé>-<AAAAMMJJTHHMMSS>Z.json`, format `cockpit-docs-proposition/1` :

| Champ | Contenu |
|---|---|
| `projet`, `cle`, `livre`, `chapitre`, `titre` | la page visée (`cle` = fichier du projet sans `.md`) |
| `page_id`, `page_url` | la page dans BookStack |
| `hash_publie` | empreinte du contenu publié au moment de la proposition (si le `.md` a changé depuis, `markdown_avant` n'est plus le texte du projet : à revoir, pas à appliquer tel quel) |
| `auteur` | `{identifiant, nom, email}` de la session (identifiant = compte DSM via le SSO) |
| `propose_le` | ISO 8601 UTC |
| `commentaire` | le « pourquoi » (2 000 caractères au plus) |
| `markdown_avant`, `markdown_propose` | le texte publié (sans bandeau) et le texte proposé (1 Mo au plus) |

Le cockpit liste ces fichiers sur la fiche projet (avant / après, auteur), **applique** (écrit le `.md`
dans le projet) ou **refuse**, et retire le fichier dans les deux cas. Le dépôt suivant republie la page.
Le bouton n'apparaît que sur les pages d'un projet déjà déposé par le cockpit (les autres projets de la
passerelle — sapyn, foulée — ne lisent pas ce dossier).

### 7 ter. Compte rendu du cockpit (v1.195.0)

Le cockpit retire la proposition qu'il a appliquée **ou** refusée : ce retrait seul ne dit pas laquelle des
deux. Après sa décision, il dépose donc :

`Docs-applications/<projet>/propositions/decisions/<nom de la proposition>.json`, format `cockpit-docs-decision/1` :

| Champ | Contenu |
|---|---|
| `format` | `cockpit-docs-decision/1` |
| `proposition` | le **nom du fichier** de la proposition, tel qu'il était déposé (`docs-guide-usage-20261116T153650Z.json`), sans dossier |
| `decision` | `appliquee` ou `refusee` |
| `par` | qui a décidé (identifiant ou nom, facultatif) |
| `le` | ISO 8601 (facultatif — sinon l'heure du relevé) |
| `motif` | facultatif (500 caractères au plus), surtout pour un refus |

Au relevé (toutes les 15 min, avec les manifestes), la Matothèque passe la proposition de « Transmise au
cockpit » à « Appliquée » ou « Refusée » (« décidé par `<par>` (cockpit) »), puis **retire le fichier**. Un
fichier illisible, qui ne correspond à aucune proposition, ou qui vise une proposition déjà close est aussi
retiré, sans rien changer. Écrire le fichier sous un nom provisoire puis le renommer en `.json` (seuls les
`.json` sont lus). Ce compte rendu est facultatif : sans lui, la proposition reste « Transmise ».

### 7 bis. Toutes les pages du wiki (v1.194.0)

Le bouton existe désormais sur **toutes** les pages, pas seulement celles du cockpit. Qui applique dépend
de l'origine de la page (décisions de Thomas du 16/11 : les administrateurs valident, une page HTML est
convertie en Markdown) :

| Page | Statut de la proposition | Qui applique |
|---|---|---|
| écrite dans BookStack | « À valider » | un **administrateur**, dans *Wiki › Liste des livres › Propositions* : « Appliquer » écrit la page dans BookStack avec l'étiquette **« Modifiée via la Matothèque »** (proposé par X, validé par Y, date). Si la page a changé depuis, la Matothèque prévient avant d'écraser. |
| publiée par le cockpit | « Transmise au cockpit » | le cockpit (§ 7) |
| publiée par un projet à jeton (sapyn, foulée) | « À reporter dans le projet » | à la main dans le projet, puis « Reportée » (jamais écrite dans BookStack : l'envoi suivant l'écraserait) |

Toutes les propositions sont gardées en base (`propositions_wiki`), avec leur auteur et leur décision.

