"""
Capture des prompts envoyés à l'IA — étape A3c du plan `docs/plan-prompts-et-rag-apprenant.md`.
================================================================================================
Script (PAS un test : pytest ne le collecte pas). Il appelle chaque fonction qui envoie un prompt
avec des **entrées fictives fixes** (aucune donnée réelle, aucun nom de candidat réel), en simulant
l'IA : le faux service enregistre le prompt et le `system` reçus, puis interrompt l'appel
(`_Arret`, une `BaseException` que les `except Exception` des fonctions ne rattrapent pas).

Lancé AVANT la migration, il a figé `tests/donnees/prompts_origine_a3c.json`. Après la migration,
`tests/test_prompts_a3c.py` rejoue les MÊMES scénarios (`capturer()`) et compare à l'octet près.

Clés : la clé du registre, suivie au besoin de `#variante` (même prompt, autres entrées).
`niveau` : « appel » = la fonction qui envoie a été appelée entière ; « construction » = la
fonction qui bâtit le texte (même entrées → même texte), quand l'appel entier dépend de la base
ou de l'heure.

    cd backend && python tests/capture_prompts_a3c.py   # réécrit la fixture
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib
import json
import sys
import tempfile
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURE = Path(__file__).parent / "donnees" / "prompts_origine_a3c.json"


class _Arret(BaseException):
    """Interrompt la fonction juste après l'envoi : on ne veut que le texte envoyé."""


_JOURNAL: list[dict] = []
_REPONSES: list[str] = []


class FauxOllama:
    """Remplace `OllamaService` (classe ou instance) : enregistre prompt + system, puis s'arrête."""

    base_url = "http://faux"

    def __init__(self, *args, **kwargs):
        pass

    async def generate(self, prompt=None, model=None, system=None, **kwargs):
        _JOURNAL.append({"prompt": prompt, "system": system})
        if _REPONSES:
            return _REPONSES.pop(0)
        raise _Arret()

    async def chat(self, *args, **kwargs):  # pragma: no cover — aucun prompt système migré n'y passe
        raise AssertionError("chat() inattendu")

    async def generate_stream(self, prompt=None, model=None, system=None, **kwargs):
        _JOURNAL.append({"prompt": prompt, "system": system})
        raise _Arret()
        yield ""  # noqa — fait de la méthode un générateur asynchrone


# Modules qui détiennent `OllamaService` en nom global (les autres l'importent localement depuis
# services.ollama_service, patché aussi).
_MODULES_OLLAMA = [
    "services.ollama_service", "routers.assistant", "routers.organize", "routers.system",
    "services.dossier_import", "services.dossier_resume", "services.jalon_ia",
    "services.presentation_service",
]


@contextlib.contextmanager
def _simulation():
    with contextlib.ExitStack() as pile:
        for nom in _MODULES_OLLAMA:
            mod = importlib.import_module(nom)
            if hasattr(mod, "OllamaService"):
                pile.enter_context(patch.object(mod, "OllamaService", FauxOllama))
        from services import runtime_config
        pile.enter_context(patch.object(runtime_config, "model_for", lambda *a, **k: "modele-test"))
        yield


async def _un_appel(coro_fn, reponses: list[str] | None = None) -> list[dict]:
    """Lance `coro_fn()` sous simulation ; rend les envois enregistrés."""
    _JOURNAL.clear()
    _REPONSES[:] = list(reponses or [])
    with _simulation():
        try:
            await coro_fn()
        except _Arret:
            pass
    return list(_JOURNAL)


def _doc(nom: str, texte: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.UUID(int=len(nom)), nom=nom, texte_extrait=texte,
                           tika_metadata=None, date_modification_fichier=None)


_DOCS = [
    _doc("offre_alpha.pdf", "Prix total : 12 000 € HT. Délai de livraison : 6 semaines.\nGarantie 2 ans."),
    _doc("memoire_technique.docx", "  Méthodologie en trois phases.\n\nÉquipe de 4 personnes.  "),
]
_INSTRUCTIONS = "Note sur 20. Privilégie le délai.\nSignale toute pièce manquante."


# ─── Scénarios ───────────────────────────────────────────────────────────────


async def _assistant_pieces():
    from routers import assistant
    from services import modeles_externes
    with patch.object(modeles_externes, "resoudre_modele_interactif",
                      AsyncMock(return_value=modeles_externes.ModeleResolu(nom="modele-test"))):
        await assistant.proposer_pieces(assistant.BesoinIn(besoin="dossier de location d'un appartement"))


