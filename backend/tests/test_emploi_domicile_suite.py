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


# ─── Les annexes ──────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def contrat(client, fiche):
    """Un contrat généré, prêt à recevoir annexes et dépôt."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/contrats",
                           json={"champs": {"taux_horaire": "4,20", "heures_semaine": "40",
                                            "enfant_prenom": "Jules"}})).json()
        await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/generer", json={})
    return ct["id"]


@pytest.mark.asyncio
async def test_les_annexes_disent_a_quoi_elles_servent(client, contrat):
    """
    Une liste de titres administratifs ne se lit pas. C'est le « pourquoi » qui fait ouvrir
    l'annexe — et ces trois-là, personne ne les écrit avant d'en avoir eu besoin.
    """
    async with client as c:
        r = (await c.get(f"/api/emploi-domicile/contrats/{contrat}/annexes")).json()
    cles = [a["cle"] for a in r["annexes"]]
    assert cles == ["autorisations", "personnes-autorisees", "renseignements"]
    assert all(len(a["resume"]) > 30 for a in r["annexes"])


@pytest.mark.asyncio
async def test_l_annexe_reprend_ce_que_le_contrat_sait_deja(client, contrat):
    """Redemander le prénom de l'enfant, c'est se garantir deux orthographes différentes."""
    async with client as c:
        r = (await c.get(
            f"/api/emploi-domicile/contrats/{contrat}/annexes/autorisations")).json()
    assert "Jules" in r["texte"]
    assert "Claire Martin" in r["texte"]


@pytest.mark.asyncio
async def test_les_trous_sont_visibles(client, contrat):
    """Un trou visible se remplit ; un trou invisible se signe."""
    async with client as c:
        r = (await c.get(
            f"/api/emploi-domicile/contrats/{contrat}/annexes/renseignements")).json()
    assert "[À COMPLÉTER]" in r["texte"]


@pytest.mark.asyncio
async def test_l_appel_aux_secours_ne_depend_d_aucune_case(client, contrat):
    """
    La seule ligne de ces annexes qui ne doit surtout pas se lire comme une permission à
    cocher. Un doute là-dessus coûte des minutes au mauvais moment.
    """
    async with client as c:
        r = (await c.get(
            f"/api/emploi-domicile/contrats/{contrat}/annexes/autorisations")).json()
    assert "l'appel aux secours ne requiert aucune autorisation" in r["texte"].lower()


@pytest.mark.asyncio
async def test_annexe_inconnue_refusee(client, contrat):
    async with client as c:
        assert (await c.get(
            f"/api/emploi-domicile/contrats/{contrat}/annexes/inventee")).status_code == 404


# ─── Le dépôt en GED ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deposer_rend_le_contrat_trouvable(client, contrat):
    """Un contrat qui ne vit que dans son écran est introuvable le jour où on le cherche."""
    async with client as c:
        r = (await c.post(f"/api/emploi-domicile/contrats/{contrat}/deposer")).json()
        doc = (await c.get(f"/api/documents/{r['document_id']}")).json()
    assert "Claire Martin" in r["nom"]
    assert doc["extension"] == "md"
    assert r["octets"] > 0


@pytest.mark.asyncio
async def test_redeposer_met_a_jour_au_lieu_de_dupliquer(client, contrat):
    """Deux versions d'un contrat dans une GED, on ne sait plus laquelle fait foi."""
    async with client as c:
        a = (await c.post(f"/api/emploi-domicile/contrats/{contrat}/deposer")).json()
        await c.patch(f"/api/emploi-domicile/contrats/{contrat}",
                      json={"texte": "# Contrat corrigé à la main"})
        b = (await c.post(f"/api/emploi-domicile/contrats/{contrat}/deposer")).json()
        doc = (await c.get(f"/api/documents/{b['document_id']}/text")).json()

    assert a["document_id"] == b["document_id"]
    assert "corrigé à la main" in str(doc)


