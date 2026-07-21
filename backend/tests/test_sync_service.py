"""
Tests du diff de synchronisation incrémentale (`services.sync_service.diff`).

`diff` est une fonction PURE : aucune I/O, donc entièrement testable. C'est elle qui décide
si un document est ré-extrait, déplacé ou marqué absent — une erreur ici abîme l'index.
"""

from datetime import datetime, timedelta, timezone

import pytest

from services.sync_service import _apparier_deplaces, _like_prefixe, diff


def _idx(chemin, taille, *, mtime=None, importe=None, statut="enriched", doc_id=None):
    """Entrée d'index. Par défaut, mtime ≈ date d'import → date jugée non exploitable."""
    base = importe or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {"id": doc_id or chemin, "chemin": chemin, "taille": taille,
            "mtime": mtime if mtime is not None else base, "import": base, "statut": statut}


def _dist(chemin, taille, mtime=None):
    return {"chemin": chemin, "rel": chemin, "taille": taille, "mtime": mtime}


def test_fichier_inchange_nest_pas_retraite():
    d = {"/a.pdf": _dist("/a.pdf", 100)}
    i = {"/a.pdf": _idx("/a.pdf", 100)}
    r = diff(d, i)
    assert r["inchanges"] == 1
    assert not r["nouveaux"] and not r["modifies"] and not r["absents"]


def test_nouveau_fichier_detecte():
    r = diff({"/neuf.pdf": _dist("/neuf.pdf", 10)}, {})
    assert [n["chemin"] for n in r["nouveaux"]] == ["/neuf.pdf"]


def test_taille_differente_marque_modifie():
    r = diff({"/a.pdf": _dist("/a.pdf", 200)}, {"/a.pdf": _idx("/a.pdf", 100)})
    assert [m["chemin"] for m in r["modifies"]] == ["/a.pdf"]


def test_fichier_disparu_marque_absent_jamais_supprime():
    r = diff({}, {"/parti.pdf": _idx("/parti.pdf", 10)})
    assert [a["chemin"] for a in r["absents"]] == ["/parti.pdf"]


def test_deplacement_reconnu_ni_nouveau_ni_absent():
    """Même nom + même taille ailleurs → un seul UPDATE, aucun transfert, aucun doublon."""
    d = {"/dossier2/a.pdf": _dist("/dossier2/a.pdf", 100)}
    i = {"/dossier1/a.pdf": _idx("/dossier1/a.pdf", 100)}
    r = diff(d, i)
    assert len(r["deplaces"]) == 1
    ancien, nouveau = r["deplaces"][0]
    assert ancien["chemin"] == "/dossier1/a.pdf"
    assert nouveau["chemin"] == "/dossier2/a.pdf"
    assert not r["nouveaux"] and not r["absents"]  # ne doit PAS être compté deux fois


def test_homonymes_de_meme_taille_ne_sont_jamais_apparies():
    """Appariement ambigu → on préfère un couple (nouveau + absent) à un mauvais rapprochement."""
    nouveaux = [_dist("/x/a.pdf", 100), _dist("/y/a.pdf", 100)]
    absents = [_idx("/z/a.pdf", 100)]
    assert _apparier_deplaces(nouveaux, absents) == []


def test_date_de_modification_ignoree_si_artefact_du_temporaire():
    """
    Anciennes indexations SMB : la date stockée est celle du fichier temporaire (≈ date d'import).
    Elle ne doit pas déclencher une ré-extraction de tout le corpus au premier passage.
    """
    imp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    i = {"/a.pdf": _idx("/a.pdf", 100, mtime=imp + timedelta(seconds=2), importe=imp)}
    d = {"/a.pdf": _dist("/a.pdf", 100, mtime=datetime(2020, 5, 5, tzinfo=timezone.utc).timestamp())}
    assert diff(d, i)["inchanges"] == 1


def test_date_de_modification_exploitee_quand_elle_est_fiable():
    """Date réelle du NAS (éloignée de l'import) et postérieure → contenu modifié."""
    imp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    vraie = datetime(2025, 6, 1, tzinfo=timezone.utc)
    i = {"/a.pdf": _idx("/a.pdf", 100, mtime=vraie, importe=imp)}
    d = {"/a.pdf": _dist("/a.pdf", 100, mtime=(vraie + timedelta(days=3)).timestamp())}
    assert [m["chemin"] for m in diff(d, i)["modifies"]] == ["/a.pdf"]


def test_tolerance_sur_la_granularite_des_horloges():
    """2 s d'écart = arrondi de système de fichiers, pas une modification."""
    imp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    vraie = datetime(2025, 6, 1, tzinfo=timezone.utc)
    i = {"/a.pdf": _idx("/a.pdf", 100, mtime=vraie, importe=imp)}
    d = {"/a.pdf": _dist("/a.pdf", 100, mtime=(vraie + timedelta(seconds=2)).timestamp())}
    assert diff(d, i)["inchanges"] == 1


def test_document_revenu_est_reactive_sans_retraitement():
    i = {"/a.pdf": _idx("/a.pdf", 100, statut="absent")}
    r = diff({"/a.pdf": _dist("/a.pdf", 100)}, i)
    assert [x["chemin"] for x in r["revenus"]] == ["/a.pdf"]
    assert not r["modifies"]  # réactivation seule : ni téléchargement ni ré-extraction


def test_absent_deja_marque_nest_pas_remarque():
    r = diff({}, {"/parti.pdf": _idx("/parti.pdf", 10, statut="absent")})
    assert r["absents"] == []


@pytest.mark.parametrize("prefixe,attendu", [
    ("/mnt/01_bebe/", "/mnt/01\\_bebe/%"),
    ("/mnt/100%/", "/mnt/100\\%/%"),
])
def test_jokers_sql_echappes_dans_le_prefixe(prefixe, attendu):
    """`_` et `%` sont courants dans les noms de dossiers : non échappés, le LIKE déborderait
    sur les dossiers voisins, qui seraient alors vus comme « absents »."""
    assert _like_prefixe(prefixe) == attendu
