"""
Contenu livré du module emploi à domicile — fiches et checklist
===============================================================
Phase 1 : **lecture seule, aucune migration, aucune écriture**. Des fiches à lire et une
checklist à imprimer, servies par `GET /api/emploi-domicile/fiches`.

Même patron que `jalon_seed` : du contenu Python, versionné, relu, daté. Ajouter une fiche
= ajouter une entrée dans `_FICHES`.

## La règle qui tient tout

**Aucun chiffre affiché sans sa date et sa source.** Les montants (SMIC, minimum
d'entretien, plafonds, barème du CMG) et les durées changent au moins une fois par an. Ce
fichier n'en contient donc **aucun** : il décrit les **mécanismes**, qui, eux, sont stables,
et renvoie au barème officiel pour les valeurs. Une fiche qui annoncerait « indemnité
d'entretien : X € » serait fausse en janvier sans que rien ne le signale — et un contrat
bâti dessus aurait l'air juste.

## Ce que le contenu ne fait pas

- **Il n'est pas produit ni relu par l'IA.** Un modèle local qui invente une durée de
  préavis est indétectable. Ce sont des règles publiées, écrites à la main.
- **Il ne remplace pas la convention collective ni la PMI.** Il dit quoi vérifier et où
  regarder ; il ne tranche pas un litige.

📌 **À relire à chaque rentrée** (septembre) et à chaque campagne de déclaration : mettre à
jour `VERIFIE_LE`, confronter à la convention collective et aux textes en vigueur.
"""

from __future__ import annotations

from datetime import date

from services.emploi_domicile.profils import Profil

VERIFIE_LE = date(2026, 9, 9)

AVERTISSEMENT = (
    "Ces fiches décrivent des mécanismes, pas des montants : les barèmes changent chaque "
    "année et ne figurent pas ici volontairement. Elles ne remplacent ni la convention "
    "collective, ni votre service PMI, ni un conseil juridique — elles disent quoi vérifier "
    "et où regarder."
)

# Ressources officielles. Ce sont des ancres ouvertes par l'utilisateur, pas des appels que
# l'application émettrait : Matothèque ne sort jamais sur le réseau toute seule.
LIENS = [
    {"libelle": "Pajemploi (URSSAF) — assistante maternelle et garde à domicile",
     "url": "https://www.pajemploi.urssaf.fr/"},
    {"libelle": "CESU (URSSAF) — emploi à domicile hors garde d'enfant",
     "url": "https://www.cesu.urssaf.fr/"},
    {"libelle": "service-public.fr — particulier employeur",
     "url": "https://www.service-public.fr/"},
    {"libelle": "caf.fr — complément de libre choix du mode de garde",
     "url": "https://www.caf.fr/"},
    {"libelle": "monenfant.fr — trouver un mode de garde près de chez soi",
     "url": "https://monenfant.fr/"},
]


# ─── Fabriques de blocs (le front rend n'importe quel bloc sans le connaître) ──────────

def _texte(titre: str, *paragraphes: str) -> dict:
    return {"type": "texte", "titre": titre, "paragraphes": list(paragraphes)}


def _vis_a_vis(titre: str, lignes: list[dict], gauche: str, droite: str) -> dict:
    """Deux colonnes en regard : ce que chacun doit à l'autre, sur le même sujet."""
    return {"type": "vis_a_vis", "titre": titre, "gauche": gauche, "droite": droite,
            "lignes": lignes}


def _tableau(titre: str, entetes: list[str], lignes: list[list[str]], note: str | None = None) -> dict:
    return {"type": "tableau", "titre": titre, "entetes": entetes, "lignes": lignes, "note": note}


def _points(titre: str, items: list[dict], ton: str = "neutre") -> dict:
    """`ton` : 'neutre' | 'attention' — ce qui coûte de l'argent se distingue du reste."""
    return {"type": "points", "titre": titre, "items": items, "ton": ton}


# ─── Fiche « Quel guichet ? » — générique, et en premier ──────────────────────────────
# Elle vaut pour TOUS les profils, et c'est voulu : la question se pose dans les deux sens
# (un foyer qui prend une nounou prend souvent aussi une aide ménagère), et une fiche qui ne
# parlerait que de Pajemploi laisserait croire que le CESU n'a jamais sa place.

