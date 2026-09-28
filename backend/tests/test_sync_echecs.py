"""
Tests — une synchro dit combien de fichiers elle N'A PAS réussi à indexer
========================================================================
Audit du 28/09/2026, H5. Un fichier en échec pendant une synchro (coupure réseau, fichier
illisible) n'était que journalisé : le récap ne comptait que les réussites, et l'écran
affichait « +50 nouveau(x) » alors que 15 n'étaient pas dans l'index. Même famille que les
« 1 220 documents enrichis à vide ».
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services import sync_service


def _dist(chemin):
    return {"chemin": chemin, "rel": chemin, "taille": 10, "mtime": None}


async def _synchro(distants, echouent):
    """Synchro d'une source locale : `distants` détectés, ceux de `echouent` lèvent."""
    src = SimpleNamespace(type="local", chemin_base="/data", libelle="Test")

    async def traiter(service, src, partage, secret, entree, taille_max):
        if entree["chemin"] in echouent:
            raise OSError("coupure réseau")

    with patch.object(sync_service, "_lister_local", AsyncMock(return_value=distants)), \
         patch.object(sync_service, "_lister_index", AsyncMock(return_value={})), \
         patch.object(sync_service, "_appliquer_deplacements", AsyncMock(return_value=0)), \
         patch.object(sync_service, "_marquer_absents", AsyncMock(return_value=0)), \
         patch.object(sync_service, "_reactiver", AsyncMock(return_value=0)), \
         patch.object(sync_service, "_traiter_fichier", side_effect=traiter), \
         patch("routers.sources._extraction_service", return_value=object()):
        return await sync_service.synchroniser(src, None, "/", None)


@pytest.mark.asyncio
async def test_les_fichiers_en_echec_sont_comptes_et_nommes():
    distants = {f"/doc{i}.pdf": _dist(f"/doc{i}.pdf") for i in range(50)}
    echouent = {f"/doc{i}.pdf" for i in range(15)}
    r = await _synchro(distants, echouent)
    assert (r["nouveaux"], r["traites"], r["echecs"]) == (50, 35, 15)
    assert set(r["fichiers_en_echec"]) == echouent


@pytest.mark.asyncio
async def test_le_nombre_est_exact_meme_quand_la_liste_est_tronquee():
    distants = {f"/doc{i}.pdf": _dist(f"/doc{i}.pdf") for i in range(60)}
    r = await _synchro(distants, set(distants))
    assert r["echecs"] == 60
    assert len(r["fichiers_en_echec"]) == sync_service.MAX_ECHECS_NOMMES


@pytest.mark.asyncio
async def test_une_synchro_sans_echec_le_dit_aussi():
    r = await _synchro({"/a.pdf": _dist("/a.pdf")}, set())
    assert (r["traites"], r["echecs"], r["fichiers_en_echec"]) == (1, 0, [])


@pytest.mark.asyncio
async def test_une_synchro_a_vide_porte_les_memes_champs():
    """Le récap a toujours la même forme : l'écran n'a pas à deviner l'absence d'un champ."""
    r = await _synchro({}, set())
    assert r["echecs"] == 0 and r["fichiers_en_echec"] == []
