"""
Service d'accès aux fichiers indexés — résolution chemin → fichier local lisible
================================================================================
La GED ne peut pas ouvrir l'explorateur Windows ni le logiciel associé depuis le
navigateur. À la place, le backend sert le fichier (aperçu / téléchargement).

Un document a un `chemin` qui est soit :
  - local  : un chemin de fichier accessible par le backend (ex. /app/documents/…)
  - SMB    : `smb://hote/partage/sous/dossier/fichier.ext`

`resolve_to_local()` rend un chemin local lisible + un booléen `temporaire`
(vrai = fichier temp à supprimer après envoi, cas SMB).
"""

import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.document import Document
from models.source import USAGE_GED, Source
from services import crypto, smb_chemins, smb_service

log = get_logger(__name__)


def _parse_smb(chemin: str) -> tuple[str, str, str]:
    """`smb://hote/partage/sous/fichier` → (hote, partage, '/sous/fichier').
    Comportement historique conservé (cf. `smb_chemins.ancien_acces`)."""
    return smb_chemins.ancien_acces(chemin)


async def _source_smb(db: AsyncSession, hote: str) -> Source | None:
    """Retrouve une source SMB configurée pour cet hôte (pour les identifiants).

    Plusieurs sources peuvent viser le même hôte (14/11/2026 : la source du Rangement, compte
    `svc-rangement`, à côté de celle de la GED). Sans ordre, la base pouvait rendre l'une ou l'autre et
    la GED lire avec le mauvais compte (le partage `home` n'est pas le même pour deux comptes). Ordre
    fixe : la plus ANCIENNE d'abord — celle avec laquelle les documents ont été indexés."""
    rows = (await db.execute(
        select(Source).where(Source.type == "smb", Source.hote == hote, Source.usage == USAGE_GED).order_by(Source.created_at, Source.id)
    )).scalars().all()
    # Priorité à une source qui porte un secret (sinon la première trouvée)
    return next((s for s in rows if s.secret_chiffre), rows[0] if rows else None)


async def resolve_to_local(doc: Document, db: AsyncSession) -> tuple[str, bool]:
    """
    Retourne (chemin_local_lisible, temporaire).
    Lève FileNotFoundError si introuvable, ValueError si chemin non géré.
    """
    chemin = doc.chemin or ""

    if chemin.startswith("smb://"):
        hote, partage, rel = _parse_smb(chemin)
        src = await _source_smb(db, hote)
        ident = src.identifiant if src else None
        secret = crypto.decrypt(src.secret_chiffre) if src and src.secret_chiffre else None
        domaine = src.domaine if src else None
        try:
            tmp = await smb_service.fetch_to_temp(hote, partage, rel, ident, secret, domaine)
        except Exception as exc:
            raise FileNotFoundError(f"Lecture SMB impossible : {exc}") from exc
        return tmp, True

    # Chemin local
    p = Path(chemin)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")
    return str(p), False


def chemin_affichage(chemin: str) -> str:
    """
    Forme « copiable dans l'explorateur » :
      smb://hote/partage/sous → \\hote\partage\sous (UNC Windows)
      local → tel quel
    """
    if chemin.startswith("smb://"):
        unc = chemin[len("smb://"):].replace("/", "\\")
        return "\\\\" + unc
    return chemin
