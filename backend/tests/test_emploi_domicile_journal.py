"""
Tests — journal mensuel : ce qui a réellement été fait
======================================================
Ce journal sert à deux moments très différents : **chaque mois**, remplir la déclaration
Pajemploi/CESU ; **une fois l'an**, reporter un total sur la déclaration de revenus et solder
la régularisation. Les deux usages n'ont pas la même tolérance à l'approximation, et c'est
là-dessus que portent ces tests :

- **un mois vide n'est pas un mois à zéro** — la confusion ferait présenter comme complète une
  année à moitié saisie, et c'est ce total-là qu'on recopierait sur une déclaration ;
- **un total partiel le dit** — sinon le chiffre est faux sans que rien ne le signale ;
- **la saisie est partielle par nature** (les heures en fin de mois, les km plus tard) : un
  envoi ne doit pas effacer ce qu'un autre a écrit ;
- **les douze mois sont toujours rendus**, saisis ou non, parce que la question qui compte en
  ouvrant l'écran est « qu'est-ce qui manque ? » ;
- **l'écart d'heures** est une estimation au taux du contrat, pas une somme due — et le texte
  doit le dire, faute de quoi on la verserait telle quelle.
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.emploi_domicile import journal


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def contrat(client):
    """Un contrat calculable : 40 h/semaine à 4,20 € — le prévisionnel a donc un sens."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/dossiers", json={"titre": "Devenir parent"})
        i = (await c.post("/api/emploi-domicile/devenir-parent/intervenants",
                          json={"nom": "Martin", "prenom": "Claire"})).json()
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/contrats",
                           json={"champs": {"taux_horaire": "4,20",
                                            "heures_semaine": "40"}})).json()
    return ct["id"]


# ─── Le calcul pur ────────────────────────────────────────────────────────────────────

def test_mois_vide_n_est_pas_un_mois_a_zero():
    """
    La distinction fondatrice du module. Deux mois saisis à zéro et dix mois non remplis
    donnent les mêmes totaux ; seul `mois_saisis` les sépare — et c'est lui qui empêche de
    prendre un total à moitié rempli pour une année.
    """
    zeros = journal.recapituler(annee=2026, mois=[{"heures": Decimal("0")} for _ in range(2)])
    vides = journal.recapituler(annee=2026, mois=[{} for _ in range(12)])
    assert zeros.totaux.heures == vides.totaux.heures == Decimal("0.00")
    assert zeros.totaux.mois_saisis == 2
    assert vides.totaux.mois_saisis == 0


def test_annee_incomplete_le_dit_en_toutes_lettres():
    """Un total partiel qui ne se signale pas est un total faux."""
    recap = journal.recapituler(
        annee=2026,
        mois=[{"heures": Decimal("140")} for _ in range(5)] + [{} for _ in range(7)],
        heures_mensualisees=Decimal("173.33"), taux_horaire=Decimal("4.20"),
    )
    assert recap.totaux.mois_saisis == 5
    assert any("partiel" in r for r in recap.remarques)


def test_aucun_mois_saisi_explique_le_vide():
    """« 0 heure » et « rien de saisi » se lisent pareil à l'écran : le texte doit trancher."""
    recap = journal.recapituler(annee=2026, mois=[{} for _ in range(12)])
    assert recap.totaux.heures == Decimal("0.00")
    assert any("rien à additionner" in r for r in recap.remarques)
    assert recap.heures_prevues is None, "rien à comparer tant que rien n'est saisi"


def test_ecart_annuel_compare_le_fait_au_lisse():
    """
    Le salaire est lissé sur douze mois : la régularisation de fin d'année compare les heures
    payées (mensualisées × 12) aux heures réellement faites. C'est le seul calcul du module.
    """
    recap = journal.recapituler(
        annee=2026,
        mois=[{"heures": Decimal("180")} for _ in range(12)],
        heures_mensualisees=Decimal("173.33"), taux_horaire=Decimal("4.20"),
        salaire_mensuel=Decimal("727.99"),
    )
    assert recap.heures_prevues == Decimal("2079.96")
    assert recap.ecart_heures == Decimal("80.04")
    assert recap.montant_ecart == Decimal("336.17")
    assert recap.salaire_annuel_prevu == Decimal("8735.88")


def test_montant_d_ecart_se_presente_comme_une_estimation():
    """
    Ce montant ignore majorations et cotisations. Présenté sec, il serait versé tel quel —
    donc le texte doit porter la réserve, pas seulement la documentation du module.
    """
    recap = journal.recapituler(
        annee=2026,
        mois=[{"heures": Decimal("180")} for _ in range(12)],
        heures_mensualisees=Decimal("173.33"), taux_horaire=Decimal("4.20"),
    )
    remarque = " ".join(recap.remarques)
    assert "estimation" in remarque and "cotisations" in remarque


def test_contrat_incalculable_ne_compare_rien():
    """Comparer à un prévisionnel qui n'existe pas produirait un écart inventé."""
    recap = journal.recapituler(annee=2026, mois=[{"heures": Decimal("140")}])
    assert recap.heures_prevues is None and recap.ecart_heures is None
    assert any("ne permet pas" in r for r in recap.remarques)


def test_ligne_ouverte_puis_laissee_vide_ne_compte_pas():
    """On ouvre un mois, on referme sans rien saisir : il reste non saisi."""
    recap = journal.recapituler(annee=2026, mois=[{"declare": False, "note": None}])
    assert recap.totaux.mois_saisis == 0


