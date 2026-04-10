# Ajouter des documents — DocFlow AI

## Méthode 1 : Dossier surveillé (automatique)

Configurer un dossier dans `.env` :
```
DOCUMENTS_ROOT=C:/Users/User/Documents/mes-documents
```

Tous les fichiers dans ce dossier sont automatiquement détectés et indexés.

Via l'interface : Page **Paramètres** → Dossiers surveillés → Ajouter.

## Méthode 2 : Drag & Drop

Sur la **Page Rapports** ou **Page GED** :
- Glisser-déposer des fichiers directement dans la zone de dépôt
- Supporte : fichiers individuels, dossiers entiers, archives ZIP

## Méthode 3 : API

```bash
curl -X POST http://localhost:8000/api/upload \
  -F "files=@document.pdf" \
  -F "files=@rapport.docx"
```

## Formats supportés

| Format | Extension | Notes |
|--------|-----------|-------|
| PDF | .pdf | PDF textuels + PDF scannés (OCR via glm-ocr) |
| Word | .docx | Microsoft Word 2007+ |
| PowerPoint | .pptx, .ppsx | Microsoft PowerPoint 2007+ |
| Excel | .xlsx | Microsoft Excel 2007+ |
| Archives | .zip | Extraction automatique du contenu |

## TODO Phase 1

Fonctionnalité à implémenter. Ce guide sera complété.
