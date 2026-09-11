"""
Comparer deux candidates — montrer ce qui les sépare
=====================================================
Après trois visites, les fiches se ressemblent toutes : chacune a été remplie un soir, en
rentrant, avec l'impression encore fraîche. Un mois plus tard, on ne sait plus laquelle
disait quoi — et on choisit sur le souvenir du dernier entretien, qui n'est pas le meilleur
critère.

## Ce que ce module fait, et ne fait pas

Il **ne classe pas**. Aucun score, aucune recommandation, aucune moyenne pondérée : la
décision tient à des choses qu'aucune grille ne capture (le courant qui passe, la maison, le
trajet réel un matin de pluie), et un classement produit par l'application serait suivi
précisément parce qu'il a l'air objectif.

Il **met en regard**, et surtout il **signale ce qui diffère**. C'est le seul travail qu'une
machine fait mieux qu'une relecture : repérer que sur douze questions, deux seulement ont
reçu des réponses opposées. Ce sont ces deux-là qui décident, et ce sont elles qu'on ne voit
plus en relisant deux fiches l'une après l'autre.

## Trois façons de différer, et une seule qui compte

- **Divergence** : l'une répond `ok`, l'autre `non`. C'est le signal fort.
- **Nuance** : `ok` d'un côté, `reserve` de l'autre. Utile, moins tranchant.
- **Lacune** : l'une a répondu, l'autre pas. **Ce n'est pas une différence entre les
  personnes, c'est un trou dans l'entretien** — et le confondre avec un désaccord ferait
  écarter quelqu'un à qui on a simplement oublié de poser la question.

Cette distinction est la raison d'être du module. Une comparaison qui traite une case vide
comme un « non » est pire qu'une absence de comparaison.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

# Poids des avis, pour décider si deux réponses divergent. Ce n'est PAS un score : rien ne
# les additionne, ils servent uniquement à mesurer l'écart entre deux réponses à la même
# question.
_RANG = {"ok": 2, "reserve": 1, "non": 0}


@dataclass
class Ecart:
    cle: str
    question: str
    groupe: str
    # Une entrée par personne, dans l'ordre demandé. `None` = pas de réponse.
    avis: list[str | None]
    textes: list[str | None]
    nature: str          # 'divergence' | 'nuance' | 'lacune'


@dataclass
class Comparaison:
    personnes: list[dict]
    ecarts: list[Ecart] = field(default_factory=list)
    # Ce qui ne vient pas de la checklist : tarif, agrément, places, impression.
    reperes: list[dict] = field(default_factory=list)
    remarques: list[str] = field(default_factory=list)


def _dec(valeur) -> Decimal | None:
    """Un tarif annoncé est du texte libre (« 4,20 € net/h ») : on en extrait le nombre."""
    if valeur is None:
        return None
    garde, vu_separateur = [], False
    for ch in str(valeur):
        if ch.isdigit():
            garde.append(ch)
        elif ch in ",." and not vu_separateur and garde:
            garde.append(".")
            vu_separateur = True
        elif garde:
            break            # on s'arrête au premier nombre : « 4,20 € + 3,50 » → 4.20
    try:
        return Decimal("".join(garde)) if garde else None
    except InvalidOperation:
        return None


def _nature(avis: list[str | None]) -> str | None:
    """
    Comment ces réponses diffèrent — ou `None` si elles ne diffèrent pas.

    Une lacune l'emporte sur tout le reste : tant qu'une personne n'a pas été interrogée, on
    ne sait pas si elle est d'accord, et prétendre le contraire est la faute que ce module
    existe pour éviter.
    """
    connus = [a for a in avis if a in _RANG]
    if len(connus) < len(avis):
        # Au moins une réponse manque. S'il n'y en a aucune, il n'y a rien à dire du tout.
        return "lacune" if connus else None
    if len(set(connus)) == 1:
        return None
    return "divergence" if max(map(_RANG.get, connus)) - min(map(_RANG.get, connus)) >= 2 \
        else "nuance"


def comparer(personnes: list[dict], checklist: list[dict]) -> Comparaison:
    """
    Met deux fiches (ou plus) en regard.

    `personnes` : `{id, nom, prenom, tarif_annonce, places, agrement_echeance, statut,
    impression, reponses}` — `reponses` étant la **fusion** des entretiens de la personne,
    la plus récente réponse l'emportant (c'est ce qu'on a appris en dernier).

    Aucun classement n'est rendu, et c'est délibéré : la décision tient à ce qu'aucune grille
    ne capture, et un ordre produit par l'application serait suivi parce qu'il a l'air
    objectif.
    """
    comp = Comparaison(personnes=[{k: p.get(k) for k in
                                   ("id", "nom", "prenom", "statut", "impression")}
                                  for p in personnes])

    if len(personnes) < 2:
        comp.remarques.append("Sélectionnez au moins deux personnes à comparer.")
        return comp

    # ── Les repères chiffrés, mis en regard sans être notés ───────────────────────────
    tarifs = [_dec(p.get("tarif_annonce")) for p in personnes]
    comp.reperes.append({
        "cle": "tarif", "libelle": "Tarif horaire annoncé",
        "valeurs": [p.get("tarif_annonce") for p in personnes],
        "note": ("Le tarif seul ne dit pas le coût : les indemnités d'entretien et de repas "
                 "s'y ajoutent, et elles varient d'une personne à l'autre."
                 if any(t is not None for t in tarifs) else
                 "Aucun tarif annoncé n'a été noté — c'est la première question du téléphone."),
    })
    comp.reperes.append({
        "cle": "places", "libelle": "Places de l'agrément",
        "valeurs": [p.get("places") for p in personnes],
        "note": "Le nombre de mineurs accueillis simultanément décide du rythme de la journée.",
    })

    echeances = [p.get("agrement_echeance") for p in personnes]
    perimees = [i for i, e in enumerate(echeances) if _perime(e)]
    comp.reperes.append({
        "cle": "agrement", "libelle": "Agrément valable jusqu'au",
        "valeurs": [str(e) if e else None for e in echeances],
        "note": ("⚠️ Un agrément est périmé : sans agrément valide, il n'y a ni aide ni "
                 "accueil légal." if perimees else
                 "La date qu'on oublie de regarder."),
    })
    comp.reperes.append({
        "cle": "impression", "libelle": "Impression après visite (1 à 5)",
        "valeurs": [p.get("impression") for p in personnes],
        "note": ("Volontairement à part des réponses : une grille parfaitement remplie ne "
                 "fait pas une bonne rencontre, et l'inverse est vrai aussi."),
    })

    # ── Les écarts de la checklist ────────────────────────────────────────────────────
    for groupe in checklist:
        for question in groupe["questions"]:
            cle = question["cle"]
            brut = [(p.get("reponses") or {}).get(cle) or {} for p in personnes]
            avis = [(r.get("avis") or None) for r in brut]
            nature = _nature(avis)
            if nature is None:
                continue
            comp.ecarts.append(Ecart(
                cle=cle, question=question["texte"], groupe=groupe["titre"],
                avis=avis, textes=[(r.get("texte") or None) for r in brut], nature=nature,
            ))

    # Les divergences d'abord : ce sont elles qui décident. Les lacunes en dernier — elles
    # ne disent rien des personnes, seulement de ce qu'on n'a pas demandé.
    ordre = {"divergence": 0, "nuance": 1, "lacune": 2}
    comp.ecarts.sort(key=lambda e: (ordre[e.nature], e.groupe, e.cle))

    nb_divergences = sum(1 for e in comp.ecarts if e.nature == "divergence")
    nb_lacunes = sum(1 for e in comp.ecarts if e.nature == "lacune")

    if not comp.ecarts:
        comp.remarques.append(
            "Aucun écart : soit les réponses concordent, soit la checklist n'a pas encore été "
            "remplie pour ces personnes. Dans le second cas, la comparaison ne peut rien dire."
        )
    elif nb_divergences == 0:
        comp.remarques.append(
            "Aucune réponse franchement opposée. Ce qui reste — nuances et questions non "
            "posées — ne suffit pas à départager : la décision se jouera ailleurs."
        )
    if nb_lacunes:
        comp.remarques.append(
            f"{nb_lacunes} question{'s' if nb_lacunes > 1 else ''} n'{'ont' if nb_lacunes > 1 else 'a'} "
            "reçu de réponse que d'un côté. **Ce n'est pas une différence entre les personnes, "
            "c'est un trou dans l'entretien** — le confondre avec un désaccord ferait écarter "
            "quelqu'un à qui on a simplement oublié de poser la question."
        )

    comp.remarques.append(
        "Matothèque ne classe pas et ne recommande personne : ce qui décide — le courant qui "
        "passe, le lieu, le trajet un matin de pluie — n'entre dans aucune grille."
    )
    return comp


def _perime(echeance) -> bool:
    if not echeance:
        return False
    try:
        valeur = echeance if isinstance(echeance, date) else date.fromisoformat(str(echeance)[:10])
    except ValueError:
        return False
    return valeur < date.today()