def _wiki(livres, chapitres):
    async def f():
        from routers import bookstack

        class FauxBookStack:
            configured = True

            async def list_books(self):
                return livres

            async def list_chapters(self):
                return chapitres

        md = "# Installer un service\n\nÉtapes : télécharger, configurer, lancer.\n" + "x" * 5000
        with patch.object(bookstack, "BookStackService", FauxBookStack), \
                patch.object(bookstack, "_resolve_markdown", AsyncMock(return_value=md)):
            await bookstack.suggest(bookstack.SuggestRequest(markdown=md), db=None)
    return f


def _comparatif_criteres(instructions):
    async def f():
        from routers.compare import _deduire_colonnes
        await _deduire_colonnes(_DOCS, instructions, "modele-test", FauxOllama())
    return f


def _comparatif_colonnes(instructions, exigences):
    async def f():
        from routers.compare import _analyser_groupe
        await _analyser_groupe("Société Alpha", _DOCS, ["Prix", "Délai", "Garantie"], instructions,
                               "modele-test", FauxOllama(), exigences=exigences)
    return f


_GROUPES = [
    {"nom": "Société Alpha", "valeurs": {"Prix": "12 000 €", "Délai": "6 semaines"}},
    {"nom": "Société Beta", "valeurs": {"Prix": "10 500 €", "Délai": "N/A"}},
]


def _comparatif_ecarts(instructions):
    async def f():
        from routers.compare import _synthetiser_ecarts
        await _synthetiser_ecarts(["Prix", "Délai"], _GROUPES, instructions, "modele-test", FauxOllama())
    return f


async def _rapport_systeme():
    from services import rapport_jobs
    ctx = SimpleNamespace(parametres={"prompt": "Fais une synthèse.", "model": "modele-test", "sources": []},
                          report=AsyncMock(), job_id="job-test", cancelled=False)
    with patch.object(rapport_jobs, "_charger_documents", AsyncMock(return_value=_DOCS)):
        await rapport_jobs.handler_rapport(ctx)


async def _resume_hf():
    from routers import huggingface

    class Rep:
        def __init__(self, code, data=None, text=""):
            self.status_code, self._data, self.text = code, data, text

        def json(self):
            return self._data

    class FauxClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            if url.endswith("README.md"):
                return Rep(200, text="---\nlicense: mit\n---\n# Modèle\nA small model for text classification.\n"
                                     "It is fast and accurate on short texts.\n")
            return Rep(200, {"pipeline_tag": "text-classification", "tags": ["gguf"]})

    with patch.object(huggingface.httpx, "AsyncClient", FauxClient), \
            patch.object(huggingface, "_token", lambda: None):
        await huggingface.model_detail(id="org-fictive/modele-fictif")


def _rangement_dossiers(consigne):
    async def f():
        from routers.organize import _proposer_dossiers
        await _proposer_dossiers(["facture", "contrat", "recette"], consigne)
    return f


def _resume_local(m):
    async def f():
        from routers.system import _resume_ia
        await _resume_ia("modele-fictif:7b", m)
    return f


async def _dossier_import():
    from services.dossier_import import parser_ressources
    await parser_ressources("| Titre | Lien |\n|---|---|\n| Podcast fictif | https://exemple.invalid/p |\n"
                            + "y" * 21000)


