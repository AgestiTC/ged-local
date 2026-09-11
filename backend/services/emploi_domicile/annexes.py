"""
Annexes au contrat — les documents qu'on redécouvre le jour où ils manquent
===========================================================================
Le contrat pose le cadre ; les annexes règlent ce qui arrive **un mardi à 16 h**. Elles
sont peu nombreuses, courtes, et systématiquement absentes des modèles trouvés en ligne —
parce qu'elles n'ont rien de contractuel : ce sont des **autorisations** et des
**renseignements**, et personne ne les écrit avant d'en avoir eu besoin.

Trois annexes, choisies sur ce critère :

1. **Autorisations** — sortir, transporter en voiture, photographier, donner un
   antipyrétique, faire appel aux secours. Sans écrit, la personne qui garde l'enfant doit
   choisir entre désobéir et ne rien faire.
2. **Personnes autorisées à venir chercher l'enfant** — la seule liste dont l'absence a une
   conséquence immédiate et irréversible.
3. **Fiche de renseignements** — santé, régime, habitudes, contacts d'urgence. Ce qu'on
   récite au téléphone à chaque fois, et qu'on oublie à moitié.

## Ce qu'elles ne sont pas

**Des clauses.** Une autorisation se retire du jour au lendemain ; une clause se renégocie.
Les mêler au contrat rendrait chaque changement d'habitude solennel — et donc jamais fait.
Elles sont donc des **documents séparés**, datés et signés à part.

## Les trous sont visibles, exprès

Comme le contrat : un champ non renseigné sort en **`[À COMPLÉTER]`**. Un trou visible se
remplit, un trou invisible se signe. Et ces annexes sont précisément celles qu'on signe sans
lire parce qu'elles ont l'air administratives.

⚠️ Aucun contenu n'est produit par l'IA : c'est du texte écrit, relu, et daté par le
millésime du module — comme le socle du contrat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from services.emploi_domicile.profils import Profil

MANQUE = "[À COMPLÉTER]"


def _v(valeur) -> str:
    """Valeur, ou marqueur visible. Jamais une chaîne vide qui passerait inaperçue."""
    texte = "" if valeur is None else str(valeur).strip()
    return texte or MANQUE


def _jolie_date(valeur: str | date | None) -> str:
    if not valeur:
        return MANQUE
    if isinstance(valeur, date):
        return valeur.strftime("%d/%m/%Y")
    try:
        return date.fromisoformat(str(valeur)[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return str(valeur)


@dataclass(frozen=True)
class Annexe:
    cle: str
    titre: str
    resume: str
    texte: str
    # Toutes les annexes ne valent pas pour tous les profils : une autorisation de sortie
    # n'a pas de sens pour une aide ménagère, et l'afficher ferait douter du reste.
    profils: tuple[str, ...] = ("assmat", "garde_domicile")


def _signatures(lieu: str | None = None) -> list[str]:
    """Le pied de page commun. Une annexe non datée ne prouve rien."""
    return [
        "",
        "---",
        "",
        f"Fait à {_v(lieu)}, le {MANQUE}, en deux exemplaires.",
        "",
        "| L'employeur | Le ou la salarié(e) |",
        "|---|---|",
        "| *signature* | *signature* |",
        "",
        "*Toute modification de cette annexe se fait par écrit, daté et signé des deux "
        "parties. Elle ne modifie pas le contrat de travail.*",
    ]


def _autorisations(champs: dict, qui: str) -> str:
    enfant = _v(champs.get("enfant_prenom"))
    a: list[str] = [
        "# Annexe 1 — Autorisations",
        "",
        f"Concernant **{enfant}**, confié(e) à **{qui}**.",
        "",
        "*Cochez ce que vous autorisez. Une ligne non cochée vaut refus : en cas de doute, "
        "la personne qui garde votre enfant s'abstiendra.*",
        "",
        "## Déplacements",
        "",
        "- [ ] **Sorties à pied** dans la commune (promenade, parc, bibliothèque, marché).",
        "- [ ] **Transport en véhicule**, en siège auto homologué adapté au poids et à la "
        "taille de l'enfant, pour les trajets liés à l'accueil.",
        "- [ ] **Sorties collectives** organisées par un relais petite enfance ou une "
        "structure équivalente.",
        "- [ ] **Baignade** (piscine, plan d'eau surveillé).",
        "",
        "Véhicule utilisé : " + _v(champs.get("vehicule")) + "  ",
        "Assurance du véhicule (compagnie et n° de contrat) : " + MANQUE,
        "",
        "## Santé",
        "",
        "- [ ] **Administrer un médicament** sur ordonnance nominative en cours de validité, "
        "l'ordonnance étant remise avec le médicament.",
        "- [ ] **Administrer un antipyrétique** (paracétamol) en cas de fièvre, après "
        "m'avoir prévenu(e), à la dose correspondant au poids de l'enfant.",
        "- [ ] **Appeler le 15 (SAMU) et faire hospitaliser** l'enfant en cas d'urgence, "
        "sans attendre de me joindre.",
        "",
        "**Dans tous les cas, l'appel aux secours ne requiert aucune autorisation.** Les "
        "cases ci-dessus règlent ce qui vient après : qui prévenir, et dans quel ordre.",
        "",
        "## Image",
        "",
        "- [ ] **Photographier ou filmer** l'enfant dans le cadre de l'accueil.",
        "- [ ] **Me transmettre** ces photos (message privé).",
        "- [ ] **Diffusion à des tiers** — réseaux sociaux, affichage, groupe de discussion.",
        "",
        "*La diffusion est une autorisation distincte de la prise de vue, et se retire à tout "
        "moment sur simple demande écrite, sans avoir à se justifier.*",
    ]
    return "\n".join(a + _signatures(champs.get("fait_a")))


def _personnes_autorisees(champs: dict, qui: str) -> str:
    enfant = _v(champs.get("enfant_prenom"))
    lignes: list[str] = [
        "# Annexe 2 — Personnes autorisées à venir chercher l'enfant",
        "",
        f"Concernant **{enfant}**, confié(e) à **{qui}**.",
        "",
        "**En dehors des personnes listées ci-dessous, l'enfant n'est remis à personne**, "
        "quel que soit le lien de parenté invoqué. Une pièce d'identité peut être demandée, "
        "y compris à quelqu'un de connu.",
        "",
        "| Nom et prénom | Lien avec l'enfant | Téléphone | Pièce d'identité vue le |",
        "|---|---|---|---|",
    ]
    lignes += [f"| {MANQUE} | {MANQUE} | {MANQUE} | |" for _ in range(4)]
    lignes += [
        "",
        "## Interdictions expresses",
        "",
        "Personne(s) à qui l'enfant **ne doit en aucun cas** être remis(e), le cas échéant :",
        "",
        f"- {MANQUE}",
        "",
        "*Si une décision de justice le prévoit, en joindre une copie à la présente annexe.*",
        "",
        "## Mise à jour",
        "",
        "Cette liste se modifie **par écrit**. Un ajout annoncé par téléphone ou par message "
        "ne suffit pas : le jour où il compte, personne ne se souvient de qui a dit quoi.",
    ]
    return "\n".join(lignes + _signatures(champs.get("fait_a")))


def _renseignements(champs: dict, qui: str) -> str:
    enfant = _v(champs.get("enfant_prenom"))
    lignes = [
        "# Annexe 3 — Fiche de renseignements",
        "",
        f"Concernant **{enfant}**, né(e) le {_jolie_date(champs.get('enfant_naissance'))}, "
        f"confié(e) à **{qui}**.",
        "",
        "## Contacts, dans l'ordre à appeler",
        "",
        "| Rang | Nom | Lien | Téléphone |",
        "|---|---|---|---|",
        f"| 1 | {MANQUE} | | {MANQUE} |",
        f"| 2 | {MANQUE} | | {MANQUE} |",
        f"| 3 | {MANQUE} | | {MANQUE} |",
        "",
        "Médecin traitant : " + MANQUE + " · Téléphone : " + MANQUE + "  ",
        "Numéro de sécurité sociale de rattachement : " + MANQUE,
        "",
        "## Santé",
        "",
        "- **Allergies** (alimentaires, médicamenteuses, autres) : " + MANQUE,
        "- **Traitement en cours** : " + MANQUE,
        "- **Antécédents à connaître** (asthme, convulsions, autre) : " + MANQUE,
        "- **Vaccinations** : joindre une copie des pages du carnet de santé.",
        "",
        "## Repas",
        "",
        "- **Régime particulier** (allergie, conviction, texture) : " + MANQUE,
        "- **Aliments non introduits à ce jour** : " + MANQUE,
        "- Repas fournis par : " + _v(champs.get("repas_fournis_par")),
        "",
        "## Rythme et habitudes",
        "",
        "- **Sieste** — heures, durée habituelle : " + MANQUE,
        "- **Endormissement** — ce qui aide, ce qui gêne : " + MANQUE,
        "- **Doudou, tétine** : " + MANQUE,
        "- **Propreté** — où en est l'enfant : " + MANQUE,
        "- **Ce qui le rassure quand il pleure** : " + MANQUE,
        "",
        "*Cette dernière ligne n'a rien d'administratif, et c'est souvent la plus utile des "
        "trois pages.*",
        "",
        "## Mise à jour",
        "",
        f"Fiche établie le {MANQUE}. **À relire tous les six mois** : un enfant de cet âge "
        "change de rythme plus vite qu'on ne pense à corriger le papier.",
    ]
    return "\n".join(lignes)


def disponibles(profil: Profil) -> list[dict]:
    """Les annexes proposées pour ce profil — libellé et raison d'être, sans le texte."""
    return [
        {"cle": a.cle, "titre": a.titre, "resume": a.resume}
        for a in _CATALOGUE if profil.cle in a.profils
    ]


