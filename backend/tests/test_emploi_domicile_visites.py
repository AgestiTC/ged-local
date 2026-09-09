"""
Tests — visites : intervenants, entretiens et checklist par entretien
=====================================================================
Ce qui est réellement fragile ici, et donc testé :

- **la checklist appartient à l'ENTRETIEN, pas à la personne** : c'est la correction du plan
  initial, et elle ne vaut que si un second rendez-vous n'écrase pas les réponses du
  premier — sinon on perd l'information la plus utile, *ce qui a bougé entre les deux* ;
- **la reprise des réponses** d'un entretien précédent : ce qui rend une seconde visite
  supportable, sans modifier l'entretien d'origine ;
- **les clés stables** des questions : c'est par elles que les réponses sont stockées, et
  une clé perdue efface silencieusement une réponse ;
- **la sauvegarde réponse par réponse** : la fiche se remplit debout, au bout d'un VPN ;
- **l'agrément périmé**, la seule date qu'on oublie de regarder ;
- **les liens d'Administration repris automatiquement**, dédoublonnés.
"""

from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.emploi_domicile import contenu


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
async def dossier(client):
    """Un dossier portant la capacité, prêt à recevoir des intervenants."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/dossiers", json={"titre": "Devenir parent"})
        await c.patch("/api/dossiers/devenir-parent",
                      json={"modules": {"emploi-domicile": {"profil": "assmat"}}})
    return "devenir-parent"


# ─── Les clés de la checklist ─────────────────────────────────────────────────────────

def test_toutes_les_questions_ont_une_cle_unique():
    """
    Les réponses sont stockées PAR CLÉ. Une clé manquante rendrait la question insaisissable,
    une clé dupliquée ferait écrire deux questions au même endroit — et l'une des deux
    réponses disparaîtrait sans bruit.
    """
    cles = [q["cle"] for g in contenu.checklist(None) for q in g["questions"]]
    assert all(cles), "chaque question doit porter une clé"
    assert len(cles) == len(set(cles)), "clés dupliquées"


# ─── Les intervenants ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_le_nom_suffit_a_creer_une_fiche(client, dossier):
    """Une fiche à moitié remplie pendant un premier appel vaut mieux qu'un formulaire abandonné."""
    async with client as c:
        r = await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                         json={"nom": "Martin"})
    assert r.status_code == 201
    assert r.json()["statut"] == "a_contacter" and r.json()["nb_entretiens"] == 0


@pytest.mark.asyncio
async def test_agrement_perime_est_signale(client, dossier):
    """Sans agrément valide, il n'y a ni aide ni accueil légal : ça doit sauter aux yeux."""
    hier = (date.today() - timedelta(days=1)).isoformat()
    demain = (date.today() + timedelta(days=1)).isoformat()
    async with client as c:
        perime = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                               json={"nom": "A", "agrement_echeance": hier})).json()
        valide = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                               json={"nom": "B", "agrement_echeance": demain})).json()
    assert perime["agrement_perime"] is True
    assert valide["agrement_perime"] is False


@pytest.mark.asyncio
async def test_statut_invalide_refuse(client, dossier):
    async with client as c:
        r = await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                         json={"nom": "X", "statut": "peut-etre"})
    assert r.status_code == 400 and "statut" in r.json()["detail"]


# ─── Les entretiens ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prendre_rdv_fait_avancer_le_suivi(client, dossier):
    """Rester « à contacter » avec une visite calée obligerait à un geste que personne ne fait."""
    async with client as c:
        i = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                          json={"nom": "Martin"})).json()
        e = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/entretiens",
                          json={"type": "visite", "date_prevue": "2026-10-02",
                                "heure_debut": "14:00"})).json()
        fiche = (await c.get(f"/api/emploi-domicile/intervenants/{i['id']}")).json()

    assert e["rang"] == 1 and e["statut"] == "planifie"
    assert fiche["statut"] == "entretien"


@pytest.mark.asyncio
async def test_prochain_rdv_ignore_les_entretiens_sans_date(client, dossier):
    """Un entretien sans date est une intention, pas un rendez-vous : ne pas l'afficher comme tel."""
    async with client as c:
        i = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                          json={"nom": "Martin"})).json()
        await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/entretiens",
                     json={"type": "telephone"})
        liste = (await c.get(f"/api/emploi-domicile/{dossier}/intervenants")).json()

    assert liste["intervenants"][0]["prochain_rdv"] is None
    assert liste["intervenants"][0]["nb_entretiens"] == 1


@pytest.mark.asyncio
async def test_une_reponse_a_la_fois_et_le_compte_suit(client, dossier):
    """Sauvegarde au fil de la saisie : perdre vingt réponses sur une coupure de VPN est le pire cas."""
    async with client as c:
        i = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                          json={"nom": "Martin"})).json()
        e = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/entretiens",
                          json={"type": "visite"})).json()

        e = (await c.post(f"/api/emploi-domicile/entretiens/{e['id']}/reponse",
                          json={"cle": "lieu_animaux_tabac", "avis": "reserve",
                                "texte": "un chien, calme"})).json()
        assert e["nb_repondues"] == 1

        # Une réponse vidée est RETIRÉE, pas stockée vide : le compte doit rester juste.
        e = (await c.post(f"/api/emploi-domicile/entretiens/{e['id']}/reponse",
                          json={"cle": "lieu_animaux_tabac"})).json()
        assert e["nb_repondues"] == 0 and "lieu_animaux_tabac" not in e["reponses"]


