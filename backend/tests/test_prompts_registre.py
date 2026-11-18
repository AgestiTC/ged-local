"""
Registre des prompts (plan docs/plan-prompts-et-rag-apprenant.md, étape A1).

La migration ne doit RIEN changer à ce que reçoivent les modèles : le texte de chaque clé est
comparé, à l'octet près, à la valeur des constantes qu'il remplace, figée avant la migration
dans `tests/donnees/prompts_origine_a1.json`.
"""
import json
from pathlib import Path

import pytest

from services import prompts
from services.ollama_service import _USAGE_IA, entetes_projet, usage_ia

_ORIGINE = json.loads(
    (Path(__file__).parent / "donnees" / "prompts_origine_a1.json").read_text(encoding="utf-8")
)


# Prompts modifiés VOLONTAIREMENT depuis la migration A1 (la référence reste celle d'avant, pour l'histoire).
_MODIFIES_DEPUIS_A1 = {
    "enrichissement": "A3 (18/11/2026) — liste fermée de catégories, voir services/categories.py",
}


@pytest.mark.parametrize("cle", sorted(set(_ORIGINE) - set(_MODIFIES_DEPUIS_A1)))
def test_texte_identique_a_l_octet_pres(cle):
    assert prompts.texte(cle) == _ORIGINE[cle]


def test_le_prompt_d_enrichissement_donne_exactement_la_liste_fermee():
    from services import categories
    assert f"UNE SEULE valeur parmi : {categories.texte_liste()}\"" in prompts.texte("enrichissement")
    # Le reste du contrat JSON est inchangé depuis A1.
    for morceau in ('"sous_categorie"', '"tags"', '"resume"', '"entites"', '"mots_cles"', '"niveau_confidentialite"'):
        assert morceau in prompts.texte("enrichissement")


def test_toutes_les_cles_migrees_sont_couvertes():
    assert set(_ORIGINE) <= set(prompts.cles())


def test_usages_et_sorties_valides():
    for cle in prompts.cles():
        p = prompts.prompt(cle)
        assert p.usage in prompts.USAGES, cle
        assert p.sortie in ("json", "texte"), cle
        assert p.description and p.texte.strip(), cle


def test_cle_inconnue_casse():
    with pytest.raises(KeyError):
        prompts.texte("n.existe.pas")


def test_usage_pour_pose_l_usage_de_la_cle():
    assert _USAGE_IA.get() == "autre"
    with prompts.usage_pour("qa.comprendre"):
        assert entetes_projet()["X-AI-Usage"] == "chat"
    assert _USAGE_IA.get() == "autre"


def test_usage_pour_ne_contredit_pas_l_appelant():
    with usage_ia("rapport"):
        with prompts.usage_pour("qa.comprendre"):
            assert entetes_projet()["X-AI-Usage"] == "rapport"


def test_prompts_interactifs_hors_usages_de_fond():
    # Le mode Question et le chat peuvent partir vers GECO (bouton administrateur) : leurs prompts
    # ne doivent jamais porter un usage de fond, que GECO refuse.
    from services.ollama_service import USAGES_DE_FOND
    for cle in ("qa.comprendre", "qa.extraire", "chat.ged.extraits", "chat.ged.vide"):
        assert prompts.prompt(cle).usage not in USAGES_DE_FOND, cle
