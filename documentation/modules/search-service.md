# Module Recherche Hybride

**Fichier** : [backend/services/search_service.py](../../backend/services/search_service.py)

## Rôle

Combine deux méthodes de recherche pour des résultats pertinents :
1. **Full-text PostgreSQL** — pertinence lexicale exacte
2. **Sémantique pgvector** — pertinence contextuelle

## Modes de recherche

| Mode | Méthode | Usage |
|------|---------|-------|
| `text` | `to_tsvector` + `plainto_tsquery` | Termes exacts, noms propres |
| `semantic` | Cosine similarity pgvector | Concepts, synonymes, paraphrases |
| `hybrid` | Fusion des deux scores | Usage général (défaut) |

## Fusion des scores (Hybrid)

Méthode : **Reciprocal Rank Fusion (RRF)**

```
score_rrf(doc) = 1/(k + rank_text) + 1/(k + rank_semantic)
```

Où `k=60` est une constante empirique.

Avantage : robuste aux échelles différentes entre full-text et cosine similarity.

## Recherche sémantique — flux

```
Requête utilisateur : "rapport de gestion 2024"
    ↓
ollama.embed("rapport de gestion 2024", model="qwen3-embedding:8b")
    ↓
Vecteur requête [0.12, -0.34, ...] (4096 dims)
    ↓
SELECT chunk_text, 1-(embedding <=> query_vector) AS score
FROM embeddings ORDER BY score DESC LIMIT 50
    ↓
Dédupliqué par document_id (garder le meilleur score par document)
    ↓
Résultats fusionnés avec full-text
```

## TODO Phase 3

- [ ] Implémenter `search()` : full-text SQL
- [ ] Implémenter la partie sémantique (embed requête → pgvector)
- [ ] Implémenter la fusion RRF
- [ ] Ajouter les filtres (catégorie, tags, extension, date)
- [ ] Retourner l'extrait de contexte (highlight du terme trouvé)
