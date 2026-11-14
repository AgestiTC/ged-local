"""
Deux sources SMB sur le même hôte (14/11/2026) : la GED (compte de Tom) et le Rangement (compte
`svc-rangement`). Pour lire un document `smb://hôte/…`, le code retrouve la source par l'hôte : il doit
toujours prendre la PLUS ANCIENNE (celle qui a indexé les documents), quel que soit l'ordre d'insertion.
Sans ordre, la base rendait l'une ou l'autre, et la GED pouvait lire avec le mauvais compte.
Données fictives.
"""

from datetime import datetime, timedelta, timezone

from models.source import Source
from services import crypto, file_access, scan_service

HOTE = "192.0.2.10"


async def _deux_sources(db):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # La plus récente est insérée EN PREMIER : l'ordre d'insertion ne doit rien décider.
    db.add(Source(libelle="Rangement", type="smb", hote=HOTE, identifiant="svc-rangement",
                  secret_chiffre=crypto.encrypt("b"), created_at=t0 + timedelta(days=300)))
    db.add(Source(libelle="GED", type="smb", hote=HOTE, identifiant="tom",
                  secret_chiffre=crypto.encrypt("a"), created_at=t0))
    await db.commit()


async def test_la_source_la_plus_ancienne_est_choisie(db_session):
    await _deux_sources(db_session)
    src = await file_access._source_smb(db_session, HOTE)
    assert src is not None and src.identifiant == "tom"
    ident, secret, _ = await scan_service.creds_smb(db_session, HOTE)
    assert (ident, secret) == ("tom", "a")
