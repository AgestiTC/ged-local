"""
Règles des congés liés à la naissance — datées, sourcées, relues à la main
===========================================================================
**Tout ce qui est réglementaire vit ici, et nulle part ailleurs.** Même discipline que
`services/fiscalite/millesime.py` : une durée de congé juste l'an dernier et fausse cette année
serait recopiée sans hésiter dans une lettre à l'employeur — et c'est un droit qui se perd, pas
une case qui se corrige.

Ces règles bougent réellement : le congé de paternité est passé de 11 à 25 jours en 2021, et
un **congé supplémentaire de naissance** est ouvert depuis le 1ᵉʳ juillet 2026 (décret
n° 2026-419 du 30 mai 2026). D'où `VERIFIE_LE`, affiché à l'écran et qui vieillit visiblement.

⚠️ **Rien ici n'est produit ni relu par l'IA.** Chaque chiffre a été relevé le 15/09/2026 sur les
pages officielles listées dans `SOURCES`, mises à jour par l'administration le 1ᵉʳ juin 2026.

📌 **À relire** à chaque changement de loi de financement de la Sécurité sociale (décembre) et
au moins une fois par an : confronter aux pages de `SOURCES`, mettre à jour `VERIFIE_LE`.

## Périmètre

Les règles ci-dessous sont celles d'un **salarié du secteur privé**. La fonction publique
(décrets n° 2026-427 et 2026-428) et les travailleurs indépendants relèvent d'autres textes :
l'écran le signale au lieu de calculer faux en silence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

VERIFIE_LE = date(2026, 9, 28)

URL_F2265 = "https://www.service-public.gouv.fr/particuliers/vosdroits/F2265"
URL_F3156 = "https://www.service-public.gouv.fr/particuliers/vosdroits/F3156"
URL_AMELI_MATERNITE = ("https://www.ameli.fr/assure/droits-demarches/famille/"
                       "maternite-paternite-adoption/conge-maternite")
URL_AMELI_CSN = ("https://www.ameli.fr/assure/droits-demarches/famille/"
                 "maternite-paternite-adoption/conge-supplementaire-naissance")

SOURCES = [
    {"libelle": "Congé de maternité d'une salariée — service-public.gouv.fr (maj. 01/06/2026)",
     "url": URL_F2265},
    {"libelle": "Congé de paternité et d'accueil de l'enfant — service-public.gouv.fr (maj. 01/06/2026)",
     "url": URL_F3156},
    {"libelle": "Congé maternité et congé pathologique — ameli.fr",
     "url": URL_AMELI_MATERNITE},
    {"libelle": "Congé supplémentaire de naissance — ameli.fr",
     "url": URL_AMELI_CSN},
    {"libelle": "Code du travail, articles L1225-46-2 à L1225-46-7 — Légifrance",
     "url": "https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006072050/LEGISCTA000053271681/"},
    {"libelle": "Décret n° 2026-419 du 30 mai 2026 — Légifrance",
     "url": "https://www.legifrance.gouv.fr/jorf/id/JORFTEXT000054153815"},
]

AVERTISSEMENT = (
    "Ces dates sont une aide à la préparation, calculées pour un salarié du secteur privé à "
    "partir des règles en vigueur à la date de vérification affichée. Elles ne remplacent ni "
    "votre convention collective (souvent plus favorable), ni votre employeur, ni la CPAM, qui "
    "seuls font foi. Tant que la naissance n'a pas eu lieu, tout est prévisionnel."
)


# ─── Congé de maternité ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DureeMaternite:
    libelle: str
    prenatal_semaines: int
    postnatal_semaines: int
    aide: str | None = None


# Clé stable : c'est elle qui est enregistrée dans les paramètres du foyer.
SITUATIONS: dict[str, DureeMaternite] = {
    "rang_1_2": DureeMaternite("1ᵉʳ ou 2ᵉ enfant", 6, 10),
    "rang_3_plus": DureeMaternite(
        "3ᵉ enfant ou plus", 8, 18,
        aide="Quand le foyer assume déjà la charge d'au moins deux enfants, ou que la mère a "
             "déjà mis au monde au moins deux enfants nés viables."),
    "jumeaux": DureeMaternite("Jumeaux", 12, 22),
    "triples": DureeMaternite("Triplés ou plus", 24, 22),
}

# Report d'une partie du prénatal sur le postnatal, sur avis favorable du professionnel de santé.
REPORT_PRENATAL_MAX_SEMAINES = 3

# Congés pathologiques — uniquement SUR PRESCRIPTION MÉDICALE, jamais de droit. Relevé le
# 28/09/2026, mot pour mot :
# - service-public F2265 : « En cas de maladie due à votre grossesse ou aux suites de votre
#   accouchement, la durée de votre congé de maternité est augmentée dans les limites suivantes :
#   2 semaines avant la date présumée de l'accouchement, 4 semaines après l'accouchement. »
# - ameli : prescrit « en une fois ou en plusieurs fois, mais dans la limite de 2 semaines
#   maximum » ; il ne se reporte pas sur le postnatal.
# ⚠️ Aucune des deux pages ne dit COMMENT ces semaines sont indemnisées : l'écran ne l'affirme
# donc pas, il renvoie à la CPAM.
# Le prénatal pathologique n'est pas forcément accolé au prénatal : le calcul le pose juste
# avant, qui est le cas courant, et le dit.
PATHO_PRENATAL_MAX_JOURS = 14
PATHO_POSTNATAL_MAX_JOURS = 28
PATHO_INDEMNISATION = ("Leur indemnisation n'est pas précisée par les pages officielles : à "
                       "confirmer avec votre CPAM.")


# ─── Congé de naissance et congé de paternité et d'accueil de l'enfant ─────────────────

# Congé de naissance : à la charge de l'employeur, compté en jours OUVRABLES.
NAISSANCE_JOURS_OUVRABLES = 3

# Congé de paternité et d'accueil de l'enfant : jours CALENDAIRES, indemnisés par la CPAM.
PATERNITE_OBLIGATOIRE_JOURS = 4          # accolés au congé de naissance, interdits au travail
PATERNITE_SOLDE_JOURS = 21               # facultatif
PATERNITE_SOLDE_JOURS_MULTIPLES = 28     # naissances multiples
PATERNITE_SOLDE_PERIODES_MAX = 2
PATERNITE_SOLDE_PERIODE_MIN_JOURS = 5
PATERNITE_DELAI_MOIS = 6                 # le solde se prend dans les 6 mois suivant la naissance
PATERNITE_PREAVIS_MOIS = 1               # date présumée ET dates de congé : au moins 1 mois avant


# ─── Congé supplémentaire de naissance (depuis le 1ᵉʳ juillet 2026) ───────────────────

CSN_MOIS_POSSIBLES = (0, 1, 2)           # 0 = ne pas le prendre ; fractionnable en 2 × 1 mois
CSN_DELAI_MOIS = 9                       # chaque période DÉBUTE dans les 9 mois (art. D. 1225-11-3)
CSN_PREAVIS_MOIS = 1                     # réduit à 15 jours dans un cas précis — voir ci-dessous
CSN_OUVERTURE = date(2026, 7, 1)
# Enfants nés entre le 1ᵉʳ janvier et le 30 juin 2026 : le délai de 9 mois court à partir du
# 1ᵉʳ juillet 2026 (régime transitoire, décret n° 2026-419, art. 2 ; ameli.fr).
CSN_TRANSITOIRE_DEBUT = date(2026, 1, 1)

CSN_INDEMNISATION = (
    "70 % du salaire net le 1ᵉʳ mois, 60 % le 2ᵉ mois, dans la limite du plafond de la Sécurité "
    "sociale. Versé par la CPAM à la fin de chaque période."
)

# Le préavis est réduit à 15 jours quand le congé suit immédiatement le congé de paternité ou
# d'accueil. On pose pourtant le rappel UN MOIS avant, toujours : un rappel en avance ne coûte
# rien, un rappel en retard coûte le congé — et l'interprétation exacte du cas réduit se
# vérifie mieux auprès de l'employeur qu'avec un calcul.
CSN_NOTE_PREAVIS = (
    "Délai légal : 1 mois avant le début (réduit à 15 jours si le congé suit immédiatement le "
    "congé de paternité ou d'accueil). Le rappel est posé un mois avant, par prudence."
)


# ─── Contrôle en ligne : les chiffres ci-dessus sont-ils toujours ceux des pages ? ─────
#
# Chaque contrôle est une phrase TÉMOIN, relevée telle quelle sur la page officielle, mais
# CONSTRUITE DEPUIS LA CONSTANTE qu'elle vérifie. Deux dérives se voient ainsi d'un coup :
# la loi (la page) change, ou quelqu'un modifie une durée ici sans que la loi ait changé.
#
# Le contrôle CONSTATE, il ne corrige jamais : une durée lue sur une page ne réécrit pas une
# règle sans relecture humaine. Une phrase introuvable veut dire « relire la page », pas « la
# loi a changé » — l'administration reformule aussi.
#
# Relevé le 28/09/2026 : les 16 phrases sont présentes sur les 4 pages.

@dataclass(frozen=True)
class Controle:
    cle: str
    libelle: str
    url: str
    phrase: str                # minuscules, espaces simples — comparée au texte normalisé


def _semaines(s: DureeMaternite) -> str:
    total = s.prenatal_semaines + s.postnatal_semaines
    return f"{s.prenatal_semaines} semaines {s.postnatal_semaines} semaines {total} semaines"


CONTROLES: list[Controle] = [
    # Congé de maternité — service-public F2265
    *[Controle(f"maternite_{k}", f"Maternité — {s.libelle} ({s.prenatal_semaines} + "
                                 f"{s.postnatal_semaines} semaines)", URL_F2265, _semaines(s))
      for k, s in SITUATIONS.items()],
    Controle("report_prenatal", f"Report du prénatal : {REPORT_PRENATAL_MAX_SEMAINES} semaines au plus",
             URL_F2265, f"durée maximale de {REPORT_PRENATAL_MAX_SEMAINES} semaines"),
    Controle("pathologique_prenatal",
             f"Congé pathologique prénatal : {PATHO_PRENATAL_MAX_JOURS // 7} semaines au plus",
             URL_F2265, f"{PATHO_PRENATAL_MAX_JOURS // 7} semaines avant la date présumée de "
                        "l'accouchement"),
    Controle("pathologique_postnatal",
             f"Congé pathologique postnatal : {PATHO_POSTNATAL_MAX_JOURS // 7} semaines au plus",
             URL_F2265, f"{PATHO_POSTNATAL_MAX_JOURS // 7} semaines après l'accouchement"),
    # Congé pathologique — ameli
    Controle("pathologique_prenatal_ameli",
             f"Congé pathologique prénatal (ameli) : {PATHO_PRENATAL_MAX_JOURS // 7} semaines au plus",
             URL_AMELI_MATERNITE, f"dans la limite de {PATHO_PRENATAL_MAX_JOURS // 7} semaines maximum"),
    # Congé de naissance et de paternité — service-public F3156
    Controle("naissance", f"Congé de naissance : {NAISSANCE_JOURS_OUVRABLES} jours ouvrables",
             URL_F3156, f"{NAISSANCE_JOURS_OUVRABLES} jours ouvrables"),
    Controle("paternite_total",
             f"Paternité : {PATERNITE_OBLIGATOIRE_JOURS + PATERNITE_SOLDE_JOURS} jours calendaires",
             URL_F3156, f"est de {PATERNITE_OBLIGATOIRE_JOURS + PATERNITE_SOLDE_JOURS} jours calendaires"),
    Controle("paternite_obligatoire", f"Paternité — part obligatoire : {PATERNITE_OBLIGATOIRE_JOURS} jours",
             URL_F3156, f"période obligatoire de {PATERNITE_OBLIGATOIRE_JOURS} jours calendaires"),
    Controle("paternite_solde", f"Paternité — solde : {PATERNITE_SOLDE_JOURS} jours",
             URL_F3156, f"période facultative de {PATERNITE_SOLDE_JOURS} jours calendaires"),
    Controle("paternite_solde_multiples",
             f"Paternité — solde, naissances multiples : {PATERNITE_SOLDE_JOURS_MULTIPLES} jours",
             URL_F3156, f"période facultative de {PATERNITE_SOLDE_JOURS_MULTIPLES} jours calendaires"),
    Controle("paternite_delai", f"Paternité — à prendre dans les {PATERNITE_DELAI_MOIS} mois",
             URL_F3156, f"dans les {PATERNITE_DELAI_MOIS} mois suivant la naissance"),
    Controle("paternite_preavis", f"Paternité — prévenir {PATERNITE_PREAVIS_MOIS} mois avant",
             URL_F3156, f"au moins {PATERNITE_PREAVIS_MOIS} mois avant"),
    # Congé supplémentaire de naissance — ameli
    Controle("csn_delai", f"Congé supplémentaire : débuter dans les {CSN_DELAI_MOIS} mois",
             URL_AMELI_CSN, f"doit débuter dans les {CSN_DELAI_MOIS} mois suivant la naissance"),
]


# ─── Jours fériés (pour compter les jours ouvrables du congé de naissance) ─────────────

def _paques(annee: int) -> date:
    """Dimanche de Pâques, algorithme grégorien anonyme (Meeus/Jones/Butcher)."""
    a = annee % 19
    b, c = divmod(annee, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mois = (h + l - 7 * m + 114) // 31
    jour = ((h + l - 7 * m + 114) % 31) + 1
    return date(annee, mois, jour)


def jours_feries(annee: int) -> set[date]:
    """
    Les onze jours fériés légaux en métropole.

    Alsace-Moselle en compte deux de plus (Vendredi saint, 26 décembre) : non intégrés, le
    congé de naissance y durerait au plus un jour de plus — l'écran le dit dans son aide.
    """
    from datetime import timedelta

    p = _paques(annee)
    return {
        date(annee, 1, 1), p + timedelta(days=1), date(annee, 5, 1), date(annee, 5, 8),
        p + timedelta(days=39), p + timedelta(days=50), date(annee, 7, 14),
        date(annee, 8, 15), date(annee, 11, 1), date(annee, 11, 11), date(annee, 12, 25),
    }


def est_ouvrable(jour: date) -> bool:
    """Jour ouvrable : tous les jours sauf le dimanche et les jours fériés."""
    return jour.weekday() != 6 and jour not in jours_feries(jour.year)
