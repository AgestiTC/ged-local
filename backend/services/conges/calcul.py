"""
Calcul des congés de naissance — la mère et le co-parent
=========================================================
Fonctions **pures** : des dates et des paramètres en entrée, des périodes, des échéances et
des alertes en sortie. Aucune base, aucun réseau, aucune IA. Les règles viennent toutes de
`regles.py`.

## Ce que ce calcul sait faire, et ce qu'il refuse de deviner

Il enchaîne les congés dans l'ordre imposé par la loi, pose les dates de **préavis** — le seul
endroit où un oubli coûte le congé lui-même —, et vérifie les délais (6 mois pour le solde du
congé de paternité, 9 mois pour le congé supplémentaire de naissance).

Il **ne calcule aucune indemnité** : même refus que le simulateur « brut → net » du module
emploi à domicile. Un montant faux qu'on croit est pire que pas de montant.

## Le terme n'est pas la naissance

Tout part de la **date présumée d'accouchement** tant que la naissance n'a pas eu lieu, et
chaque date est alors marquée *prévisionnelle*. Une fois la **date réelle** saisie, tout est
recalculé depuis elle : une naissance en avance allonge le postnatal du prénatal non pris, une
naissance en retard prolonge le prénatal sans raccourcir le postnatal. Un planning resté sur
le prévisionnel afficherait des dates fausses au moment précis où l'on s'en sert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from services.conges import regles

MERE = "mere"
COPARENT = "coparent"


# ─── Arithmétique de dates ─────────────────────────────────────────────────────────────

def ajouter_mois(depart: date, mois: int) -> date:
    """
    `depart` + `mois` mois, **jour pour jour**. Un jour qui n'existe pas dans le mois d'arrivée
    (31 janvier + 1 mois) glisse au **1ᵉʳ du mois suivant** plutôt que d'être ramené au dernier
    jour : c'est ce qui rend juste le calcul « de date à date » de `fin_de_mois` ci-dessous.
    """
    total = depart.month - 1 + mois
    annee, mois_idx = depart.year + total // 12, total % 12 + 1
    try:
        return date(annee, mois_idx, depart.day)
    except ValueError:
        suivant = date(annee + (mois_idx == 12), mois_idx % 12 + 1, 1)
        return suivant


def fin_de_mois(debut: date, mois: int) -> date:
    """
    Dernier jour d'une période de `mois` mois comptée **de date à date** : du 15 mars au
    14 avril, du 31 janvier au 28 février (29 les années bissextiles).
    """
    return ajouter_mois(debut, mois) - timedelta(days=1)


def jours_ouvrables(debut: date, nombre: int) -> tuple[date, date]:
    """
    Première et dernière journée d'un congé de `nombre` jours ouvrables.

    Il commence le jour de `debut` si celui-ci est ouvrable, sinon le premier jour ouvrable
    qui suit — c'est le choix par défaut prévu par le Code du travail.
    """
    jour = debut
    while not regles.est_ouvrable(jour):
        jour += timedelta(days=1)
    premier, comptes, dernier = jour, 0, jour
    while comptes < nombre:
        if regles.est_ouvrable(jour):
            comptes += 1
            dernier = jour
        jour += timedelta(days=1)
    return premier, dernier


def _fr(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ─── Paramètres ────────────────────────────────────────────────────────────────────────

@dataclass
class ParamsMere:
    salariee: bool = True
    report_prenatal_semaines: int = 0
    csn_mois: int = 0
    csn_fractionne: bool = False
    csn_debut: date | None = None
    csn_debut_2: date | None = None


@dataclass
class ParamsCoparent:
    salarie: bool = True
    solde_pris: bool = True
    solde_fractionne: bool = False
    solde_debut: date | None = None
    solde_jours_1: int | None = None
    solde_debut_2: date | None = None
    csn_mois: int = 0
    csn_fractionne: bool = False
    csn_debut: date | None = None
    csn_debut_2: date | None = None


# ─── Résultat ──────────────────────────────────────────────────────────────────────────

@dataclass
class Periode:
    cle: str
    parent: str
    libelle: str
    debut: date
    fin: date
    obligatoire: bool
    paye_par: str
    note: str | None = None

    @property
    def jours(self) -> int:
        return (self.fin - self.debut).days + 1


@dataclass
class Echeance:
    """Une date à ne pas manquer — surtout les préavis, dont l'oubli coûte le congé."""
    cle: str
    parent: str
    libelle: str
    date: date
    note: str | None = None
    obligatoire: bool = True


