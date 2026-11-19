"""
Étape A6 du plan docs/plan-prompts-et-rag-apprenant.md — plus aucun texte de prompt dans le frontend.
====================================================================================================
1. Consignes « documents de référence » : origines au registre, rendu du prompt final côté
   backend (POST /api/consignes/{cle}/rendu), IDENTIQUE à l'octet près à la capture faite avec
   l'ancien code frontend (`tests/donnees/prompts_origine_a6.json`, commit « test: capture des
   prompts du frontend avant A6 ») ; garde-fou de structure appliqué à l'enregistrement.
2. Page IA internet : message système désigné par sa clé (`consigne_systeme` du chat).
3. Historique des prompts pré-enregistrés (`prompts_presets_versions`).
Données FICTIVES uniquement.
"""
import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from services import acces, consignes_reference, prompts

_ORIGINE = json.loads((Path(__file__).parent / "donnees" / "prompts_origine_a6.json").read_text(encoding="utf-8"))
_CAS = sorted(k for k, v in _ORIGINE.items() if "cle" in v)

STRUCTURE = "# Titre fictif\n\n## Un\n" + "Phrase fictive de consigne. " * 4 + "\n\n## Deux\n" \
            + "Autre phrase fictive. " * 4 + "\n\n## Trois\n" + "Dernière phrase fictive. " * 3 + "N'invente rien."


# ─── 1. Consignes de référence ───────────────────────────────────────────────

def test_origines_au_registre_identiques_a_la_capture():
    assert prompts.prompt("reference.analyse").texte == _ORIGINE["analyse#origine"]["texte"]
    assert prompts.prompt("reference.corrigee").texte == _ORIGINE["corrigee#origine"]["texte"]
    for cle in ("reference.analyse", "reference.corrigee"):
        assert prompts.prompt(cle).usage == "rapport" and prompts.prompt(cle).sortie == "texte"


@pytest.mark.asyncio
@pytest.mark.parametrize("cas", _CAS)
async def test_rendu_identique_a_l_octet_pres(client, cas):
    c = _ORIGINE[cas]
    r = await client.post(f"/api/consignes/{c['cle']}/rendu",
                          json={"criteres": c["criteres"], "corps": c["corps"], "instructions": c["instructions"]})
    assert r.status_code == 200
    assert r.json()["texte"] == c["texte"]


@pytest.mark.asyncio
async def test_rendu_sans_corps_utilise_la_version_active(client):
    assert (await client.post("/api/consignes/reference_corrigee", json={"texte": STRUCTURE})).status_code == 201
    r = (await client.post("/api/consignes/reference_corrigee/rendu", json={"criteres": ["Prix"]})).json()
    assert r["version"] == 1 and r["texte"] == consignes_reference.rendre("reference_corrigee", STRUCTURE.strip(), ["Prix"])
    # Retour à l'origine : le rendu repart du texte du code.
    await client.post("/api/consignes/reference_corrigee", json={"texte": None})
    r = (await client.post("/api/consignes/reference_corrigee/rendu", json={})).json()
    assert r["version"] == 2 and r["texte"] == _ORIGINE["corrigee#origine"]["texte"]


@pytest.mark.asyncio
async def test_lecture_donne_origine_et_texte_actif(client):
    r = (await client.get("/api/consignes/reference_analyse")).json()
    assert r["origine_texte"] == r["texte_actif"] == _ORIGINE["analyse#origine"]["texte"]
    assert (r["min_caracteres"], r["min_sections"]) == (200, 3)
    await client.post("/api/consignes/reference_analyse", json={"texte": STRUCTURE})
    r = (await client.get("/api/consignes/reference_analyse")).json()
    assert r["texte_actif"] == STRUCTURE.strip() and r["origine_texte"] == _ORIGINE["analyse#origine"]["texte"]


@pytest.mark.asyncio
async def test_enregistrement_refuse_une_consigne_sans_structure(client):
    sans_sections = "## Une seule section\n" + "Consigne fictive sans structure. " * 10
    r = await client.post("/api/consignes/reference_analyse", json={"texte": sans_sections})
    assert r.status_code == 400 and "section(s)" in r.json()["detail"]
    assert (await client.get("/api/consignes/reference_analyse")).json()["versions"] == []


