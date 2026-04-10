# Schéma de Base de Données — DocFlow AI

## PostgreSQL 16 + pgvector

### Extensions requises

```sql
CREATE EXTENSION vector;    -- Recherche sémantique (embeddings)
CREATE EXTENSION pg_trgm;   -- Full-text trigramme (recherche rapide)
CREATE EXTENSION "uuid-ossp"; -- Génération UUID
```

---

## Tables

### `documents` — Table principale

La table centrale. Un enregistrement = un fichier unique (identifié par son hash SHA256).

| Colonne | Type | Rôle |
|---------|------|------|
| `id` | UUID PK | Identifiant unique |
| `chemin` | TEXT | Chemin absolu sur le système de fichiers hôte |
| `nom` | TEXT | Nom du fichier |
| `extension` | TEXT | pdf, docx, pptx, xlsx... |
| `hash_sha256` | TEXT | Déduplication + détection de version |
| `texte_extrait` | TEXT | Texte brut extrait par Tika |
| `tika_metadata` | JSONB | Métadonnées brutes Tika (auteur, dates, nb pages...) |
| `statut` | TEXT | `pending` → `extracted` → `enriched` (ou `error`) |
| `source` | TEXT | `watch` \| `upload` \| `drag_drop` |

**Index** :
- `hash_sha256` — déduplication rapide
- `nom gin_trgm_ops` — recherche partielle sur le nom
- `texte_extrait` (to_tsvector french) — full-text en français

---

### `metadonnees_ia` — Enrichissement LLM

Résultat de l'analyse par Ollama. Relation 1-1 avec `documents`.

| Colonne | Type | Rôle |
|---------|------|------|
| `categorie` | TEXT | Catégorie principale (ex: "Contrat", "Rapport") |
| `tags` | TEXT[] | Tags libres extraits |
| `resume` | TEXT | Résumé auto-généré (3-5 phrases) |
| `langue` | TEXT | Code langue (fr, en...) |
| `entites` | JSONB | `{personnes:[], dates:[], lieux:[], organisations:[]}` |
| `modele_utilise` | TEXT | Nom du modèle Ollama utilisé |

---

### `embeddings` — Vecteurs pgvector

Un document est découpé en **chunks de 500 tokens** avec 50 tokens d'overlap.
Chaque chunk a son vecteur d'embedding.

| Colonne | Type | Rôle |
|---------|------|------|
| `chunk_index` | INTEGER | Index du chunk dans le document |
| `chunk_text` | TEXT | Texte du chunk |
| `embedding` | vector(4096) | Vecteur d'embedding (qwen3-embedding:8b) |

> **Attention** : dimension 4096 pour `qwen3-embedding:8b`. À vérifier au premier test.
> Si différent, adapter le `CREATE TABLE` et le modèle SQLAlchemy.

**Index** : IVFFlat cosine — créé manuellement après les premiers embeddings :
```sql
CREATE INDEX idx_embeddings_vector ON embeddings
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

---

### `versions` — Historique des modifications

Quand un fichier source change (nouveau hash), une version est créée.

---

### `jobs` — File d'attente

Évite le parallélisme LLM (Mixtral 26 GB). Une tâche à la fois.

Statuts : `pending` → `running` → `completed` (ou `failed`)

Types : `extraction`, `enrichissement`, `rapport`, `embedding`

---

### `dossiers_surveilles`

Dossiers à scanner périodiquement pour détecter les nouveaux fichiers.

---

## Requêtes utiles

```sql
-- Documents en attente d'extraction
SELECT id, nom, statut FROM documents WHERE statut = 'pending' ORDER BY date_import;

-- Recherche full-text en français
SELECT id, nom, ts_rank(to_tsvector('french', texte_extrait), query) AS rank
FROM documents, plainto_tsquery('french', 'votre recherche') query
WHERE to_tsvector('french', texte_extrait) @@ query
ORDER BY rank DESC;

-- Recherche sémantique (après avoir calculé l'embedding de la requête)
SELECT d.id, d.nom, 1 - (e.embedding <=> '[...vecteur...]'::vector) AS score
FROM embeddings e JOIN documents d ON e.document_id = d.id
ORDER BY score DESC LIMIT 10;

-- Stats par catégorie
SELECT m.categorie, COUNT(*) AS nb_docs
FROM metadonnees_ia m GROUP BY m.categorie ORDER BY nb_docs DESC;
```
