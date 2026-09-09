"""
Datation d'une pièce — à quelle année de revenus se rattache-t-elle ?
====================================================================
Le contributeur `ged_pieces` range d'abord les pièces par **date de fichier**, faute de
mieux : ce n'est pas la date de la dépense, et il le dit. Ce module donne de quoi
**trancher**, pièce par pièce.

**Aucune sortie réseau, et ce n'est pas un oubli.** L'année d'une attestation est *dans*
l'attestation : Tika a déjà extrait son texte à l'indexation (`documents.texte_extrait`).
Il n'y a donc rien à demander à Internet — et brancher une confirmation de sortie réseau
sur une lecture purement locale apprendrait à l'utilisateur que ces confirmations ne
veulent rien dire. On garde la fenêtre de confirmation pour ce qui sort vraiment.

**Aucun appel à l'IA non plus.** Repérer « 2026 » derrière « au titre de l'année » est un
travail d'expression régulière ; un LLM y ajouterait une chance de se tromper, un délai, et
une dépendance à un modèle chargé. La règle du module fiscal — *sourcé et déterministe* —
vaut aussi ici.

**Ce que le module rend : des candidats, jamais une décision.** Chaque candidat porte
l'**extrait de texte qui le justifie**, pour que l'utilisateur voie *pourquoi* on propose
cette année avant de la confirmer. Une proposition qu'on ne peut pas vérifier d'un coup
d'œil ne vaut pas mieux qu'une devinette.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

# On ne lit que le début du texte : sur une attestation, un relevé ou une facture, l'année
# de référence est en tête. Balayer 200 pages d'un rapport n'ajouterait que du bruit.
MAX_TEXTE = 20_000

# Fenêtre (en caractères) après un mot déclencheur dans laquelle une année compte double.
FENETRE_INDICE = 60

# Bornes de plausibilité. Au-delà de l'année prochaine, c'est une référence de contrat ou
# une coquille, pas une année de revenus.
ANNEE_MIN = 2000

# Mots qui, juste avant une année, en font une année DE RÉFÉRENCE et non une date
# quelconque (« imprimé le 12/03/2027 » ne dit rien de l'année des revenus).
INDICES = (
    "année", "annee", "exercice", "période", "periode", "au titre",
    "revenus", "imposition", "impôt", "impot", "déclaration", "declaration",
    "du 01/01", "du 1er janvier", "cotisations", "salaires versés", "salaires verses",
)

_RE_ANNEE = re.compile(r"\b(20\d{2})\b")
_RE_DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-](20\d{2})\b")
_RE_ESPACES = re.compile(r"\s+")


@dataclass
class Candidat:
    annee: int
    score: int
    occurrences: int
    extrait: str | None       # ce qui justifie la proposition — affiché tel quel
    motif: str                # « au titre de l'année », « date », « mentionnée »


def _extrait_autour(texte: str, position: int, largeur: int = 110) -> str:
    """Un morceau lisible autour d'une occurrence : c'est la preuve montrée à l'écran."""
    debut = max(0, position - largeur // 2)
    brut = texte[debut:debut + largeur]
    return _RE_ESPACES.sub(" ", brut).strip()


def candidats(texte: str | None, nom_fichier: str | None = None) -> list[Candidat]:
    """
    Années plausibles pour cette pièce, la plus probable en tête.

    Le classement combine trois signaux, du plus fort au plus faible :

    1. l'année suit un mot de référence (« au titre de l'année 2026 ») — signal décisif ;
    2. l'année figure dans le **nom du fichier** — l'utilisateur l'a souvent nommée lui-même,
       et c'est plus fiable qu'une date d'impression noyée dans le pied de page ;
    3. l'année est simplement présente — départage par le nombre d'occurrences.
    """
    limite = datetime.now(tz=timezone.utc).year + 1
    scores: dict[int, int] = {}
    occurrences: dict[int, int] = {}
    # Preuve retenue pour chaque année : celle du signal le PLUS FORT rencontré. Montrer
    # « 2026 apparaît quelque part » alors qu'on a trouvé « au titre de l'année 2026 »
    # affaiblirait à l'écran une proposition en réalité solide.
    preuves: dict[int, tuple[int, str | None, str]] = {}

    def _ajouter(annee: int, points: int, extrait: str | None, motif: str) -> None:
        if not (ANNEE_MIN <= annee <= limite):
            return
        scores[annee] = scores.get(annee, 0) + points
        occurrences[annee] = occurrences.get(annee, 0) + 1
        if points >= preuves.get(annee, (-1, None, ""))[0]:
            preuves[annee] = (points, extrait, motif)

    # 1) Le nom du fichier — souvent le plus sûr, et toujours présent.
    for m in _RE_ANNEE.finditer(nom_fichier or ""):
        _ajouter(int(m.group(1)), 6, nom_fichier, "nom du fichier")

    corps = (texte or "")[:MAX_TEXTE]
    bas = corps.lower()

    # 2) Les années précédées d'un mot de référence, dans une fenêtre courte.
    #
    # ⚠️ Deux bornes, et chacune corrige une erreur observée sur un cas réel :
    #   - la fenêtre s'arrête à la **fin de phrase**, sinon « au titre de l'année 2025.
    #     Document imprimé le 14/02/2026 » créditait AUSSI 2026 du signal fort ;
    #   - on ne retient que la **première** année de la fenêtre : « au titre de » qualifie
    #     l'année qui suit, pas toutes celles de la ligne.
    for indice in INDICES:
        depart = 0
        while (pos := bas.find(indice, depart)) != -1:
            depart = pos + len(indice)
            fenetre = corps[pos:pos + FENETRE_INDICE]
            fin = min((i for i in (fenetre.find(c) for c in ".;\n") if i > len(indice)),
                      default=len(fenetre))
            if (m := _RE_ANNEE.search(fenetre[:fin])) is not None:
                _ajouter(int(m.group(1)), 10, _extrait_autour(corps, pos), f"« {indice} »")

    # 3) Les dates complètes : plus parlantes qu'une année isolée, moins qu'un « au titre de ».
    for m in _RE_DATE.finditer(corps):
        _ajouter(int(m.group(1)), 3, _extrait_autour(corps, m.start()), "date")

    # 4) Les années simplement citées — départage, pas décision.
    for m in _RE_ANNEE.finditer(corps):
        _ajouter(int(m.group(1)), 1, _extrait_autour(corps, m.start()), "mentionnée")

    sortie = [
        Candidat(annee=a, score=s, occurrences=occurrences[a],
                 extrait=preuves[a][1], motif=preuves[a][2])
        for a, s in scores.items()
    ]
    # Score, puis occurrences, puis l'année la plus récente : à égalité, une pièce parle
    # plus souvent de l'année qu'on vient de vivre que d'une année ancienne.
    sortie.sort(key=lambda c: (c.score, c.occurrences, c.annee), reverse=True)
    return sortie[:5]
