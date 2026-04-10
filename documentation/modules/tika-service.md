# Module Tika Service

**Fichier** : [backend/services/tika_service.py](../../backend/services/tika_service.py)

## Rôle

Client async pour Apache Tika Server. Extrait le texte et les métadonnées de tous les formats documentaires supportés.

## Endpoints Tika utilisés

| Endpoint | Usage |
|----------|-------|
| `PUT /tika` | Texte brut uniquement |
| `PUT /rmeta/text` | Texte + métadonnées (JSON) |

## Formats supportés

PDF, DOCX, PPTX, PPSX, XLSX, ZIP (et beaucoup d'autres via Tika)

## Cas particulier : ZIP

Tika gère les ZIP nativement via `/rmeta` : il retourne **une liste** de dicts, un par fichier dans le ZIP. Chaque dict contient le texte et les métadonnées du fichier extrait.

## Retry automatique

3 tentatives avec backoff exponentiel (2s → 10s) via `tenacity`.

## Vérification de la dimension des embeddings

Avant de générer les embeddings en production :
```bash
curl -X POST http://localhost:11434/api/embeddings \
  -d '{"model":"qwen3-embedding:8b","prompt":"test"}' | python3 -c \
  "import sys,json; data=json.load(sys.stdin); print('Dimension:', len(data['embedding']))"
```

Si différent de 4096, adapter :
1. `scripts/init-db.sql` : `vector(4096)` → `vector(<N>)`
2. `backend/models/embedding.py` : `Vector(4096)` → `Vector(<N>)`
3. `.env` : `EMBEDDING_DIMENSION=<N>`

## Métadonnées Tika importantes

```json
{
  "X-TIKA:content": "texte extrait...",
  "Content-Type": "application/pdf",
  "dc:creator": "Auteur",
  "Creation-Date": "2024-01-15",
  "xmpTPg:NPages": "12",
  "Content-Length": "245678"
}
```

## TODO Phase 1

- [ ] Tester avec chaque format (PDF, DOCX, PPTX, XLSX, ZIP)
- [ ] Gérer les PDF scannés (texte vide → fallback OCR avec glm-ocr)
- [ ] Injecter via `Depends()` dans les routers FastAPI