@pytest.mark.asyncio
async def test_c_est_le_texte_relu_qui_est_depose(client, contrat):
    """Déposer autre chose que ce qui a été signé serait pire que ne rien déposer."""
    async with client as c:
        await c.patch(f"/api/emploi-domicile/contrats/{contrat}",
                      json={"texte": "# Version amendée article 3"})
        r = (await c.post(f"/api/emploi-domicile/contrats/{contrat}/deposer")).json()
        doc = (await c.get(f"/api/documents/{r['document_id']}/text")).json()
    assert "amendée article 3" in str(doc)


@pytest.mark.asyncio
async def test_contrat_sans_texte_refuse_avec_sa_raison(client, fiche):
    async with client as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/contrats",
                           json={"champs": {}})).json()
        r = await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/deposer")
    assert r.status_code == 400
    assert "générez" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_retirer_coupe_le_lien(client, contrat):
    """« Déposé » affiché pour un document que la recherche ne trouve plus est un mensonge."""
    async with client as c:
        await c.post(f"/api/emploi-domicile/contrats/{contrat}/deposer")
        await c.delete(f"/api/emploi-domicile/contrats/{contrat}/deposer")
        detail = (await c.get(f"/api/emploi-domicile/contrats/{contrat}")).json()
    assert detail["document_id"] is None


# ─── Comparer deux candidates ─────────────────────────────────────────────────────────

async def _candidate(c, nom, *, tarif=None, places=None, reponses=None, impression=None):
    """Une fiche avec un entretien déjà rempli."""
    i = (await c.post("/api/emploi-domicile/devenir-parent/intervenants",
                      json={"nom": nom, "tarif_annonce": tarif, "places": places})).json()
    e = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/entretiens",
                      json={})).json()
    for cle, avis in (reponses or {}).items():
        await c.post(f"/api/emploi-domicile/entretiens/{e['id']}/reponse",
                     json={"cle": cle, "avis": avis})
    if impression:
        await c.patch(f"/api/emploi-domicile/entretiens/{e['id']}",
                      json={"impression": impression})
    return i["id"]


@pytest.mark.asyncio
async def test_les_divergences_passent_devant(client, fiche):
    """
    C'est le seul travail qu'une machine fait mieux qu'une relecture : repérer que sur douze
    questions, deux seulement ont reçu des réponses opposées. Ce sont ces deux-là qui décident.
    """
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a = await _candidate(c, "Durand", reponses={"tel_place": "ok", "agr_effectif": "ok"})
        b = await _candidate(c, "Leroy", reponses={"tel_place": "non", "agr_effectif": "reserve"})
        r = (await c.get(
            f"/api/emploi-domicile/devenir-parent/comparaison?ids={a},{b}")).json()

    natures = [e["nature"] for e in r["ecarts"]]
    assert natures[0] == "divergence", "la divergence passe devant la nuance"
    assert {e["cle"] for e in r["ecarts"] if e["nature"] == "divergence"} == {"tel_place"}
    assert {e["cle"] for e in r["ecarts"] if e["nature"] == "nuance"} == {"agr_effectif"}


@pytest.mark.asyncio
async def test_une_question_non_posee_n_est_pas_un_desaccord(client, fiche):
    """
    La raison d'être du module. Traiter une case vide comme un « non » ferait écarter
    quelqu'un à qui on a simplement oublié de poser la question.
    """
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a = await _candidate(c, "Durand", reponses={"tel_place": "ok"})
        b = await _candidate(c, "Leroy", reponses={})
        r = (await c.get(
            f"/api/emploi-domicile/devenir-parent/comparaison?ids={a},{b}")).json()

    ecart = next(e for e in r["ecarts"] if e["cle"] == "tel_place")
    assert ecart["nature"] == "lacune"
    assert ecart["avis"] == ["ok", None]
    assert any("trou dans l'entretien" in m for m in r["remarques"])


