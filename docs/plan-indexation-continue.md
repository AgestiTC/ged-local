# Plan — Réindexation & indexation continue

> **Origine** : retour user 17/07 — « les nouveaux dossiers / fichiers, ou ceux modifiés,
> n'apparaissent pas dans les arborescences de Matothèque ».
> Constat mesuré sur le corpus NAS (source `nas-mato TOM`, partage `Partage-Nas-Mato/[MaTo]`) :
> `01-bebe` (modifié le 16/07, soit **après** le dernier scan) → **0 document en base**.
>
> Statut : **plan** — cf. ROADMAP « Indexation continue ».

---

## 0. Diagnostic — pourquoi c'est normal aujourd'hui

L'arbre « Dossiers indexés » (`GET /sources/{id}/indexed`) est **dérivé de la table `documents`** :
un dossier n'apparaît que s'il contient **au moins un document indexé**. Ce n'est pas une vue du
système de fichiers. Donc :

| Cas | Comportement actuel | Correct ? |
|-----|--------------------|-----------|
| Dossier **sans extension indexable** (`DRIVER IMPRIMANTE HP`, `ligiciels` : `.exe`/`.inf`) | absent de l'arbre | ✅ voulu |
| Fichier **ajouté** après le dernier scan (`01-bebe`) | invisible **indéfiniment** | ❌ |
| Fichier **modifié** (contenu) | re-traité **seulement si on relance un scan** (le hash SHA256 change → détecté) | ⚠️ partiel |
| Fichier **supprimé** du NAS | **reste dans l'index** (fantôme) | ❌ |
| Fichier **déplacé/renommé** | apparaît en double (ancien chemin fantôme + nouveau) | ❌ |

**Cause racine** : l'indexation est **exclusivement manuelle** (bouton « Indexer » sur une source).
Aucun scan périodique n'existe. Les workflows n8n `folder-watcher`/`indexer` sont présents dans
`n8n/workflows/` mais **n'ont jamais été activés**.

---

## 1. Correctifs immédiats — réindexation manuelle utilisable

### 1a. Le bouton « Rafraîchir » ne fait pas ce qu'on croit — ✅ livré (17/07)

`IndexedSourcesSummary.chargerTout()` **relit les compteurs depuis l'index**. Il ne déclenche
**aucun scan du NAS**. Sans changement en base → aucun effet visible → « rien ne se passe ».

- **Livré** : libellé honnête **« Rafraîchir les compteurs »** + `title` explicite renvoyant vers la
  réindexation. Corrige l'attente, pas la fonction.
- **À faire (Phase 1)** : un vrai bouton **« Réindexer »** par source (relance le scan des dossiers
  déjà indexés, sans re-choisir les dossiers à la main).

### 1b. « Aucun partage » à l'exploration d'une source montée — ✅ livré (17/07)

**Deux bugs superposés** :

1. **Backend** (corrigé plus tôt) : `crypto.decrypt()` renvoie `""` **sans lever** quand la clé Fernet
   diffère (cas prod : clé rotée / index migré) → connexion SMB avec **mot de passe vide** → 0 partage,
   en silence. → garde `_secret_clair()` (`routers/sources.py`) qui lève un **HTTP 400 explicite**.
2. **Frontend** (corrigé 17/07) : `catch (e) { toast.error('Exploration impossible') }` **jetait le
   message du backend**. L'utilisateur voyait « Aucun partage (ou identifiants requis) », qui n'apprend
   rien. → helper **`extractApiError`** exporté depuis `api/index.ts`, utilisé par tous les `catch` de
   `SourcesManager` ; la cause s'affiche **dans le panneau** (bandeau rouge) avec un lien direct
   **« Modifier la source (re-saisir le mot de passe) »**.

> **Action utilisateur en prod** : la clé Fernet ayant été rotée, il faut **re-saisir le mot de passe
> du NAS** une fois (✏️ Modifier → champ mot de passe → Enregistrer). Le message le dit désormais.

---

## 2. Indexation continue (le vrai correctif)

### 2.1 Décision d'architecture : worker, pas n8n

| Option | Verdict |
|--------|---------|
| **Activer les workflows n8n** (`folder-watcher`/`indexer`) | ❌ ajoute une dépendance externe au chemin critique, duplique la logique d'indexation déjà dans le worker, et n8n ne connaît ni les sources SMB chiffrées ni les extensions configurables. |
| **Scan périodique incrémental dans le worker durable** | ✅ **retenu** — le worker existe déjà (`services/job_worker.py`, conteneur dédié), sait déchiffrer les secrets, réutilise `_index_smb`/`_index_local`, et la progression/annulation sont déjà branchées. |

