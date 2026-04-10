# Module Pipeline d'Extraction

**Fichier** : [backend/services/extraction.py](../../backend/services/extraction.py)

## Rôle

Orchestre le traitement complet d'un fichier : de la réception jusqu'au stockage des embeddings.

## Flux détaillé

```
Fichier (chemin ou bytes uploadés)
│
├── 1. hash_utils.compute_sha256()
│   └── Si hash existe en DB → doublon détecté
│       ├── Même chemin → ignorer
│       └── Chemin différent → copie (signaler)
│
├── 2. INSERT INTO documents (statut='pending')
│
├── 3. tika_service.extract_metadata(file_path)
│   ├── Retourne liste de dicts (1 pour fichier normal, N pour ZIP)
│   └── Chaque dict : X-TIKA:content + métadonnées
│
├── 4. UPDATE documents SET texte_extrait=..., tika_metadata=..., statut='extracted'
│
├── 5. ollama_service.generate(prompt_enrichissement, model='mistral:latest')
│   └── Prompt système → retourne JSON {categorie, tags, resume, langue, entites}
│
├── 6. INSERT INTO metadonnees_ia
│
├── 7. chunker.chunk_text(texte_extrait, chunk_size=500, overlap=50)
│   └── N chunks
│
├── 8. Pour chaque chunk :
│   └── ollama_service.embed(chunk, model='qwen3-embedding:8b')
│       └── INSERT INTO embeddings (chunk_index, chunk_text, embedding)
│
└── 9. UPDATE documents SET statut='enriched'
```

## Prompt d'enrichissement

```
Analyse ce document et retourne UNIQUEMENT un objet JSON valide avec ces champs :
{
  "categorie": "catégorie principale du document",
  "sous_categorie": "sous-catégorie optionnelle",
  "tags": ["tag1", "tag2", "tag3"],
  "resume": "résumé en 3-5 phrases",
  "langue": "fr",
  "entites": {
    "personnes": [],
    "dates": [],
    "lieux": [],
    "organisations": []
  },
  "mots_cles": ["mot1", "mot2"]
}

Document :
{texte_extrait[:3000]}
```

## Gestion des erreurs

- Si Tika échoue → statut=error, erreur loguée
- Si Ollama enrichissement échoue → statut reste 'extracted' (pas bloquant)
- Si embedding échoue → retry 3 fois, puis log warning (pas bloquant)
- Pour les PDF scannés (texte vide) → TODO : fallback glm-ocr

## TODO Phase 1

- [ ] Implémenter `process_file()` complet
- [ ] Implémenter `process_zip()` (réutilise process_file() pour chaque entrée)
- [ ] Ajouter à la table `jobs` pour traçabilité
- [ ] Gérer le cas PDF scanné (texte extrait < 50 chars → OCR fallback)