_FICHE_GUICHET = {
    "cle": "guichet",
    "titre": "Quel guichet : Pajemploi ou CESU ?",
    "chapeau": "C'est le LIEU et l'ÂGE qui décident, jamais le mot qu'on emploie. Se tromper "
               "de guichet ne bloque rien immédiatement — ça fait juste perdre une aide, "
               "sans que rien ne le signale.",
    "blocs": [
        _tableau(
            "Le tableau qui tranche",
            ["Situation", "Où", "Guichet", "Aide"],
            [
                ["Assistante maternelle agréée", "chez elle", "Pajemploi",
                 "CMG (jusqu'aux 6 ans de l'enfant)"],
                ["Garde d'enfant de moins de 6 ans", "chez vous", "Pajemploi",
                 "CMG"],
                ["Garde d'enfant de plus de 6 ans", "chez vous", "CESU",
                 "Crédit d'impôt services à la personne"],
                ["Ménage, repassage, courses", "chez vous", "CESU",
                 "Crédit d'impôt services à la personne"],
                ["Jardinage, bricolage, soutien scolaire", "chez vous", "CESU",
                 "Crédit d'impôt services à la personne"],
                ["Aide à l'autonomie (personne âgée, handicap)", "chez vous", "CESU",
                 "Crédit d'impôt + APA / PCH selon la situation"],
            ],
            note="Une même personne peut relever des deux au cours de sa vie : ce n'est pas "
                 "le métier qui classe, c'est le lieu et l'âge de l'enfant.",
        ),
        _points(
            "Ce qu'on confond, et ce que ça coûte",
            [
                {"titre": "CESU au lieu de Pajemploi pour une assistante maternelle",
                 "detail": "Le CESU couvre l'emploi À DOMICILE. Une assistante maternelle "
                           "agréée garde chez elle : elle relève de Pajemploi, qui édite le "
                           "bulletin de salaire et sert de porte d'entrée au CMG. Déclarer au "
                           "mauvais endroit fait perdre le complément."},
                {"titre": "CESU déclaratif ≠ CESU préfinancé",
                 "detail": "Le premier est le service de déclaration de l'URSSAF. Le second "
                           "est un titre de paiement financé par un employeur ou un organisme "
                           "social. Deux choses différentes sous le même sigle."},
                {"titre": "Emploi direct, mandataire ou prestataire",
                 "detail": "Vous n'êtes particulier employeur qu'en emploi DIRECT ou en "
                           "MANDATAIRE. En prestataire, vous achetez une prestation à une "
                           "société : pas de contrat de travail, pas de déclaration, pas de "
                           "licenciement à gérer. Beaucoup croient employer quelqu'un alors "
                           "qu'ils sont clients — ou l'inverse, ce qui est plus grave."},
            ],
            ton="attention",
        ),
        _points(
            "Les aides, et le piège commun aux deux",
            [
                {"titre": "CMG — complément de libre choix du mode de garde",
                 "detail": "Versé par la CAF ou la MSA, il prend en charge une partie du "
                           "salaire et des cotisations. Il se demande dès l'embauche : les "
                           "délais de déclaration sont courts."},
                {"titre": "Crédit d'impôt services à la personne",
                 "detail": "La moitié des dépenses, dans la limite d'un plafond annuel, avec "
                           "possibilité d'avance immédiate — le crédit se déduit à chaque paie "
                           "au lieu d'être remboursé l'année suivante."},
                {"titre": "⚠️ Les aides perçues se DÉDUISENT de ce que vous déclarez",
                 "detail": "CMG, avance immédiate, aide du comité d'entreprise : elles ne "
                           "s'ajoutent pas au crédit d'impôt, elles se retirent de l'assiette. "
                           "C'est l'erreur la plus fréquente du dispositif — et c'est aussi ce "
                           "que rappelle l'onglet « Aide à la déclaration » d'Administration."},
            ],
        ),
    ],
}


# ─── Fiche « Droits et devoirs » — tronc commun + spécificités ────────────────────────

