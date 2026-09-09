"""
Registre des contributeurs fiscaux
==================================
Le cœur de l'onglet « Aide à la déclaration » : **l'écran ne connaît aucun module**.
Il affiche ce que les contributeurs enregistrés ici lui rendent.

Pourquoi ce détour plutôt qu'un écran qui interrogerait directement les modules : un
onglet fiscal écrit en dur obligerait à rouvrir la page à chaque module touchant à
l'argent (emploi à domicile, dons, travaux, revenus locatifs…). Un jour on oublierait, et
l'écran deviendrait **faux par omission** — le pire état possible ici, puisque rien à
l'écran ne signale ce qui manque. Ajouter un module fiscal = enregistrer un contributeur,
zéro ligne d'interface.

**Ce que produit un contributeur** : des `LigneFiscale`, c'est-à-dire *où reporter quoi*.
La question à laquelle tout cet écran répond est « j'ai payé ça — dans quelle case je le
mets ? » : d'où `formulaire` **et** `case` (le numéro seul ne dit pas où écrire — 7GA est
sur la 2042-RICI, pas sur la 2042), et d'où le droit de rendre `case=None` accompagnée
d'une `Question` quand la case dépend de la situation.

Trois règles portées par la structure, pas par la bonne volonté de l'appelant :

1. **Aucun montant sans source cliquable** — `sources` vide + `montant` renseigné est
   refusé à la construction. Une ligne non traçable devient « à saisir », avec sa raison.
2. **La confiance est une donnée** (`confiance`), pas un ton : « calculé sur 11 relevés »
   et « estimé d'après un contrat » ne se recopient pas de la même main.
3. **Ce qui manque s'affiche** — un contributeur sans donnée rend une liste vide *et* le
   routeur l'affiche quand même (« rien pour 2026, voici pourquoi »).

⚠️ **Aucun montant ni aucune règle de case ne vient de l'IA.** Les cases et leurs
conditions sont écrites en dur, datées et sourcées (voir `millesime.py`). Un LLM local qui
se trompe de numéro de case produit une erreur *indétectable*, recopiée telle quelle dans
une déclaration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger

log = get_logger(__name__)


# Nature d'une ligne. Volontairement sans Enum : comme `ressources.type` et
# `jalons.categorie`, ajouter une nature ne doit demander ni migration ni refonte.
NATURES = ("credit_impot", "reduction", "revenu", "charge", "piece", "alerte")

# Degré de confiance — AFFICHÉ, jamais décoratif.
#   calcule    : montant reconstitué à partir de données de l'application, sources à l'appui
#   partiel    : une partie seulement des pièces est connue (le total est donc un plancher)
#   a_verifier : proposition à confronter au document d'origine
#   a_saisir   : l'application sait OÙ, pas COMBIEN — c'est une réponse valable
CONFIANCES = ("calcule", "partiel", "a_verifier", "a_saisir")


@dataclass(frozen=True)
class Source:
    """
    D'où sort une ligne. Sans elle, pas de montant : c'est la règle n°1.

    `ref` est un identifiant interne (UUID de document, de contrat…) que le front
    transforme en lien ; `url` est un lien externe, ouvert après confirmation (le projet
    ne sort jamais sur le réseau sans un clic explicite).
    """

    libelle: str
    type: str = "document"          # 'document' | 'contrat' | 'fiche' | 'externe'
    ref: str | None = None
    url: str | None = None
    # Chemin INTERNE de l'application vers l'objet (« /dossiers/devenir-parent?onglet=contrat »).
    # Sans lui, le front devrait savoir où vit chaque type d'objet — c'est-à-dire connaître les
    # modules, précisément ce que le registre existe pour éviter. Le contributeur, lui, le sait.
    lien_interne: str | None = None
    # Année à laquelle la pièce est rattachée, et si c'est un FAIT ou une déduction.
    # `annee_confirmee=False` signifie « déduit de la date du fichier » — l'écran doit le
    # montrer et offrir de trancher, plutôt que de laisser croire à une précision qu'on n'a pas.
    annee: int | None = None
    annee_confirmee: bool = False


@dataclass(frozen=True)
class Option:
    valeur: str
    libelle: str


@dataclass(frozen=True)
class Question:
    """
    Ce qui manque pour trancher une case.

    C'est *l'*apport de l'écran : 7GA/7GB/7GC dépendent du rang de l'enfant, la résidence
    alternée bascule ailleurs, 7DB se double de 7DR pour les aides déjà perçues. Plutôt que
    de choisir à la place de l'utilisateur (ou de renoncer à afficher la ligne), le
    contributeur pose la question, et la réponse est mémorisée pour l'année.

    `options` vide = saisie libre. `cle` est stable dans le temps : c'est elle qui est
    stockée, et une clé renommée perdrait la réponse de l'an dernier.
    """

    cle: str
    intitule: str
    options: list[Option] = field(default_factory=list)
    aide: str | None = None


@dataclass
class LigneFiscale:
    """
    « Ce montant-là va dans cette case-là de ce formulaire-là, et voici pourquoi. »

    `montant=None` n'est pas un échec : savoir OÙ reporter sans savoir COMBIEN est déjà
    l'essentiel de ce qu'on cherche un dimanche de mai.
    """

    formulaire: str                       # « 2042-RICI » — le numéro de case seul ne suffit pas
    libelle: str
    case: str | None = None               # None tant qu'une `question` n'a pas tranché
    montant: Decimal | None = None
    nature: str = "piece"
    confiance: str = "a_saisir"
    sources: list[Source] = field(default_factory=list)
    note: str | None = None               # ce qu'il reste à faire, en français
    question: Question | None = None
    notice_url: str | None = None
    bareme_verifie_le: date | None = None

    def __post_init__(self) -> None:
        if self.nature not in NATURES:
            raise ValueError(f"nature inconnue : {self.nature!r} (attendu : {NATURES})")
        if self.confiance not in CONFIANCES:
            raise ValueError(f"confiance inconnue : {self.confiance!r} (attendu : {CONFIANCES})")
        # Règle n°1, tenue par la structure : un chiffre non traçable n'a rien à faire à
        # l'écran. Le laisser passer « juste cette fois » est exactement ce qui rendrait
        # l'onglet dangereux — un montant recopié dans une déclaration sans pouvoir
        # remonter à la pièce qui le justifie.
        if self.montant is not None and not self.sources:
            raise ValueError(
                f"montant sans source pour {self.formulaire} {self.case or '(case à trancher)'} : "
                "une ligne chiffrée doit pouvoir être remontée jusqu'à sa pièce"
            )


@runtime_checkable
class ContributeurFiscal(Protocol):
    """
    Ce qu'un module doit fournir pour apparaître dans l'onglet. Deux méthodes, pas plus.

    `reponses` porte les réponses déjà données pour l'année (cf. `Question`) : le
    contributeur s'en sert pour résoudre ses cases, et redemande sinon.
    """

    cle: str
    libelle: str

    async def annees(self, db: AsyncSession) -> list[int]:
        """Années pour lesquelles ce contributeur a quelque chose à dire."""
        ...

    async def contributions(
        self, db: AsyncSession, annee: int, reponses: dict[str, str]
    ) -> list[LigneFiscale]:
        ...


_CONTRIBUTEURS: dict[str, ContributeurFiscal] = {}


def enregistrer(contributeur: ContributeurFiscal) -> None:
    """
    Inscrit un contributeur. Idempotent par `cle` : un ré-enregistrement remplace, ce qui
    rend le rechargement de module inoffensif (et les tests lisibles).
    """
    _CONTRIBUTEURS[contributeur.cle] = contributeur
    log.info("Contributeur fiscal enregistré", cle=contributeur.cle)


def contributeurs() -> list[ContributeurFiscal]:
    """Les contributeurs, dans l'ordre d'enregistrement (ordre d'affichage secondaire)."""
    return list(_CONTRIBUTEURS.values())


def reinitialiser() -> None:
    """Vide le registre — réservé aux tests, qui doivent partir d'un état connu."""
    _CONTRIBUTEURS.clear()
