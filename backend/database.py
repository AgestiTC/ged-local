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

import re
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


_AJOUT_COLONNE = re.compile(r"^\s*ALTER\s+TABLE\s+(\w+)\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+(\w+)\b", re.I)
_CREATION_INDEX = re.compile(r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+(\w+)\b", re.I)


def deja_applique(sql: str, colonnes: set[tuple[str, str]], index: set[str]) -> bool:
    """
    Cette migration idempotente est-elle déjà faite ? Fonction PURE.

    Ne reconnaît que les deux formes sans ambiguïté — ajout de colonne, création d'index. Tout le
    reste (contraintes, fonctions, déclencheurs) renvoie False et reste rejoué comme avant.
    """
    m = _AJOUT_COLONNE.match(sql)
    if m:
        return (m.group(1).lower(), m.group(2).lower()) in colonnes
    m = _CREATION_INDEX.match(sql)
    return bool(m) and m.group(1).lower() in index


async def garantir_colonnes(table: str, colonnes: dict[str, str], *, essais: int = 6, pause: float = 2.0) -> None:
    """
    Garantit des colonnes dont l'ABSENCE casserait les lectures de la table (l'ORM les sélectionne
    toutes). Lit d'abord le catalogue (sans verrou : aucun ACCESS EXCLUSIVE aux démarrages suivants),
    ajoute celles qui manquent en UN SEUL `ALTER TABLE` (`lock_timeout` 5 s), et RÉESSAIE si le verrou
    n'est pas obtenu (worker chargé). Seulement PostgreSQL. Après `essais` échecs : erreur bruyante.
    """
    import asyncio as _asyncio

    from sqlalchemy import text
    if not engine.dialect.name.startswith("postgres") or not colonnes:
        return
    for essai in range(1, essais + 1):
        try:
            async with engine.connect() as conn:
                presentes = {r[0] for r in await conn.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                    "AND table_name = :t"), {"t": table})}
            manquantes = {c: t for c, t in colonnes.items() if c not in presentes}
            if not manquantes:
                return
            ajouts = ", ".join(f"ADD COLUMN IF NOT EXISTS {c} {t}" for c, t in manquantes.items())
            async with engine.begin() as conn:
                await conn.execute(text("SET LOCAL lock_timeout = '5s'"))
                await conn.execute(text(f"ALTER TABLE {table} {ajouts}"))
            log.info("Colonnes ajoutées à chaud", table=table, colonnes=sorted(manquantes))
            return
        except Exception as e:  # noqa: BLE001 — verrou non obtenu : la table est occupée
            log.warning("Ajout de colonnes en attente d'un verrou — nouvel essai", table=table,
                        colonnes=sorted(colonnes), essai=essai, erreur=str(e) or type(e).__name__)
            await _asyncio.sleep(pause)
    log.error("COLONNES NON AJOUTÉES — les lectures de la table échoueront jusqu'au prochain démarrage",
              table=table, colonnes=sorted(colonnes))


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
        # Plusieurs processus démarrent ensemble (uvicorn --workers 2, worker) : sans verrou, deux
        # `CREATE TABLE` d'une table NOUVELLE se croisent → l'un meurt sur pg_type_typname_nsp_index
        # puis est relancé (vu le 14/11/2026 à la création de notification_preferences). Le verrou
        # d'avis, levé à la fin de la transaction, les fait passer l'un après l'autre.
        if engine.dialect.name.startswith("postgres"):
            await conn.execute(text("SELECT pg_advisory_xact_lock(461203878)"))
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
    # Ce qui existe DÉJÀ, lu une fois dans le catalogue (aucun verrou). Sans ce filtre, les ~30
    # `ADD COLUMN IF NOT EXISTS` — tous des no-op depuis longtemps — demandaient chacun un verrou
    # exclusif : worker occupé, chacun attendait ses 4 s avant d'être « reporté », et le backend
    # mettait plus de 30 s à démarrer (le script de déploiement concluait à l'échec, 09/10/2026).
    colonnes_presentes: set[tuple[str, str]] = set()
    index_presents: set[str] = set()
    if engine.dialect.name.startswith("postgres"):
        try:
            async with engine.connect() as conn:
                colonnes_presentes = {(t, c) for t, c in await conn.execute(text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema()"))}
                index_presents = {r[0] for r in await conn.execute(text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"))}
        except Exception as e:  # noqa: BLE001 — catalogue illisible : on rejoue tout, comme avant
            log.warning("Catalogue illisible — migrations rejouées sans filtre", erreur=str(e) or type(e).__name__)

    async def _migration(sqls: list[str], *, timeout: str = "4s") -> None:
        sqls = [s for s in sqls if not deja_applique(s, colonnes_presentes, index_presents)]
        if not sqls:
            return
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"SET LOCAL lock_timeout = '{timeout}'"))
                for sql in sqls:
                    await conn.execute(text(sql))
        except Exception as e:  # noqa: BLE001 — non bloquant : l'app démarre même si la migration est reportée
            log.warning("Migration de démarrage reportée (verrou/timeout)",
                        erreur=str(e) or type(e).__name__, ddl=(sqls[0][:70] if sqls else ""))

    # Contraintes CHECK : on ne les recrée QUE si leur définition en base diffère. Avant (audit
    # du 28/09/2026, M4), DROP + ADD à CHAQUE démarrage, par chacun des 3 process : l'ADD
    # revalide toute la table sous verrou exclusif, même quand la contrainte est identique.
    # Même modèle que le bloc `tsv` plus bas : on regarde le catalogue avant d'agir.
    async def _check_conforme(table: str, nom: str, valeurs: tuple[str, ...]) -> bool:
        import re
        try:
            async with engine.connect() as conn:
                definition = (await conn.execute(text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid WHERE c.conname = :n AND t.relname = :t"
                ), {"n": nom, "t": table})).scalar()
        except Exception:  # noqa: BLE001 — catalogue illisible (autre moteur) : on rejoue
            return False
        return definition is not None and set(re.findall(r"'([^']+)'", definition)) == set(valeurs)

    statuts_doc = ("pending", "extracted", "enriched", "error", "catalogued", "absent")
    sources_doc = ("watch", "upload", "drag_drop", "connector", "wiki", "smb", "synology", "scan")
    statuts_job = ("pending", "running", "completed", "failed", "cancelled")
    types_template = ("docx", "pdf", "xlsx")
    _en_sql = lambda vs: ",".join(f"'{v}'" for v in vs)   # noqa: E731 — constantes internes

    # Statuts 'catalogued'/'absent' autorisés (bases créées via init-db.sql).
    if not await _check_conforme("documents", "documents_statut_check", statuts_doc):
        await _migration([
            "ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_statut_check",
            f"ALTER TABLE documents ADD CONSTRAINT documents_statut_check "
            f"CHECK (statut IN ({_en_sql(statuts_doc)}))",
        ])
    # Origine 'scan' (module Scan → GED) : les bases créées via init-db.sql portent un CHECK fermé.
    if not await _check_conforme("documents", "documents_source_check", sources_doc):
        await _migration([
            "ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_source_check",
            f"ALTER TABLE documents ADD CONSTRAINT documents_source_check "
            f"CHECK (source IN ({_en_sql(sources_doc)}))",
        ])
    # Modèles Excel (.xlsx, dont les grilles d'analyse) : le CHECK d'init-db.sql n'acceptait que
    # docx/pdf — tout envoi de modèle Excel finissait en 500 (constaté le 01/10/2026).
    if not await _check_conforme("templates", "templates_type_check", types_template):
        await _migration([
            "ALTER TABLE templates DROP CONSTRAINT IF EXISTS templates_type_check",
            f"ALTER TABLE templates ADD CONSTRAINT templates_type_check "
            f"CHECK (type IN ({_en_sql(types_template)}))",
        ])
    # Colonnes ajoutées à chaud (create_all ne fait que CREATE TABLE) — une par transaction : le report
    # de l'une n'empêche pas les autres. Synchro (Phase 3), annulation/reprises, Matryoshka (E7).
    for ddl in (
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS sync_intervalle_minutes INTEGER",
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS dernier_sync TIMESTAMPTZ",
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS dernier_sync_recap JSONB",
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS sync_dossiers JSONB",
        # Usage d'une source (14/11/2026) : `rangement` = jamais utilisée par la GED (models/source.py).
        "ALTER TABLE sources ADD COLUMN IF NOT EXISTS usage TEXT NOT NULL DEFAULT 'ged'",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS annulation_demandee BOOLEAN DEFAULT false",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS reprises INTEGER DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS priorite_forcee BOOLEAN DEFAULT false",
        # Qui a fait l'action (authentification, étape 5) : identifiant SSO ou « jeton:<nom> ».
        "ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS auteur TEXT",
        "ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS embedding_small halfvec(1024)",
        "ALTER TABLE ressources ADD COLUMN IF NOT EXISTS contenu TEXT",
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS antivirus TEXT",
        # Année de revenus confirmée à la main (Administration → Aide à la déclaration) : la
        # date du fichier ne dit pas quand la dépense a eu lieu.
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS annee_fiscale INTEGER",
        # Évaluation du tableau comparatif des modèles IA, recalculée depuis les faits
        # (Paramètres → « Mettre à jour le tableau ») et conservée entre deux affichages.
        "ALTER TABLE model_meta ADD COLUMN IF NOT EXISTS evaluation JSONB",
        "ALTER TABLE model_meta ADD COLUMN IF NOT EXISTS evaluee_le TIMESTAMPTZ",
        "ALTER TABLE ressources ADD COLUMN IF NOT EXISTS resume_ia TEXT",
        "ALTER TABLE ressources ADD COLUMN IF NOT EXISTS flux_url TEXT",
        # Doc des applications (plan-reception-doc-applications, étape 3) : version de l'en-tête.
        "ALTER TABLE versions ADD COLUMN IF NOT EXISTS libelle TEXT",
        # Rendez-vous PRIS dans un rétroplanning : une date fixée, et son créneau. Sans ces
        # colonnes ici, un déploiement casse le planning — `jalons` existe déjà, donc
        # `create_all` ne la retouche pas (cf. migration alembic 0008_jalon_date_reelle).
        "ALTER TABLE jalons ADD COLUMN IF NOT EXISTS date_reelle DATE",
        "ALTER TABLE jalons ADD COLUMN IF NOT EXISTS heure_debut TEXT",
        "ALTER TABLE jalons ADD COLUMN IF NOT EXISTS heure_fin TEXT",
        # Hiérarchie des dossiers thématiques (« MON BÉBÉ » → sous-dossiers par tranche d'âge).
        "ALTER TABLE dossiers_thematiques ADD COLUMN IF NOT EXISTS parent_id UUID "
        "REFERENCES dossiers_thematiques(id) ON DELETE CASCADE",
        "ALTER TABLE dossiers_thematiques ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0",
        # Capacités du dossier (onglets supplémentaires) : {"emploi-domicile": {"profil": …}}.
        "ALTER TABLE dossiers_thematiques ADD COLUMN IF NOT EXISTS modules JSONB NOT NULL DEFAULT '{}'::jsonb",
        # Portrait d'un intervenant (v1.97.0). ⚠️ La table existait déjà depuis la v1.93.0, et
        # `create_all` ne fait que CREATE TABLE : sans ces deux lignes, le SELECT réclamait une
        # colonne absente et l'onglet « Visites » restait bloqué sur « Chargement… ».
        "ALTER TABLE emploi_domicile_intervenants ADD COLUMN IF NOT EXISTS photo TEXT",
        "ALTER TABLE emploi_domicile_intervenants ADD COLUMN IF NOT EXISTS photo_accord "
        "BOOLEAN NOT NULL DEFAULT false",
        # Identité administrative CHIFFRÉE (v1.105.0) : n° de sécurité sociale et IBAN.
        # Même raison qu'au-dessus — la table est antérieure, `create_all` n'ajoute rien.
        "ALTER TABLE emploi_domicile_intervenants ADD COLUMN IF NOT EXISTS numero_secu_chiffre TEXT",
        "ALTER TABLE emploi_domicile_intervenants ADD COLUMN IF NOT EXISTS iban_chiffre TEXT",
        # Date de disponibilité (v1.106.0), distincte du texte libre `disponibilite` qui dit
        # les JOURS et les horaires. Même raison qu'au-dessus : la table est antérieure.
        "ALTER TABLE emploi_domicile_intervenants ADD COLUMN IF NOT EXISTS disponible_le DATE",
        # Dossier surveillé devenu inaccessible : la raison, visible dans Paramètres (audit
        # du 28/09/2026) — `dossiers_surveilles` existe déjà, `create_all` n'ajoute rien.
        "ALTER TABLE dossiers_surveilles ADD COLUMN IF NOT EXISTS dernier_scan_erreur TEXT",
        # Journal des déplacements commun (plan rangement + mails, décision n° 3) : d'où vient
        # le déplacement, s'il porte sur un dossier, et qui l'a annulé quand. `reorg_moves`
        # existe depuis la v1.8 : `create_all` n'y ajoute rien.
        "ALTER TABLE reorg_moves ADD COLUMN IF NOT EXISTS origine TEXT NOT NULL DEFAULT 'ged_reorg'",
        "ALTER TABLE reorg_moves ADD COLUMN IF NOT EXISTS est_dossier BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE reorg_moves ADD COLUMN IF NOT EXISTS annule_le TIMESTAMPTZ",
        "ALTER TABLE reorg_moves ADD COLUMN IF NOT EXISTS annule_par TEXT",
        # Étape 10 (rangement) : un déplacement du Rangement n'a pas forcément de fiche GED, et supprimer
        # une fiche ne doit plus effacer la trace de ses déplacements (décision d'architecture n° 3).
        "ALTER TABLE reorg_moves ALTER COLUMN document_id DROP NOT NULL",
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'reorg_moves_document_id_fkey' "
        "AND confdeltype <> 'n') THEN ALTER TABLE reorg_moves DROP CONSTRAINT reorg_moves_document_id_fkey; "
        "ALTER TABLE reorg_moves ADD CONSTRAINT reorg_moves_document_id_fkey FOREIGN KEY (document_id) "
        "REFERENCES documents(id) ON DELETE SET NULL; END IF; END $$",
        # Étape 11 (rangement) — cloche par personne ou par rôle, dédoublonnée, heures de silence
        # (décision d'architecture n° 4). `notifications` existe depuis le 11/10 : rien par create_all.
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS utilisateur_id UUID "
        "REFERENCES utilisateurs(id) ON DELETE CASCADE",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS pour_role TEXT",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS cle TEXT",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS lien TEXT",
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS visible_le TIMESTAMPTZ",
        "CREATE INDEX IF NOT EXISTS idx_notifications_utilisateur ON notifications (utilisateur_id)",
        # Une seule notification NON LUE par (destinataire, clé) : la suivante la remplace.
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_cle_non_lue ON notifications "
        "(COALESCE(utilisateur_id::text, ''), cle) WHERE NOT lu AND cle IS NOT NULL",
        # Un élément hors plan n'est signalé qu'une fois (la table date de l'étape 9).
        "ALTER TABLE plan_propositions ADD COLUMN IF NOT EXISTS signale_le TIMESTAMPTZ",
        # Règle des séries (15/11/2026) : un pack d'épisodes est vidé dans `Titre/S01`.
        "ALTER TABLE plan_propositions ADD COLUMN IF NOT EXISTS contenu BOOLEAN NOT NULL DEFAULT false",
        # Titre des épisodes (15/11/2026) : renommer sur place, d'après Plex.
        "ALTER TABLE plan_propositions ADD COLUMN IF NOT EXISTS nouveau_nom TEXT",
    ):
        await _migration([ddl])
    # Jobs : types applicatifs (retrait du CHECK type), statut 'cancelled', colonnes de progression.
    if not await _check_conforme("jobs", "jobs_statut_check", statuts_job):
        await _migration([
            "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_type_check",
            "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_statut_check",
            f"ALTER TABLE jobs ADD CONSTRAINT jobs_statut_check "
            f"CHECK (statut IN ({_en_sql(statuts_job)}))",
        ])
    await _migration([
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_message TEXT",
    ])
    # Index jobs (audit du 18/09/2026). `document_id` était filtré partout (anti-double-clic, historique
    # d'un doc, compteur d'échecs répétés) SANS index ; la boucle du worker trie les `pending` par
    # `created_at` sans index non plus. Table de quelques milliers de lignes : un CREATE INDEX simple
    # tient sous le `lock_timeout` ; s'il est reporté, il sera rejoué au prochain démarrage.
    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_jobs_doc_type_statut ON jobs (document_id, type, statut)",
        "CREATE INDEX IF NOT EXISTS idx_jobs_statut_type_created ON jobs (statut, type, created_at)",
        # Liste « Tâches » (sans filtre, triée par date, sondée toutes les 2,5 s par onglet
        # ouvert) : aucun index ne servait ce tri → parcours complet à chaque sondage, d'autant
        # plus lourd que l'historique n'est purgé qu'à la main (audit du 28/09/2026, M5).
        "CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs (created_at DESC)",
    ):
        await _migration([ddl])

    # Colonne dont l'ABSENCE casserait TOUTES les lectures de `documents` (l'ORM la sélectionne) :
    # on ne se contente pas d'un essai « reportable ». On regarde d'abord le catalogue (sans
    # verrou) — donc aucun ACCESS EXCLUSIVE aux démarrages suivants — puis on insiste.
    async def _colonne_garantie(table: str, colonne: str, type_sql: str) -> None:
        await garantir_colonnes(table, {colonne: type_sql})

    await _colonne_garantie("documents", "doublon_de", "UUID")
    # Reprise différée d'un job IA en incident passager (plan lots IA, étape 5) : TOUT le code qui lit
    # `jobs` (l'ORM sélectionne chaque colonne du modèle) en dépend — sans elles, plus aucun job ne
    # démarre. On les GARANTIT donc (catalogue, puis nouveaux essais), en un seul ALTER, au lieu de les
    # laisser à `_migration()` dont un verrou non obtenu est avalé en silence. Rien ne lit ces colonnes
    # avant : le worker démarre APRÈS `init_db` (main.py, lifespan).
    await garantir_colonnes("jobs", {"essais": "INTEGER NOT NULL DEFAULT 0", "pas_avant": "TIMESTAMPTZ"})
    await garantir_colonnes("projets_publieurs", {"depot_cockpit": "BOOLEAN NOT NULL DEFAULT false"})
    # Liste fermée des catégories (prompts A3) : lues par l'ORM à chaque lecture de fiche.
    await garantir_colonnes("metadonnees_ia", {"categorie_origine": "TEXT",
                                               "categorie_manuelle": "BOOLEAN NOT NULL DEFAULT false"})
    await _migration(["CREATE INDEX IF NOT EXISTS idx_documents_doublon_de ON documents (doublon_de) "
                      "WHERE doublon_de IS NOT NULL"])

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

    await _schema_inventaire()

    # Dernier geste du démarrage : dire tout de suite ce qui manquera plus tard.
    await _verifier_colonnes()


