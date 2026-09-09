"""
Calculs du contrat — mensualisation, frais, contrôles
====================================================
Le cœur de la phase 3, et la partie où une erreur coûte de l'argent tous les mois pendant
deux ans. Tout est ici, en fonctions **pures** : pas de base, pas de réseau, pas d'IA —
seulement de l'arithmétique testable.

## Pourquoi un formulaire qui CALCULE, et non qui saisit

Le salaire d'une assistante maternelle n'est pas « le taux horaire fois les heures du
mois » : il est **mensualisé**, c'est-à-dire lissé sur douze mois, identique en février
comme en juillet, y compris les mois où l'on ne travaille pas. Demander directement le
montant mensuel reviendrait à demander à l'utilisateur de faire le calcul — et c'est
précisément là que les contrats se trompent.

Chaque résultat sort donc **avec sa formule en toutes lettres**, pour être vérifiable sans
faire confiance.

## Les deux régimes, et pourquoi on ne peut pas deviner lequel s'applique

- **Année complète** : l'accueil couvre toute l'année ; les congés payés sont inclus dans le
  lissé. La base est **52 semaines**.
- **Année incomplète** : l'accueil ne couvre pas toute l'année (parent enseignant, garde
  scolaire…). La base est le **nombre de semaines réellement programmées**, et les congés
  payés se règlent **à part**.

Choisir à la place de l'utilisateur serait une faute : le même taux horaire et les mêmes
heures donnent deux salaires différents, et l'écart se répète chaque mois.

## Ce qui est mensualisé, et ce qui ne l'est PAS

Le **salaire** est mensualisé. Les **indemnités** (entretien, repas, kilomètres) sont dues
par **jour d'accueil réel** : elles ne se lissent pas. Ce module en donne une *estimation*
mensuelle pour dimensionner un budget, et le dit — les confondre ferait promettre un montant
fixe là où il varie avec les jours de présence.

⚠️ **Aucun montant réglementaire n'est écrit ici.** Le SMIC horaire et le minimum garanti
changent chaque année : ils viennent des **Paramètres**, saisis et datés par l'utilisateur
depuis la source officielle. Sans eux, les calculs fonctionnent quand même — seuls les
**contrôles de plancher** sont désactivés, et l'écran l'annonce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

# Base légale du lissé en année complète : 52 semaines, congés payés inclus.
SEMAINES_ANNEE_COMPLETE = 52

# Seuil hebdomadaire au-delà duquel les heures sont majorées, et taux de majoration par
# défaut. Le taux exact se négocie et s'écrit AU CONTRAT : celui-ci n'est qu'une proposition.
SEUIL_HEURES_MAJOREES = Decimal("45")
MAJORATION_DEFAUT = Decimal("0.10")

# Ratio légal du salaire horaire minimum par enfant et par heure d'accueil, exprimé en
# fraction du SMIC horaire brut (art. D. 423-9 du Code de l'action sociale et des familles).
# C'est un RATIO inscrit dans la loi, pas un prix : il ne bouge pas avec l'inflation, et n'a
# donc pas sa place dans le barème saisi par l'utilisateur — contrairement au SMIC lui-même.
# Vérifié le 09/09/2026.
RATIO_MINIMUM_HORAIRE = Decimal("0.281")

# Plafond légal du salaire journalier par enfant, en SMIC horaire brut.
PLAFOND_JOURNALIER_SMIC = Decimal("5")


def _euros(valeur: Decimal) -> Decimal:
    """Arrondi au centime, au plus proche. Un salaire ne se tronque pas."""
    return valeur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _nombre(valeur: Decimal) -> Decimal:
    """Arrondi à deux décimales pour les heures (7,58 h et non 7,5833…)."""
    return valeur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _fr(valeur: Decimal) -> str:
    """« 1234.5 » → « 1 234,50 » : les formules sont lues par un humain, pas par un parseur."""
    entier, _, decimales = f"{valeur:.2f}".partition(".")
    signe, entier = ("-", entier[1:]) if entier.startswith("-") else ("", entier)
    groupes = []
    while entier:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    return f"{signe}{' '.join(groupes)},{decimales}"


@dataclass
class Alerte:
    """Un contrôle qui n'est pas passé. `bloquant` = le contrat serait illégal en l'état."""

    cle: str
    message: str
    bloquant: bool = False


@dataclass
class Mensualisation:
    regime: str                     # 'complete' | 'incomplete'
    semaines: int
    heures_semaine: Decimal
    taux_horaire: Decimal
    heures_mensualisees: Decimal
    heures_normales_semaine: Decimal
    heures_majorees_semaine: Decimal
    salaire_mensuel: Decimal
    formule: str
    detail: list[str] = field(default_factory=list)


def mensualiser(
    *,
    taux_horaire: Decimal,
    heures_semaine: Decimal,
    annee_complete: bool,
    semaines: int | None = None,
    majoration: Decimal | None = None,
) -> Mensualisation:
    """
    Salaire mensuel lissé et heures mensualisées, **avec la formule appliquée**.

    `semaines` n'est lu qu'en année incomplète ; en année complète, la base est 52, et
    accepter une autre valeur laisserait croire qu'on peut la négocier.

    Les heures au-delà de 45 h par semaine sont majorées : elles entrent dans le lissé à
    leur taux majoré, sans quoi le salaire mensuel serait sous-évalué toute l'année.
    """
    if taux_horaire <= 0 or heures_semaine <= 0:
        raise ValueError("Le taux horaire et les heures hebdomadaires doivent être positifs.")

    nb_semaines = SEMAINES_ANNEE_COMPLETE if annee_complete else int(semaines or 0)
    if not annee_complete and not 1 <= nb_semaines <= 52:
        raise ValueError("En année incomplète, le nombre de semaines d'accueil doit être "
                         "compris entre 1 et 52.")

    taux_majoration = MAJORATION_DEFAUT if majoration is None else majoration
    normales = min(heures_semaine, SEUIL_HEURES_MAJOREES)
    majorees = max(Decimal("0"), heures_semaine - SEUIL_HEURES_MAJOREES)

    # Coût d'une semaine, majoration comprise.
    cout_semaine = normales * taux_horaire + majorees * taux_horaire * (1 + taux_majoration)
    salaire = _euros(cout_semaine * nb_semaines / 12)
    heures_mens = _nombre(heures_semaine * nb_semaines / 12)

    libelle = "année complète" if annee_complete else "année incomplète"
    formule = (
        f"({_fr(taux_horaire)} € × {_fr(heures_semaine)} h × {nb_semaines} semaines) ÷ 12 "
        f"= {_fr(salaire)} € par mois"
    )
    detail = [
        f"Régime : {libelle} — base de {nb_semaines} semaines.",
        f"Heures mensualisées : {_fr(heures_semaine)} h × {nb_semaines} ÷ 12 = {_fr(heures_mens)} h par mois.",
    ]
    if majorees > 0:
        formule = (
            f"(({_fr(normales)} h × {_fr(taux_horaire)} € + {_fr(majorees)} h × "
            f"{_fr(taux_horaire)} € × {_fr(1 + taux_majoration)}) × {nb_semaines}) ÷ 12 "
            f"= {_fr(salaire)} € par mois"
        )
        detail.append(
            f"Au-delà de {_fr(SEUIL_HEURES_MAJOREES)} h par semaine, {_fr(majorees)} h sont "
            f"majorées de {_fr(taux_majoration * 100)} % — elles entrent dans le lissé à leur "
            "taux majoré, sinon le salaire mensuel serait sous-évalué toute l'année."
        )
    if annee_complete:
        detail.append("Les congés payés sont compris dans ce lissé.")
    else:
        detail.append("⚠️ En année incomplète, les congés payés se règlent EN PLUS de ce "
                      "montant : ils ne sont pas compris dans le lissé.")

    return Mensualisation(
        regime="complete" if annee_complete else "incomplete",
        semaines=nb_semaines, heures_semaine=heures_semaine, taux_horaire=taux_horaire,
        heures_mensualisees=heures_mens,
        heures_normales_semaine=normales, heures_majorees_semaine=majorees,
        salaire_mensuel=salaire, formule=formule, detail=detail,
    )


@dataclass
class Frais:
    entretien_mensuel: Decimal
    repas_mensuel: Decimal
    km_mensuel: Decimal
    total_mensuel: Decimal
    detail: list[str] = field(default_factory=list)


def estimer_frais(
    *,
    jours_semaine: int,
    semaines: int,
    entretien_jour: Decimal | None = None,
    repas_jour: Decimal | None = None,
    km_semaine: Decimal | None = None,
    tarif_km: Decimal | None = None,
) -> Frais:
    """
    **Estimation** mensuelle des indemnités — et le mot compte.

    Contrairement au salaire, ces sommes sont dues **par jour d'accueil réel** : un mois où
    l'enfant est absent une semaine, elles baissent. Les présenter comme un montant fixe
    ferait promettre ce qui n'est pas promis, et fausserait le budget dans les deux sens.

    Elles ne sont pas du salaire : elles ne se cotisent pas et n'entrent pas dans la
    mensualisation.
    """
    par_mois = Decimal(jours_semaine * semaines) / 12
    entretien = _euros((entretien_jour or Decimal("0")) * par_mois)
    repas = _euros((repas_jour or Decimal("0")) * par_mois)
    km = _euros((km_semaine or Decimal("0")) * (tarif_km or Decimal("0")) * Decimal(semaines) / 12)

    detail = [
        f"Base : {jours_semaine} jour(s) par semaine × {semaines} semaines ÷ 12 "
        f"= {_fr(_nombre(par_mois))} jours d'accueil par mois en moyenne.",
        "Ces indemnités sont dues par jour d'accueil RÉEL : ce sont des estimations, pas des "
        "montants fixes. Elles ne sont pas du salaire et ne se cotisent pas.",
    ]
    return Frais(entretien_mensuel=entretien, repas_mensuel=repas, km_mensuel=km,
                 total_mensuel=_euros(entretien + repas + km), detail=detail)


def controler(
    *,
    taux_horaire: Decimal,
    heures_jour: Decimal | None,
    entretien_jour: Decimal | None,
    smic_horaire: Decimal | None,
    minimum_garanti: Decimal | None,
) -> list[Alerte]:
    """
    Contrôles de plancher légal — **actifs seulement si le barème est renseigné**.

    Sans SMIC ni minimum garanti saisis dans les Paramètres, on ne rend pas une alerte
    rassurante : on rend une alerte disant que le contrôle **n'a pas eu lieu**. Un écran
    silencieux se lirait « tout va bien », ce qui est exactement l'erreur à éviter.
    """
    alertes: list[Alerte] = []

    if smic_horaire is None or smic_horaire <= 0:
        alertes.append(Alerte(
            cle="bareme_absent",
            message="Barème non renseigné : le salaire horaire n'a PAS été comparé au minimum "
                    "légal. Saisissez le SMIC horaire brut dans Paramètres → Barème emploi à "
                    "domicile pour activer ce contrôle.",
        ))
    else:
        plancher = _euros(smic_horaire * RATIO_MINIMUM_HORAIRE)
        if taux_horaire < plancher:
            alertes.append(Alerte(
                cle="sous_plancher",
                bloquant=True,
                message=f"Salaire horaire inférieur au minimum légal : {_fr(taux_horaire)} € "
                        f"contre {_fr(plancher)} € (SMIC horaire {_fr(smic_horaire)} € × "
                        f"{RATIO_MINIMUM_HORAIRE} par enfant et par heure).",
            ))
        if heures_jour and heures_jour > 0:
            plafond = _euros(smic_horaire * PLAFOND_JOURNALIER_SMIC)
            journalier = _euros(taux_horaire * heures_jour)
            if journalier > plafond:
                alertes.append(Alerte(
                    cle="au_dessus_plafond",
                    message=f"Salaire journalier de {_fr(journalier)} € : au-delà du plafond "
                            f"légal de {_fr(plafond)} € par enfant et par jour "
                            f"({PLAFOND_JOURNALIER_SMIC} SMIC horaires).",
                ))

    if entretien_jour is not None and minimum_garanti and minimum_garanti > 0 and heures_jour:
        # Minimum d'entretien : 85 % du minimum garanti pour 9 h d'accueil, proratisé.
        minimum = _euros(minimum_garanti * Decimal("0.85") * heures_jour / Decimal("9"))
        if entretien_jour < minimum:
            alertes.append(Alerte(
                cle="entretien_insuffisant",
                bloquant=True,
                message=f"Indemnité d'entretien de {_fr(entretien_jour)} € par jour, en dessous "
                        f"du minimum de {_fr(minimum)} € pour {_fr(heures_jour)} h d'accueil.",
            ))

    return alertes
