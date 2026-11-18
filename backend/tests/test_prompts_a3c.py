"""
Migration A3c des prompts vers le registre (plan docs/plan-prompts-et-rag-apprenant.md).
=======================================================================================
La migration ne doit RIEN changer à ce que reçoivent les modèles : chaque scénario de
`capture_prompts_a3c.py` (entrées fictives, IA simulée) est rejoué avec le code migré, et le
prompt comme le `system` envoyés sont comparés, à l'octet près, à la capture faite AVANT la
migration (`tests/donnees/prompts_origine_a3c.json`).
"""
import json
import string
from pathlib import Path

import pytest

import capture_prompts_a3c as capture
from services import prompts

_ORIGINE = json.loads(capture.FIXTURE.read_text(encoding="utf-8"))


_REJOUE: dict = {}


async def _rejoue() -> dict:
    """Scénarios rejoués UNE fois pour le module, dans la boucle du test (pas d'asyncio.run)."""
    if not _REJOUE:
        _REJOUE.update(await capture.capturer())
    return _REJOUE


async def test_la_capture_couvre_les_memes_scenarios():
    assert sorted(await _rejoue()) == sorted(_ORIGINE)


@pytest.mark.parametrize("cle", sorted(_ORIGINE))
async def test_prompt_et_system_identiques_a_l_octet_pres(cle):
    rejoue = await _rejoue()
    assert rejoue[cle]["prompt"] == _ORIGINE[cle]["prompt"]
    assert rejoue[cle]["system"] == _ORIGINE[cle]["system"]


@pytest.mark.parametrize("cle", sorted({capture.cle_registre(c) for c in _ORIGINE}))
def test_cle_de_la_capture_au_registre_avec_un_usage_connu(cle):
    assert cle in prompts.cles()
    assert prompts.prompt(cle).usage in prompts.USAGES


# ─── rendre() et gabarits ────────────────────────────────────────────────────

@pytest.mark.parametrize("cle", prompts.cles())
def test_champs_du_gabarit_egaux_aux_variables_declarees(cle):
    p = prompts.prompt(cle)
    if p.variables:
        champs = {nom for _, nom, _, _ in string.Formatter().parse(p.texte) if nom is not None}
        assert champs == set(p.variables)
    else:   # texte littéral : rendu tel quel, accolades comprises
        assert prompts.rendre(cle) == prompts.texte(cle)


def test_rendre_refuse_une_variable_manquante():
    with pytest.raises(KeyError):
        prompts.rendre("assistant.pieces")


def test_rendre_refuse_une_variable_en_trop():
    with pytest.raises(ValueError):
        prompts.rendre("assistant.pieces", besoin="x", autre="y")
    with pytest.raises(ValueError):
        prompts.rendre("regroupement.defaut", besoin="x")


def test_rendre_ne_reinterprete_pas_les_accolades_des_valeurs():
    texte = prompts.rendre("assistant.pieces", besoin='{"piege": "{besoin}"}')
    assert texte.endswith('Besoin : {"piege": "{besoin}"}')
    assert '{"pieces": ["...", "...", ...]}' in texte   # accolades doublées du gabarit → simples


def test_une_cle_dont_les_variables_ne_collent_pas_est_refusee():
    with pytest.raises(ValueError):
        prompts._enregistrer(prompts.Prompt(cle="test.incoherent", usage="chat", sortie="texte",
                                            description="d", texte="{a} {b}", variables=("a",)))
    assert "test.incoherent" not in prompts.cles()


def test_les_prompts_interactifs_n_ont_pas_d_usage_de_fond():
    # Seul « version.diff_resume » (job de fond d'indexation) porte « enrichissement ».
    from services.ollama_service import USAGES_DE_FOND
    de_fond = {capture.cle_registre(c) for c in _ORIGINE
               if prompts.prompt(capture.cle_registre(c)).usage in USAGES_DE_FOND}
    assert de_fond == {"version.diff_resume"}


def test_fixture_presente():
    assert Path(capture.FIXTURE).is_file()
