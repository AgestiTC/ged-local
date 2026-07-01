# Plan détaillé — « Forcer l'analyse » d'un média / doc sans texte (fetch SMB, **sans doublon**)

> Statut : **planifié** (01/07/2026). Fait suite au retour utilisateur : « Forcer l'analyse »
> sur un média SMB renvoie « fichier distant ou introuvable localement ».
> Décision : **on part sur le fetch SMB** — mais **fetch temporaire éphémère + mise à jour du
> document existant** (⚠️ **aucun téléchargement conservé, aucun doublon** — contrainte forte
> de l'utilisateur).

## 1. Problème

- Les **médias** (image/audio/vidéo) du NAS sont **catalogués sans contenu**
  (`statut='catalogued'`, `texte_extrait` vide) — « indexation média raisonnée ».
- **151 documents `extracted` ont aussi un `texte_extrait` VIDE** (extraction Tika sans texte,
  typiquement PDF scannés) → « Relancer l'IA » ne peut rien faire (rien à analyser).
- L'actuel « Forcer l'analyse » appelle `POST /extract/{id}` qui lit un **chemin local**
  (`Path(chemin).exists()`), donc **échoue** pour `smb://…` (fichier non monté dans le conteneur).

## 2. Objectif

Un seul mécanisme durable **« Analyser le contenu »** qui, pour un document **sans texte**
(média catalogué **ou** doc extrait vide), **local ou SMB** :

1. récupère le fichier (chemin local, ou **fetch SMB → fichier temporaire**),
2. extrait le contenu (Tika ; puis OCR/vision en phase 2),
3. **met à jour le document EXISTANT** (résumé, catégorie, tags, texte, embeddings),
4. **supprime le fichier temporaire**.

### ⚠️ Garanties anti-doublon (non négociables)

- **Aucune nouvelle ligne `documents`** : on **UPDATE** la ligne existante (par `id`),
  on ne passe **pas** par `process_file` (qui crée un nouveau doc + déduplique par hash).
- **Aucun fichier conservé** : `fetch_to_temp` écrit dans `/tmp`, on **`os.unlink`** dans un
  `finally`. Le NAS reste la seule copie.
- Le **hash** du doc passe du pseudo-hash (chemin+taille) au **vrai SHA256 du contenu** une fois
  analysé → permet à la purge de doublons de fonctionner ensuite.

## 3. Architecture

### 3.1 Nouveau service — `ExtractionService.analyze_existing(doc, file_path, db)`

Réutilise la logique de `process_file` **mais sur un doc déjà en base** :

```
async def analyze_existing(self, doc, file_path, db, *, force_ocr=False):
    # 1. (option) recalcul du vrai hash SHA256 du contenu  (asyncio.to_thread)
    # 2. Tika : metadata_list = await self.tika.extract_metadata(file_path)
    #           texte = metadata.pop("X-TIKA:content", "")
    # 3. si média image ET texte vide ET phase 2 activée → OCR (glm-ocr) / vision (llava)
    # 4. doc.texte_extrait = texte ; doc.tika_metadata = metadata ;
    #    doc.hash_sha256 = vrai_hash ; doc.taille_octets = taille ;
    #    doc.statut = 'extracted' ; doc.date_derniere_extraction = now()
    # 5. await self._enrich(doc, texte, db)  → statut 'enriched' si ok
    # 6. embeddings (chunks) — comme process_file
    # 7. commit
```

### 3.2 Résolution du fichier — helper `_resoudre_fichier(doc, db)`

- **Local** : `chemin` est un chemin filesystem → retourne `(Path(chemin), cleanup=noop)`.
- **SMB** (`chemin` commence par `smb://`) :
  1. Parse `smb://{hote}/{partage}/{rel}`.
  2. Retrouve la **Source SMB** par `hote` (type='smb'), déchiffre `secret_chiffre`.
     (si plusieurs sources même hôte → prendre celle dont un partage indexé matche ; sinon 1re.)
  3. `tmp = await smb_service.fetch_to_temp(hote, partage, rel, identifiant, secret, domaine)`.
  4. retourne `(Path(tmp), cleanup=lambda: os.unlink(tmp))`.
- Si aucune source/creds → erreur claire « source SMB introuvable pour cet hôte ».

### 3.3 Nouveau job durable — type `analyze` (handler dans `job_handlers.py`)

```
@register("analyze")
async def handler_analyze(ctx):
    doc = get(document_id)
    file_path, cleanup = await _resoudre_fichier(doc, db)   # fetch SMB → tmp si besoin
    try:
        await ctx.report(30, "Extraction du contenu…")
        await service.analyze_existing(doc, file_path, db, force_ocr=ctx.parametres.get("ocr"))
    finally:
        cleanup()                                           # ⚠️ suppression du tmp
    return {"statut": doc.statut, "document_id": str(doc.id)}
```

- Progression : 15 (résolution) → 30 (fetch) → 60 (Tika/OCR) → 85 (IA) → 100.
- **Secret SMB déchiffré à l'exécution** depuis la Source (jamais dans les params du job —
  même règle que l'indexation).

### 3.4 Endpoints

- `POST /api/documents/{id}/analyze` → enqueue job `analyze` (remplace, pour les médias/vides,
  l'appel à `/extract/{id}`). Renvoie `{job_id, statut}`.
- **Bulk** `POST /api/documents/analyze-batch?scope=media|empty|all&limit=N` :
  met en file un job `analyze` par doc concerné. `scope` :
  - `empty` : docs `statut IN (extracted,error)` **avec `texte_extrait` vide** (les 151),
  - `media` : `statut='catalogued'` (optionnel : filtrer images seules),
  - `all` : les deux.

### 3.5 Frontend

- **Fiche** (`DocumentCard`) : le bouton « Forcer l'analyse » (média) **et** un bouton
  « Analyser le contenu » sur un doc extrait **sans texte** → `documentsApi.analyze(id)` + `suivreJob`.
- **Paramètres → Maintenance** : reformuler l'action groupée. Aujourd'hui « Relancer l'IA (152) »
  est **trompeur** (ces 151 docs ont un texte vide → enrich inutile). Remplacer par :
  - « **Ré-analyser les documents sans texte (N)** » → `analyze-batch?scope=empty` (vraie ré-extraction),
  - garder « Relancer l'IA (N) » **uniquement** pour les docs **avec texte** non enrichis
    (compteur = vrais candidats, via un petit `GET /documents/reenrich-count`).

## 4. Correctifs liés (barre de progression sur gros lots)

Constat : le widget « Tâches » ne lit que les **20 jobs les plus récents** → sur un lot de 150,
les jobs **en cours** (les plus anciens) sortent de la fenêtre → **barre figée à 0 %**.

- `JobsIndicator` : afficher en priorité un job **`running`** (`actifs.find(running) ?? actifs[0]`)
  et un **agrégat** « X en cours / Y en file ».
- Backend `/api/jobs` : ajouter des **compteurs par statut** (ou un `GET /api/jobs/summary`)
  pour un agrégat fiable indépendant de la fenêtre de 20.

## 5. Phasage

- **Phase 1 (Tika)** : `analyze_existing` + `_resoudre_fichier` (local + SMB temp) + job `analyze`
  + endpoints unitaire & batch + fiche + reformulation Maintenance + correctif barre gros lots.
  → Suffisant pour **PDF scannés dont Tika/Tesseract extrait du texte** et documents distants.
- **Phase 2 (OCR/vision)** : router les **images** (et scans sans texte) vers **glm-ocr**
  (OCR) et **llava** (description) quand Tika ne rend rien. → nécessaire pour photos/scans purs.
  Rejoint le **connecteur Scanner** (import `Scans_Epson` du NAS).

## 6. Tests / validation

- Média **SMB** (image du NAS) → « Forcer l'analyse » : job `analyze` `pending→running→completed`,
  **tmp supprimé** (vérif `/tmp` vide), **doc mis à jour** (texte/hash/statut), **pas de nouveau doc**
  (count `documents` inchangé, juste l'existant modifié).
- Doc **extrait vide** local → « Analyser le contenu » : texte extrait si Tika le permet.
- **Batch** `scope=empty` sur les 151 → progression visible (agrégat), pas de figeage à 0 %.
- Purge doublons : le doc ré-analysé (vrai hash) est bien dédupliqué s'il existe en double.

## 7. Points d'attention

- **Concurrence Ollama** : un batch de 150 `analyze` = beaucoup d'appels IA → garder
  `CONCURRENCE=2` du worker, prévenir dans l'UI (« traitement en file, peut être long »).
- **Gros fichiers SMB** : `fetch_to_temp` télécharge tout le fichier en RAM/disque tmp →
  plafonner la taille (ex. skip > 200 Mo, message clair) pour les vidéos.
- **Sécurité** : secret SMB déchiffré à l'exécution, jamais loggé, jamais en params de job.
