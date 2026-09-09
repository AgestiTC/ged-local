"""
Tests — contributeur fiscal « emploi-domicile »
===============================================
Ce contributeur est le premier de l'onglet à **produire un montant**. C'est ce qui le rend
utile, et c'est aussi ce qui le rend dangereux : un chiffre affiché à côté d'un numéro de case
sera recopié tel quel dans une déclaration. Les tests portent donc sur les garde-fous, plus
que sur l'arithmétique :

- **le lieu décide de la case, pas le métier** — une garde chez l'assistante maternelle va en
  7GA, la même garde chez vous va en 7DB. C'est l'erreur de rangement la plus courante, et la
  seule que l'application peut éviter à coup sûr puisqu'elle connaît le profil ;
- **aucun montant sur une année incomplète** — onze mois ressemblent à une année ;
- **le total n'est pas le montant à déclarer** : les aides s'en déduisent, et l'attestation
  fiscale fait foi. La ligne doit le dire, pas le sous-entendre ;
- **un brouillon sans journal n'est pas une dépense** — une simulation affichée parmi des
  montants réels serait indiscernable d'un versement ;
- **la question du rang d'enfant partage sa clé avec `ged-pieces`** : deux clés distinctes la
  poseraient deux fois, avec deux réponses possiblement contradictoires sur le même écran.
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.fiscalite.contributeurs import ged_pieces
from services.fiscalite.contributeurs.emploi_domicile import EmploiDomicile, QUESTION_RANG


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def _monter(profil: str, champs: dict, mois: int, annee: int = 2026) -> str:
    """
    Crée dossier + intervenant + contrat, et remplit `mois` mois de journal.

    Le journal est rempli par l'API et non en base : c'est le chemin que prend l'utilisateur,
    et c'est lui qui doit produire des totaux justes.
    """
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/dossiers", json={"titre": "Devenir parent"})
        i = (await c.post("/api/emploi-domicile/devenir-parent/intervenants",
                          json={"nom": "Martin", "prenom": "Claire", "profil": profil})).json()
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/contrats",
                           json={"champs": {**champs, "profil": profil}})).json()
        await c.patch(f"/api/emploi-domicile/contrats/{ct['id']}", json={"statut": "signe"})
        for n in range(1, mois + 1):
            await c.put(f"/api/emploi-domicile/contrats/{ct['id']}/journal/{annee}/{n}",
                        json={"heures": "100", "jours_accueil": 20, "repas": 20, "km": "40"})
    return ct["id"]


TARIFS = {"taux_horaire": "4,20", "heures_semaine": "40",
          "entretien_jour": "3,60", "repas_jour": "4,00", "tarif_km": "0,50"}


# ─── Le lieu décide de la case ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_assistante_maternelle_va_en_garde_hors_domicile(client, db_session):
    """Elle accueille chez elle : 7GA et suivantes, pas 7DB."""
    await _monter("assmat", TARIFS, mois=12)
    async with client:
        lignes = await EmploiDomicile().contributions(
            db_session, 2026, {QUESTION_RANG.cle: "1"})
    cases = [l.case for l in lignes]
    assert "7GA" in cases
    assert "7DB" not in cases, "une garde chez l'assistante maternelle n'est pas un emploi à domicile"


@pytest.mark.asyncio
async def test_aide_menagere_va_en_services_a_la_personne(client, db_session):
    """Elle travaille chez vous : 7DB, avec la case des aides en compagne."""
    await _monter("aide_domicile", TARIFS, mois=12)
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {})
    cases = [l.case for l in lignes]
    assert cases == ["7DB", "7DR"]
    assert not any(c in cases for c in ("7GA", "7GB", "7GC"))


@pytest.mark.asyncio
async def test_garde_a_votre_domicile_n_est_pas_une_garde_hors_domicile(client, db_session):
    """
    Le piège du dispositif : même métier, même enfant, autre case — parce que le lieu change.
    C'est écrit dans la notice, et c'est ce qu'on rate.
    """
    await _monter("garde_domicile", TARIFS, mois=12)
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {})
    assert [l.case for l in lignes] == ["7DB", "7DR"]


# ─── Le montant, et son refus ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_annee_complete_donne_un_montant_calcule(client, db_session):
    """
    12 × (100 h × 4,20 + 20 j × 3,60 + 20 repas × 4,00 + 40 km × 0,50) = 12 × 592 = 7 104 €.
    Le montant est marqué « calculé » : il est reconstitué depuis des données saisies.
    """
    await _monter("aide_domicile", TARIFS, mois=12)
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {})
    ligne = next(l for l in lignes if l.case == "7DB")
    assert ligne.montant == Decimal("7104.00")
    assert ligne.confiance == "calcule"
    assert ligne.sources, "un montant sans source serait refusé par le registre"


@pytest.mark.asyncio
async def test_annee_incomplete_ne_donne_aucun_montant(client, db_session):
    """
    Onze mois ressemblent à une année. Le total serait faux d'un douzième, sans que rien ne
    le signale au moment où on le recopie — d'où le refus pur et simple du chiffre.
    """
    await _monter("aide_domicile", TARIFS, mois=11)
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {})
    ligne = next(l for l in lignes if l.case == "7DB")
    assert ligne.montant is None
    assert ligne.confiance == "a_saisir"
    assert "11/12" in ligne.note


@pytest.mark.asyncio
async def test_le_total_dit_qu_il_n_est_pas_le_montant_a_declarer(client, db_session):
    """
    Les aides perçues se déduisent, et l'attestation fiscale fait foi. Un total présenté sec
    à côté d'un numéro de case serait recopié sans ces deux réserves.
    """
    await _monter("aide_domicile", TARIFS, mois=12)
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {})
    note = next(l for l in lignes if l.case == "7DB").note
    assert "aides" in note.lower() and "attestation fiscale" in note.lower()


@pytest.mark.asyncio
async def test_le_detail_du_calcul_est_donne(client, db_session):
    """Un total qu'on ne peut pas décomposer ne peut pas être confronté à l'attestation."""
    await _monter("aide_domicile", TARIFS, mois=12)
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {})
    note = next(l for l in lignes if l.case == "7DB").note
    assert "Salaire" in note and "Entretien" in note and "Repas" in note


# ─── Ce qui ne doit PAS apparaître ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_brouillon_sans_journal_n_est_pas_une_depense(client, db_session):
    """Une simulation affichée parmi des montants réels serait indiscernable d'un versement."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/dossiers", json={"titre": "Devenir parent"})
        i = (await c.post("/api/emploi-domicile/devenir-parent/intervenants",
                          json={"nom": "Essai", "profil": "assmat"})).json()
        await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/contrats",
                     json={"champs": TARIFS})
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {})
    assert lignes == []


