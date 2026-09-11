"""
Tests — récapitulatif imprimable et saison de déclaration
=========================================================
Le récapitulatif est le seul artefact de cet onglet qui **survit à la session**. C'est ce qui
change tout : sur un écran, une omission se rattrape en rechargeant ; sur un papier posé à
côté du clavier, elle est définitive — personne ne retournera vérifier.

D'où ce qui est testé ici :

- **rien ne disparaît entre l'écran et le papier** : les cases non tranchées, les alertes, et
  jusqu'aux modules qui n'ont RIEN trouvé. Un module silencieux se lit « à jour » ;
- **la confiance est écrite en toutes lettres** — l'infobulle de l'écran n'existe plus sur
  papier, et « à saisir » ne se recopie pas comme « calculé » ;
- **l'avertissement et la date de vérification y sont**, sans quoi le document se relit
  l'année suivante comme s'il valait encore ;
- **aucune date limite n'est affirmée** : elles varient par département et changent chaque
  année. Une échéance fausse *qui a l'air sûre* est pire que pas d'échéance.
"""

from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.fiscalite import recapitulatif


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


SYNTHESE = {
    "annee": 2025,
    "millesime": {"annee": 2026, "verifie_le": "2026-09-09",
                  "avertissement": "Ces montants sont une aide à la saisie, pas une déclaration.",
                  "url_officielle": "https://www.impots.gouv.fr/"},
    "formulaires": [{
        "code": "2042-RICI",
        "libelle": "Annexe réductions et crédits d'impôt",
        "lignes": [
            {"case": "7DB", "libelle": "Salarié à domicile", "montant": "7104.00",
             "confiance": "calcule", "provenance": "Contrats d'emploi à domicile",
             "note": "Total versé en 2025 d'après votre journal.",
             "sources": [{"libelle": "Claire Martin — Aide ménagère", "annee": 2025,
                          "annee_confirmee": True}],
             "question": None},
            {"case": None, "libelle": "Frais de garde hors domicile", "montant": None,
             "confiance": "a_verifier", "provenance": "Pièces déjà dans la GED",
             "note": "3 pièces trouvées.", "sources": [],
             "question": {"intitule": "Combien d'enfants gardés hors domicile ?"}},
        ],
    }],
    "alertes": [{"libelle": "Aucune pièce reconnue pour 2025", "note": "412 documents examinés."}],
    "contributeurs": [
        {"cle": "ged-pieces", "libelle": "Pièces déjà dans la GED", "etat": "vide", "nb_lignes": 0},
        {"cle": "emploi-domicile", "libelle": "Contrats d'emploi à domicile", "etat": "ok", "nb_lignes": 1},
    ],
}


# ─── Le document ──────────────────────────────────────────────────────────────────────

def test_le_montant_et_sa_case_sont_lisibles():
    texte = recapitulatif.rendre(SYNTHESE)
    assert "7DB" in texte and "7104.00" in texte


def test_la_confiance_est_ecrite_en_toutes_lettres():
    """Sur papier, l'infobulle de l'écran n'existe plus : le mot seul ne suffit pas."""
    texte = recapitulatif.rendre(SYNTHESE)
    assert "calculé à partir de vos données" in texte
    assert "a_saisir" not in texte, "aucun code technique ne doit fuir sur le papier"


def test_une_case_non_tranchee_reste_visible_sur_le_papier():
    """
    C'est là qu'il reste quelque chose à décider. La faire disparaître de l'export ferait
    recopier le reste en croyant avoir tout traité.
    """
    texte = recapitulatif.rendre(SYNTHESE)
    assert "À trancher" in texte
    assert "Combien d'enfants gardés hors domicile ?" in texte


def test_les_alertes_sont_a_part_pas_parmi_les_cases():
    """Rangée parmi les cases, une alerte passerait pour un montant à recopier."""
    texte = recapitulatif.rendre(SYNTHESE)
    section = texte.index("Ce que Matothèque n'a pas trouvé")
    assert section > texte.index("2042-RICI"), "les alertes viennent APRÈS les formulaires"
    assert "412 documents examinés" in texte