_FICHE_DROITS = {
    "cle": "droits-devoirs",
    "titre": "Qui doit quoi",
    "chapeau": "Vous devenez employeur. Ce n'est pas une figure de style : contrat écrit, "
               "salaire mensualisé, congés payés, préavis, solde de tout compte — tout "
               "s'applique, y compris pour quelques heures par semaine.",
    "blocs": [
        _vis_a_vis(
            "Avant le premier jour", gauche="Vous, l'employeur", droite="La personne employée",
            lignes=[
                {"sujet": "Vérifications",
                 "employeur": "Demander l'agrément (pour une assistante maternelle) et sa "
                              "validité, l'attestation d'assurance responsabilité civile "
                              "professionnelle, et l'assurance auto avec transport d'enfants "
                              "si elle conduit.",
                 "salarie": "Fournir ces pièces, et signaler tout ce qui limite l'accueil "
                            "(places déjà prises, tranches d'âge, restrictions de l'agrément)."},
                {"sujet": "Contrat",
                 "employeur": "Rédiger un contrat de travail ÉCRIT avant le premier accueil, "
                              "et en remettre un exemplaire signé.",
                 "salarie": "Le lire, demander à modifier ce qui ne convient pas, le signer."},
                {"sujet": "Déclaration",
                 "employeur": "S'inscrire au guichet (Pajemploi ou CESU) et déclarer "
                              "l'embauche. Demander l'aide (CMG) sans attendre : les délais "
                              "sont courts.",
                 "salarie": "Fournir les éléments nécessaires : identité, numéro de sécurité "
                            "sociale, coordonnées bancaires."},
            ],
        ),
        _vis_a_vis(
            "Au quotidien", gauche="Vous, l'employeur", droite="La personne employée",
            lignes=[
                {"sujet": "Respect du cadre",
                 "employeur": "Respecter les horaires convenus. Prévenir dès que possible "
                              "d'un changement ou d'une absence.",
                 "salarie": "Assurer l'accueil convenu, respecter les consignes parentales, "
                            "ne jamais déléguer la garde à un tiers non prévu au contrat."},
                {"sujet": "Information",
                 "employeur": "Signaler ce qui change chez l'enfant : sommeil, santé, "
                              "traitement, événement familial.",
                 "salarie": "Rendre compte de la journée et signaler tout incident, même "
                            "bénin — c'est ce qui construit la confiance, et ce dont on a "
                            "besoin le jour où il se passe quelque chose."},
                {"sujet": "Fournitures",
                 "employeur": "Fournir ce que le contrat met à votre charge (couches, repas, "
                              "siège auto…). Ce qui n'est pas écrit sera discuté un jour.",
                 "salarie": "Fournir ce qui relève de l'accueil et que couvre l'indemnité "
                            "d'entretien : jeux, matériel, eau, électricité, chauffage."},
            ],
        ),
        _vis_a_vis(
            "La paie", gauche="Vous, l'employeur", droite="La personne employée",
            lignes=[
                {"sujet": "Salaire",
                 "employeur": "Verser un salaire MENSUALISÉ — un montant identique chaque "
                              "mois, y compris les mois courts. Ce n'est pas un paiement à "
                              "l'heure faite.",
                 "salarie": "Tenir le décompte des heures réellement effectuées et le "
                            "communiquer chaque mois."},
                {"sujet": "Indemnités",
                 "employeur": "Verser en plus du salaire : indemnité d'entretien (obligatoire "
                              "pour une assistante maternelle), repas et kilomètres si prévus. "
                              "Ce ne sont pas des salaires : elles ne se cotisent pas.",
                 "salarie": "Ne pas les confondre avec le salaire dans ses propres comptes."},
                {"sujet": "Déclaration",
                 "employeur": "Déclarer chaque mois au guichet, dans les délais. C'est lui qui "
                              "édite le bulletin de salaire.",
                 "salarie": "Vérifier son bulletin, déclarer ses revenus."},
                {"sujet": "Heures en plus",
                 "employeur": "Les heures au-delà de l'horaire prévu se paient, et au-delà "
                              "d'un seuil hebdomadaire elles sont majorées. À suivre au mois "
                              "le mois, pas à régulariser en décembre.",
                 "salarie": "Les signaler au fil de l'eau, pas en fin d'année."},
            ],
        ),
        _vis_a_vis(
            "Absences, maladie, congés", gauche="Vous, l'employeur", droite="La personne employée",
            lignes=[
                {"sujet": "Enfant absent",
                 "employeur": "Une absence de votre fait ne suspend pas le salaire : la "
                              "mensualisation est due. Les exceptions sont limitées et doivent "
                              "être prévues au contrat.",
                 "salarie": "Rester disponible sur les créneaux prévus."},
                {"sujet": "Salarié absent",
                 "employeur": "Retenir les heures non faites, sans plus. Aucune obligation de "
                              "trouver un remplaçant ne pèse sur elle, sauf accord écrit.",
                 "salarie": "Prévenir immédiatement et fournir un justificatif (arrêt de "
                            "travail)."},
                {"sujet": "Congés payés",
                 "employeur": "Ils sont dus et se calculent sur les périodes travaillées. "
                              "Les dates se fixent tôt dans l'année, et par écrit.",
                 "salarie": "Annoncer ses dates dans le délai prévu par la convention — une "
                            "date annoncée en juin pour août met tout le monde en difficulté."},
                {"sujet": "Jours fériés",
                 "employeur": "Leur traitement dépend du contrat et de la convention : à "
                              "écrire noir sur blanc, sinon la discussion revient chaque mai.",
                 "salarie": "Idem."},
            ],
        ),
        _vis_a_vis(
            "La fin du contrat", gauche="Vous, l'employeur", droite="La personne employée",
            lignes=[
                {"sujet": "Rompre",
                 "employeur": "Retirer l'enfant met fin au contrat : cela se notifie par écrit "
                              "et ouvre un préavis dont la durée dépend de l'ancienneté.",
                 "salarie": "Démissionner suppose également un préavis écrit."},
                {"sujet": "Ce qui est dû",
                 "employeur": "Indemnité de rupture (selon l'ancienneté), régularisation de la "
                              "mensualisation (on compare ce qui a été payé et ce qui a été "
                              "fait), congés payés non pris.",
                 "salarie": "Restituer ce qui appartient à la famille."},
                {"sujet": "Les papiers",
                 "employeur": "Solde de tout compte, certificat de travail, attestation "
                              "destinée à France Travail. Les trois, systématiquement.",
                 "salarie": "Les vérifier avant de signer le solde de tout compte."},
            ],
        ),
        _points(
            "Ce qui se prépare AU CONTRAT, pas au moment où ça arrive",
            [
                {"titre": "La fin", "detail": "Préavis, indemnité, régularisation : personne "
                                              "n'a envie d'en parler au premier entretien, et "
                                              "c'est pourtant le seul moment où on en parle bien."},
                {"titre": "Les absences", "detail": "Vacances de la famille, vacances de la "
                                                    "salariée, enfant malade, salariée malade : "
                                                    "quatre cas, quatre traitements."},
                {"titre": "L'année complète ou incomplète",
                 "detail": "Travaille-t-elle toutes les semaines de l'année, ou seulement "
                           "celles où vous en avez besoin ? La formule de mensualisation n'est "
                           "pas la même, et c'est la première source d'erreur de paie."},
                {"titre": "Les autorisations",
                 "detail": "Sortie, transport en voiture, photos, soins d'urgence, et un PAI "
                           "s'il y a allergie ou traitement."},
            ],
            ton="attention",
        ),
    ],
}


