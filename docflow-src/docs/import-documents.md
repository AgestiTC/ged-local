# Import de documents — DocFlow AI

## Formats supportés

| Extension | Type | Notes |
|-----------|------|-------|
| `.pdf` | PDF | Texte natif ou OCR via Tika |
| `.docx` | Word | Texte + métadonnées Office |
| `.pptx` / `.ppsx` | PowerPoint | Texte de chaque diapositive |
| `.xlsx` | Excel | Texte des cellules |
| `.odt` / `.ods` / `.odp` | LibreOffice | Formats Open Document |
| `.zip` | Archive | Extraction automatique du contenu |

---

## Méthodes d'import

### 1. Drag & drop de fichiers individuels

Glissez un ou plusieurs fichiers directement sur la zone de dépôt dans la page **Rapports**.

- Feedback visuel immédiat (bordure bleue animée)
- Upload simultané de plusieurs fichiers
- Rejet automatique des formats non supportés (message d'erreur)

### 2. Drag & drop d'un dossier entier

Glissez un dossier depuis l'explorateur de fichiers sur la zone de dépôt.

**Comportement :**
- Tous les fichiers du dossier sont uploadés en un seul lot
- Le **nom du dossier devient automatiquement un tag** appliqué à tous les fichiers
- Les sous-dossiers sont inclus (récursion automatique)

**Exemple :**
```
OFFRE_MASSON/
  ├── CV_Jean_Martin.pdf       → tag : OFFRE_MASSON
  ├── lettre_motivation.docx   → tag : OFFRE_MASSON
  └── references.zip           → tag : OFFRE_MASSON
```

Ce tag de dossier est appliqué **immédiatement** à l'import, avant même l'enrichissement IA. Il sera conservé et fusionné avec les tags générés par l'IA lors de l'enrichissement.

### 3. Upload d'une archive ZIP

Un fichier `.zip` est automatiquement décompressé côté serveur. Chaque fichier extrait est traité individuellement.

### 4. Dossiers surveillés (n8n)

Des dossiers peuvent être configurés en surveillance automatique via la page **Paramètres → Dossiers surveillés**. Tout nouveau fichier déposé dans un dossier surveillé est automatiquement importé.

---

## Pipeline de traitement après import

```
Fichier reçu
   │
   ├─ Calcul SHA256
   │     └─ Si hash déjà connu → doublon ignoré (ou nouvelle version)
   │
   ├─ Sauvegarde dans storage/uploads/
   │
   ├─ Création en DB (statut = pending)
   │     └─ Si folder_tag → MetadonneeIA créée immédiatement avec le tag dossier
   │
   ├─ Extraction Tika (statut = extracted)
   │     └─ Texte brut + métadonnées (auteur, date, langue détectée…)
   │
   ├─ Enrichissement IA — mistral (statut = enriched)
   │     └─ catégorie, sous-catégorie, tags, résumé, entités, mots-clés
   │        Les tags IA sont fusionnés avec le tag dossier (dossier en premier)
   │
   └─ Embeddings — qwen3-embedding:8b
         └─ Découpage en chunks de 500 tokens (overlap 50)
            Vecteurs stockés dans pgvector
```

---

## Statuts de traitement

| Statut | Signification |
|--------|---------------|
| `pending` | Fichier reçu, en attente d'extraction |
| `extracted` | Texte extrait par Tika, enrichissement IA en attente |
| `enriched` | Traitement complet, prêt pour la recherche et les rapports |
| `error` | Erreur à l'une des étapes (détail disponible dans la fiche document) |

---

## Gestion des doublons

- Chaque fichier est identifié par son **hash SHA256**
- Si un fichier identique est importé deux fois, la deuxième entrée est ignorée
- Si le même fichier est modifié puis réimporté, une **nouvelle version** est créée

Pour nettoyer manuellement les doublons : `POST /api/documents/purge-duplicates`

---

## Tags de dossier et groupes automatiques

Quand des fichiers sont importés depuis un dossier, le nom du dossier devient leur tag commun. Dans le mode **Comparatif** de la page Rapports, le bouton **"Charger les groupes depuis les dossiers importés"** lit ces tags et crée automatiquement un groupe par dossier.

Voir [rapport-comparatif.md](rapport-comparatif.md) pour le détail du mode comparatif.
