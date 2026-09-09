"""
Tests — module emploi à domicile (phase 1 : fiches et checklist)
================================================================
Ce qui est réellement fragile ici, et donc testé :

- **la table des profils décide de tout** : le guichet dépend du LIEU (Pajemploi chez elle,
  CESU chez vous pour un ménage), et c'est l'erreur la plus coûteuse du sujet ;
- **la capacité déclarée sur le dossier**, qui remplace le `if slug == 'devenir-parent'` :
  elle doit s'appliquer à un dossier DÉJÀ installé (sinon une prod existante n'aurait jamais
  l'onglet) sans écraser une configuration faite à la main ;
- **la promesse « aucun chiffre »** : une fiche réglementaire qui annoncerait un montant
  serait fausse en janvier sans que rien ne le signale ;
- **un profil non documenté rend quand même le tronc commun, et le dit** — un écran vide se
  lirait « il n'y a rien à savoir ».
"""

import re

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.emploi_domicile import contenu
from services.emploi_domicile.profils import PROFILS, profil


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


# ─── Les profils : c'est le LIEU qui décide du guichet ────────────────────────────────

@pytest.mark.parametrize("cle,guichet", [
    ("assmat", "Pajemploi"),          # chez elle
    ("garde_domicile", "Pajemploi"),  # chez vous, mais enfant de moins de 6 ans
    ("aide_domicile", "CESU"),        # chez vous, pas de garde d'enfant
    ("autre_sap", "CESU"),
])
def test_guichet_par_profil(cle, guichet):
    assert PROFILS[cle].guichet == guichet


def test_profil_inconnu_retombe_sur_assmat():
    """Une clé fantaisiste ne doit pas vider l'écran ni inventer un guichet."""
    assert profil("n-importe-quoi").cle == "assmat"
    assert profil(None).cle == "assmat"


def test_tous_les_profils_partagent_la_convention():
    """
    C'est le fait qui justifie UN module et non deux : même convention collective, donc
    même contrat et mêmes obligations. Si un profil sortait de ce cadre, l'architecture
    serait à revoir — et ce test le dirait.
    """
    socles = {p.socle for p in PROFILS.values()}
    assert socles == {"Assistants maternels du particulier employeur",
                      "Salariés du particulier employeur"}


# ─── Le contenu ───────────────────────────────────────────────────────────────────────

def test_aucun_montant_en_euros_dans_les_fiches():
    """
    Promesse tenue par un test, pas par la vigilance : les barèmes changent chaque année, et
    une fiche qui en contiendrait serait fausse en janvier sans que rien ne le signale.
    """
    p = profil("assmat")
    texte = repr(contenu.fiches(p)) + repr(contenu.checklist(p))
    montants = re.findall(r"\d[\d\s.,]*\s?(?:€|euros?)", texte)
    assert montants == [], f"montant figé trouvé dans le contenu : {montants}"


def test_la_fiche_guichet_vient_en_premier():
    """Se tromper de guichet coûte une aide : un lecteur qui n'en lit qu'une doit lire celle-là."""
    assert contenu.fiches(profil("assmat"))[0]["cle"] == "guichet"


def test_chaque_question_de_la_checklist_dit_pourquoi():
    """Une question sans son pourquoi se récite ; avec, elle s'adapte."""
    for groupe in contenu.checklist(profil("assmat")):
        for q in groupe["questions"]:
            assert q.get("pourquoi"), f"« {q['texte']} » n'explique pas ce qu'on en fait"


@pytest.mark.asyncio
async def test_fiches_servies_avec_leur_date_et_leur_avertissement(client):
    async with client as c:
        data = (await c.get("/api/emploi-domicile/fiches")).json()

    assert data["profil"]["cle"] == "assmat"
    assert data["profil"]["onglet"] == "Nounou", "l'onglet porte le profil, pas le module"
    assert data["verifie_le"] and data["avertissement"]
    assert data["fiches"] and data["checklist"] and data["liens"]


@pytest.mark.asyncio
async def test_profil_non_documente_rend_quand_meme_le_tronc_commun(client):
    """Un écran vide se lirait « il n'y a rien à savoir », ce qui est faux."""
    async with client as c:
        data = (await c.get("/api/emploi-domicile/fiches",
                            params={"profil": "aide_domicile"})).json()

    assert data["profil"]["guichet"] == "CESU"
    assert data["fiches"], "les fiches communes valent pour tous les profils"
    assert data["avertissements"], "et l'écran dit ce qui manque"


# ─── La capacité déclarée sur le dossier ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_seed_declare_la_capacite(client, db_session):
    async with client as c:
        await c.post("/api/dossiers/seed/devenir-parent")
        d = (await c.get("/api/dossiers/devenir-parent")).json()

    assert d["modules"]["emploi-domicile"]["profil"] == "assmat"


@pytest.mark.asyncio
async def test_capacite_ajoutee_a_un_dossier_deja_installe(client, db_session):
    """
    Le cas qui compte vraiment : une installation existante doit gagner l'onglet en
    réinstallant le pré-rempli. Sans ça, la fonctionnalité serait livrée et invisible pour
    tous ceux qui ont déjà le dossier — c'est-à-dire pour l'utilisateur.
    """
    from models.dossier import DossierThematique
    from sqlalchemy import select

    async with client as c:
        await c.post("/api/dossiers/seed/devenir-parent")

        d = (await db_session.execute(
            select(DossierThematique).where(DossierThematique.slug == "devenir-parent")
        )).scalar_one()
        d.modules = {}
        await db_session.commit()

        await c.post("/api/dossiers/seed/devenir-parent")
        rendu = (await c.get("/api/dossiers/devenir-parent")).json()

    assert rendu["modules"]["emploi-domicile"]["profil"] == "assmat"


@pytest.mark.asyncio
async def test_une_capacite_reglee_a_la_main_n_est_pas_ecrasee(client):
    """Réinstaller un pré-rempli ne doit jamais défaire un réglage de l'utilisateur."""
    async with client as c:
        await c.post("/api/dossiers/seed/devenir-parent")
        await c.patch("/api/dossiers/devenir-parent",
                      json={"modules": {"emploi-domicile": {"profil": "aide_domicile"}}})
        await c.post("/api/dossiers/seed/devenir-parent")
        rendu = (await c.get("/api/dossiers/devenir-parent")).json()

    assert rendu["modules"]["emploi-domicile"]["profil"] == "aide_domicile"


@pytest.mark.asyncio
async def test_capacite_declarable_sur_n_importe_quel_dossier(client):
    """C'est ce qui rend le mécanisme générique plutôt que réservé à « Devenir parent »."""
    async with client as c:
        await c.post("/api/dossiers", json={"titre": "Employer chez soi"})
        await c.patch("/api/dossiers/employer-chez-soi",
                      json={"modules": {"emploi-domicile": {"profil": "aide_domicile"}}})
        rendu = (await c.get("/api/dossiers/employer-chez-soi")).json()

    assert rendu["modules"]["emploi-domicile"]["profil"] == "aide_domicile"


@pytest.mark.asyncio
async def test_dossier_ordinaire_n_a_aucune_capacite(client):
    """Pas d'onglet parasite : un dossier de veille reste un dossier de veille."""
    async with client as c:
        await c.post("/api/dossiers", json={"titre": "RGPD"})
        assert (await c.get("/api/dossiers/rgpd")).json()["modules"] == {}