# ─── Fiche « Comparer les modes de garde » ────────────────────────────────────────────

_FICHE_MODES = {
    "cle": "modes-garde",
    "titre": "Comparer les modes de garde",
    "chapeau": "Le coût affiché n'est jamais le coût réel : c'est le reste à charge, après "
               "aides et crédit d'impôt, qui décide. Et la place se demande souvent bien "
               "avant que la question ne se pose vraiment.",
    "blocs": [
        _tableau(
            "En un coup d'œil",
            ["Mode", "Où", "Souplesse des horaires", "Ce qui fait la différence"],
            [
                ["Assistante maternelle", "chez elle", "Forte (négociée au contrat)",
                 "Petit effectif, souplesse, mais vous êtes employeur — avec tout ce que ça implique."],
                ["Crèche collective", "structure", "Faible (horaires fixes)",
                 "Aucune gestion administrative, équipe pluridisciplinaire. Places rares, "
                 "dossier à déposer très tôt."],
                ["Micro-crèche", "structure", "Moyenne",
                 "Petit groupe. Le financement diffère d'une structure à l'autre : demander "
                 "laquelle des deux aides s'applique AVANT de s'engager."],
                ["MAM (maison d'assistantes maternelles)", "local partagé", "Forte",
                 "Assistantes maternelles regroupées : vous restez employeur, l'enfant est en "
                 "collectivité réduite."],
                ["Garde à domicile", "chez vous", "Très forte",
                 "L'enfant ne se déplace pas. Le coût est le plus élevé, sauf en garde partagée."],
                ["Garde partagée", "chez vous / chez l'autre famille", "Forte",
                 "Coût divisé entre deux familles, mais il faut s'entendre à trois — et deux "
                 "contrats coexistent."],
            ],
            note="Aucun montant ici, volontairement : les barèmes changent chaque année et le "
                 "reste à charge dépend de vos revenus. Le simulateur d'un site officiel "
                 "donnera un chiffre à jour, ce qu'une fiche figée ne peut pas faire.",
        ),
        _points(
            "Ce qu'on découvre trop tard",
            [
                {"titre": "Les délais ne sont pas les mêmes",
                 "detail": "Un dossier de crèche se dépose souvent pendant la grossesse, avec "
                           "des commissions d'attribution au printemps. Une assistante "
                           "maternelle se contacte aussi tôt : les places convoitées partent "
                           "des mois à l'avance."},
                {"titre": "Être employeur est un vrai engagement",
                 "detail": "Contrat, paie mensualisée, congés, fin de contrat. Ce n'est pas "
                           "difficile, mais ce n'est pas rien — et c'est ce qui distingue "
                           "réellement l'assistante maternelle de la crèche."},
                {"titre": "Le mode de garde peut changer en cours de route",
                 "detail": "Une place se libère, un rythme de travail change. Prévoir la "
                           "sortie dès l'entrée coûte une conversation ; ne pas la prévoir "
                           "coûte un conflit."},
            ],
        ),
    ],
}


