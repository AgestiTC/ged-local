"""
Mesure B0 « en processus » (plan prompts + RAG) — sans HTTP ni jeton d'automate.
================================================================================
À lancer DANS un conteneur du backend (celui de la prod, ou un `docker compose run` jetable qui
monte le code d'une branche) : appelle la route de recherche comme le ferait
`GET /api/search?type=hybrid&limit=20`, en lecture seule.

    python -m utils.mesure_rag_processus /tmp/jeu.json [--fusion rrf] > mesure.json

Les embeddings des questions sont calculés D'ABORD, avec un délai long, et placés dans le cache
de la recherche : la mesure juge le CLASSEMENT, pas la latence d'Ollama. (Relevé du 19/11/2026 :
l'embedding d'une question met de 0,2 à 10 s selon l'occupation de la carte ; au-delà de 8 s la
recherche retombe sur le texte seul — sans ce préchauffage, la mesure aurait noté ce repli.)

Le jeu de référence cite de vrais documents : il reste hors du dépôt (cf. `scripts/mesurer_rag.py`).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time


async def mesurer_jeu(jeu: dict, fusion: str | None = None, limite: int = 20) -> dict:
    from database import AsyncSessionLocal
    from routers import search as recherche
    from services import fusion_recherche, runtime_config
    from services.ollama_service import OllamaService
    from utils.mesure_rag import mesurer

    async with AsyncSessionLocal() as db:
        await runtime_config.load(db, journal=False)     # adresse d'Ollama / de l'AIGUILLEUR en base
    if fusion:
        if fusion not in fusion_recherche.METHODES:
            raise SystemExit(f"fusion inconnue : {fusion} ({', '.join(fusion_recherche.METHODES)})")
        recherche.FUSION_DEFAUT = fusion
    modele = runtime_config.usage_model("embeddings") or ""
    for q in jeu["questions"]:
        recherche._EMBED_CACHE[(modele, q["question"])] = await OllamaService().embed(
            q["question"], model=modele or None, timeout=120.0)

    cas, debut = [], time.monotonic()
    for q in jeu["questions"]:
        async with AsyncSessionLocal() as db:
            rep = await recherche.search(q=q["question"], type="hybrid", limit=limite, offset=0, categorie=None,
                                         extension=None, inclure_non_pertinents=False, db=db)
        cas.append({"id": q["id"], "attendus": q["attendus"], "moteur": rep.get("moteur_semantique"),
                    "resultats": [{"id": r.get("id"), "nom": r.get("nom")} for r in rep["resultats"]]})
    mesure = mesurer(cas)
    mesure.update({"fusion": recherche.FUSION_DEFAUT, "version_jeu": jeu.get("version"),
                   "moteurs": sorted({c["moteur"] for c in cas}),
                   "duree_recherches_s": round(time.monotonic() - debut, 1)})
    return mesure


def main() -> None:
    p = argparse.ArgumentParser(description="Mesure B0 en processus (lecture seule)")
    p.add_argument("jeu", help="fichier du jeu de questions de référence")
    p.add_argument("--fusion", help="ponderee | rrf (défaut : celle de routers/search.py)")
    p.add_argument("--limite", type=int, default=20)
    a = p.parse_args()
    with open(a.jeu, encoding="utf-8") as f:
        jeu = json.load(f)
    print(json.dumps(asyncio.run(mesurer_jeu(jeu, a.fusion, a.limite)), ensure_ascii=False))


if __name__ == "__main__":
    main()