@dataclass
class Alerte:
    niveau: str        # 'bloquant' | 'attention' | 'info'
    message: str
    parent: str | None = None


@dataclass
class PlanParent:
    parent: str
    periodes: list[Periode] = field(default_factory=list)
    echeances: list[Echeance] = field(default_factory=list)
    alertes: list[Alerte] = field(default_factory=list)
    reprise: date | None = None


@dataclass
class Plan:
    naissance: date | None
    previsionnel: bool
    mere: PlanParent
    coparent: PlanParent
    alertes: list[Alerte] = field(default_factory=list)


# ─── Congé de maternité ────────────────────────────────────────────────────────────────

def _maternite(terme: date, naissance: date | None, situation: str,
               p: ParamsMere, plan: PlanParent) -> date:
    """Prénatal et postnatal. Rend le dernier jour du congé de maternité."""
    duree = regles.SITUATIONS[situation]
    report = max(0, min(p.report_prenatal_semaines, regles.REPORT_PRENATAL_MAX_SEMAINES))
    if report != p.report_prenatal_semaines:
        plan.alertes.append(Alerte(
            "attention", f"Le report du prénatal est plafonné à "
                         f"{regles.REPORT_PRENATAL_MAX_SEMAINES} semaines : {report} retenues.", MERE))

    pre_semaines = duree.prenatal_semaines - report
    post_semaines = duree.postnatal_semaines + report
    debut_pre = terme - timedelta(weeks=pre_semaines)

    if naissance is None:
        fin_pre, debut_post = terme - timedelta(days=1), terme
        post_jours = post_semaines * 7
        note_post = "Prévisionnel : recalculé depuis la date réelle de naissance."
    elif naissance < terme:
        # Naissance en avance : le prénatal non pris s'ajoute au postnatal — la durée totale
        # est conservée, dans la limite du prénatal prévu.
        fin_pre, debut_post = naissance - timedelta(days=1), naissance
        non_pris = min((terme - naissance).days, pre_semaines * 7)
        post_jours = post_semaines * 7 + non_pris
        note_post = (f"Naissance avant le terme : {non_pris} jour(s) de prénatal non pris "
                     "reporté(s) sur le postnatal.")
        if naissance < debut_pre:
            plan.alertes.append(Alerte(
                "attention",
                "Naissance survenue avant même le début prévu du congé prénatal. Si l'enfant est "
                "né plus de 6 semaines avant le terme et a dû être hospitalisé, le congé est "
                "prolongé d'autant — cas particulier non calculé ici : à confirmer avec la CPAM.",
                MERE))
    else:
        # Naissance en retard : le prénatal se prolonge jusqu'à la naissance, le postnatal
        # garde sa durée entière.
        fin_pre, debut_post = naissance - timedelta(days=1), naissance
        post_jours = post_semaines * 7
        note_post = ("Naissance après le terme : le prénatal est prolongé jusqu'à la naissance, "
                     "le postnatal garde sa durée entière." if naissance > terme else None)

    if fin_pre >= debut_pre:
        plan.periodes.append(Periode(
            "maternite_prenatal", MERE, "Congé de maternité — prénatal", debut_pre, fin_pre,
            obligatoire=False, paye_par="CPAM (indemnités journalières)",
            note=(f"Report de {report} semaine(s) sur le postnatal, sur avis médical."
                  if report else None)))

    fin_post = debut_post + timedelta(days=post_jours - 1)
    plan.periodes.append(Periode(
        "maternite_postnatal", MERE, "Congé de maternité — postnatal", debut_post, fin_post,
        obligatoire=False, paye_par="CPAM (indemnités journalières)",
        note=(note_post + " " if note_post else "") +
             "Au moins 8 semaines d'arrêt sont obligatoires, dont 6 après l'accouchement."))

    plan.echeances.append(Echeance(
        "maternite_informer", MERE, "Informer l'employeur des dates du congé de maternité",
        debut_pre - timedelta(days=30),
        note="Pas de délai légal fixe, mais la protection et les autorisations d'absence ne "
             "courent qu'une fois l'employeur informé par écrit — rappel posé un mois avant.",
        obligatoire=False))
    return fin_post