def _ressource(**kw):
    base = dict(id=uuid.UUID(int=7), contenu=None, note=None, type="livre", titre="Un livre fictif", auteur=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _dossier_resume(r):
    async def f():
        from services.dossier_resume import resumer_ressource
        await resumer_ressource(r)
    return f


def _diff_resume(ancien):
    async def f():
        from services.extraction import ExtractionService
        svc = ExtractionService.__new__(ExtractionService)
        svc.ollama = FauxOllama()
        version = SimpleNamespace(id=uuid.UUID(int=3), diff_resume=None)
        db = SimpleNamespace(flush=AsyncMock())
        await svc._generate_diff_resume(version, ancien, "Nouveau texte du contrat. " * 400, db)
    return f


def _fiche(instructions):
    async def f():
        from services.fiches_candidats import rediger_fiche
        await rediger_fiche("Société Alpha", {"Prix": "12 000 €", "Délai": "N/A", "Garantie": "2 ans"},
                            instructions, "modele-test", FauxOllama())
    return f


def _grille(**kw):
    async def f():
        from services.grille_analyse import Critere, evaluer_critere
        crit = Critere(ligne=4, libelle="Valeur technique\nMéthodologie et moyens", documents=kw.get("documents", ""),
                       points=None)
        await evaluer_critere("Société Alpha", crit, _DOCS, kw.get("instructions"), "modele-test", FauxOllama(),
                              note_max=kw.get("note_max", 20.0), exigences=kw.get("exigences"),
                              bareme=kw.get("bareme"))
    return f


async def _grille_structure():
    import openpyxl
    from services.grille_apprise import apprendre
    with tempfile.TemporaryDirectory() as d:
        chemin = Path(d) / "grille.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Analyse"
        ws["A1"] = "Grille d'analyse fictive"
        ws["B4"] = "Candidat 1"
        ws["C4"] = "Candidat 2"
        ws["A5"] = "Critère 1 : prix"
        ws["A6"] = "Critère 2 : délai"
        ws["B7"] = 3
        ws["C7"] = "=B7*2"
        wb.save(chemin)
        await apprendre(chemin, FauxOllama(), "modele-test")


def _agenda(terme):
    async def f():
        from services.jalon_ia import analyser_evenement
        await analyser_evenement("Rendez-vous de suivi le vendredi 25 septembre de 13h à 14h", date(2026, 9, 20),
                                 terme)
    return f


def _musique(style, paroles):
    async def f():
        from services import musique_jobs
        with patch.object(musique_jobs, "_modeles_charges", AsyncMock(return_value=[])):
            await musique_jobs.preparer_style(style, paroles, "fr")
    return f


def _presentation(consigne):
    async def f():
        from services.presentation_service import generer_slides

        meta = SimpleNamespace(resume="Résumé fictif du premier document.")
        rows = [(_DOCS[0], meta), (_DOCS[1], None)]

        class Res:
            def all(self):
                return rows

        db = SimpleNamespace(execute=AsyncMock(return_value=Res()))
        await generer_slides([str(uuid.UUID(int=1))], db, consigne=consigne)
    return f


def _rangement_plan(parent, apercu, famille):
    async def f():
        from services.rangement.plan import Candidat, proposer_par_ia
        noeuds = [SimpleNamespace(chemin="Films", description="Films de cinéma"),
                  SimpleNamespace(chemin="Dessins Animes", description=None)]
        c = Candidat(chemin=(parent + "/" if parent else "") + "Un film fictif", nom="Un film fictif",
                     est_dossier=True, taille=1_500_000_000, parent=parent, famille=famille, apercu=apercu)
        await proposer_par_ia(c, noeuds)
    return f


def _recommandation(classement, synthese, instructions):
    async def f():
        from services.recommandation_comparatif import recommander
        await recommander("| Critère | Alpha | Beta |\n|---|---|---|\n| Prix | 12 000 € | 10 500 € |",
                          [{"nom": "Société Alpha"}, {"nom": "Société Beta"}, {"nom": "Société Gamma", "echec_ia": True}],
                          classement, synthese, instructions, "modele-test", FauxOllama())
    return f


async def _regroupement():
    from services import modeles_externes, regroupement_jobs
    rg = SimpleNamespace(prompt=None, modele="modele-test", document_ids=[str(uuid.UUID(int=1))])

    class Res:
        def scalars(self):
            return self

        def all(self):
            return _DOCS

    class FausseSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a):
            return rg

        async def execute(self, *a):
            return Res()

    ctx = SimpleNamespace(parametres={"regroupement_id": str(uuid.UUID(int=9))}, type="analyse_regroupement",
                          report=AsyncMock())
    with patch.object(regroupement_jobs, "AsyncSessionLocal", FausseSession), \
            patch.object(modeles_externes, "controle_job", AsyncMock(return_value=None)):
        await regroupement_jobs.handler_analyse_regroupement(ctx)


def _relecture(mode):
    async def f():
        from services.relecture_prompt import relire_prompt
        await relire_prompt("note les offres sur 20 et dis pourquoi", mode, "modele-test", FauxOllama())
    return f


