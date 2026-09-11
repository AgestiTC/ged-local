"""
Tests — suite du module emploi à domicile
==========================================
Quatre chantiers qui partagent une même idée : **ne pas obliger à ressaisir ce que
l'application sait déjà**, et ne pas exposer ce qu'elle n'a pas besoin de montrer.

- **Le rendez-vous au planning** : un entretien vit sur la fiche (on y prépare la visite) et
  au planning (on y regarde sa semaine). Les recopier à la main garantit qu'ils divergeront,
  et c'est toujours le calendrier qu'on croit. Le lien est donc **idempotent** — rappuyer
  déplace, ne duplique pas.
- **L'identité administrative** (n° de sécurité sociale, IBAN) : chiffrée au repos, **jamais**
  rendue en clair par défaut. Un champ affiché par défaut finit dans une capture d'écran.
- **Le dépôt du contrat en GED** : retrouvable par la recherche comme le reste, sans doublon
  à chaque régénération.
- **La comparaison de deux candidates** : ce qui les sépare, pas ce qu'elles ont en commun.
"""

from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def cle_de_chiffrement():
    """
    Une clé Fernet connue, posée directement dans le service.

    Sans elle, `crypto` va chercher `storage/.secret.key` et **l'écrit** s'il ne la trouve
    pas : la suite dépendrait alors d'un répertoire accessible en écriture, et elle échoue
    effectivement dans un conteneur dont le volume est monté en lecture seule. Un test qui
    tombe pour une raison d'environnement ne dit plus rien du code.

    On restaure l'état précédent : laisser cette clé en place ferait passer les tests des
    *sources* avec une clé qui n'est pas la leur.
    """
    from cryptography.fernet import Fernet

    from services import crypto

    precedent = crypto._fernet
    crypto._fernet = Fernet(Fernet.generate_key())
    yield
    crypto._fernet = precedent


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
async def fiche(client):
    """Un dossier, une personne suivie."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/dossiers", json={"titre": "Devenir parent"})
        i = (await c.post("/api/emploi-domicile/devenir-parent/intervenants",
                          json={"nom": "Martin", "prenom": "Claire",
                                "telephone": "06 12 34 56 78"})).json()
    return i["id"]


# ─── Le rendez-vous au planning ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poser_un_entretien_cree_un_jalon_nomme(client, fiche):
    """Le jalon doit se lire seul dans un calendrier : « Visite — Claire Martin »."""
    jour = (date.today() + timedelta(days=10)).isoformat()
    async with client as c:
        e = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/entretiens",
                          json={"date_prevue": jour, "heure_debut": "14:00",
                                "lieu": "chez elle"})).json()
        r = (await c.post(f"/api/emploi-domicile/entretiens/{e['id']}/planning")).json()

    assert r["jalon"]["titre"] == "Visite — Claire Martin"
    assert r["jalon"]["date_reelle"] == jour
    assert r["jalon"]["heure_debut"] == "14:00"
    assert r["entretien"]["jalon_id"] == r["jalon"]["id"]
    assert "chez elle" in r["jalon"]["detail"]


@pytest.mark.asyncio
async def test_reposer_deplace_au_lieu_de_dupliquer(client, fiche):
    """
    Un planning qui accumule trois fois le même rendez-vous parce qu'on a cliqué trois fois
    est un planning qu'on cesse de regarder.
    """
    jour = (date.today() + timedelta(days=10)).isoformat()
    plus_tard = (date.today() + timedelta(days=17)).isoformat()
    async with client as c:
        e = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/entretiens",
                          json={"date_prevue": jour})).json()
        a = (await c.post(f"/api/emploi-domicile/entretiens/{e['id']}/planning")).json()

        await c.patch(f"/api/emploi-domicile/entretiens/{e['id']}",
                      json={"date_prevue": plus_tard})
        b = (await c.post(f"/api/emploi-domicile/entretiens/{e['id']}/planning")).json()

        planning = (await c.get("/api/dossiers/devenir-parent/planning")).json()

    assert a["jalon"]["id"] == b["jalon"]["id"], "le même jalon, déplacé"
    assert b["jalon"]["date_reelle"] == plus_tard
    poses = [j for m in planning["mois"] for j in m["jalons"] if j["categorie"] == "garde"]
    assert len(poses) == 1, "un seul rendez-vous au planning, pas deux"


@pytest.mark.asyncio
async def test_entretien_sans_date_refuse_avec_sa_raison(client, fiche):
    """Sans date, il n'y a rien à poser — et le dire vaut mieux que d'inventer un jour."""
    async with client as c:
        e = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/entretiens",
                          json={})).json()
        r = await c.post(f"/api/emploi-domicile/entretiens/{e['id']}/planning")
    assert r.status_code == 400
    assert "date" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retirer_du_planning_coupe_le_lien(client, fiche):
    """
    Effacer le jalon sans effacer `jalon_id` laisserait la fiche croire que le rendez-vous
    est toujours au calendrier.
    """
    jour = (date.today() + timedelta(days=5)).isoformat()
    async with client as c:
        e = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/entretiens",
                          json={"date_prevue": jour})).json()
        await c.post(f"/api/emploi-domicile/entretiens/{e['id']}/planning")
        r = (await c.delete(f"/api/emploi-domicile/entretiens/{e['id']}/planning")).json()
        planning = (await c.get("/api/dossiers/devenir-parent/planning")).json()

    assert r["entretien"]["jalon_id"] is None
    assert not [j for m in planning["mois"] for j in m["jalons"] if j["categorie"] == "garde"]


# ─── L'identité administrative ────────────────────────────────────────────────────────

SECU = "2 85 04 35 238 042 12"
IBAN = "FR76 3000 6000 0112 3456 7890 189"


@pytest.mark.asyncio
async def test_identite_n_est_jamais_rendue_en_clair(client, fiche):
    """
    La règle centrale. Un champ affiché par défaut finit recopié dans une capture d'écran,
    un partage de session ou une impression — sans que personne l'ait décidé.
    """
    async with client as c:
        r = (await c.put(f"/api/emploi-domicile/intervenants/{fiche}/identite",
                         json={"numero_secu": SECU, "iban": IBAN})).json()
    assert "285043523804212" not in str(r)
    assert "FR7630006000011234567890189" not in str(r)
    assert r["numero_secu"].startswith("••••")
    assert r["iban"].startswith("••••")


@pytest.mark.asyncio
async def test_l_apercu_permet_de_reconnaitre_la_bonne_valeur(client, fiche):
    """
    Rendre un simple `true`/`false` obligerait à ouvrir le clair pour vérifier qu'on n'a pas
    saisi deux fois la même chose au mauvais endroit — l'inverse du but recherché.
    """
    async with client as c:
        r = (await c.put(f"/api/emploi-domicile/intervenants/{fiche}/identite",
                         json={"iban": IBAN})).json()
    assert r["iban"] == "•••• 0189"


@pytest.mark.asyncio
async def test_la_donnee_est_chiffree_en_base(client, fiche, db_session):
    """Sans ça, tout le reste n'est qu'une politesse d'affichage."""
    import uuid as _uuid

    from models.emploi_domicile import Intervenant

    async with client as c:
        await c.put(f"/api/emploi-domicile/intervenants/{fiche}/identite",
                    json={"numero_secu": SECU})
    i = await db_session.get(Intervenant, _uuid.UUID(fiche))
    assert i.numero_secu_chiffre.startswith("enc::")
    assert "2850435" not in i.numero_secu_chiffre


