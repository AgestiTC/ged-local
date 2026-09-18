"""
Suites de l'audit du 16/09/2026 (v1.109.1) — les trois points laissés ouverts.

1. Un document en échec répété n'est plus relancé à chaque clic de « Relancer l'IA ».
2. Le job « Analyser le contenu » échoue quand l'IA ne produit rien sur un doc AVEC texte,
   mais reste « terminé » pour une photo ou une vidéo sans texte (cas normal).
3. Une divergence de contexte (num_ctx) est signalée : diagnostic IA + journal.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.document import Document
from models.job import Job
from models.metadata import MetadonneeIA
from routers.documents import ECHECS_ENRICH_MAX
from services import diagnostic_ia as diag
from services import job_handlers
from services.ollama_service import OllamaService, settings


# ─── 1. Échecs répétés ────────────────────────────────────────────────────────

def _doc(nom: str, texte: str = "du texte") -> Document:
    return Document(id=uuid.uuid4(), nom=nom, extension="pdf", chemin=f"/x/{nom}",
                    hash_sha256=nom, texte_extrait=texte, statut="extracted")


async def _base(db_session, echecs_par_doc: dict[str, int]) -> dict[str, Document]:
    docs = {nom: _doc(nom) for nom in echecs_par_doc}
    enrichi = _doc("deja-classe.pdf")
    db_session.add_all([*docs.values(), enrichi])
    db_session.add(MetadonneeIA(document_id=enrichi.id, categorie="rapport", tags=[]))
    for nom, n in echecs_par_doc.items():
        for _ in range(n):
            db_session.add(Job(type="enrich", statut="failed", document_id=docs[nom].id, erreur="vide"))
    await db_session.commit()
    return docs


class TestEchecsRepetes:
    @pytest.mark.asyncio
    async def test_compteurs_distinguent_les_echecs_repetes(self, client, db_session):
        await _base(db_session, {"jamais.pdf": 0, "une-fois.pdf": 1, "chronique.pdf": ECHECS_ENRICH_MAX})

        r = await client.get("/api/documents/maintenance/counts")

        assert r.status_code == 200
        assert r.json()["reenrich"] == 3            # « Restant » dit toujours la vérité
        assert r.json()["reenrich_echecs"] == 1     # … dont 1 que le bouton ne relance plus

    @pytest.mark.asyncio
    async def test_lot_ignore_les_echecs_repetes(self, client, db_session):
        docs = await _base(db_session, {"jamais.pdf": 0, "une-fois.pdf": 1, "chronique.pdf": ECHECS_ENRICH_MAX})
        with patch("services.job_worker.enqueue", new=AsyncMock()) as enqueue:
            r = await client.post("/api/documents/reenrich-batch")

        assert r.json()["enqueued"] == 2
        relances = {c.kwargs["document_id"] for c in enqueue.await_args_list}
        assert docs["chronique.pdf"].id not in relances
        assert docs["une-fois.pdf"].id in relances   # sous le seuil : on retente

    @pytest.mark.asyncio
    async def test_reessayer_quand_meme(self, client, db_session):
        await _base(db_session, {"jamais.pdf": 0, "chronique.pdf": ECHECS_ENRICH_MAX + 2})
        with patch("services.job_worker.enqueue", new=AsyncMock()):
            r = await client.post("/api/documents/reenrich-batch", params={"inclure_echecs": True})

        assert r.json()["enqueued"] == 2


# ─── 2. Job « analyze » ──────────────────────────────────────────────────────

async def _lancer_analyze(doc: Document, ok: bool):
    session = MagicMock()
    session.get = AsyncMock(return_value=doc)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    ctx = MagicMock()
    ctx.parametres = {"document_id": str(doc.id)}
    ctx.report = AsyncMock()
    service = MagicMock()
    service.analyze_existing = AsyncMock(return_value=ok)
    with patch.object(job_handlers, "AsyncSessionLocal", return_value=cm), \
         patch.object(job_handlers, "_resoudre_fichier", new=AsyncMock(return_value=("/tmp/f", lambda: None))), \
         patch("routers.upload._get_extraction_service", return_value=service):
        return await job_handlers.handler_analyze(ctx)


class TestJobAnalyze:
    @pytest.mark.asyncio
    async def test_photo_sans_texte_reste_terminee(self):
        doc = _doc("photo.jpg", texte="")
        resultat = await _lancer_analyze(doc, ok=False)
        assert resultat["ok"] is False and resultat["sans_texte"] is True

    @pytest.mark.asyncio
    async def test_texte_sans_categorie_echoue(self):
        doc = _doc("long.pdf", texte="beaucoup de texte")
        with pytest.raises(RuntimeError, match="catégorie"):
            await _lancer_analyze(doc, ok=False)

    @pytest.mark.asyncio
    async def test_fichier_infecte_echoue_avec_la_raison(self):
        doc = _doc("virus.pdf", texte="")
        doc.statut, doc.erreur = "error", "Menace détectée par l'antivirus : Eicar"
        with pytest.raises(RuntimeError, match="Eicar"):
            await _lancer_analyze(doc, ok=False)

    @pytest.mark.asyncio
    async def test_succes_inchange(self):
        doc = _doc("ok.pdf")
        assert (await _lancer_analyze(doc, ok=True))["ok"] is True


# ─── 3. Divergence de contexte ───────────────────────────────────────────────

LLAMA = {"nom": "llama3.1:latest", "taille_go": 4.9, "parametres": "", "quantisation": "Q4_K_M",
         "architecture": "llama", "moe": False, "experts": 0, "experts_actifs": 0, "contexte_max": 131072,
         "capacites": ["completion"], "projecteur": False, "template_ok": True, "analyse_complete": True}
USAGES = {"enrichissement": "llama3.1:latest"}


def _charge(contexte: int) -> dict:
    return {"nom": "llama3.1:latest", "taille_go": 6.0, "part_gpu": 100, "contexte": contexte, "permanent": True}


class TestDiagnosticContexte:
    def test_modele_partage_avec_autre_contexte_signale(self):
        faits = {"modeles": [LLAMA], "charges": [_charge(8192)]}
        c = next(c for c in diag.analyser(faits, USAGES, 16, "llama3.1:latest", num_ctx=16384)
                 if c.titre == "Contexte du modèle partagé différent de Matothèque")
        assert c.niveau == "important"
        assert "8192" in c.detail and "16384" in c.detail

    def test_contexte_aligne_rien_a_signaler(self):
        faits = {"modeles": [LLAMA], "charges": [_charge(16384)]}
        titres = [c.titre for c in diag.analyser(faits, USAGES, 16, "llama3.1:latest", num_ctx=16384)]
        assert not any("différent de" in t for t in titres)

    def test_sans_num_ctx_pas_de_comparaison(self):
        faits = {"modeles": [LLAMA], "charges": [_charge(8192)]}
        titres = [c.titre for c in diag.analyser(faits, USAGES, 16, "llama3.1:latest")]
        assert not any("différent de" in t for t in titres)


class TestRechargementEpingle:
    @pytest.fixture(autouse=True)
    def _epingle(self, monkeypatch):
        monkeypatch.setattr(settings, "ollama_pinned_model", "llama3.1:latest", raising=False)

    def test_rechargement_long_du_modele_epingle_signale(self):
        assert OllamaService._signaler_rechargement("llama3.1:latest", {"load_duration": 6_000_000_000})

    def test_modele_deja_resident_pas_de_signal(self):
        assert not OllamaService._signaler_rechargement("llama3.1:latest", {"load_duration": 20_000_000})

    def test_autre_modele_pas_concerne(self):
        """Le chargement d'un modèle non épinglé est normal (keep_alive borné)."""
        assert not OllamaService._signaler_rechargement("ministral-3:14b", {"load_duration": 9_000_000_000})