# ─── Congé de naissance + congé de paternité et d'accueil de l'enfant ─────────────────

def _paternite(terme: date, naissance_base: date, situation: str,
               p: ParamsCoparent, plan: PlanParent) -> date:
    """Naissance (3 j ouvrables), part obligatoire (4 j), solde. Rend le dernier jour pris."""
    debut_n, fin_n = jours_ouvrables(naissance_base, regles.NAISSANCE_JOURS_OUVRABLES)
    plan.periodes.append(Periode(
        "naissance", COPARENT, "Congé de naissance", debut_n, fin_n,
        obligatoire=True, paye_par="Employeur (maintien du salaire)",
        note=f"{regles.NAISSANCE_JOURS_OUVRABLES} jours ouvrables (dimanches et jours fériés "
             "exclus)."))

    debut_o = fin_n + timedelta(days=1)
    fin_o = debut_o + timedelta(days=regles.PATERNITE_OBLIGATOIRE_JOURS - 1)
    plan.periodes.append(Periode(
        "paternite_obligatoire", COPARENT, "Congé de paternité — part obligatoire", debut_o, fin_o,
        obligatoire=True, paye_par="CPAM (indemnités journalières)",
        note="Accolée au congé de naissance ; interdiction de travailler pendant ces 4 jours."))

    plan.echeances.append(Echeance(
        "paternite_prevenir_terme", COPARENT,
        "Prévenir l'employeur de la date présumée d'accouchement",
        ajouter_mois(terme, -regles.PATERNITE_PREAVIS_MOIS),
        note="Délai légal : au moins 1 mois avant la date présumée."))

    derniere_fin = fin_o
    if not p.solde_pris:
        plan.alertes.append(Alerte(
            "info", "Solde du congé de paternité non pris. Il est facultatif — mais le congé "
                    "supplémentaire de naissance exige d'avoir pris l'intégralité du congé de "
                    "paternité et d'accueil.", COPARENT))
        return derniere_fin

    total = (regles.PATERNITE_SOLDE_JOURS_MULTIPLES if situation in ("jumeaux", "triples")
             else regles.PATERNITE_SOLDE_JOURS)
    limite = ajouter_mois(naissance_base, regles.PATERNITE_DELAI_MOIS) - timedelta(days=1)
    mini = regles.PATERNITE_SOLDE_PERIODE_MIN_JOURS

    if p.solde_fractionne:
        j1 = p.solde_jours_1 if p.solde_jours_1 is not None else total // 2
        if not (mini <= j1 <= total - mini):
            borne = max(mini, min(j1, total - mini))
            plan.alertes.append(Alerte(
                "bloquant", f"Chaque période du solde doit durer au moins {mini} jours : "
                            f"{j1} jour(s) en 1ʳᵉ période n'est pas possible, {borne} retenus.",
                COPARENT))
            j1 = borne
        durees = [j1, total - j1]
    else:
        durees = [total]

    debut = p.solde_debut or fin_o + timedelta(days=1)
    for rang, jours in enumerate(durees, start=1):
        if rang == 2:
            debut = p.solde_debut_2 or derniere_fin + timedelta(days=1)
        if debut <= derniere_fin:
            plan.alertes.append(Alerte(
                "bloquant", f"La période {rang} du solde commence le {_fr(debut)}, avant la fin "
                            f"de la précédente ({_fr(derniere_fin)}).", COPARENT))
        fin = debut + timedelta(days=jours - 1)
        suffixe = f" ({rang}/2)" if len(durees) == 2 else ""
        plan.periodes.append(Periode(
            f"paternite_solde_{rang}", COPARENT, f"Congé de paternité — solde{suffixe}",
            debut, fin, obligatoire=False, paye_par="CPAM (indemnités journalières)",
            note=f"{jours} jours calendaires, à prendre avant le {_fr(limite)}."))
        plan.echeances.append(Echeance(
            f"paternite_preavis_solde_{rang}", COPARENT,
            f"Prévenir l'employeur des dates du solde de paternité{suffixe}",
            ajouter_mois(debut, -regles.PATERNITE_PREAVIS_MOIS),
            note="Délai légal : au moins 1 mois avant le début de la période."))
        if debut > limite:
            plan.alertes.append(Alerte(
                "bloquant", f"La période {rang} du solde commence après le délai de "
                            f"{regles.PATERNITE_DELAI_MOIS} mois (limite : {_fr(limite)}).",
                COPARENT))
        elif fin > limite:
            plan.alertes.append(Alerte(
                "attention", f"La période {rang} du solde se termine après le délai de "
                             f"{regles.PATERNITE_DELAI_MOIS} mois ({_fr(limite)}) — à vérifier "
                             "avec l'employeur.", COPARENT))
        derniere_fin = max(derniere_fin, fin)
    return derniere_fin


