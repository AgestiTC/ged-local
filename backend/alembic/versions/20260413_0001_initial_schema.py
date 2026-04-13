"""Schéma initial — toutes les tables DocFlow AI

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-13 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# identifiants de révision
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extensions PostgreSQL requises
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── Table documents ────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("chemin", sa.Text(), nullable=False),
        sa.Column("nom", sa.Text(), nullable=False),
        sa.Column("extension", sa.String(20), nullable=False),
        sa.Column("type_mime", sa.Text(), nullable=True),
        sa.Column("hash_sha256", sa.String(64), nullable=False),
        sa.Column("taille_octets", sa.BigInteger(), nullable=True),
        sa.Column("date_import", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
        sa.Column("date_modification_fichier", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_derniere_extraction", sa.DateTime(timezone=True), nullable=True),
        sa.Column("texte_extrait", sa.Text(), nullable=True),
        sa.Column("tika_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("statut", sa.String(20), server_default="pending", nullable=True),
        sa.Column("erreur", sa.Text(), nullable=True),
        sa.Column("source", sa.String(20), server_default="watch", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
    )
    op.create_index("idx_documents_hash", "documents", ["hash_sha256"])
    op.create_index("idx_documents_chemin", "documents", ["chemin"])
    op.create_index("idx_documents_statut", "documents", ["statut"])
    op.create_index(
        "idx_documents_nom_trgm", "documents", ["nom"],
        postgresql_using="gin",
        postgresql_ops={"nom": "gin_trgm_ops"},
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_texte_fts "
        "ON documents USING gin(to_tsvector('french', coalesce(texte_extrait, '')))"
    )

    # ── Table metadonnees_ia ───────────────────────────────────────────────────
    op.create_table(
        "metadonnees_ia",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("categorie", sa.Text(), nullable=True),
        sa.Column("sous_categorie", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("resume", sa.Text(), nullable=True),
        sa.Column("langue", sa.String(10), nullable=True),
        sa.Column("entites", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("mots_cles", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("niveau_confidentialite", sa.String(20),
                  server_default="normal", nullable=True),
        sa.Column("modele_utilise", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
        sa.UniqueConstraint("document_id", name="uq_metadonnees_ia_document"),
    )
    op.create_index("idx_meta_categorie", "metadonnees_ia", ["categorie"])
    op.create_index(
        "idx_meta_tags", "metadonnees_ia", ["tags"],
        postgresql_using="gin",
    )

    # ── Table embeddings ───────────────────────────────────────────────────────
    # NOTE : la colonne vector est créée en SQL brut car SQLAlchemy ne connaît
    # pas le type pgvector nativement dans Alembic sans plugin.
    op.create_table(
        "embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("modele_embedding", sa.Text(),
                  server_default="qwen3-embedding:8b", nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
    )
    # Ajouter la colonne vector séparément (pgvector)
    op.execute(
        "ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS "
        "embedding vector(4096)"
    )
    op.create_index("idx_embeddings_document", "embeddings", ["document_id"])
    # Index IVFFlat pour la recherche approchée (à créer APRÈS le chargement des données)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_embeddings_vector "
        "ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    # ── Table versions ─────────────────────────────────────────────────────────
    op.create_table(
        "versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("numero_version", sa.Integer(), nullable=False),
        sa.Column("hash_sha256", sa.String(64), nullable=False),
        sa.Column("taille_octets", sa.BigInteger(), nullable=True),
        sa.Column("date_detection", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
        sa.Column("diff_resume", sa.Text(), nullable=True),
        sa.Column("chemin_archive", sa.Text(), nullable=True),
    )
    op.create_index("idx_versions_document", "versions", ["document_id"])

    # ── Table templates ────────────────────────────────────────────────────────
    op.create_table(
        "templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("nom", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("type", sa.String(10), nullable=False),
        sa.Column("chemin_fichier", sa.Text(), nullable=False),
        sa.Column("champs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
    )

    # ── Table prompts_presets ──────────────────────────────────────────────────
    op.create_table(
        "prompts_presets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("nom", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("categorie", sa.Text(), nullable=True),
        sa.Column("modele_prefere", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
    )

    # ── Table jobs ─────────────────────────────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("statut", sa.String(20), server_default="pending", nullable=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("parametres", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("resultat", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("erreur", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_jobs_statut", "jobs", ["statut"])
    op.create_index("idx_jobs_type", "jobs", ["type"])

    # ── Table dossiers_surveilles ──────────────────────────────────────────────
    op.create_table(
        "dossiers_surveilles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("chemin", sa.Text(), nullable=False),
        sa.Column("nom_affichage", sa.Text(), nullable=True),
        sa.Column("actif", sa.Boolean(), server_default="true", nullable=True),
        sa.Column("recursive", sa.Boolean(), server_default="true", nullable=True),
        sa.Column("extensions_filtrees", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("intervalle_scan_secondes", sa.Integer(),
                  server_default="300", nullable=True),
        sa.Column("dernier_scan", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=True),
        sa.UniqueConstraint("chemin", name="uq_dossiers_surveilles_chemin"),
    )


def downgrade() -> None:
    # Supprimer dans l'ordre inverse (contraintes FK)
    op.drop_table("dossiers_surveilles")
    op.drop_table("jobs")
    op.drop_table("prompts_presets")
    op.drop_table("templates")
    op.drop_table("versions")
    op.drop_table("embeddings")
    op.drop_table("metadonnees_ia")
    op.drop_table("documents")

    # Extensions (commenté par défaut — peut affecter d'autres apps)
    # op.execute("DROP EXTENSION IF EXISTS vector")
    # op.execute("DROP EXTENSION IF EXISTS pg_trgm")
