"""
Tests — le démarrage ne retente plus les migrations déjà faites
==============================================================
09/10/2026 : ~30 `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, tous sans effet depuis longtemps,
demandaient chacun un verrou exclusif au démarrage. Worker occupé, chacun attendait 4 s : le
backend mettait plus de 30 s à répondre et le script de déploiement concluait à l'échec.
"""

from database import deja_applique

COLONNES = {("documents", "antivirus"), ("sources", "sync_dossiers")}
INDEX = {"idx_documents_doublon_de"}


def test_une_colonne_deja_presente_n_est_plus_tentee():
    assert deja_applique("ALTER TABLE documents ADD COLUMN IF NOT EXISTS antivirus TEXT", COLONNES, INDEX)
    assert deja_applique("  alter table SOURCES add column if not exists Sync_Dossiers JSONB", COLONNES, INDEX)


def test_une_colonne_manquante_est_bien_ajoutee():
    assert not deja_applique("ALTER TABLE documents ADD COLUMN IF NOT EXISTS nouvelle INTEGER", COLONNES, INDEX)
    assert not deja_applique("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS antivirus TEXT", COLONNES, INDEX)


def test_les_index():
    creer = "CREATE INDEX IF NOT EXISTS {} ON documents (doublon_de) WHERE doublon_de IS NOT NULL"
    assert deja_applique(creer.format("idx_documents_doublon_de"), COLONNES, INDEX)
    assert not deja_applique(creer.format("idx_autre"), COLONNES, INDEX)


def test_tout_le_reste_est_rejoue_comme_avant():
    """Contraintes, fonctions, déclencheurs : on ne prétend pas savoir s'ils sont à jour."""
    for sql in ("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_statut_check",
                "ALTER TABLE documents ADD CONSTRAINT documents_statut_check CHECK (statut IN ('pending'))",
                "CREATE OR REPLACE FUNCTION metadonnees_ia_maj_tsv() RETURNS trigger AS $$ BEGIN END $$",
                "ALTER TABLE documents ADD COLUMN antivirus TEXT"):          # sans IF NOT EXISTS
        assert not deja_applique(sql, COLONNES, INDEX)


def test_sans_catalogue_rien_n_est_saute():
    assert not deja_applique("ALTER TABLE documents ADD COLUMN IF NOT EXISTS antivirus TEXT", set(), set())