# ─── Congé supplémentaire de naissance ─────────────────────────────────────────────────

def _csn(parent: str, naissance_base: date, fin_principal: date, mois: int, fractionne: bool,
         debut_1: date | None, debut_2: date | None, plan: PlanParent,
         principal_complet: bool) -> None:
    if mois not in regles.CSN_MOIS_POSSIBLES:
        plan.alertes.append(Alerte("bloquant", f"Durée impossible : {mois} mois (1 ou 2).", parent))
        return
    if mois == 0:
        return

    if naissance_base < regles.CSN_TRANSITOIRE_DEBUT:
        plan.alertes.append(Alerte(
            "bloquant", "Le congé supplémentaire de naissance concerne les enfants nés à partir "
                        "du 1ᵉʳ janvier 2026.", parent))
        return

    # Point de départ du délai : la naissance, ou le 1ᵉʳ juillet 2026 pour les enfants nés au
    # 1ᵉʳ semestre 2026 (régime transitoire).
    depart = max(naissance_base, regles.CSN_OUVERTURE)
    limite = ajouter_mois(depart, regles.CSN_DELAI_MOIS) - timedelta(days=1)

    if not principal_complet:
        plan.alertes.append(Alerte(
            "bloquant", "Ce congé n'est ouvert qu'après avoir pris l'INTÉGRALITÉ du congé de "
                        "paternité et d'accueil de l'enfant (solde compris).", parent))

    periodes = [(1, debut_1)] if (mois == 1 or not fractionne) else [(1, debut_1), (1, debut_2)]
    duree_unique = mois if len(periodes) == 1 else 1
    precedent_fin = fin_principal
    for rang, (_, choisi) in enumerate(periodes, start=1):
        debut = choisi or precedent_fin + timedelta(days=1)
        fin = fin_de_mois(debut, duree_unique)
        suffixe = f" ({rang}/2)" if len(periodes) == 2 else ""
        if debut <= fin_principal:
            plan.alertes.append(Alerte(
                "bloquant", f"Le congé supplémentaire{suffixe} commence le {_fr(debut)}, avant la "
                            f"fin du congé {'de maternité' if parent == MERE else 'de paternité'} "
                            f"({_fr(fin_principal)}). Il ne peut que le suivre.", parent))
        elif debut <= precedent_fin:
            plan.alertes.append(Alerte(
                "bloquant", f"La 2ᵉ période commence le {_fr(debut)}, avant la fin de la 1ʳᵉ "
                            f"({_fr(precedent_fin)}).", parent))
        if debut > limite:
            plan.alertes.append(Alerte(
                "bloquant", f"Le congé supplémentaire{suffixe} doit débuter au plus tard le "
                            f"{_fr(limite)} (délai de {regles.CSN_DELAI_MOIS} mois).", parent))

        plan.periodes.append(Periode(
            f"csn_{rang}", parent, f"Congé supplémentaire de naissance{suffixe}", debut, fin,
            obligatoire=False, paye_par="CPAM",
            note=f"{duree_unique} mois de date à date. {regles.CSN_INDEMNISATION}"))
        plan.echeances.append(Echeance(
            f"csn_preavis_{rang}", parent,
            f"Prévenir l'employeur du congé supplémentaire de naissance{suffixe}",
            ajouter_mois(debut, -regles.CSN_PREAVIS_MOIS), note=regles.CSN_NOTE_PREAVIS))
        precedent_fin = fin


