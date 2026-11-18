# Plan — Recevoir la documentation des autres applications

> **État au 18/11/2026** : **livré** v1.191.0 → v1.195.0, réglages faits (16/11) ; propositions de correction (v1.193/v1.194) et compte rendu du cockpit (v1.195.0, cockpit 0.8.40). Reste : l'essai de bout en bout par Thomas.

> Décidé le 2026-11-16 avec Thomas : « on arrête de multiplier les interconnexions entre applications ».
> **Principe : une application ne parle à personne pour publier sa doc. Elle DÉPOSE un fichier dans
> un dossier du NAS ; la Matothèque le ramasse, le classe et le versionne.** Aucun jeton, aucune API,
> aucun appel réseau côté application. Premier client : le Composeur Yealink (dépôt `yearlink composer`,
> guide `doc/livre-composeur-yealink.md`), qui cesse de publier vers BookStack.

> **État au 2026-11-16 (v1.191.0)** : étapes 1 à 4 **livrées** (code + tests) ; étape 0 = réglages à
> saisir dans la DSM et la Matothèque (voir [reception-doc-applications.md](reception-doc-applications.md)) ;
> étape 5 faite côté composeur (dépôt `yearlink composer`).

## Problème

Chaque application maintient aujourd'hui son propre lien vers la doc (script + jeton BookStack par
projet — jeton révoqué le 2026-08-25 après fuite). Ça fait autant de secrets et de points de casse
que d'applications.

## Ce qui existe déjà (relevé du 2026-11-16)

- **Sources SMB synchronisées** (`models/source.py:23-50`, planificateur `job_worker.py:780,842-905`,
  tic de 5 min) : ajout → pipeline complet ; **fichier modifié (même chemin, autre empreinte) → nouvelle
  VERSION du même document** (`extraction.py:569-607`) ; renommé → chemin suivi ; supprimé → `absent`.
  C'est exactement le mécanisme voulu : **aucun code n'est nécessaire pour l'étape 0**.
- `.md` et `.pdf` acceptés (`folder_watcher.py:25-41`), texte extrait par Tika et indexé.
- Les anciens « dossiers surveillés » (`/api/folders`) ne sont **pas** scannés en prod (FolderWatcher jamais
  instancié, n8n absent) → **ne pas** les utiliser.

## Ce qui manque

1. **Classement fixe** : l'IA reclasse chaque document, et `_update_version` (`extraction.py:731-770`)
   **efface catégorie et tags à chaque nouvelle version** → la doc d'une appli changerait de rangement
   à chaque release. Le seul précédent de classement fixe est `ScanProfil` (`models/scan.py:50-74`,
   `classement = fixe | ia_confirme`).
2. **Contenu des anciennes versions** : seule l'empreinte de l'ancienne version est gardée
   (`chemin_archive` jamais renseigné) → impossible de relire la doc de la version N-1.
3. **Visibilité** : rien ne montre « quelles applis ont déposé leur doc, quelle version, quand ».

## Convention de dépôt (contrat avec les applications)

```
\\NAS-MATO\Partage-Nas-Mato\[GED]\Docs-applications\      (existe, vérifié le 2026-11-16)
    <appli>\                       un sous-dossier par application (minuscules, tirets)
        <nom-stable>.md | .pdf     MÊME NOM à chaque release → nouvelle version, pas un doublon
```

En-tête facultatif en tête des `.md` (front-matter YAML), lu à l'étape 3 :

```yaml
---
appli: composeur-yealink
version: 1.5.18
titre: Guide du Composeur Yealink T54W
---
```

## Règle des secrets (décision du 2026-11-16)

**Aucun secret dans un fichier** (code, config, script, `.env` versionné, doc). Quand un secret est
indispensable, il vit dans la base, **chiffré** (Fernet, `services/crypto.py`) ou **haché** s'il n'a
qu'à être vérifié (cf. jetons de la passerelle), et se saisit / se change **dans les Paramètres**.

- Compte de lecture de la zone de dépôt : **`svc-ged`**, porté par la **Source SMB** de la Matothèque
  (`sources.identifiant` + `sources.secret_chiffre`, chiffré Fernet ; modifiable dans l'écran Sources,
  `PUT /api/sources/{id}`). Changer de compte = une modification dans les Paramètres, pas de code.
