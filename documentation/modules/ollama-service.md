# Module Ollama Service

**Fichier** : [backend/services/ollama_service.py](../../backend/services/ollama_service.py)

## Rôle

Client async pour Ollama. Deux usages distincts :
1. **Génération LLM** — rapports, enrichissement, remplissage templates
2. **Embeddings** — vecteurs pour la recherche sémantique

## Modèles disponibles

| Modèle | Taille | Usage dans le projet |
|--------|--------|---------------------|
| `mixtral:latest` | 26 GB | Rapport principal, raisonnement complexe |
| `llama3.1:latest` | 4.9 GB | Alternative plus rapide |
| `mistral:latest` | 4.4 GB | Enrichissement IA (catégorie/tags) |
| `glm-ocr:latest` | 2.2 GB | OCR PDF scannés |
| `qwen3-embedding:8b` | 4.7 GB | Embeddings principal |
| `nomic-embed-text:latest` | 274 MB | Embeddings fallback |

## Attention : gestion mémoire

**Ne jamais lancer embeddings et génération en parallèle.**
Mixtral seul occupe 26 GB de RAM/VRAM. La table `jobs` gère la file d'attente.

## Génération streaming (SSE)

```python
async for chunk in ollama.generate_stream(prompt, model="mixtral:latest"):
    # Envoyer chunk au frontend via SSE
    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
```

## Timeout configuré

- Timeout standard : 300 secondes (5 min) pour Mixtral sur gros documents
- Configurable via `OLLAMA_TIMEOUT_MS` dans `.env`

## TODO Phase 1

- [ ] Tester `generate()` avec mistral et mixtral
- [ ] Tester `embed()` avec qwen3-embedding:8b — vérifier la dimension retournée
- [ ] Implémenter fallback embedding (qwen3 → nomic-embed-text)
- [ ] Injecter via `Depends()` dans les routers
