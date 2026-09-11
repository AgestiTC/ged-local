"""
Récapitulatif imprimable, et la saison de la déclaration
========================================================
Deux choses que l'écran seul ne peut pas faire.

## 1. Un document qu'on emporte

On ne remplit pas sa déclaration devant Matothèque : on la remplit sur impots.gouv.fr, dans
un autre onglet, souvent sur un autre écran — et parfois avec un papier à côté. Un
récapitulatif **exporté** (PDF ou DOCX, via la chaîne d'export déjà en place) est ce qui
permet de cocher au fur et à mesure sans faire d'aller-retour.

Il reprend **exactement** ce que l'écran affiche, dans le même ordre — formulaire, puis case.
Un export qui réordonne ou qui résume produirait un second document de référence, divergent du
premier : c'est l'accident classique des exports, et il se paie au moment précis où l'on fait
confiance au papier plutôt qu'à l'écran.

Trois choses y sont **obligatoires**, parce que c'est le document qui survivra à la session :

- l'**avertissement** du millésime et la date à laquelle les cases ont été vérifiées — un
  papier non daté se relit l'année suivante comme s'il valait encore ;
- la **confiance** de chaque ligne, en toutes lettres — « à saisir » et « calculé » ne se
  recopient pas de la même main ;
- les **sources**, pour que chaque chiffre reste remontable jusqu'à sa pièce.

## 2. Savoir qu'on est en retard

Le rappel annuel du plan. Il **ne passe pas par un jalon** : un jalon s'ancre sur la date de
terme d'un dossier thématique (cf. `models/jalon`), et une déclaration de revenus n'appartient
à aucun dossier — l'y forcer demanderait d'inventer un dossier et une ancre qui n'existent pas.
Le signal est donc calculé **à l'affichage**, à partir de la date du jour : rien à stocker,
rien à semer, rien qui puisse se désynchroniser.

⚠️ **Aucune date limite n'est affirmée.** Elles changent chaque année et dépendent du
département ; les écrire en dur produirait exactement le genre d'erreur que cet onglet existe
pour éviter — une information fausse *qui a l'air sûre*. On dit la saison, et on renvoie au
portail pour les dates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from services.fiscalite import millesime

# Libellés des degrés de confiance, pour un document lu hors de l'écran (où l'infobulle
# n'existe plus). Le mot seul ne suffit pas sur papier.
CONFIANCES: dict[str, str] = {
    "calcule": "calculé à partir de vos données",
    "partiel": "partiel — une partie seulement des pièces est connue",
    "a_verifier": "à vérifier avant report",
    "a_saisir": "à saisir — Matothèque sait où, pas combien",
}


@dataclass(frozen=True)
class Campagne:
    """
    Où l'on en est dans l'année fiscale, sans affirmer aucune date limite.

    `annee_a_declarer` est **N-1** : c'est ce qu'on déclare au printemps. `etat` sert à
    choisir un ton, pas à calculer un délai.
    """

    etat: str                   # 'approche' | 'ouverte' | 'passee' | 'hors_saison'
    annee_a_declarer: int
    message: str


def campagne(aujourdhui: date) -> Campagne:
    """
    La saison, d'après le seul mois — volontairement grossier.

    Les bornes exactes de la campagne sont publiées chaque année et varient selon le
    département. Un compte à rebours au jour près serait faux pour une partie des gens, et
    faux de façon **invisible** : il aurait l'air d'une information vérifiée. Quatre saisons
    suffisent à déclencher le bon geste, et renvoyer au portail pour la date est la seule
    chose honnête à faire.
    """
    an = aujourdhui.year
    mois = aujourdhui.month
    a_declarer = an - 1

    if mois in (3,):
        return Campagne("approche", a_declarer,
                        f"La campagne de déclaration des revenus {a_declarer} ouvre "
                        "généralement en avril. C'est le moment de compléter ce qui manque "
                        "ci-dessous.")
    if mois in (4, 5, 6):
        return Campagne("ouverte", a_declarer,
                        f"La campagne de déclaration des revenus {a_declarer} est "
                        "habituellement ouverte. Les dates limites varient selon le "
                        "département et sont publiées sur impots.gouv.fr.")
    if mois in (7, 8):
        return Campagne("passee", a_declarer,
                        f"La campagne {a_declarer} est probablement close. Une déclaration "
                        "rectificative reste possible : le récapitulatif ci-dessous sert "
                        "aussi à ça.")
    return Campagne("hors_saison", a_declarer,
                    f"Hors campagne. Préparer la déclaration {a_declarer} maintenant évite "
                    "de chercher ses pièces en mai.")


def _ligne(l: dict) -> list[str]:
    """Une ligne de synthèse, telle que le routeur la sérialise, en Markdown."""
    case = l.get("case") or "case à trancher"
    montant = l.get("montant")
    tete = f"- **{case}** — {l['libelle']}"
    if montant:
        tete += f" : **{montant} €**"
    out = [tete]

    confiance = CONFIANCES.get(l.get("confiance", ""), l.get("confiance", ""))
    out.append(f"  - *{confiance}* · source : {l.get('provenance', '—')}")
    if l.get("note"):
        out.append(f"  - {l['note']}")
    if l.get("question"):
        # Une case non tranchée doit rester visible SUR LE PAPIER : c'est là qu'il y a
        # quelque chose à décider, et c'est ce qu'on oublie en recopiant.
        out.append(f"  - ❓ **À trancher** : {l['question']['intitule']}")
    for s in l.get("sources", []):
        annee = f" ({s['annee']}{'' if s.get('annee_confirmee') else ' ?'})" if s.get("annee") else ""
        out.append(f"  - pièce : {s['libelle']}{annee}")
    return out


def rendre(synthese: dict) -> str:
    """
    Le récapitulatif en Markdown, prêt pour la chaîne d'export PDF/DOCX existante.

    `synthese` est **le dictionnaire que rend `/fiscalite/synthese`**, pas une structure
    intermédiaire : l'écran et le papier lisent la même donnée, et ne peuvent donc pas
    diverger. Reconstruire la synthèse ici aurait créé un second chemin de calcul — le genre
    de duplication qui se découvre le jour où les deux ne disent plus la même chose.
    """
    an = synthese["annee"]
    m = synthese.get("millesime", {})
    lignes: list[str] = [
        f"# Aide à la déclaration — revenus {an}",
        "",
        f"*Préparé par Matothèque. Cases vérifiées le {m.get('verifie_le', '—')} "
        f"(millésime {m.get('annee', '—')}).*",
        "",
        f"> {m.get('avertissement', millesime.AVERTISSEMENT)}",
        "",
    ]

    if not synthese.get("formulaires"):
        lignes += [f"**Rien à reporter pour {an}** d'après ce que Matothèque connaît.", ""]

    for form in synthese.get("formulaires", []):
        lignes += [f"## {form['code']} — {form['libelle']}", ""]
        for l in form["lignes"]:
            lignes += _ligne(l)
        lignes.append("")

    # Les alertes expliquent ce qui a été examiné, ou ce qui manque. Elles sont mises À PART,
    # après les formulaires : rangées parmi les cases, elles passeraient pour des montants.
    if synthese.get("alertes"):
        lignes += ["## Ce que Matothèque n'a pas trouvé", ""]
        for a in synthese["alertes"]:
            lignes.append(f"- **{a['libelle']}** — {a.get('note') or ''}".rstrip(" —"))
        lignes.append("")

    # L'état de chaque source, y compris celles qui n'ont rien rendu : un module silencieux se
    # lit « à jour » alors qu'il peut n'avoir rien trouvé. Sur papier, l'omission est
    # définitive — personne n'ira vérifier l'écran.
    if synthese.get("contributeurs"):
        lignes += ["## Ce qui a été consulté", ""]
        for c in synthese["contributeurs"]:
            etat = {"ok": f"{c['nb_lignes']} ligne(s)", "vide": "rien trouvé",
                    "erreur": "INDISPONIBLE"}.get(c["etat"], c["etat"])
            lignes.append(f"- {c['libelle']} : {etat}")
        lignes.append("")

    lignes += [
        "---",
        "",
        "Matothèque ne calcule aucun impôt, ne transmet rien à l'administration et ne "
        "remplace pas la notice officielle. Vérifiez chaque montant avant de le reporter — "
        f"{m.get('url_officielle', millesime.URL_IMPOTS)}",
    ]
    return "\n".join(lignes)


def titre(annee: int) -> str:
    return f"Aide a la declaration - revenus {annee}"