# ─── L'API ────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_les_douze_mois_sont_toujours_rendus(client, contrat):
    """
    Même vierge, l'écran doit montrer les douze cases : c'est le trou qui informe. Renvoyer
    seulement les mois remplis obligerait le frontend à reconstituer l'année.
    """
    async with client as c:
        r = (await c.get(f"/api/emploi-domicile/contrats/{contrat}/journal?annee=2026")).json()
    assert [m["mois"] for m in r["mois"]] == list(range(1, 13))
    assert r["mois"][0]["nom"] == "janvier"
    assert all(m["heures"] is None for m in r["mois"]), "vide, pas zéro"
    assert r["recapitulatif"]["totaux"]["mois_saisis"] == 0


@pytest.mark.asyncio
async def test_saisir_un_mois_le_cree_puis_le_corrige(client, contrat):
    """L'écran n'a pas à savoir si la ligne existe : un PUT suffit, création comprise."""
    async with client as c:
        base = f"/api/emploi-domicile/contrats/{contrat}/journal"
        r = (await c.put(f"{base}/2026/3", json={"heures": "150,5", "repas": 20})).json()
        assert r["mois"][2]["heures"] == "150.50"
        assert r["mois"][2]["repas"] == 20

        r = (await c.put(f"{base}/2026/3", json={"heures": "152"})).json()
        assert r["mois"][2]["heures"] == "152.00"
        assert r["mois"][2]["repas"] == 20, "corriger les heures n'efface pas les repas"


@pytest.mark.asyncio
async def test_marquer_declare_n_efface_pas_la_saisie(client, contrat):
    """
    On coche « déclaré » depuis Pajemploi, des semaines après avoir saisi les heures. Si cet
    envoi minimal remettait le reste à zéro, on perdrait le mois sans s'en apercevoir.
    """
    async with client as c:
        base = f"/api/emploi-domicile/contrats/{contrat}/journal"
        await c.put(f"{base}/2026/1", json={"heures": "173,33", "jours_accueil": 18})
        r = (await c.put(f"{base}/2026/1", json={"declare": True})).json()
    assert r["mois"][0]["declare"] is True
    assert r["mois"][0]["heures"] == "173.33"
    assert r["mois"][0]["jours_accueil"] == 18
    assert r["recapitulatif"]["totaux"]["mois_declares"] == 1


@pytest.mark.asyncio
async def test_vider_un_mois_le_rend_non_saisi(client, contrat):
    """Effacer une saisie erronée doit ramener au vide, pas à un mois à zéro heure."""
    async with client as c:
        base = f"/api/emploi-domicile/contrats/{contrat}/journal"
        await c.put(f"{base}/2026/6", json={"heures": "160"})
        r = (await c.delete(f"{base}/2026/6")).json()
    assert r["mois"][5]["heures"] is None
    assert r["recapitulatif"]["totaux"]["mois_saisis"] == 0


@pytest.mark.asyncio
async def test_deux_annees_ne_se_melangent_pas(client, contrat):
    """La déclaration de revenus porte sur une année précise ; un report d'année serait faux."""
    async with client as c:
        base = f"/api/emploi-domicile/contrats/{contrat}/journal"
        await c.put(f"{base}/2025/2", json={"heures": "100"})
        await c.put(f"{base}/2026/2", json={"heures": "200"})
        a = (await c.get(f"{base}?annee=2025")).json()
        b = (await c.get(f"{base}?annee=2026")).json()
    assert a["recapitulatif"]["totaux"]["heures"] == "100.00"
    assert b["recapitulatif"]["totaux"]["heures"] == "200.00"
    assert 2025 in b["annees_disponibles"], "l'année saisie doit rester atteignable"


@pytest.mark.asyncio
async def test_annee_precedente_toujours_proposee(client, contrat):
    """C'est l'année qu'on vient chercher au printemps ; vide, elle serait absente du menu."""
    from datetime import datetime, timezone

    async with client as c:
        r = (await c.get(f"/api/emploi-domicile/contrats/{contrat}/journal")).json()
    assert datetime.now(tz=timezone.utc).year - 1 in r["annees_disponibles"]


@pytest.mark.asyncio
async def test_saisie_francaise_acceptee(client, contrat):
    """« 7,5 » est ce qu'on tape sur un clavier français ; le refuser ferait perdre la saisie."""
    async with client as c:
        r = (await c.put(f"/api/emploi-domicile/contrats/{contrat}/journal/2026/4",
                         json={"heures": "162,25", "km": "48,6"})).json()
    assert r["mois"][3]["heures"] == "162.25"
    assert r["mois"][3]["km"] == "48.60"


@pytest.mark.asyncio
async def test_mois_hors_bornes_refuse(client, contrat):
    async with client as c:
        base = f"/api/emploi-domicile/contrats/{contrat}/journal"
        assert (await c.put(f"{base}/2026/13", json={"heures": "10"})).status_code == 422
        assert (await c.put(f"{base}/1900/2", json={"heures": "10"})).status_code == 422


@pytest.mark.asyncio
async def test_contrat_inconnu_ne_renvoie_pas_un_journal_vide(client):
    """Un journal vide sur un mauvais identifiant se lirait « rien saisi » au lieu de « erreur »."""
    async with client as c:
        r = await c.get("/api/emploi-domicile/contrats/"
                        "00000000-0000-0000-0000-000000000000/journal")
    assert r.status_code == 404
