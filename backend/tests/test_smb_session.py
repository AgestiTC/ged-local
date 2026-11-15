"""
Session SMB qui dure toute une tâche (étape 2 du plan Rangement sur Sources SMB, 14/11/2026).

Faux serveur en mémoire (aucun réseau) : on vérifie qu'une session ne se reconnecte PAS à chaque
dossier, qu'une coupure en lecture est rattrapée une fois, qu'une écriture n'est JAMAIS rejouée
(elle a pu aboutir), et que le secret n'apparaît nulle part. Données fictives.
"""

import pytest
from smb.base import NotConnectedError
from smb.smb_structs import OperationFailure

from services.smb_session import EntreeSmb, SessionSmb


class FauxFichier:
    def __init__(self, nom, dossier, taille=0, mtime=0.0):
        self.filename, self.isDirectory, self.file_size, self.last_write_time = nom, dossier, taille, mtime


class FauxServeur:
    """Un partage : chemins « /a/b » → contenu (bytes) ou None pour un dossier."""

    def __init__(self, arbre):
        self.arbre = dict(arbre)
        self.arbre.setdefault("/", None)
        self.connexions = 0
        self.couper_au_prochain = False
        self.appels = []

    def connecter(self):
        self.connexions += 1
        return FausseConnexion(self)


class FausseConnexion:
    def __init__(self, srv):
        self.srv, self.ouverte = srv, True

    def _verifier(self, nom):
        self.srv.appels.append(nom)
        if not self.ouverte:
            raise NotConnectedError("fermée")
        if self.srv.couper_au_prochain:
            self.srv.couper_au_prochain = False
            self.ouverte = False
            raise NotConnectedError("coupure")

    def listPath(self, partage, chemin, **_):
        self._verifier("listPath")
        if self.srv.arbre.get(chemin, b"") is not None:
            raise OperationFailure("absent", [])
        base = chemin.rstrip("/")
        sortie = [FauxFichier(".", True), FauxFichier("..", True)]
        for p, v in self.srv.arbre.items():
            if p != "/" and p.rsplit("/", 1)[0] == base:
                sortie.append(FauxFichier(p.rsplit("/", 1)[1], v is None, len(v or b""), 1_700_000_000.0))
        return sortie

    def getAttributes(self, partage, chemin, **_):
        self._verifier("getAttributes")
        if chemin not in self.srv.arbre:
            raise OperationFailure("absent", [])
        v = self.srv.arbre[chemin]
        return FauxFichier(chemin.rsplit("/", 1)[-1] or "/", v is None, len(v or b""), 1_700_000_000.0)

    def retrieveFileFromOffset(self, partage, chemin, fh, offset=0, max_length=-1, **_):
        self._verifier("retrieveFileFromOffset")
        data = self.srv.arbre[chemin]
        morceau = data[offset:] if max_length < 0 else data[offset:offset + max_length]
        fh.write(morceau)
        return 0, len(morceau)

    def rename(self, partage, src, dst, **_):
        self._verifier("rename")
        if dst in self.srv.arbre:
            raise OperationFailure("existe", [])
        for p in [p for p in self.srv.arbre if p == src or p.startswith(src + "/")]:
            self.srv.arbre[dst + p[len(src):]] = self.srv.arbre.pop(p)

    def createDirectory(self, partage, chemin, **_):
        self._verifier("createDirectory")
        if chemin in self.srv.arbre:
            raise OperationFailure("existe", [])
        self.srv.arbre[chemin] = None

    def deleteDirectory(self, partage, chemin, **_):
        self._verifier("deleteDirectory")
        if self.srv.arbre.get(chemin, b"") is not None:
            raise OperationFailure("absent", [])
        if any(p.startswith(chemin + "/") for p in self.srv.arbre):
            raise OperationFailure("pas vide", [])     # comme le NAS : jamais un dossier plein
        del self.srv.arbre[chemin]

    def deleteFiles(self, partage, chemin, **_):
        self._verifier("deleteFiles")
        if self.srv.arbre.get(chemin) is None:
            raise OperationFailure("absent", [])
        del self.srv.arbre[chemin]

    def close(self):
        self.ouverte = False