### 2.2 Principe — un **diff** NAS ↔ index

Un job durable `sync_source` par source, qui **compare** l'état du partage à l'index et n'agit que
sur les écarts (jamais de ré-extraction complète) :

```
walk_files(source)  ──┐
                      ├─► diff par CHEMIN + (taille, date_modif) ─► 4 listes
SELECT chemin,        │
       hash, taille,  │
       date_modif ────┘
  FROM documents
 WHERE chemin LIKE '<prefixe source>%'
```

| Écart | Détection | Action |
|-------|-----------|--------|
| **Nouveau** | chemin absent de l'index | pipeline complet (extraction → IA → embeddings) |
| **Modifié** | chemin présent, **taille OU date_modif** différente → on recalcule le **hash** pour confirmer | re-extraction + ré-enrichissement + ré-embeddings ; nouvelle ligne `versions` |
| **Supprimé** | chemin en index, absent du walk | marquer `statut='absent'` (**pas** de suppression sèche) → purge validée par l'utilisateur |
| **Déplacé/renommé** | **hash identique**, chemin différent | **UPDATE du chemin** (zéro re-extraction, zéro doublon) |

> **Clé de perf** : ne comparer d'abord que `(taille, date_modif)` — métadonnées déjà renvoyées par le
> walk SMB. Le **hash n'est calculé que sur les candidats modifiés**, pas sur les 56 k fichiers.
> Le walk SMB reste le coût dominant (énumération réseau).

### 2.3 Ordonnancement

- Champ `Source.sync_intervalle_minutes` (0/`null` = désactivé) + `Source.dernier_sync`.
- Un **tick** dans le worker (toutes les N min) enfile un job `sync_source` pour chaque source dont
  `dernier_sync + intervalle < now()`.