async def _schema_inventaire() -> None:
    """
    Tables `inv_*` de l'inventaire (module Rangement) — PostgreSQL seulement.

    Elles ne sont pas dans les modèles ORM (cf. `models/inventaire.py`) : `create_all` ne les
    crée pas, c'est ici que ça se passe. Le backend (2 process) et le worker démarrent ensemble,
    d'où le verrou d'avis ; le catalogue est relu SOUS ce verrou, donc le deuxième arrivé
    constate que tout existe et ne rejoue rien. Comme les autres migrations à chaud, un échec
    est journalisé et reporté au prochain démarrage : il ne doit jamais empêcher de démarrer.
    """
    if not engine.dialect.name.startswith("postgres"):
        return
    from sqlalchemy import text

    from models.inventaire import CLE_VERROU_SCHEMA, appliquer_schema

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL lock_timeout = '4s'"))
            await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": CLE_VERROU_SCHEMA})
            jouees = await appliquer_schema(conn)
        if jouees:
            log.info("Schéma de l'inventaire créé ou complété", instructions=jouees)
    except Exception as e:  # noqa: BLE001 — non bloquant : l'inventaire attendra le prochain démarrage
        log.warning("Schéma de l'inventaire reporté (verrou/timeout)", erreur=str(e) or type(e).__name__)


