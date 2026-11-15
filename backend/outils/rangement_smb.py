"""
Bascule des emplacements du Rangement vers SMB — `python -m outils.rangement_smb` (étape 8)
==========================================================================================
À lancer SUR LE LXC, dans le worker (`docker compose exec worker python -m outils.rangement_smb ...`),
jamais par l'API (aucune route ne l'offre) :

    --liste                         emplacements (racine, source) et Sources « Rangement »
    --emplacement N --source UUID --partage P [--dossier /D] [--prefixe SOUS] [--appliquer] [--scanner]
                                    bascule l'emplacement N vers smb://hôte/P/D, en gardant son
                                    identifiant (entrées, empreintes, instantanés, historique).
                                    À BLANC sans --appliquer. --prefixe : le sous-dossier (relatif à la
                                    racine actuelle) qui devient la racine ; le reste est retiré.
                                    --scanner : lance aussitôt le scan de contrôle (worker), qui ne doit
                                    rien ajouter ni retirer.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.source import USAGE_RANGEMENT, Source
from services.rangement import bascule_smb, service
from services.rangement.depot import Depot
from services.rangement.erreurs import InventaireRefus


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m outils.rangement_smb",
                                description="Bascule des emplacements du Rangement vers SMB (étape 8).")
    p.add_argument("--liste", action="store_true")
    p.add_argument("--emplacement", type=int)
    p.add_argument("--source")
    p.add_argument("--partage")
    p.add_argument("--dossier", default="/")
    p.add_argument("--prefixe", default="")
    p.add_argument("--appliquer", action="store_true")
    p.add_argument("--scanner", action="store_true")
    return p


async def _liste(db: AsyncSession, depot: Depot) -> str:
    lignes = ["Emplacements :"]
    for e in await depot.emplacements():
        lignes.append(f"  {e.id:>3}  {e.source:<8} {'actif ' if e.actif else 'inactif'} {e.libelle} — {e.racine}")
    lignes.append("Sources SMB :")
    sources = (await db.execute(select(Source).where(Source.type == "smb"))).scalars().all()
    for s in sources:
        marque = "  [Rangement]" if s.usage == USAGE_RANGEMENT else "  (GED : non utilisable par le Rangement)"
        lignes.append(f"  {s.id}  {s.identifiant or 'invité'}@{s.hote}  {s.libelle}{marque}")
    return "\n".join(lignes)


async def _scanner(db: AsyncSession, depot: Depot, emplacement_id: int) -> str:
    from services import job_worker
    scan_id = await service.ouvrir_scan_manuel(depot, emplacement_id)
    await job_worker.enqueue(db, service.JOB_SCAN, {"emplacement_id": emplacement_id, "scan_id": scan_id,
                                                    "cible": f"emplacement:{emplacement_id}"})
    await db.commit()
    return f"Scan de contrôle n° {scan_id} lancé (worker)."


async def executer(argv: list[str], db: AsyncSession, depot: Depot) -> str:
    """Exécute la commande et rend le message à afficher. SystemExit si les arguments sont invalides."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.liste:
        return await _liste(db, depot)
    if args.emplacement is None or not args.source or not args.partage:
        parser.error("--emplacement, --source et --partage sont requis (ou --liste).")
    try:
        b = await bascule_smb.basculer(db, depot, args.emplacement, args.source, args.partage, args.dossier,
                                       prefixe=args.prefixe, appliquer=args.appliquer)
    except InventaireRefus as exc:
        return f"REFUS ({exc.code}) : {exc.message}"
    lignes = [f"« {b.libelle} » (n° {b.emplacement_id})", f"  avant : {b.avant}", f"  après : {b.apres}"]
    if b.prefixe:
        lignes.append(f"  « {b.prefixe} » devient la racine ; le reste de l'inventaire est retiré.")
    if not b.applique:
        lignes.append("À BLANC : dossier vérifié par SMB, rien n'est écrit. Ajouter --appliquer.")
        return "\n".join(lignes)
    lignes.append(f"BASCULÉ : {b.entrees_gardees} entrées gardées, {b.entrees_retirees} retirées.")
    if args.scanner:
        lignes.append(await _scanner(db, depot, b.emplacement_id))
    return "\n".join(lignes)


async def _main(argv: list[str]) -> str:
    from database import AsyncSessionLocal, engine
    depot = service.fabrique()
    if depot is None:
        return "Inventaire indisponible (pas de base PostgreSQL)."
    try:
        async with AsyncSessionLocal() as db:
            return await executer(argv, db, depot)
    finally:
        await engine.dispose()


def main() -> None:
    print(asyncio.run(_main(sys.argv[1:])))


if __name__ == "__main__":
    main()
