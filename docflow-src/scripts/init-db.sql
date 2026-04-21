-- ============================================================
-- DocFlow AI — Initialisation PostgreSQL + pgvector
-- Exécuté une seule fois à la création du conteneur
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;          -- pgvector : recherche sémantique
CREATE EXTENSION IF NOT EXISTS pg_trgm;         -- Full-text trigram rapide
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";     -- gen_random_uuid()

-- ============================================================
-- Table principale des documents
-- ============================================================
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chemin TEXT NOT NULL,
    nom TEXT NOT NULL,
    extension TEXT NOT NULL,
    type_mime TEXT,
    hash_sha256 TEXT NOT NULL,
    taille_octets BIGINT,
    date_import TIMESTAMPTZ DEFAULT NOW(),
    date_modification_fichier TIMESTAMPTZ,
    date_derniere_extraction TIMESTAMPTZ,
    texte_extrait TEXT,
    tika_metadata JSONB,
    statut TEXT DEFAULT 'pending' CHECK (statut IN ('pending', 'extracted', 'enriched', 'error')),
    erreur TEXT,
    source TEXT DEFAULT 'watch' CHECK (source IN ('watch', 'upload', 'drag_drop')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_hash     ON documents(hash_sha256);
CREATE INDEX IF NOT EXISTS idx_documents_chemin   ON documents(chemin);
CREATE INDEX IF NOT EXISTS idx_documents_statut   ON documents(statut);
CREATE INDEX IF NOT EXISTS idx_documents_nom_trgm ON documents USING gin(nom gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_documents_fts      ON documents
    USING gin(to_tsvector('french', COALESCE(texte_extrait, '')));

-- ============================================================
-- Métadonnées enrichies par l'IA
-- ============================================================
CREATE TABLE IF NOT EXISTS metadonnees_ia (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE UNIQUE NOT NULL,
    categorie TEXT,
    sous_categorie TEXT,
    tags TEXT[],
    resume TEXT,
    langue TEXT,
    entites JSONB,
    mots_cles TEXT[],
    niveau_confidentialite TEXT DEFAULT 'normal' CHECK (niveau_confidentialite IN ('normal', 'confidentiel', 'restreint')),
    modele_utilise TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_meta_categorie ON metadonnees_ia(categorie);
CREATE INDEX IF NOT EXISTS idx_meta_tags      ON metadonnees_ia USING gin(tags);

-- ============================================================
-- Embeddings vectoriels (pgvector)
-- IMPORTANT : dimension = 4096 pour qwen3-embedding:8b
-- À vérifier au premier appel et adapter si différent
-- ============================================================
CREATE TABLE IF NOT EXISTS embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE NOT NULL,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(4096),
    modele_embedding TEXT DEFAULT 'qwen3-embedding:8b',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_document ON embeddings(document_id);

-- Index IVFFlat pour la recherche cosine (créé après les premiers embeddings)
-- À exécuter manuellement après avoir inséré des données :
-- CREATE INDEX idx_embeddings_vector ON embeddings
--     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================
-- Versions des documents
-- ============================================================
CREATE TABLE IF NOT EXISTS versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE NOT NULL,
    numero_version INTEGER NOT NULL,
    hash_sha256 TEXT NOT NULL,
    taille_octets BIGINT,
    date_detection TIMESTAMPTZ DEFAULT NOW(),
    diff_resume TEXT,
    chemin_archive TEXT
);

CREATE INDEX IF NOT EXISTS idx_versions_document ON versions(document_id);

-- ============================================================
-- Templates DOCX/PDF
-- ============================================================
CREATE TABLE IF NOT EXISTS templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nom TEXT NOT NULL,
    description TEXT,
    type TEXT NOT NULL CHECK (type IN ('docx', 'pdf')),
    chemin_fichier TEXT NOT NULL,
    champs JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Prompts pré-enregistrés
-- ============================================================
CREATE TABLE IF NOT EXISTS prompts_presets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nom TEXT NOT NULL,
    description TEXT,
    prompt_text TEXT NOT NULL,
    categorie TEXT CHECK (categorie IN ('rapport', 'classement', 'extraction', 'analyse')),
    modele_prefere TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- File d'attente des jobs
-- ============================================================
CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL CHECK (type IN ('extraction', 'enrichissement', 'rapport', 'embedding')),
    statut TEXT DEFAULT 'pending' CHECK (statut IN ('pending', 'running', 'completed', 'failed')),
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    parametres JSONB,
    resultat JSONB,
    erreur TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_statut ON jobs(statut);
CREATE INDEX IF NOT EXISTS idx_jobs_type   ON jobs(type);

-- ============================================================
-- Dossiers surveillés
-- ============================================================
CREATE TABLE IF NOT EXISTS dossiers_surveilles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chemin TEXT NOT NULL UNIQUE,
    nom_affichage TEXT,
    actif BOOLEAN DEFAULT true,
    recursive BOOLEAN DEFAULT true,
    extensions_filtrees TEXT[],
    intervalle_scan_secondes INTEGER DEFAULT 300,
    dernier_scan TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- Trigger : mise à jour automatique de updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE OR REPLACE TRIGGER templates_updated_at
    BEFORE UPDATE ON templates
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- Données initiales
-- ============================================================

-- Charger les prompts par défaut depuis seed-prompts (fait via l'API au démarrage)
-- Les prompts sont dans scripts/seed-prompts.json

SELECT 'DocFlow AI — Base de données initialisée avec succès' AS message;
