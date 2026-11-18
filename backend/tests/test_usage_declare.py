"""
Usage IA déclaré sur chaque fonction qui envoie un prompt (plan prompts + RAG, étape A3b — 18/11/2026).
=========================================================================================================
Au 18/11/2026, 25 appels IA partaient avec `X-AI-Usage: autre` : l'AIGUILLEUR ne savait pas les ranger,
et l'avancement d'A3 se mesure justement à la baisse de « autre » dans son journal. Ici : chaque fonction
qui envoie porte son usage, et aucune fonction servie à une DEMANDE INTERACTIVE ne porte un usage de fond
(« enrichissement », « embeddings », « vision » sont refusés à GECO).
"""
import importlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import ollama_service
from services.ollama_service import USAGES_DE_FOND, _USAGE_IA, avec_usage
from services.prompts import USAGES

# (module, fonction, usage, interactive ?)
ATTENDUS = [
    ("routers.compare", "_deduire_colonnes", "analyse", True),
    ("routers.compare", "_analyser_groupe", "analyse", True),
    ("routers.compare", "_synthetiser_ecarts", "analyse", True),
    ("routers.organize", "_proposer_dossiers", "analyse", True),
    ("routers.system", "_resume_ia", "resume", True),
    ("services.dossier_import", "parser_ressources", "analyse", True),
    ("services.dossier_resume", "resumer_ressource", "resume", True),
    ("services.fiches_candidats", "rediger_fiche", "analyse", True),
    ("services.grille_analyse", "evaluer_critere", "analyse", True),
    ("services.grille_apprise", "apprendre", "analyse", True),
    ("services.idees_evolution", "generer_bilan", "rapport", True),
    ("services.jalon_ia", "analyser_evenement", "analyse", True),
    ("services.musique_jobs", "preparer_style", "chat", True),
    ("services.presentation_service", "generer_slides", "rapport", True),
    ("services.recommandation_comparatif", "recommander", "analyse", True),
    ("services.relecture_prompt", "relire_prompt", "chat", True),
    ("services.video_jobs", "preparer_mouvement", "chat", True),
    ("services.regroupement_jobs", "handler_analyse_regroupement", "rapport", True),
    # Tâche de fond : jamais envoyée à GECO.
    ("services.rangement.plan", "proposer_par_ia", "analyse", False),
]


@pytest.mark.parametrize("module, nom, usage, interactive", ATTENDUS)
def test_chaque_fonction_porte_son_usage(module, nom, usage, interactive):
    fn = getattr(importlib.import_module(module), nom)
    assert getattr(fn, "usage_ia", None) == usage
    assert usage in USAGES
    if interactive:
        assert usage not in USAGES_DE_FOND


def test_methodes_decorees():
    from services.extraction import ExtractionService
    from services.template_filler import TemplateFiller
    assert ExtractionService._generate_diff_resume.usage_ia == "enrichissement"   # job de fond
    assert TemplateFiller.fill.usage_ia == "rapport"


@pytest.mark.asyncio
async def test_le_decorateur_pose_l_usage_le_temps_de_l_appel_seulement():
    vu = []

    @avec_usage("analyse")
    async def envoyer():
        vu.append(_USAGE_IA.get())
        return "ok"

    assert await envoyer() == "ok"
    assert vu == ["analyse"]
    assert _USAGE_IA.get() == ollama_service._USAGE_DEFAUT


@pytest.mark.asyncio
async def test_un_vrai_envoi_part_avec_l_usage_analyse():
    from routers.compare import _synthetiser_ecarts

    vu = []

    async def generate(*args, **kwargs):
        vu.append(_USAGE_IA.get())
        return "- écart fictif"

    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=generate)
    groupes = [{"nom": "A", "valeurs": {"Prix": "10"}}, {"nom": "B", "valeurs": {"Prix": "12"}}]
    await _synthetiser_ecarts(["Prix"], groupes, None, "modele-fictif", ollama)
    assert vu == ["analyse"]
