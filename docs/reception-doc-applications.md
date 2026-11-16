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
