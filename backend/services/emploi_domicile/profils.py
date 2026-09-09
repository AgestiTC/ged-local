"""
Profils d'emploi à domicile — la table qui décide de tout
=========================================================
Le module s'appelle `emploi-domicile`, **pas `nounou`** : « Nounou » n'est que le libellé
du profil affiché dans « Devenir parent ». La raison tient en une ligne — employer une
**aide ménagère** relève de la **même convention collective** qu'une **assistante
maternelle**, avec le même contrat et les mêmes obligations ; ne changent vraiment que le
**lieu**, le **guichet**, l'**aide** et quelques clauses.

Écrire deux modules aurait dupliqué l'essentiel du travail pour une petite différence, et
condamné l'un des deux à vieillir seul.

**Ce fichier est la seule chose à modifier pour ajouter un profil.** Il pilote le libellé de
l'onglet, le guichet de déclaration, l'aide mobilisable et les blocs de contenu propres au
profil. Ajouter un profil = ajouter une entrée.

⚠️ Le **lieu** est le critère qui tranche, pas le métier : une garde d'enfant **chez elle**
relève de Pajemploi, la même personne **chez vous** aussi (tant qu'il y a un enfant de moins
de 6 ans et une demande de CMG), et un ménage **chez vous** relève du CESU. C'est l'erreur
la plus coûteuse du sujet, parce qu'elle fait perdre une aide sans rien signaler.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profil:
    cle: str
    # Libellé de l'ONGLET tel que l'utilisateur le lit. Jamais le nom du module.
    onglet: str
    libelle: str
    lieu: str
    guichet: str                 # « Pajemploi » | « CESU »
    aide: str
    socle: str                   # socle de la convention collective applicable
    resume: str
    # Blocs de contenu propres à ce profil (cf. `contenu.py`). Le tronc commun est écrit
    # une seule fois et vaut pour tous.
    specificites: list[str] = field(default_factory=list)
    # `False` = le profil existe dans la table mais son contenu n'est pas encore écrit.
    # On l'affiche quand même, en le disant : un profil absent se lirait « ça n'existe pas ».
    documente: bool = False


PROFILS: dict[str, Profil] = {
    "assmat": Profil(
        cle="assmat",
        onglet="Nounou",
        libelle="Assistante maternelle agréée",
        lieu="chez elle",
        guichet="Pajemploi",
        aide="CMG (complément de libre choix du mode de garde)",
        socle="Assistants maternels du particulier employeur",
        resume="Elle accueille votre enfant à son domicile, sous agrément du conseil "
               "départemental. Vous devenez son employeur : contrat, paie mensualisée, "
               "congés, préavis — tout s'applique.",
        specificites=["agrement", "indemnite_entretien", "mensualisation"],
        documente=True,
    ),
    "garde_domicile": Profil(
        cle="garde_domicile",
        onglet="Garde à domicile",
        libelle="Garde d'enfant à votre domicile",
        lieu="chez vous",
        guichet="Pajemploi",
        aide="CMG, tant qu'un enfant a moins de 6 ans",
        socle="Salariés du particulier employeur",
        resume="La personne vient garder l'enfant chez vous. Pas d'agrément requis, mais "
               "vous fournissez le lieu, le matériel et les repas — et vous restez "
               "l'employeur, avec les mêmes obligations.",
        specificites=["garde_partagee"],
    ),
    "aide_domicile": Profil(
        cle="aide_domicile",
        onglet="Aide à domicile",
        libelle="Aide ménagère, aide à la personne",
        lieu="chez vous",
        guichet="CESU",
        aide="Crédit d'impôt services à la personne (avance immédiate possible)",
        socle="Salariés du particulier employeur",
        resume="Ménage, repassage, courses, aide à l'autonomie. Même convention collective "
               "que l'assistante maternelle, mais un autre guichet — et la question qui "
               "précède toutes les autres : emploi direct, mandataire ou prestataire ?",
        specificites=["direct_mandataire_prestataire", "autonomie"],
    ),
    "autre_sap": Profil(
        cle="autre_sap",
        onglet="Service à la personne",
        libelle="Autre service à la personne",
        lieu="chez vous",
        guichet="CESU",
        aide="Crédit d'impôt services à la personne",
        socle="Salariés du particulier employeur",
        resume="Jardinage, bricolage, soutien scolaire, assistance informatique.",
        specificites=["direct_mandataire_prestataire"],
    ),
}

PROFIL_DEFAUT = "assmat"


def profil(cle: str | None) -> Profil:
    """Profil demandé, ou le profil par défaut. Une clé inconnue retombe sur `assmat`."""
    return PROFILS.get((cle or "").strip(), PROFILS[PROFIL_DEFAUT])