@pytest.mark.asyncio
async def test_aucun_classement_n_est_rendu(client, fiche):
    """
    Un ordre produit par l'application serait suivi précisément parce qu'il a l'air objectif —
    alors que ce qui décide n'entre dans aucune grille.
    """
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a = await _candidate(c, "Durand", reponses={"tel_place": "ok"}, impression=5)
        b = await _candidate(c, "Leroy", reponses={"tel_place": "non"}, impression=2)
        r = (await c.get(
            f"/api/emploi-domicile/devenir-parent/comparaison?ids={a},{b}")).json()

    assert "score" not in str(r).lower()
    assert [p["nom"] for p in r["personnes"]] == ["Durand", "Leroy"], "l'ordre demandé, pas un rang"
    assert any("ne classe pas" in m for m in r["remarques"])


@pytest.mark.asyncio
async def test_le_tarif_est_mis_en_regard_avec_sa_reserve(client, fiche):
    """Le tarif seul ne dit pas le coût : les indemnités s'y ajoutent et varient."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a = await _candidate(c, "Durand", tarif="4,20 € net/h", places=3)
        b = await _candidate(c, "Leroy", tarif="3,90 € net/h + 4 € d'entretien", places=2)
        r = (await c.get(
            f"/api/emploi-domicile/devenir-parent/comparaison?ids={a},{b}")).json()

    tarif = next(x for x in r["reperes"] if x["cle"] == "tarif")
    assert tarif["valeurs"] == ["4,20 € net/h", "3,90 € net/h + 4 € d'entretien"]
    assert "ne dit pas le coût" in tarif["note"]


@pytest.mark.asyncio
async def test_checklist_vierge_le_dit_au_lieu_de_conclure(client, fiche):
    """Sans réponses, la comparaison ne peut rien dire — et doit le reconnaître."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a = await _candidate(c, "Durand")
        b = await _candidate(c, "Leroy")
        r = (await c.get(
            f"/api/emploi-domicile/devenir-parent/comparaison?ids={a},{b}")).json()

    assert r["ecarts"] == []
    assert any("ne peut rien dire" in m for m in r["remarques"])


@pytest.mark.asyncio
async def test_la_reponse_la_plus_recente_l_emporte(client, fiche):
    """Une seconde visite sert justement à corriger ce qu'on avait mal compris la première."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        a = await _candidate(c, "Durand", reponses={"tel_place": "non"})
        # Second entretien : la place s'est libérée.
        e2 = (await c.post(f"/api/emploi-domicile/intervenants/{a}/entretiens",
                           json={})).json()
        await c.post(f"/api/emploi-domicile/entretiens/{e2['id']}/reponse",
                     json={"cle": "tel_place", "avis": "ok"})
        b = await _candidate(c, "Leroy", reponses={"tel_place": "ok"})
        r = (await c.get(
            f"/api/emploi-domicile/devenir-parent/comparaison?ids={a},{b}")).json()

    assert not [e for e in r["ecarts"] if e["cle"] == "tel_place"], \
        "les deux répondent « ok » une fois la mise à jour prise en compte"


@pytest.mark.asyncio
async def test_une_seule_personne_est_refusee(client, fiche):
    async with client as c:
        r = await c.get(f"/api/emploi-domicile/devenir-parent/comparaison?ids={fiche}")
    assert r.status_code == 400


# ─── Reste à charge ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_poste_non_saisi_n_est_pas_zero(client, fiche):
    """
    La même règle que le journal. Compter un champ vide comme zéro annoncerait un reste à
    charge flatteur à quelqu'un qui n'a simplement pas encore saisi ses cotisations.
    """
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/contrats",
                           json={"champs": {"taux_horaire": "4,20", "heures_semaine": "40"}})).json()
        r = (await c.get(f"/api/emploi-domicile/contrats/{ct['id']}/cout")).json()

    assert r["complet"] is False
    cmg = next(p for p in r["postes"] if p["cle"] == "cmg")
    assert cmg["saisi"] is False and cmg["montant"] is None


@pytest.mark.asyncio
async def test_le_sens_de_l_erreur_est_dit(client, fiche):
    """
    Un manquant en « entrée » gonfle le reste à charge, un manquant en « sortie » le minore.
    Sans le dire, l'utilisateur ne sait pas dans quel sens il se trompe.
    """
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/contrats",
                           json={"champs": {"taux_horaire": "4,20", "heures_semaine": "40"}})).json()
        r = (await c.get(f"/api/emploi-domicile/contrats/{ct['id']}/cout")).json()

    remarque = " ".join(r["remarques"])
    assert "plus élevé" in remarque and "plus bas" in remarque


@pytest.mark.asyncio
async def test_le_total_soustrait_les_aides(client, fiche):
    """728 € de salaire − 200 € de CMG − 50 € d'avance = 478 € qui sortent vraiment."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/contrats",
                           json={"champs": {"taux_horaire": "4,20", "heures_semaine": "40",
                                            "cmg_mensuel": "200", "avance_immediate": "50",
                                            "cotisations_mensuelles": "0"}})).json()
        r = (await c.get(f"/api/emploi-domicile/contrats/{ct['id']}/cout")).json()

    assert r["entrees"] == "250.00"
    assert r["complet"] is True
    assert r["total"] == "478.00"


