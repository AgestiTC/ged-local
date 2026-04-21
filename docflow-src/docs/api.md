# Référence API — DocFlow AI

Base URL : `http://NAS:8000/api`

---

## Upload & Extraction

### POST /upload

Upload un ou plusieurs fichiers. Déclenche l'extraction en arrière-plan.

**Content-Type :** `multipart/form-data`

| Champ | Type | Description |
|-------|------|-------------|
| `files` | File[] | Fichiers à uploader (PDF, DOCX, PPTX, PPSX, XLSX, ODT, ODS, ODP, ZIP) |
| `folder_tag` | string | (optionnel) Tag à appliquer à tous les fichiers (nom du dossier source) |

**Réponse 200 :**
```json
{
  "jobs": [
    {"fichier": "cv.pdf", "job_id": "uuid", "statut": "en_attente"},
    {"fichier": "bad.txt", "statut": "rejeté", "raison": "Extension .txt non supportée"}
  ]
}
```

### POST /upload/zip

Upload d'un fichier ZIP → extraction automatique de chaque fichier contenu.

**Content-Type :** `multipart/form-data`  
**Champ :** `file` (UploadFile)

**Réponse 200 :**
```json
{"fichier": "archive.zip", "job_id": "uuid", "statut": "en_attente"}
```

---

## Documents

### GET /documents

Liste paginée des documents avec filtres.

**Paramètres query :**
| Param | Type | Description |
|-------|------|-------------|
| `page` | int | Page (défaut : 1) |
| `page_size` | int | Résultats par page, max 100 (défaut : 20) |
| `statut` | string | `pending` / `extracted` / `enriched` / `error` |
| `extension` | string | `pdf`, `docx`… |
| `source` | string | `watch` / `upload` / `drag_drop` |
| `q` | string | Recherche dans le nom |
| `tag` | string | Filtrer par tag exact |

**Réponse :**
```json
{
  "total": 42,
  "page": 1,
  "page_size": 20,
  "pages": 3,
  "documents": [
    {
      "id": "uuid",
      "nom": "rapport.pdf",
      "extension": "pdf",
      "taille_octets": 204800,
      "statut": "enriched",
      "source": "upload",
      "date_import": "2024-11-15T10:23:00Z",
      "tags": ["RH", "OFFRE_MARTIN"]
    }
  ]
}
```

### GET /documents/stats

Statistiques globales sur les documents.

**Réponse :**
```json
{
  "total": 156,
  "par_statut": {"enriched": 148, "extracted": 5, "pending": 2, "error": 1},
  "taille_totale_octets": 524288000,
  "top_categories": [
    {"categorie": "Ressources humaines", "nb": 45},
    {"categorie": "Finance", "nb": 32}
  ]
}
```

### GET /documents/{id}

Détail complet d'un document.

### GET /documents/{id}/text

Texte brut extrait par Tika.

**Réponse :**
```json
{"document_id": "uuid", "nom": "rapport.pdf", "texte": "...", "nb_caracteres": 12500}
```

### GET /documents/{id}/metadata

Métadonnées IA enrichies.

**Réponse :**
```json
{
  "categorie": "Finance",
  "sous_categorie": "Rapport annuel",
  "tags": ["finance", "2024", "BILAN"],
  "resume": "Rapport financier annuel de l'exercice 2024...",
  "langue": "fr",
  "entites": {
    "personnes": ["Jean Dupont"],
    "organisations": ["Entreprise XYZ"],
    "dates": ["2024-12-31"],
    "lieux": ["Paris"]
  },
  "mots_cles": ["chiffre d'affaires", "résultat net", "EBITDA"],
  "niveau_confidentialite": "confidentiel"
}
```

### PATCH /documents/{id}/metadata

Mise à jour partielle des métadonnées IA.

**Body :**
```json
{
  "tags": ["RH", "CV", "senior"],
  "categorie": "Ressources humaines",
  "resume": "Résumé corrigé manuellement.",
  "niveau_confidentialite": "confidentiel",
  "mots_cles": ["Python", "FastAPI"]
}
```

Seuls les champs fournis sont mis à jour.

### GET /documents/{id}/versions

Historique des versions détectées.

### GET /documents/{id}/jobs

Jobs d'extraction/enrichissement associés au document.

### DELETE /documents/{id}

Supprime le document de l'index (DB + embeddings + métadonnées en cascade). Le fichier source n'est pas supprimé.

### POST /documents/purge-duplicates

Supprime les doublons (même hash SHA256 ou même chemin). Conserve le document le mieux enrichi.

**Réponse :**
```json
{"supprimes": 3, "message": "3 doublon(s) supprimé(s)"}
```

---

## Recherche

### GET /search

Recherche dans les documents indexés.

