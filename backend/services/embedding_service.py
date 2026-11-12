"""
Service Embedding — Génération et stockage des vecteurs
========================================================
Découpe le texte en chunks et calcule leurs embeddings via Ollama, par PAQUETS
(`/api/embed`) : un appel pour jusqu'à `TAILLE_PAQUET` morceaux au lieu d'un par morceau.
Les embeddings sont stockés dans la table `embeddings` (pgvector).
"""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from logger import get_logger
from models.embedding import Embedding
from services.ollama_service import EmbedLotNonSupporte
from utils.chunker import chunk_text
from utils.vectors import matryoshka_prefix

log = get_logger(__name__)
settings = get_settings()

# Morceaux envoyés par appel `/api/embed`. 32 × ~500 tokens reste très en dessous de ce que le
# serveur accepte, et ramène un document de 100 morceaux à 4 appels (plan lots IA, étape 2).
TAILLE_PAQUET = 32


class EmbeddingService:
    """Gère la génération et le stockage des embeddings."""

    def __init__(self, ollama_service):
        self.ollama = ollama_service

    @staticmethod
    def _verifier_paquet(vecteurs: list, attendus: int, modele: str) -> list:
        """
        Cohérence d'une réponse par paquet : autant de vecteurs que de textes, aucun vide.
        Un vecteur vide stocké en NULL rendait le morceau invisible à la recherche sémantique alors
        que le document passait « enrichi » (audit du 28/09/2026, M12) ; un compte décalé
        associerait en plus un vecteur au MAUVAIS morceau. Dans les deux cas : échec, pas résultat.
        """
        if len(vecteurs) != attendus or not all(vecteurs):
            raise ValueError(
                f"embeddings incohérents renvoyés par {modele} : {len(vecteurs)} vecteur(s) "
                f"pour {attendus} texte(s), ou vecteur vide")
        return vecteurs

    async def _vecteurs_unitaires(self, paquet: list[str], modele: str) -> tuple[list, str]:
        """Appel unitaire (`/api/embeddings`) morceau par morceau — comportement historique, avec
        sa bascule sur le modèle de repli (qui reste acquise pour la suite du document)."""
        vecteurs = []
        for chunk in paquet:
            try:
                vecteur = await self.ollama.embed(chunk, model=modele)
                # Une réponse VIDE est un échec, pas un résultat (audit du 28/09/2026, M12) :
                # on la traite comme une erreur : repli, puis échec explicite.
                if not vecteur:
                    raise ValueError(f"embedding vide renvoyé par {modele}")
            except Exception as e:
                modele = self._basculer_sur_repli(modele, e)
                vecteur = await self.ollama.embed(chunk, model=modele)
                if not vecteur:
                    raise RuntimeError(
                        f"Embedding vide, y compris avec le modèle de repli {modele} — "
                        "modèle d'embedding absent ou inadapté ?") from e
            vecteurs.append(vecteur)
        return vecteurs, modele

    @staticmethod
    def _basculer_sur_repli(modele: str, erreur: Exception) -> str:
        """Fallback vers le modèle léger si le modèle principal échoue."""
        log.warning(
            "Fallback embedding",
            erreur=str(erreur),
            modele_principal=modele,
            fallback=settings.ollama_model_embedding_fallback,
        )
        return settings.ollama_model_embedding_fallback

    async def _vecteurs_du_paquet(self, paquet: list[str], modele: str,
                                  lot_possible: bool) -> tuple[list, str, bool]:
        """
        Vecteurs d'un paquet. Renvoie (vecteurs, modèle effectivement utilisé, `/api/embed` encore
        utilisable). Un échec bascule sur le modèle de repli pour ce paquet et la suite, comme
        l'ancien code le faisait morceau par morceau. Si le serveur ne connaît pas `/api/embed`,
        on retombe sur l'appel unitaire pour le reste du document.
        """
        if lot_possible:
            try:
                return self._verifier_paquet(await self.ollama.embed_many(paquet, model=modele),
                                             len(paquet), modele), modele, True
            except EmbedLotNonSupporte:
                log.warning("/api/embed refusé — repli sur l'appel unitaire", modele=modele)
                lot_possible = False
            except Exception as e:
                modele = self._basculer_sur_repli(modele, e)
                try:
                    vecteurs = self._verifier_paquet(await self.ollama.embed_many(paquet, model=modele),
                                                     len(paquet), modele)
                    return vecteurs, modele, True
                except EmbedLotNonSupporte:
                    lot_possible = False
                except ValueError as e2:
                    raise RuntimeError(
                        f"Embedding vide, y compris avec le modèle de repli {modele} — "
                        "modèle d'embedding absent ou inadapté ?") from e2
        vecteurs, modele = await self._vecteurs_unitaires(paquet, modele)
        return vecteurs, modele, lot_possible

    async def embed_document(self, document_id: str, texte: str, db: AsyncSession) -> int:
        """
        Découpe le texte en chunks, calcule les vecteurs (par paquets) et les stocke en DB.

        Args:
            document_id: UUID du document (str)
            texte: Texte extrait à encoder
            db: Session DB async

        Returns:
            Nombre de chunks générés
        """
        # Découpage déporté en thread (CPU : peut être lourd sur de gros textes → ne pas bloquer l'event loop).
        chunks = await asyncio.to_thread(chunk_text, texte)
        if not chunks:
            log.warning("Aucun chunk généré", document_id=document_id)
            return 0

        log.info("Début embedding", document_id=document_id, nb_chunks=len(chunks))
        doc_uuid = uuid.UUID(document_id)

        # Usage « embeddings » (config Paramètres) > modèle d'embedding par défaut.
        from services import runtime_config
        modele = runtime_config.usage_model("embeddings") or settings.ollama_model_embedding
        lot_possible = True
        for debut in range(0, len(chunks), TAILLE_PAQUET):
            paquet = chunks[debut:debut + TAILLE_PAQUET]
            vecteurs, modele, lot_possible = await self._vecteurs_du_paquet(paquet, modele, lot_possible)
            for i, (chunk, vecteur) in enumerate(zip(paquet, vecteurs), start=debut):
                db.add(Embedding(
                    document_id=doc_uuid,
                    chunk_index=i,
                    chunk_text=chunk,
                    embedding=vecteur,
                    # Préfixe Matryoshka 1024-d (indexable ANN) dérivé du 4096 — 1ᵉ passe de recherche.
                    embedding_small=matryoshka_prefix(vecteur),
                    modele_embedding=modele,
                ))

        await db.flush()
        log.info("Embedding terminé", document_id=document_id, nb_chunks=len(chunks))
        return len(chunks)
