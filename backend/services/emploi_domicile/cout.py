"""
Reste à charge — le chiffre qui décide
=======================================
« Combien ça me coûte, à la fin du mois ? » est la question qu'on pose en premier et à
laquelle rien ne répondait. Le contrat donne un salaire mensualisé ; il ne dit ni ce que la
CAF verse, ni ce que le crédit d'impôt rend.

## Pourquoi ce n'est PAS le « simulateur brut → net → cotisations » du plan

Parce qu'il aurait fallu inventer des taux. Le passage du net au coût employeur dépend de
cotisations, d'exonérations et de plafonds que Matothèque ne connaît pas, qui changent chaque
année et qui varient selon la situation. Un simulateur faux est pire que pas de simulateur :
il produit un chiffre **qu'on croit**, et sur lequel on engage un budget.

Ce module ne calcule donc **que de l'arithmétique sur des montants que l'utilisateur a sous
les yeux** :

- le **salaire et les indemnités** viennent de son contrat (déjà calculés, formule affichée) ;
- le **CMG** vient de sa notification CAF — un montant notifié, pas estimé ;
- l'**avance immédiate** du crédit d'impôt vient de son relevé Pajemploi/CESU ;
- les **cotisations restant à sa charge** viennent de son bulletin, s'il en a un.

Chacun de ces montants est **saisi**, et chacun est **facultatif**. Une ligne non renseignée
n'est pas comptée comme zéro : elle est signalée comme manquante, et le total est annoncé
**incomplet**. C'est la même règle que le journal mensuel — un champ vide n'est pas un champ
à zéro.

## Ce que le total vaut

Un ordre de grandeur *pour décider*, pas un budget prévisionnel à l'euro. Il le dit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


def _euros(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Poste:
    """Une ligne du décompte. `saisi=False` = l'utilisateur ne l'a pas renseignée."""

    cle: str
    libelle: str
    montant: Decimal | None
    sens: str            # 'sortie' | 'entree'
    origine: str         # d'où vient le chiffre — c'est ce qui permet de le vérifier
    saisi: bool = True


@dataclass
class ResteACharge:
    postes: list[Poste]
    sorties: Decimal
    entrees: Decimal
    total: Decimal
    complet: bool
    remarques: list[str] = field(default_factory=list)


def calculer(
    *,
    salaire_mensuel: Decimal | None = None,
    frais_mensuels: Decimal | None = None,
    cmg: Decimal | None = None,
    avance_immediate: Decimal | None = None,
    cotisations: Decimal | None = None,
) -> ResteACharge:
    """
    Ce qui sort réellement du compte chaque mois.

    Tous les montants sont **mensuels** et **facultatifs**. `None` signifie « pas renseigné »
    et **jamais** « zéro » : confondre les deux ferait annoncer un reste à charge flatteur à
    quelqu'un qui n'a simplement pas encore saisi ses cotisations.
    """
    postes = [
        Poste("salaire", "Salaire net mensualisé", salaire_mensuel, "sortie",
              "calculé depuis votre contrat (taux horaire × heures mensualisées)"),
        Poste("frais", "Indemnités d'entretien, repas, kilomètres", frais_mensuels, "sortie",
              "estimées depuis votre contrat — elles sont dues par jour d'accueil réel"),
        Poste("cotisations", "Cotisations restant à votre charge", cotisations, "sortie",
              "à relever sur votre bulletin Pajemploi/CESU — Matothèque ne les calcule pas"),
        Poste("cmg", "CMG perçu (complément de libre choix du mode de garde)", cmg, "entree",
              "montant notifié par votre CAF, pas une estimation"),
        Poste("avance", "Avance immédiate du crédit d'impôt", avance_immediate, "entree",
              "à relever sur votre relevé Pajemploi/CESU"),
    ]
    for p in postes:
        p.saisi = p.montant is not None

    sorties = sum((p.montant for p in postes if p.sens == "sortie" and p.montant is not None),
                  Decimal("0"))
    entrees = sum((p.montant for p in postes if p.sens == "entree" and p.montant is not None),
                  Decimal("0"))

    manquants = [p for p in postes if not p.saisi]
    resultat = ResteACharge(
        postes=postes, sorties=_euros(sorties), entrees=_euros(entrees),
        total=_euros(sorties - entrees), complet=not manquants,
    )

    if manquants:
        # On nomme ce qui manque ET le sens de l'erreur : un manquant en « entrée » gonfle le
        # reste à charge, un manquant en « sortie » le minore. Sans ça, l'utilisateur ne sait
        # pas dans quel sens se tromper.
        gonfle = [p.libelle for p in manquants if p.sens == "entree"]
        minore = [p.libelle for p in manquants if p.sens == "sortie"]
        detail = []
        if minore:
            detail.append(f"il **manque** {', '.join(minore).lower()} — le vrai coût est donc "
                          "plus élevé que ce total")
        if gonfle:
            detail.append(f"il **manque** {', '.join(gonfle).lower()} — le vrai coût est donc "
                          "plus bas que ce total")
        resultat.remarques.append("Total **incomplet** : " + " ; ".join(detail) + ".")

    if resultat.complet:
        resultat.remarques.append(
            "Ordre de grandeur pour décider, pas un budget à l'euro : les indemnités sont "
            "dues par jour d'accueil réel, et varient donc d'un mois à l'autre."
        )

    resultat.remarques.append(
        "Matothèque **ne calcule aucune cotisation** et ne simule aucun passage du net au "
        "coût employeur : ces taux changent chaque année et dépendent de votre situation. "
        "Chaque montant ci-dessus vient d'un document que vous avez sous les yeux."
    )
    return resultat
