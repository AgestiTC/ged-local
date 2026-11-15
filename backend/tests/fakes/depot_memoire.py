"""
Dépôt de l'inventaire EN MÉMOIRE — mêmes règles que `DepotPostgres`, sans base.

Les tables `inv_*` n'existent pas sous SQLite (cf. `models/inventaire.py`) : c'est ce double qui
porte les tests du scan, de la carte et des copies. Il compte chaque écriture d'entrée, ce qui
permet de vérifier qu'un rescan sans changement n'écrit rien. `tests/test_inventaire_depot.py`
le fait passer par le même contrat que le dépôt PostgreSQL : s'ils divergent, ça se voit.

Porté de l'application « rangement » (`app/inventaire/depot_memoire.py`). Jamais utilisé en
production.
"""

import uuid
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any

from services.rangement.depot import (
    Bilan,
    Compteurs,
    Connu,
    Copie,
    DossierEnvoye,
    DoublonRacine,
    Element,
    Emplacement,
    EnvoiEnCours,
    Fichier,
    Groupe,
    LigneInstantane,
    PasseEnCours,
    Poste,
    PosteEnDouble,
    RecuperableLieu,
    ResumePasse,
    ScanEnCours,
    chemin_enfant,
    extension,
)


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _totaux(e: dict[str, Any]) -> tuple[int, int, int] | None:
    if e.get("taille_totale") is None:
        return None
    return e["taille_totale"], e["nb_fichiers_total"], e["nb_dossiers_total"]


