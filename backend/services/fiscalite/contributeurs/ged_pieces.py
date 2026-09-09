"""
Contributeur « ged-pieces » — les pièces fiscales déjà indexées
==============================================================
Le contributeur le plus modeste, et celui qui sert dès le premier jour : il ne calcule
rien, il **retrouve**. Les attestations de dons, les relevés Pajemploi, les factures de
services à la personne sont déjà dans la GED, déjà indexés, déjà catégorisés par
l'enrichissement IA — et pourtant on les cherche un par un chaque printemps.

Ce qu'il rend : **une ligne par nature de dépense reconnue**, avec la case où la reporter
et les pièces qui la justifient. C'est exactement la question posée : *« j'ai payé ça,
dans quelle case je le mets ? »* — l'application dit **où**, l'utilisateur saisit
**combien**.

⚠️ **Aucun montant n'est lu dans un document.** Ni par l'IA, ni par une expression
régulière : un total mal lu sur une attestation est une erreur *indétectable*, recopiée
telle quelle dans une déclaration. Toutes les lignes sortent donc en `a_saisir`, avec
leurs pièces à portée de clic. C'est délibérément moins ambitieux, et c'est ce qui rend
l'écran sûr.

**La détection est déterministe** (mots-clés sur le nom du fichier, la catégorie, les tags
et les mots-clés déjà posés). Pas d'appel à Ollama : classer une pièce n'a pas besoin d'un
modèle, et un modèle indisponible ne doit pas vider l'onglet.

**Le rattachement à une année se corrige.** Par défaut on retient la date de modification du
fichier (à défaut, sa date d'import), qui n'est pas la date de la dépense — la pièce est
alors marquée « déduite ». Le bouton « Dater » propose les années trouvées **dans le texte
déjà extrait** (voir `services/fiscalite/datation`) ; une fois confirmée, l'année vit dans
`documents.annee_fiscale` et prime définitivement. Rien de tout cela ne sort sur le réseau :
la date d'une attestation est dans l'attestation.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from logger import get_logger
from models.document import Document
from services.fiscalite import millesime
from services.fiscalite.registre import LigneFiscale, Option, Question, Source

log = get_logger(__name__)

# Nombre de pièces citées en source sur une ligne. Au-delà, la ligne devient illisible et
# n'apprend plus rien : le compte total reste dans la note.
MAX_SOURCES = 8


# ─── Natures reconnues ────────────────────────────────────────────────────────────────
# Chaque nature = des mots-clés (sur nom de fichier + métadonnées IA) et la case où aller.
# Les mots-clés sont volontairement peu nombreux et sans ambiguïté : mieux vaut ne pas
# reconnaître une pièce que la ranger dans la mauvaise case.
_NATURES: list[dict] = [
    {
        "cle": "garde_enfant",
        "libelle": "Frais de garde d'un enfant hors domicile",
        "mots": ("pajemploi", "assistante maternelle", "assistant maternel", "assmat",
                 "creche", "crèche", "halte-garderie", "garde d'enfant", "garde enfant"),
        # La case dépend du RANG de l'enfant : une case par enfant, dans l'ordre.
        "cases": ("7GA", "7GB", "7GC"),
        "question": Question(
            cle="nb_enfants_garde_hors_domicile",
            intitule="Combien d'enfants avez-vous fait garder hors de votre domicile ?",
            options=[Option("1", "1 enfant"), Option("2", "2 enfants"), Option("3", "3 enfants et plus")],
            aide="Il y a une case par enfant (7GA, puis 7GB, puis 7GC). Seuls les enfants de "
                 "moins de 6 ans ouvrent droit au crédit d'impôt.",
        ),
    },
    {
        "cle": "services_personne",
        "libelle": "Emploi d'un salarié à votre domicile",
        "mots": ("cesu", "chèque emploi service", "cheque emploi service",
                 "service à la personne", "service a la personne", "aide ménagère",
                 "aide menagere", "femme de ménage", "garde à domicile"),
        "cases": ("7DB",),
        "question": None,
        # Ligne compagne : les aides perçues se reportent ailleurs, et les oublier revient à
        # déclarer une dépense qu'on n'a pas supportée.
        "compagne": "7DR",
    },
    {
        "cle": "don",
        "libelle": "Dons à des associations",
        "mots": ("don ", "dons", "attestation fiscale", "reçu fiscal", "recu fiscal",
                 "association", "fondation"),
        "cases": ("7UD", "7UF"),
        "question": Question(
            cle="type_organisme_don",
            intitule="À quel type d'organisme avez-vous donné ?",
            options=[
                Option("7UD", "Aide aux personnes en difficulté (repas, soins, logement)"),
                Option("7UF", "Autre organisme d'intérêt général"),
            ],
            aide="Les deux existent : si vous avez donné aux deux, reportez chaque montant "
                 "dans sa case. Le taux n'est pas le même.",
        ),
    },
]


def _texte_indexable(doc: Document) -> str:
    """Tout ce sur quoi on cherche des mots-clés, en minuscules et en une seule chaîne."""
    morceaux = [doc.nom or ""]
    meta = doc.metadonnees_ia
    if meta is not None:
        morceaux += [meta.categorie or "", meta.sous_categorie or "", meta.resume or ""]
        morceaux += list(meta.tags or [])
        morceaux += list(meta.mots_cles or [])
    return " ".join(morceaux).lower()


def _annee_de(doc: Document) -> int | None:
    """
    Année rattachée à une pièce, dans l'ordre de fiabilité :

    1. **`annee_fiscale`** — l'utilisateur a tranché depuis le bouton « Dater » : c'est un
       fait, il prime sur tout le reste et ne se recalcule jamais ;
    2. la **date de modification** du fichier, à défaut la date d'import — approximation
       assumée : elle dit quand le fichier a été touché ou rangé, pas quand la dépense a eu
       lieu. D'où le marquage « déduit » sur la pièce, et l'invitation à vérifier.
    """
    if doc.annee_fiscale:
        return doc.annee_fiscale
    d = doc.date_modification_fichier or doc.date_import
    return d.year if d else None


def _resoudre_case(nature: dict, reponses: dict[str, str]) -> tuple[list[str], Question | None]:
    """
    Rend les cases retenues et, si elles ne peuvent pas l'être, la question qui tranche.

    Une seule case possible → rien à demander. Plusieurs → on regarde la réponse déjà
    donnée pour l'année ; à défaut, on rend la question et aucune case. Rendre une case au
    hasard « pour afficher quelque chose » serait pire que de demander.
    """
    cases: tuple[str, ...] = nature["cases"]
    question: Question | None = nature.get("question")
    if len(cases) == 1 or question is None:
        return list(cases), None

    reponse = (reponses.get(question.cle) or "").strip()
    if not reponse:
        return [], question

    # Réponse = un numéro de case (dons) ou un nombre d'enfants (garde).
    if reponse in cases:
        return [reponse], None
    if reponse.isdigit():
        return list(cases[: max(1, min(int(reponse), len(cases)))]), None
    return [], question


class GedPieces:
    """Contributeur fiscal : les pièces de l'année déjà présentes dans la GED."""

    cle = "ged-pieces"
    libelle = "Pièces déjà dans la GED"

    async def _pieces(self, db: AsyncSession, annee: int) -> dict[str, list[Document]]:
        """Documents de l'année, regroupés par nature reconnue. Une pièce = une nature."""
        result = await db.execute(
            select(Document).options(selectinload(Document.metadonnees_ia))
        )
        par_nature: dict[str, list[Document]] = {}
        for doc in result.scalars().all():
            if _annee_de(doc) != annee:
                continue
            texte = _texte_indexable(doc)
            for nature in _NATURES:
                if any(mot in texte for mot in nature["mots"]):
                    par_nature.setdefault(nature["cle"], []).append(doc)
                    break  # une pièce ne compte que pour la première nature reconnue
        return par_nature

    async def annees(self, db: AsyncSession) -> list[int]:
        """
        Années où l'on a trouvé au moins une pièce. On ajoute **toujours** l'année fiscale
        courante (N-1) : un onglet qui n'offrirait pas l'année en cours de déclaration
        laisserait croire qu'il n'y a rien à déclarer.
        """
        result = await db.execute(select(Document).options(selectinload(Document.metadonnees_ia)))
        trouvees = set()
        for doc in result.scalars().all():
            an = _annee_de(doc)
            if an and any(mot in _texte_indexable(doc) for n in _NATURES for mot in n["mots"]):
                trouvees.add(an)
        trouvees.add(datetime.now(tz=timezone.utc).year - 1)
        return sorted(trouvees, reverse=True)

    async def contributions(
        self, db: AsyncSession, annee: int, reponses: dict[str, str]
    ) -> list[LigneFiscale]:
        par_nature = await self._pieces(db, annee)
        lignes: list[LigneFiscale] = []

        for nature in _NATURES:
            docs = par_nature.get(nature["cle"], [])
            if not docs:
                continue

            sources = [
                Source(libelle=d.nom, type="document", ref=str(d.id),
                       annee=_annee_de(d), annee_confirmee=bool(d.annee_fiscale))
                for d in sorted(docs, key=lambda d: d.nom or "")[:MAX_SOURCES]
            ]
            reste = len(docs) - len(sources)
            a_dater = sum(1 for d in docs if not d.annee_fiscale)
            trouvees = (f"{len(docs)} pièce{'s' if len(docs) > 1 else ''} trouvée"
                        f"{'s' if len(docs) > 1 else ''} pour {annee}"
                        + (f" ({reste} non listée{'s' if reste > 1 else ''})" if reste else ""))
            # On ne parle de dates à vérifier que s'il en reste : une fois tout daté, la
            # phrase deviendrait un avertissement permanent qu'on cesse de lire.
            datation = (f" {a_dater} date{'s' if a_dater > 1 else ''} déduite"
                        f"{'s' if a_dater > 1 else ''} du fichier — bouton « Dater » pour "
                        f"trancher." if a_dater else " Toutes les dates ont été confirmées.")

            cases, question = _resoudre_case(nature, reponses)

            if question is not None:
                # Case indéterminée : on le dit, et on donne de quoi trancher. C'est la
                # situation la plus utile de l'écran, pas un cas dégradé.
                lignes.append(LigneFiscale(
                    formulaire=millesime.formulaire_de(nature["cases"][0]),
                    case=None,
                    libelle=nature["libelle"],
                    nature="piece",
                    confiance="a_verifier",
                    sources=sources,
                    note=f"{trouvees}. La case dépend de votre situation — répondez ci-dessous."
                         + datation,
                    question=question,
                    notice_url=millesime.URL_IMPOTS,
                    bareme_verifie_le=millesime.VERIFIE_LE,
                ))
                continue

            for i, code in enumerate(cases):
                c = millesime.case(code)
                lignes.append(LigneFiscale(
                    formulaire=millesime.formulaire_de(code),
                    case=code,
                    libelle=c.libelle if c else nature["libelle"],
                    nature="credit_impot",
                    confiance="a_saisir",
                    # Les pièces ne sont citées que sur la première case : les répéter sur
                    # 7GA, 7GB et 7GC laisserait croire que chaque enfant a les mêmes.
                    sources=sources if i == 0 else [],
                    note=((f"{trouvees}. Montant à saisir : Matothèque ne lit aucun chiffre "
                           f"dans un document.{datation}") if i == 0 else
                          "Répartissez selon l'enfant concerné."),
                    notice_url=millesime.URL_IMPOTS,
                    bareme_verifie_le=millesime.VERIFIE_LE,
                ))

            # Ligne compagne : la case des aides à déduire, qui n'a aucune pièce à elle mais
            # dont l'oubli fausse la déclaration au premier euro.
            compagne = nature.get("compagne")
            if compagne:
                cc = millesime.case(compagne)
                lignes.append(LigneFiscale(
                    formulaire=millesime.formulaire_de(compagne),
                    case=compagne,
                    libelle=cc.libelle if cc else "Aides perçues — à déduire",
                    nature="credit_impot",
                    confiance="a_saisir",
                    note="À ne pas oublier si vous avez perçu une aide (CMG, APA, PCH, comité "
                         "d'entreprise) ou l'avance immédiate du crédit d'impôt.",
                    notice_url=millesime.URL_IMPOTS,
                    bareme_verifie_le=millesime.VERIFIE_LE,
                ))

        return lignes


def installer() -> None:
    from services.fiscalite.registre import enregistrer
    enregistrer(GedPieces())
