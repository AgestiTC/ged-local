"""
Seeds de dossiers thématiques — contenus pré-remplis livrés avec Matothèque
==========================================================================
Un « seed » = un dossier thématique complet (titre + ressources) installable en un
appel API (`POST /api/dossiers/seed/{cle}`). L'installation est **idempotente par
slug** : réinstaller un seed déjà présent ne crée pas de doublon, il complète le
dossier existant avec les ressources dont l'URL (ou, à défaut, le titre) manque.

Ajouter un seed = ajouter une entrée dans `SEEDS`. Aucun autre fichier à toucher.

⚠️ Les liens et disponibilités (replay, éditions) se périment : les ressources
installées sont un point de départ à maintenir depuis l'interface, pas une vérité
figée. Les entrées sans URL sont volontaires — la ressource se retrouve par son titre.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.dossier import DossierThematique, Ressource

log = get_logger(__name__)


# ─── Dossier « Devenir parent » ───────────────────────────────────────────────
# Sources relevées en septembre 2026. `note` = ce que la ressource apporte de
# spécifique ; c'est ce qui distingue un dossier d'une simple liste de liens.

# Texte INTÉGRAL des prompts de recherche livrés avec le dossier. Ils alimentent le champ
# `contenu` des ressources de type « prompt » : l'interface les déplie et les copie d'un clic,
# pour les coller dans une IA connectée au web (Claude, ChatGPT, Perplexity, Gemini).
# Les crochets [MAJUSCULES] sont à remplacer avant envoi.

_PROMPT_PRINCIPAL = """Tu es documentaliste spécialisé en périnatalité et en parentalité. Tu as accès au web : utilise-le et vérifie chaque référence.

OBJECTIF
Constituer une bibliographie de sources sur la maternité, la paternité et le fait de devenir parent, destinée à [PRÉCISER : futurs parents / père en préparation / travail de recherche / conférence].

PÉRIMÈTRE
- Langue : français en priorité, anglais accepté si la ressource est majeure (signale-le).
- Période : privilégie 2018-2026, sauf classiques indépassables (signale-les comme tels).
- Aire : France et francophonie, avec les références internationales de référence.

CATÉGORIES ATTENDUES (10 à 15 entrées chacune)
1. Podcasts — en distinguant : maternité/matrescence, paternité, parentalité mixte
2. Chaînes et vidéos YouTube — médias, professionnels de santé, conférences
3. Documentaires, émissions TV et films — avec la plateforme de visionnage actuelle
4. Livres — en distinguant : guides pratiques, essais/sciences sociales, récits
5. Articles, rapports institutionnels et études scientifiques — sources primaires uniquement
6. Associations et dispositifs de soutien en France