- Côté applications : **aucun identifiant** — le dépôt est une copie de fichier faite avec la session
  Windows du poste (droit d'écriture accordé sur le NAS), jamais avec un mot de passe écrit dans un script.

## Étape 0 — Zone de dépôt et Source SMB (configuration, sans code)

- Dossier : `\\NAS-MATO\Partage-Nas-Mato\[GED]\Docs-applications\` (existe). Droits DSM : **lecture**
  pour `svc-ged`, **écriture** pour le compte Windows qui dépose (PC de dev).
- Matothèque → Paramètres → Sources : créer une **Source SMB** « Docs des applications »
  (hôte `192.168.42.200`, chemin `Partage-Nas-Mato/[GED]/Docs-applications`, identifiant `svc-ged`,
  mot de passe saisi dans l'écran → stocké chiffré), synchronisation activée (15 min).
- Rédiger `docs/reception-doc-applications.md` (la convention ci-dessus + la règle des secrets, pour les
  autres projets).

**Acceptation** : un `.md` déposé apparaît dans la GED en ≤ 1 cycle de synchro ; le redéposer modifié
crée une version 2 du **même** document (pas un nouveau document).

## Étape 1 — Règles de classement par dossier

- Nouveau modèle `RegleClassement` : `prefixe_chemin` (ex. `smb://…/Docs-applications/`),
  `categorie`, `sous_categorie`, `tags` (liste), `tag_depuis_sous_dossier` (bool : le nom du sous-dossier
  `<appli>` devient un tag), `classement` (`fixe` | `ia` — `ia` : posé à l'import puis reclassé par
  l'IA ; le `ia_confirme` de `ScanProfil` n'a pas été repris, faute d'écran de confirmation), `actif`.
- Application dans le pipeline d'import (`sync_service.py:225-243` → `extraction.py`) : la règle au
  préfixe le plus long l'emporte ; en `fixe`, l'IA ne touche ni à la catégorie ni aux tags (résumé et
  plongements restent calculés).
- Écran Paramètres : liste / ajout / suppression des règles.

**Acceptation** : un document sous le préfixe reçoit catégorie et tags de la règle (+ tag `<appli>`) ;
hors préfixe, comportement inchangé ; tests unitaires sur la sélection du préfixe le plus long.

## Étape 2 — Versions : garder le classement et le contenu précédent

- `_update_version` : si le document relève d'une règle `fixe`, **conserver** catégorie et tags au lieu
  de les effacer.
- Archiver le contenu de la version remplacée (`chemin_archive` dans `storage/`), borné aux **5
  dernières** versions par document ; purge des plus anciennes.

**Acceptation** : après 3 dépôts successifs, catégorie/tags inchangés, 3 entrées dans `versions`, les
2 anciennes relisibles ; la 7ᵉ version purge l'archive la plus ancienne.

## Étape 3 — En-tête des fichiers Markdown

- À l'extraction d'un `.md`, lire le front-matter YAML (`appli`, `version`, `titre`) : `titre` → titre
  du document, `appli` → tag, `version` → libellé enregistré sur la version (`versions`) ; en-tête
  absent ou invalide → ignoré sans erreur. Le front-matter est retiré du texte indexé.

**Acceptation** : un `.md` avec en-tête affiche son titre et sa version dans la GED ; sans en-tête, rien
ne change ; un YAML invalide n'interrompt pas l'import (journal seulement).

## Étape 4 — Page « Documentation des applications »

- API `GET /api/doc-applications` : par sous-dossier `<appli>` du préfixe des règles concernées,
  documents, dernière version (libellé + date), nombre de versions, statut (`absent` si retiré).
- Frontend : page listant les applis, lien vers chaque document et son historique de versions.

**Acceptation** : le Composeur Yealink apparaît avec son guide, sa version 1.5.18 et la date du dépôt ;
une appli sans dépôt depuis 90 jours est signalée.

## Étape 5 — Bascule du Composeur Yealink (dépôt `yearlink composer`)

- Remplacer `doc/publier-bookstack.js` par une simple copie du guide vers
  `\\NAS-MATO\Partage-Nas-Mato\[GED]\Docs-applications\composeur-yealink\guide-composeur-yealink.md`
  (script `doc/deposer-doc.ps1`, destination en paramètre avec ce chemin par défaut ; **aucun
  identifiant** : la copie utilise la session Windows), et ajouter le front-matter au guide.
- Mettre à jour `doc/README.md`, ROADMAP du composeur ; archiver le livre BookStack 186 (à la main).

**Acceptation** : plus aucune référence à l'API BookStack dans le dépôt du composeur ; le dépôt du guide
crée/actualise le document dans la Matothèque (étapes 0-4).

## Hors périmètre

- Publication vers BookStack (la passerelle wiki existante reste telle quelle pour ceux qui l'utilisent ;
  elle n'est pas étendue).
- Toute API ou jeton côté application ; les anciens « dossiers surveillés » `/api/folders`.
- Rendu Markdown riche dans la visionneuse (à évaluer séparément si besoin).
