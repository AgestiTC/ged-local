"""
Copies sur disque par SMB (étape 5 du plan Rangement sur Sources SMB, 14/11/2026).

Un faux NAS en mémoire (aucun réseau), rempli des MÊMES fichiers que le jeu des copies sur disque
(`test_inventaire_copies`) : la passe doit trouver les mêmes groupes, avec les mêmes empreintes au
bit près (un fichier du NAS et sa copie sur un disque se retrouvent ensemble), et lire autant d'octets.
Puis la prudence : un fichier modifié avant ou PENDANT la lecture est écarté, un fichier refusé est
compté sans arrêter la passe, un NAS éteint ou coupé n'enregistre rien et n'est pas martelé.
Données fictives.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fakes.depot_memoire import DepotMemoire
from smb.base import NotConnectedError
from test_scan_smb import ConnexionNas, NasFictif

from services import duplicate_service
from services.rangement import copies, emplacement_smb
from services.rangement.exclusions import Exclusions
from services.rangement.reglages import ReglagesInventaire
from services.rangement.scan import Scanner
from services.rangement.source_smb import SourceSmb
from services.smb_session import SessionSmb

MO = 1024 * 1024
NUIT = datetime(2099, 10, 14, 2, tzinfo=timezone.utc)
HOTE = "192.0.2.50"

VIDEO = bytes((i * 13) % 251 for i in range(2 * MO))
_m = bytearray(VIDEO)
_m[MO] ^= 0xFF
PRESQUE = bytes(_m)   # même taille, même début, même fin : seule la 3ᵉ passe la départage

#: Le jeu de `test_inventaire_copies`, en deux dossiers (deux emplacements).
JEU = {
    "A": {"Films/film.mkv": VIDEO, "Films/presque.mkv": PRESQUE, "petit.txt": b"petit"},
    "B": {"Sauvegarde/film (copie).mkv": VIDEO},
}


def _ecrire(racine: Path, fichiers: dict[str, bytes]) -> None:
    for rel, contenu in fichiers.items():
        p = racine / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(contenu)


def _arbre(jeu) -> dict[str, bytes | None]:
    arbre: dict[str, bytes | None] = {}
    for dossier, fichiers in jeu.items():
        for rel, contenu in fichiers.items():
            parties = f"{dossier}/{rel}".split("/")
            for i in range(1, len(parties)):
                arbre.setdefault("/" + "/".join(parties[:i]), None)
            arbre["/" + "/".join(parties)] = contenu
    return arbre


class NasCompte(NasFictif):
    """Compte les tentatives de connexion, même celles qui échouent (NAS éteint)."""

    def __init__(self, arbre):
        super().__init__(arbre)
        self.tentatives = 0

    def connecter(self):
        self.tentatives += 1
        return super().connecter()


def _session_vers(nas):
    async def session(_emp, ouvrir=None):
        return SessionSmb(HOTE, "homes", "svc", "fictif", connecter=nas.connecter)
    return session


async def _emplacement_smb(depot, nas, dossier: str, exclusions=Exclusions()):
    emp = await depot.creer_emplacement(dossier, f"smb://{HOTE}/homes/{dossier}", source="smb",
                                        source_id="src-fictive", partage="homes", sous_dossier=f"/{dossier}")
    source = SourceSmb(SessionSmb(HOTE, "homes", "svc", "fictif", connecter=nas.connecter), emp, exclusions)
    assert (await Scanner(depot, emp, exclusions, source=source).executer()).statut == "termine"
    return emp


async def _passe(depot, *, limite=200 * MO, exclusions=Exclusions()):
    return await copies.executer(depot, ReglagesInventaire(exclusions=exclusions), taille_min=MO,
                                 limite_nuit=limite, horloge=lambda: NUIT, a_la_demande=True)


async def _groupes(depot):
    emplacements = await depot.emplacements()
    noms = {e.id: e.libelle for e in emplacements}
    return {(g.empreinte, frozenset((noms[c.emplacement_id], c.chemin) for c in g.copies))
            for g in await depot.groupes_identiques([e.id for e in emplacements], 10)}


async def _nas_scanne(monkeypatch, jeu=JEU, classe=NasFictif):
    nas = classe(_arbre(jeu))
    monkeypatch.setattr(emplacement_smb, "session_de", _session_vers(nas))
    depot = DepotMemoire()
    for dossier in jeu:
        await _emplacement_smb(depot, nas, dossier)
    return nas, depot


# --------------------------------------------------------------------------- #
# Mêmes copies qu'en local                                                     #
# --------------------------------------------------------------------------- #
async def test_memes_groupes_memes_empreintes_memes_octets_qu_en_local(tmp_path, monkeypatch):
    local = DepotMemoire()
    for dossier, fichiers in JEU.items():
        _ecrire(tmp_path / dossier, fichiers)
        emp = await local.creer_emplacement(dossier, str(tmp_path / dossier))
        await Scanner(local, emp, Exclusions()).executer()
    r_local = await _passe(local)

    nas, smb = await _nas_scanne(monkeypatch)
    connexions_du_scan = nas.connexions
    r_smb = await _passe(smb)

    assert r_smb["statut"] == r_local["statut"] == "termine"
    assert (r_smb["partielles"], r_smb["completes"]) == (r_local["partielles"], r_local["completes"]) == (3, 3)
    assert r_smb["octets_lus"] == r_local["octets_lus"]
    assert await _groupes(smb) == await _groupes(local)     # empreintes comprises, au bit près
    assert len(await _groupes(smb)) == 1                    # « presque.mkv » n'est pas une copie
    # UNE session par emplacement pour toute la passe, refermée à la fin.
    assert nas.connexions - connexions_du_scan == 2
    assert nas.fermetures == nas.connexions


async def test_une_copie_entre_le_nas_et_un_disque(tmp_path, monkeypatch):
    nas, depot = await _nas_scanne(monkeypatch, {"B": JEU["B"]})
    _ecrire(tmp_path / "disque", {"film.mkv": VIDEO})
    emp = await depot.creer_emplacement("Disque", str(tmp_path / "disque"))
    await Scanner(depot, emp, Exclusions()).executer()
    await _passe(depot)
    (groupe,) = await _groupes(depot)
    assert groupe[1] == {("Disque", "film.mkv"), ("B", "Sauvegarde/film (copie).mkv")}


async def test_une_empreinte_n_est_jamais_relue(monkeypatch):
    nas, depot = await _nas_scanne(monkeypatch)
    await _passe(depot)
    nas.appels.clear()
    r = await _passe(depot)
    assert r["octets_lus"] == 0 and "retrieveFileFromOffset" not in nas.appels


# --------------------------------------------------------------------------- #
# Prudence                                                                     #
# --------------------------------------------------------------------------- #
async def test_fichier_modifie_depuis_le_scan_pas_lu(monkeypatch):
    nas, depot = await _nas_scanne(monkeypatch)
    nas.arbre["/A/Films/film.mkv"] = VIDEO + b"!"      # a grossi depuis le scan
    r = await _passe(depot)
    assert "modifié" in r["message"]
    assert await _groupes(depot) == set()


async def test_fichier_modifie_pendant_la_lecture_ecarte(monkeypatch):
    nas, depot = await _nas_scanne(monkeypatch)
    lire = ConnexionNas.retrieveFileFromOffset

    def lire_puis_modifier(self, partage, chemin, fh, offset=0, max_length=-1, **kw):
        sortie = lire(self, partage, chemin, fh, offset, max_length, **kw)
        if chemin == "/B/Sauvegarde/film (copie).mkv":
            self.srv.arbre[chemin] = VIDEO + b"!"          # quelqu'un écrit pendant qu'on lit
        return sortie

    monkeypatch.setattr(ConnexionNas, "retrieveFileFromOffset", lire_puis_modifier)
    r = await _passe(depot)
    assert "1 modifié" in r["message"]
    assert await _groupes(depot) == set()


async def test_fichier_refuse_compte_et_la_passe_continue(monkeypatch):
    nas, depot = await _nas_scanne(monkeypatch, {**JEU, "C": {"film (2).mkv": VIDEO}})
    del nas.arbre["/A/Films/film.mkv"]                     # retiré (ou droit retiré) depuis le scan
    r = await _passe(depot)
    assert r["statut"] == "termine" and "1 fichier(s) illisible(s)" in r["message"]
    (groupe,) = await _groupes(depot)
    assert groupe[1] == {("B", "Sauvegarde/film (copie).mkv"), ("C", "film (2).mkv")}


async def test_nas_eteint_rien_d_enregistre_et_pas_martele(tmp_path, monkeypatch):
    nas, depot = await _nas_scanne(monkeypatch, {"A": JEU["A"]}, classe=NasCompte)
    # Le disque, lui, reste lu : une copie locale est trouvée malgré le NAS absent.
    _ecrire(tmp_path / "d1", {"presque.mkv": PRESQUE})
    _ecrire(tmp_path / "d2", {"presque (copie).mkv": PRESQUE})
    for d in ("d1", "d2"):
        emp = await depot.creer_emplacement(d, str(tmp_path / d))
        await Scanner(depot, emp, Exclusions()).executer()
    nas.eteint = True
    avant = nas.tentatives
    r = await _passe(depot)
    assert r["statut"] == "termine" and "illisible" in r["message"]
    assert nas.tentatives - avant == 1                     # une tentative pour tout l'emplacement
    assert {frozenset(nom for nom, _ in g[1]) for g in await _groupes(depot)} == {frozenset({"d1", "d2"})}
    assert all(f.get("emp_partielle") is None for f in depot.entrees.values()
               if f["emplacement_id"] == 1 and not f["est_dossier"])


async def test_nas_coupe_pendant_la_passe(monkeypatch):
    nas, depot = await _nas_scanne(monkeypatch)
    lire = ConnexionNas.retrieveFileFromOffset
    lectures = 0

    def lire_puis_couper(self, *a, **kw):
        nonlocal lectures
        lectures += 1
        if lectures == 2:
            self.srv.eteint = True                         # la reconnexion échouera aussi
        if self.srv.eteint:
            raise NotConnectedError("coupure")
        return lire(self, *a, **kw)

    monkeypatch.setattr(ConnexionNas, "retrieveFileFromOffset", lire_puis_couper)
    r = await _passe(depot)
    assert r["statut"] == "termine" and "illisible" in r["message"]
    assert await _groupes(depot) == set()
    assert lectures == 2          # après la coupure, plus aucune lecture n'est tentée sur ce partage


# --------------------------------------------------------------------------- #
# Réglages communs : exclusions et limite de la nuit                           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("motifs,chemins", [("Sauvegarde", ""), ("", f"smb://{HOTE}/homes/B/Sauvegarde")])
async def test_exclusion_ajoutee_apres_le_scan_respectee(monkeypatch, motifs, chemins):
    _, depot = await _nas_scanne(monkeypatch)
    r = await _passe(depot, exclusions=Exclusions.depuis_reglages(motifs, chemins))
    assert r["statut"] == "termine" and await _groupes(depot) == set()


async def test_la_limite_de_la_nuit_compte_les_octets_smb(monkeypatch):
    _, depot = await _nas_scanne(monkeypatch)
    r = await _passe(depot, limite=300 * 1024)
    assert r["statut"] == "limite" and 0 < r["octets_lus"] <= 300 * 1024


# --------------------------------------------------------------------------- #
# Affichage                                                                    #
# --------------------------------------------------------------------------- #
async def test_la_facade_montre_le_chemin_smb(monkeypatch):
    _, depot = await _nas_scanne(monkeypatch)
    await _passe(depot)
    (groupe,) = (await duplicate_service.copies_sur_disque(depot))["groupes"]
    assert {f["chemin"] for f in groupe["fichiers"]} == {
        f"smb://{HOTE}/homes/A/Films/film.mkv", f"smb://{HOTE}/homes/B/Sauvegarde/film (copie).mkv"}
    assert all(f["sur_serveur"] for f in groupe["fichiers"])
