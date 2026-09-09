"""
Tests — calculs et génération du contrat
========================================
C'est ici que les tests comptent le plus du module : une erreur de mensualisation se répète
**tous les mois pendant deux ans**, et personne ne la voit passer — le montant a l'air
plausible.

Ce qui est vérifié :

- **les deux régimes** donnent bien deux résultats différents pour les mêmes entrées : c'est
  la première source d'erreur des contrats d'assistante maternelle ;
- **les heures majorées entrent dans le lissé**, sinon le salaire est sous-évalué toute
  l'année sans que rien ne le signale ;
- **le barème absent ne se lit pas « tout va bien »** : l'absence de contrôle est elle-même
  une alerte ;
- **régénérer n'écrase pas un texte corrigé** — le moment où l'on régénère sans y penser est
  précisément celui qui suit un ajustement de chiffre ;
- **un champ manquant n'apparaît jamais comme une valeur** : `[À COMPLÉTER]` se remplit, un
  trou invisible se signe.
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.emploi_domicile import calcul


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
async def intervenant(client):
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/dossiers", json={"titre": "Devenir parent"})
        i = (await c.post("/api/emploi-domicile/devenir-parent/intervenants",
                          json={"nom": "Martin", "prenom": "Claire",
                                "agrement_numero": "35-2024-118"})).json()
    return i["id"]


# ─── Mensualisation : le cœur ─────────────────────────────────────────────────────────

def test_annee_complete_lisse_sur_52_semaines():
    m = calcul.mensualiser(taux_horaire=Decimal("4.20"), heures_semaine=Decimal("40"),
                           annee_complete=True)
    # 4,20 × 40 × 52 ÷ 12 = 728,00
    assert m.salaire_mensuel == Decimal("728.00")
    assert m.semaines == 52
    assert m.heures_mensualisees == Decimal("173.33")
    assert "52 semaines" in m.formule


def test_annee_incomplete_utilise_les_semaines_reelles():
    m = calcul.mensualiser(taux_horaire=Decimal("4.20"), heures_semaine=Decimal("40"),
                           annee_complete=False, semaines=42)
    # 4,20 × 40 × 42 ÷ 12 = 588,00
    assert m.salaire_mensuel == Decimal("588.00")
    assert m.regime == "incomplete"


def test_les_deux_regimes_ne_donnent_pas_le_meme_salaire():
    """
    La raison pour laquelle on ne peut pas choisir le régime à la place de l'utilisateur :
    mêmes entrées, 140 € d'écart par mois, tous les mois.
    """
    args = dict(taux_horaire=Decimal("4.20"), heures_semaine=Decimal("40"))
    complete = calcul.mensualiser(**args, annee_complete=True)
    incomplete = calcul.mensualiser(**args, annee_complete=False, semaines=42)
    assert complete.salaire_mensuel - incomplete.salaire_mensuel == Decimal("140.00")


def test_annee_incomplete_previent_pour_les_conges():
    """En année incomplète, les congés se paient EN PLUS — l'oublier fausse le budget."""
    m = calcul.mensualiser(taux_horaire=Decimal("4"), heures_semaine=Decimal("30"),
                           annee_complete=False, semaines=40)
    assert any("congés payés se règlent EN PLUS" in d for d in m.detail)


def test_heures_majorees_entrent_dans_le_lisse():
    """Sans elles, le salaire mensuel est sous-évalué toute l'année, en silence."""
    sans = calcul.mensualiser(taux_horaire=Decimal("5"), heures_semaine=Decimal("45"),
                              annee_complete=True)
    avec = calcul.mensualiser(taux_horaire=Decimal("5"), heures_semaine=Decimal("50"),
                              annee_complete=True, majoration=Decimal("0.10"))
    assert avec.heures_majorees_semaine == Decimal("5")
    # 5 h × 5 € × 1,10 × 52 ÷ 12 = 119,17 de plus que les 5 h au taux normal
    assert avec.salaire_mensuel > sans.salaire_mensuel + Decimal("100")
    assert any("majorées" in d for d in avec.detail)