def test_verifier_identique_a_l_ancien_garde_fou():
    assert consignes_reference.verifier(_ORIGINE["analyse#origine"]["texte"]) == []
    assert consignes_reference.verifier(_ORIGINE["corrigee#origine"]["texte"]) == []
    assert len(consignes_reference.verifier("trop court")) == 2
    assert "section" in consignes_reference.verifier("x" * 300)[0]


@pytest.mark.asyncio
async def test_rendu_cle_inconnue(client):
    assert (await client.post("/api/consignes/inconnue/rendu", json={})).status_code == 404


def test_acces_rendu_utilisateur_enregistrement_admin():
    assert acces.classer("POST", "/api/consignes/{cle}/rendu") == acces.UTILISATEUR
    assert acces.classer("GET", "/api/consignes/{cle}") == acces.UTILISATEUR
    assert acces.classer("POST", "/api/consignes/{cle}") == acces.ADMIN
    assert not acces.a_tracer("POST", "/api/consignes/{cle}/rendu")   # n'enregistre rien


@pytest.mark.asyncio
async def test_prompts_systeme_ne_les_expose_pas(client):
    liste = (await client.get("/api/system/prompts")).json()["prompts"]
    assert not {"reference.analyse", "reference.corrigee"} & {p["cle"] for p in liste}
    assert "internet.formulation" in {p["cle"] for p in liste}
    for cle in ("reference.analyse", "reference.corrigee"):
        assert (await client.get(f"/api/system/prompts/{cle}")).status_code == 409
        r = await client.post(f"/api/system/prompts/{cle}/versions", json={"texte": STRUCTURE})
        assert r.status_code == 409 and "Consignes de base" in r.json()["detail"]


# ─── 2. IA internet : consigne système par sa clé ────────────────────────────

class _OllamaFactice:
    recus: list = []

    async def chat_stream(self, messages, model=None, think=False):
        type(self).recus = messages
        yield "ok"


async def _resoudre(demande=None, usage="rapport"):
    from services.modeles_externes import ModeleResolu
    return ModeleResolu(demande or "llama3.1:latest")


@pytest.mark.asyncio
async def test_chat_consigne_systeme_en_premier_identique_a_l_ancien_frontend():
    from main import app
    historique = [{"role": "user", "content": "Ressources fictives sur un sujet fictif"},
                  {"role": "assistant", "content": "Réponse fictive"},
                  {"role": "user", "content": "Et des podcasts ?"}]
    with patch("routers.generate._resoudre_complet", new=AsyncMock(side_effect=_resoudre)), \
         patch("routers.generate.OllamaService", _OllamaFactice):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/generate/chat", json={"messages": historique, "use_ged": False,
                                                         "consigne_systeme": "internet.formulation"})
    assert r.status_code == 200
    systeme = _ORIGINE["internet.formulation"]
    # Exactement ce qu'envoyait le frontend avant A6 : [SYSTEME, ...historique].
    assert _OllamaFactice.recus == [{"role": systeme["role"], "content": systeme["texte"]}, *historique]


@pytest.mark.asyncio
async def test_chat_consigne_systeme_inconnue_refusee():
    from main import app
    with patch("routers.generate._resoudre_complet", new=AsyncMock(side_effect=_resoudre)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/generate/chat", json={"messages": [{"role": "user", "content": "x"}],
                                                         "use_ged": False, "consigne_systeme": "enrichissement"})
    assert r.status_code == 422


# ─── 3. Historique des prompts pré-enregistrés ───────────────────────────────

PRESET = {"nom": "Synthèse fictive", "prompt_text": "Résume les documents fictifs.", "categorie": "rapport"}


async def _versions(client, ident):
    r = await client.get(f"/api/prompts/{ident}/versions")
    assert r.status_code == 200
    return r.json()["versions"]


