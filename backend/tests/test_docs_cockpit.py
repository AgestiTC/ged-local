"""
Docs du cockpit → BookStack (16/11/2026) : relevé de `[GED]/Docs-applications/<projet>/manifeste.json`.

Faux NAS en mémoire, faux BookStack ; la VRAIE publication (`publier_manifeste`) et la vraie base de test.
"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from models.publication import Publication
from models.publieur import ProjetPublieur
from services import docs_cockpit as dc
from services import publication_service


# --------------------------------------------------------------------------- #
# Faux                                                                         #
# --------------------------------------------------------------------------- #
class FauxNas:
    """Le dossier de dépôt en mémoire : chemin relatif (`projet/fichier`) → octets."""

    def __init__(self) -> None:
        self.fichiers: dict[str, bytes] = {}
        self.supprimes: list[str] = []
        self.apres_lecture = None   # crochet : simuler un nouveau dépôt pendant le traitement

    def deposer(self, projet: str, donnees, nom: str = dc.MANIFESTE) -> None:
        brut = donnees if isinstance(donnees, bytes) else json.dumps(donnees).encode("utf-8")
        self.fichiers[f"{projet}/{nom}"] = brut

    async def lister(self, relatif: str = "") -> list[dict]:
        """Les enfants DIRECTS de `relatif` (fichiers, et dossiers déduits des chemins plus longs)."""
        prefixe = f"{relatif}/" if relatif else ""
        vus: dict[str, dict] = {}
        for c, v in self.fichiers.items():
            if not c.startswith(prefixe):
                continue
            nom, _, reste = c[len(prefixe):].partition("/")
            vus.setdefault(nom, {"nom": nom, "dossier": bool(reste), "taille": 0 if reste else len(v)})
        return sorted(vus.values(), key=lambda e: e["nom"])

    async def lire(self, relatif: str) -> bytes:
        brut = self.fichiers[relatif]
        if self.apres_lecture:
            crochet, self.apres_lecture = self.apres_lecture, None
            crochet()
        return brut

    async def ecrire(self, relatif: str, contenu: str) -> None:
        self.fichiers[relatif] = contenu.encode("utf-8")

    async def supprimer(self, relatif: str) -> None:
        self.supprimes.append(relatif)
        del self.fichiers[relatif]

    def json(self, relatif: str) -> dict:
        return json.loads(self.fichiers[relatif].decode("utf-8"))


class FauxBookStack:
    configured = True
    base_url = "http://wiki.local"

    def __init__(self) -> None:
        self.livres: dict[str, dict] = {}
        self.pages: dict[int, dict] = {}
        self.etageres: dict[str, set] = {}

    async def ensure_book(self, nom: str) -> dict:
        return self.livres.setdefault(nom, {"id": len(self.livres) + 1, "slug": nom.lower().replace(" ", "-")})

    async def ensure_chapter(self, book_id: int, nom: str) -> dict:
        return {"id": 1000 + book_id}

    async def create_page(self, titre: str, markdown: str, **cible) -> dict:
        pid = len(self.pages) + 1
        self.pages[pid] = {"id": pid, "titre": titre, "markdown": markdown, **cible}
        return {"id": pid, "slug": f"p{pid}", "book_slug": "b"}

    async def update_page(self, page_id: int, markdown: str, name: str) -> dict:
        self.pages[page_id].update(markdown=markdown, titre=name)
        return {"id": page_id, "slug": f"p{page_id}", "book_slug": "b"}

    async def ensure_shelf(self, nom: str) -> dict:
        self.etageres.setdefault(nom, set())
        return {"id": nom}

    async def ensure_book_in_shelf(self, shelf_id, book_id) -> None:
        self.etageres[shelf_id].add(book_id)

    def page_url(self, page: dict) -> str:
        return f"{self.base_url}/books/{page['book_slug']}/page/{page['slug']}"

    def book_url(self, book: dict) -> str:
        return f"{self.base_url}/books/{book['slug']}"


def manifeste(projet: str = "gestion-projet-appli", **extra) -> dict:
    m = {
        "format": "cockpit-docs/1", "projet": projet, "nom": "Cockpit Projets", "version": "0.8.35",
        "source": "C:/x", "depose_le": "2026-11-16T13:05:00+00:00", "depose_par": "cockpit 0.8.35",
        "etagere": "Applications",
        "pages": [
            {"cle": "README", "livre": "Cockpit Projets", "chapitre": None, "titre": "Cockpit Projets",
             "markdown": "# Cockpit\nBonjour", "genere_le": "2026-11-16T13:05:00+00:00"},
            {"cle": "docs/guide/usage", "livre": "Cockpit Projets", "chapitre": "guide", "titre": "Utilisation",
             "markdown": "# Utilisation", "genere_le": "2026-11-16T13:05:00+00:00"},
        ],
    }
    m.update(extra)
    return m


@pytest.fixture
def wiki() -> FauxBookStack:
    return FauxBookStack()


@pytest.fixture
def publier(wiki):
    async def _publier(db, projet, pages, etagere):
        return await publication_service.publier_manifeste(db, projet, pages, etagere, service=wiki)
    return _publier


async def declarer(db, nom="gestion-projet-appli", livres=("Cockpit Projets",), actif=True) -> None:
    db.add(ProjetPublieur(nom=nom, token_hash=f"h-{nom}", livres_autorises=list(livres), actif=actif))
    await db.commit()


# --------------------------------------------------------------------------- #
# Validation (pure)                                                            #
# --------------------------------------------------------------------------- #
def test_un_manifeste_conforme_est_normalise():
    m = dc.valider(manifeste(), "gestion-projet-appli")
    assert m["projet"] == "gestion-projet-appli" and m["etagere"] == "Applications" and m["version"] == "0.8.35"
    assert [p["cle"] for p in m["pages"]] == ["README", "docs/guide/usage"]
    assert m["pages"][0]["chapitre"] is None and m["pages"][1]["chapitre"] == "guide"
    assert m["pages"][0]["genere_le"] == datetime(2026, 11, 16, 13, 5, tzinfo=timezone.utc)


@pytest.mark.parametrize(("modif", "code"), [
    ({"format": "cockpit-docs/2"}, "format_inconnu"),
    ({"projet": "autre"}, "projet_incoherent"),
    ({"pages": []}, "manifeste_invalide"),
    ({"pages": [{"cle": "a", "livre": "L", "titre": "T", "markdown": "x"}] * 301}, "trop_de_pages"),
    ({"pages": [{"cle": "a", "livre": "L", "titre": "", "markdown": "x"}]}, "page_invalide"),
    ({"pages": [{"cle": "a", "livre": "L", "titre": "T", "markdown": "é" * 600_000}]}, "page_trop_grande"),
    ({"pages": [{"cle": "a", "livre": "L", "titre": "T", "markdown": "x"}] * 2}, "cle_en_double"),
])
def test_un_manifeste_fautif_est_refuse(modif, code):
    with pytest.raises(dc.Refus) as e:
        dc.valider(manifeste(**modif), "gestion-projet-appli")
    assert e.value.code == code


# --------------------------------------------------------------------------- #
# Relevé                                                                       #
# --------------------------------------------------------------------------- #
async def test_depot_publie_puis_retire_avec_resultat(db_session, wiki, publier, tmp_path):
    await declarer(db_session)
    nas = FauxNas()
    nas.deposer("gestion-projet-appli", manifeste())
    nas.deposer("gestion-projet-appli", b"{en cours", nom="manifeste.json.part")   # écriture en cours : ignorée
    nas.deposer("sans-depot", b"x", nom="guide.md")                               # doc GED : pas un dépôt

    r = await dc.relever(db_session, nas=nas, publier=publier, archives=tmp_path)

    assert r["depots"] == [{"projet": "gestion-projet-appli", "statut": "publie", "creees": 2, "mises_a_jour": 0,
                            "inchangees": 0, "erreurs": 0}]
    assert "gestion-projet-appli/manifeste.json" not in nas.fichiers          # retiré : « pris en charge »
    assert "gestion-projet-appli/manifeste.json.part" in nas.fichiers         # jamais touché
    assert "sans-depot/guide.md" in nas.fichiers
    res = nas.json("gestion-projet-appli/resultat.json")
    assert res["statut"] == "publie" and res["pages"] == {"creees": 2, "mises_a_jour": 0, "inchangees": 0, "total": 2}
    assert res["livres"] == [{"livre": "Cockpit Projets", "url": "http://wiki.local/books/cockpit-projets"}]
    assert res["etagere"] == "Applications"
    # BookStack : 2 pages avec le bandeau, le livre dans l'étagère ; une archive côté Matothèque.
    assert len(wiki.pages) == 2 and all("générée automatiquement" in p["markdown"] for p in wiki.pages.values())
    assert wiki.etageres["Applications"] == {1}
    assert len(list((tmp_path / "gestion-projet-appli").iterdir())) == 1
    pubs = (await db_session.execute(select(Publication))).scalars().all()
    assert {p.cle for p in pubs} == {"README", "docs/guide/usage"}
    assert await dc.depose_par_cockpit(db_session, "gestion-projet-appli") is True   # en base, pas sur disque

    # Nouveau dépôt, une page changée : mise à jour de la MÊME page, l'autre inchangée.
    m2 = manifeste()
    m2["pages"][1]["markdown"] = "# Utilisation v2"
    nas.deposer("gestion-projet-appli", m2)
    r = await dc.relever(db_session, nas=nas, publier=publier, archives=tmp_path)
    assert r["depots"][0].get("mises_a_jour") == 1, r
    assert r["depots"][0]["inchangees"] == 1
    assert len(wiki.pages) == 2 and wiki.pages[2]["markdown"].endswith("# Utilisation v2")


async def test_projet_inconnu_refuse_avec_erreur_json(db_session, publier, tmp_path):
    nas = FauxNas()
    nas.deposer("gestion-projet-appli", manifeste())
    nas.deposer("gestion-projet-appli", b"{}", nom="resultat.json")   # compte rendu d'un dépôt précédent

    r = await dc.relever(db_session, nas=nas, publier=publier, archives=tmp_path)

    assert r["depots"][0]["statut"] == "refuse" and r["depots"][0]["code"] == "projet_inconnu"
    err = nas.json("gestion-projet-appli/erreur.json")
    assert err["statut"] == "refuse" and err["code"] == "projet_inconnu" and err["manifeste_retire"] is True
    assert "gestion-projet-appli/manifeste.json" not in nas.fichiers   # traité : retiré
    assert "gestion-projet-appli/resultat.json" not in nas.fichiers    # l'ancien compte rendu ne trompe plus


async def test_livre_non_autorise_et_projet_mis_refuses(db_session, wiki, publier, tmp_path):
    await declarer(db_session, livres=("Autre livre",))
    await declarer(db_session, nom="mis-facturation", livres=("Cockpit Projets",))
    nas = FauxNas()
    nas.deposer("gestion-projet-appli", manifeste())
    nas.deposer("mis-facturation", manifeste(projet="mis-facturation"))

    r = await dc.relever(db_session, nas=nas, publier=publier, archives=tmp_path)

    codes = {b["projet"]: b["code"] for b in r["depots"]}
    assert codes == {"gestion-projet-appli": "livre_non_autorise", "mis-facturation": "projet_exclu"}
    assert wiki.pages == {}                                             # rien publié, aucun livre fantôme


async def test_bookstack_indisponible_laisse_le_depot(db_session, wiki, publier, tmp_path):
    await declarer(db_session)
    wiki.configured = False
    nas = FauxNas()
    nas.deposer("gestion-projet-appli", manifeste())

    r = await dc.relever(db_session, nas=nas, publier=publier, archives=tmp_path)

    assert r["depots"][0]["statut"] == "en_attente"
    assert "gestion-projet-appli/manifeste.json" in nas.fichiers      # repris au relevé suivant
    assert nas.json("gestion-projet-appli/erreur.json")["manifeste_retire"] is False


async def test_nouveau_depot_pendant_le_traitement_n_est_pas_efface(db_session, publier, tmp_path):
    await declarer(db_session)
    nas = FauxNas()
    nas.deposer("gestion-projet-appli", manifeste())
    nas.apres_lecture = lambda: nas.deposer("gestion-projet-appli", manifeste(version="0.8.36"))

    await dc.relever(db_session, nas=nas, publier=publier, archives=tmp_path)

    assert nas.json("gestion-projet-appli/manifeste.json")["version"] == "0.8.36"   # gardé pour le suivant


async def test_manifeste_illisible(db_session, publier, tmp_path):
    nas = FauxNas()
    nas.deposer("gestion-projet-appli", b"\xff\xfe pas du json")
    r = await dc.relever(db_session, nas=nas, publier=publier, archives=tmp_path)
    assert r["depots"][0]["code"] == "manifeste_illisible"
    assert "gestion-projet-appli/manifeste.json" not in nas.fichiers


async def test_sans_source_le_releve_dit_quoi_faire(db_session):
    r = await dc.relever(db_session)
    assert r["statut"] == "ignore" and "svc-ged" in r["message"]


def test_le_job_est_io():
    from services import job_worker
    assert dc.JOB in job_worker._HANDLERS and job_worker.classe_tache(dc.JOB) == "io"


async def test_la_source_svc_ged_qui_couvre_tout_le_serveur_est_trouvee(db_session):
    """Une Source créée par l'écran n'a pas de dossier de base (16/11/2026) : celle de svc-ged sert."""
    from models.source import Source
    db_session.add_all([
        Source(libelle="NAS-MATO", type="smb", hote="192.168.42.200", identifiant="Tom", chemin_base=None, actif=True),
        Source(libelle="Docs-application", type="smb", hote="192.168.42.200", identifiant="SVC-GED", chemin_base="",
               actif=True),
    ])
    await db_session.commit()
    src = await dc.trouver_source(db_session)
    assert src is not None and src.libelle == "Docs-application"


# --------------------------------------------------------------------------- #
# Proposer une modification (16/11/2026)                                       #
# --------------------------------------------------------------------------- #
def test_le_bandeau_est_retire_du_markdown():
    md = publication_service.bandeau("gestion-projet-appli", "# Titre\nTexte")
    assert publication_service.retirer_bandeau(md) == "# Titre\nTexte"
    assert publication_service.retirer_bandeau("# Écrit à la main") == "# Écrit à la main"


async def test_une_proposition_est_deposee_avec_son_auteur(db_session, wiki, publier, tmp_path):
    await declarer(db_session)
    nas = FauxNas()
    nas.deposer("gestion-projet-appli", manifeste())
    await dc.relever(db_session, nas=nas, publier=publier, archives=tmp_path)
    pub = (await db_session.execute(select(Publication).where(Publication.cle == "docs/guide/usage"))).scalar_one()
    nas.creer_dossier = lambda rel: _async_rien()

    auteur = {"identifiant": "tclement", "nom": "Thomas C.", "email": None}
    chemin = await dc.deposer_proposition(db_session, pub, titre="Utilisation", page_url="http://wiki/p",
                                          avant="# Utilisation", propose="# Utilisation\r\nCorrigé",
                                          commentaire="  coquille  ", auteur=auteur, nas=nas)

    assert chemin.startswith("gestion-projet-appli/propositions/docs-guide-usage-") and chemin.endswith("Z.json")
    p = nas.json(chemin)
    assert p["format"] == "cockpit-docs-proposition/1" and p["cle"] == "docs/guide/usage"
    assert p["auteur"] == auteur and p["commentaire"] == "coquille"
    assert p["markdown_avant"] == "# Utilisation" and p["markdown_propose"] == "# Utilisation\nCorrigé"
    assert p["hash_publie"] == pub.contenu_hash and p["page_id"] == pub.page_id


async def test_une_proposition_sans_changement_est_refusee(db_session):
    class Pub:
        projet, cle, livre, chapitre, page_id, contenu_hash = "p", "README", "L", None, 1, "h"
    with pytest.raises(ValueError, match="Aucune modification"):
        await dc.deposer_proposition(db_session, Pub(), titre="T", page_url=None, avant="# A\n", propose="# A",
                                     commentaire="", auteur={}, nas=FauxNas())


async def test_seul_un_projet_depose_par_le_cockpit_se_propose(db_session):
    await declarer(db_session, nom="sapyn", livres=("Sapyn",))           # publie par jeton : pas de proposition
    assert await dc.depose_par_cockpit(db_session, "sapyn") is False
    assert await dc.depose_par_cockpit(db_session, "inconnu") is False


async def _async_rien():
    return None


# --------------------------------------------------------------------------- #
# Compte rendu du cockpit sur une proposition                                  #
# --------------------------------------------------------------------------- #
async def _transmise(db, nom="readme-20261116T153650Z.json", statut="transmise"):
    from models.proposition_wiki import PropositionWiki

    p = PropositionWiki(page_id=1, titre="Cockpit", origine="cockpit", projet="gestion-projet-appli", cle="README",
                        markdown_avant="a", markdown_propose="b", commentaire="", auteur={"identifiant": "tclement"},
                        statut=statut, fichier_nas=f"gestion-projet-appli/propositions/{nom}")
    db.add(p)
    await db.commit()
    return p


def _decision(nas, nom, **champs):
    d = {"format": "cockpit-docs-decision/1", "proposition": nom, "decision": "appliquee",
         "par": "tclement", "le": "2026-11-16T21:00:00+00:00"}
    d.update(champs)
    nas.deposer("gestion-projet-appli", d, nom=f"propositions/decisions/{nom.replace('/', '_')}")


async def test_la_decision_du_cockpit_clot_la_proposition(db_session, publier, tmp_path):
    a = await _transmise(db_session, "a-20261116T150000Z.json")
    r = await _transmise(db_session, "r-20261116T150000Z.json")
    nas = FauxNas()
    _decision(nas, "a-20261116T150000Z.json")
    _decision(nas, "r-20261116T150000Z.json", decision="refusee", motif="déjà corrigé", par=None)

    bilan = await dc.relever(db_session, nas=nas, publier=publier, archives=tmp_path)

    await db_session.refresh(a)
    await db_session.refresh(r)
    assert (a.statut, a.decide_par) == ("appliquee", "tclement (cockpit)")
    assert a.decide_le.isoformat().startswith("2026-11-16T21:00")
    assert (r.statut, r.decide_par, r.motif) == ("refusee", "cockpit", "déjà corrigé")
    assert not [c for c in nas.fichiers if "/decisions/" in c]          # fichiers retirés
    assert sorted(b["resultat"] for b in bilan["depots"]) == ["appliquee", "refusee"]


async def test_une_decision_inconnue_ou_illisible_est_retiree_sans_rien_changer(db_session, publier, tmp_path):
    close = await _transmise(db_session, "c-20261116T150000Z.json", statut="refusee")
    nas = FauxNas()
    _decision(nas, "c-20261116T150000Z.json")                          # déjà close : on n'y touche pas
    _decision(nas, "x-20261116T150000Z.json")                          # ne correspond à rien
    nas.deposer("gestion-projet-appli", b"{pas du json", nom="propositions/decisions/casse.json")
    _decision(nas, "../evasion.json")                                  # nom invalide

    bilan = await dc.relever(db_session, nas=nas, publier=publier, archives=tmp_path)

    await db_session.refresh(close)
    assert close.statut == "refusee" and close.decide_par is None
    assert not [c for c in nas.fichiers if "/decisions/" in c]
    assert sorted(b["resultat"] for b in bilan["depots"]) == ["deja_close", "illisible", "illisible", "inconnue"]


def test_une_decision_doit_dire_appliquee_ou_refusee():
    with pytest.raises(dc.Refus):
        dc.lire_decision({"format": "cockpit-docs-decision/1", "proposition": "a.json", "decision": "peut-etre"})
    assert dc.lire_decision({"format": "cockpit-docs-decision/1", "proposition": "a.json",
                             "decision": "refusee"})["par"] is None
