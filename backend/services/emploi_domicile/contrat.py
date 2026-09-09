"""
Génération du contrat — un texte éditable, pas un PDF figé
==========================================================
Produit le contrat en **Markdown**, à partir des champs saisis et des calculs de
`calcul.py`. Ce format n'est pas un détail :

- il se **relit et se corrige à l'écran** avant export — l'application propose, l'humain
  assume, comme pour le résumé IA d'une ressource ;
- il se convertit en **PDF et en DOCX** par les briques déjà en place
  (`POST /api/export/{pdf,docx}`), sans gabarit à maintenir ni dépendance nouvelle.

## Un tronc commun, des blocs par profil

Assistante maternelle et aide à domicile relèvent de la **même convention collective** :
identité des parties, essai, horaires, salaire, congés, préavis et rupture sont identiques.
Seuls quelques blocs changent — l'agrément et l'indemnité d'entretien n'existent que chez
l'assistante maternelle, le lieu d'exécution et les tâches chez l'aide à domicile. C'est
exactement ce qui justifiait un module `emploi-domicile` et non un module `nounou`.

## Ce que le contrat NE fait pas

- **Il n'invente aucun montant réglementaire.** Les chiffres viennent des champs saisis ; le
  SMIC et le minimum garanti, quand ils servent à un contrôle, viennent des Paramètres.
- **Il n'est pas rédigé par l'IA.** Un modèle qui reformule une clause de préavis produit
  une erreur indétectable dans un document qui engage juridiquement.
- **Il ne remplace pas la convention collective**, et le document le dit lui-même en pied.

⚠️ Un champ non renseigné est rendu comme **`[À COMPLÉTER]`**, jamais deviné ni omis : un
trou visible se remplit, un trou invisible se signe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from services.emploi_domicile.calcul import Frais, Mensualisation, _fr
from services.emploi_domicile.profils import Profil

MANQUANT = "[À COMPLÉTER]"

AVERTISSEMENT_PIED = (
    "Ce document a été préparé avec Matothèque à partir des informations saisies. Il ne "
    "remplace ni la convention collective applicable, ni le code du travail, ni un conseil "
    "juridique : relisez-le et adaptez-le avant signature."
)


@dataclass
class Partie:
    nom: str | None = None
    adresse: str | None = None
    telephone: str | None = None
    email: str | None = None


def _v(valeur) -> str:
    """Valeur affichable, ou marqueur explicite. Le vide se remplit ; l'absent se signe."""
    if valeur is None:
        return MANQUANT
    texte = str(valeur).strip()
    return texte or MANQUANT


def _montant(valeur: Decimal | None, suffixe: str = " €") -> str:
    return f"{_fr(valeur)}{suffixe}" if valeur is not None else MANQUANT


def _jolie_date(valeur: str | date | None) -> str:
    if not valeur:
        return MANQUANT
    d = valeur if isinstance(valeur, date) else None
    if d is None:
        try:
            d = date.fromisoformat(str(valeur))
        except ValueError:
            return str(valeur)
    return d.strftime("%d/%m/%Y")