@pytest.mark.asyncio
async def test_creation_modification_restauration(client):
    ident = (await client.post("/api/prompts", json=PRESET)).json()["id"]
    v = await _versions(client, ident)
    assert [x["version"] for x in v] == [1] and v[0]["prompt_text"] == PRESET["prompt_text"]

    await client.put(f"/api/prompts/{ident}", json={"prompt_text": "Texte fictif modifié.", "nom": "Autre nom"})
    await client.put(f"/api/prompts/{ident}", json={"prompt_text": "Texte fictif modifié."})   # rien ne change
    v = await _versions(client, ident)
    assert [x["version"] for x in v] == [2, 1]
    assert (v[0]["nom"], v[0]["prompt_text"]) == ("Autre nom", "Texte fictif modifié.")

    r = await client.post(f"/api/prompts/{ident}/restaurer/1")
    assert r.status_code == 200 and r.json()["version"] == 3
    assert (r.json()["nom"], r.json()["prompt_text"]) == (PRESET["nom"], PRESET["prompt_text"])
    v = await _versions(client, ident)
    assert [x["version"] for x in v] == [3, 2, 1]                     # rien d'écrasé
    assert v[0]["commentaire"] == "Restauration de la version 1"
    liste = (await client.get("/api/prompts")).json()["prompts"]
    assert next(p for p in liste if p["id"] == ident)["prompt_text"] == PRESET["prompt_text"]

    assert (await client.post(f"/api/prompts/{ident}/restaurer/3")).status_code == 409   # déjà l'actuel
    assert (await client.post(f"/api/prompts/{ident}/restaurer/9")).status_code == 404


@pytest.mark.asyncio
async def test_preset_ancien_sans_historique(client, db_session):
    from models.prompt import PromptPreset
    ancien = PromptPreset(id=uuid.uuid4(), nom="Ancien fictif", prompt_text="Texte d'avant l'historique.")
    db_session.add(ancien)
    await db_session.commit()
    # Première modification : le contenu d'avant devient la v1, la modification la v2.
    await client.put(f"/api/prompts/{ancien.id}", json={"prompt_text": "Texte fictif retouché."})
    v = await _versions(client, ancien.id)
    assert [(x["version"], x["prompt_text"]) for x in v] == [(2, "Texte fictif retouché."),
                                                              (1, "Texte d'avant l'historique.")]
    assert v[1]["commentaire"] == "Contenu existant avant l'historique"


@pytest.mark.asyncio
async def test_preset_ancien_lu_avant_toute_modification(client, db_session):
    from models.prompt import PromptPreset
    ancien = PromptPreset(id=uuid.uuid4(), nom="Ancien fictif 2", prompt_text="Texte ancien fictif.")
    db_session.add(ancien)
    await db_session.commit()
    assert [x["version"] for x in await _versions(client, ancien.id)] == [1]
    assert [x["version"] for x in await _versions(client, ancien.id)] == [1]   # pas de doublon


@pytest.mark.asyncio
async def test_suppression_efface_l_historique(client, db_session):
    from sqlalchemy import func, select

    from models.prompt_preset_version import PromptPresetVersion
    ident = (await client.post("/api/prompts", json=PRESET)).json()["id"]
    await client.put(f"/api/prompts/{ident}", json={"prompt_text": "Texte fictif 2."})
    assert (await client.delete(f"/api/prompts/{ident}")).status_code == 200
    restant = (await db_session.execute(select(func.count()).select_from(PromptPresetVersion)
                                        .where(PromptPresetVersion.preset_id == uuid.UUID(ident)))).scalar()
    assert restant == 0
    assert (await client.get(f"/api/prompts/{ident}/versions")).status_code == 404


def test_acces_historique_presets_admin():
    assert acces.classer("GET", "/api/prompts/{prompt_id}/versions") == acces.ADMIN
    assert acces.classer("POST", "/api/prompts/{prompt_id}/restaurer/{version}") == acces.ADMIN
    assert acces.classer("GET", "/api/prompts") == acces.UTILISATEUR


def test_seed_sans_modele_absent():
    fichier = Path(__file__).resolve().parents[2] / "scripts" / "seed-prompts.json"
    if not fichier.exists():   # conteneur de test : seul backend/ est monté
        pytest.skip("scripts/seed-prompts.json hors du conteneur")
    seed = json.loads(fichier.read_text(encoding="utf-8"))
    assert len(seed) == 6
    assert not {p["modele_prefere"] for p in seed} & {"mixtral:latest", "mistral:latest"}
