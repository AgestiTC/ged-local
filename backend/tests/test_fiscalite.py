"""
Tests — Aide à la déclaration d'impôts
======================================
Ce qui est réellement fragile ici, et donc testé :

- la **garantie structurelle** « aucun montant sans source » : c'est elle qui empêche un
  chiffre non traçable d'être recopié dans une déclaration, et elle ne vaut que si elle
  est tenue par le constructeur, pas par la bonne volonté des appelants ;
- le **regroupement par formulaire puis par case**, avec les lignes à trancher en tête —
  l'écran répond à « dans quelle case », pas à « quels modules ai-je » ;
- la **résolution de case par une réponse** : tant qu'on n'a pas répondu, aucune case
  n'est inventée ; une fois la réponse donnée, elle est mémorisée **pour l'année** ;
- le fait qu'un contributeur **sans donnée reste affiché** (« rien pour 2026 ») et qu'un
  contributeur **en échec ne vide pas l'écran** — les deux façons de rendre l'onglet faux
  par omission ;
- le **filtre par année**, seul lien entre une pièce et une déclaration.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from models.document import Document
from models.metadata import MetadonneeIA
from services.fiscalite import registre
from services.fiscalite.contributeurs.ged_pieces import GedPieces
from services.fiscalite.registre import LigneFiscale, Source


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def registre_vierge():
    """
    Le registre est un dictionnaire de MODULE : sans remise à zéro, un test qui enregistre
    un contributeur factice le laisse en place pour tous les suivants — et l'onglet
    « n'affiche rien » ou « affiche trop » selon l'ordre d'exécution. Même précaution que
    `config_runtime_vierge`.
    """
    sauvegarde = dict(registre._CONTRIBUTEURS)
    registre.reinitialiser()
    yield
    registre.reinitialiser()
    registre._CONTRIBUTEURS.update(sauvegarde)


async def _piece(db, nom: str, annee: int, *, categorie: str | None = None,
                 tags: list[str] | None = None) -> Document:
    doc = Document(
        chemin=f"/docs/{nom}", nom=nom, extension="pdf", hash_sha256=f"h{nom}",
        date_modification_fichier=datetime(annee, 6, 15, tzinfo=timezone.utc),
    )
    db.add(doc)
    await db.flush()
    if categorie or tags:
        db.add(MetadonneeIA(document_id=doc.id, categorie=categorie, tags=tags or []))
    await db.commit()
    return doc


# ─── La garantie structurelle ─────────────────────────────────────────────────────────

def test_montant_sans_source_est_refuse():
    """Un chiffre qu'on ne peut pas remonter jusqu'à sa pièce n'a pas à s'afficher."""
    with pytest.raises(ValueError, match="source"):
        LigneFiscale(formulaire="2042-RICI", case="7GA", libelle="Garde",
                     montant=Decimal("2340"), nature="credit_impot", confiance="calcule")


def test_montant_avec_source_est_accepte():
    ligne = LigneFiscale(formulaire="2042-RICI", case="7GA", libelle="Garde",
                         montant=Decimal("2340.55"), nature="credit_impot", confiance="calcule",
                         sources=[Source(libelle="Relevé Pajemploi", ref="abc")])
    assert ligne.montant == Decimal("2340.55")


def test_ligne_sans_montant_ne_demande_aucune_source():
    """« Je sais OÙ, pas COMBIEN » est une réponse valable — la plus fréquente, même."""
    ligne = LigneFiscale(formulaire="2042-RICI", case="7DB", libelle="Salarié à domicile")
    assert ligne.montant is None and ligne.confiance == "a_saisir"


@pytest.mark.parametrize("champ,valeur", [("nature", "inventee"), ("confiance", "peut-etre")])
def test_vocabulaire_ferme(champ, valeur):
    with pytest.raises(ValueError):
        LigneFiscale(formulaire="2042", libelle="x", **{champ: valeur})


# ─── Le contributeur « pièces de la GED » ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pieces_reconnues_et_filtrees_par_annee(db_session):
    await _piece(db_session, "releve-pajemploi-mars.pdf", 2026)
    await _piece(db_session, "releve-pajemploi-avril.pdf", 2026)
    await _piece(db_session, "releve-pajemploi-2024.pdf", 2024)      # autre année
    await _piece(db_session, "photo-vacances.jpg", 2026)             # rien de fiscal

    lignes = await GedPieces().contributions(db_session, 2026, {})

    assert len(lignes) == 1, "une seule nature reconnue"
    ligne = lignes[0]
    assert ligne.case is None, "le rang de l'enfant n'est pas connu : aucune case inventée"
    assert ligne.question is not None
    assert len(ligne.sources) == 2, "seules les pièces de 2026 sont citées"


@pytest.mark.asyncio
async def test_case_resolue_par_la_reponse(db_session):
    await _piece(db_session, "facture-creche.pdf", 2026)

    lignes = await GedPieces().contributions(
        db_session, 2026, {"nb_enfants_garde_hors_domicile": "2"}
    )

    cases = [l.case for l in lignes]
    assert cases == ["7GA", "7GB"], "deux enfants → une case chacun, dans l'ordre"
    assert all(l.formulaire == "2042-RICI" for l in lignes)
    # Les pièces ne sont citées qu'une fois : les répéter laisserait croire que chaque
    # enfant a les siennes.
    assert lignes[0].sources and not lignes[1].sources


@pytest.mark.asyncio
async def test_aucun_montant_n_est_lu_dans_un_document(db_session):
    await _piece(db_session, "attestation-cesu-2026.pdf", 2026)
    lignes = await GedPieces().contributions(db_session, 2026, {})
    assert all(l.montant is None for l in lignes)


@pytest.mark.asyncio
async def test_ligne_compagne_des_aides_percues(db_session):
    """7DR n'a aucune pièce à elle, mais l'oublier fausse la déclaration au premier euro."""
    await _piece(db_session, "bulletin-cesu.pdf", 2026)
    lignes = await GedPieces().contributions(db_session, 2026, {})
    assert {l.case for l in lignes} == {"7DB", "7DR"}


@pytest.mark.asyncio
async def test_detection_par_metadonnees_ia_pas_seulement_le_nom(db_session):
    """Un scan nommé « doc0012.pdf » reste trouvable par ce que l'indexation a posé."""
    await _piece(db_session, "doc0012.pdf", 2026, categorie="Impôts", tags=["reçu fiscal"])
    lignes = await GedPieces().contributions(db_session, 2026, {})
    assert lignes and lignes[0].question is not None  # nature « don », case à trancher