async def _verifier_colonnes() -> None:
    """
    Compare les colonnes DÉCLARÉES dans les modèles à celles réellement présentes en base, et
    journalise bruyamment les manquantes.

    **Pourquoi ce contrôle existe** *(incident v1.97.0)* : `create_all` ne fait que
    `CREATE TABLE`. Ajouter une colonne à un modèle dont la table existe déjà **ne l'ajoute
    pas** — il faut un `ALTER TABLE … ADD COLUMN IF NOT EXISTS` dans les migrations à chaud
    ci-dessus. L'oubli ne se voit pas au démarrage : l'application démarre normalement, et
    c'est le premier `SELECT` qui échoue, des heures plus tard, sur un écran resté sur
    « Chargement… ».

    **Aucun test ne peut attraper ça** : la suite tourne sous SQLite, où toutes les tables
    sont recréées à neuf à chaque exécution — le schéma y est donc toujours juste. Ce contrôle
    est le seul endroit où l'écart devient visible, et il l'est **à l'endroit où on regarde**,
    les logs du déploiement.

    Il ne corrige rien, volontairement : ajouter une colonne à la volée masquerait l'oubli de
    migration au lieu de le signaler.
    """
    if not engine.dialect.name.startswith("postgres"):
        return   # `information_schema` n'existe pas sous SQLite : rien à vérifier en test

    # `text` et `Base` sont importés localement dans init_db : ici ils manquaient tous les deux
    # (« name 'text' is not defined », puis « name 'Base' is not defined » en 1.104.1).
    from sqlalchemy import text

    from models import Base

    try:
        async with engine.connect() as conn:
            lignes = await conn.execute(text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema()"
            ))
            reelles: dict[str, set[str]] = {}
            for table, colonne in lignes:
                reelles.setdefault(table, set()).add(colonne)

        manquantes = [
            f"{table.name}.{colonne.name}"
            for table in Base.metadata.sorted_tables
            # Table absente = create_all s'en chargera au prochain démarrage : ce n'est pas
            # le défaut qu'on traque ici.
            if (presentes := reelles.get(table.name)) is not None
            for colonne in table.columns
            if colonne.name not in presentes
        ]
    except Exception as e:  # noqa: BLE001 — un contrôle ne doit jamais empêcher de démarrer
        log.warning("Contrôle des colonnes impossible", erreur=str(e) or type(e).__name__)
        return

    if manquantes:
        log.error(
            "COLONNES DÉCLARÉES DANS LES MODÈLES MAIS ABSENTES EN BASE — les requêtes qui les "
            "lisent échoueront. Ajouter un `ALTER TABLE … ADD COLUMN IF NOT EXISTS` dans les "
            "migrations à chaud de database.py",
            colonnes=manquantes, nombre=len(manquantes),
        )
    else:
        log.info("Schéma vérifié : toutes les colonnes des modèles existent en base")


async def close_db() -> None:
    """Ferme le pool de connexions proprement à l'arrêt."""
    await engine.dispose()