def generer(
    *,
    profil: Profil,
    employeur: Partie,
    salariee: Partie,
    champs: dict,
    mensualisation: Mensualisation | None,
    frais: Frais | None,
) -> str:
    """Le contrat complet, en Markdown. `champs` porte tout ce qui a été saisi à l'écran."""
    assmat = profil.cle == "assmat"
    lignes: list[str] = []
    a = lignes.append

    titre = ("Contrat de travail — assistant(e) maternel(le) agréé(e)" if assmat
             else f"Contrat de travail — {profil.libelle.lower()}")
    a(f"# {titre}")
    a("")
    a(f"*Convention collective applicable : socle « {profil.socle} ». "
      f"Déclaration auprès de **{profil.guichet}**.*")
    a("")

    # ── Les parties ───────────────────────────────────────────────────────────────────
    a("## Entre les soussignés")
    a("")
    a(f"**L'employeur** — {_v(employeur.nom)}  ")
    a(f"Adresse : {_v(employeur.adresse)}  ")
    a(f"Téléphone : {_v(employeur.telephone)} · Courriel : {_v(employeur.email)}")
    a("")
    a(f"**Le ou la salarié(e)** — {_v(salariee.nom)}  ")
    a(f"Adresse : {_v(salariee.adresse)}  ")
    a(f"Téléphone : {_v(salariee.telephone)} · Courriel : {_v(salariee.email)}")
    if assmat:
        a("")
        a(f"Agrément n° {_v(champs.get('agrement_numero'))}, "
          f"valable jusqu'au {_jolie_date(champs.get('agrement_echeance'))}, "
          f"pour l'accueil simultané de {_v(champs.get('places'))} mineur(s).")
    a("")

    # ── L'enfant / l'objet ────────────────────────────────────────────────────────────
    if assmat:
        a("## Article 1 — Enfant accueilli")
        a("")
        a(f"Prénom et nom : {_v(champs.get('enfant_nom'))}  ")
        a(f"Né(e) le : {_jolie_date(champs.get('enfant_naissance'))}  ")
        a(f"Lieu d'accueil : {_v(champs.get('lieu_accueil') or salariee.adresse)}")
    else:
        a("## Article 1 — Objet et lieu d'exécution")
        a("")
        a(f"Nature des tâches : {_v(champs.get('taches'))}  ")
        a(f"Lieu d'exécution : {_v(champs.get('lieu_accueil') or employeur.adresse)}")
    a("")

    # ── Date d'effet, adaptation, essai ───────────────────────────────────────────────
    a("## Article 2 — Date d'effet, adaptation et période d'essai")
    a("")
    a(f"Le contrat prend effet le **{_jolie_date(champs.get('date_debut'))}**, pour une durée "
      "indéterminée.")
    a("")
    if assmat:
        a(f"**Période d'adaptation** : {_v(champs.get('adaptation'))}. Elle permet à l'enfant "
          "et à l'accueillant(e) de se connaître progressivement ; elle est rémunérée selon "
          "les heures réellement effectuées.")
        a("")
    a(f"**Période d'essai** : {_v(champs.get('essai'))}. Pendant cette période, chaque partie "
      "peut rompre le contrat sans avoir à motiver sa décision, en respectant le délai de "
      "prévenance prévu par la convention collective.")
    a("")

    # ── Horaires ──────────────────────────────────────────────────────────────────────
    a("## Article 3 — Jours et horaires")
    a("")
    a(f"Jours d'accueil : {_v(champs.get('jours'))}  ")
    a(f"Horaires : {_v(champs.get('horaires'))}  ")
    a(f"Durée hebdomadaire convenue : {_v(champs.get('heures_semaine'))} heures  ")
    a(f"Nombre de jours d'accueil par semaine : {_v(champs.get('jours_semaine'))}")
    a("")
    a("Toute heure effectuée au-delà de l'horaire convenu est rémunérée. Au-delà de 45 heures "
      "par semaine, les heures sont majorées au taux prévu à l'article 4.")
    a("")

    # ── Rémunération ──────────────────────────────────────────────────────────────────
    a("## Article 4 — Rémunération")
    a("")
    if mensualisation is not None:
        regime = ("**année complète**" if mensualisation.regime == "complete"
                  else "**année incomplète**")
        a(f"Le salaire est **mensualisé** : il est lissé sur douze mois et versé chaque mois "
          f"pour un montant identique, y compris les mois sans accueil. Régime retenu : {regime}.")
        a("")
        a(f"- Taux horaire : **{_montant(mensualisation.taux_horaire)}**")
        a(f"- Durée hebdomadaire : {_fr(mensualisation.heures_semaine)} heures")
        a(f"- Nombre de semaines d'accueil : {mensualisation.semaines}")
        a(f"- Heures mensualisées : **{_fr(mensualisation.heures_mensualisees)} heures**")
        a(f"- **Salaire mensuel brut : {_montant(mensualisation.salaire_mensuel)}**")
        a("")
        a(f"> Calcul : {mensualisation.formule}")
        a("")
        for ligne in mensualisation.detail:
            a(f"> {ligne}")
        a("")
    else:
        a(f"Taux horaire : {_montant(champs.get('taux_horaire'))} — "
          f"salaire mensualisé : {MANQUANT}.")
        a("")
    a(f"Majoration des heures au-delà de 45 h par semaine : "
      f"{_v(champs.get('majoration_pct'))} %.")
    a("")
    a(f"Le salaire est versé le {_v(champs.get('jour_paie'))} de chaque mois. La déclaration "
      f"est effectuée auprès de **{profil.guichet}**, qui édite le bulletin de salaire.")
    a("")

    # ── Indemnités ────────────────────────────────────────────────────────────────────
    a("## Article 5 — Indemnités et frais")
    a("")
    a("Ces sommes ne constituent **pas** du salaire : elles ne sont pas soumises à cotisations "
      "et sont dues **par jour d'accueil réellement effectué**.")
    a("")
    if assmat:
        a(f"- Indemnité d'entretien : **{_montant(champs.get('entretien_jour'))} par jour "
          "d'accueil** — elle couvre les jeux, le matériel, l'eau, l'électricité et le chauffage.")
    a(f"- Repas : {_montant(champs.get('repas_jour'))} par jour "
      f"({_v(champs.get('repas_fourni_par'))} les fournit).")
    a(f"- Frais kilométriques : {_montant(champs.get('tarif_km'))} par kilomètre, pour environ "
      f"{_v(champs.get('km_semaine'))} km par semaine.")
    if frais is not None:
        a("")
        a(f"> Estimation mensuelle des indemnités : **{_montant(frais.total_mensuel)}**.")
        for ligne in frais.detail:
            a(f"> {ligne}")
    a("")

    # ── Congés et absences ────────────────────────────────────────────────────────────
    a("## Article 6 — Congés payés et absences")
    a("")
    a(f"Dates de congés : {_v(champs.get('conges'))}. Elles sont arrêtées d'un commun accord "
      "et communiquées dans les délais prévus par la convention collective.")
    a("")
    if mensualisation is not None and mensualisation.regime == "incomplete":
        a("En **année incomplète**, les congés payés sont réglés **en plus** du salaire "
          "mensualisé : ils ne sont pas compris dans le lissé.")
    else:
        a("En **année complète**, les congés payés sont compris dans le salaire mensualisé.")
    a("")
    a(f"Absences de l'enfant : {_v(champs.get('absences'))}.  ")
    a("En dehors des cas expressément prévus ci-dessus, une absence du fait de l'employeur "
      "ne suspend pas le versement du salaire mensualisé.")
    a("")
    a(f"Jours fériés travaillés : {_v(champs.get('feries'))}.")
    a("")

    # ── Autorisations (assmat) ────────────────────────────────────────────────────────
    if assmat:
        a("## Article 7 — Autorisations et santé")
        a("")
        a(f"- Sorties : {_v(champs.get('autorisation_sorties'))}")
        a(f"- Transport en véhicule : {_v(champs.get('autorisation_transport'))}")
        a(f"- Photographies : {_v(champs.get('autorisation_photos'))}")
        a(f"- Soins d'urgence : {_v(champs.get('autorisation_soins'))}")
        a(f"- Projet d'accueil individualisé (allergie, traitement) : "
          f"{_v(champs.get('pai'))}")
        a("")
        a(f"Personnes à prévenir en cas d'urgence : {_v(champs.get('urgence'))}")
        a("")

    # ── Assurances ────────────────────────────────────────────────────────────────────
    numero = 8 if assmat else 7
    a(f"## Article {numero} — Assurances")
    a("")
    a(f"Responsabilité civile professionnelle : {_v(champs.get('assurance_rc'))}.  ")
    a(f"Assurance automobile couvrant le transport d'enfants : "
      f"{_v(champs.get('assurance_auto'))}.")
    a("")
    a("Une copie des attestations en cours de validité est annexée au présent contrat.")
    a("")

    # ── Rupture ───────────────────────────────────────────────────────────────────────
    a(f"## Article {numero + 1} — Rupture du contrat")
    a("")
    if assmat:
        a("Le retrait de l'enfant par l'employeur met fin au contrat. Il est notifié par écrit "
          "et ouvre un préavis dont la durée dépend de l'ancienneté, selon la convention "
          "collective.")
    else:
        a("La rupture du contrat par l'employeur est notifiée par écrit et ouvre un préavis "
          "dont la durée dépend de l'ancienneté, selon la convention collective.")
    a("")
    a("À la fin du contrat sont dus, selon les cas : l'indemnité de rupture, la "
      "**régularisation de la mensualisation** (comparaison entre ce qui a été payé et ce qui "
      "a été réellement effectué) et les congés payés non pris. L'employeur remet le solde de "
      "tout compte, le certificat de travail et l'attestation destinée à France Travail.")
    a("")

    # ── Signatures ────────────────────────────────────────────────────────────────────
    a(f"## Article {numero + 2} — Signatures")
    a("")
    a(f"Fait à {_v(champs.get('fait_a'))}, le {_jolie_date(champs.get('fait_le'))}, "
      "en deux exemplaires originaux.")
    a("")
    a("| L'employeur | Le ou la salarié(e) |")
    a("|---|---|")
    a("| *Signature précédée de la mention « lu et approuvé »* | *Signature précédée de la "
      "mention « lu et approuvé »* |")
    a("|  |  |")
    a("")
    a("---")
    a("")
    a(f"*{AVERTISSEMENT_PIED}*")
    if champs.get("bareme_verifie_le"):
        a("")
        a(f"*Barème utilisé pour les contrôles : vérifié le "
          f"{_jolie_date(champs.get('bareme_verifie_le'))}.*")

    return "\n".join(lignes)