POUR CHAQUE ENTRÉE, DONNE EXACTEMENT
- Titre exact | Auteur ou producteur | Année | Plateforme ou éditeur
- Un lien vérifié (indique-le si tu n'as pas pu le vérifier)
- 1 à 2 phrases : ce que la ressource apporte de spécifique
- Public visé et niveau d'exigence (grand public / averti / spécialisé)
- 3 mots-clés

CONTRAINTES DE FIABILITÉ — IMPORTANTES
- N'invente aucun titre, auteur, date ou URL. Si tu doutes, écris « à vérifier » et explique pourquoi.
- Distingue clairement ce que tu as vérifié en ligne de ce que tu restitues de mémoire.
- Signale les sources controversées ou militantes et sur quoi porte la controverse.
- Équilibre les points de vue : médical, psychologique, sociologique, vécu.
- Ne néglige pas la paternité : c'est le versant le moins documenté, cherche activement.

FORMAT
Un tableau markdown par catégorie, puis une section finale « Par où commencer » avec 5 ressources classées dans un ordre de découverte argumenté."""

_PROMPT_PATERNITE = """Même rôle et mêmes contraintes de fiabilité que précédemment, mais concentre-toi uniquement sur la PATERNITÉ et le second parent.

Cherche spécifiquement :
- podcasts et chaînes tenus par des pères, en français, actifs après 2023
- la recherche sur le cerveau paternel, l'ocytocine et l'effet du congé de paternité
- l'état du droit français : durée du congé, indemnisation, taux de recours réel
- les récits de co-parents non biologiques et de familles homoparentales
- ce qui existe sur la dépression post-natale paternelle, sujet peu couvert

Dis-moi explicitement où les sources manquent ou sont de faible qualité — cette lacune est en soi une information."""

_PROMPT_SCIENTIFIQUE = """Même rôle, mais je ne veux QUE des sources primaires vérifiables : études évaluées par les pairs, méta-analyses Cochrane, rapports d'agences publiques (HAS, Santé publique France, INSPQ, OMS), données de cohortes (Elfe, Epifane).

Pour chaque source : auteurs, revue, année, DOI ou lien officiel, type d'étude, taille d'échantillon, principal résultat en une phrase, et la principale limite méthodologique.

Couvre : transformations cérébrales et hormonales de la grossesse et de la paternité, dépression périnatale et son dépistage, sommeil du nourrisson, allaitement, violences obstétricales, effets du congé parental.

Si une croyance répandue n'est pas soutenue par les données, dis-le et cite l'étude qui la contredit."""

_PROMPT_PLAN = """À partir des sources que tu viens de rassembler, propose un plan de [ARTICLE / VIDÉO / ÉPISODE DE PODCAST / ATELIER] destiné à [PUBLIC] et d'une durée de [DURÉE].

Structure attendue :
- un angle unique, formulé en une phrase, qui ne soit pas déjà traité par les sources listées
- 4 à 6 parties, chacune adossée à au moins une source précise de la liste
- pour chaque partie : l'idée principale, la citation ou le chiffre qui l'appuie, et sa source
- les 3 objections ou nuances qu'un spécialiste opposerait à cet angle
- ce qu'il reste à vérifier avant publication

Ne reprends aucune source que tu n'as pas vérifiée à l'étape précédente."""

_METHODE = """QUATRE RÈGLES POUR INTERROGER UNE IA SUR CE SUJET

1. Enchaîner, ne pas tout demander d'un coup.
   Lance le prompt principal, puis relance catégorie par catégorie :
   « approfondis uniquement la catégorie 3, 15 entrées de plus ».
   La qualité chute nettement au-delà de 60 entrées d'un seul jet.

2. Toujours exiger la vérification des liens.
   Les titres inventés et les URL mortes sont l'erreur la plus fréquente sur ce type de
   demande. La clause « n'invente aucun titre, écris à-vérifier » réduit fortement le
   problème sans l'éliminer : recoupe à la main les 5 sources sur lesquelles tu vas
   réellement t'appuyer.

3. Ancrer dans le temps et dans l'espace.
   « Actif en 2026 », « disponible en France », « en replay sur france.tv ». Sans ces
   bornes, l'IA remonte des podcasts arrêtés depuis cinq ans et des documentaires
   introuvables.

4. Demander ce qui manque.
   « Où les sources sont-elles faibles ou absentes ? » est souvent la question la plus
   rentable — c'est ce qui distingue un état des lieux d'une simple liste."""


_DEVENIR_PARENT: list[dict] = [
    # ── Podcasts · maternité, matrescence, post-partum ────────────────────────
    {"groupe": "Podcasts — maternité et matrescence", "type": "podcast", "favori": True,
     "titre": "La Matrescence", "auteur": "Clémentine Sarlat",
     "tags": ["matrescence", "post-partum", "charge mentale"],
     "note": "La référence francophone. Un thème par épisode avec des spécialistes (psys, sages-femmes, chercheurs). Point d'entrée idéal."},
    {"groupe": "Podcasts — maternité et matrescence", "type": "podcast",
     "titre": "Bliss Stories", "auteur": "Clémentine Galey",
     "tags": ["accouchement", "témoignages"],
     "note": "Récits d'accouchement et de maternité à la première personne, sans filtre. Le contrepoint vécu des guides médicaux."},
    {"groupe": "Podcasts — maternité et matrescence", "type": "podcast",
     "titre": "Sage-Meuf", "auteur": "Anna Roy",
     "tags": ["sage-femme", "grossesse", "suites de couches"],
     "note": "Une sage-femme répond aux questions concrètes de la grossesse et des suites de couches. Très pratique, ton direct."},
    {"groupe": "Podcasts — maternité et matrescence", "type": "podcast",
     "titre": "Un podcast à soi", "auteur": "Charlotte Bienaimé, ARTE Radio",
     "url": "https://www.arteradio.com/emission/un_podcast_soi",
     "tags": ["documentaire sonore", "féminisme", "charge mentale"],
     "note": "Documentaire sonore féministe. Plusieurs numéros sur l'accouchement, le désir d'enfant et le travail parental. Qualité de fabrication rare."},
    {"groupe": "Podcasts — maternité et matrescence", "type": "podcast",
     "titre": "Le Nid", "auteur": "parents et experts de l'enfance",
     "tags": ["parentalité", "petite enfance"],
     "note": "Espace de partage sans jugement : vécus de parents alternés avec des spécialistes de la petite enfance."},
    {"groupe": "Podcasts — maternité et matrescence", "type": "podcast",
     "titre": "Parents Informés", "auteur": "Charline Roumagnac",
     "tags": ["experts", "interview"],
     "note": "Format interview de professionnels, sujet par sujet. Utile quand on cherche une réponse sur un point précis."},
    {"groupe": "Podcasts — maternité et matrescence", "type": "podcast",
     "titre": "Bébé arrive / Devenir parent", "auteur": "Les Adultes de demain",
     "url": "https://www.lesadultesdedemain.com/podcast-bb-arrive-devenir-parent",
     "tags": ["préparation", "série"],
     "note": "Série dédiée à la préparation à l'arrivée du bébé, pensée comme un parcours plutôt qu'un catalogue d'épisodes."},
    {"groupe": "Podcasts — maternité et matrescence", "type": "podcast",
     "titre": "Le Cœur sur la table", "auteur": "Victoire Tuaillon, Binge Audio",
     "tags": ["couple", "famille", "essai"],
     "note": "Sur l'amour et la famille comme institutions. Aide à replacer le couple parental dans un contexte politique et social."},

    # ── Podcasts · paternité ──────────────────────────────────────────────────
    {"groupe": "Podcasts — paternité", "type": "podcast", "favori": True,
     "titre": "Papatriarcat", "auteur": "Cédric Rostein",
     "tags": ["paternité", "masculinités"],
     "note": "Repenser le rôle du père : déconstruction des modèles hérités, place des hommes dans le soin et l'éducation. Le plus construit du lot."},
    {"groupe": "Podcasts — paternité", "type": "podcast",
     "titre": "Devenir Papa", "auteur": "Antoine Le Guilloux",
     "url": "https://open.spotify.com/show/3e0LTZ7BxfTpeClgtgKOwc",
     "tags": ["paternité", "premiers mois"],
     "note": "Des papas par des papas, plus des interviews de soignants et de spécialistes petite enfance. Format intime, très accessible."},
    {"groupe": "Podcasts — paternité", "type": "podcast",
     "titre": "Le podcast des Paternelles", "auteur": "Houssem Loussaïef",
     "url": "https://podcasts.apple.com/fr/podcast/le-podcast-des-paternelles/id1771886685",
     "tags": ["paternité", "témoignages"],
     "note": "Rencontres hebdomadaires avec des pères, sujet par sujet."},
    {"groupe": "Podcasts — paternité", "type": "podcast",
     "titre": "Histoires de Darons", "auteur": None,
     "tags": ["paternité", "témoignages"],
     "note": "Points de vue d'hommes sur la paternité, avec aussi des « daronnes » invitées à témoigner."},
    {"groupe": "Podcasts — paternité", "type": "podcast",
     "titre": "Père", "auteur": "Florence Vertanessian",
     "url": "https://www.lokko.fr/2025/01/27/pere-par-florence-vertanessian/",
     "tags": ["paternité", "récit", "transmission"],
     "note": "Le père qu'on a eu, celui qu'on n'a pas eu, celui qu'on essaie d'être. Plus littéraire et introspectif que les autres."},
    {"groupe": "Podcasts — paternité", "type": "podcast",
     "titre": "Papas Poules", "auteur": "Vincent, Florian et Jérémie",
     "tags": ["paternité", "humour"],
     "note": "Trois pères, ton humoristique. Bon pour dédramatiser les premiers mois."},
    {"groupe": "Podcasts — paternité", "type": "podcast",
     "titre": "Papa Velours", "auteur": None,
     "tags": ["paternité", "équilibre pro/perso"],
     "note": "Ce dont les hommes ne parlent pas d'habitude : équilibre vie pro / vie perso, vulnérabilité, transmission."},
    {"groupe": "Podcasts — paternité", "type": "podcast",
     "titre": "À quoi pense Papa ?", "auteur": None,
     "tags": ["paternité"],
     "note": "Conversations de pères sur leurs doutes et leurs apprentissages."},
    {"groupe": "Podcasts — paternité", "type": "podcast",
     "titre": "Les Couilles sur la table", "auteur": "Victoire Tuaillon, Binge Audio",
     "tags": ["masculinités", "travail domestique", "essai"],
     "note": "Pas un podcast de parentalité, mais plusieurs épisodes de référence sur les pères et le travail domestique. Chercher « père » dans le catalogue."},

    # ── Podcasts · anglophones ────────────────────────────────────────────────
    {"groupe": "Podcasts — en anglais", "type": "podcast", "langue": "en", "favori": True,
     "titre": "Good Inside", "auteur": "Dr Becky Kennedy",
     "tags": ["psychologie", "éducation"],
     "note": "Psychologie clinique appliquée à la parentalité quotidienne. Extrêmement pragmatique, sans culpabilisation."},
    {"groupe": "Podcasts — en anglais", "type": "podcast", "langue": "en",
     "titre": "Janet Lansbury — Unruffled", "auteur": "Janet Lansbury",
     "tags": ["RIE", "bébé", "épisodes courts"],
     "note": "Approche RIE : respect du bébé comme personne. Épisodes courts, chacun sur une situation concrète."},
    {"groupe": "Podcasts — en anglais", "type": "podcast", "langue": "en",
     "titre": "The Longest Shortest Time", "auteur": None,
     "tags": ["récits", "post-partum", "couple"],
     "note": "Le classique du récit de parentalité, très bien produit. Archives riches sur le post-partum et le couple."},
    {"groupe": "Podcasts — en anglais", "type": "podcast", "langue": "en",
     "titre": "The Birth Hour", "auteur": None,
     "tags": ["accouchement", "témoignages"],
     "note": "Uniquement des récits d'accouchement, dans toute leur diversité (voie basse, césarienne, maison, complications)."},
    {"groupe": "Podcasts — en anglais", "type": "podcast", "langue": "en",
     "titre": "ParentData", "auteur": "Emily Oster",
     "tags": ["données", "esprit critique"],
     "note": "Une économiste passe les recommandations de grossesse et de petite enfance au crible des données. Antidote aux injonctions."},

    # ── Chaînes YouTube ───────────────────────────────────────────────────────
    {"groupe": "YouTube — médias et institutions", "type": "chaine", "favori": True,
     "titre": "La Maison des Maternelles", "auteur": "France Télévisions",
     "tags": ["grossesse", "allaitement", "sommeil"],
     "note": "Le fonds le plus vaste en français : des milliers de séquences courtes validées par des professionnels."},
    {"groupe": "YouTube — médias et institutions", "type": "chaine",
     "titre": "ARTE — documentaires en accès libre", "auteur": "ARTE",
     "url": "https://www.youtube.com/@arte",
     "tags": ["documentaire", "naissance", "paternité"],
     "note": "Publie régulièrement des documentaires entiers sur la naissance et le cerveau parental. Chercher « paternité », « naissance »."},
    {"groupe": "YouTube — médias et institutions", "type": "chaine",
     "titre": "Institut de la Parentalité", "auteur": "Institut de la Parentalité",
     "url": "https://www.youtube.com/channel/UCcDamxtNGRkfaRfxCqS4MPg",
     "tags": ["conférences", "prévention"],
     "note": "Conférences et webinaires sur la relation parent-enfant. Plus long, plus dense, gratuit."},
    {"groupe": "YouTube — médias et institutions", "type": "chaine",
     "titre": "PARENTS.fr et Doctissimo", "auteur": None,
     "tags": ["vulgarisation"],
     "note": "Formats courts de vulgarisation médicale. Pratique pour une question ponctuelle, à recouper avec les sources officielles."},
    {"groupe": "YouTube — médias et institutions", "type": "chaine",
     "titre": "Angélique, Marquise des Langes", "auteur": None,
     "tags": ["vlog", "vécu"],
     "note": "Chaîne de créatrice couvrant grossesse, naissance et vie de mère sur la durée. Le versant vécu, hors média."},
    {"groupe": "YouTube — professionnels de santé", "type": "chaine", "langue": "en", "favori": True,
     "titre": "Mama Doctor Jones", "auteur": "Dr Danielle Jones, gynécologue-obstétricienne",
     "tags": ["mythes", "obstétrique", "sourcé"],
     "note": "Démonte les mythes de grossesse et d'accouchement avec les sources médicales à l'appui. Rigoureuse et drôle."},
    {"groupe": "YouTube — professionnels de santé", "type": "chaine", "langue": "en",
     "titre": "Emma Hubbard", "auteur": "physiothérapeute pédiatrique",
     "tags": ["développement moteur", "bébé"],
     "note": "Développement moteur du bébé mois par mois, avec démonstrations. Rassure sur le normal, signale ce qui ne l'est pas."},
    {"groupe": "YouTube — professionnels de santé", "type": "chaine", "langue": "en",
     "titre": "Bridget Teyler", "auteur": "doula",
     "tags": ["accouchement", "co-parent", "plan de naissance"],
     "note": "Préparation à l'accouchement : positions, respiration, plan de naissance, rôle du partenaire. Très utile pour le co-parent."},
    {"groupe": "YouTube — professionnels de santé", "type": "chaine", "langue": "en",
     "titre": "Pregnancy and Postpartum TV", "auteur": None,
     "tags": ["périnée", "diastasis", "post-partum"],
     "note": "Rééducation abdominale et périnéale, reprise du sport. Le sujet le moins bien couvert ailleurs."},
    {"groupe": "YouTube — conférences et vidéos uniques", "type": "video", "langue": "en", "favori": True,
     "titre": "A new way to think about the transition to motherhood", "auteur": "Alexandra Sacks, TED",
     "tags": ["matrescence", "7 minutes"],
     "note": "Sept minutes qui expliquent la matrescence mieux que la plupart des livres : devenir mère est une transition développementale, pas un défaut de caractère."},
    {"groupe": "YouTube — conférences et vidéos uniques", "type": "video", "favori": True,
     "titre": "Paternité, une métamorphose décryptée", "auteur": "ARTE",
     "url": "https://www.youtube.com/watch?v=13_MB7OFttw",
     "tags": ["paternité", "neurosciences", "hormones"],
     "note": "Ce qui change physiologiquement chez les pères : hormones, cerveau, attachement. Le pendant masculin de la matrescence."},

    # ── Documentaires ─────────────────────────────────────────────────────────
    {"groupe": "Documentaires — naissance et maternité", "type": "documentaire", "favori": True,
     "titre": "Naître mère", "auteur": "Cécile Khindria et Armelle de Rocquigny",
     "url": "https://www.francetvpro.fr/contenu-de-presse/68857902",
     "tags": ["première grossesse", "post-partum"],
     "note": "Suit une première grossesse du dernier trimestre aux premiers mois du bébé. Regard sans fard sur le bonheur, la douleur et l'impuissance mêlés."},
    {"groupe": "Documentaires — naissance et maternité", "type": "documentaire",
     "titre": "Post-partum, le documentaire", "auteur": None,
     "url": "https://postpartum-ledocumentaire.com/",
     "tags": ["post-partum", "indépendant"],
     "note": "Documentaire indépendant entièrement consacré à l'après-naissance — la période la plus mal préparée et la moins racontée."},
    {"groupe": "Documentaires — naissance et maternité", "type": "documentaire",
     "titre": "Le Premier Cri", "auteur": "Gilles de Maistre, 2007",
     "tags": ["naissance", "international"],
     "note": "Dix naissances sur cinq continents, le même jour. Relativise puissamment les normes occidentales de l'accouchement."},
    {"groupe": "Documentaires — naissance et maternité", "type": "documentaire",
     "titre": "Entre leurs mains", "auteur": "Céline Darmayan, 2012",
     "tags": ["sages-femmes", "physiologique"],
     "note": "Sages-femmes et accouchement physiologique, y compris à domicile. Documente un débat français encore vif."},
    {"groupe": "Documentaires — naissance et maternité", "type": "documentaire",
     "titre": "Brisons le tabou", "auteur": "RMC Story",
     "tags": ["post-partum", "série documentaire"],
     "note": "Série documentaire dont un volet porte sur le post-partum : fatigue, transformations du corps, doutes."},
    {"groupe": "Documentaires — naissance et maternité", "type": "documentaire", "langue": "en",
     "titre": "Babies", "auteur": "Netflix, 2020",
     "tags": ["science", "première année"],
     "note": "Série documentaire scientifique sur la première année : sommeil, alimentation, premiers pas, cerveau parental."},
    {"groupe": "Documentaires — naissance et maternité", "type": "documentaire", "langue": "en",
     "titre": "The Business of Being Born", "auteur": "Abby Epstein, 2008",
     "tags": ["médicalisation", "enquête"],
     "note": "Enquête sur la médicalisation de l'accouchement aux États-Unis. Contexte américain, mais questions transposables."},
    {"groupe": "Documentaires — naissance et maternité", "type": "documentaire",
     "titre": "Bébés", "auteur": "Thomas Balmès, 2010",
     "tags": ["observation", "international"],
     "note": "Quatre bébés — Namibie, Mongolie, Japon, États-Unis — de la naissance aux premiers pas. Sans commentaire : on observe."},

    # ── Émissions TV ──────────────────────────────────────────────────────────
    {"groupe": "Émissions et magazines TV", "type": "emission",
     "titre": "La Maison des Maternelles", "auteur": "France 5",
     "url": "https://www.france.tv/france-5/la-maison-des-maternelles/",
     "tags": ["replay", "quotidien"],
     "note": "Le magazine quotidien de référence. Chroniques de sages-femmes, pédiatres et psys, en replay sur france.tv."},
    {"groupe": "Émissions et magazines TV", "type": "emission",
     "titre": "Infrarouge", "auteur": "France 2",
     "tags": ["archives", "société"],
     "note": "Case documentaire société : plusieurs numéros sur la maternité, le post-partum, l'infertilité et la place des pères."},
    {"groupe": "Émissions et magazines TV", "type": "emission",
     "titre": "Baby Boom", "auteur": "TF1",
     "tags": ["immersion", "maternité"],
     "note": "Immersion en maternité. Peu d'analyse, mais un panorama concret de ce qui se passe en salle de naissance."},
    {"groupe": "Émissions et magazines TV", "type": "serie",
     "titre": "Parents mode d'emploi", "auteur": "France 2",
     "tags": ["humour", "format court"],
     "note": "Format court et humoristique sur le quotidien parental. À prendre pour ce que c'est : un miroir, pas un guide."},

    # ── Fictions ──────────────────────────────────────────────────────────────
    {"groupe": "Fictions qui disent le vrai", "type": "film",
     "titre": "Un heureux événement", "auteur": "Rémi Bezançon, 2011",
     "tags": ["ambivalence", "adaptation"],
     "note": "D'après le roman d'Éliette Abécassis. L'un des rares films français à montrer l'ambivalence maternelle sans la punir."},
    {"groupe": "Fictions qui disent le vrai", "type": "film",
     "titre": "Sage-femme", "auteur": "Martin Provost, 2017",
     "tags": ["métier", "sages-femmes"],
     "note": "Le métier vu de l'intérieur, avec Catherine Frot et Catherine Deneuve."},
    {"groupe": "Fictions qui disent le vrai", "type": "film",
     "titre": "Pupille", "auteur": "Jeanne Herry, 2018",
     "tags": ["adoption", "né sous X"],
     "note": "La chaîne humaine qui mène un nouveau-né né sous X jusqu'à son adoption. Devenir parent par une autre porte."},
    {"groupe": "Fictions qui disent le vrai", "type": "film", "langue": "en",
     "titre": "Tully", "auteur": "Jason Reitman, 2018",
     "tags": ["épuisement", "post-partum"],
     "note": "Le film le plus juste jamais fait sur l'épuisement post-partum. Se regarde après la naissance plutôt qu'avant."},
    {"groupe": "Fictions qui disent le vrai", "type": "serie", "langue": "en",
     "titre": "Workin' Moms", "auteur": "Netflix",
     "tags": ["retour au travail", "dépression post-natale"],
     "note": "Retour au travail, dépression post-natale, couple : comédie qui n'édulcore pas."},
    {"groupe": "Fictions qui disent le vrai", "type": "serie", "langue": "en",
     "titre": "Catastrophe", "auteur": "Channel 4",
     "tags": ["couple", "grossesse imprévue"],
     "note": "Grossesse imprévue puis vie de jeunes parents. Écriture acérée, aucun angélisme sur le couple."},
    {"groupe": "Fictions qui disent le vrai", "type": "serie", "langue": "en",
     "titre": "The Letdown", "auteur": "Netflix",
     "tags": ["groupe de soutien", "jeunes mères"],
     "note": "Groupe de soutien de jeunes mères, saison après saison. Drôle et étonnamment documenté."},

    # ── Livres · guides pratiques ─────────────────────────────────────────────
    {"groupe": "Livres — guides pratiques", "type": "livre",
     "titre": "J'attends un enfant", "auteur": "Laurence Pernoud",
     "tags": ["classique", "grossesse"],
     "note": "Le classique français, réactualisé chaque année depuis 1956. Complet et rassurant, parfois conservateur : le socle à compléter."},
    {"groupe": "Livres — guides pratiques", "type": "livre", "favori": True,
     "titre": "Le Grand Livre de ma grossesse", "auteur": "CNGOF",
     "tags": ["médical", "référence"],
     "note": "Écrit par le Collège national des gynécologues et obstétriciens français. La référence médicale à jour, sans marketing."},
    {"groupe": "Livres — guides pratiques", "type": "livre",
     "titre": "Bien-être et maternité", "auteur": "Dr Bernadette de Gasquet",
     "tags": ["corps", "périnée", "postures"],
     "note": "Postures, respiration, périnée, positions d'accouchement. Le livre qui change concrètement le vécu du corps."},
    {"groupe": "Livres — guides pratiques", "type": "livre", "favori": True,
     "titre": "Le Mois d'or", "auteur": "Céline Chadelat et Marie Mahé-Poulin",
     "tags": ["post-partum", "40 jours", "à offrir"],
     "note": "Les 40 jours après la naissance, inspirés des traditions du monde : repos, nourriture, entourage. Le livre à offrir aux futurs parents."},
    {"groupe": "Livres — guides pratiques", "type": "livre",
     "titre": "Ceci est notre post-partum", "auteur": "Illana Weizman",
     "tags": ["post-partum", "#MonPostPartum"],
     "note": "À l'origine du hashtag #MonPostPartum. Politise ce qu'on présentait comme une affaire privée et honteuse."},
    {"groupe": "Livres — guides pratiques", "type": "livre", "favori": True,
     "titre": "Mieux vivre avec notre enfant de la grossesse à deux ans", "auteur": "INSPQ, Québec",
     "url": "https://www.inspq.qc.ca/mieux-vivre",
     "tags": ["gratuit", "PDF", "officiel"],
     "note": "Guide public québécois, gratuit en PDF, mis à jour chaque année. Sans doute le meilleur rapport qualité/prix de tout le dossier."},
    {"groupe": "Livres — guides pratiques", "type": "livre",
     "titre": "Au cœur des émotions de l'enfant", "auteur": "Isabelle Filliozat",
     "tags": ["émotions", "parentalité positive"],
     "note": "Comprendre les colères et les pleurs plutôt que les mater. Point d'entrée de la parentalité dite positive."},
    {"groupe": "Livres — guides pratiques", "type": "livre",
     "titre": "Pour une enfance heureuse", "auteur": "Dr Catherine Gueguen",
     "tags": ["neurosciences affectives"],
     "note": "Ce que les neurosciences affectives disent du cerveau du jeune enfant, et ce que ça implique pour les adultes."},
    {"groupe": "Livres — guides pratiques", "type": "livre",
     "titre": "Le Cerveau de votre enfant", "auteur": "Daniel Siegel et Tina Payne Bryson",
     "tags": ["traduit", "stratégies"],
     "note": "Douze stratégies concrètes fondées sur le développement cérébral. Très opérationnel."},

    # ── Livres · essais ───────────────────────────────────────────────────────
    {"groupe": "Livres — essais et sciences sociales", "type": "livre", "favori": True,
     "titre": "La Naissance d'une mère", "auteur": "Daniel Stern et Nadia Bruschweiler-Stern",
     "tags": ["matrescence", "fondateur"],
     "note": "Le texte fondateur : la mère naît en même temps que l'enfant, et cette naissance-là a ses propres étapes."},
    {"groupe": "Livres — essais et sciences sociales", "type": "livre",
     "titre": "L'Amour en plus", "auteur": "Élisabeth Badinter",
     "tags": ["histoire", "instinct maternel"],
     "note": "Histoire de l'amour maternel du XVIIe siècle à nos jours. Démontre que l'« instinct maternel » a une date de naissance."},
    {"groupe": "Livres — essais et sciences sociales", "type": "livre",
     "titre": "Le Conflit : la femme et la mère", "auteur": "Élisabeth Badinter",
     "tags": ["débat", "naturalisme"],
     "note": "Sur la pression du naturalisme contemporain (allaitement, maternage) et son coût pour les femmes. Discuté, donc utile à lire."},
    {"groupe": "Livres — essais et sciences sociales", "type": "livre",
     "titre": "Le Regret d'être mère", "auteur": "Orna Donath",
     "tags": ["sociologie", "tabou"],
     "note": "Enquête sur des femmes qui aiment leurs enfants mais regrettent d'être devenues mères. Le tabou le plus dur, traité avec rigueur."},
    {"groupe": "Livres — essais et sciences sociales", "type": "livre",
     "titre": "L'Art d'accommoder les bébés", "auteur": "G. Delaisi de Parseval et S. Lallemand",
     "tags": ["anthropologie", "puériculture"],
     "note": "Cent ans de conseils de puériculture passés au crible de l'anthropologie. Vaccine durablement contre les modes éducatives."},
    {"groupe": "Livres — essais et sciences sociales", "type": "livre",
     "titre": "Accouchement : les femmes méritent mieux", "auteur": "Marie-Hélène Lahaye",
     "tags": ["violences obstétricales", "consentement"],
     "note": "Sur les violences obstétricales et le consentement en salle de naissance. À lire avant d'écrire un projet de naissance."},
    {"groupe": "Livres — essais et sciences sociales", "type": "livre",
     "titre": "Le Ventre des femmes", "auteur": "Françoise Vergès",
     "tags": ["politique", "histoire coloniale"],
     "note": "Capitalisme, racisme et contrôle de la reproduction, à partir des avortements forcés à La Réunion. Le versant politique du sujet."},

    # ── Livres · pères et co-parents ──────────────────────────────────────────
    {"groupe": "Livres — pères et co-parents", "type": "livre", "favori": True,
     "titre": "Tu seras un homme féministe, mon fils", "auteur": "Aurélia Blanc",
     "tags": ["éducation", "masculinités"],
     "note": "Élever un garçon sans lui transmettre les scripts virils par défaut. Utile autant pour l'enfant que pour le père qui l'élève."},
    {"groupe": "Livres — pères et co-parents", "type": "bd",
     "titre": "Les Contraceptés", "auteur": "G. Daudin, S. Jourdain et C. Rousset",
     "tags": ["contraception masculine", "enquête dessinée"],
     "note": "Enquête dessinée sur la contraception masculine. Élargit la question de la charge reproductive au-delà de la grossesse."},
    {"groupe": "Livres — pères et co-parents", "type": "bd",
     "titre": "Un autre regard / Fallait demander", "auteur": "Emma",
     "tags": ["charge mentale", "couple"],
     "note": "La planche qui a fait entrer « charge mentale » dans le langage courant. Le sujet le plus décisif pour l'équilibre du couple parental."},
    {"groupe": "Livres — pères et co-parents", "type": "livre",
     "titre": "Le Deuxième Sexe, chapitre « La mère »", "auteur": "Simone de Beauvoir",
     "tags": ["fondateur", "philosophie"],
     "note": "Se lit seul. Toujours la charpente intellectuelle de presque tout ce qui s'écrit aujourd'hui sur la maternité."},

    # ── Livres · récits ───────────────────────────────────────────────────────
    {"groupe": "Livres — récits et littérature", "type": "livre",
     "titre": "Le Travail d'une vie : devenir mère", "auteur": "Rachel Cusk",
     "tags": ["récit", "première année"],
     "note": "Récit d'une première année de maternité, d'une honnêteté qui a fait scandale à sa parution. Superbe écriture."},
    {"groupe": "Livres — récits et littérature", "type": "livre",
     "titre": "Maternité", "auteur": "Sheila Heti",
     "tags": ["décider", "désir d'enfant"],
     "note": "Non pas comment être mère, mais faut-il l'être. Le livre pour la phase de décision, avant même la conception."},
    {"groupe": "Livres — récits et littérature", "type": "livre",
     "titre": "Les Argonautes", "auteur": "Maggie Nelson",
     "tags": ["familles plurielles", "queer"],
     "note": "Grossesse, famille queer, transition du conjoint : refonde ce que « faire famille » veut dire."},
    {"groupe": "Livres — récits et littérature", "type": "livre",
     "titre": "L'Événement", "auteur": "Annie Ernaux",
     "tags": ["IVG", "récit"],
     "note": "L'avortement clandestin de 1963. Le revers indissociable de toute réflexion sur le choix de devenir parent."},

    # ── Sources primaires ─────────────────────────────────────────────────────
    {"groupe": "Sources primaires — rapports et institutions", "type": "rapport", "favori": True,
     "titre": "Les 1000 premiers jours — rapport de la commission Cyrulnik (2020)", "auteur": "Commission des 1000 jours",
     "url": "https://onpe.france-enfance-protegee.fr/wp-content/uploads/2024/06/rapport-1000-premiers-jours.pdf",
     "tags": ["1000 jours", "politique publique"],
     "note": "Le document de référence de la politique française de périnatalité : congés, entretien prénatal, dépression post-natale, place du second parent."},
    {"groupe": "Sources primaires — rapports et institutions", "type": "rapport",
     "titre": "Dispositif « 1000 premiers jours »", "auteur": "Ministère de la Santé",
     "url": "https://sante.gouv.fr/prevention-en-sante/sante-des-populations/1000jours/",
     "tags": ["gratuit", "livret", "application"],
     "note": "Fiches officielles, livret des 1000 jours et application mobile gratuite. Le contenu grand public issu du rapport."},
    {"groupe": "Sources primaires — rapports et institutions", "type": "rapport",
     "titre": "Haute Autorité de santé — suivi de grossesse et dépistage post-natal", "auteur": "HAS",
     "url": "https://www.has-sante.fr/",
     "tags": ["recommandations", "EPDS"],
     "note": "Recommandations sur le suivi de grossesse, la sortie de maternité et le dépistage de la dépression post-natale (échelle EPDS)."},
    {"groupe": "Sources primaires — rapports et institutions", "type": "rapport",
     "titre": "Santé publique France — périnatalité", "auteur": "Santé publique France",
     "url": "https://www.santepubliquefrance.fr/",
     "tags": ["épidémiologie", "repères"],
     "note": "Données épidémiologiques, campagnes, repères sur l'alimentation, le sommeil sécuritaire et la santé mentale périnatale."},
    {"groupe": "Sources primaires — rapports et institutions", "type": "article", "favori": True,
     "titre": "ameli.fr et caf.fr — congés et prestations", "auteur": "Assurance Maladie / CAF",
     "url": "https://www.ameli.fr/",
     "tags": ["démarches", "congé paternité", "PAJE"],
     "note": "Congé maternité, congé de paternité et d'accueil de l'enfant, prime à la naissance, PAJE, congé parental. À vérifier tôt : délais de déclaration courts."},
    {"groupe": "Sources primaires — rapports et institutions", "type": "etude",
     "titre": "Cohorte Elfe", "auteur": "Ined / Inserm",
     "url": "https://www.elfe-france.fr/",
     "tags": ["cohorte", "France", "données"],
     "note": "Étude longitudinale suivant plus de 18 000 enfants depuis 2011. Source des chiffres sérieux sur la vie des familles françaises."},
    {"groupe": "Sources primaires — rapports et institutions", "type": "etude", "langue": "en", "favori": True,
     "titre": "Pregnancy leads to long-lasting changes in human brain structure", "auteur": "Hoekzema et al., Nature Neuroscience, 2017",
     "tags": ["matrescence", "neurosciences", "étude clé"],
     "note": "L'étude qui a montré que la grossesse remodèle durablement le cerveau, dans les régions de l'empathie et de l'attachement."},
    {"groupe": "Sources primaires — rapports et institutions", "type": "etude", "langue": "en",
     "titre": "Travaux de Ruth Feldman sur l'ocytocine paternelle", "auteur": "Ruth Feldman",
     "tags": ["cerveau paternel", "ocytocine"],
     "note": "Montrent que le cerveau des pères se réorganise aussi, proportionnellement au temps de soin donné. L'argument scientifique du congé paternité."},
    {"groupe": "Sources primaires — rapports et institutions", "type": "article", "langue": "en",
     "titre": "Dana Raphael, 1973 — l'invention du mot « matrescence »", "auteur": "Dana Raphael",
     "tags": ["histoire du concept"],
     "note": "L'anthropologue qui a forgé le terme, repopularisé depuis 2017 par Aurélia Athan (Columbia) et Alexandra Sacks."},
    {"groupe": "Sources primaires — rapports et institutions", "type": "association", "favori": True,
     "titre": "Maman Blues et réseaux de psychiatrie périnatale", "auteur": "Association Maman Blues",
     "tags": ["soutien", "dépression post-natale"],
     "note": "Difficulté maternelle et dépression post-natale : témoignages, annuaire de professionnels, entraide. À connaître avant d'en avoir besoin."},

    # ── Prompts IA ────────────────────────────────────────────────────────────
    # `contenu` = le texte à copier tel quel dans une IA connectée au web.
    {"groupe": "Prompts IA — recherche assistée", "type": "prompt", "favori": True,
     "titre": "Prompt principal — bibliographie large", "auteur": "Matothèque",
     "tags": ["recherche", "IA avec accès web", "bibliographie"],
     "note": "Rôle documentaliste, périmètre FR 2018-2026, six catégories, format tableau, "
             "et surtout la clause anti-invention : « n'invente aucun titre, auteur, date ou URL ; "
             "si tu doutes, écris à-vérifier et explique pourquoi ». Le point de départ.",
     "contenu": _PROMPT_PRINCIPAL},
    {"groupe": "Prompts IA — recherche assistée", "type": "prompt",
     "titre": "Variante A — creuser la paternité", "auteur": "Matothèque",
     "tags": ["paternité", "lacunes", "relance"],
     "note": "Restreint la recherche aux pères et seconds parents : podcasts actifs après 2023, "
             "cerveau paternel, droit du congé, co-parents non biologiques, dépression post-natale "
             "paternelle. Demande explicitement où les sources manquent — la lacune est une information.",
     "contenu": _PROMPT_PATERNITE},
    {"groupe": "Prompts IA — recherche assistée", "type": "prompt",
     "titre": "Variante B — exigence scientifique", "auteur": "Matothèque",
     "tags": ["sources primaires", "méthodologie", "DOI"],
     "note": "N'accepte que des sources primaires vérifiables (revues à comité de lecture, Cochrane, "
             "HAS, INSPQ, OMS, cohortes) avec DOI, type d'étude, taille d'échantillon et principale "
             "limite méthodologique. À utiliser quand il faut pouvoir citer.",
     "contenu": _PROMPT_SCIENTIFIQUE},
    {"groupe": "Prompts IA — recherche assistée", "type": "prompt",
     "titre": "Variante C — plan de contenu", "auteur": "Matothèque",
     "tags": ["rédaction", "angle", "plan"],
     "note": "Transforme la bibliographie en plan d'article, de vidéo, d'épisode ou d'atelier : un "
             "angle unique, des parties adossées à des sources précises, et les objections qu'un "
             "spécialiste opposerait. À lancer après le prompt principal, dans la même conversation.",
     "contenu": _PROMPT_PLAN},
    {"groupe": "Prompts IA — recherche assistée", "type": "prompt",
     "titre": "Méthode — quatre règles pour interroger une IA", "auteur": "Matothèque",
     "tags": ["méthode", "vérification", "esprit critique"],
     "note": "Enchaîner plutôt que tout demander d'un coup, exiger la vérification des liens, "
             "ancrer dans le temps et l'espace, et demander ce qui manque. À lire avant d'utiliser "
             "les prompts ci-dessus.",
     "contenu": _METHODE},
]


SEEDS: dict[str, dict] = {
    "devenir-parent": {
        "titre": "Devenir parent",
        "description": (
            "Maternité, paternité et 1000 premiers jours : podcasts, chaînes, documentaires, "
            "émissions, films, livres, rapports institutionnels et prompts de recherche. "
            "Trois familles de livres à ne pas confondre — les guides (que faire), les essais "
            "(pourquoi c'est comme ça) et les récits (à quoi ça ressemble de l'intérieur) : en "
            "prendre au moins un de chaque. Si tu n'en lis que trois : Le Grand Livre de ma "
            "grossesse pour le médical, Le Mois d'or pour l'après, La Naissance d'une mère pour "
            "ce qui se passe dans la tête. La section « Prompts IA » contient le texte intégral "
            "des requêtes à copier dans une IA connectée au web pour prolonger cette veille. "
            "Relevé de septembre 2026 — les disponibilités en replay et en librairie évoluent, "
            "à vérifier avant usage. Rien ici ne remplace un avis médical : sage-femme, médecin "
            "ou PMI restent les interlocuteurs de première ligne."
        ),
        "ressources": _DEVENIR_PARENT,
    },
}


def _cle_ressource(titre: str, url: str | None) -> str:
    """Clé d'unicité d'une ressource : l'URL si elle existe, sinon le titre normalisé."""
    return (url or "").strip().lower() or titre.strip().lower()


async def installer_seed(db: AsyncSession, cle: str) -> dict:
    """
    Installe (ou complète) le dossier pré-rempli `cle`.

    Idempotent : si le dossier existe déjà (même slug), seules les ressources absentes
    sont ajoutées — les modifications faites à la main sont donc préservées.

    Retourne un récapitulatif `{dossier_id, slug, cree, ajoutees, ignorees}`.
    """
    seed = SEEDS.get(cle)
    if seed is None:
        raise KeyError(cle)

    dossier = (
        await db.execute(select(DossierThematique).where(DossierThematique.slug == cle))
    ).scalar_one_or_none()

    cree = dossier is None
    if dossier is None:
        dossier = DossierThematique(
            id=uuid.uuid4(), titre=seed["titre"], slug=cle,
            description=seed["description"], origine=f"seed:{cle}",
        )
        db.add(dossier)
        await db.flush()   # besoin de l'id pour rattacher les ressources

    # Ressources déjà présentes → on ne réinsère pas (URL prioritaire, sinon titre).
    existantes = {
        _cle_ressource(r.titre, r.url)
        for r in (await db.execute(
            select(Ressource).where(Ressource.dossier_id == dossier.id)
        )).scalars().all()
    }

    ajoutees = 0
    for position, item in enumerate(seed["ressources"]):
        if _cle_ressource(item["titre"], item.get("url")) in existantes:
            continue
        db.add(Ressource(
            dossier_id=dossier.id,
            titre=item["titre"],
            auteur=item.get("auteur"),
            type=item.get("type", "article"),
            url=item.get("url"),
            langue=item.get("langue", "fr"),
            groupe=item.get("groupe"),
            note=item.get("note"),
            contenu=item.get("contenu"),
            tags=item.get("tags", []),
            position=position,
            favori=item.get("favori", False),
        ))
        ajoutees += 1

    await db.commit()
    log.info("Seed de dossier installé", cle=cle, cree=cree, ajoutees=ajoutees)
    return {
        "dossier_id": str(dossier.id),
        "slug": cle,
        "cree": cree,
        "ajoutees": ajoutees,
        "ignorees": len(seed["ressources"]) - ajoutees,
    }
