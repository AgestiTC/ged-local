"""
Propositions de modification pour TOUS les livres du wiki (16/11/2026).

Faux BookStack (pages Markdown, HTML, publiées par le cockpit ou un projet à jeton), vraie base de test.
"""
import json

import pytest

from models.publication import Publication
from models.publieur import ProjetPublieur
from services import propositions_wiki as pw
from tests.test_docs_cockpit import FauxNas

AUTEUR = {"identifiant": "mdupont", "nom": "Marie Dupont", "email": "m@x.fr"}


class Wiki:
    configured = True
    base_url = "http://wiki.local"

    def __init__(self) -> None:
        self.pages = {
            1: {"id": 1, "name": "Procédure", "book_id": 7, "markdown": "# Procédure\nÉtape 1", "html": "",
                "updated_at": "2026-11-01T10:00:00Z", "tags": [{"name": "service", "value": "compta"}]},
            2: {"id": 2, "name": "Ancienne page", "book_id": 7, "markdown": "",
                "html": "<h2>Titre</h2><p>Texte <strong>gras</strong></p><ul><li>un</li><li>deux</li></ul>",
                "updated_at": "2026-11-01T10:00:00Z", "tags": []},
            3: {"id": 3, "name": "README", "book_id": 8, "markdown": "> ⚙️ _Page générée automatiquement depuis le "
                "projet **gestion-projet-appli** via la passerelle_\n\n# Cockpit", "html": "", "updated_at": "x", "tags": []},
            4: {"id": 4, "name": "Sapyn", "book_id": 9, "markdown": "# Sapyn", "html": "", "updated_at": "x", "tags": []},
        }
        self.ecrits: list[tuple] = []

    async def get_page(self, page_id: int) -> dict:
        return dict(self.pages[page_id])

    async def update_page(self, page_id, markdown, name=None, tags=None):
        self.ecrits.append((page_id, markdown, tags))
        self.pages[page_id].update(markdown=markdown, tags=tags, updated_at="2026-11-16T18:00:00Z")
        return self.pages[page_id]

    def page_url(self, page: dict) -> str:
        return f"{self.base_url}/p/{page['id']}"


@pytest.fixture
async def base(db_session):
    db_session.add_all([
        ProjetPublieur(nom="gestion-projet-appli", token_hash="a", livres_autorises=["Cockpit Projets"], depot_cockpit=True),
        ProjetPublieur(nom="sapyn", token_hash="b", livres_autorises=["Sapyn"]),
        Publication(projet="gestion-projet-appli", cle="README", livre="Cockpit Projets", page_id=3, contenu_hash="h3"),
        Publication(projet="sapyn", cle="index", livre="Sapyn", page_id=4, contenu_hash="h4"),
    ])
    await db_session.commit()
    return db_session


def test_html_converti_en_markdown():
    md = pw.html_vers_markdown("<h2>Titre</h2><p>Texte <strong>gras</strong></p><ul><li>un</li><li>deux</li></ul>")
    assert "## Titre" in md and "**gras**" in md and "- un" in md and "- deux" in md


def test_nom_auteur():
    assert pw.nom_auteur(AUTEUR) == "Marie Dupont (mdupont)"
    assert pw.nom_auteur({"identifiant": "tclement", "nom": "tclement"}) == "tclement"


async def test_origine_de_chaque_page(base):
    assert (await pw.origine_page(base, 1))[0] == "bookstack"
    assert (await pw.origine_page(base, 3))[0] == "cockpit"
    assert (await pw.origine_page(base, 4))[0] == "projet"


async def test_page_bookstack_proposee_puis_appliquee_avec_etiquette(base):
    wiki = Wiki()
    p = await pw.proposer(base, wiki, 1, "# Procédure\nÉtape 1\nÉtape 2", " ajout ", AUTEUR)
    assert (p.statut, p.origine, p.converti, p.commentaire) == ("proposee", "bookstack", False, "ajout")
    assert wiki.ecrits == []                                   # rien n'est écrit sans un admin

    await pw.appliquer(base, wiki, p, "Thomas (tclement)")
    (pid, md, tags), = wiki.ecrits
    assert pid == 1 and md.endswith("Étape 2")
    assert {"name": "service", "value": "compta"} in tags     # les étiquettes existantes sont gardées
    trace = next(t["value"] for t in tags if t["name"] == pw.ETIQUETTE)
    assert "proposé par Marie Dupont (mdupont)" in trace and "validé par Thomas (tclement)" in trace
    assert p.statut == "appliquee" and p.decide_par == "Thomas (tclement)"


async def test_page_html_convertie(base):
    p = await pw.proposer(base, Wiki(), 2, "## Titre\n\nTexte corrigé", "", AUTEUR)
    assert p.converti is True and "## Titre" in p.markdown_avant


async def test_conflit_si_la_page_a_change_depuis(base):
    wiki = Wiki()
    p = await pw.proposer(base, wiki, 1, "# Procédure\nNouveau", "", AUTEUR)
    wiki.pages[1]["updated_at"] = "2026-11-10T09:00:00Z"      # quelqu'un a modifié la page dans BookStack
    with pytest.raises(pw.Conflit):
        await pw.appliquer(base, wiki, p, "admin")
    await pw.appliquer(base, wiki, p, "admin", forcer=True)
    assert p.statut == "appliquee"


async def test_page_du_cockpit_transmise_au_projet(base):
    nas = FauxNas()

    async def rien(_):
        return None
    nas.creer_dossier = rien
    p = await pw.proposer(base, Wiki(), 3, "# Cockpit\nCorrigé", "", AUTEUR, nas=nas)
    assert p.statut == "transmise" and p.fichier_nas.startswith("gestion-projet-appli/propositions/readme-")
    assert json.loads(nas.fichiers[p.fichier_nas])["markdown_avant"] == "# Cockpit"   # sans bandeau
    with pytest.raises(ValueError):
        await pw.appliquer(base, Wiki(), p, "admin")           # c'est le cockpit qui applique


async def test_page_d_un_projet_a_jeton_a_reporter(base):
    wiki = Wiki()
    p = await pw.proposer(base, wiki, 4, "# Sapyn\nCorrigé", "", AUTEUR)
    assert p.statut == "a_reporter"
    with pytest.raises(ValueError):
        await pw.appliquer(base, wiki, p, "admin")             # jamais écrit : le prochain envoi l'écraserait
    await pw.cloturer(base, p, "appliquee", "admin", "reporté dans le dépôt Git")
    assert p.statut == "appliquee" and wiki.ecrits == []


async def test_refus_et_validations(base):
    wiki = Wiki()
    with pytest.raises(ValueError, match="Aucune modification"):
        await pw.proposer(base, wiki, 1, "# Procédure\nÉtape 1\n", "", AUTEUR)
    p = await pw.proposer(base, wiki, 1, "# Autre", "", AUTEUR)
    await pw.cloturer(base, p, "refusee", "admin", "hors sujet")
    assert (p.statut, p.motif) == ("refusee", "hors sujet")
    with pytest.raises(ValueError):
        await pw.cloturer(base, p, "refusee", "admin")