**Paramètres query :**
| Param | Type | Description |
|-------|------|-------------|
| `q` | string | Requête (obligatoire) |
| `type` | string | `hybrid` (défaut) / `text` / `semantic` |
| `limit` | int | Résultats max (défaut : 20, max : 100) |
| `offset` | int | Décalage pour pagination |
| `categorie` | string | Filtrer par catégorie |
| `extension` | string | Filtrer par extension |

**Stratégie hybride :** `score = 0.4 × score_texte + 0.6 × score_sémantique`

### GET /search/tags

Tous les tags avec leur fréquence.

**Réponse :**
```json
{"total": 25, "tags": [{"tag": "RH", "nb_documents": 12}, ...]}
```

### GET /search/categories

Toutes les catégories avec leur fréquence.

---

## Génération de rapports

### POST /generate/report

Génère un rapport libre à partir de documents sélectionnés.

**Body :**
```json
{
  "document_ids": ["uuid1", "uuid2"],
  "prompt": "Rédige une synthèse des compétences présentées.",
  "model": "mixtral:latest",
  "output_format": "markdown"
}
```

### POST /generate/fill-template

Remplit un template DOCX avec les données extraites des documents.

**Body :**
```json
{
  "document_ids": ["uuid1"],
  "template_id": "uuid-template",
  "instructions": "Sois concis.",
  "model": "mistral:latest"
}
```

### POST /generate/compare

Lance un rapport comparatif multi-groupes → Excel.

**Body :**
```json
{
  "groupes": [
    {"nom": "OFFRE_MASSON", "document_ids": ["uuid1", "uuid2"]},
    {"nom": "OFFRE_DUPONT", "document_ids": ["uuid3"]}
  ],
  "template_id": "uuid-template-xlsx",
  "model": "mistral:latest",
  "instructions": "Sois synthétique."
}
```

**Réponse 202 :**
```json
{
  "job_id": "uuid",
  "statut": "en_attente",
  "nb_groupes": 2,
  "colonnes": ["Nom", "Expérience", "Compétences"],
  "stream_url": "/api/generate/compare/stream/{job_id}"
}
```

### GET /generate/compare/stream/{job_id}

Flux SSE de progression (text/event-stream).

**Événements :**
```
data: {"groupe": "OFFRE_MASSON", "statut": "running", "index": 1, "total": 2}
data: {"groupe": "OFFRE_MASSON", "statut": "done", "index": 1, "total": 2}
data: {"statut": "complete", "download_url": "/api/generate/compare/download/{job_id}"}
```

### GET /generate/compare/download/{job_id}

Télécharge le fichier Excel généré.

---

## Templates

### GET /templates

Liste tous les templates disponibles.

### POST /templates

Upload d'un template DOCX ou XLSX. Les champs sont détectés automatiquement.

**Content-Type :** `multipart/form-data`  
**Champ :** `file`

### GET /templates/{id}

Détail d'un template avec la liste des champs détectés.

### DELETE /templates/{id}

Supprime le template (DB + fichier disque).

---

## Dossiers surveillés

### GET /folders

Liste les dossiers configurés en surveillance.

### POST /folders

Ajoute un dossier à surveiller.

**Body :**
```json
{
  "chemin": "/mnt/documents/offres",
  "nom_affichage": "Dossier Offres",
  "recursive": true,
  "extensions_filtrees": ["pdf", "docx"],
  "intervalle_scan_secondes": 300
}
```

### POST /folders/{id}/scan

Force un scan immédiat du dossier.

### DELETE /folders/{id}

Retire le dossier de la surveillance.

---

## Prompts pré-enregistrés

### GET /prompts

Liste tous les prompts sauvegardés.

### POST /prompts

Crée un nouveau prompt.

**Body :**
```json
{
  "nom": "Synthèse RH",
  "description": "Synthèse des compétences d'un candidat",
  "prompt_text": "Rédige une fiche synthèse du candidat en 5 points clés...",
  "categorie": "rapport",
  "modele_prefere": "mixtral:latest"
}
```

### PUT /prompts/{id}

Modifie un prompt existant.

### DELETE /prompts/{id}

Supprime un prompt.

---

## Export

### POST /export/pdf

Convertit du contenu Markdown en fichier PDF.

**Body :** `{"content": "# Rapport\n...", "title": "Mon rapport"}`

### POST /export/docx

Convertit du contenu Markdown en fichier DOCX.

---

## Codes de retour HTTP

| Code | Signification |
|------|---------------|
| 200 | Succès |
| 201 | Créé |
| 202 | Accepté (traitement asynchrone) |
| 400 | Requête invalide (paramètre manquant, format incorrect) |
| 404 | Ressource non trouvée |
| 500 | Erreur serveur interne |