# ─── Checklist d'entretien ────────────────────────────────────────────────────────────
# Chaque question porte son POURQUOI. Une liste de questions sans le pourquoi se récite ;
# avec, elle s'adapte — et on sait quoi faire de la réponse.
#
# ⚠️ En phase 1, la checklist est faite pour être IMPRIMÉE : elle n'a pas de cases à cocher
# interactives. Offrir des cases qui oublient tout au changement de page serait pire que ne
# rien offrir — la saisie par candidate arrive en phase 2, avec sa table.

# Chaque question porte une CLÉ STABLE : c'est elle qui est stockée avec la réponse d'un
# entretien. Une clé dérivée du texte se perdrait à la première reformulation, une clé
# dérivée du rang se décalerait à la première insertion — les deux effaceraient
# silencieusement des réponses déjà données. Ne JAMAIS renommer une clé existante.
_CHECKLIST: list[dict] = [
    {"titre": "Au téléphone, avant de se déplacer", "questions": [
        {"cle": "tel_place", "texte": "Avez-vous une place disponible, et à partir de quelle date ?",
         "pourquoi": "Évite un déplacement pour une place déjà prise."},
        {"cle": "tel_horaires", "texte": "Quels jours et quels horaires pouvez-vous couvrir ?",
         "pourquoi": "Un décalage d'une demi-heure le matin suffit à rendre l'accueil impossible."},
        {"cle": "tel_tarif", "texte": "Quel est votre tarif horaire net, et vos indemnités ?",
         "pourquoi": "Pour comparer sur la même base : le tarif seul ne dit pas le coût."},
        {"cle": "tel_agrement", "texte": "Votre agrément est-il en cours de validité, et pour combien de places ?",
         "pourquoi": "Sans agrément valide, pas d'aide et l'accueil n'est pas légal."},
    ]},
    {"titre": "L'agrément et le cadre", "questions": [
        {"cle": "agr_numero", "texte": "Numéro d'agrément, département, date d'échéance ?",
         "pourquoi": "À noter et à photographier dès la première visite — c'est la pièce de base."},
        {"cle": "agr_effectif", "texte": "Combien d'enfants accueillez-vous, et de quels âges ?",
         "pourquoi": "Détermine l'attention disponible et le rythme de la journée."},
        {"cle": "agr_restrictions", "texte": "Votre agrément porte-t-il des restrictions ?",
         "pourquoi": "Certaines limitent l'âge ou le nombre — mieux vaut le savoir avant."},
        {"cle": "agr_formation", "texte": "Formation initiale suivie, PSC1 à jour, formations continues ?",
         "pourquoi": "Le secourisme n'est pas un détail quand on garde un nourrisson."},
        {"cle": "agr_experience", "texte": "Depuis combien de temps exercez-vous ? Puis-je joindre des parents ?",
         "pourquoi": "Une référence joignable en dit plus qu'une heure d'entretien."},
    ]},
    {"titre": "Le lieu", "questions": [
        {"cle": "lieu_visite", "texte": "Puis-je voir les pièces où mon enfant vivra et dormira ?",
         "pourquoi": "Une visite refusée est une réponse en soi."},
        {"cle": "lieu_type", "texte": "Maison ou appartement, étage, ascenseur, extérieur ?",
         "pourquoi": "Conditionne les sorties quotidiennes et l'accès en poussette."},
        {"cle": "lieu_animaux_tabac", "texte": "Y a-t-il des animaux ? Quelqu'un fume-t-il, même dehors ?",
         "pourquoi": "Deux sujets qu'on n'ose pas aborder, et qu'on regrette de ne pas avoir abordés."},
        {"cle": "lieu_presents", "texte": "Qui d'autre est présent au domicile dans la journée ?",
         "pourquoi": "Adolescent, conjoint en télétravail, parent âgé : ça change le quotidien."},
        {"cle": "lieu_securite", "texte": "Comment est sécurisé l'espace : escaliers, prises, fenêtres, piscine ?",
         "pourquoi": "La question ouverte vaut mieux que l'inspection : la réponse montre l'attention portée."},
    ]},
    {"titre": "Le quotidien", "questions": [
        {"cle": "quo_journee", "texte": "À quoi ressemble une journée type ?",
         "pourquoi": "La réponse la plus révélatrice de tout l'entretien."},
        {"cle": "quo_repas", "texte": "Qui fournit les repas, et comment sont-ils préparés ?",
         "pourquoi": "Change le coût, et se met au contrat."},
        {"cle": "quo_sommeil", "texte": "Comment gérez-vous les siestes, et si mon enfant ne s'endort pas ?",
         "pourquoi": "Le sommeil est le premier sujet de désaccord avec un mode de garde."},
        {"cle": "quo_sorties", "texte": "Sortez-vous ? Où, comment, à quelle fréquence ?",
         "pourquoi": "Nécessite une autorisation écrite, et une assurance si c'est en voiture."},
        {"cle": "quo_ecrans", "texte": "Y a-t-il des écrans dans la journée ?",
         "pourquoi": "Mieux vaut une réponse franche maintenant qu'une découverte dans six mois."},
        {"cle": "quo_transmission", "texte": "Comment me rendez-vous compte de la journée ?",
         "pourquoi": "Cahier, message, oral : aucun n'est meilleur, mais il faut en choisir un."},
    ]},
    {"titre": "Santé et sécurité", "questions": [
        {"cle": "san_fievre", "texte": "Que faites-vous si mon enfant a de la fièvre ?",
         "pourquoi": "Vérifie le réflexe, et l'ordre dans lequel on est prévenu."},
        {"cle": "san_malade", "texte": "Acceptez-vous un enfant malade, et dans quelles limites ?",
         "pourquoi": "Détermine combien de jours vous devrez poser dans l'année."},
        {"cle": "san_traitement", "texte": "Administrez-vous un traitement ? Avez-vous déjà géré un PAI ?",
         "pourquoi": "Indispensable en cas d'allergie ou de traitement au long cours."},
        {"cle": "san_vaccins", "texte": "Quelles vaccinations exigez-vous ?",
         "pourquoi": "Question légitime des deux côtés, à poser tôt."},
        {"cle": "san_urgence", "texte": "Qui appelez-vous en urgence si vous ne me joignez pas ?",
         "pourquoi": "À écrire, avec les numéros, avant le premier jour."},
    ]},
    {"titre": "Organisation et imprévus", "questions": [
        {"cle": "org_absence_pro", "texte": "Comment faites-vous quand vous êtes malade ou en formation ?",
         "pourquoi": "Aucune obligation de remplacement ne pèse sur elle : autant le savoir."},
        {"cle": "org_conges", "texte": "Quand fixez-vous vos congés, et me les annoncez-vous quand ?",
         "pourquoi": "Les dates se calent tôt dans l'année ; l'ignorer désorganise l'été."},
        {"cle": "org_retard", "texte": "Que se passe-t-il si je suis en retard le soir ?",
         "pourquoi": "Évite la tension du premier retard, qui arrivera."},
        {"cle": "org_absence_enfant", "texte": "Et si mon enfant est absent une semaine ?",
         "pourquoi": "La mensualisation reste due sauf cas prévus : à clarifier avant de signer."},
    ]},
    {"titre": "L'argent, dit clairement", "questions": [
        {"cle": "arg_tarif", "texte": "Tarif horaire net par enfant, et pour combien d'heures par semaine ?",
         "pourquoi": "Base de la mensualisation."},
        {"cle": "arg_indemnites", "texte": "Indemnité d'entretien, repas, kilomètres : quels montants ?",
         "pourquoi": "S'ajoutent au salaire et ne se cotisent pas — à distinguer dès le début."},
        {"cle": "arg_annee", "texte": "Année complète ou année incomplète ?",
         "pourquoi": "Deux formules de mensualisation différentes. LA question qui fausse les paies."},
        {"cle": "arg_heures_feries", "texte": "Comment traitez-vous les heures au-delà du prévu, et les jours fériés ?",
         "pourquoi": "Sujet récurrent : autant l'écrire une fois."},
    ]},
    {"titre": "Le contrat", "questions": [
        {"cle": "con_adaptation", "texte": "Prévoyez-vous une période d'adaptation ? Comment se déroule-t-elle ?",
         "pourquoi": "Différente de la période d'essai — et elle se rémunère."},
        {"cle": "con_essai", "texte": "Quelle période d'essai proposez-vous ?",
         "pourquoi": "C'est le moment où chacun peut se retirer sans avoir à se justifier."},
        {"cle": "con_modele", "texte": "Avez-vous un modèle de contrat, et qu'y tenez-vous particulièrement ?",
         "pourquoi": "Sa réponse dit ce qui s'est mal passé avec d'autres familles."},
        {"cle": "con_pieces", "texte": "Pouvez-vous me transmettre agrément et attestations d'assurance ?",
         "pourquoi": "À demander avant de signer, pas après."},
    ]},
    {"titre": "La question qu'on oublie", "questions": [
        {"cle": "res_confiance", "texte": "Est-ce que je me vois lui confier mon enfant, tous les jours, pendant deux ans ?",
         "pourquoi": "Aucune réponse aux questions précédentes ne remplace celle-ci. Une "
                     "grille parfaitement remplie ne fait pas une bonne rencontre, et un "
                     "malaise sans raison identifiable est une raison suffisante."},
    ]},
]