def test_un_module_sans_resultat_est_cite_quand_meme():
    """
    Un module silencieux se lit « je suis à jour ». Sur papier l'omission est définitive :
    personne n'ira vérifier l'écran pour savoir ce qui n'a pas été consulté.
    """
    texte = recapitulatif.rendre(SYNTHESE)
    assert "Pièces déjà dans la GED : rien trouvé" in texte


def test_l_avertissement_et_la_date_de_verification_sont_presents():
    """Un papier non daté se relit l'année suivante comme s'il valait encore."""
    texte = recapitulatif.rendre(SYNTHESE)
    assert "2026-09-09" in texte
    assert "aide à la saisie" in texte
    assert "ne calcule aucun impôt" in texte


def test_les_sources_suivent_leur_ligne():
    """Un montant qu'on ne peut pas remonter jusqu'à sa pièce n'a rien à faire sur le papier."""
    texte = recapitulatif.rendre(SYNTHESE)
    assert "Claire Martin" in texte


def test_annee_vide_le_dit_au_lieu_de_rendre_une_page_blanche():
    vide = {**SYNTHESE, "formulaires": [], "alertes": [], "contributeurs": []}
    texte = recapitulatif.rendre(vide)
    assert "Rien à reporter pour 2025" in texte


# ─── La saison ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("jour,etat", [
    (date(2026, 3, 12), "approche"),
    (date(2026, 4, 20), "ouverte"),
    (date(2026, 6, 2), "ouverte"),
    (date(2026, 7, 15), "passee"),
    (date(2026, 11, 3), "hors_saison"),
    (date(2026, 1, 8), "hors_saison"),
])
def test_les_quatre_saisons(jour, etat):
    assert recapitulatif.campagne(jour).etat == etat


def test_l_annee_a_declarer_est_toujours_la_precedente():
    """On déclare au printemps les revenus de l'année d'avant — jamais ceux de l'année en cours."""
    assert recapitulatif.campagne(date(2026, 4, 20)).annee_a_declarer == 2025
    assert recapitulatif.campagne(date(2026, 12, 31)).annee_a_declarer == 2025


@pytest.mark.parametrize("jour", [date(2026, 3, 1), date(2026, 5, 1), date(2026, 8, 1)])
def test_aucune_date_limite_n_est_affirmee(jour):
    """
    Les dates limites varient selon le département et changent chaque année. Les écrire en dur
    produirait exactement l'erreur que cet onglet existe pour éviter : une information fausse
    qui a l'air vérifiée.
    """
    message = recapitulatif.campagne(jour).message
    for interdit in ("date limite est", "avant le", "jusqu'au", "échéance du"):
        assert interdit not in message.lower()
    assert any(mot in message.lower() for mot in ("généralement", "habituellement",
                                                  "probablement", "impots.gouv.fr", "évite"))


# ─── La route ─────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_la_route_rend_un_texte_et_un_titre_exportables(client):
    async with client as c:
        r = (await c.get("/api/fiscalite/recapitulatif?annee=2025")).json()
    assert r["annee"] == 2025
    assert "2025" in r["titre"]
    assert r["texte"].startswith("# Aide à la déclaration")
    # Le titre devient un nom de fichier : pas d'accent, pas de caractère qui casse un
    # téléchargement selon le navigateur.
    assert r["titre"].isascii()


@pytest.mark.asyncio
async def test_la_synthese_porte_la_saison(client):
    """Le bandeau se calcule à l'affichage : rien n'est stocké, rien ne peut se désynchroniser."""
    async with client as c:
        r = (await c.get("/api/fiscalite/synthese")).json()
    assert r["campagne"]["etat"] in ("approche", "ouverte", "passee", "hors_saison")
    assert r["campagne"]["annee_a_declarer"] == r["annee"]