@pytest.mark.asyncio
async def test_annee_sans_journal_ne_produit_rien(client, db_session):
    """Le contrat existe, mais rien n'a été saisi pour CETTE année-là."""
    await _monter("aide_domicile", TARIFS, mois=12, annee=2025)
    async with client:
        assert await EmploiDomicile().contributions(db_session, 2024, {}) == []


@pytest.mark.asyncio
async def test_annees_proposees_sont_celles_du_journal(client, db_session):
    """Proposer une année sans données ferait chercher ce qui n'existe pas."""
    await _monter("aide_domicile", TARIFS, mois=3, annee=2025)
    async with client:
        assert await EmploiDomicile().annees(db_session) == [2025]


# ─── La case à trancher ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rang_de_l_enfant_demande_avant_de_choisir_une_case(client, db_session):
    """Rendre 7GA « pour afficher quelque chose » serait pire que de poser la question."""
    await _monter("assmat", TARIFS, mois=12)
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {})
    assert len(lignes) == 1
    assert lignes[0].case is None
    assert lignes[0].question is not None
    assert lignes[0].montant is None, "pas de montant tant qu'on ne sait pas où le mettre"


@pytest.mark.asyncio
async def test_reponse_deux_enfants_ouvre_deux_cases(client, db_session):
    await _monter("assmat", TARIFS, mois=12)
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {QUESTION_RANG.cle: "2"})
    assert [l.case for l in lignes] == ["7GA", "7GB"]
    assert lignes[0].montant is not None
    assert lignes[1].montant is None, "le journal ne dit pas quel enfant a été gardé combien"


@pytest.mark.asyncio
async def test_le_passage_des_six_ans_est_signale_pas_tranche(client, db_session):
    """Matothèque ne connaît pas l'âge de l'enfant : le taire laisserait croire qu'elle l'a pris en compte."""
    await _monter("assmat", TARIFS, mois=12)
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {QUESTION_RANG.cle: "1"})
    assert "6 ans" in lignes[0].note


def test_la_question_du_rang_partage_sa_cle_avec_ged_pieces():
    """
    Même question, même personne, même année. Deux clés la poseraient deux fois sur le même
    écran, et autoriseraient deux réponses contradictoires — dont une seule serait suivie.
    """
    nature = next(n for n in ged_pieces._NATURES if n["cle"] == "garde_enfant")
    assert nature["question"].cle == QUESTION_RANG.cle


# ─── Le lien de retour ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_source_ouvre_l_ecran_du_contrat(client, db_session):
    """
    Citer un contrat sans permettre de l'ouvrir oblige à le retrouver à la main — exactement
    ce que cet onglet prétend éviter. Et l'écran se choisit par la PERSONNE, pas par le
    contrat : un lien qui parle la mauvaise langue ouvre le bon dossier au mauvais endroit.
    """
    await _monter("aide_domicile", TARIFS, mois=12)
    async with client:
        lignes = await EmploiDomicile().contributions(db_session, 2026, {})
    source = next(l for l in lignes if l.case == "7DB").sources[0]
    assert source.type == "contrat"
    assert source.lien_interne is not None
    assert source.lien_interne.startswith("/dossiers/devenir-parent?onglet=contrat&personne=")
    assert source.annee_confirmee, "l'année vient du journal, pas d'une date de fichier"