@pytest.mark.asyncio
async def test_aucune_cotisation_n_est_calculee(client, fiche):
    """
    Le refus structurant du module : les taux changent chaque année et dépendent de la
    situation. Un simulateur faux produit un chiffre qu'on croit, et sur lequel on engage un
    budget.
    """
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/contrats",
                           json={"champs": {"taux_horaire": "4,20", "heures_semaine": "40"}})).json()
        r = (await c.get(f"/api/emploi-domicile/contrats/{ct['id']}/cout")).json()

    assert any("ne calcule aucune cotisation" in m for m in r["remarques"])
    cotis = next(p for p in r["postes"] if p["cle"] == "cotisations")
    assert "bulletin" in cotis["origine"]


@pytest.mark.asyncio
async def test_chaque_poste_dit_d_ou_vient_son_chiffre(client, fiche):
    """Un montant qu'on ne peut pas rattacher à un document ne se vérifie pas."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/contrats",
                           json={"champs": {"taux_horaire": "4,20", "heures_semaine": "40"}})).json()
        r = (await c.get(f"/api/emploi-domicile/contrats/{ct['id']}/cout")).json()
    assert all(len(p["origine"]) > 20 for p in r["postes"])


# ─── Les rappels au planning ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_les_rappels_couvrent_le_mensuel_et_l_annuel(client, fiche):
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/contrats",
                           json={"champs": {"taux_horaire": "4,20", "heures_semaine": "40"}})).json()
        r = (await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/rappels")).json()

    titres = " | ".join(p["titre"] for p in r["poses"])
    assert "Pajemploi" in titres, "le guichet vient du profil"
    assert "Régularisation annuelle" in titres
    assert len(r["poses"]) == 4, "trois déclarations mensuelles + la régularisation"


@pytest.mark.asyncio
async def test_reposer_les_rappels_ne_duplique_pas(client, fiche):
    """Un planning qui accumule les mêmes rappels cesse d'être lu."""
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{fiche}/contrats",
                           json={"champs": {"taux_horaire": "4,20"}})).json()
        await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/rappels")
        r = (await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/rappels")).json()

    assert r["poses"] == []
    assert r["deja_presents"] == 4


@pytest.mark.asyncio
async def test_l_agrement_qui_expire_donne_un_rappel_anticipe(client):
    """Un renouvellement ne se fait pas la veille : on prévient deux mois avant."""
    from main import app

    echeance = date.today() + timedelta(days=120)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/dossiers", json={"titre": "Devenir parent"})
        i = (await c.post("/api/emploi-domicile/devenir-parent/intervenants",
                          json={"nom": "Martin",
                                "agrement_echeance": echeance.isoformat()})).json()
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{i['id']}/contrats",
                           json={"champs": {}})).json()
        r = (await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/rappels")).json()

    rappel = next(p for p in r["poses"] if "agrément" in p["titre"].lower())
    assert rappel["date"] == (echeance - timedelta(days=60)).isoformat()