@pytest.mark.parametrize("args", [
    dict(taux_horaire=Decimal("0"), heures_semaine=Decimal("40"), annee_complete=True),
    dict(taux_horaire=Decimal("4"), heures_semaine=Decimal("0"), annee_complete=True),
    dict(taux_horaire=Decimal("4"), heures_semaine=Decimal("40"), annee_complete=False, semaines=0),
    dict(taux_horaire=Decimal("4"), heures_semaine=Decimal("40"), annee_complete=False, semaines=60),
])
def test_entrees_absurdes_refusees(args):
    with pytest.raises(ValueError):
        calcul.mensualiser(**args)


# ─── Les frais ne sont PAS mensualisés ────────────────────────────────────────────────

def test_frais_sont_une_estimation_et_le_disent():
    f = calcul.estimer_frais(jours_semaine=4, semaines=52, entretien_jour=Decimal("3.50"),
                             repas_jour=Decimal("4"))
    # 4 jours × 52 ÷ 12 = 17,33 jours/mois → 3,50 × 17,33 = 60,67
    assert f.entretien_mensuel == Decimal("60.67")
    assert any("jour d'accueil RÉEL" in d for d in f.detail)
    assert any("ne se cotisent pas" in d for d in f.detail)


# ─── Les contrôles ────────────────────────────────────────────────────────────────────

def test_bareme_absent_est_une_alerte_pas_un_silence():
    """Un écran muet se lirait « tout va bien » — c'est l'erreur qu'on veut éviter."""
    alertes = calcul.controler(taux_horaire=Decimal("1"), heures_jour=None,
                               entretien_jour=None, smic_horaire=None, minimum_garanti=None)
    assert [a.cle for a in alertes] == ["bareme_absent"]
    assert "n'a PAS été comparé" in alertes[0].message


def test_salaire_sous_le_plancher_est_bloquant():
    # Plancher = SMIC × 0,281. Avec un SMIC de 12 €, il vaut 3,37 €.
    alertes = calcul.controler(taux_horaire=Decimal("3.00"), heures_jour=Decimal("9"),
                               entretien_jour=None, smic_horaire=Decimal("12"),
                               minimum_garanti=None)
    sous = next(a for a in alertes if a.cle == "sous_plancher")
    assert sous.bloquant is True and "3,37" in sous.message


def test_contrat_conforme_ne_declenche_rien():
    """
    Valeurs toutes au-dessus des planchers : 4,20 € > 3,37 € (SMIC × 0,281), et 3,60 €
    d'entretien > 3,57 € (85 % du minimum garanti pour 9 h).

    *Premier jet de ce test : 3,50 € d'entretien — que le contrôle a refusé, à raison. Le
    piège est instructif, puisque 3,50 est justement le montant qu'on écrit « au jugé ».*
    """
    assert calcul.controler(taux_horaire=Decimal("4.20"), heures_jour=Decimal("9"),
                            entretien_jour=Decimal("3.60"), smic_horaire=Decimal("12"),
                            minimum_garanti=Decimal("4.20")) == []


def test_entretien_insuffisant_est_bloquant():
    """85 % du minimum garanti pour 9 h : avec un MG de 4,20 €, le minimum est 3,57 €."""
    alertes = calcul.controler(taux_horaire=Decimal("4.20"), heures_jour=Decimal("9"),
                               entretien_jour=Decimal("2.00"), smic_horaire=Decimal("12"),
                               minimum_garanti=Decimal("4.20"))
    manque = next(a for a in alertes if a.cle == "entretien_insuffisant")
    assert manque.bloquant is True and "3,57" in manque.message


# ─── Le contrat, de bout en bout ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_contrat_prerempli_depuis_la_fiche(client, intervenant):
    """Retaper ce que l'application connaît déjà est le meilleur moyen d'y glisser une coquille."""
    async with client as c:
        contrat = (await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/contrats",
                                json={"champs": {}})).json()
    assert contrat["champs"]["agrement_numero"] == "35-2024-118"
    assert contrat["champs"]["annee_complete"] is True
    assert contrat["statut"] == "brouillon"
    assert "Claire Martin" in contrat["titre"]


@pytest.mark.asyncio
async def test_calcul_rendu_avec_sa_formule(client, intervenant):
    async with client as c:
        contrat = (await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/contrats",
                                json={"champs": {"taux_horaire": "4,20",
                                                 "heures_semaine": "40"}})).json()
    assert contrat["calcul"]["salaire_mensuel"] == "728.00"
    assert "÷ 12" in contrat["calcul"]["formule"], "la formule doit être lisible, pas juste juste"