def _remplissage(instructions):
    async def f():
        from services.template_filler import TemplateFiller
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "modele.docx"
            chemin.write_bytes(b"fictif")
            template = SimpleNamespace(type="docx", chemin_fichier=str(chemin), nom="Modèle fictif",
                                       champs=[{"nom": "client"}, {"nom": "montant_total"}])

            class Res:
                def __init__(self, valeur):
                    self.valeur = valeur

                def scalar_one_or_none(self):
                    return self.valeur

                def scalars(self):
                    return self

                def all(self):
                    return self.valeur

            db = SimpleNamespace(execute=AsyncMock(side_effect=[Res(template), Res(_DOCS)]))
            tf = TemplateFiller.__new__(TemplateFiller)
            tf.ollama = FauxOllama()
            await tf.fill(str(uuid.UUID(int=5)), [str(uuid.UUID(int=1))], instructions, "modele-test", db)
    return f


async def _video():
    from services.video_jobs import preparer_mouvement
    await preparer_mouvement("Le chat tourne la tête puis s'endort.")


# (clé, entrées décrites, scénario, réponses simulées par l'IA avant l'arrêt)
SCENARIOS: list[tuple[str, dict, object, list[str] | None]] = [
    ("assistant.pieces", {"besoin": "dossier de location d'un appartement"}, _assistant_pieces, None),
    ("wiki.emplacement", {"livres": 2, "chapitres": 1, "markdown": "≈ 5 000 car."},
     _wiki([{"id": 1, "name": "Infrastructure"}, {"id": 2, "name": "Applications"}],
           [{"name": "Docker", "book_id": 1}]), None),
    ("wiki.emplacement#vide", {"livres": 0, "chapitres": 0}, _wiki([], []), None),
    ("comparatif.criteres", {"instructions": None}, _comparatif_criteres(None), None),
    ("comparatif.criteres#consignes", {"instructions": _INSTRUCTIONS}, _comparatif_criteres(_INSTRUCTIONS), None),
    ("comparatif.colonnes", {"instructions": None, "exigences": None}, _comparatif_colonnes(None, None), None),
    ("comparatif.colonnes#complet", {"instructions": _INSTRUCTIONS, "exigences": "Délai maximal : 8 semaines."},
     _comparatif_colonnes(_INSTRUCTIONS, "Délai maximal : 8 semaines."), None),
    ("comparatif.ecarts", {"instructions": None}, _comparatif_ecarts(None), None),
    ("comparatif.ecarts#attentes", {"instructions": "Insiste sur le prix"}, _comparatif_ecarts("Insiste sur le prix"),
     None),
    ("rapport.systeme", {"prompt": "Fais une synthèse."}, _rapport_systeme, None),
    ("modeles.resume_hf", {"id": "org-fictive/modele-fictif"}, _resume_hf, None),
    ("rangement.dossiers", {"consigne": None}, _rangement_dossiers(None), None),
    ("rangement.dossiers#consigne", {"consigne": "par année"}, _rangement_dossiers("par année"), None),
    ("modeles.resume_local", {"parametres": "7B", "moe": False},
     _resume_local({"parametres": "7B", "taille_go": 4.5, "quantisation": "Q4_K_M", "moe": False,
                    "capacites": ["completion", "tools"]}), None),
    ("modeles.resume_local#inconnu", {"m": {}}, _resume_local({"moe": True}), None),
    ("dossier.import_ressources", {"texte": "tableau markdown + 21 000 car."}, _dossier_import, None),
    ("dossier.resume_condense", {"contenu": "texte long"},
     _dossier_resume(_ressource(contenu="Un texte fictif à résumer. " * 300)), None),
    ("dossier.resume_condense#note", {"note": "> 200 car."},
     _dossier_resume(_ressource(note="Une note fictive assez longue. " * 10)), None),
    ("dossier.resume_decrit", {"titre": "Un livre fictif"}, _dossier_resume(_ressource()), None),
    ("dossier.resume_decrit#complet", {"auteur": "Auteur Fictif", "note": "courte"},
     _dossier_resume(_ressource(type="serie", auteur="Auteur Fictif", note="Note courte.")), None),
    ("version.diff_resume", {"ancien_resume": "Contrat de 2025."}, _diff_resume("Contrat de 2025."), None),
    ("version.diff_resume#sans_ancien", {"ancien_resume": None}, _diff_resume(None), None),
    ("comparatif.fiche", {"instructions": None}, _fiche(None), None),
    ("comparatif.fiche#contexte", {"instructions": _INSTRUCTIONS}, _fiche(_INSTRUCTIONS), None),
    ("grille.critere", {"minimal": True}, _grille(), None),
    ("grille.critere#complet", {"bareme": 2, "exigences": True, "instructions": True, "documents": True},
     _grille(documents="Mémoire technique", instructions=_INSTRUCTIONS, exigences="Équipe d'au moins 3 personnes.",
             note_max=25.0, bareme=[{"note": 0, "libelle": "Absent"}, {"note": 12.5, "libelle": "Complet"}]), None),
    ("grille.structure", {"classeur": "fictif, 1 feuille"}, _grille_structure, ["{}"]),
    ("agenda.evenement", {"aujourdhui": "2026-09-20", "terme": None}, _agenda(None), None),
    ("agenda.evenement#terme", {"aujourdhui": "2026-09-20", "terme": "2027-01-10"}, _agenda(date(2027, 1, 10)), None),
    ("musique.style", {"style": "rap mélancolique", "paroles": "deux lignes"},
     _musique("rap mélancolique", "Première ligne\nDeuxième ligne"), None),
    ("musique.style#vide", {"style": "", "paroles": ""}, _musique("", ""), None),
    ("presentation.slides", {"consigne": None}, _presentation(None), None),
    ("presentation.slides#consigne", {"consigne": "10 diapos"}, _presentation("10 diapos"), None),
    ("rangement.plan", {"parent": "Films", "apercu": 2}, _rangement_plan("Films", ["a.mkv", "b.srt"], "video"), None),
    ("rangement.plan#racine", {"parent": "", "apercu": 0}, _rangement_plan("", [], None), None),
    ("comparatif.recommandation", {"classement": None, "synthese": None, "instructions": None},
     _recommandation(None, None, None), None),
    ("comparatif.recommandation#complet", {"classement": True, "synthese": True, "instructions": True},
     _recommandation("| Rang | Candidat |\n| 1 | Alpha |\n", "- Alpha plus cher\n", _INSTRUCTIONS), None),
    ("regroupement.defaut", {"prompt_du_groupe": None}, _regroupement, None),
    ("prompts.relecture", {"mode": "comparatif"}, _relecture("comparatif"), None),
    ("prompts.relecture#rapport_libre", {"mode": "rapport_libre"}, _relecture("rapport_libre"), None),
    ("modele.remplissage", {"instructions": None}, _remplissage(None), None),
    ("modele.remplissage#instructions", {"instructions": "Ton formel"}, _remplissage("Ton formel"), None),
    ("video.mouvement", {"scenario": "Le chat tourne la tête puis s'endort."}, _video, None),
]


