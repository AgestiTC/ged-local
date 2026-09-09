"""
Tests — portrait d'un intervenant
=================================
Ce qui compte ici tient en trois points, et deux sont des questions de confiance :

- **un format illisible est refusé, pas accepté en silence.** Le HEIC des iPhone arrive
  parfois tel quel ; l'accepter donnerait une photo « enregistrée » qu'on ne découvrirait
  cassée qu'en rouvrant la fiche ;
- **supprimer supprime vraiment le fichier.** Une donnée personnelle qu'on croit effacée et
  qui reste sur le disque est le pire des deux mondes — et ça vaut aussi quand c'est la
  fiche entière qu'on supprime ;
- le portrait vit **hors GED** : il ne doit apparaître dans aucun index.
"""

import io
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# 1×1 pixel PNG — le plus petit fichier valide possible, on teste le chemin, pas l'image.
PNG_MINIMAL = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


@pytest_asyncio.fixture
async def client(db_session, tmp_path, monkeypatch):
    """
    Les portraits partent dans un dossier temporaire : un test qui écrirait dans le vrai
    `storage/` laisserait des fichiers derrière lui, et ferait passer ou échouer le suivant
    selon ce qu'il y trouve.
    """
    from config import get_settings
    from database import get_db
    from main import app
    from routers import emploi_domicile_visites as visites

    reglages = get_settings()
    monkeypatch.setattr(reglages, "storage_intervenants", str(tmp_path / "intervenants"),
                        raising=False)
    monkeypatch.setattr(visites, "settings", reglages)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def intervenant(client):
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/dossiers", json={"titre": "Devenir parent"})
        i = (await c.post("/api/emploi-domicile/devenir-parent/intervenants",
                          json={"nom": "Martin"})).json()
    return i["id"]


def _fichier(contenu: bytes = PNG_MINIMAL, nom: str = "portrait.png", type_mime: str = "image/png"):
    return {"fichier": (nom, io.BytesIO(contenu), type_mime)}


@pytest.mark.asyncio
async def test_depot_et_relecture(client, intervenant):
    async with client as c:
        pose = (await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/photo",
                             files=_fichier())).json()
        assert pose["photo"] is True

        lu = await c.get(f"/api/emploi-domicile/intervenants/{intervenant}/photo")
    assert lu.status_code == 200
    assert lu.headers["content-type"].startswith("image/")
    assert lu.content == PNG_MINIMAL


@pytest.mark.asyncio
async def test_sans_photo_le_404_est_explicite(client, intervenant):
    """L'écran affiche alors les initiales : encore faut-il qu'il puisse le savoir."""
    async with client as c:
        r = await c.get(f"/api/emploi-domicile/intervenants/{intervenant}/photo")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_heic_refuse_avec_un_message_utile(client, intervenant):
    """
    Accepter un HEIC donnerait une photo « enregistrée » que le navigateur ne sait pas
    afficher — on ne le découvrirait qu'en rouvrant la fiche.
    """
    async with client as c:
        r = await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/photo",
                         files=_fichier(b"pas-une-image", "IMG_0001.HEIC", "image/heic"))
    assert r.status_code == 400
    assert "HEIC" in r.json()["detail"], "le message doit nommer le format et sa solution"


@pytest.mark.asyncio
async def test_fichier_vide_refuse(client, intervenant):
    async with client as c:
        r = await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/photo",
                         files=_fichier(b"", "vide.png"))
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_photo_trop_lourde_refusee(client, intervenant):
    async with client as c:
        r = await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/photo",
                         files=_fichier(b"x" * (9 * 1024 * 1024), "grosse.png"))
    assert r.status_code == 400 and "lourde" in r.json()["detail"]


@pytest.mark.asyncio
async def test_remplacer_ne_laisse_pas_l_ancienne(client, intervenant, tmp_path):
    """Deux extensions différentes : l'ancien fichier doit disparaître, pas s'accumuler."""
    async with client as c:
        await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/photo",
                     files=_fichier(PNG_MINIMAL, "a.png", "image/png"))
        await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/photo",
                     files=_fichier(PNG_MINIMAL, "b.jpg", "image/jpeg"))

    fichiers = sorted(p.name for p in (tmp_path / "intervenants").iterdir())
    assert fichiers == [f"{intervenant}.jpg"], f"reste : {fichiers}"


@pytest.mark.asyncio
async def test_suppression_efface_le_fichier(client, intervenant, tmp_path):
    async with client as c:
        await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/photo", files=_fichier())
        await c.delete(f"/api/emploi-domicile/intervenants/{intervenant}/photo")

    assert list((tmp_path / "intervenants").iterdir()) == []


@pytest.mark.asyncio
async def test_supprimer_la_fiche_emporte_le_portrait(client, intervenant, tmp_path):
    """Le cas qu'on oublie : on supprime la personne, et sa photo reste sur le disque."""
    async with client as c:
        await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/photo", files=_fichier())
        await c.delete(f"/api/emploi-domicile/intervenants/{intervenant}")

    assert list((tmp_path / "intervenants").iterdir()) == []


@pytest.mark.asyncio
async def test_accord_photo_enregistre(client, intervenant):
    """Le portrait d'une personne identifiée n'est pas notre donnée : l'accord se coche."""
    async with client as c:
        maj = (await c.patch(f"/api/emploi-domicile/intervenants/{intervenant}",
                             json={"photo_accord": True})).json()
    assert maj["photo_accord"] is True


@pytest.mark.asyncio
async def test_le_portrait_n_entre_pas_dans_la_ged(client, intervenant, db_session):
    """Un visage n'a rien à faire dans les résultats de recherche, ni dans les embeddings."""
    from sqlalchemy import func, select

    from models.document import Document

    async with client as c:
        await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/photo", files=_fichier())

    total = (await db_session.execute(select(func.count()).select_from(Document))).scalar_one()
    assert total == 0, "aucun document ne doit être créé par le dépôt d'un portrait"