# ─── Le routeur : ce qui s'affiche, et ce qui s'affiche quand il n'y a rien ───────────

@pytest.mark.asyncio
async def test_synthese_groupe_par_formulaire_et_case(client, db_session):
    registre.enregistrer(GedPieces())
    await _piece(db_session, "facture-creche.pdf", 2026)

    async with client as c:
        r = await c.post("/api/fiscalite/reponses",
                         json={"annee": 2026, "cle": "nb_enfants_garde_hors_domicile", "valeur": "1"})
        assert r.status_code == 200
        data = r.json()

    assert [f["code"] for f in data["formulaires"]] == ["2042-RICI"]
    assert [l["case"] for l in data["formulaires"][0]["lignes"]] == ["7GA"]
    assert data["millesime"]["avertissement"]
    # La réponse est mémorisée POUR L'ANNÉE : la situation change d'une année sur l'autre.
    assert data["reponses"]["nb_enfants_garde_hors_domicile"] == "1"


@pytest.mark.asyncio
async def test_lignes_a_trancher_remontent_en_tete(client, db_session):
    registre.enregistrer(GedPieces())
    await _piece(db_session, "bulletin-cesu.pdf", 2026)      # → 7DB + 7DR, sans question
    await _piece(db_session, "facture-creche.pdf", 2026)     # → case à trancher

    async with client as c:
        data = (await c.get("/api/fiscalite/synthese", params={"annee": 2026})).json()

    lignes = data["formulaires"][0]["lignes"]
    assert lignes[0]["case"] is None, "ce qui demande une action passe devant"
    assert lignes[0]["question"]["cle"] == "nb_enfants_garde_hors_domicile"


@pytest.mark.asyncio
async def test_contributeur_sans_donnee_reste_affiche(client, db_session):
    """Le silence se lit « à jour ». Un module qui n'a rien trouvé doit le dire."""
    registre.enregistrer(GedPieces())

    async with client as c:
        data = (await c.get("/api/fiscalite/synthese", params={"annee": 2026})).json()

    assert data["formulaires"] == []
    etat = data["contributeurs"][0]
    assert etat["etat"] == "vide" and "2026" in etat["message"]


@pytest.mark.asyncio
async def test_contributeur_en_echec_ne_vide_pas_l_ecran(client, db_session):
    class Casse:
        cle, libelle = "casse", "Contributeur cassé"

        async def annees(self, db):
            return []

        async def contributions(self, db, annee, reponses):
            raise RuntimeError("boom")

    registre.enregistrer(Casse())
    registre.enregistrer(GedPieces())
    await _piece(db_session, "bulletin-cesu.pdf", 2026)

    async with client as c:
        data = (await c.get("/api/fiscalite/synthese", params={"annee": 2026})).json()

    etats = {e["cle"]: e["etat"] for e in data["contributeurs"]}
    assert etats["casse"] == "erreur"
    assert etats["ged-pieces"] == "ok", "les autres sources restent affichées"
    assert data["nb_lignes"] > 0


@pytest.mark.asyncio
async def test_annee_par_defaut_est_l_annee_declarable(client):
    """L'impôt se déclare l'année suivante : ouvrir sur l'année en cours montrerait du vide."""
    registre.enregistrer(GedPieces())
    async with client as c:
        data = (await c.get("/api/fiscalite/synthese")).json()
    assert data["annee"] == datetime.now(tz=timezone.utc).year - 1


