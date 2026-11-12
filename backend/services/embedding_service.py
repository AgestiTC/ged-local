"""
Service Embedding — Génération et stockage des vecteurs
========================================================
Découpe le texte en chunks et calcule leurs embeddings via Ollama, par PAQUETS
(`/api/embed`) : un appel pour jusqu'à `TAILLE_PAQUET` morceaux au lieu d'un par morceau.
Les embeddings sont stockés dans la table `embeddings` (pgvector).
"""

import asyncio
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from logger import get_logger
from models.document import Document
from models.embedding import Embedding
from services import classement_echecs
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

    @staticmethod
    def _lever_echec(erreur: BaseException, modele: str):
        """
        Convertit l'échec d'un appel d'embedding en sa conduite (plan lots IA, étape 5) — ne rend jamais :

        - PASSAGER (délai dépassé, 504, connexion…) → `EchecPassager` : le calcul entier échoue, rien
          n'est écrit, les anciens vecteurs restent, le worker REPORTE le job. AUCUN appel à un autre
          modèle : un modèle de plus sur une carte pleine aggravait la saturation (12/11/2026) ;
        - modèle ABSENT → `ModeleAbsent` (échec définitif, message lisible). PAS de repli : un document
          n'a jamais de vecteurs de deux modèles, et le modèle de repli (nomic-embed-text : 768
          dimensions) ne peut pas être stocké — `embeddings.embedding` est `halfvec(4096)`,
          `embedding_small` `halfvec(1024)` — ni comparé aux vecteurs que la recherche calcule avec le
          modèle principal : même à dimension égale, deux modèles ne partagent pas le même espace ;
        - le reste → relevé tel quel (échec définitif).
        """
        nature = classement_echecs.classer_echec(erreur)
        if nature == classement_echecs.PASSAGER:
            raise classement_echecs.EchecPassager(
                classement_echecs.decrire_echec(erreur), "les embeddings") from erreur
        if nature == classement_echecs.MODELE_ABSENT:
            log.warning("Modèle d'embedding absent — pas de repli", modele=modele,
                        repli_ignore=settings.ollama_model_embedding_fallback)
            raise classement_echecs.ModeleAbsent(
                modele,
                f"Modèle d'embedding « {modele} » absent d'Ollama : aucun repli possible (le modèle de repli "
                f"« {settings.ollama_model_embedding_fallback} » ne produit pas les vecteurs de "
                f"{settings.embedding_dimension} dimensions que la base stocke, et la recherche ne saurait "
                f"pas les comparer). Installer « {modele} » dans Ollama.") from erreur
        raise (classement_echecs.cause_reelle(erreur) or erreur)

    async def _vecteurs_unitaires(self, paquet: list[str], modele: str) -> list:
        """Appel unitaire (`/api/embeddings`) morceau par morceau — comportement historique, SANS bascule
        de modèle : un échec passager ou un modèle absent suit la conduite de `_lever_echec`."""
        vecteurs = []
        for chunk in paquet:
            try:
                vecteur = await self.ollama.embed(chunk, model=modele, rejouer_apres_attente=False)
            except Exception as e:
                self._lever_echec(e, modele)
            # Une réponse VIDE est un échec définitif, pas un résultat (audit du 28/09/2026, M12) :
            # aucun repli, un modèle muet se corrige à la source.
            if not vecteur:
                raise RuntimeError(f"Embedding vide ou incohérent renvoyé par {modele} — "
                                   "modèle d'embedding inadapté ?")
            vecteurs.append(vecteur)
        return vecteurs

    async def _vecteurs_du_paquet(self, paquet: list[str], modele: str,
                                  lot_possible: bool) -> tuple[list, bool]:
        """
        Vecteurs d'un paquet, TOUJOURS du modèle demandé. Renvoie (vecteurs, `/api/embed` encore
        utilisable). Si le serveur ne connaît pas `/api/embed`, on retombe sur l'appel unitaire pour le
        reste du document. Tout autre échec suit `_lever_echec` (jamais de bascule de modèle).
        """
        if lot_possible:
            try:
                brut = await self.ollama.embed_many(paquet, model=modele, rejouer_apres_attente=False)
            except EmbedLotNonSupporte:
                log.warning("/api/embed refusé — repli sur l'appel unitaire", modele=modele)
                lot_possible = False
            except Exception as e:
                self._lever_echec(e, modele)
            else:
                try:
                    return self._verifier_paquet(brut, len(paquet), modele), True
                except ValueError as e:
                    raise RuntimeError(f"Embedding vide ou incohérent renvoyé par {modele} — "
                                       "modèle d'embedding inadapté ?") from e
        return await self._vecteurs_unitaires(paquet, modele), lot_possible

    async def calculer(self, texte: str) -> list[tuple[int, str, list, list | None, str]]:
        """
        Calcule les vecteurs d'un texte (appels Ollama, par paquets) SANS rien écrire en base.
        Renvoie des lignes `(index, morceau, vecteur, préfixe Matryoshka 1024-d, modèle)`.

        Séparé du stockage pour que la transaction d'écriture soit courte : on ne garde pas une
        connexion ouverte (et un verrou) pendant des minutes d'appels IA, et un calcul en échec
        n'a rien touché — les anciens vecteurs du document restent en place.
        """
        # Découpage déporté en thread (CPU : peut être lourd sur de gros textes → ne pas bloquer l'event loop).
        chunks = await asyncio.to_thread(chunk_text, texte)
        if not chunks:
            return []

        # Usage « embeddings » (config Paramètres) > modèle d'embedding par défaut. UN SEUL modèle pour
        # tout le document : pas de bascule en cours de route (voir `_lever_echec`).
        from services import runtime_config
        modele = runtime_config.usage_model("embeddings") or settings.ollama_model_embedding
        lot_possible = True
        lignes: list[tuple[int, str, list, list | None, str]] = []
        for debut in range(0, len(chunks), TAILLE_PAQUET):
            paquet = chunks[debut:debut + TAILLE_PAQUET]
            vecteurs, lot_possible = await self._vecteurs_du_paquet(paquet, modele, lot_possible)
            for i, (chunk, vecteur) in enumerate(zip(paquet, vecteurs), start=debut):
                # Préfixe Matryoshka 1024-d (indexable ANN) dérivé du 4096 — 1ᵉ passe de recherche.
                lignes.append((i, chunk, vecteur, matryoshka_prefix(vecteur), modele))
        return lignes

    async def remplacer(self, document_id: str, lignes: list, db: AsyncSession) -> int:
        """
        REMPLACE les embeddings d'un document : verrou sur la ligne du document, suppression des
        anciens vecteurs, insertion des nouveaux (flush ; le commit reste à l'appelant). Une étape
        rejouée ne duplique donc jamais les vecteurs, et deux écritures simultanées se sérialisent
        sur le verrou. Aucune ligne à écrire → on ne touche à rien (jamais d'effacement à vide).
        """
        if not lignes:
            return 0
        doc_uuid = uuid.UUID(str(document_id))
        # FOR NO KEY UPDATE : sérialise les écritures du document sans bloquer les clés étrangères qui le visent.
        verrou = await db.execute(select(Document.id).where(Document.id == doc_uuid).with_for_update(key_share=True))
        if verrou.first() is None:
            log.info("Embeddings abandonnés — document supprimé pendant le calcul", document_id=str(doc_uuid))
            return 0
        await db.execute(delete(Embedding).where(Embedding.document_id == doc_uuid))
        for i, chunk, vecteur, petit, modele in lignes:
            db.add(Embedding(
                document_id=doc_uuid,
                chunk_index=i,
                chunk_text=chunk,
                embedding=vecteur,
                embedding_small=petit,
                modele_embedding=modele,
            ))
        await db.flush()
        return len(lignes)

    async def embed_document(self, document_id: str, texte: str, db: AsyncSession) -> int:
        """
        Découpe le texte en chunks, calcule les vecteurs (par paquets) et les stocke en DB en
        REMPLAÇANT ceux du document (« supprimer puis insérer » : rejouable sans doublon).

        Args:
            document_id: UUID du document (str)
            texte: Texte extrait à encoder
            db: Session DB async

        Returns:
            Nombre de chunks générés
        """
        log.info("Début embedding", document_id=document_id)
        lignes = await self.calculer(texte)
        if not lignes:
            log.warning("Aucun chunk généré", document_id=document_id)
            return 0
        n = await self.remplacer(document_id, lignes, db)
        log.info("Embedding terminé", document_id=document_id, nb_chunks=n)
        return n
