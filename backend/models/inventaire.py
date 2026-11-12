"""
Schéma de l'inventaire (module Rangement) — tables `inv_*`
==========================================================
Repris de l'application « rangement » (`Gestion-des-dossiers/app/inventaire/db.py`), désormais
dans la base de Matothèque (plan `docs/plan-integration-rangement-mails.md`, étape 3).

**Pourquoi du SQL brut et pas des modèles ORM** (décision d'architecture n° 8) : ce schéma repose
sur des index partiels, un index `text_pattern_ops`, un index couvrant (`INCLUDE`), des unicités
sur expression et des réglages de stockage — rien de cela ne s'exprime sous SQLite, où tourne la
suite de tests. Les tables ne sont donc PAS dans `Base.metadata` : `create_all` les ignore, et
c'est `appliquer_schema` (appelée par `database.init_db`, PostgreSQL seulement) qui les crée.
La logique se teste avec le dépôt en mémoire (`tests/fakes/depot_memoire.py`), les requêtes sur
un vrai PostgreSQL (`tests/test_inventaire_depot.py`, variable `INVENTAIRE_TEST_DATABASE_URL`).

Règle d'évolution : uniquement des `CREATE … IF NOT EXISTS`. Le jour où une colonne change, on
ajoute un `ALTER TABLE … ADD COLUMN IF NOT EXISTS` à la suite, jamais en remplacement.

Conventions de chemin : relatif à la racine de l'emplacement, séparateur « / » ; la racine
elle-même est `""`.
"""

import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: Verrou d'avis PostgreSQL : le backend (2 process) et le worker démarrent ensemble, et
#: `CREATE … IF NOT EXISTS` n'est pas atomique face à un concurrent.
CLE_VERROU_SCHEMA = 7261_2001

#: Tables de l'inventaire, dans l'ordre de création (une table référencée vient avant).
TABLES = (
    "inv_postes",
    "inv_emplacements",
    "inv_scans",
    "inv_entrees",
    "inv_doublons_passes",
    "inv_envois",
    "inv_envoi_dossiers",
    "inv_instantanes",
)