@pytest.mark.asyncio
async def test_avis_invalide_refuse(client, dossier):
    async with client as c:
        i = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                          json={"nom": "M"})).json()
        e = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/entretiens",
                          json={})).json()
        r = await c.post(f"/api/emploi-domicile/entretiens/{e['id']}/reponse",
                         json={"cle": "quo_repas", "avis": "bof"})
    assert r.status_code == 400


# ─── Le cœur : un second entretien ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_second_entretien_a_sa_propre_checklist(client, dossier):
    """
    LA raison d'être de ce découpage : deux visites chez la même personne, deux jeux de
    réponses. Si le second écrasait le premier, on perdrait ce qui a changé entre les deux.
    """
    async with client as c:
        i = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                          json={"nom": "Martin"})).json()
        e1 = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/entretiens",
                           json={"type": "visite"})).json()
        await c.post(f"/api/emploi-domicile/entretiens/{e1['id']}/reponse",
                     json={"cle": "org_conges", "avis": "non", "texte": "ne sait pas encore"})

        e2 = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/entretiens",
                           json={"type": "seconde_visite"})).json()
        await c.post(f"/api/emploi-domicile/entretiens/{e2['id']}/reponse",
                     json={"cle": "org_conges", "avis": "ok", "texte": "août, dates données"})

        fiche = (await c.get(f"/api/emploi-domicile/intervenants/{i['id']}")).json()

    premier, second = fiche["entretiens"][0], fiche["entretiens"][1]
    assert premier["rang"] == 1 and second["rang"] == 2
    assert premier["reponses"]["org_conges"]["avis"] == "non"
    assert second["reponses"]["org_conges"]["avis"] == "ok", "le premier n'est pas écrasé"


@pytest.mark.asyncio
async def test_reprendre_les_reponses_du_precedent(client, dossier):
    """On ne repose pas quarante questions : on met à jour ce qui a changé."""
    async with client as c:
        i = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                          json={"nom": "Martin"})).json()
        e1 = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/entretiens",
                           json={"type": "visite"})).json()
        await c.post(f"/api/emploi-domicile/entretiens/{e1['id']}/reponse",
                     json={"cle": "quo_repas", "avis": "ok", "texte": "elle fournit"})

        e2 = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/entretiens",
                           json={"type": "seconde_visite", "reprendre_de": "precedent"})).json()

        # Modifier le second ne doit RIEN changer au premier : c'est ce qui garde l'écart lisible.
        await c.post(f"/api/emploi-domicile/entretiens/{e2['id']}/reponse",
                     json={"cle": "quo_repas", "avis": "reserve", "texte": "finalement non"})
        fiche = (await c.get(f"/api/emploi-domicile/intervenants/{i['id']}")).json()

    assert e2["reponses"]["quo_repas"]["avis"] == "ok", "les réponses sont bien reprises"
    assert fiche["entretiens"][0]["reponses"]["quo_repas"]["avis"] == "ok"
    assert fiche["entretiens"][1]["reponses"]["quo_repas"]["avis"] == "reserve"


@pytest.mark.asyncio
async def test_reprendre_un_entretien_d_une_autre_personne_est_refuse(client, dossier):
    async with client as c:
        a = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants", json={"nom": "A"})).json()
        b = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants", json={"nom": "B"})).json()
        ea = (await c.post(f"/api/emploi-domicile/intervenants/{a['id']}/entretiens",
                           json={})).json()
        r = await c.post(f"/api/emploi-domicile/intervenants/{b['id']}/entretiens",
                         json={"reprendre_de": ea["id"]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_supprimer_une_fiche_emporte_ses_entretiens(client, dossier):
    """Pas de visite orpheline en base."""
    async with client as c:
        i = (await c.post(f"/api/emploi-domicile/{dossier}/intervenants",
                          json={"nom": "Martin"})).json()
        e = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/entretiens",
                          json={})).json()
        await c.delete(f"/api/emploi-domicile/intervenants/{i['id']}")
        reste = await c.patch(f"/api/emploi-domicile/entretiens/{e['id']}", json={"statut": "fait"})
    assert reste.status_code == 404


# ─── Les liens repris d'Administration ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_liens_administration_pertinents_sont_repris(client, db_session):
    """
    Ajouter un lien dans Administration doit le faire apparaître ici, sans saisie en double —
    et sans noyer les guichets sous les liens médicaux ou bancaires.
    """
    import json

    from models.config import Config

    db_session.add(Config(cle="admin_links", valeur=json.dumps([
        {"label": "Ma CAF", "section": "Famille", "url": "https://caf.fr/mon-compte"},
        {"label": "Doctolib", "section": "Médical", "url": "https://doctolib.fr"},
        # Déjà livré par le module : ne doit pas apparaître deux fois.
        {"label": "Pajemploi", "section": "Gouv", "url": "https://www.pajemploi.urssaf.fr"},
    ])))
    await db_session.commit()

    async with client as c:
        liens = (await c.get("/api/emploi-domicile/fiches")).json()["liens"]

    urls = [l["url"] for l in liens]
    assert any("caf.fr/mon-compte" in u for u in urls), "un lien pertinent est repris"
    assert not any("doctolib" in u for u in urls), "un lien hors sujet ne l'est pas"
    assert sum(1 for u in urls if "pajemploi" in u) == 1, "dédoublonné par URL"
    assert {l["origine"] for l in liens} <= {"module", "administration"}


@pytest.mark.asyncio
async def test_liens_administration_illisibles_ne_cassent_pas_l_ecran(client, db_session):
    from models.config import Config

    db_session.add(Config(cle="admin_links", valeur="{ceci n'est pas du JSON"))
    await db_session.commit()

    async with client as c:
        r = await c.get("/api/emploi-domicile/fiches")

    assert r.status_code == 200 and r.json()["liens"], "les liens livrés restent affichés"