class DepotMemoire:
    def __init__(self) -> None:
        self._emplacements: dict[int, Emplacement] = {}
        self.scans: dict[int, dict[str, Any]] = {}
        self.entrees: dict[tuple[int, str], dict[str, Any]] = {}
        self.instantanes: list[dict[str, Any]] = []
        self.passes: dict[int, dict[str, Any]] = {}
        self._postes: dict[int, Poste] = {}
        self.envois: dict[int, dict[str, Any]] = {}
        self.envoi_dossiers: dict[tuple[int, str], DossierEnvoye] = {}
        #: Nombre de lignes d'entrées écrites (ajout, modification, disparition, totaux).
        self.ecritures_entrees = 0

    # ----------------------------------------------------------------- emplacements
    async def emplacements(self, actifs_seulement: bool = False) -> list[Emplacement]:
        return [e for e in sorted(self._emplacements.values(), key=lambda e: e.id)
                if e.actif or not actifs_seulement]

    async def emplacement(self, emplacement_id: int) -> Emplacement | None:
        return self._emplacements.get(emplacement_id)

    async def creer_emplacement(self, libelle: str, racine: str, source: str = "serveur",
                                poste_id: int | None = None, *, source_id: str | None = None,
                                partage: str | None = None, sous_dossier: str | None = None) -> Emplacement:
        cle = (source, poste_id, racine)
        if any((e.source, e.poste_id, e.racine) == cle for e in self._emplacements.values()):
            raise DoublonRacine(racine)
        emp = Emplacement(id=len(self._emplacements) + 1, libelle=libelle, racine=racine, source=source,
                          poste_id=poste_id, source_id=source_id, partage=partage, sous_dossier=sous_dossier)
        self._emplacements[emp.id] = emp
        return emp

    async def activer_emplacement(self, emplacement_id: int, actif: bool) -> None:
        if emplacement_id in self._emplacements:
            self._emplacements[emplacement_id] = replace(self._emplacements[emplacement_id], actif=actif)

    async def rebrancher_emplacement(self, emplacement_id: int, *, racine: str, source: str,
                                     source_id: str | None, partage: str | None, sous_dossier: str | None,
                                     prefixe: str = "") -> tuple[int, int]:
        emp = self._emplacements[emplacement_id]
        if any(e.id != emplacement_id and (e.source, e.poste_id, e.racine) == (source, emp.poste_id, racine)
               for e in self._emplacements.values()):
            raise DoublonRacine(racine)
        retirees = 0
        if prefixe:
            sl, n = prefixe + "/", len(prefixe) + 1
            for (eid, chemin) in [k for k in self.entrees if k[0] == emplacement_id]:
                e = self.entrees.pop((eid, chemin))
                if not chemin.startswith(sl):
                    retirees += 1
                    continue
                e["chemin"] = chemin[n:]
                e["parent"] = "" if e["parent"] == prefixe else e["parent"][n:]
                self.entrees[(eid, e["chemin"])] = e
            scans = {s for s, v in self.scans.items() if v["emplacement_id"] == emplacement_id}
            gardes = []
            for li in self.instantanes:
                if li["scan_id"] in scans:
                    if li["chemin"] != prefixe and not li["chemin"].startswith(sl):
                        continue
                    li = {**li, "chemin": "" if li["chemin"] == prefixe else li["chemin"][n:],
                          "profondeur": li["profondeur"] - prefixe.count("/") - 1}
                gardes.append(li)
            self.instantanes = gardes
        self._emplacements[emplacement_id] = replace(emp, racine=racine, source=source, source_id=source_id,
                                                     partage=partage, sous_dossier=sous_dossier)
        return sum(1 for k in self.entrees if k[0] == emplacement_id), retirees

    # ----------------------------------------------------------------------- scans
    async def ouvrir_scan(self, emplacement_id: int, declencheur: str) -> int:
        if any(s["emplacement_id"] == emplacement_id and s["statut"] == "en_cours"
               for s in self.scans.values()):
            raise ScanEnCours(emplacement_id)
        sid = len(self.scans) + 1
        self.scans[sid] = {"id": sid, "emplacement_id": emplacement_id, "declencheur": declencheur,
                           "debut": _maintenant(), "fin": None, "statut": "en_cours", "message": "",
                           **asdict(Compteurs())}
        return sid

    async def fermer_scan(self, scan_id: int, statut: str, compteurs: Compteurs, message: str = "") -> None:
        self.scans[scan_id].update(statut=statut, fin=_maintenant(), message=message, **asdict(compteurs))

    async def interrompre_scans_orphelins(self, age_heures: int) -> int:
        limite = _maintenant() - timedelta(hours=age_heures)
        orphelins = [s for s in self.scans.values() if s["statut"] == "en_cours" and s["debut"] < limite]
        for s in orphelins:
            s.update(statut="interrompu", fin=_maintenant(), message="scan resté « en cours » : interrompu")
        return len(orphelins)

    async def dernier_scan(self, emplacement_id: int, termine_seulement: bool = False) -> dict[str, Any] | None:
        candidats = [s for s in self.scans.values() if s["emplacement_id"] == emplacement_id
                     and (s["statut"] == "termine" or not termine_seulement)]
        return dict(max(candidats, key=lambda s: s["id"])) if candidats else None

    async def scan_en_cours(self) -> bool:
        return any(s["statut"] == "en_cours" for s in self.scans.values())

    # --------------------------------------------------------------------- entrées
    def entree(self, emplacement_id: int, chemin: str) -> dict[str, Any]:
        """Accès direct pour les tests (pas dans le contrat)."""
        return self.entrees[(emplacement_id, chemin)]

    async def a_des_entrees(self, emplacement_id: int) -> bool:
        return any(e["disparu_scan_id"] is None
                   for (eid, _), e in self.entrees.items() if eid == emplacement_id)

    async def enfants(self, emplacement_id: int, parent: str) -> dict[str, Connu]:
        return {e["nom"]: self._connu(e)
                for (eid, _), e in self.entrees.items()
                if eid == emplacement_id and e["parent"] == parent and e["disparu_scan_id"] is None}

    async def ajouter(self, emplacement_id: int, scan_id: int, parent: str, elements: list[Element]) -> None:
        for el in elements:
            cle = (emplacement_id, chemin_enfant(parent, el.nom))
            existant = self.entrees.get(cle)
            if existant:  # réapparition : la ligne revit, son historique reste
                existant.update(est_dossier=el.est_dossier, taille=el.taille, mtime=el.mtime,
                                extension=extension(el), disparu_scan_id=None, modifie_scan_id=scan_id)
            else:
                self.entrees[cle] = {"id": len(self.entrees) + 1, "emplacement_id": emplacement_id,
                                     "chemin": cle[1], "parent": parent, "nom": el.nom,
                                     "est_dossier": el.est_dossier, "taille": el.taille, "mtime": el.mtime,
                                     "extension": extension(el),
                                     "apparu_scan_id": scan_id, "modifie_scan_id": None,
                                     "disparu_scan_id": None, "taille_totale": None,
                                     "nb_fichiers_total": None, "nb_dossiers_total": None,
                                     "emp_partielle": None, "emp_complete": None, "emp_taille": None,
                                     "emp_mtime": None}
        self.ecritures_entrees += len(elements)

    async def modifier(self, emplacement_id: int, scan_id: int, parent: str, elements: list[Element]) -> None:
        for el in elements:
            self.entrees[(emplacement_id, chemin_enfant(parent, el.nom))].update(
                est_dossier=el.est_dossier, taille=el.taille, mtime=el.mtime, extension=extension(el),
                modifie_scan_id=scan_id)
        self.ecritures_entrees += len(elements)

    async def marquer_disparus(self, emplacement_id: int, scan_id: int, parent: str, noms: list[str]) -> int:
        n = 0
        for nom in noms:
            cible = chemin_enfant(parent, nom)
            for (eid, chemin), e in self.entrees.items():
                if (eid == emplacement_id and e["disparu_scan_id"] is None
                        and (chemin == cible or chemin.startswith(cible + "/"))):
                    e["disparu_scan_id"] = scan_id
                    n += 1
        self.ecritures_entrees += n
        return n

    async def mettre_a_jour_totaux(self, emplacement_id: int, parent: str,
                                   totaux: list[tuple[str, int, int, int]]) -> None:
        for nom, taille, nb_fichiers, nb_dossiers in totaux:
            self.entrees[(emplacement_id, chemin_enfant(parent, nom))].update(
                taille_totale=taille, nb_fichiers_total=nb_fichiers, nb_dossiers_total=nb_dossiers)
        self.ecritures_entrees += len(totaux)

    # ------------------------------------------------------------------ instantanés
    async def enregistrer_instantane(self, scan_id: int, lignes: list[LigneInstantane]) -> None:
        self.instantanes.extend({"scan_id": scan_id, **asdict(ligne)} for ligne in lignes)

    def _scans_instantanes(self, emplacement_id: int) -> list[int]:
        ids = {li["scan_id"] for li in self.instantanes
               if self.scans[li["scan_id"]]["emplacement_id"] == emplacement_id}
        return sorted(ids, reverse=True)

    async def purger_instantanes(self, emplacement_id: int, garder: int) -> int:
        a_purger = set(self._scans_instantanes(emplacement_id)[garder:])
        avant = len(self.instantanes)
        self.instantanes = [li for li in self.instantanes if li["scan_id"] not in a_purger]
        return avant - len(self.instantanes)

    async def scans_avec_instantane(self, emplacement_id: int, n: int) -> list[int]:
        return self._scans_instantanes(emplacement_id)[:n]

    async def tailles_instantane(self, scan_id: int) -> dict[str, int]:
        return {li["chemin"]: li["taille_totale"] for li in self.instantanes if li["scan_id"] == scan_id}

    # ------------------------------------------------------------------ lecture carte
    def _presents(self, emplacement_id: int, prefixe: str) -> list[dict[str, Any]]:
        return [e for (eid, chemin), e in self.entrees.items()
                if eid == emplacement_id and e["disparu_scan_id"] is None
                and (prefixe == "" or chemin.startswith(prefixe + "/"))]

    @staticmethod
    def _connu(e: dict[str, Any]) -> Connu:
        return Connu(e["nom"], e["est_dossier"], e["taille"], e["mtime"], _totaux(e))

    async def dossier(self, emplacement_id: int, chemin: str) -> Connu | None:
        e = self.entrees.get((emplacement_id, chemin))
        if e is None or e["disparu_scan_id"] is not None or not e["est_dossier"]:
            return None
        return self._connu(e)

    async def enfants_tries(self, emplacement_id: int, parent: str, limite: int) -> tuple[list[Connu], int]:
        enfants = [self._connu(e) for (eid, _), e in self.entrees.items()
                   if eid == emplacement_id and e["parent"] == parent and e["disparu_scan_id"] is None]

        def cle(c: Connu) -> tuple[int, str]:
            taille = (c.totaux[0] if c.totaux else 0) if c.est_dossier else c.taille
            return -(taille or 0), c.nom

        enfants.sort(key=cle)
        return enfants[:limite], len(enfants)

    async def repartition_types(self, emplacement_id: int, prefixe: str) -> list[tuple[str | None, int, int]]:
        cumul: dict[str | None, list[int]] = {}
        for e in self._presents(emplacement_id, prefixe):
            if e["est_dossier"]:
                continue
            c = cumul.setdefault(e["extension"], [0, 0])
            c[0] += 1
            c[1] += e["taille"]
        return [(ext, nb, octets) for ext, (nb, octets) in cumul.items()]

    async def plus_gros_fichiers(self, emplacement_id: int, prefixe: str, limite: int) -> list[tuple[str, int]]:
        fichiers = [(e["chemin"], e["taille"]) for e in self._presents(emplacement_id, prefixe)
                    if not e["est_dossier"]]
        fichiers.sort(key=lambda f: (-f[1], f[0]))
        return fichiers[:limite]

    # ------------------------------------------------------------- copies sur disque
    @staticmethod
    def _en_fichier(e: dict[str, Any]) -> Fichier:
        return Fichier(e["id"], e["emplacement_id"], e["chemin"], e["taille"], e["mtime"],
                       e["emp_partielle"], e["emp_complete"], e["emp_taille"], e["emp_mtime"])

    def _fichiers(self, emplacements: list[int]) -> list[Fichier]:
        return [self._en_fichier(e) for e in self.entrees.values()
                if e["emplacement_id"] in emplacements and e["disparu_scan_id"] is None
                and not e["est_dossier"]]

    async def tailles_en_double(self, emplacements: list[int], taille_min: int, sous: int | None,
                                limite: int) -> list[int]:
        compte: dict[int, int] = {}
        for f in self._fichiers(emplacements):
            if f.taille >= taille_min and (sous is None or f.taille < sous):
                compte[f.taille] = compte.get(f.taille, 0) + 1
        return sorted((t for t, n in compte.items() if n >= 2), reverse=True)[:limite]

    async def fichiers_de_taille(self, emplacements: list[int], taille: int) -> list[Fichier]:
        return sorted((f for f in self._fichiers(emplacements) if f.taille == taille),
                      key=lambda f: (f.emplacement_id, f.chemin))

    async def fichier(self, entree_id: int) -> Fichier | None:
        for e in self.entrees.values():
            if e["id"] == entree_id and e["disparu_scan_id"] is None and not e["est_dossier"]:
                return self._en_fichier(e)
        return None

    async def enregistrer_empreinte(self, entree_id: int, partielle: bytes, complete: bytes | None,
                                    taille: int, mtime: float | None) -> None:
        for e in self.entrees.values():
            if e["id"] == entree_id:
                e.update(emp_partielle=partielle, emp_complete=complete, emp_taille=taille, emp_mtime=mtime)

    def _groupes(self, emplacements: list[int]) -> list[Groupe]:
        par_cle: dict[tuple[bytes, int], list[Fichier]] = {}
        for f in self._fichiers(emplacements):
            if f.complete is not None and f.complete_valide:
                par_cle.setdefault((f.complete, f.taille), []).append(f)
        groupes = [Groupe(emp, taille, tuple(Copie(f.emplacement_id, f.chemin)
                                             for f in sorted(fs, key=lambda f: (f.emplacement_id, f.chemin))))
                   for (emp, taille), fs in par_cle.items() if len(fs) >= 2]
        groupes.sort(key=lambda g: (-g.recuperable, -g.taille, min(c.chemin for c in g.copies)))
        return groupes

    async def groupes_identiques(self, emplacements: list[int], limite: int,
                                 emplacement_id: int | None = None) -> list[Groupe]:
        groupes = [g for g in self._groupes(emplacements)
                   if emplacement_id is None or any(c.emplacement_id == emplacement_id for c in g.copies)]
        return groupes[:limite]

    async def bilan_identiques(self, emplacements: list[int]) -> Bilan:
        groupes = self._groupes(emplacements)
        return Bilan(sum(g.recuperable for g in groupes), len(groupes),
                     sum(len(g.copies) - 1 for g in groupes))

    async def recuperable_par_emplacement(self, emplacements: list[int]) -> dict[int, RecuperableLieu]:
        cumul: dict[int, list[int]] = {}
        for g in self._groupes(emplacements):
            par_lieu: dict[int, int] = {}
            for c in g.copies:
                par_lieu[c.emplacement_id] = par_lieu.get(c.emplacement_id, 0) + 1
            for lieu, n in par_lieu.items():
                total = cumul.setdefault(lieu, [0, 0])
                total[0] += g.taille * (n - 1)
                if len(g.copies) > n:
                    total[1] += g.taille * n
        return {lieu: RecuperableLieu(i, a) for lieu, (i, a) in cumul.items()}

    async def empreintes_a_calculer(self, emplacement_id: int, emplacements: list[int], taille_min: int,
                                    limite: int) -> list[tuple[Fichier, str]]:
        tous = self._fichiers(emplacements)
        miens = sorted((f for f in tous if f.emplacement_id == emplacement_id and f.taille >= taille_min),
                       key=lambda f: (-f.taille, f.id))
        partielles = [(f, "partielle") for f in miens if not f.partielle_valide
                      and any(o.id != f.id and o.taille == f.taille for o in tous)]
        completes = [(f, "complete") for f in miens if f.partielle_valide and f.complete is None
                     and any(o.id != f.id and o.taille == f.taille and o.partielle_valide
                             and o.partielle == f.partielle for o in tous)]
        return (partielles[:limite] + completes[:limite])[:limite]

    async def ouvrir_passe(self) -> int:
        if any(p["statut"] == "en_cours" for p in self.passes.values()):
            raise PasseEnCours()
        pid = len(self.passes) + 1
        self.passes[pid] = {"id": pid, "debut": _maintenant(), "fin": None, "statut": "en_cours",
                            "message": "", **asdict(ResumePasse())}
        return pid

    async def avancer_passe(self, passe_id: int, octets_lus: int) -> None:
        self.passes[passe_id]["octets_lus"] = octets_lus

    async def fermer_passe(self, passe_id: int, statut: str, resume: ResumePasse, message: str = "") -> None:
        self.passes[passe_id].update(statut=statut, fin=_maintenant(), message=message, **asdict(resume))

    async def interrompre_passes_orphelines(self, age_heures: int) -> int:
        limite = _maintenant() - timedelta(hours=age_heures)
        orphelines = [p for p in self.passes.values() if p["statut"] == "en_cours" and p["debut"] < limite]
        for p in orphelines:
            p.update(statut="interrompu", fin=_maintenant(),
                     message="passe restée « en cours » : interrompue")
        return len(orphelines)

    async def octets_lus_depuis(self, moment: datetime) -> int:
        return sum(p["octets_lus"] for p in self.passes.values() if p["debut"] >= moment)

    async def derniere_passe(self) -> dict[str, Any] | None:
        return dict(self.passes[max(self.passes)]) if self.passes else None

    # ---------------------------------------------------------------- postes, envois
    def _jeton_pris(self, jeton_id: uuid.UUID | None, sauf: int | None = None) -> bool:
        return jeton_id is not None and any(p.jeton_id == jeton_id and p.id != sauf
                                            for p in self._postes.values())

    async def creer_poste(self, nom: str, jeton_id: uuid.UUID | None = None) -> Poste:
        if any(p.nom == nom for p in self._postes.values()) or self._jeton_pris(jeton_id):
            raise PosteEnDouble(nom)
        poste = Poste(len(self._postes) + 1, nom, jeton_id=jeton_id)
        self._postes[poste.id] = poste
        return poste

    async def postes(self) -> list[Poste]:
        return sorted(self._postes.values(), key=lambda p: p.nom)

    async def poste(self, poste_id: int) -> Poste | None:
        return self._postes.get(poste_id)

    async def poste_par_jeton(self, jeton_id: uuid.UUID) -> Poste | None:
        return next((p for p in self._postes.values() if p.jeton_id == jeton_id), None)

    async def contact_poste(self, poste_id: int, version: str) -> None:
        self._postes[poste_id] = replace(self._postes[poste_id], dernier_contact=_maintenant(),
                                         version=version[:40])

    async def activer_poste(self, poste_id: int, actif: bool) -> None:
        self._postes[poste_id] = replace(self._postes[poste_id], actif=actif)

    async def changer_jeton_poste(self, poste_id: int, jeton_id: uuid.UUID | None) -> None:
        if self._jeton_pris(jeton_id, sauf=poste_id):
            raise PosteEnDouble(str(poste_id))
        self._postes[poste_id] = replace(self._postes[poste_id], jeton_id=jeton_id)

    async def compter_lecture_poste(self, poste_id: int, jour: date, octets: int) -> None:
        p = self._postes[poste_id]
        cumul = p.lecture_octets + octets if p.lecture_jour == jour else octets
        self._postes[poste_id] = replace(p, lecture_jour=jour, lecture_octets=cumul)

    def _vider_envoi(self, envoi_id: int) -> None:
        for cle in [c for c in self.envoi_dossiers if c[0] == envoi_id]:
            del self.envoi_dossiers[cle]

    async def ouvrir_envoi(self, emplacement_id: int) -> int:
        # Comme en base : un envoi en traitement fait échouer TOUTE l'opération, rien n'est abandonné.
        if any(e["emplacement_id"] == emplacement_id and e["statut"] == "traitement"
               for e in self.envois.values()):
            raise EnvoiEnCours(emplacement_id)
        for e in self.envois.values():
            if e["emplacement_id"] == emplacement_id and e["statut"] == "reception":
                e.update(statut="abandonne", fin=_maintenant())
                self._vider_envoi(e["id"])
        eid = len(self.envois) + 1
        self.envois[eid] = {"id": eid, "emplacement_id": emplacement_id, "debut": _maintenant(), "fin": None,
                            "statut": "reception", "nb_dossiers": 0}
        return eid

    async def envoi(self, envoi_id: int) -> dict[str, Any] | None:
        e = self.envois.get(envoi_id)
        return dict(e) if e else None

    async def ajouter_dossiers_envoi(self, envoi_id: int, dossiers: list[DossierEnvoye]) -> None:
        for d in dossiers:
            cle = (envoi_id, d.chemin)
            avant = self.envoi_dossiers.get(cle)
            if avant:
                d = DossierEnvoye(d.chemin, avant.illisible or d.illisible, avant.enfants + d.enfants,
                                  avant.illisibles + d.illisibles)
            self.envoi_dossiers[cle] = d
        self.envois[envoi_id]["nb_dossiers"] = sum(1 for c in self.envoi_dossiers if c[0] == envoi_id)

    async def dossier_envoi(self, envoi_id: int, chemin: str) -> DossierEnvoye | None:
        return self.envoi_dossiers.get((envoi_id, chemin))

    def _clore(self, envoi_id: int, statut: str) -> None:
        self.envois[envoi_id]["statut"] = statut
        if statut in ("traite", "abandonne"):
            self.envois[envoi_id]["fin"] = _maintenant()
            self._vider_envoi(envoi_id)

    async def clore_envoi(self, envoi_id: int, statut: str) -> None:
        self._clore(envoi_id, statut)

    async def abandonner_envois(self, age_heures: int) -> int:
        limite = _maintenant() - timedelta(hours=age_heures)
        vieux = [e for e in self.envois.values()
                 if e["statut"] in ("reception", "traitement") and e["debut"] < limite]
        for e in vieux:
            self._clore(e["id"], "abandonne")
        return len(vieux)
