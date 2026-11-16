"""
Dépôt de l'inventaire dans PostgreSQL — l'implémentation de production du contrat `Depot`.

Porté de l'application « rangement » (`app/inventaire/depot_postgres.py`, psycopg synchrone) vers
le moteur async de Matothèque. Ce qui est conservé :

- **une transaction courte par opération**. Un scan interrompu garde ce qu'il a déjà enregistré,
  et aucune transaction ne reste ouverte pendant qu'on parcourt un disque ;
- **les écritures d'un même dossier passent ensemble** (`executemany` dans une transaction), sans
  quoi un premier scan de 500 000 entrées ferait 500 000 validations ;
- `synchronous_commit = off` sur les écritures : l'inventaire se reconstruit au scan suivant,
  perdre les dernières lignes d'un arrêt brutal est acceptable. Le réglage est posé **par
  transaction** (`SET LOCAL`) : les connexions viennent du pool commun, on ne le laisse pas
  déborder sur le reste de l'application.

Toutes les requêtes sont paramétrées. Seul piège réel : la disparition d'un sous-arbre utilise
`LIKE 'x/%'`, où `%` et `_` sont des jokers — un dossier « 100%_bio » emporterait « 100x_bio »
sans l'échappement de `_motif_prefixe`.

⚠️ Sous SQLAlchemy, ne jamais écrire `:param::type` (le `::` casse le repérage du paramètre) :
`CAST(:param AS type)`.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from services.rangement.depot import (
    Bilan,
    Compteurs,
    Connu,
    Copie,
    DossierEnvoye,
    DoublonRacine,
    Element,
    Emplacement,
    EnvoiEnCours,
    Fichier,
    Groupe,
    LigneInstantane,
    PasseEnCours,
    Poste,
    PosteEnDouble,
    RecuperableLieu,
    ResumePasse,
    ScanEnCours,
    chemin_enfant,
    extension,
)

COLONNES_SCAN = ("nb_dossiers", "nb_fichiers", "volume_octets", "nb_ajouts", "nb_modifs",
                 "nb_disparus", "nb_erreurs")

_COLONNES_EMPLACEMENT = "id, libelle, racine, actif, source, poste_id, source_id::text, partage, sous_dossier"
_EMPLACEMENT = f"SELECT {_COLONNES_EMPLACEMENT} FROM inv_emplacements"   # noqa: S608 — fragment constant
_COLONNES_POSTE = "id, nom, actif, dernier_contact, version, lecture_jour, lecture_octets, jeton_id"
_POSTE = f"SELECT {_COLONNES_POSTE} FROM inv_postes"   # noqa: S608 — fragment constant
_COLONNES_CONNU = "nom, est_dossier, taille, mtime, taille_totale, nb_fichiers_total, nb_dossiers_total"
_COLONNES_FICHIER = ("id, emplacement_id, chemin, taille, mtime, emp_partielle, emp_complete, "
                     "emp_taille, emp_mtime")

# Les requêtes des copies assemblent ces deux fragments CONSTANTS : la règle « empreinte
# valable » n'existe ainsi qu'une fois. Les valeurs, elles, restent paramétrées.
_PRESENTS = "disparu_scan_id IS NULL AND NOT est_dossier AND emplacement_id = ANY(:emps)"
#: Empreinte complète valable : calculée sur la taille et la date connues aujourd'hui.
_VALIDE = "emp_complete IS NOT NULL AND emp_taille = taille AND emp_mtime = mtime"

_BIGINT_MAX = 2**63 - 1


def _octets(valeur: Any) -> bytes | None:
    """`bytea` arrive en `memoryview` ou en `bytes` selon le pilote : on rend des `bytes`."""
    return None if valeur is None else bytes(valeur)


def _motif_prefixe(chemin: str) -> str:
    echappe = chemin.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return echappe + "/%"


def _json(valeur: Any) -> Any:
    """Une colonne `jsonb` lue par une requête brute arrive en texte : on la décode."""
    return json.loads(valeur) if isinstance(valeur, (str, bytes)) else valeur


def _unicite(exc: IntegrityError) -> bool:
    """Violation d'unicité (23505) — et non une clé étrangère absente, qui doit remonter telle quelle."""
    origine = exc.orig
    code = getattr(origine, "sqlstate", None) or getattr(origine, "pgcode", None)
    return code == "23505"


def _connu(r: Any) -> Connu:
    return Connu(r[0], r[1], int(r[2]), r[3], None if r[4] is None else (int(r[4]), int(r[5]), int(r[6])))


def _fichier(r: Any) -> Fichier:
    return Fichier(int(r[0]), int(r[1]), r[2], int(r[3]), r[4], _octets(r[5]), _octets(r[6]), r[7], r[8])


def _poste(r: Any) -> Poste:
    return Poste(int(r[0]), r[1], r[2], r[3], r[4], r[5], int(r[6]),
                 None if r[7] is None else uuid.UUID(str(r[7])))


