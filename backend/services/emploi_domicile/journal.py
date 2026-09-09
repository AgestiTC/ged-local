"""
Journal mensuel — récapituler ce qui a été réellement fait
==========================================================
Fonctions **pures** : pas de base, pas de réseau, pas d'IA. Elles additionnent ce que
l'utilisateur a saisi et comparent au contrat.

## Les trois questions auxquelles ce récapitulatif répond

1. **Que déclarer ce mois-ci ?** Heures, jours d'accueil, repas, kilomètres — exactement ce
   que demande le formulaire Pajemploi ou CESU.
2. **Combien a-t-on versé cette année ?** La déclaration fiscale veut le **réalisé**, pas le
   prévisionnel du contrat. Sans ces douze lignes, tout total annuel serait inventé.
3. **Où en est-on par rapport au contrat ?** C'est la matière de la **régularisation
   annuelle** : le salaire étant lissé, on compare en fin d'année les heures payées et les
   heures faites, et on solde l'écart.

## Ce que ce module ne fait pas

- **Aucun bulletin de salaire.** Il est édité par Pajemploi (assistante maternelle) ou le
  CESU (aide à domicile) à partir de la déclaration, et c'est lui qui fait foi. Un bulletin
  fabriqué à côté serait au mieux inutile, au pire divergent — avec une salariée qui aurait
  deux versions de sa paie.
- **Aucun net à payer, aucune cotisation.** Le calcul des charges dépend d'aides et de
  barèmes que Matothèque ne connaît pas. Le montant d'un écart d'heures est donné **au taux
  horaire du contrat**, et présenté comme une estimation à vérifier — pas comme une somme due.

## Un mois vide n'est pas un mois à zéro

Un mois non saisi et un mois réellement sans accueil sont deux choses différentes. Le premier
signifie « je n'ai pas encore rempli », le second « il n'y a rien eu ». Les confondre ferait
croire à une année complète alors qu'il en manque la moitié — d'où le décompte des mois
**saisis**, rendu avec les totaux.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

MOIS_NOMS = ("janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre", "décembre")


def _euros(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _nombre(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Totaux:
    heures: Decimal
    jours_accueil: int
    repas: int
    km: Decimal
    absences: int
    mois_saisis: int
    mois_declares: int


@dataclass
class Recapitulatif:
    annee: int
    totaux: Totaux
    # Comparaison au contrat — `None` tant que le contrat n'est pas calculable (taux ou
    # durée hebdomadaire manquants). On ne compare pas à un prévisionnel qui n'existe pas.
    heures_prevues: Decimal | None = None
    ecart_heures: Decimal | None = None
    montant_ecart: Decimal | None = None
    salaire_annuel_prevu: Decimal | None = None
    remarques: list[str] = field(default_factory=list)


def recapituler(
    *,
    annee: int,
    mois: list[dict],
    heures_mensualisees: Decimal | None = None,
    taux_horaire: Decimal | None = None,
    salaire_mensuel: Decimal | None = None,
) -> Recapitulatif:
    """
    Totaux de l'année et comparaison au contrat.

    `mois` = les lignes saisies (une par mois renseigné). Un mois absent de la liste n'est
    **pas** compté comme un mois à zéro : il est simplement non saisi, et le récapitulatif le
    dit plutôt que de laisser croire à une année complète.
    """
    def _dec(ligne: dict, cle: str) -> Decimal:
        valeur = ligne.get(cle)
        return Decimal(str(valeur)) if valeur is not None else Decimal("0")

    def _int(ligne: dict, cle: str) -> int:
        valeur = ligne.get(cle)
        return int(valeur) if valeur is not None else 0

    # Un mois compte comme SAISI dès qu'il porte une valeur exploitable. Une ligne créée puis
    # laissée vide (on ouvre le mois, on referme) ne doit pas gonfler le compte.
    saisis = [m for m in mois if any(m.get(c) is not None
                                     for c in ("heures", "jours_accueil", "repas", "km"))]

    totaux = Totaux(
        heures=_nombre(sum((_dec(m, "heures") for m in mois), Decimal("0"))),
        jours_accueil=sum(_int(m, "jours_accueil") for m in mois),
        repas=sum(_int(m, "repas") for m in mois),
        km=_nombre(sum((_dec(m, "km") for m in mois), Decimal("0"))),
        absences=sum(_int(m, "absences") for m in mois),
        mois_saisis=len(saisis),
        mois_declares=sum(1 for m in mois if m.get("declare")),
    )

    recap = Recapitulatif(annee=annee, totaux=totaux)

    if totaux.mois_saisis == 0:
        recap.remarques.append(
            "Aucun mois saisi pour cette année : les totaux sont vides parce qu'il n'y a rien "
            "à additionner, pas parce qu'il ne s'est rien passé."
        )
        return recap
    if totaux.mois_saisis < 12:
        manquants = 12 - totaux.mois_saisis
        recap.remarques.append(
            f"{manquants} mois non saisi{'s' if manquants > 1 else ''} : le total annuel est "
            "**partiel**, et ne doit pas être reporté tel quel sur une déclaration."
        )

    if heures_mensualisees is None or heures_mensualisees <= 0:
        recap.remarques.append(
            "Le contrat ne permet pas encore de calculer les heures prévues (taux horaire ou "
            "durée hebdomadaire manquants) : aucune comparaison n'est faite."
        )
        return recap

    # Les heures prévues d'une ANNÉE = les heures mensualisées × 12, quel que soit le régime :
    # c'est bien douze versements identiques qui ont eu lieu.
    recap.heures_prevues = _nombre(heures_mensualisees * 12)
    recap.ecart_heures = _nombre(totaux.heures - recap.heures_prevues)
    if salaire_mensuel is not None:
        recap.salaire_annuel_prevu = _euros(salaire_mensuel * 12)
    if taux_horaire is not None and taux_horaire > 0:
        recap.montant_ecart = _euros(recap.ecart_heures * taux_horaire)

    if totaux.mois_saisis == 12 and recap.ecart_heures != 0:
        sens = "en plus" if recap.ecart_heures > 0 else "en moins"
        recap.remarques.append(
            f"Régularisation : {abs(recap.ecart_heures)} heures {sens} par rapport au lissé. "
            "Le montant indiqué est une estimation au taux horaire du contrat — il ne tient "
            "compte ni des majorations ni des cotisations."
        )

    return recap