# ─── Fiche « Employer chez soi » — profils CESU (phase 5) ─────────────────────────────
# Elle ne s'affiche que pour `aide_domicile` et `autre_sap`. Le reste du contenu — le
# guichet, les droits et devoirs, le contrat — vaut déjà pour eux : c'était le pari des
# phases 1 à 3, et cette fiche est ce qu'il restait vraiment à écrire.
#
# La question qui domine ici n'est pas celle d'une assistante maternelle. Chez la nounou,
# tout découle de l'agrément ; ici, tout découle d'un choix fait AVANT de chercher
# quelqu'un : emploi direct, mandataire, ou prestataire. Les trois s'appellent « aide à
# domicile » dans le langage courant, et ne donnent ni le même employeur, ni les mêmes
# obligations, ni le même recours quand ça se passe mal.

_FICHE_EMPLOI_CHEZ_SOI = {
    "cle": "emploi-chez-soi",
    "titre": "Emploi direct, mandataire ou prestataire : le choix qui précède tout",
    "chapeau": "Les trois se disent « aide à domicile » et ne recouvrent pas la même chose. "
               "Ce qui change : QUI est l'employeur — donc qui recrute, qui paie, qui "
               "remplace en cas d'absence, et qui est responsable.",
    "blocs": [
        _tableau(
            "Ce que chacun engage",
            ["", "Emploi direct", "Mandataire", "Prestataire"],
            [
                ["Employeur", "Vous", "Vous", "L'organisme"],
                ["Qui recrute", "Vous", "L'organisme propose, vous décidez", "L'organisme"],
                ["Qui remplace en cas d'absence", "Personne — vous vous débrouillez",
                 "L'organisme cherche", "L'organisme, c'est son engagement"],
                ["Qui gère paie et déclarations", "Vous, via le CESU",
                 "L'organisme, contre frais de gestion", "L'organisme"],
                ["En cas de litige avec la personne", "Vous êtes l'employeur",
                 "Vous êtes l'employeur", "Vous changez de prestataire"],
                ["Coût horaire", "Le plus bas", "Intermédiaire", "Le plus élevé"],
            ],
            note="Le prestataire coûte plus cher parce qu'il porte le risque : l'absence, "
                 "le remplacement, le conflit. En emploi direct, ce risque reste chez vous — "
                 "c'est exactement ce que paie la différence de prix.",
        ),
        _points(
            "Ce qui se décide maintenant et se paie plus tard",
            [
                {"titre": "L'absence, prévue ou non",
                 "detail": "Congés, arrêt maladie, départ. En emploi direct, personne ne "
                           "vient : c'est le point qu'on ne mesure qu'au premier lundi sans "
                           "aide, et il pèse plus lourd que l'écart de tarif."},
                {"titre": "Les clés de chez vous",
                 "detail": "Qui les détient, combien d'exemplaires, ce qui se passe en cas "
                           "de perte, et leur restitution à la fin. À écrire quel que soit "
                           "le mode — c'est une remise d'objet, pas une marque de méfiance."},
                {"titre": "L'assurance",
                 "detail": "Vérifiez que votre responsabilité civile couvre l'accident d'une "
                           "personne travaillant à votre domicile. Un appel à votre "
                           "assureur, une fois, et c'est réglé."},
            ],
            ton="attention",
        ),
        _vis_a_vis(
            "En emploi direct, ce que chacun doit à l'autre",
            [
                {"sujet": "Le travail à faire",
                 "gauche": "Dire précisément les tâches attendues, et ce qui n'en fait pas "
                           "partie. « Le ménage » ne veut rien dire.",
                 "droite": "Exécuter ce qui est convenu, signaler une tâche impossible ou "
                           "dangereuse plutôt que de l'improviser."},
                {"sujet": "Le matériel et les produits",
                 "gauche": "Les fournir, en état, et adaptés. Un produit imposé qui provoque "
                           "une réaction engage votre responsabilité.",
                 "droite": "En prendre soin et signaler ce qui manque avant d'en manquer."},
                {"sujet": "Les horaires",
                 "gauche": "Les fixer au contrat et les respecter. Une heure ajoutée est une "
                           "heure due.",
                 "droite": "Être là aux heures convenues, prévenir dès que possible en cas "
                           "d'empêchement."},
                {"sujet": "La fin du contrat",
                 "gauche": "Préavis, solde de tout compte, certificat de travail. Un "
                           "licenciement se motive — même pour quelques heures par semaine.",
                 "droite": "Préavis en cas de démission."},
            ],
            gauche="Vous, employeur", droite="La personne employée",
        ),
        _texte(
            "L'avantage fiscal, et ce qui le réduit",
            "Les sommes versées ouvrent droit au crédit d'impôt « services à la personne », "
            "dans la limite d'un plafond annuel. L'aide à domicile va en case 7DB — et non "
            "dans les cases de garde d'enfant, qui ne concernent que l'accueil HORS de votre "
            "domicile. C'est le lieu qui décide, pas le métier.",
            "Les aides perçues et l'avance immédiate du crédit d'impôt se déduisent des "
            "sommes déclarées (case 7DR). C'est l'oubli le plus fréquent du dispositif : il "
            "revient à déclarer une dépense qu'on n'a pas supportée.",
            "L'onglet « Aide à la déclaration » d'Administration reprend ces cases à partir "
            "de vos contrats et de votre journal mensuel.",
        ),
        _texte(
            "L'avance immédiate, en un mot",
            "Plutôt que d'attendre l'année suivante, le crédit d'impôt peut être déduit "
            "directement de ce que vous versez chaque mois. C'est une option à activer sur "
            "le site du CESU, et elle change le montant qui sort de votre compte — pensez à "
            "la reporter dans le calcul du reste à charge, sans quoi il sera surestimé.",
        ),
    ],
    "profils": ("aide_domicile", "autre_sap"),
}

