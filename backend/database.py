"""
Moteur de base de données — DocFlow AI
=======================================
Moteur SQLAlchemy async + factory de sessions + dépendance FastAPI.

Usage dans un router :
    from database import get_db
    from sqlalchemy.ext.asyncio import AsyncSession

    @router.get("/exemple")
    async def exemple(db: AsyncSession = Depends(get_db)):
        ...
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from logger import get_logger

log = get_logger(__name__)

settings = get_settings()

# --- Moteur async ---
_is_sqlite = settings.database_url.startswith("sqlite")
_engine_kwargs: dict = {"echo": settings.debug}
if not _is_sqlite:
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20
    _engine_kwargs["pool_pre_ping"] = True  # Vérifier la connexion avant chaque utilisation

engine = create_async_engine(settings.database_url, **_engine_kwargs)

# --- Factory de sessions ---
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,       # Éviter les lazy-load après commit
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dépendance FastAPI — fournit une session DB async.
    La session est fermée automatiquement après la requête.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """
    Initialise la base de données au démarrage.
    Crée les extensions pgvector/pg_trgm puis les tables si elles n'existent pas.
    En production, les migrations Alembic prennent le relais (alembic upgrade head).
    """
    from models import Base  # Import ici pour éviter les imports circulaires
    from sqlalchemy import text

    # Extensions + tables. `create_all` (checkfirst) ne CRÉE que les tables manquantes et ne touche
    # PAS aux tables existantes → aucun verrou sur les tables « chaudes ». On l'ISOLE pour qu'un
    # éventuel report des migrations idempotentes ci-dessous ne l'annule jamais.
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)

    # ── Migrations idempotentes « à chaud » ──────────────────────────────────────
    # ⚠️ Chaque `ALTER TABLE … ADD COLUMN/CONSTRAINT`, MÊME quand c'est un no-op (déjà là), prend un
    # verrou ACCESS EXCLUSIVE. Si le WORKER est chargé (écritures continues sur jobs/documents), ce
    # verrou n'est jamais accordé → le DÉMARRAGE se bloque indéfiniment (incident déploiement 1.56.0).
    # Parade : `lock_timeout` court + transaction ISOLÉE par migration → si le verrou n'est pas obtenu,
    # on REPORTE proprement cette migration (idempotente, elle repassera à un démarrage moins chargé)
    # au lieu de bloquer l'app. Un timeout n'affecte que sa propre transaction.
    async def _migration(sqls: list[str], *, timeout: str = "4s") -> None:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"SET LOCAL lock_timeout = '{timeout}'"))
                for sql in sqls:
                    await conn.execute(text(sql))
        except Exception as e:  # noqa: BLE001 — non bloquant : l'app démarre même si la migration est reportée
            log.warning("Migration de démarrage reportée (verrou/timeout)",
                        erreur=str(e) or type(e).__name__, ddl=(sqls[0][:70] if sqls else ""))

    # Statuts 'catalogued'/'absent' autorisés (bases créées via init-db.sql).
    await _migration([
        "ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_statut_check",
        "ALTER TABLE documents ADD CONSTRAINT documents_statut_check "
        "CHECK (statut IN ('pending','extracted','enriched','error','catalogued','absent'))",
    ])
    # Colonnes ajoutées à chaud (create_all ne fait que CREATE TABLE) — une par transaction : le report
    # de l'une n'empêche pas les autres. Synchro (Phase 3), annulation/reprises, Matryoshka (E7).
    for ddl in (
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS sync_intervalle_minutes INTEGER",
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS dernier_sync TIMESTAMPTZ",
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS dernier_sync_recap JSONB",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS annulation_demandee BOOLEAN DEFAULT false",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS reprises INTEGER DEFAULT 0",
        "ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS embedding_small vector(1024)",
    ):
        await _migration([ddl])
    # Jobs : types applicatifs (retrait du CHECK type), statut 'cancelled', colonnes de progression.
    await _migration([
        "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_type_check",
        "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_statut_check",
        "ALTER TABLE jobs ADD CONSTRAINT jobs_statut_check "
        "CHECK (statut IN ('pending','running','completed','failed','cancelled'))",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_message TEXT",
    ])

    # Recherche full-text : colonne `tsv` STOCKÉE (générée) sur documents → `ts_rank(tsv,…)` sans
    # recalcul (~20×). ⚠️ On VÉRIFIE le catalogue AVANT l'ALTER (lecture sans verrou) → on ne prend le
    # verrou ACCESS EXCLUSIVE que la 1ʳᵉ fois (colonne absente), plus jamais ensuite → redémarrages sûrs
    # même worker à fond. `lock_timeout` en dernier recours ; ANALYZE seulement si on a créé qqch.
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL lock_timeout = '4s'"))
            col = (await conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='documents' AND column_name='tsv'"))).scalar()
            if not col:
                await conn.execute(text(
                    "ALTER TABLE documents ADD COLUMN tsv tsvector GENERATED ALWAYS AS (to_tsvector('french', "
                    "COALESCE(texte_extrait, '') || ' ' || COALESCE(nom, ''))) STORED"))
            idx = (await conn.execute(text(
                "SELECT 1 FROM pg_indexes WHERE indexname='idx_documents_tsv'"))).scalar()
            if not idx:
                await conn.execute(text("CREATE INDEX idx_documents_tsv ON documents USING gin(tsv)"))
            # Index sur l'expression devenu redondant → retiré (drop seulement s'il existe).
            if (await conn.execute(text(
                    "SELECT 1 FROM pg_indexes WHERE indexname='idx_documents_fts_nom'"))).scalar():
                await conn.execute(text("DROP INDEX idx_documents_fts_nom"))
            if not col or not idx:
                await conn.execute(text("ANALYZE documents"))
    except Exception as e:
        log.warning("Full-text documents (tsv) reporté au démarrage (verrou/timeout)",
                    erreur=str(e) or type(e).__name__)

    # Full-text sur les MÉTADONNÉES IA : une image sans texte extrait n'a « Fanny Jovignot » que
    # dans son résumé/tags/entités → invisible si l'on ne cherche que `documents.tsv` (texte+nom).
    # Colonne tsvector STOCKÉE sur `metadonnees_ia` (résumé + tags + mots-clés + catégorie + ENTITÉS
    # IA : personnes/organisations/lieux/dates), cherchée EN PLUS. Les valeurs d'entités sont
    # extraites du JSONB via `jsonb_path_query_array($.*[*])` (immutable → OK en colonne générée) —
    # on n'indexe QUE les valeurs, pas les clés du JSON.
    #
    # PG16 ne sait pas MODIFIER l'expression d'une colonne générée → on la RECRÉE, mais seulement si
    # elle est absente ou obsolète (marqueur : présence de `jsonb_path_query_array` dans l'expression
    # actuelle) — sinon on réécrirait la table à chaque démarrage.
    # Une colonne GÉNÉRÉE ne peut pas aplatir le JSONB des entités (conversion jsonb→text non
    # immutable → PG refuse). On maintient donc `tsv` par un TRIGGER (aucune contrainte
    # d'immutabilité), qui inclut les VALEURS des entités (personnes/organisations/lieux/dates).
    _FN_TSV = """
        CREATE OR REPLACE FUNCTION metadonnees_ia_maj_tsv() RETURNS trigger AS $$
        BEGIN
          NEW.tsv := to_tsvector('french',
            coalesce(NEW.resume,'') || ' ' ||
            coalesce(array_to_string(NEW.tags,' '),'') || ' ' ||
            coalesce(array_to_string(NEW.mots_cles,' '),'') || ' ' ||
            coalesce(NEW.categorie,'') || ' ' || coalesce(NEW.sous_categorie,'') || ' ' ||
            coalesce((
              SELECT string_agg(elem, ' ')
              FROM jsonb_each(coalesce(NEW.entites,'{}'::jsonb)) AS kv(k, val)
              CROSS JOIN LATERAL jsonb_array_elements_text(
                CASE WHEN jsonb_typeof(val)='array' THEN val ELSE '[]'::jsonb END) AS elem
            ), ''));
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """
    _META_TSV_LOCK = 771038   # verrou d'avis : un seul process (multi-uvicorn) fait le DDL
    try:
        async with engine.begin() as conn:
            await conn.execute(text(_FN_TSV))   # fonction idempotente (sûre en concurrence)

        # DDL SEUL (colonne + trigger + index vide) dans une transaction COURTE qui COMMITTE tout de
        # suite → `m.tsv` existe immédiatement, la recherche ne plante plus. ⚠️ Le backfill des 66 k
        # lignes est SÉPARÉ (ci-dessous) : le mettre ici (UPDATE massif) rendait la transaction longue
        # et fragile — un redéploiement pendant le backfill la ROLLBACKAIT → colonne jamais créée
        # (« column m.tsv does not exist » en prod, 05/08).
        async with engine.begin() as conn:
            got = (await conn.execute(text("SELECT pg_try_advisory_xact_lock(:k)"),
                                      {"k": _META_TSV_LOCK})).scalar()
            if got:
                existe = (await conn.execute(text(
                    "SELECT 1 FROM pg_trigger WHERE tgname='trg_meta_tsv' "
                    "AND tgrelid='metadonnees_ia'::regclass"))).scalar()
                if not existe:
                    await conn.execute(text("ALTER TABLE metadonnees_ia DROP COLUMN IF EXISTS tsv"))
                    await conn.execute(text("ALTER TABLE metadonnees_ia ADD COLUMN tsv tsvector"))
                    await conn.execute(text(
                        "CREATE TRIGGER trg_meta_tsv BEFORE INSERT OR UPDATE ON metadonnees_ia "
                        "FOR EACH ROW EXECUTE FUNCTION metadonnees_ia_maj_tsv()"))
                    await conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS idx_meta_tsv ON metadonnees_ia USING gin(tsv)"))
                    log.info("metadonnees_ia.tsv (colonne + trigger + index) créé")

        # BACKFILL par LOTS (résumable + idempotent) : ne traite que les lignes `tsv IS NULL`, par
        # paquets committés séparément. `FOR UPDATE SKIP LOCKED` → plusieurs workers peuvent aider sans
        # se marcher dessus. Le trigger recalcule `tsv` (SET tsv=NULL → BEFORE trigger le remplit).
        # Interruptible : au prochain démarrage on reprend là où on s'était arrêté.
        total = 0
        while True:
            try:
                async with engine.begin() as conn:
                    res = await conn.execute(text("""
                        WITH lot AS (
                            SELECT ctid FROM metadonnees_ia WHERE tsv IS NULL
                            LIMIT 3000 FOR UPDATE SKIP LOCKED
                        )
                        UPDATE metadonnees_ia m SET tsv = NULL FROM lot WHERE m.ctid = lot.ctid
                    """))
            except Exception:  # noqa: BLE001 — colonne absente (DDL a échoué) → rien à backfiller
                break
            n = res.rowcount or 0
            total += n
            if n < 3000:
                break
        if total:
            log.info("Backfill metadonnees_ia.tsv terminé", lignes=total)
            # ANALYZE seulement si le backfill a réellement traité des lignes (sinon inutile à chaque
            # démarrage) — sous `lock_timeout` pour ne jamais bloquer si un autre ANALYZE/VACUUM tourne.
            async with engine.begin() as conn:
                await conn.execute(text("SET LOCAL lock_timeout = '4s'"))
                await conn.execute(text("ANALYZE metadonnees_ia"))
    except Exception as e:
        log.warning("Full-text métadonnées (meta.tsv, trigger) non initialisé", erreur=str(e) or type(e).__name__)


async def close_db() -> None:
    """Ferme le pool de connexions proprement à l'arrêt."""
    await engine.dispose()