@pytest.mark.asyncio
async def test_reponse_effacee_fait_revenir_la_question(client, db_session):
    registre.enregistrer(GedPieces())
    await _piece(db_session, "facture-creche.pdf", 2026)

    async with client as c:
        await c.post("/api/fiscalite/reponses",
                     json={"annee": 2026, "cle": "nb_enfants_garde_hors_domicile", "valeur": "1"})
        data = (await c.post("/api/fiscalite/reponses",
                             json={"annee": 2026, "cle": "nb_enfants_garde_hors_domicile",
                                   "valeur": ""})).json()

    assert data["formulaires"][0]["lignes"][0]["case"] is None


@pytest.mark.asyncio
async def test_disponible_signale_le_registre_vide(client):
    async with client as c:
        assert (await c.get("/api/fiscalite/disponible")).json()["disponible"] is False
        registre.enregistrer(GedPieces())
        assert (await c.get("/api/fiscalite/disponible")).json()["disponible"] is True


# ─── Datation d'une pièce : corriger l'année déduite ──────────────────────────────────
# Le rattachement par date de fichier était la limite assumée du lot 2. Ce qui est testé
# ici, c'est qu'on puisse la CORRIGER, et que la correction tienne.

def test_datation_privilegie_l_annee_de_reference():
    """« au titre de l'année 2025 » l'emporte sur une date d'impression plus récente."""
    from services.fiscalite import datation

    texte = ("Attestation fiscale établie au titre de l'année 2025. "
             "Document imprimé le 14/02/2026 à Paris.")
    trouves = datation.candidats(texte, "attestation.pdf")

    assert trouves[0].annee == 2025
    assert "2025" in (trouves[0].extrait or ""), "la preuve montrée doit contenir l'année"
    assert 2026 in [c.annee for c in trouves], "l'autre année reste proposée, en second"


def test_datation_ecarte_les_annees_implausibles():
    from services.fiscalite import datation
    trouves = datation.candidats("Contrat n° 2099-A signé en 1998.", None)
    assert [c.annee for c in trouves] == []


def test_datation_sans_texte_extrait_utilise_le_nom():
    """Une image non océrisée n'a pas de texte : le nom du fichier reste exploitable."""
    from services.fiscalite import datation
    trouves = datation.candidats(None, "pajemploi-2026-recap.pdf")
    assert trouves and trouves[0].annee == 2026 and trouves[0].motif == "nom du fichier"


@pytest.mark.asyncio
async def test_datation_expose_candidats_et_origine(client, db_session):
    doc = await _piece(db_session, "recap.pdf", 2026)
    doc.texte_extrait = "Récapitulatif des cotisations au titre de l'année 2025."
    await db_session.commit()

    async with client as c:
        data = (await c.get(f"/api/fiscalite/datation/{doc.id}")).json()

    assert data["confirmee"] is False
    assert data["annee_deduite"] == 2026, "l'année déduite reste celle du fichier"
    assert data["origine_deduite"].startswith("date de modification")
    assert data["candidats"][0]["annee"] == 2025, "le texte propose mieux que le fichier"


@pytest.mark.asyncio
async def test_annee_confirmee_prime_et_deplace_la_piece(client, db_session):
    """Une pièce datée à la main change d'année dans la synthèse — c'est tout l'objet."""
    registre.enregistrer(GedPieces())
    doc = await _piece(db_session, "bulletin-cesu.pdf", 2026)

    async with client as c:
        avant = (await c.get("/api/fiscalite/synthese", params={"annee": 2025})).json()
        assert avant["nb_lignes"] == 0

        await c.post(f"/api/fiscalite/datation/{doc.id}", json={"annee": 2025})

        apres = (await c.get("/api/fiscalite/synthese", params={"annee": 2025})).json()
        source = apres["formulaires"][0]["lignes"][0]["sources"][0]

    assert apres["nb_lignes"] > 0
    assert source["annee"] == 2025 and source["annee_confirmee"] is True
    assert "confirmées" in apres["formulaires"][0]["lignes"][0]["note"]


@pytest.mark.asyncio
async def test_datation_se_relache(client, db_session):
    """Pouvoir défaire compte autant que pouvoir trancher : une erreur doit se retirer."""
    registre.enregistrer(GedPieces())
    doc = await _piece(db_session, "bulletin-cesu.pdf", 2026)

    async with client as c:
        await c.post(f"/api/fiscalite/datation/{doc.id}", json={"annee": 2025})
        rendu = (await c.post(f"/api/fiscalite/datation/{doc.id}", json={})).json()

    assert rendu["confirmee"] is False and rendu["annee"] == 2026


@pytest.mark.asyncio
async def test_datation_document_inconnu(client):
    async with client as c:
        assert (await c.get("/api/fiscalite/datation/pas-un-uuid")).status_code == 400
        import uuid as _u
        assert (await c.get(f"/api/fiscalite/datation/{_u.uuid4()}")).status_code == 404