@pytest.mark.asyncio
async def test_reveler_rend_le_clair_normalise(client, fiche):
    """Un IBAN se recopie avec ses espaces et se compare sans : on stocke la forme compacte."""
    async with client as c:
        await c.put(f"/api/emploi-domicile/intervenants/{fiche}/identite", json={"iban": IBAN})
        r = (await c.post(
            f"/api/emploi-domicile/intervenants/{fiche}/identite/reveler?champ=iban")).json()
    assert r["valeur"] == "FR7630006000011234567890189"


@pytest.mark.asyncio
async def test_enregistrer_un_champ_n_efface_pas_l_autre(client, fiche):
    """On saisit ces deux données à des moments différents, parfois à des semaines d'écart."""
    async with client as c:
        await c.put(f"/api/emploi-domicile/intervenants/{fiche}/identite",
                    json={"numero_secu": SECU})
        r = (await c.put(f"/api/emploi-domicile/intervenants/{fiche}/identite",
                         json={"iban": IBAN})).json()
    assert r["numero_secu"] is not None and r["iban"] is not None


@pytest.mark.asyncio
async def test_effacer_est_possible(client, fiche):
    """Pouvoir retirer une donnée personnelle compte autant que pouvoir la saisir."""
    async with client as c:
        await c.put(f"/api/emploi-domicile/intervenants/{fiche}/identite", json={"iban": IBAN})
        r = (await c.put(f"/api/emploi-domicile/intervenants/{fiche}/identite",
                         json={"iban": None})).json()
    assert r["iban"] is None


@pytest.mark.asyncio
async def test_reveler_un_champ_vide_dit_qu_il_est_vide(client, fiche):
    async with client as c:
        r = await c.post(
            f"/api/emploi-domicile/intervenants/{fiche}/identite/reveler?champ=iban")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_reveler_un_champ_inconnu_refuse(client, fiche):
    """La liste est fermée : on ne révèle pas une colonne arbitraire par son nom."""
    async with client as c:
        r = await c.post(
            f"/api/emploi-domicile/intervenants/{fiche}/identite/reveler?champ=note")
    assert r.status_code == 400
