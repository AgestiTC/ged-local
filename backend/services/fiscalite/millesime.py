"""
Millésime fiscal — les cases, leur formulaire, et la date à laquelle on les a vérifiées
======================================================================================
**Tout ce qui est réglementaire vit ici, et nulle part ailleurs.** Un numéro de case
dispersé dans le code d'un contributeur serait impossible à relire une fois par an — or
c'est exactement ce qu'il faut faire.

Les numéros de case bougent peu, mais ils bougent (une case fusionne, une annexe se
renomme). Une case juste l'an dernier et fausse cette année serait **la pire erreur de cet
onglet**, parce qu'elle serait recopiée sans hésiter. D'où :

- un **millésime explicite** (`MILLESIME`) et une **date de vérification** (`VERIFIE_LE`),
  affichés à l'écran et vieillissant visiblement au-delà d'un an ;
- des libellés courts qui disent *ce qu'on y met*, pas le jargon du formulaire ;
- l'**avertissement** rendu avec la synthèse, jamais optionnel.

⚠️ **Rien ici n'est produit ni relu par l'IA.** C'est du contenu humain, daté et sourcé.

📌 **À faire à chaque campagne** (avril) : confronter ces cases à la notice officielle de
l'année, mettre à jour `VERIFIE_LE`, et compléter `notice_url` quand le lien profond de la
case est vérifié. Tant qu'il ne l'est pas, on renvoie vers le portail — afficher un lien
qu'on n'a pas ouvert serait la même faute que d'afficher un montant qu'on n'a pas tracé.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Millésime couvert et date du dernier contrôle humain de ce fichier.
MILLESIME = 2026
VERIFIE_LE = date(2026, 9, 9)

# Portail officiel. Volontairement générique : les liens profonds vers la notice de chaque
# case ne sont pas renseignés tant qu'ils n'ont pas été ouverts et vérifiés.
URL_IMPOTS = "https://www.impots.gouv.fr/"

AVERTISSEMENT = (
    "Ces montants et ces cases sont une aide à la saisie, pas une déclaration : ils sont à "
    "vérifier avant report. Matothèque ne calcule aucun impôt, ne transmet rien à "
    "l'administration et ne remplace pas la notice officielle, qui seule fait foi."
)

# Les formulaires cités, avec ce qu'il faut savoir pour les trouver — c'est la moitié du
# problème : on cherche 7GA sur la 2042 alors qu'elle est sur une annexe.
FORMULAIRES: dict[str, str] = {
    "2042": "Déclaration de revenus (formulaire principal)",
    "2042-RICI": "Annexe « réductions et crédits d'impôt » — à demander explicitement en "
                 "ligne : elle n'apparaît pas d'office dans le parcours de déclaration",
}


@dataclass(frozen=True)
class Case:
    code: str
    formulaire: str
    libelle: str
    aide: str | None = None
    notice_url: str | None = None


def _c(code: str, formulaire: str, libelle: str, aide: str | None = None) -> Case:
    return Case(code=code, formulaire=formulaire, libelle=libelle, aide=aide,
                notice_url=None)  # cf. docstring : lien profond seulement une fois vérifié


CASES: dict[str, Case] = {c.code: c for c in [
    # ── Frais de garde des jeunes enfants (une case PAR enfant, dans l'ordre) ─────────
    _c("7GA", "2042-RICI", "Frais de garde hors domicile — 1ᵉʳ enfant",
       "Enfant de moins de 6 ans gardé à l'extérieur (assistante maternelle agréée, crèche, "
       "halte-garderie). Les aides perçues pour cette garde — CMG notamment — se déduisent "
       "des sommes déclarées : c'est l'oubli le plus fréquent du dispositif."),
    _c("7GB", "2042-RICI", "Frais de garde hors domicile — 2ᵉ enfant"),
    _c("7GC", "2042-RICI", "Frais de garde hors domicile — 3ᵉ enfant"),

    # ── Emploi d'un salarié à domicile ───────────────────────────────────────────────
    _c("7DB", "2042-RICI", "Sommes versées pour un salarié à domicile",
       "Garde d'enfant AU DOMICILE, ménage, jardinage, soutien scolaire, aide à "
       "l'autonomie. À ne pas confondre avec la garde hors domicile (7GA et suivantes) : "
       "c'est le LIEU qui décide, pas le métier."),
    _c("7DR", "2042-RICI", "Aides perçues pour cet emploi — à déduire",
       "APA, PCH, CMG, aides de la commune, du comité d'entreprise, et avance immédiate du "
       "crédit d'impôt déjà versée. Elles se reportent ici : les oublier revient à déclarer "
       "une dépense qu'on n'a pas supportée."),

    # ── Dons ─────────────────────────────────────────────────────────────────────────
    _c("7UD", "2042-RICI", "Dons — organismes d'aide aux personnes en difficulté",
       "Repas, soins, logement aux personnes en difficulté (taux majoré)."),
    _c("7UF", "2042-RICI", "Dons — autres organismes d'intérêt général",
       "Associations, fondations, culture, environnement, enseignement."),
]}


def case(code: str) -> Case | None:
    return CASES.get(code)


def formulaire_de(code: str | None) -> str:
    """Formulaire portant cette case ; « 2042-RICI » par défaut (cas des lignes à trancher)."""
    c = CASES.get(code or "")
    return c.formulaire if c else "2042-RICI"


def libelle_formulaire(code: str) -> str:
    return FORMULAIRES.get(code, code)
