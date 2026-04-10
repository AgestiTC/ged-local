# Référence API — DocFlow AI

Base URL : `http://localhost:8000/api`

Documentation interactive : http://localhost:8000/api/docs (Swagger UI)

---

## Upload

### `POST /upload`
Upload un ou plusieurs fichiers.

**Body** : `multipart/form-data`
- `files` : liste de fichiers (PDF, DOCX, PPTX, PPSX, XLSX)

**Réponse** :
```json
{ "job_ids": ["uuid1", "uuid2"], "nb_fichiers": 2 }
```

### `POST /upload/zip`
Upload un ZIP → extraction automatique.

### `POST /upload/folder`
Upload un dossier entier (webkitdirectory).

---

## Documents

### `GET /documents`
Liste paginée des documents.

**Query params** :
- `page` (défaut: 1), `per_page` (défaut: 20)
- `statut` : pending | extracted | enriched | error
- `extension` : pdf, docx...
- `categorie` : filtre par catégorie IA

### `GET /documents/{id}`
Détail complet d'un document (+ métadonnées IA).

### `GET /documents/{id}/text`
Texte extrait brut.

### `GET /documents/{id}/versions`
Historique des versions.

### `DELETE /documents/{id}`
Supprime de l'index (pas le fichier source).

---

## Génération

### `POST /generate/report`
Génère un rapport libre.

**Body** :
```json
{
  "document_ids": ["uuid1", "uuid2"],
  "prompt": "Synthétise ces documents en rapport de direction",
  "model": "mixtral:latest",
  "output_format": "markdown"
}
```

### `GET /generate/stream/{job_id}`
Stream SSE du rapport en cours de génération.

**Format SSE** : `data: {"chunk": "texte...", "done": false}\n\n`

### `POST /generate/fill-template`
Remplit un template DOCX avec données extraites des documents.

---

## Recherche

### `GET /search`
Recherche hybride (défaut), full-text, ou sémantique.

**Query params** :
- `q` : requête (obligatoire)
- `type` : hybrid | text | semantic (défaut: hybrid)
- `categorie`, `tags`, `extension`, `date_debut`, `date_fin`
- `limit` (défaut: 20)

**Réponse** :
```json
{
  "results": [
    {
      "document": { "id": "...", "nom": "...", ... },
      "score": 0.87,
      "extrait": "...texte avec le terme recherché..."
    }
  ],
  "total": 42,
  "query": "votre recherche"
}
```

---

## Export

### `POST /export/pdf`
Convertit du Markdown en PDF.

**Body** : `{ "content": "# Rapport\n...", "title": "Mon rapport" }`

**Réponse** : Fichier PDF en stream, ou `{ "path": "/exports/rapport.pdf" }`

### `POST /export/docx`
Convertit du Markdown en DOCX.

---

## Dossiers surveillés

### `GET /folders`
Liste les dossiers configurés.

### `POST /folders`
Ajoute un dossier à surveiller.
```json
{
  "chemin": "C:/Documents/projets",
  "nom_affichage": "Projets",
  "recursive": true,
  "extensions_filtrees": ["pdf", "docx"]
}
```

### `POST /folders/{id}/scan`
Force un scan immédiat.

### `GET /folders/browse?path=C:/Documents`
Navigue dans le système de fichiers hôte.

---

## Santé

### `GET /health`
État de l'application et connectivité des services.
```json
{
  "status": "ok",
  "version": "0.2.0",
  "services": {
    "tika": "ok",
    "ollama": "ok",
    "database": "ok"
  }
}
```
