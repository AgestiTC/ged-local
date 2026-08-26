"""
Q&R — Raisonnement temporel (fonctions PURES)
==============================================
Brique de l'Assistant « Poser une question » (E8). Isole toute la logique de DATES pour la
rendre **testable sans IA ni base** : normalisation de périodes, parsing d'expressions
françaises (« juillet 2018 »), lecture d'une période dans un nom de fichier (« 7-Juillet »),
couverture d'une date par une période, et durée humaine entre deux périodes.

Convention : une **période** = un couple `(debut, fin)` de `datetime.date` INCLUSIF (fin =
dernier jour du mois/année). Les fiches de paie sont mensuelles → période d'un mois.
"""
from __future__ import annotations

import calendar
import re
from datetime import date

# Mois français → numéro (formes longues + abréviations courantes, avec/sans accent).
MOIS_FR: dict[str, int] = {
    "janvier": 1, "janv": 1, "jan": 1,
    "fevrier": 2, "février": 2, "fev": 2, "fév": 2, "fevr": 2,
    "mars": 3, "mar": 3,
    "avril": 4, "avr": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7, "juil": 7, "jui": 7, "jul": 7,
    "aout": 8, "août": 8,
    "septembre": 9, "sept": 9, "sep": 9,
    "octobre": 10, "oct": 10,
    "novembre": 11, "nov": 11,
    "decembre": 12, "décembre": 12, "dec": 12, "déc": 12,
}

MOIS_NOM = {
    1: "janvier", 2: "février", 3: "mars", 4: "avril", 5: "mai", 6: "juin",
    7: "juillet", 8: "août", 9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre",
}


def mois_fr(nom: str) -> int | None:
    """Numéro de mois (1-12) depuis un libellé français, ou None. Insensible casse/accents partiels."""
    return MOIS_FR.get((nom or "").strip().lower())


def _fin_de_mois(annee: int, mois: int) -> date:
    return date(annee, mois, calendar.monthrange(annee, mois)[1])


def normaliser_periode(annee: int, mois: int | None = None) -> tuple[date, date]:
    """
    (debut, fin) INCLUSIF pour une année entière (mois=None) ou un mois précis.
    Ex. (2018, 7) → (2018-07-01, 2018-07-31) ; (2018, None) → (2018-01-01, 2018-12-31).
    """
    if mois is None:
        return date(annee, 1, 1), date(annee, 12, 31)
    return date(annee, mois, 1), _fin_de_mois(annee, mois)


def parse_date_iso(s: str) -> date | None:
    """Parse une date ISO souple : AAAA, AAAA-MM, AAAA-MM-JJ. None si non reconnue."""
    if not s:
        return None
    s = s.strip()
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", s)
    if not m:
        return None
    an = int(m.group(1))
    mo = int(m.group(2)) if m.group(2) else 1
    jo = int(m.group(3)) if m.group(3) else 1
    if not (1 <= mo <= 12) or not (1 <= jo <= 31):
        return None
    try:
        return date(an, mo, jo)
    except ValueError:
        return None


def periode_depuis_texte(texte: str) -> tuple[date, date] | None:
    """
    Extrait UNE période d'un texte libre français, par ordre de spécificité :
      « juillet 2018 » / « 07/2018 » / « 2018-07 » → le mois ;  « 2018 » → l'année entière.
    Renvoie (debut, fin) inclusif, ou None si aucune date exploitable. Best-effort (1ʳᵉ trouvée).
    """
    if not texte:
        return None
    t = texte.lower()

    # 1) « <mois> <année> » (ex. « juillet 2018 »)
    noms = "|".join(sorted(MOIS_FR, key=len, reverse=True))
    m = re.search(rf"\b({noms})\.?\s+(\d{{4}})\b", t)
    if m:
        mo = mois_fr(m.group(1))
        if mo:
            return normaliser_periode(int(m.group(2)), mo)

    # 2) « MM/AAAA » ou « AAAA-MM »
    m = re.search(r"\b(0?[1-9]|1[0-2])[/-](\d{4})\b", t)
    if m:
        return normaliser_periode(int(m.group(2)), int(m.group(1)))
    m = re.search(r"\b(\d{4})-(0?[1-9]|1[0-2])\b", t)
    if m:
        return normaliser_periode(int(m.group(1)), int(m.group(2)))

    # 3) année seule « 2018 » (bornée à un intervalle plausible pour éviter les faux positifs)
    m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
    if m:
        return normaliser_periode(int(m.group(1)), None)

    return None