SCHEMA_INVENTAIRE: tuple[str, ...] = (
    # Postes : les PC qui portent l'agent. Leur jeton vit avec ceux des automates (`jetons_api`,
    # portée `agent` — décision n° 2) : ici on ne garde que le lien. Jeton supprimé = poste sans
    # jeton, à réappairer ; son inventaire reste.
    """CREATE TABLE IF NOT EXISTS inv_postes (
        id               serial PRIMARY KEY,
        nom              text NOT NULL UNIQUE,
        jeton_id         uuid UNIQUE REFERENCES jetons_api(id) ON DELETE SET NULL,
        actif            boolean NOT NULL DEFAULT true,
        cree_le          timestamptz NOT NULL DEFAULT now(),
        dernier_contact  timestamptz,
        version          text NOT NULL DEFAULT '',
        lecture_jour     date,
        lecture_octets   bigint NOT NULL DEFAULT 0
    )""",
    # Emplacements : une racine à inventorier. `source` dit d'où viennent ses listes — le disque
    # du serveur (NAS monté), un poste qui envoie son inventaire, ou un import WizTree.
    """CREATE TABLE IF NOT EXISTS inv_emplacements (
        id        serial PRIMARY KEY,
        libelle   text NOT NULL,
        racine    text NOT NULL,
        actif     boolean NOT NULL DEFAULT true,
        cree_le   timestamptz NOT NULL DEFAULT now(),
        source    text NOT NULL DEFAULT 'serveur'
                  CHECK (source IN ('serveur', 'agent', 'import')),
        poste_id  integer REFERENCES inv_postes(id)
    )""",
    # Deux PC ont chacun le même dossier utilisateur : la racine est unique par source et par poste.
    """CREATE UNIQUE INDEX IF NOT EXISTS inv_emplacements_racine_unique
        ON inv_emplacements (source, COALESCE(poste_id, 0), racine)""",
    """CREATE TABLE IF NOT EXISTS inv_scans (
        id              bigserial PRIMARY KEY,
        emplacement_id  integer NOT NULL REFERENCES inv_emplacements(id),
        declencheur     text NOT NULL,
        debut           timestamptz NOT NULL DEFAULT now(),
        fin             timestamptz,
        statut          text NOT NULL DEFAULT 'en_cours'
                        CHECK (statut IN ('en_cours', 'termine', 'echec', 'interrompu')),
        nb_dossiers     bigint NOT NULL DEFAULT 0,
        nb_fichiers     bigint NOT NULL DEFAULT 0,
        volume_octets   bigint NOT NULL DEFAULT 0,
        nb_ajouts       bigint NOT NULL DEFAULT 0,
        nb_modifs       bigint NOT NULL DEFAULT 0,
        nb_disparus     bigint NOT NULL DEFAULT 0,
        nb_erreurs      bigint NOT NULL DEFAULT 0,
        message         text NOT NULL DEFAULT ''
    )""",
    # Un seul scan en cours par emplacement : c'est la BASE qui l'interdit, pas un verrou en
    # mémoire — le backend tourne en plusieurs process, plus le worker.
    """CREATE UNIQUE INDEX IF NOT EXISTS inv_scans_un_seul_en_cours
        ON inv_scans (emplacement_id) WHERE statut = 'en_cours'""",
    "CREATE INDEX IF NOT EXISTS inv_scans_par_emplacement ON inv_scans (emplacement_id, id DESC)",
    # Entrées : une ligne par fichier ou dossier vu. `disparu_scan_id` est mis à jour souvent et
    # figure dans le prédicat des index (jamais de mise à jour « HOT ») → nettoyage plus précoce
    # que les 20 % par défaut, et de la place dans chaque page.
    # `taille_totale`… : totaux du sous-arbre, pour les dossiers — la carte se lit sans recalcul.
    # `emp_*` : empreintes SHA-256 (partielle = début + fin ; complète = tout le fichier), avec la
    # taille et la date sur lesquelles elles ont été calculées. Elles ne valent que tant que le
    # fichier n'a pas changé : aucune remise à zéro n'est nécessaire au scan.
    """CREATE TABLE IF NOT EXISTS inv_entrees (
        id                 bigserial PRIMARY KEY,
        emplacement_id     integer NOT NULL REFERENCES inv_emplacements(id),
        chemin             text NOT NULL,
        parent             text NOT NULL,
        nom                text NOT NULL,
        est_dossier        boolean NOT NULL,
        taille             bigint NOT NULL DEFAULT 0,
        mtime              double precision,
        extension          text,
        apparu_scan_id     bigint NOT NULL REFERENCES inv_scans(id),
        modifie_scan_id    bigint REFERENCES inv_scans(id),
        disparu_scan_id    bigint REFERENCES inv_scans(id),
        taille_totale      bigint,
        nb_fichiers_total  bigint,
        nb_dossiers_total  bigint,
        emp_partielle      bytea,
        emp_complete       bytea,
        emp_taille         bigint,
        emp_mtime          double precision
    ) WITH (fillfactor = 90, autovacuum_vacuum_scale_factor = 0.02,
            autovacuum_analyze_scale_factor = 0.02)""",
    # UN seul index sur le chemin, à la fois unicité (cible de l'ON CONFLICT) et préfixe :
    # `chemin LIKE 'x/%'` n'utilise un index qu'avec text_pattern_ops. Deux index texte sur des
    # millions de chemins ne tiendraient pas dans la mémoire de la base.
    """CREATE UNIQUE INDEX IF NOT EXISTS inv_entrees_chemin
        ON inv_entrees (emplacement_id, chemin text_pattern_ops)""",
    # La comparaison lit les enfants PRÉSENTS d'un dossier : c'est la requête chaude du scan.
    """CREATE INDEX IF NOT EXISTS inv_entrees_enfants_presents
        ON inv_entrees (emplacement_id, parent) WHERE disparu_scan_id IS NULL""",
    # « Les plus gros fichiers » : tri par taille parmi les fichiers présents.
    """CREATE INDEX IF NOT EXISTS inv_entrees_gros_fichiers
        ON inv_entrees (emplacement_id, taille DESC)
        WHERE disparu_scan_id IS NULL AND NOT est_dossier""",
    # « Types de fichiers » : regroupement par extension sans relire la table.
    """CREATE INDEX IF NOT EXISTS inv_entrees_types
        ON inv_entrees (emplacement_id, extension) INCLUDE (taille)
        WHERE disparu_scan_id IS NULL AND NOT est_dossier""",
    # Copies, passe 1 : « quelles tailles reviennent plusieurs fois ? » se lit dans cet index seul.
    """CREATE INDEX IF NOT EXISTS inv_entrees_tailles
        ON inv_entrees (taille, emplacement_id)
        WHERE disparu_scan_id IS NULL AND NOT est_dossier""",
    # Écran des copies : regroupement par empreinte, limité aux fichiers déjà relus.
    """CREATE INDEX IF NOT EXISTS inv_entrees_empreintes
        ON inv_entrees (emp_complete)
        WHERE emp_complete IS NOT NULL AND disparu_scan_id IS NULL""",
    """CREATE TABLE IF NOT EXISTS inv_doublons_passes (
        id             bigserial PRIMARY KEY,
        debut          timestamptz NOT NULL DEFAULT now(),
        fin            timestamptz,
        statut         text NOT NULL DEFAULT 'en_cours'
                       CHECK (statut IN ('en_cours', 'termine', 'limite', 'hors_fenetre', 'echec',
                                         'interrompu')),
        octets_lus     bigint NOT NULL DEFAULT 0,
        nb_partielles  bigint NOT NULL DEFAULT 0,
        nb_completes   bigint NOT NULL DEFAULT 0,
        nb_erreurs     bigint NOT NULL DEFAULT 0,
        nb_changes     bigint NOT NULL DEFAULT 0,
        nb_reportes    bigint NOT NULL DEFAULT 0,
        message        text NOT NULL DEFAULT ''
    )""",
    # Une seule passe à la fois, garanti par la base (comme les scans).
    """CREATE UNIQUE INDEX IF NOT EXISTS inv_doublons_une_seule_passe
        ON inv_doublons_passes ((true)) WHERE statut = 'en_cours'""",
    # Envois : les listes de dossiers d'un agent ou d'un import, reçues par lots puis relues par
    # le scan. Effacées une fois traitées.
    """CREATE TABLE IF NOT EXISTS inv_envois (
        id              bigserial PRIMARY KEY,
        emplacement_id  integer NOT NULL REFERENCES inv_emplacements(id),
        debut           timestamptz NOT NULL DEFAULT now(),
        fin             timestamptz,
        statut          text NOT NULL DEFAULT 'reception'
                        CHECK (statut IN ('reception', 'traitement', 'traite', 'abandonne')),
        nb_dossiers     bigint NOT NULL DEFAULT 0
    )""",
    """CREATE UNIQUE INDEX IF NOT EXISTS inv_envois_un_seul_actif
        ON inv_envois (emplacement_id) WHERE statut IN ('reception', 'traitement')""",
    """CREATE TABLE IF NOT EXISTS inv_envoi_dossiers (
        envoi_id    bigint NOT NULL REFERENCES inv_envois(id) ON DELETE CASCADE,
        chemin      text NOT NULL,
        illisible   boolean NOT NULL DEFAULT false,
        enfants     jsonb NOT NULL DEFAULT '[]',
        illisibles  jsonb NOT NULL DEFAULT '[]',
        PRIMARY KEY (envoi_id, chemin)
    )""",
    # Instantanés : la taille des dossiers de tête à chaque scan, pour dire « ça a grossi ».
    """CREATE TABLE IF NOT EXISTS inv_instantanes (
        scan_id        bigint NOT NULL REFERENCES inv_scans(id) ON DELETE CASCADE,
        chemin         text NOT NULL,
        profondeur     smallint NOT NULL,
        taille_totale  bigint NOT NULL,
        nb_fichiers    bigint NOT NULL,
        nb_dossiers    bigint NOT NULL,
        PRIMARY KEY (scan_id, chemin)
    )""",
)

