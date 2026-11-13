"""
Assemblage des documents dans un prompt (plan docs/plan-prompts-et-rag-apprenant.md, étape A2).

Les quatre constructeurs de contexte passent par `utils.contexte_ia.assembler_documents` : leurs
sorties doivent rester IDENTIQUES À L'OCTET à celles des anciennes boucles. La référence
(`tests/donnees/contextes_origine_a2.json`) a été figée avec l'ancien code, sur les mêmes
documents fictifs et les mêmes budgets : on y compare l'empreinte SHA-256 et la longueur.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from routers import compare, generate
from services import grille_analyse, template_filler

_REF = json.loads((Path(__file__).parent / "donnees" / "contextes_origine_a2.json").read_text(encoding="utf-8"))


def _texte(spec: dict) -> str:
    if spec.get("blancs"):
        return "   \n\t  "
    corps = "".join(f"mot{i % 97} " for i in range(spec["n"]))[: spec["n"]]
    return f"  \n{corps}\n  " if spec.get("autour") else corps


def _doc(spec: dict) -> SimpleNamespace:
    return SimpleNamespace(
        nom=spec["nom"],
        texte_extrait=_texte(spec),
        tika_metadata={"dcterms:created": spec["creation"]} if spec.get("creation") else {},
        date_modification_fichier=(
            datetime.fromisoformat(spec["modif"]).replace(tzinfo=timezone.utc) if spec.get("modif") else None
        ),
    )


_DOCS = [_doc(s) for s in _REF["specs"]]


def _sorties(monkeypatch) -> dict[str, str]:
    s: dict[str, str] = {}
    for b in _REF["budgets"]:
        s[f"generate:{b}"] = generate._construire_contexte(_DOCS, "INSTRUCTION", max_chars=b)
        s[f"compare:{b}"] = compare._contexte_documents(_DOCS, b)
        s[f"grille:{b}"] = grille_analyse._contexte(_DOCS, b)
        monkeypatch.setattr(template_filler, "MAX_CONTEXT_CHARS", b)
        s[f"template:{b}"] = template_filler._construire_contexte(_DOCS)
    s["generate:defaut"] = generate._construire_contexte(_DOCS, "INSTRUCTION")
    s["vides:generate"] = generate._construire_contexte([_DOCS[1], _DOCS[2]], "X", max_chars=500)
    s["vides:compare"] = compare._contexte_documents([_DOCS[1]], 500)
    s["vides:grille"] = grille_analyse._contexte([], 500)
    monkeypatch.setattr(template_filler, "MAX_CONTEXT_CHARS", 500)
    s["vides:template"] = template_filler._construire_contexte([_DOCS[2]])
    return s


def test_memes_cas_que_la_reference(monkeypatch):
    assert set(_sorties(monkeypatch)) == set(_REF["sorties"])


@pytest.mark.parametrize("cle", sorted(_REF["sorties"]))
def test_sortie_identique_a_l_octet(cle, monkeypatch):
    sortie = _sorties(monkeypatch)[cle]
    attendu = _REF["sorties"][cle]
    assert len(sortie) == attendu["longueur"], cle
    assert hashlib.sha256(sortie.encode("utf-8")).hexdigest() == attendu["sha256"], cle