@pytest.mark.asyncio
async def test_champs_incomplets_n_empechent_pas_l_ecran(client, intervenant):
    """Un formulaire qui refuse de s'afficher tant qu'il n'est pas complet ne se remplit jamais."""
    async with client as c:
        contrat = (await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/contrats",
                                json={"champs": {}})).json()
    assert contrat["calcul"] is None
    assert any(a["cle"] == "incomplet" for a in contrat["alertes"])


@pytest.mark.asyncio
async def test_patch_fusionne_les_champs(client, intervenant):
    """L'écran envoie le champ modifié : un remplacement effacerait tout le reste."""
    async with client as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/contrats",
                           json={"champs": {"taux_horaire": "4.20"}})).json()
        maj = (await c.patch(f"/api/emploi-domicile/contrats/{ct['id']}",
                             json={"champs": {"heures_semaine": "40"}})).json()
    assert maj["champs"]["taux_horaire"] == "4.20"
    assert maj["champs"]["heures_semaine"] == "40"


@pytest.mark.asyncio
async def test_generation_et_marqueurs_de_champs_manquants(client, intervenant):
    async with client as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/contrats",
                           json={"champs": {"taux_horaire": "4.20", "heures_semaine": "40",
                                            "jours_semaine": "4"}})).json()
        gen = (await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/generer", json={})).json()

    texte = gen["texte"]
    assert texte.startswith("# Contrat de travail — assistant")
    assert "728,00 €" in texte, "le salaire calculé doit figurer au contrat"
    assert "35-2024-118" in texte, "l'agrément pré-rempli doit y figurer"
    assert "[À COMPLÉTER]" in texte, "un champ vide se signale, il ne s'omet pas"
    assert "Pajemploi" in texte, "le guichet vient du profil"
    assert gen["genere_le"] is not None


@pytest.mark.asyncio
async def test_regenerer_n_ecrase_pas_un_texte_corrige(client, intervenant):
    """
    Le moment où l'on régénère sans y penser est celui qui suit un ajustement de chiffre :
    c'est exactement là qu'on perdrait les corrections relues.
    """
    async with client as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/contrats",
                           json={"champs": {"taux_horaire": "4.20", "heures_semaine": "40"}})).json()
        await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/generer", json={})
        await c.patch(f"/api/emploi-domicile/contrats/{ct['id']}",
                      json={"texte": "# Ma version relue et amendée"})

        refus = await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/generer", json={})
        assert refus.status_code == 409

        force = (await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/generer",
                              json={"ecraser": True})).json()
    assert force["texte"].startswith("# Contrat de travail")


@pytest.mark.asyncio
async def test_contrat_signe_protege_de_la_regeneration(client, intervenant):
    async with client as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/contrats",
                           json={"champs": {"taux_horaire": "4.20", "heures_semaine": "40"}})).json()
        await c.patch(f"/api/emploi-domicile/contrats/{ct['id']}", json={"statut": "signe"})
        r = await c.post(f"/api/emploi-domicile/contrats/{ct['id']}/generer", json={})
    assert r.status_code == 409 and "signé" in r.json()["detail"]


@pytest.mark.asyncio
async def test_bareme_saisi_active_les_controles(client, intervenant, db_session):
    from models.config import Config

    db_session.add(Config(cle="bareme_smic_horaire", valeur="12.00"))
    db_session.add(Config(cle="bareme_verifie_le", valeur="2026-09-09"))
    await db_session.commit()

    async with client as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/contrats",
                           json={"champs": {"taux_horaire": "3.00", "heures_semaine": "40"}})).json()

    cles = {a["cle"] for a in ct["alertes"]}
    assert "bareme_absent" not in cles
    assert "sous_plancher" in cles


@pytest.mark.asyncio
async def test_statut_invalide_refuse(client, intervenant):
    async with client as c:
        ct = (await c.post(f"/api/emploi-domicile/intervenants/{intervenant}/contrats",
                           json={"champs": {}})).json()
        r = await c.patch(f"/api/emploi-domicile/contrats/{ct['id']}", json={"statut": "peut-etre"})
    assert r.status_code == 400