_CREATION_TABLE = re.compile(r"^\s*CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\b", re.I)
_CREATION_INDEX = re.compile(r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\s+(\w+)\b", re.I)


def instructions_manquantes(tables: set[str], index: set[str]) -> list[str]:
    """
    Les instructions du schéma qui restent à jouer, vu ce qui existe déjà. Fonction PURE.

    Rejouer un `CREATE INDEX IF NOT EXISTS` déjà fait n'est pas gratuit : PostgreSQL verrouille
    la table avant de constater que l'index existe, et un scan qui écrit dans `inv_entrees`
    pendant des heures ferait attendre le démarrage. On ne rejoue donc que ce qui manque.
    """
    manquantes: list[str] = []
    for sql in SCHEMA_INVENTAIRE:
        m = _CREATION_TABLE.match(sql)
        if m:
            if m.group(1).lower() not in tables:
                manquantes.append(sql)
            continue
        m = _CREATION_INDEX.match(sql)
        if m and m.group(1).lower() in index:
            continue
        manquantes.append(sql)   # index absent, ou forme non reconnue : rejouée (idempotente)
    return manquantes


async def appliquer_schema(conn: AsyncConnection) -> int:
    """
    Crée ce qui manque du schéma `inv_*` dans le schéma courant. Renvoie le nombre
    d'instructions jouées (0 = tout existait). L'appelant fournit la transaction — et, au
    démarrage de l'application, le verrou d'avis et le `lock_timeout`.
    """
    tables = {r[0] for r in await conn.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))}
    index = {r[0] for r in await conn.execute(text(
        "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"))}
    a_jouer = instructions_manquantes(tables, index)
    for sql in a_jouer:
        await conn.execute(text(sql))
    return len(a_jouer)