def _idees_bilan() -> dict:
    from services.idees_evolution import construire_prompt
    consignes = [(datetime(2026, 9, 3, tzinfo=timezone.utc), "Vérifie les pénalités de retard"),
                 (datetime(2026, 9, 17, tzinfo=timezone.utc), "Compare les délais de livraison")]
    return {"prompt": construire_prompt(consignes, "01/09/2026 → 30/09/2026"), "system": None}


CONSTRUCTIONS = [
    ("idees.bilan", {"consignes": 2, "periode": "01/09/2026 → 30/09/2026"}, _idees_bilan),
]


async def capturer() -> dict:
    """Rejoue tous les scénarios ; rend `{clé: {entrees, niveau, prompt, system}}`."""
    sortie: dict = {}
    for cle, entrees, scenario, reponses in SCENARIOS:
        envois = await _un_appel(scenario, reponses)
        if not envois:
            raise RuntimeError(f"{cle} : aucun envoi capturé")
        sortie[cle] = {"entrees": entrees, "niveau": "appel", **envois[0]}
        if len(envois) > 1:   # second essai (grille apprise : rappel de l'erreur)
            sortie[cle + "@essai2"] = {"entrees": entrees, "niveau": "appel", **envois[1]}
    for cle, entrees, fn in CONSTRUCTIONS:
        sortie[cle] = {"entrees": entrees, "niveau": "construction", **fn()}
    return sortie


def cle_registre(cle_fixture: str) -> str:
    """`grille.structure#x@essai2` → `grille.structure`."""
    return cle_fixture.split("#")[0].split("@")[0]


if __name__ == "__main__":
    donnees = asyncio.run(capturer())
    FIXTURE.write_text(json.dumps(donnees, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(donnees)} envois capturés → {FIXTURE}")
