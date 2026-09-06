"""
Seeds de rétroplanning — les jalons livrés avec un dossier thématique
=====================================================================
Un **jalon** = une chose à faire, située dans le temps par rapport à la date d'ancrage
du dossier (pour « Devenir parent » : la date du terme). Voir `models/jalon` pour le
repérage temporel — un seul entier signé, négatif avant la naissance.

⚠️ **Ce contenu ne remplace ni un avis médical ni les textes officiels.** Les règles
françaises citées (délais de déclaration, durées de congé, calendrier vaccinal) étaient
celles en vigueur en septembre 2026 ; elles changent. Les sources qui font foi sont
`service-public.fr`, `ameli.fr`, `caf.fr` et le carnet de santé. Chaque jalon porte donc
la formulation de son échéance, pas seulement un mois : « avant la fin de la 14ᵉ semaine »
est opposable, « au 3ᵉ mois » ne l'est pas.

L'installation est **idempotente** : relancée, elle n'ajoute que les jalons absents et ne
touche JAMAIS au suivi personnel (`fait`, `fait_le`, `note_perso`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.jalon import Jalon

log = get_logger(__name__)

# Phrase affichée en tête du planning. Elle n'est pas décorative : un rétroplanning de
# grossesse qui aurait l'air d'un protocole médical serait nuisible.
AVERTISSEMENT = (
    "Repères indicatifs, établis d'après les règles françaises en vigueur en septembre 2026. "
    "Ils ne remplacent ni l'avis de votre médecin ou sage-femme, ni les textes officiels "
    "(service-public.fr, ameli.fr, caf.fr). Les dates affichées sont calculées depuis la date "
    "du terme que vous avez saisie : un accouchement réel s'en écarte presque toujours."
)

# Libellés des catégories — servent au front (couleur, filtre) et documentent le champ.
CATEGORIES = {
    "medical": "Médical",
    "administratif": "Administratif",
    "conges": "Congés & travail",
    "garde": "Mode de garde",
    "materiel": "Matériel",
    "preparation": "Préparation",
    "reperes": "Repères de développement",
}


# ─── « Devenir parent » ───────────────────────────────────────────────────────
# mois -9 … -1 = 1ᵉʳ … 9ᵉ mois de grossesse ; 0 … 36 = âge de l'enfant en mois.
# `sa` = semaines d'aménorrhée (le repère des soignants), quand l'échéance se dit ainsi.

_DEVENIR_PARENT: list[dict] = [
    # ── 1ᵉʳ mois de grossesse ────────────────────────────────────────────────
    {"mois": -9, "categorie": "medical", "titre": "Confirmer la grossesse",
     "detail": "Test urinaire puis, si besoin, prise de sang (bêta-hCG) prescrite par le médecin "
               "ou la sage-femme. C'est cette première consultation qui enclenche tout le reste.",
     "sa": 5},
    {"mois": -9, "categorie": "medical", "titre": "Acide folique (vitamine B9)",
     "detail": "400 µg par jour jusqu'à la 12ᵉ semaine, idéalement commencé avant la conception. "
               "Réduit le risque d'anomalie de fermeture du tube neural. À faire prescrire.",
     "echeance": "Jusqu'à 12 SA", "sa": 5},
    {"mois": -9, "categorie": "medical", "titre": "Arrêter alcool et tabac, revoir les médicaments",
     "detail": "Aucun seuil d'alcool n'est considéré comme sûr pendant la grossesse. Faire relire "
               "toutes les ordonnances en cours, y compris l'automédication et les compléments."},
    {"mois": -9, "categorie": "preparation", "titre": "Inscription à la maternité",
     "detail": "Dans les zones tendues, les places partent dès les premières semaines. Se renseigner "
               "sur le niveau de la maternité (I, II, III) selon le suivi envisagé.",
     "echeance": "Le plus tôt possible"},

    # ── 2ᵉ mois ──────────────────────────────────────────────────────────────
    {"mois": -8, "categorie": "medical", "titre": "1ᵉʳ examen prénatal obligatoire",
     "detail": "Le premier des sept examens pris en charge à 100 %. Il déclenche la déclaration de "
               "grossesse et fixe la date présumée d'accouchement.",
     "echeance": "Avant la fin du 3ᵉ mois", "obligatoire": True, "sa": 9},
    {"mois": -8, "categorie": "medical", "titre": "Sérologies et analyses obligatoires",
     "detail": "Groupe sanguin et rhésus, RAI, toxoplasmose, rubéole, syphilis, VIH proposé. "
               "Si la toxoplasmose est négative : contrôle tous les mois et règles d'hygiène "
               "alimentaire jusqu'à l'accouchement.",
     "obligatoire": True, "sa": 9},
    {"mois": -8, "categorie": "conges", "titre": "Réfléchir au moment d'annoncer à l'employeur",
     "detail": "Aucune obligation de délai, mais la protection contre le licenciement et les "
               "aménagements de poste ne s'appliquent qu'une fois l'employeur informé par écrit."},

    # ── 3ᵉ mois ──────────────────────────────────────────────────────────────
    {"mois": -7, "categorie": "medical", "titre": "1ʳᵉ échographie (datation)",
     "detail": "Entre 11 SA et 13 SA + 6 jours. Confirme le terme, le nombre d'embryons et mesure "
               "la clarté nucale, qui entre dans le calcul du risque de trisomie 21.",
     "echeance": "11 à 13 SA + 6 jours", "sa": 12},
    {"mois": -7, "categorie": "medical", "titre": "Dépistage de la trisomie 21",
     "detail": "Marqueurs sériques combinés à la clarté nucale. Le dépistage est proposé, jamais "
               "imposé : le refuser est un droit, et se dit simplement au praticien.",
     "echeance": "11 à 13 SA + 6 jours", "sa": 12},
    {"mois": -7, "categorie": "administratif",
     "titre": "Déclaration de grossesse à la CPAM et à la CAF",
     "detail": "C'est LA date à ne pas manquer : elle ouvre la prise en charge à 100 % des examens "
               "obligatoires, la prime à la naissance et les droits au congé maternité. Le praticien "
               "transmet le plus souvent en ligne ; vérifier que c'est fait plutôt que de le supposer.",
     "echeance": "Avant la fin de la 14ᵉ semaine de grossesse", "obligatoire": True,
     "url": "https://www.ameli.fr", "sa": 14},
    {"mois": -7, "categorie": "administratif", "titre": "Reconnaissance anticipée (couple non marié)",
     "detail": "En mairie, avec une pièce d'identité. Faite avant la naissance, elle établit la "
               "filiation dès le premier jour et évite d'avoir à la régulariser après.",
     "url": "https://www.service-public.fr"},

    # ── 4ᵉ mois ──────────────────────────────────────────────────────────────
    {"mois": -6, "categorie": "medical", "titre": "2ᵉ examen prénatal",
     "detail": "À partir du 4ᵉ mois, les examens deviennent mensuels jusqu'à l'accouchement.",
     "obligatoire": True, "sa": 17},
    {"mois": -6, "categorie": "medical", "titre": "Entretien prénatal précoce (EPP)",
     "detail": "Systématiquement proposé depuis 2020, pris en charge à 100 %. Un temps de parole "
               "long, sans examen clinique, avec une sage-femme : fatigue, appréhensions, situation "
               "familiale, addictions, violences. C'est le rendez-vous que les futurs pères sautent "
               "le plus souvent, et l'un des rares où leur place est explicitement prévue.",
     "echeance": "Proposé au 4ᵉ mois", "obligatoire": True},
    {"mois": -6, "categorie": "garde", "titre": "Lancer les démarches de mode de garde",
     "detail": "Crèche municipale : dossier souvent à déposer dès le 4ᵉ ou 5ᵉ mois, commissions "
               "d'attribution au printemps. Assistante maternelle : prendre contact tôt, les bonnes "
               "sont réservées un an à l'avance dans beaucoup de communes. Ne pas attendre la naissance.",
     "url": "https://monenfant.fr"},
    {"mois": -6, "categorie": "conges", "titre": "Calculer les dates du congé maternité",
     "detail": "Pour un premier ou deuxième enfant : 16 semaines, dont 6 avant la date présumée "
               "d'accouchement et 10 après. À partir du troisième : 26 semaines. Le report d'une "
               "partie du prénatal sur le postnatal est possible, avec accord médical."},
    {"mois": -6, "categorie": "conges", "titre": "Informer l'employeur par écrit",
     "detail": "Lettre remise en main propre ou recommandé, avec le certificat médical et les dates "
               "de congé. C'est cet écrit qui déclenche la protection et les autorisations d'absence "
               "pour les examens obligatoires."},

    # ── 5ᵉ mois ──────────────────────────────────────────────────────────────
    {"mois": -5, "categorie": "medical", "titre": "3ᵉ examen prénatal", "obligatoire": True, "sa": 21},
    {"mois": -5, "categorie": "medical", "titre": "2ᵉ échographie (morphologique)",
     "detail": "L'examen le plus long et le plus attendu : analyse organe par organe. C'est aussi "
               "celui où l'on peut connaître le sexe, si on le souhaite — dites-le avant, pas pendant.",
     "echeance": "Entre 20 et 25 SA", "sa": 22},
    {"mois": -5, "categorie": "medical", "titre": "Vaccination contre la coqueluche",
     "detail": "Recommandée à chaque grossesse, entre 20 et 36 SA, idéalement au 2ᵉ trimestre : les "
               "anticorps transmis protègent le nourrisson avant sa propre vaccination. L'entourage "
               "proche non à jour devrait l'être aussi.",
     "echeance": "Entre 20 et 36 SA", "sa": 22},
    {"mois": -5, "categorie": "preparation", "titre": "Réserver la préparation à la naissance",
     "detail": "Huit séances prises en charge à 100 %, avec une sage-femme, en plus de l'entretien "
               "précoce. Les places partent vite. Certaines séances sont ouvertes au deuxième parent."},
    {"mois": -5, "categorie": "materiel", "titre": "Établir la liste de naissance",
     "detail": "Le nécessaire tient en peu de choses : un lit aux normes, un siège auto, de quoi "
               "changer et nourrir. Le reste peut attendre, et beaucoup se prête ou s'achète d'occasion "
               "— sauf le siège auto et le matelas, qui se prennent neufs."},

    # ── 6ᵉ mois ──────────────────────────────────────────────────────────────
    {"mois": -4, "categorie": "medical", "titre": "4ᵉ examen prénatal", "obligatoire": True, "sa": 26},
    {"mois": -4, "categorie": "medical", "titre": "Dépistage du diabète gestationnel",
     "detail": "Test d'hyperglycémie provoquée, proposé aux femmes présentant au moins un facteur de "
               "risque. À jeun, et long : prévoir la matinée.",
     "echeance": "Entre 24 et 28 SA", "sa": 26},
    {"mois": -4, "categorie": "conges", "titre": "Envoyer la demande de congé maternité",
     "detail": "À l'employeur et à la CPAM. La prise en charge à 100 % de tous les soins commence "
               "au 1ᵉʳ jour du 6ᵉ mois de grossesse, quel que soit le motif."},
    {"mois": -4, "categorie": "conges", "titre": "Congé paternité : prévenir l'employeur",
     "detail": "25 jours calendaires (32 en cas de naissances multiples), en plus des 3 jours de "
               "naissance. L'employeur doit être informé au moins UN MOIS avant la date prévue — "
               "c'est un délai légal, pas une politesse. Les 4 premiers jours suivant les 3 jours "
               "de naissance sont obligatoires et interdits au travail.",
     "echeance": "Au moins 1 mois avant la date prévue", "obligatoire": True,
     "url": "https://www.service-public.fr"},
    {"mois": -4, "categorie": "materiel", "titre": "Siège auto : choisir et apprendre à l'installer",
     "detail": "Obligatoire dès la sortie de maternité, dos à la route. L'installer une fois à vide, "
               "sans stress : c'est la pièce de matériel la plus mal montée, et la seule dont une "
               "erreur se paie comptant."},

    # ── 7ᵉ mois ──────────────────────────────────────────────────────────────
    {"mois": -3, "categorie": "medical", "titre": "5ᵉ examen prénatal", "obligatoire": True, "sa": 31},
    {"mois": -3, "categorie": "medical", "titre": "3ᵉ échographie (croissance)",
     "detail": "Vérifie la croissance, la position du bébé et celle du placenta — éléments qui "
               "orientent les modalités de l'accouchement.",
     "echeance": "Entre 30 et 35 SA", "sa": 32},
    {"mois": -3, "categorie": "administratif", "titre": "Prime à la naissance (CAF)",
     "detail": "Versée au 7ᵉ mois de grossesse, sous conditions de ressources, à condition que la "
               "déclaration de grossesse ait été faite dans les délais. Vérifier que la CAF a bien "
               "enregistré la grossesse.",
     "url": "https://www.caf.fr"},
    {"mois": -3, "categorie": "materiel", "titre": "Préparer la chambre et la sécuriser",
     "detail": "Lit aux normes, matelas ferme à la taille exacte du lit, pas d'oreiller, pas de tour "
               "de lit, pas de couette : une gigoteuse. Couchage sur le dos. Température autour de 19 °C."},
    {"mois": -3, "categorie": "administratif", "titre": "Prénom et choix du nom de famille",
     "detail": "Le nom de famille se choisit par déclaration conjointe au moment de la naissance : "
               "nom du père, de la mère, ou les deux accolés dans l'ordre choisi. Le choix vaut pour "
               "tous les enfants suivants du même couple — mieux vaut en parler avant la salle "
               "d'accouchement."},

    # ── 8ᵉ mois ──────────────────────────────────────────────────────────────
    {"mois": -2, "categorie": "medical", "titre": "6ᵉ examen prénatal", "obligatoire": True, "sa": 35},
    {"mois": -2, "categorie": "medical", "titre": "Consultation d'anesthésie",
     "detail": "Obligatoire au 3ᵉ trimestre, MÊME si aucune péridurale n'est envisagée : en cas de "
               "césarienne en urgence, l'anesthésiste doit déjà connaître le dossier.",
     "echeance": "Au 3ᵉ trimestre", "obligatoire": True, "sa": 35},
    {"mois": -2, "categorie": "medical", "titre": "Prélèvement vaginal (streptocoque B)",
     "detail": "Recherche de portage : s'il est positif, un antibiotique est administré pendant le "
               "travail pour protéger le nouveau-né. Portage banal, sans symptôme, sans gravité s'il "
               "est connu.",
     "echeance": "Entre 34 et 38 SA", "sa": 36},
    {"mois": -2, "categorie": "preparation", "titre": "Préparer la valise de maternité",
     "detail": "Prête à 8 mois : une naissance prématurée ne prévient pas. Trois sacs distincts — "
               "la mère, l'enfant, le second parent — et les documents à part, accessibles sans "
               "ouvrir le reste."},
    {"mois": -2, "categorie": "conges", "titre": "Début du congé maternité prénatal",
     "detail": "Six semaines avant la date présumée d'accouchement pour un premier ou deuxième enfant. "
               "Un report partiel sur l'après est possible avec l'accord du praticien."},
    {"mois": -2, "categorie": "preparation", "titre": "Choisir le médecin de l'enfant",
     "detail": "Pédiatre ou médecin généraliste : les examens obligatoires du premier mois arrivent "
               "vite, et trouver un praticien qui prend de nouveaux patients prend du temps."},

    # ── 9ᵉ mois ──────────────────────────────────────────────────────────────
    {"mois": -1, "categorie": "medical", "titre": "7ᵉ et dernier examen prénatal",
     "obligatoire": True, "sa": 39},
    {"mois": -1, "categorie": "preparation", "titre": "Repérer le trajet et prévoir un plan B",
     "detail": "Faire le trajet une fois, aux heures de pointe. Noter le numéro direct des urgences "
               "obstétricales, l'entrée à utiliser la nuit, et qui appeler si le premier conducteur "
               "n'est pas joignable."},
    {"mois": -1, "categorie": "administratif", "titre": "Rassembler les documents pour la maternité",
     "detail": "Carte Vitale, carte de mutuelle, pièces d'identité des deux parents, reconnaissance "
               "anticipée, livret de famille, groupe sanguin, dossier de suivi, déclaration conjointe "
               "de choix de nom si elle est décidée."},
    {"mois": -1, "categorie": "preparation", "titre": "Organiser les deux semaines d'après",
     "detail": "Repas congelés, courses livrées, ménage, aînés, animaux. Décider À L'AVANCE qui vient "
               "et quand : les visites non filtrées sont l'épreuve la plus citée du retour à la maison."},

    # ── Naissance et 1ᵉʳ mois ────────────────────────────────────────────────
    {"mois": 0, "categorie": "administratif", "titre": "Déclaration de naissance en mairie",
     "detail": "Dans les cinq jours ouvrables suivant l'accouchement (le jour de la naissance ne "
               "compte pas). Beaucoup de maternités hébergent un officier d'état civil : se renseigner "
               "avant, c'est la démarche qui se rate le plus souvent.",
     "echeance": "Dans les 5 jours ouvrables", "obligatoire": True,
     "url": "https://www.service-public.fr"},
    {"mois": 0, "categorie": "medical", "titre": "Examen du 8ᵉ jour et 1ᵉʳ certificat de santé",
     "detail": "Le premier des trois certificats de santé obligatoires. Réalisé le plus souvent avant "
               "la sortie de maternité. Dépistage néonatal (test de Guthrie) et dépistage auditif.",
     "echeance": "Dans les 8 premiers jours", "obligatoire": True},
    {"mois": 0, "categorie": "administratif", "titre": "Déclarer la naissance à la CPAM et à la CAF",
     "detail": "Rattachement de l'enfant aux deux parents (possible et recommandé), ouverture de "
               "l'allocation de base de la PAJE, mise à jour de la carte Vitale."},
    {"mois": 0, "categorie": "conges", "titre": "Congé de naissance et congé paternité",
     "detail": "3 jours de congé de naissance à la charge de l'employeur, puis 4 jours de congé "
               "paternité obligatoires, pris immédiatement à la suite. Les 21 jours restants se "
               "prennent en une ou deux fois, dans les six mois.",
     "obligatoire": True},
    {"mois": 0, "categorie": "administratif", "titre": "Ajouter l'enfant à la mutuelle",
     "detail": "Souvent dans un délai contractuel court après la naissance, avec effet rétroactif "
               "au jour de la naissance si la demande est faite à temps."},
    {"mois": 0, "categorie": "medical", "titre": "Suivi à domicile après la sortie",
     "detail": "Une sage-femme peut passer à domicile dans les jours suivant la sortie (dispositif "
               "PRADO), prise en charge à 100 %. À accepter : c'est le moment où l'allaitement, le "
               "poids et le moral se jouent."},

    # ── Première année ───────────────────────────────────────────────────────
    {"mois": 1, "categorie": "medical", "titre": "Examen obligatoire du 1ᵉʳ mois",
     "obligatoire": True},
    {"mois": 1, "categorie": "garde", "titre": "Confirmer le mode de garde et demander le CMG",
     "detail": "Le complément de libre choix du mode de garde (CMG) prend en charge une partie du "
               "salaire d'une assistante maternelle ou d'une garde à domicile. La demande se fait "
               "après l'embauche, via Pajemploi.",
     "url": "https://www.pajemploi.urssaf.fr"},
    {"mois": 2, "categorie": "medical", "titre": "Examen du 2ᵉ mois et premières vaccinations",
     "detail": "Première injection du calendrier vaccinal (diphtérie, tétanos, poliomyélite, "
               "coqueluche, Haemophilus influenzae b, hépatite B) et pneumocoque. Le calendrier "
               "évolue : celui du carnet de santé et du médecin fait foi.",
     "obligatoire": True},
    {"mois": 2, "categorie": "reperes", "titre": "Repères : sourire réponse, regard qui accroche",
     "detail": "Vers 6 à 8 semaines apparaît le sourire en réponse. Les repères sont des moyennes "
               "larges, pas un examen : l'écart à la moyenne se discute au rendez-vous mensuel, il "
               "ne se diagnostique pas seul."},
    {"mois": 3, "categorie": "medical", "titre": "Examen du 3ᵉ mois", "obligatoire": True},
    {"mois": 3, "categorie": "conges", "titre": "Fin du congé maternité : reprise ou congé parental",
     "detail": "Le postnatal de 10 semaines s'achève environ 2,5 mois après la naissance. Trois voies : "
               "reprise, congé parental d'éducation (avec la PreParE), ou temps partiel. La demande de "
               "congé parental se fait au moins un mois avant la fin du congé maternité.",
     "echeance": "Demande 1 mois avant la fin du congé maternité"},
    {"mois": 4, "categorie": "medical", "titre": "Examen du 4ᵉ mois et 2ᵉ injection vaccinale",
     "obligatoire": True},
    {"mois": 4, "categorie": "preparation", "titre": "Diversification alimentaire",
     "detail": "Entre 4 et 6 mois révolus, jamais avant 4 mois. Un aliment nouveau à la fois. "
               "L'introduction précoce des allergènes majeurs est désormais recommandée plutôt "
               "qu'évitée : en parler au médecin."},
    {"mois": 5, "categorie": "medical", "titre": "Examen du 5ᵉ mois", "obligatoire": True},
    {"mois": 6, "categorie": "medical", "titre": "Examen du 6ᵉ mois", "obligatoire": True},
    {"mois": 6, "categorie": "reperes",
     "titre": "Repères : tient assis avec appui, attrape et porte à la bouche",
     "detail": "C'est aussi l'âge où la maison doit être revue à hauteur de sol : petits objets, "
               "produits ménagers, escaliers, coins de table."},
    {"mois": 9, "categorie": "medical", "titre": "Examen du 9ᵉ mois et 2ᵉ certificat de santé",
     "detail": "Deuxième des trois certificats obligatoires, adressé au service de PMI. Bilan de "
               "développement, vision, audition, langage.",
     "obligatoire": True},
    {"mois": 11, "categorie": "medical", "titre": "Rappel vaccinal des 11 mois", "obligatoire": True},
    {"mois": 12, "categorie": "medical", "titre": "Examen du 12ᵉ mois et vaccin ROR",
     "detail": "Première dose de rougeole-oreillons-rubéole, et méningocoque selon le calendrier "
               "en vigueur.",
     "obligatoire": True},
    {"mois": 12, "categorie": "reperes",
     "titre": "Repères : se met debout, premiers mots, pointe du doigt",
     "detail": "Le pointage du doigt vers 12-15 mois est un repère de communication au moins aussi "
               "important que la marche ou les premiers mots. Son absence se signale au médecin."},

    # ── Deuxième et troisième années ─────────────────────────────────────────
    {"mois": 17, "categorie": "medical", "titre": "Examen des 16-18 mois et 2ᵉ dose de ROR",
     "obligatoire": True},
    {"mois": 24, "categorie": "medical", "titre": "Examen du 24ᵉ mois et 3ᵉ certificat de santé",
     "detail": "Dernier des trois certificats de santé obligatoires. Bilan du langage, de la marche "
               "et de l'autonomie.",
     "obligatoire": True},
    {"mois": 24, "categorie": "reperes", "titre": "Repères : associe deux mots, monte un escalier",
     "detail": "Vers deux ans, l'explosion du vocabulaire est très variable d'un enfant à l'autre. "
               "Le repère qui compte n'est pas le nombre de mots mais la progression."},
    {"mois": 30, "categorie": "garde", "titre": "Inscription à l'école maternelle",
     "detail": "L'instruction est obligatoire dès 3 ans. L'inscription se fait en mairie, souvent "
               "entre janvier et mars pour la rentrée de septembre — donc bien avant le troisième "
               "anniversaire si l'enfant est né en fin d'année.",
     "echeance": "Janvier-mars pour la rentrée suivante", "obligatoire": True},
    {"mois": 36, "categorie": "medical", "titre": "Examen des 3 ans",
     "detail": "Bilan réalisé en partie à l'école maternelle par le service de PMI : vision, "
               "audition, langage, dépistage des troubles des apprentissages.",
     "obligatoire": True},
]


JALONS_SEEDS: dict[str, list[dict]] = {
    "devenir-parent": _DEVENIR_PARENT,
}


def _cle_jalon(titre: str, mois: int) -> str:
    """
    Clé d'unicité d'un jalon : son titre normalisé, à son mois. Le même intitulé peut
    revenir à un autre moment (« examen du n-ième mois ») sans être un doublon.
    """
    return f"{mois}|{titre.strip().lower()}"


async def installer_jalons(db: AsyncSession, dossier_id: uuid.UUID, cle: str) -> dict:
    """
    Installe (ou complète) le rétroplanning livré pour le dossier `cle`.

    Idempotent : n'ajoute que les jalons absents. Ne touche jamais au suivi personnel —
    un jalon coché et annoté le reste, y compris si son libellé a changé côté seed.
    Retourne `{ajoutes, presents}`. Ne commit pas : c'est l'appelant qui décide.
    """
    modele = JALONS_SEEDS.get(cle)
    if not modele:
        return {"ajoutes": 0, "presents": 0}

    existants = {
        _cle_jalon(j.titre, j.mois)
        for j in (await db.execute(
            select(Jalon).where(Jalon.dossier_id == dossier_id)
        )).scalars().all()
    }

    ajoutes = 0
    for position, item in enumerate(modele):
        if _cle_jalon(item["titre"], item["mois"]) in existants:
            continue
        db.add(Jalon(
            dossier_id=dossier_id,
            mois=item["mois"],
            sa=item.get("sa"),
            titre=item["titre"],
            detail=item.get("detail"),
            categorie=item.get("categorie", "preparation"),
            echeance=item.get("echeance"),
            url=item.get("url"),
            obligatoire=item.get("obligatoire", False),
            position=position,
            origine=f"seed:{cle}",
        ))
        ajoutes += 1

    log.info("Jalons installés", dossier=cle, ajoutes=ajoutes, presents=len(existants))
    return {"ajoutes": ajoutes, "presents": len(existants)}