ARBRE = {
    "/Films": None,
    "/Films/2026": None,
    "/Films/2026/a.mkv": b"0123456789",
    "/Films/b.mkv": b"abc",
    "/Series": None,
}


def _session(srv):
    return SessionSmb("nas", "media", "svc", "s3cr3t-fictif", connecter=srv.connecter)


async def test_une_seule_connexion_pour_tout_un_parcours():
    srv = FauxServeur(ARBRE)
    async with _session(srv) as s:
        vus, pile = [], ["/"]
        while pile:
            d = pile.pop()
            for e in await s.lister(d):
                chemin = f"{d.rstrip('/')}/{e.nom}"
                vus.append(chemin)
                if e.est_dossier:
                    pile.append(chemin)
    assert sorted(vus) == sorted(p for p in ARBRE)
    assert srv.connexions == 1


async def test_lister_rend_nom_type_taille_date():
    srv = FauxServeur(ARBRE)
    async with _session(srv) as s:
        entrees = {e.nom: e for e in await s.lister("Films")}
    assert set(entrees) == {"2026", "b.mkv"}  # « . » et « .. » écartés
    assert entrees["b.mkv"] == EntreeSmb("b.mkv", False, 3, 1_700_000_000.0)
    assert entrees["2026"].est_dossier


async def test_stat_et_existe():
    srv = FauxServeur(ARBRE)
    async with _session(srv) as s:
        assert (await s.stat("/Films/b.mkv")).taille == 3
        assert await s.stat("/Films/absent.mkv") is None
        assert await s.existe("/Series") and not await s.existe("/Nope")


async def test_lire_par_morceaux():
    srv = FauxServeur(ARBRE)
    async with _session(srv) as s:
        assert await s.lire("/Films/2026/a.mkv", 0, 4) == b"0123"
        assert await s.lire("/Films/2026/a.mkv", 7, 64) == b"789"
    assert srv.connexions == 1


async def test_une_coupure_en_lecture_est_rattrapee_une_fois():
    srv = FauxServeur(ARBRE)
    async with _session(srv) as s:
        await s.lister("/")
        srv.couper_au_prochain = True
        assert {e.nom for e in await s.lister("/")} == {"Films", "Series"}
    assert srv.connexions == 2


async def test_une_ecriture_coupee_n_est_pas_rejouee():
    srv = FauxServeur(ARBRE)
    async with _session(srv) as s:
        srv.couper_au_prochain = True
        with pytest.raises(NotConnectedError):
            await s.renommer("/Films/b.mkv", "/Series/b.mkv")
        assert srv.appels.count("rename") == 1
        # la session se reconnecte pour l'appel suivant
        assert await s.existe("/Films/b.mkv")
    assert srv.connexions == 2


async def test_renommer_et_creer_dossier_avec_parents():
    srv = FauxServeur(ARBRE)
    async with _session(srv) as s:
        await s.creer_dossier("/Archives/2026/Q4")
        await s.creer_dossier("/Archives/2026/Q4")  # idempotent
        await s.renommer("/Films/b.mkv", "/Archives/2026/Q4/b.mkv")
    assert srv.arbre["/Archives"] is None and srv.arbre["/Archives/2026/Q4"] is None
    assert srv.arbre["/Archives/2026/Q4/b.mkv"] == b"abc" and "/Films/b.mkv" not in srv.arbre


async def test_la_remontee_de_dossier_est_refusee():
    srv = FauxServeur(ARBRE)
    async with _session(srv) as s:
        with pytest.raises(ValueError):
            await s.renommer("/Films/b.mkv", "/../autre/b.mkv")
        with pytest.raises(ValueError):
            await s.lister("/Films/../../x")
    assert "rename" not in srv.appels


async def test_hors_session_ouverte_refus_clair():
    s = _session(FauxServeur(ARBRE))
    with pytest.raises(RuntimeError):
        await s.lister("/")


def test_le_secret_n_apparait_pas():
    s = _session(FauxServeur(ARBRE))
    assert "s3cr3t" not in repr(s) and "s3cr3t" not in str(s)
