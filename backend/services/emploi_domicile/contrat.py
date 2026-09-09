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

## ⚠️ Ce que ce contrat est, et ce qu'il n'est pas

C'est une **trame complète et sérieuse**, couvrant les articles qu'un contrat de particulier
employeur doit porter. Ce n'est **pas la reproduction d'un modèle officiel**, et rien ici ne
garantit qu'il colle au dernier état de la convention collective.

La nuance n'est pas de la prudence de façade : un contrat qui *aurait l'air* officiel serait
plus dangereux qu'un contrat qui annonce ce qu'il est. Le document le dit lui-même en pied,
et l'écran renvoie vers les sources qui font foi.

- **Aucun montant réglementaire inventé.** Les chiffres viennent des champs saisis ; le SMIC
  et le minimum garanti, quand ils servent à un contrôle, viennent des Paramètres.
- **Aucune clause rédigée par l'IA.** Un modèle qui reformule un préavis produit une erreur
  indétectable dans un document qui engage juridiquement.

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
    "Ce document a été préparé avec Matothèque à partir des informations saisies. Il en "
    "reprend la structure attendue, mais ne reproduit aucun modèle officiel : il ne remplace "
    "ni la convention collective applicable, ni le code du travail, ni un conseil juridique. "
    "Relisez-le et adaptez-le avant signature."
)

# Sources qui font foi, proposées à côté du contrat. **Domaines racines uniquement** : un lien
# profond non vérifié serait la même faute que d'afficher un montant qu'on n'a pas relu.
SOURCES_OFFICIELLES = [
    {"libelle": "service-public.fr — employer une assistante maternelle",
     "url": "https://www.service-public.fr/"},
    {"libelle": "legifrance.gouv.fr — convention collective des particuliers employeurs",
     "url": "https://www.legifrance.gouv.fr/"},
    {"libelle": "pajemploi.urssaf.fr — déclaration, modèles et simulateurs",
     "url": "https://www.pajemploi.urssaf.fr/"},
]