def generer(cle: str, *, profil: Profil, champs: dict, salariee_nom: str | None) -> Annexe:
    """
    Le texte d'une annexe, en Markdown — même chaîne d'export que le contrat.

    `champs` est celui **du contrat** : l'annexe reprend le prénom de l'enfant, le lieu, le
    véhicule déjà saisis. Redemander ce que le contrat porte déjà est le meilleur moyen d'y
    glisser une divergence, et c'est la divergence qu'on remarque le jour du désaccord.
    """
    modele = next((a for a in _CATALOGUE if a.cle == cle), None)
    if modele is None:
        raise ValueError(f"Annexe inconnue : {cle!r}")
    if profil.cle not in modele.profils:
        raise ValueError(f"L'annexe « {modele.titre} » ne s'applique pas au profil "
                         f"« {profil.libelle} »")

    qui = (salariee_nom or "").strip() or MANQUE
    rendus = {
        "autorisations": _autorisations,
        "personnes-autorisees": _personnes_autorisees,
        "renseignements": _renseignements,
    }
    return Annexe(cle=modele.cle, titre=modele.titre, resume=modele.resume,
                  texte=rendus[modele.cle](champs, qui), profils=modele.profils)


_CATALOGUE: tuple[Annexe, ...] = (
    Annexe(cle="autorisations", titre="Autorisations",
           resume="Sorties, transport en voiture, soins, photos. Sans écrit, la personne qui "
                  "garde votre enfant doit choisir entre désobéir et ne rien faire.",
           texte=""),
    Annexe(cle="personnes-autorisees", titre="Personnes autorisées à venir chercher l'enfant",
           resume="La seule liste dont l'absence a une conséquence immédiate et irréversible.",
           texte=""),
    Annexe(cle="renseignements", titre="Fiche de renseignements",
           resume="Santé, repas, rythme, contacts d'urgence — ce qu'on récite au téléphone à "
                  "chaque fois, et qu'on oublie à moitié.",
           texte=""),
)
