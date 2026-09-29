-- ============================================================================================
-- Migration des embeddings en demi-précision (halfvec) — une seule fois, par base
-- ============================================================================================
-- Pourquoi : ~1 Go gagné sur 2,5 en prod (colonne 4096d 1 267 → ~634 Mo, 1024d 317 → ~158 Mo,
-- index HNSW 561 → ~280 Mo), pour AUCUNE perte mesurée : top-10 exact identique 10/10 sur
-- 25 requêtes (évaluation du 29/09/2026, docs/plan-perf-2026-09.md, étape 8).
--
-- Le code (≥ v1.126.0) fonctionne AVANT comme APRÈS : une requête `CAST(… AS vector)` contre
-- une colonne halfvec est convertie par pgvector, et l'index halfvec est bien utilisé (vérifié
-- sur base jetable). Aucun ordre à respecter avec le déploiement.
--
-- Pendant l'ALTER (verrou exclusif sur `embeddings`, quelques minutes) : l'indexation et la
-- recherche sémantique ATTENDENT, elles n'échouent pas. Sauvegarde de la base AVANT.
--
-- Usage (LXC) :
--   docker compose exec -T postgres psql -U docflow -d docflow -v ON_ERROR_STOP=1 < migrer-halfvec.sql
--   puis, HORS transaction (non bloquant) :
--   CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_embeddings_small_hnsw
--       ON embeddings USING hnsw (embedding_small halfvec_cosine_ops);
--   (ou redémarrer le worker : il recrée l'index avec l'opérateur qui suit le type de la colonne)
--
-- ⚠️ PUIS REDÉMARRER backend ET worker (`docker compose restart backend worker`, puis
--   `restart frontend` pour l'IP du backend) : les connexions déjà ouvertes gardent des requêtes
--   préparées sur l'ANCIEN type, et chacune échoue une fois (InvalidCachedStatementError) avant de
--   se rétablir. Constaté sur base jetable le 29/09/2026 ; un pool neuf n'a pas le problème.
-- ============================================================================================

\timing on
BEGIN;
-- L'index existant est en vector_cosine_ops : il ne survivrait pas au changement de type.
DROP INDEX IF EXISTS idx_embeddings_small_hnsw;
-- Une seule réécriture de la table pour les deux colonnes.
ALTER TABLE embeddings
    ALTER COLUMN embedding       TYPE halfvec(4096) USING embedding::halfvec(4096),
    ALTER COLUMN embedding_small TYPE halfvec(1024) USING embedding_small::halfvec(1024);
COMMIT;
ANALYZE embeddings;