- **Un seul sync par source à la fois** (verrou d'avis Postgres, comme la reprise des orphelins).
- Ne jamais lancer un sync pendant une indexation manuelle de la même source.

### 2.4 UI (Paramètres → Sources & indexation)

- Par source : **interrupteur « Synchro auto »** + intervalle (15 min / 1 h / 6 h / 24 h) +
  « Dernière synchro : … » + bouton **« Synchroniser maintenant »**.
- **Récap du dernier sync** : `+N nouveaux · ~M modifiés · −K absents · ↔P déplacés`.
- Les **absents** sont proposés à la purge (réversible), jamais supprimés d'office.

### 2.5 Phasage

| Phase | Contenu | Valeur | Statut |
|-------|---------|--------|--------|
| **1** | Bouton **« Réindexer »** par source (manuel, réutilise l'existant) + récap | débloque `01-bebe` **tout de suite** | ✅ 17/07 |
| **2** | Job `sync_source` + **diff** (nouveau/modifié/supprimé/déplacé), déclenché **à la demande** | le cœur, testable sans planificateur | ✅ **21/07 (v1.23.0)** |
| **3** | **Planification** (`sync_intervalle_minutes` + tick worker) + UI interrupteur | l'indexation devient continue | ✅ **21/07 (v1.24.0)** |
| **4** | Purge des **absents** + réconciliation des **déplacés** | l'index cesse de dériver | ⬜ (déplacés déjà traités en 2) |

### 2.7 Phase 2 — ce qui a réellement été livré (21/07)

`services/sync_service.py` (+ handler `sync_source`, `POST /sources/{id}/sync`, bouton
**« Synchroniser »**). **Mesure sur le NAS réel**, premier passage :

| Périmètre | Inchangés | Nouveaux | Modifiés | Absents | Déplacés |
|-----------|-----------|----------|----------|---------|----------|
| `/[03-W]` | 24 636 | 2 443 | 0 | 0 | 0 |
| `/[02-données]` | 26 274 | 8 016 | 0 | 0 | 0 |

**50 910 fichiers écartés sans transférer un octet** — l'ancienne indexation les rapatriait tous
en SMB (fetch → hash → « doublon » → jeté). Les 10 459 nouveaux sont ceux qui n'apparaissaient jamais.

Quatre décisions de robustesse, toutes motivées par un risque de **corruption de l'index** :

1. **Garde-fou « scan vide »** — si le walk ne renvoie rien alors que l'index est peuplé, la synchro
   **échoue** au lieu de marquer tout le corpus absent. Un partage démonté ou des droits perdus ne
   doivent jamais ressembler à une suppression massive.
2. **Dates héritées ignorées** — avant `chemin_logique`, les documents SMB portaient la date du
   *fichier temporaire* de rapatriement (≈ date d'import). Comparer dessus aurait reclassé **tout le
   corpus** en « modifié » au premier passage. On les détecte (`|mtime − import| < 5 min`) et on se
   rabat sur la taille. Vérifié en conditions réelles : `modifies=0`.
3. **Jokers SQL échappés** — `_` et `%` sont fréquents dans les noms de dossiers (`01_bebe`) et
   valent « n'importe quel caractère » dans un `LIKE` : non échappés, la photo de l'index déborde sur
   les dossiers voisins, qui passent alors pour « absents ».
4. **Appariement de déplacement strictement non ambigu** — (nom, taille) identiques, et **unique des
   deux côtés**. Deux homonymes de même taille restent un couple (nouveau + absent) plutôt qu'un
   mauvais rapprochement.

### 2.8 Phase 3 — planification (21/07)

Sélecteur **« Synchro auto »** par source (désactivée / 1 h / 6 h / 24 h), « dernière : il y a … »
et récap du dernier diff consigné en base. Un **tick worker toutes les 5 min** (`TICK_SYNC_S`)
regarde quelles sources sont dues — ce n'est pas l'intervalle des synchros, réglé par source.

- **Une source déjà occupée passe son tour** — un `sync_source` *ou* une `indexation` en attente/en
  cours sur la même source suffit à reporter : une synchro et une indexation manuelle se
  marcheraient dessus.
- `dernier_sync` est daté **à l'enfilement**, pas à la fin : un scan de 30 min ne provoque pas une
  rafale de re-planifications aux ticks suivants.
- `dernier_sync_recap` est écrit en **un seul UPDATE JSONB** (`|| jsonb_build_object(...)`), car
  deux périmètres de la même source peuvent se terminer simultanément (`CONCURRENCE=2`) — un
  read-modify-write en Python perdrait l'un des deux.

**Deux bugs bloquants découverts en développant cette phase** :

1. **`statut='absent'` violait la contrainte `CHECK`** de `documents` (`pending|extracted|enriched|
   error|catalogued`). La synchro aurait **planté en production à la première suppression de
   fichier sur le NAS** — invisible en développement, où le premier passage donnait `absents=0`.
2. **Verrou d'avis Postgres qui fuyait.** `pg_try_advisory_lock` puis `commit()` : le commit **rend
   la connexion au pool**, si bien que l'`unlock` du `finally` s'exécutait sur une **autre**
   connexion et ne libérait rien. Le verrou restait pris à vie (`pg_locks` le montrait tenu par une
   session `idle`). Deux conséquences : la planification renonçait **silencieusement** à chaque
   tick, et surtout la **reprise des jobs orphelins était sautée depuis toujours** — le worker
   annonçait « déléguée à un autre worker » alors qu'il n'y en avait aucun, d'où les jobs fantômes
   du 2 juillet qui bouchaient la file. Corrigé par `pg_try_advisory_xact_lock` (verrou
   **transactionnel**, libéré par le commit) ; la reprise signale enfin « nb=1 ».

**Bug de fond corrigé au passage** : `process_file` acceptait le chemin du *temporaire*, donc la
détection de version (« même chemin, contenu différent ») ne matchait **jamais** pour SMB — modifier
un fichier sur le NAS créait une **2ᵉ ligne au même chemin** au lieu d'une nouvelle version. Le
paramètre `chemin_logique` (+ `mtime_fichier`) corrige l'indexation **et** la synchro.

### 2.6 Points de vigilance

- **Le walk SMB n'est pas interruptible** (`walk_files` en thread) — déjà connu ; un sync long
  ne doit pas bloquer l'annulation → borner et rendre le walk annulable (recoupe le bug « arrêter
  une indexation »).
- **Ne pas réveiller Ollama** : un sync qui ne trouve aucun écart ne doit déclencher **aucun** appel IA.
- **Coût réseau** : un walk complet sur 56 k fichiers est lourd → intervalle par défaut **généreux**
  (6 h), et scan **par dossier indexé**, pas par partage entier.
- **100 % local** : SMB/LAN uniquement, aucune sortie Internet → pas de confirmation « Demandes Mise
  à jour internet » nécessaire.