class DepotPostgres:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        #: Nombre de lignes d'entrées écrites (ajout, modification, disparition, totaux).
        self.ecritures_entrees = 0

    # ------------------------------------------------------------------- accès base
    @asynccontextmanager
    async def _ecriture(self) -> AsyncIterator[AsyncConnection]:
        async with self._engine.begin() as conn:
            await conn.execute(text("SET LOCAL synchronous_commit = off"))
            yield conn

    async def _lignes(self, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
        async with self._engine.connect() as conn:
            return list((await conn.execute(text(sql), params or {})).all())

    async def _ligne(self, sql: str, params: dict[str, Any] | None = None) -> Any | None:
        async with self._engine.connect() as conn:
            return (await conn.execute(text(sql), params or {})).first()

    async def _dict(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            ligne = (await conn.execute(text(sql), params or {})).mappings().first()
        return dict(ligne) if ligne is not None else None

    async def _executer(self, sql: str, params: dict[str, Any] | None = None) -> int:
        """Une écriture seule, dans sa transaction. Renvoie le nombre de lignes touchées."""
        async with self._ecriture() as conn:
            return (await conn.execute(text(sql), params or {})).rowcount or 0

    # ----------------------------------------------------------------- emplacements
    async def emplacements(self, actifs_seulement: bool = False) -> list[Emplacement]:
        sql = _EMPLACEMENT + (" WHERE actif" if actifs_seulement else "") + " ORDER BY id"
        return [Emplacement(*r) for r in await self._lignes(sql)]

    async def emplacement(self, emplacement_id: int) -> Emplacement | None:
        r = await self._ligne(_EMPLACEMENT + " WHERE id = :id", {"id": emplacement_id})
        return Emplacement(*r) if r else None

    async def creer_emplacement(self, libelle: str, racine: str, source: str = "serveur",
                                poste_id: int | None = None, *, source_id: str | None = None,
                                partage: str | None = None, sous_dossier: str | None = None) -> Emplacement:
        try:
            async with self._ecriture() as conn:
                r = (await conn.execute(text(
                    "INSERT INTO inv_emplacements (libelle, racine, source, poste_id, source_id, partage, "
                    "sous_dossier) VALUES (:libelle, :racine, :source, :poste_id, CAST(:source_id AS uuid), "
                    f":partage, :sous_dossier) RETURNING {_COLONNES_EMPLACEMENT}"),
                    {"libelle": libelle, "racine": racine, "source": source, "poste_id": poste_id,
                     "source_id": source_id, "partage": partage, "sous_dossier": sous_dossier})).one()
        except IntegrityError as exc:
            if _unicite(exc):
                raise DoublonRacine(racine) from exc
            raise
        return Emplacement(*r)

    async def activer_emplacement(self, emplacement_id: int, actif: bool) -> None:
        await self._executer("UPDATE inv_emplacements SET actif = :actif WHERE id = :id",
                             {"actif": actif, "id": emplacement_id})

    async def rebrancher_emplacement(self, emplacement_id: int, *, racine: str, source: str,
                                     source_id: str | None, partage: str | None, sous_dossier: str | None,
                                     prefixe: str = "") -> tuple[int, int]:
        p = {"emp": emplacement_id}
        try:
            async with self._engine.begin() as conn:   # synchronous_commit normal : c'est un geste unique
                retirees = 0
                if prefixe:
                    # Pas de LIKE (jokers « % » et « _ ») : comparaison de préfixe par substr. Réécriture
                    # en deux temps derrière un marqueur (\x01, jamais dans un nom de fichier) : un
                    # dossier « P/P/x » devenant « P/x » ne heurte pas l'index unique (emplacement, chemin).
                    q = {**p, "pre": prefixe, "sl": prefixe + "/", "n": len(prefixe) + 1, "m": "\x01",
                         "prof": prefixe.count("/") + 1}
                    retirees = (await conn.execute(text(
                        "DELETE FROM inv_entrees WHERE emplacement_id = :emp "
                        "AND substr(chemin, 1, :n) <> :sl"), q)).rowcount
                    await conn.execute(text(
                        "UPDATE inv_entrees SET chemin = :m || substr(chemin, :n + 1), "
                        "parent = CASE WHEN parent = :pre THEN '' ELSE substr(parent, :n + 1) END "
                        "WHERE emplacement_id = :emp"), q)
                    await conn.execute(text(
                        "UPDATE inv_entrees SET chemin = substr(chemin, 2) "
                        "WHERE emplacement_id = :emp AND substr(chemin, 1, 1) = :m"), q)
                    scans = "scan_id IN (SELECT id FROM inv_scans WHERE emplacement_id = :emp)"
                    await conn.execute(text(
                        f"DELETE FROM inv_instantanes WHERE {scans} "  # noqa: S608 — fragment constant
                        "AND chemin <> :pre AND substr(chemin, 1, :n) <> :sl"), q)
                    await conn.execute(text(
                        "UPDATE inv_instantanes SET profondeur = profondeur - :prof, chemin = :m || "  # noqa: S608
                        f"CASE WHEN chemin = :pre THEN '' ELSE substr(chemin, :n + 1) END WHERE {scans}"), q)
                    await conn.execute(text(
                        "UPDATE inv_instantanes SET chemin = substr(chemin, 2) "  # noqa: S608
                        f"WHERE {scans} AND substr(chemin, 1, 1) = :m"), q)
                await conn.execute(text(
                    "UPDATE inv_emplacements SET racine = :racine, source = :source, "
                    "source_id = CAST(:source_id AS uuid), partage = :partage, sous_dossier = :sous_dossier "
                    "WHERE id = :emp"),
                    {**p, "racine": racine, "source": source, "source_id": source_id, "partage": partage,
                     "sous_dossier": sous_dossier})
                gardees = (await conn.execute(text(
                    "SELECT count(*) FROM inv_entrees WHERE emplacement_id = :emp"), p)).scalar_one()
        except IntegrityError as exc:
            if _unicite(exc):
                raise DoublonRacine(racine) from exc
            raise
        return int(gardees), int(retirees)

    # ----------------------------------------------------------------------- scans
    async def ouvrir_scan(self, emplacement_id: int, declencheur: str) -> int:
        try:
            async with self._ecriture() as conn:
                r = (await conn.execute(text(
                    "INSERT INTO inv_scans (emplacement_id, declencheur) VALUES (:emp, :declencheur) "
                    "RETURNING id"), {"emp": emplacement_id, "declencheur": declencheur})).one()
        except IntegrityError as exc:
            if _unicite(exc):
                raise ScanEnCours(emplacement_id) from exc
            raise
        return int(r[0])

    async def fermer_scan(self, scan_id: int, statut: str, compteurs: Compteurs, message: str = "") -> None:
        params = {c: getattr(compteurs, c) for c in COLONNES_SCAN}
        await self._executer(
            "UPDATE inv_scans SET statut = :statut, fin = now(), message = :message, "
            "nb_dossiers = :nb_dossiers, nb_fichiers = :nb_fichiers, volume_octets = :volume_octets, "
            "nb_ajouts = :nb_ajouts, nb_modifs = :nb_modifs, nb_disparus = :nb_disparus, "
            "nb_erreurs = :nb_erreurs WHERE id = :id",
            {**params, "statut": statut, "message": message, "id": scan_id})

    async def interrompre_scans_orphelins(self, age_heures: int) -> int:
        return await self._executer(
            "UPDATE inv_scans SET statut = 'interrompu', fin = now(), "
            "message = 'scan resté « en cours » : interrompu' "
            "WHERE statut = 'en_cours' AND debut < now() - make_interval(hours => :h)", {"h": age_heures})

    async def dernier_scan(self, emplacement_id: int, termine_seulement: bool = False) -> dict[str, Any] | None:
        filtre = " AND statut = 'termine'" if termine_seulement else ""
        return await self._dict(
            f"SELECT * FROM inv_scans WHERE emplacement_id = :emp{filtre} ORDER BY id DESC LIMIT 1",  # noqa: S608
            {"emp": emplacement_id})

    async def scan_en_cours(self) -> bool:
        r = await self._ligne("SELECT EXISTS (SELECT 1 FROM inv_scans WHERE statut = 'en_cours')")
        return bool(r[0])

    # --------------------------------------------------------------------- entrées
    async def a_des_entrees(self, emplacement_id: int) -> bool:
        r = await self._ligne("SELECT EXISTS (SELECT 1 FROM inv_entrees WHERE emplacement_id = :emp "
                              "AND disparu_scan_id IS NULL)", {"emp": emplacement_id})
        return bool(r[0])

    async def enfants(self, emplacement_id: int, parent: str) -> dict[str, Connu]:
        lignes = await self._lignes(
            f"SELECT {_COLONNES_CONNU} FROM inv_entrees "  # noqa: S608
            "WHERE emplacement_id = :emp AND parent = :parent AND disparu_scan_id IS NULL",
            {"emp": emplacement_id, "parent": parent})
        return {r[0]: _connu(r) for r in lignes}

    async def ajouter(self, emplacement_id: int, scan_id: int, parent: str, elements: list[Element]) -> None:
        if not elements:
            return
        async with self._ecriture() as conn:
            await conn.execute(text(
                "INSERT INTO inv_entrees (emplacement_id, chemin, parent, nom, est_dossier, taille, mtime, "
                "extension, apparu_scan_id) VALUES (:emp, :chemin, :parent, :nom, :est_dossier, :taille, "
                ":mtime, :extension, :scan) "
                # Réapparition : la ligne revit, son historique (apparu_scan_id) reste.
                "ON CONFLICT (emplacement_id, chemin text_pattern_ops) DO UPDATE "
                "SET est_dossier = EXCLUDED.est_dossier, taille = EXCLUDED.taille, mtime = EXCLUDED.mtime, "
                "extension = EXCLUDED.extension, disparu_scan_id = NULL, "
                "modifie_scan_id = EXCLUDED.apparu_scan_id"),
                [{"emp": emplacement_id, "chemin": chemin_enfant(parent, el.nom), "parent": parent,
                  "nom": el.nom, "est_dossier": el.est_dossier, "taille": el.taille, "mtime": el.mtime,
                  "extension": extension(el), "scan": scan_id} for el in elements])
        self.ecritures_entrees += len(elements)

    async def modifier(self, emplacement_id: int, scan_id: int, parent: str, elements: list[Element]) -> None:
        if not elements:
            return
        async with self._ecriture() as conn:
            await conn.execute(text(
                "UPDATE inv_entrees SET est_dossier = :est_dossier, taille = :taille, mtime = :mtime, "
                "extension = :extension, modifie_scan_id = :scan "
                "WHERE emplacement_id = :emp AND chemin = :chemin"),
                [{"est_dossier": el.est_dossier, "taille": el.taille, "mtime": el.mtime,
                  "extension": extension(el), "scan": scan_id, "emp": emplacement_id,
                  "chemin": chemin_enfant(parent, el.nom)} for el in elements])
        self.ecritures_entrees += len(elements)

    async def marquer_disparus(self, emplacement_id: int, scan_id: int, parent: str, noms: list[str]) -> int:
        n = 0
        if not noms:
            return n
        async with self._ecriture() as conn:
            for nom in noms:
                cible = chemin_enfant(parent, nom)
                res = await conn.execute(text(
                    "UPDATE inv_entrees SET disparu_scan_id = :scan WHERE emplacement_id = :emp "
                    "AND disparu_scan_id IS NULL AND (chemin = :cible OR chemin LIKE :motif ESCAPE '\\')"),
                    {"scan": scan_id, "emp": emplacement_id, "cible": cible, "motif": _motif_prefixe(cible)})
                n += res.rowcount or 0
        self.ecritures_entrees += n
        return n

    async def mettre_a_jour_totaux(self, emplacement_id: int, parent: str,
                                   totaux: list[tuple[str, int, int, int]]) -> None:
        if not totaux:
            return
        async with self._ecriture() as conn:
            await conn.execute(text(
                "UPDATE inv_entrees SET taille_totale = :taille, nb_fichiers_total = :fichiers, "
                "nb_dossiers_total = :dossiers WHERE emplacement_id = :emp AND chemin = :chemin"),
                [{"taille": t, "fichiers": f, "dossiers": d, "emp": emplacement_id,
                  "chemin": chemin_enfant(parent, nom)} for nom, t, f, d in totaux])
        self.ecritures_entrees += len(totaux)

    # ------------------------------------------------------------------ instantanés
    async def enregistrer_instantane(self, scan_id: int, lignes: list[LigneInstantane]) -> None:
        if not lignes:
            return
        async with self._ecriture() as conn:
            await conn.execute(text(
                "INSERT INTO inv_instantanes (scan_id, chemin, profondeur, taille_totale, nb_fichiers, "
                "nb_dossiers) VALUES (:scan, :chemin, :profondeur, :taille, :fichiers, :dossiers)"),
                [{"scan": scan_id, "chemin": li.chemin, "profondeur": li.profondeur,
                  "taille": li.taille_totale, "fichiers": li.nb_fichiers, "dossiers": li.nb_dossiers}
                 for li in lignes])

    async def purger_instantanes(self, emplacement_id: int, garder: int) -> int:
        return await self._executer(
            "DELETE FROM inv_instantanes WHERE scan_id IN ("
            " SELECT DISTINCT i.scan_id FROM inv_instantanes i JOIN inv_scans s ON s.id = i.scan_id"
            " WHERE s.emplacement_id = :emp ORDER BY i.scan_id DESC OFFSET :garder)",
            {"emp": emplacement_id, "garder": garder})

    async def scans_avec_instantane(self, emplacement_id: int, n: int) -> list[int]:
        lignes = await self._lignes(
            "SELECT DISTINCT i.scan_id FROM inv_instantanes i JOIN inv_scans s ON s.id = i.scan_id "
            "WHERE s.emplacement_id = :emp ORDER BY i.scan_id DESC LIMIT :n", {"emp": emplacement_id, "n": n})
        return [int(r[0]) for r in lignes]

    async def tailles_instantane(self, scan_id: int) -> dict[str, int]:
        lignes = await self._lignes("SELECT chemin, taille_totale FROM inv_instantanes WHERE scan_id = :scan",
                                    {"scan": scan_id})
        return {r[0]: int(r[1]) for r in lignes}

    # ------------------------------------------------------------------ lecture carte
    async def dossier(self, emplacement_id: int, chemin: str) -> Connu | None:
        r = await self._ligne(
            f"SELECT {_COLONNES_CONNU} FROM inv_entrees WHERE emplacement_id = :emp AND chemin = :chemin "  # noqa: S608
            "AND est_dossier AND disparu_scan_id IS NULL", {"emp": emplacement_id, "chemin": chemin})
        return _connu(r) if r else None

    async def enfants_tries(self, emplacement_id: int, parent: str, limite: int) -> tuple[list[Connu], int]:
        params = {"emp": emplacement_id, "parent": parent}
        lignes = await self._lignes(
            f"SELECT {_COLONNES_CONNU} FROM inv_entrees "  # noqa: S608
            "WHERE emplacement_id = :emp AND parent = :parent AND disparu_scan_id IS NULL "
            "ORDER BY CASE WHEN est_dossier THEN COALESCE(taille_totale, 0) ELSE taille END DESC, nom "
            "LIMIT :limite", {**params, "limite": limite})
        total = await self._ligne(
            "SELECT count(*) FROM inv_entrees WHERE emplacement_id = :emp AND parent = :parent "
            "AND disparu_scan_id IS NULL", params)
        return [_connu(r) for r in lignes], int(total[0])

    async def repartition_types(self, emplacement_id: int, prefixe: str) -> list[tuple[str | None, int, int]]:
        params: dict[str, Any] = {"emp": emplacement_id}
        filtre = ""
        if prefixe:
            filtre = " AND chemin LIKE :motif ESCAPE '\\'"
            params["motif"] = _motif_prefixe(prefixe)
        lignes = await self._lignes(
            "SELECT extension, count(*), COALESCE(sum(taille), 0) FROM inv_entrees "  # noqa: S608
            f"WHERE emplacement_id = :emp AND disparu_scan_id IS NULL AND NOT est_dossier{filtre} "
            "GROUP BY extension", params)
        return [(r[0], int(r[1]), int(r[2])) for r in lignes]

    async def plus_gros_fichiers(self, emplacement_id: int, prefixe: str, limite: int) -> list[tuple[str, int]]:
        params: dict[str, Any] = {"emp": emplacement_id, "limite": limite}
        filtre = ""
        if prefixe:
            filtre = " AND chemin LIKE :motif ESCAPE '\\'"
            params["motif"] = _motif_prefixe(prefixe)
        lignes = await self._lignes(
            "SELECT chemin, taille FROM inv_entrees WHERE emplacement_id = :emp "  # noqa: S608
            f"AND disparu_scan_id IS NULL AND NOT est_dossier{filtre} "
            "ORDER BY taille DESC, chemin LIMIT :limite", params)
        return [(r[0], int(r[1])) for r in lignes]

    async def fichiers(self, emplacement_id: int, prefixe: str) -> list[tuple[str, int]]:
        """Tous les fichiers présents (chemin, taille) — statistiques des noms (`nommage.py`)."""
        params: dict[str, Any] = {"emp": emplacement_id}
        filtre = ""
        if prefixe:
            filtre = " AND chemin LIKE :motif ESCAPE '\\'"
            params["motif"] = _motif_prefixe(prefixe)
        lignes = await self._lignes(
            "SELECT chemin, taille FROM inv_entrees WHERE emplacement_id = :emp "  # noqa: S608
            f"AND disparu_scan_id IS NULL AND NOT est_dossier{filtre} ORDER BY chemin", params)
        return [(r[0], int(r[1])) for r in lignes]

    async def nommage_memorise(self, emplacement_id: int, chemin: str) -> tuple[str, dict[str, Any]] | None:
        r = await self._ligne("SELECT cle, bilan FROM inv_nommage WHERE emplacement_id = :emp AND chemin = :ch",
                              {"emp": emplacement_id, "ch": chemin})
        if r is None:
            return None
        bilan = r[1] if isinstance(r[1], dict) else json.loads(r[1])
        return r[0], bilan

    async def memoriser_nommage(self, emplacement_id: int, chemin: str, cle: str, bilan: dict[str, Any]) -> None:
        await self._executer(
            "INSERT INTO inv_nommage (emplacement_id, chemin, cle, bilan) "
            "VALUES (:emp, :ch, :cle, CAST(:bilan AS jsonb)) "
            "ON CONFLICT (emplacement_id, chemin) DO UPDATE SET cle = EXCLUDED.cle, bilan = EXCLUDED.bilan, "
            "calcule_le = now()",
            {"emp": emplacement_id, "ch": chemin, "cle": cle, "bilan": json.dumps(bilan)})

    async def oublier_nommage(self, emplacement_id: int, sauf_cle: str) -> int:
        return await self._executer("DELETE FROM inv_nommage WHERE emplacement_id = :emp AND cle <> :cle",
                                    {"emp": emplacement_id, "cle": sauf_cle})

    # ------------------------------------------------------------- copies sur disque
    async def tailles_en_double(self, emplacements: list[int], taille_min: int, sous: int | None,
                                limite: int) -> list[int]:
        lignes = await self._lignes(
            f"SELECT taille FROM inv_entrees WHERE {_PRESENTS} AND taille >= :min AND taille < :sous "  # noqa: S608
            "GROUP BY taille HAVING count(*) >= 2 ORDER BY taille DESC LIMIT :limite",
            {"emps": emplacements, "min": taille_min, "sous": sous if sous is not None else _BIGINT_MAX,
             "limite": limite})
        return [int(r[0]) for r in lignes]

    async def fichiers_de_taille(self, emplacements: list[int], taille: int) -> list[Fichier]:
        lignes = await self._lignes(
            f"SELECT {_COLONNES_FICHIER} FROM inv_entrees WHERE {_PRESENTS} AND taille = :taille "  # noqa: S608
            "ORDER BY emplacement_id, chemin", {"emps": emplacements, "taille": taille})
        return [_fichier(r) for r in lignes]

    async def fichier(self, entree_id: int) -> Fichier | None:
        r = await self._ligne(
            f"SELECT {_COLONNES_FICHIER} FROM inv_entrees "  # noqa: S608
            "WHERE id = :id AND disparu_scan_id IS NULL AND NOT est_dossier", {"id": entree_id})
        return _fichier(r) if r else None

    async def enregistrer_empreinte(self, entree_id: int, partielle: bytes, complete: bytes | None,
                                    taille: int, mtime: float | None) -> None:
        await self._executer(
            "UPDATE inv_entrees SET emp_partielle = :partielle, emp_complete = :complete, "
            "emp_taille = :taille, emp_mtime = :mtime WHERE id = :id",
            {"partielle": partielle, "complete": complete, "taille": taille, "mtime": mtime, "id": entree_id})

    async def groupes_identiques(self, emplacements: list[int], limite: int,
                                 emplacement_id: int | None = None) -> list[Groupe]:
        filtre = "HAVING count(*) >= 2"
        params: dict[str, Any] = {"emps": emplacements, "limite": limite}
        if emplacement_id is not None:
            filtre += " AND bool_or(emplacement_id = :emp)"
            params["emp"] = emplacement_id
        lignes = await self._lignes(
            "SELECT emp_complete, taille, array_agg(emplacement_id ORDER BY emplacement_id, chemin), "  # noqa: S608
            "array_agg(chemin ORDER BY emplacement_id, chemin) "
            f"FROM inv_entrees WHERE {_PRESENTS} AND {_VALIDE} "
            f"GROUP BY emp_complete, taille {filtre} "
            "ORDER BY taille * (count(*) - 1) DESC, taille DESC, min(chemin) LIMIT :limite", params)
        return [Groupe(bytes(r[0]), int(r[1]),
                       tuple(Copie(int(e), c) for e, c in zip(r[2], r[3], strict=True)))
                for r in lignes]

    async def bilan_identiques(self, emplacements: list[int]) -> Bilan:
        r = await self._ligne(
            "SELECT COALESCE(sum(taille * (n - 1)), 0), count(*), COALESCE(sum(n - 1), 0) FROM ("  # noqa: S608
            f" SELECT taille, count(*) AS n FROM inv_entrees WHERE {_PRESENTS} AND {_VALIDE}"
            " GROUP BY emp_complete, taille HAVING count(*) >= 2) g", {"emps": emplacements})
        return Bilan(int(r[0]), int(r[1]), int(r[2]))

    async def recuperable_par_emplacement(self, emplacements: list[int]) -> dict[int, RecuperableLieu]:
        lignes = await self._lignes(
            "WITH lieu AS ("  # noqa: S608
            " SELECT emp_complete, taille, emplacement_id, count(*) AS n FROM inv_entrees"
            f" WHERE {_PRESENTS} AND {_VALIDE} GROUP BY emp_complete, taille, emplacement_id),"
            " total AS (SELECT emp_complete, taille, sum(n) AS n FROM lieu GROUP BY emp_complete, taille"
            " HAVING sum(n) >= 2) "
            "SELECT l.emplacement_id, sum(l.taille * (l.n - 1)),"
            " sum(CASE WHEN t.n > l.n THEN l.taille * l.n ELSE 0 END) "
            "FROM lieu l JOIN total t USING (emp_complete, taille) GROUP BY l.emplacement_id",
            {"emps": emplacements})
        return {int(r[0]): RecuperableLieu(int(r[1]), int(r[2])) for r in lignes}

    async def empreintes_a_calculer(self, emplacement_id: int, emplacements: list[int], taille_min: int,
                                    limite: int) -> list[tuple[Fichier, str]]:
        """Ce que le POSTE doit lire : partielles des fichiers dont la taille est partagée, puis
        complètes de ceux dont la partielle est partagée — même règle que la passe du serveur,
        exprimée en SQL."""
        a_jour = "e.emp_taille = e.taille AND e.emp_mtime = e.mtime"
        autre = ("o.id <> e.id AND o.disparu_scan_id IS NULL AND NOT o.est_dossier "
                 "AND o.emplacement_id = ANY(:emps)")
        colonnes = ", ".join(f"e.{c.strip()}" for c in _COLONNES_FICHIER.split(","))
        base = ("FROM inv_entrees e WHERE e.emplacement_id = :emp AND e.disparu_scan_id IS NULL "
                "AND NOT e.est_dossier AND e.taille >= :min")
        params = {"emp": emplacement_id, "emps": emplacements, "min": taille_min, "n": limite}
        partielles = await self._lignes(
            f"SELECT {colonnes} {base} AND NOT (e.emp_partielle IS NOT NULL AND {a_jour}) "  # noqa: S608
            f"AND EXISTS (SELECT 1 FROM inv_entrees o WHERE o.taille = e.taille AND {autre}) "
            "ORDER BY e.taille DESC, e.id LIMIT :n", params)
        completes = await self._lignes(
            f"SELECT {colonnes} {base} AND e.emp_partielle IS NOT NULL AND {a_jour} "  # noqa: S608
            "AND e.emp_complete IS NULL "
            f"AND EXISTS (SELECT 1 FROM inv_entrees o WHERE o.taille = e.taille AND {autre} "
            "AND o.emp_partielle = e.emp_partielle AND o.emp_taille = o.taille AND o.emp_mtime = o.mtime) "
            "ORDER BY e.taille DESC, e.id LIMIT :n", params)
        sortie = [(_fichier(r), "partielle") for r in partielles]
        sortie += [(_fichier(r), "complete") for r in completes]
        return sortie[:limite]

    async def ouvrir_passe(self) -> int:
        try:
            async with self._ecriture() as conn:
                r = (await conn.execute(text(
                    "INSERT INTO inv_doublons_passes DEFAULT VALUES RETURNING id"))).one()
        except IntegrityError as exc:
            if _unicite(exc):
                raise PasseEnCours() from exc
            raise
        return int(r[0])

    async def avancer_passe(self, passe_id: int, octets_lus: int) -> None:
        await self._executer("UPDATE inv_doublons_passes SET octets_lus = :octets WHERE id = :id",
                             {"octets": octets_lus, "id": passe_id})

    async def fermer_passe(self, passe_id: int, statut: str, resume: ResumePasse, message: str = "") -> None:
        await self._executer(
            "UPDATE inv_doublons_passes SET statut = :statut, fin = now(), message = :message, "
            "octets_lus = :octets_lus, nb_partielles = :nb_partielles, nb_completes = :nb_completes, "
            "nb_erreurs = :nb_erreurs, nb_changes = :nb_changes, nb_reportes = :nb_reportes WHERE id = :id",
            {"statut": statut, "message": message, "octets_lus": resume.octets_lus,
             "nb_partielles": resume.nb_partielles, "nb_completes": resume.nb_completes,
             "nb_erreurs": resume.nb_erreurs, "nb_changes": resume.nb_changes,
             "nb_reportes": resume.nb_reportes, "id": passe_id})

    async def interrompre_passes_orphelines(self, age_heures: int) -> int:
        return await self._executer(
            "UPDATE inv_doublons_passes SET statut = 'interrompu', fin = now(), "
            "message = 'passe restée « en cours » : interrompue' "
            "WHERE statut = 'en_cours' AND debut < now() - make_interval(hours => :h)", {"h": age_heures})

    async def octets_lus_depuis(self, moment: datetime) -> int:
        r = await self._ligne(
            "SELECT COALESCE(sum(octets_lus), 0) FROM inv_doublons_passes WHERE debut >= :moment",
            {"moment": moment})
        return int(r[0])

    async def derniere_passe(self) -> dict[str, Any] | None:
        return await self._dict("SELECT * FROM inv_doublons_passes ORDER BY id DESC LIMIT 1")

    # ---------------------------------------------------------------- postes, envois
    async def creer_poste(self, nom: str, jeton_id: uuid.UUID | None = None) -> Poste:
        try:
            async with self._ecriture() as conn:
                r = (await conn.execute(text(
                    "INSERT INTO inv_postes (nom, jeton_id) VALUES (:nom, :jeton) "  # noqa: S608
                    f"RETURNING {_COLONNES_POSTE}"), {"nom": nom, "jeton": jeton_id})).one()
        except IntegrityError as exc:
            if _unicite(exc):
                raise PosteEnDouble(nom) from exc
            raise
        return _poste(r)

    async def postes(self) -> list[Poste]:
        return [_poste(r) for r in await self._lignes(_POSTE + " ORDER BY nom")]

    async def poste(self, poste_id: int) -> Poste | None:
        r = await self._ligne(_POSTE + " WHERE id = :id", {"id": poste_id})
        return _poste(r) if r else None

    async def poste_par_jeton(self, jeton_id: uuid.UUID) -> Poste | None:
        r = await self._ligne(_POSTE + " WHERE jeton_id = :jeton", {"jeton": jeton_id})
        return _poste(r) if r else None

    async def contact_poste(self, poste_id: int, version: str) -> None:
        await self._executer("UPDATE inv_postes SET dernier_contact = now(), version = :version WHERE id = :id",
                             {"version": version[:40], "id": poste_id})

    async def activer_poste(self, poste_id: int, actif: bool) -> None:
        await self._executer("UPDATE inv_postes SET actif = :actif WHERE id = :id",
                             {"actif": actif, "id": poste_id})

    async def changer_jeton_poste(self, poste_id: int, jeton_id: uuid.UUID | None) -> None:
        try:
            await self._executer("UPDATE inv_postes SET jeton_id = :jeton WHERE id = :id",
                                 {"jeton": jeton_id, "id": poste_id})
        except IntegrityError as exc:
            if _unicite(exc):
                raise PosteEnDouble(str(poste_id)) from exc
            raise

    async def compter_lecture_poste(self, poste_id: int, jour: date, octets: int) -> None:
        await self._executer(
            "UPDATE inv_postes SET lecture_octets = CASE WHEN lecture_jour = :jour "
            "THEN lecture_octets + :octets ELSE :octets END, lecture_jour = :jour WHERE id = :id",
            {"jour": jour, "octets": octets, "id": poste_id})

    async def ouvrir_envoi(self, emplacement_id: int) -> int:
        try:
            async with self._ecriture() as conn:
                # Un envoi resté en réception est mort (l'agent recommence) : on l'abandonne.
                anciens = (await conn.execute(text(
                    "UPDATE inv_envois SET statut = 'abandonne', fin = now() WHERE emplacement_id = :emp "
                    "AND statut = 'reception' RETURNING id"), {"emp": emplacement_id})).all()
                for (ancien,) in anciens:
                    await conn.execute(text("DELETE FROM inv_envoi_dossiers WHERE envoi_id = :id"),
                                       {"id": ancien})
                r = (await conn.execute(text(
                    "INSERT INTO inv_envois (emplacement_id) VALUES (:emp) RETURNING id"),
                    {"emp": emplacement_id})).one()
        except IntegrityError as exc:
            # Un envoi en TRAITEMENT occupe la place : rien n'a été abandonné (transaction annulée).
            if _unicite(exc):
                raise EnvoiEnCours(emplacement_id) from exc
            raise
        return int(r[0])

    async def envoi(self, envoi_id: int) -> dict[str, Any] | None:
        return await self._dict("SELECT * FROM inv_envois WHERE id = :id", {"id": envoi_id})

    async def ajouter_dossiers_envoi(self, envoi_id: int, dossiers: list[DossierEnvoye]) -> None:
        if not dossiers:
            return
        async with self._ecriture() as conn:
            # Un même dossier peut arriver en plusieurs fois (import WizTree, lot renvoyé) : ses
            # enfants s'ajoutent. Un doublon de nom est sans effet (le scan les dédoublonne).
            await conn.execute(text(
                "INSERT INTO inv_envoi_dossiers (envoi_id, chemin, illisible, enfants, illisibles) "
                "VALUES (:envoi, :chemin, :illisible, CAST(:enfants AS jsonb), CAST(:illisibles AS jsonb)) "
                "ON CONFLICT (envoi_id, chemin) DO UPDATE SET "
                "illisible = inv_envoi_dossiers.illisible OR EXCLUDED.illisible, "
                "enfants = inv_envoi_dossiers.enfants || EXCLUDED.enfants, "
                "illisibles = inv_envoi_dossiers.illisibles || EXCLUDED.illisibles"),
                [{"envoi": envoi_id, "chemin": d.chemin, "illisible": d.illisible,
                  "enfants": json.dumps([[e.nom, e.est_dossier, e.taille, e.mtime] for e in d.enfants]),
                  "illisibles": json.dumps(list(d.illisibles))} for d in dossiers])
            await conn.execute(text(
                "UPDATE inv_envois SET nb_dossiers = (SELECT count(*) FROM inv_envoi_dossiers "
                "WHERE envoi_id = :id) WHERE id = :id"), {"id": envoi_id})

    async def dossier_envoi(self, envoi_id: int, chemin: str) -> DossierEnvoye | None:
        r = await self._ligne(
            "SELECT illisible, enfants, illisibles FROM inv_envoi_dossiers "
            "WHERE envoi_id = :envoi AND chemin = :chemin", {"envoi": envoi_id, "chemin": chemin})
        if r is None:
            return None
        enfants = tuple(Element(e[0], bool(e[1]), int(e[2]), float(e[3])) for e in _json(r[1]))
        return DossierEnvoye(chemin, bool(r[0]), enfants, tuple(_json(r[2])))

    async def clore_envoi(self, envoi_id: int, statut: str) -> None:
        clos = statut in ("traite", "abandonne")
        async with self._ecriture() as conn:
            await conn.execute(text(
                "UPDATE inv_envois SET statut = :statut, fin = CASE WHEN :clos THEN now() ELSE fin END "
                "WHERE id = :id"), {"statut": statut, "clos": clos, "id": envoi_id})
            if clos:
                await conn.execute(text("DELETE FROM inv_envoi_dossiers WHERE envoi_id = :id"),
                                   {"id": envoi_id})

    async def abandonner_envois(self, age_heures: int) -> int:
        async with self._ecriture() as conn:
            ids = (await conn.execute(text(
                "UPDATE inv_envois SET statut = 'abandonne', fin = now() WHERE statut IN ('reception', "
                "'traitement') AND debut < now() - make_interval(hours => :h) RETURNING id"),
                {"h": age_heures})).all()
            for (i,) in ids:
                await conn.execute(text("DELETE FROM inv_envoi_dossiers WHERE envoi_id = :id"), {"id": i})
        return len(ids)