# ─── Assemblage ────────────────────────────────────────────────────────────────────────

def calculer(*, terme: date, naissance: date | None = None, situation: str = "rang_1_2",
             mere: ParamsMere | None = None, coparent: ParamsCoparent | None = None) -> Plan:
    """
    Le plan complet des deux parents.

    `terme` est obligatoire : sans lui, rien n'est datable. `naissance` est facultative et,
    quand elle est connue, **prime** sur le terme pour tout ce qui court depuis l'accouchement.
    """
    mere = mere or ParamsMere()
    coparent = coparent or ParamsCoparent()
    if situation not in regles.SITUATIONS:
        situation = "rang_1_2"

    base = naissance or terme
    plan = Plan(naissance=naissance, previsionnel=naissance is None,
                mere=PlanParent(MERE), coparent=PlanParent(COPARENT))

    if plan.previsionnel:
        plan.alertes.append(Alerte(
            "info", f"Dates prévisionnelles, calculées depuis le terme du {_fr(terme)}. Saisissez "
                    "la date réelle de naissance dès qu'elle est connue : tout sera recalculé."))

    # La mère
    fin_mat = _maternite(terme, naissance, situation, mere, plan.mere)
    _csn(MERE, base, fin_mat, mere.csn_mois, mere.csn_fractionne,
         mere.csn_debut, mere.csn_debut_2, plan.mere, principal_complet=True)
    if not mere.salariee:
        plan.mere.alertes.append(Alerte(
            "attention", "Règles calculées pour une salariée du secteur privé : fonction publique "
                         "et travailleuses indépendantes relèvent d'autres textes.", MERE))

    # Le co-parent
    fin_pat = _paternite(terme, base, situation, coparent, plan.coparent)
    _csn(COPARENT, base, fin_pat, coparent.csn_mois, coparent.csn_fractionne,
         coparent.csn_debut, coparent.csn_debut_2, plan.coparent,
         principal_complet=coparent.solde_pris)
    if not coparent.salarie:
        plan.coparent.alertes.append(Alerte(
            "attention", "Règles calculées pour un salarié du secteur privé : fonction publique "
                         "et travailleurs indépendants relèvent d'autres textes.", COPARENT))

    for p in (plan.mere, plan.coparent):
        p.periodes.sort(key=lambda x: x.debut)
        p.echeances.sort(key=lambda x: x.date)
        if p.periodes:
            p.reprise = max(x.fin for x in p.periodes) + timedelta(days=1)
    return plan