# ─── Assemblage ───────────────────────────────────────────────────────────────────────

# Ordre voulu : le guichet d'abord (c'est l'erreur qui coûte), puis les obligations, puis
# la comparaison. Un lecteur qui s'arrête après la première fiche aura lu la plus utile.
_FICHES = [_FICHE_GUICHET, _FICHE_DROITS, _FICHE_MODES, _FICHE_EMPLOI_CHEZ_SOI]


def fiches(p: Profil) -> list[dict]:
    """
    Fiches pour ce profil.

    Le **tronc commun** est écrit une fois et vaut pour tous : c'est la même convention
    collective et le même contrat. Une fiche peut déclarer `profils` pour se restreindre —
    « Emploi direct, mandataire ou prestataire » n'a aucun sens chez une assistante
    maternelle, et l'afficher ferait douter du reste.

    Le filtrage est **inclusif par défaut** : une fiche sans `profils` vaut partout. C'est
    l'inverse qui serait piégeux — une fiche ajoutée sans y penser disparaîtrait de tous les
    profils, sans que rien ne le signale.
    """
    cle = getattr(p, "cle", None) or "assmat"
    return [f for f in _FICHES if cle in f.get("profils", (cle,))]


def checklist(p: Profil) -> list[dict]:
    """
    Checklist d'entretien. Rendue telle quelle pour l'instant : elle est écrite pour
    l'accueil d'un enfant. Les autres profils la reçoivent aussi — l'ossature (cadre, lieu,
    quotidien, argent, contrat) vaut pour toute embauche à domicile —, mais le routeur
    prévient que le détail est calibré pour `assmat`.
    """
    return _CHECKLIST