def periode_fichier(nom: str) -> tuple[date, date] | None:
    """
    Devine la période d'un document depuis son NOM (signal de récupération, pas autoritaire) :
      « TC-Fiche paie 7-Juillet.pdf », « bulletin 07-2018.pdf », « paie juillet 2018 ».
    Cherche d'abord une vraie période texte ; à défaut un mois nommé/numéroté SANS année
    (renvoyé sur une année neutre 1900 → sert au tri/regroupement relatif, pas au filtre absolu).
    """
    if not nom:
        return None
    base = nom.rsplit(".", 1)[0].lower()
    pleine = periode_depuis_texte(base)
    if pleine:
        return pleine
    # mois nommé seul : « 7-juillet », « juillet », « 7 » entre séparateurs
    noms = "|".join(sorted(MOIS_FR, key=len, reverse=True))
    m = re.search(rf"\b({noms})\b", base)
    if m and mois_fr(m.group(1)):
        return normaliser_periode(1900, mois_fr(m.group(1)))
    return None


def couvre(periode: tuple[date, date], cible: date | tuple[date, date]) -> bool:
    """
    La `periode` (debut, fin inclusif) couvre-t-elle la `cible` (une date, ou une plage
    qu'elle doit CHEVAUCHER) ? Pour une question « en juillet 2018 », la cible est la plage
    du mois et un chevauchement suffit (une paie mensuelle « colle » au mois demandé).
    """
    deb, fin = periode
    if isinstance(cible, tuple):
        c_deb, c_fin = cible
        return deb <= c_fin and c_deb <= fin       # chevauchement d'intervalles
    return deb <= cible <= fin


def agreger_periodes(periodes: list[tuple[date, date]]) -> tuple[date, date] | None:
    """Enveloppe (min des débuts, max des fins) d'une liste de périodes. None si vide."""
    valides = [p for p in periodes if p]
    if not valides:
        return None
    return min(p[0] for p in valides), max(p[1] for p in valides)


def nb_mois_inclusif(debut: date, fin: date) -> int:
    """Nombre de mois entre deux dates, INCLUSIF (07/2018→11/2018 = 5). ≥ 1 si fin ≥ debut."""
    if fin < debut:
        return 0
    return (fin.year - debut.year) * 12 + (fin.month - debut.month) + 1


def duree_humaine(debut: date, fin: date) -> str:
    """
    Durée lisible entre deux périodes, en années/mois (« 1 an et 5 mois », « 7 mois »,
    « 2 ans »). Basée sur le nombre de mois inclusif. Chaîne vide si intervalle invalide.
    """
    total = nb_mois_inclusif(debut, fin)
    if total <= 0:
        return ""
    ans, mois = divmod(total, 12)
    bouts = []
    if ans:
        bouts.append(f"{ans} an{'s' if ans > 1 else ''}")
    if mois:
        bouts.append(f"{mois} mois")
    return " et ".join(bouts) if bouts else "moins d'un mois"


def libelle_periode(debut: date, fin: date) -> str:
    """
    Libellé court : « 2018 » (année entière) · « juillet 2018 » (un seul mois) ·
    « 07/2018 → 11/2018 » (intervalle).
    """
    if debut.year == fin.year and debut.month == 1 and fin.month == 12:
        return str(debut.year)
    if debut.year == fin.year and debut.month == fin.month:
        return f"{MOIS_NOM[debut.month]} {debut.year}"
    return f"{debut.month:02d}/{debut.year} → {fin.month:02d}/{fin.year}"
