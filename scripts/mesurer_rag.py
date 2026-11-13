"""
Mesure la qualité de la récupération de Matothèque sur un jeu de questions de référence.

Plan `docs/plan-prompts-et-rag-apprenant.md`, étape B0. Lecture seule : n'appelle que
`GET /api/search`. Python standard, rien à installer.

    python scripts/mesurer_rag.py --api http://192.168.42.83:8008 --jeu rag-jeu-reference.json
    (jeton d'automate « lecture » si l'authentification est active : variable MATO_JETON)

Le jeu de référence cite de VRAIS documents : il reste hors de git (`rag-jeu-reference*.json`
est ignoré). Format : `docs/rag-jeu-reference.exemple.json`. Chaque passage est enregistré
(`--sortie`, par défaut `rag-mesures/AAAA-MM-JJ_HHMM.json`) : c'est la suite de ces fichiers
qui dira si la recherche s'améliore ou régresse.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from utils.mesure_rag import mesurer  # noqa: E402


def chercher(api: str, question: str, jeton: str | None, limite: int) -> list[dict]:
    url = f"{api.rstrip('/')}/api/search?" + urllib.parse.urlencode(
        {"q": question, "type": "hybrid", "limit": limite})
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {jeton}"} if jeton else {})
    with urllib.request.urlopen(req, timeout=60) as rep:
        return json.load(rep).get("resultats") or []


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--api", required=True, help="adresse du backend, ex. http://192.168.42.83:8008")
    p.add_argument("--jeu", required=True, type=Path, help="fichier du jeu de questions de référence")
    p.add_argument("--sortie", type=Path, help="fichier de résultat (défaut : rag-mesures/<date>.json)")
    p.add_argument("--limite", type=int, default=20, help="résultats demandés par question")
    a = p.parse_args()

    jeu = json.loads(a.jeu.read_text(encoding="utf-8"))
    jeton = os.environ.get("MATO_JETON")
    cas = []
    for q in jeu["questions"]:
        resultats = chercher(a.api, q["question"], jeton, a.limite)
        cas.append({"id": q["id"], "attendus": q["attendus"],
                    "resultats": [{"id": r.get("id"), "nom": r.get("nom")} for r in resultats]})
    mesure = mesurer(cas)
    mesure.update({"date": datetime.now().isoformat(timespec="seconds"), "api": a.api,
                   "jeu": a.jeu.name, "version_jeu": jeu.get("version")})

    sortie = a.sortie or Path("rag-mesures") / f"{datetime.now():%Y-%m-%d_%H%M}.json"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(mesure, ensure_ascii=False, indent=1), encoding="utf-8")

    for nom, valeur in mesure["indicateurs"].items():
        print(f"{nom:>14} : {valeur}")
    ratees = [d["id"] for d in mesure["detail"] if d["premier"] is None]
    if ratees:
        print("Questions sans aucun document attendu retrouvé :", ", ".join(ratees))
    print("Résultat enregistré :", sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