# Jeu d'exemple : des valeurs PLAUSIBLES, pour voir le contrat rendu d'un coup sans avoir à
# tout saisir. Elles sont là pour être remplacées, et l'écran le dit.
#
# ⚠️ Aucun montant réglementaire réel ici, et les champs qui engagent (assurances, contacts
# d'urgence, lieu de signature) portent explicitement « à compléter » : un exemple qu'on
# oublierait de remplacer doit produire un contrat visiblement inachevé, pas un contrat faux
# qui a l'air juste.
EXEMPLE: dict = {
    "enfant_nom": "Léa Dupont",
    "date_debut": "2026-09-01",
    "adaptation": "5 demi-journées réparties sur 2 semaines",
    "essai": "2 mois",
    "jours": "du lundi au jeudi",
    "horaires": "8h30 – 17h30",
    "jours_semaine": "4",
    "heures_jour": "9",
    "heures_semaine": "36",
    "taux_horaire": "4,20",
    "majoration_pct": "10",
    "annee_complete": True,
    "jour_paie": "le 2 du mois",
    "entretien_jour": "3,60",
    "repas_jour": "4,00",
    "repas_fourni_par": "l'assistante maternelle",
    "km_semaine": "10",
    "tarif_km": "0,45",
    "conges": "3 semaines en août, 1 semaine à Noël",
    "absences": "les absences prévues au calendrier sont déduites ; les autres restent dues",
    "feries": "non travaillés, hors 1er mai",
    "autorisation_sorties": "oui — parc, médiathèque, promenades",
    "autorisation_transport": "oui, siège auto adapté fourni par l'assistante maternelle",
    "autorisation_photos": "oui, usage familial uniquement, aucune diffusion en ligne",
    "autorisation_soins": "oui — prévenir les parents, puis le 15 si nécessaire",
    "pai": "aucun à ce jour",
    "urgence": "à compléter : deux numéros joignables en journée",
    "assurance_rc": "à compléter : assureur et n° de police",
    "assurance_auto": "à compléter : attestation mentionnant le transport d'enfants",
    "fait_a": "à compléter",
}


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
    """
    Le contrat complet, en Markdown. `champs` porte tout ce qui a été saisi à l'écran.

    Les articles sont **numérotés automatiquement**. Le gabarit varie selon le profil
    (agrément et autorisations n'existent que chez l'assistante maternelle) et selon le
    régime (la régularisation annuelle ne concerne que l'année incomplète) : une
    numérotation écrite à la main se décale au premier article ajouté, et produit un contrat
    qui renvoie à « l'article 7 » alors que ce n'est plus le bon.
    """
    assmat = profil.cle == "assmat"
    lignes: list[str] = []
    a = lignes.append
    compteur = {"n": 0}

    def article(titre: str) -> None:
        compteur["n"] += 1
        a("")
        a(f"## Article {compteur['n']} — {titre}")
        a("")

    entete = ("Contrat de travail à durée indéterminée — assistant(e) maternel(le) agréé(e)"
              if assmat else
              f"Contrat de travail à durée indéterminée — {profil.libelle.lower()}")
    a(f"# {entete}")
    a("")
    a("*Le présent contrat est régi par la convention collective applicable aux particuliers "
      f"employeurs et à l'emploi à domicile, socle « {profil.socle} », ainsi que par les "
      f"dispositions légales en vigueur. Déclaration auprès de **{profil.guichet}**.*")
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
        a(f"Titulaire de l'agrément n° {_v(champs.get('agrement_numero'))}, valable jusqu'au "
          f"{_jolie_date(champs.get('agrement_echeance'))}, pour l'accueil simultané de "
          f"{_v(champs.get('places'))} mineur(s).")
        a("")
        a("Le ou la salarié(e) s'engage à informer l'employeur **sans délai** de toute "
          "modification, suspension ou retrait de son agrément.")

    # ── Objet ─────────────────────────────────────────────────────────────────────────
    if assmat:
        article("Enfant accueilli et lieu d'accueil")
        a(f"Prénom et nom : {_v(champs.get('enfant_nom'))}  ")
        a(f"Né(e) le : {_jolie_date(champs.get('enfant_naissance'))}  ")
        a(f"Lieu d'accueil : {_v(champs.get('lieu_accueil') or salariee.adresse)}")
    else:
        article("Objet et lieu d'exécution")
        a(f"Nature des tâches : {_v(champs.get('taches'))}  ")
        a(f"Lieu d'exécution : {_v(champs.get('lieu_accueil') or employeur.adresse)}")

    # ── Effet, adaptation, essai ──────────────────────────────────────────────────────
    article("Date d'effet, adaptation et période d'essai")
    a(f"Le contrat prend effet le **{_jolie_date(champs.get('date_debut'))}**, pour une durée "
      "indéterminée.")
    if assmat:
        a("")
        a(f"**Période d'adaptation** : {_v(champs.get('adaptation'))}. Elle permet à l'enfant "
          "et à l'accueillant(e) de se connaître progressivement ; elle est rémunérée selon "
          "les heures réellement effectuées.")
    a("")
    a(f"**Période d'essai** : {_v(champs.get('essai'))}. Pendant cette période, chaque partie "
      "peut rompre le contrat sans avoir à motiver sa décision, en respectant le délai de "
      "prévenance prévu par la convention collective. La rupture est notifiée par écrit.")

    # ── Horaires ──────────────────────────────────────────────────────────────────────
    article("Jours, horaires et durée du travail")
    a(f"Jours d'accueil : {_v(champs.get('jours'))}  ")
    a(f"Horaires : {_v(champs.get('horaires'))}  ")
    a(f"Durée hebdomadaire convenue : {_v(champs.get('heures_semaine'))} heures  ")
    a(f"Nombre de jours d'accueil par semaine : {_v(champs.get('jours_semaine'))}")
    if mensualisation is not None:
        a("")
        a(f"Nombre de semaines d'accueil programmées sur l'année : **{mensualisation.semaines}**.")
    a("")
    a("Toute heure effectuée au-delà de l'horaire convenu est rémunérée. Au-delà de 45 heures "
      "par semaine, les heures sont majorées au taux prévu à l'article suivant. Toute "
      "modification durable des horaires fait l'objet d'un **avenant écrit**.")

    # ── Rémunération ──────────────────────────────────────────────────────────────────
    article("Rémunération")
    if mensualisation is not None:
        regime = ("**année complète**" if mensualisation.regime == "complete"
                  else "**année incomplète**")
        a("Le salaire est **mensualisé** : il est lissé sur douze mois et versé chaque mois "
          f"pour un montant identique, y compris les mois sans accueil. Régime retenu : {regime}.")
        a("")
        a(f"- Taux horaire : **{_montant(mensualisation.taux_horaire)}**")
        a(f"- Durée hebdomadaire : {_fr(mensualisation.heures_semaine)} heures")
        a(f"- Nombre de semaines d'accueil : {mensualisation.semaines}")
        a(f"- Heures mensualisées : **{_fr(mensualisation.heures_mensualisees)} heures**")
        a(f"- **Salaire mensuel : {_montant(mensualisation.salaire_mensuel)}**")
        a("")
        a(f"> Calcul : {mensualisation.formule}")
        a("")
        for ligne in mensualisation.detail:
            a(f"> {ligne}")
    else:
        a(f"Taux horaire : {_montant(champs.get('taux_horaire'))} — salaire mensualisé : "
          f"{MANQUANT}.")
    a("")
    a(f"Majoration des heures au-delà de 45 h par semaine : {_v(champs.get('majoration_pct'))} %.")
    a("")
    a(f"Le salaire est versé le {_v(champs.get('jour_paie'))} de chaque mois. L'employeur "
      f"déclare l'emploi auprès de **{profil.guichet}**, qui édite le **bulletin de salaire** "
      "remis au ou à la salarié(e) à chaque échéance.")

    # ── Régularisation (année incomplète seulement) ───────────────────────────────────
    if mensualisation is not None and mensualisation.regime == "incomplete":
        article("Régularisation annuelle")
        a("Le salaire étant lissé sur une base prévisionnelle, les parties comparent **une "
          "fois par an**, ainsi qu'à la fin du contrat, les heures réellement effectuées et "
          "les heures rémunérées. L'écart constaté est régularisé sur la paie suivante.")
        a("")
        a("Cette comparaison n'est pas facultative : sans elle, un écart minime se répète "
          "chaque mois et devient significatif au bout d'une année.")

    # ── Indemnités ────────────────────────────────────────────────────────────────────
    article("Indemnités et frais")
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

    # ── Congés et absences ────────────────────────────────────────────────────────────
    article("Congés payés, absences et jours fériés")
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
    a("En dehors des cas expressément prévus ci-dessus, une absence du fait de l'employeur ne "
      "suspend pas le versement du salaire mensualisé.")
    a("")
    a(f"Jours fériés travaillés : {_v(champs.get('feries'))}.")
    a("")
    a("En cas d'absence pour maladie, le ou la salarié(e) prévient l'employeur sans délai et "
      "transmet son arrêt de travail.")

    # ── Autorisations (assmat) ────────────────────────────────────────────────────────
    if assmat:
        article("Autorisations, santé et sécurité")
        a(f"- Sorties : {_v(champs.get('autorisation_sorties'))}")
        a(f"- Transport en véhicule : {_v(champs.get('autorisation_transport'))}")
        a(f"- Photographies : {_v(champs.get('autorisation_photos'))}")
        a(f"- Soins d'urgence : {_v(champs.get('autorisation_soins'))}")
        a(f"- Projet d'accueil individualisé (allergie, traitement) : {_v(champs.get('pai'))}")
        a("")
        a(f"Personnes à prévenir en cas d'urgence : {_v(champs.get('urgence'))}")
        a("")
        a("Le ou la salarié(e) informe l'employeur de tout incident survenu pendant l'accueil, "
          "même bénin, ainsi que de tout élément susceptible d'affecter la sécurité de l'enfant.")

    # ── Assurances ────────────────────────────────────────────────────────────────────
    article("Assurances")
    a(f"Responsabilité civile professionnelle : {_v(champs.get('assurance_rc'))}.  ")
    a(f"Assurance automobile couvrant le transport d'enfants : {_v(champs.get('assurance_auto'))}.")
    a("")
    a("Une copie des attestations en cours de validité est annexée au présent contrat, et "
      "renouvelée à chaque échéance.")

    # ── Suivi médical ─────────────────────────────────────────────────────────────────
    article("Suivi médical du ou de la salarié(e)")
    a("L'employeur procède à l'affiliation du ou de la salarié(e) au service de santé au "
      "travail compétent, et lui permet de se rendre aux visites d'information, de prévention "
      "et de suivi sur le temps de travail.")
    a("")
    a("*Cette obligation est régulièrement absente des contrats de particulier employeur ; "
      "elle n'en est pas facultative pour autant.*")

    # ── Discrétion ────────────────────────────────────────────────────────────────────
    article("Discrétion")
    a("Chaque partie s'engage à la plus grande discrétion sur ce qu'elle apprend de la vie "
      "privée de l'autre à l'occasion de l'exécution du contrat. Cet engagement survit à la "
      "fin du contrat.")

    # ── Modification ──────────────────────────────────────────────────────────────────
    article("Modification du contrat")
    a("Toute modification d'un élément essentiel du présent contrat — horaires, durée "
      "d'accueil, rémunération, lieu — fait l'objet d'un **avenant écrit signé des deux "
      "parties**. Un accord verbal ne modifie pas le contrat et laisse chacun sans preuve le "
      "jour où les souvenirs divergent.")

    # ── Rupture ───────────────────────────────────────────────────────────────────────
    article("Rupture du contrat")
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
      "a été réellement effectué) et les congés payés non pris. L'employeur remet le **solde "
      "de tout compte**, le **certificat de travail** et l'**attestation destinée à France "
      "Travail** — ces trois documents sont dus systématiquement.")

    # ── Signatures ────────────────────────────────────────────────────────────────────
    article("Signatures")
    a(f"Fait à {_v(champs.get('fait_a'))}, le {_jolie_date(champs.get('fait_le'))}, en deux "
      "exemplaires originaux, dont un remis à chaque partie.")
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
