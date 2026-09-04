/**
 * Page « Aide — Prompts des dossiers ».
 * Bibliothèque d'exemples de prompts à COPIER puis coller dans une IA connectée au web
 * (Claude, ChatGPT, Perplexity, Gemini) pour constituer/enrichir un dossier de veille.
 * La copie passe par `copierTexte` — `navigator.clipboard` est absent en HTTP simple.
 */
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Check, Copy, HelpCircle } from 'lucide-react'
import { copierTexte } from '../utils/clipboard'

interface Exemple { emoji: string; titre: string; quand: string; prompt: string }

const P_SUJET = `Tu es documentaliste. Tu as accès au web : utilise-le et vérifie chaque référence.

OBJECTIF
Constituer une bibliographie de sources fiables sur [SUJET], destinée à [PRÉCISER : usage / public].

PÉRIMÈTRE
- Langue : français en priorité ; anglais si la ressource est majeure (signale-le).
- Période : privilégie les 5 dernières années, sauf classiques indépassables (signale-les).
- Aire : France et francophonie, + références internationales de référence.

CATÉGORIES ATTENDUES (8 à 12 entrées chacune)
1. Podcasts  2. Chaînes/vidéos YouTube  3. Documentaires, émissions, films (+ plateforme)
4. Livres (guides / essais / récits)  5. Articles, rapports institutionnels et études (sources primaires)
6. Associations et dispositifs en France

POUR CHAQUE ENTRÉE : Titre exact | Auteur/producteur | Année | Plateforme/éditeur ; un lien vérifié
(dis-le si non vérifié) ; 1-2 phrases sur l'apport spécifique ; public visé et niveau ; 3 mots-clés.

FIABILITÉ : n'invente aucun titre, auteur, date ou URL — si tu doutes, écris « à vérifier » et explique.
Distingue le vérifié en ligne du restitué de mémoire. Signale les sources controversées.

FORMAT : un tableau markdown par catégorie, puis « Par où commencer » (5 ressources dans un ordre argumenté).`

const P_AGE = `Même rôle et mêmes contraintes de fiabilité, mais pour des PARENTS d'un enfant de [TRANCHE D'ÂGE].

Concentre-toi sur les besoins et le développement propres à cet âge :
[LISTE LES THÈMES : sommeil, alimentation, langage, motricité, émotions, écrans, santé, sexualité… selon l'âge]

Mêmes 6 catégories, même format par entrée, même « Par où commencer ». Ajoute une catégorie
« Professionnels de santé à suivre » (pédiatres, sages-femmes, psychologues). Rien ne remplace un
avis médical : renvoie vers pédiatre, médecin ou PMI en cas de doute.`

const P_RECENTRER = `Reprends la même conversation. Recentre TOUT sur [SOUS-THÈME / VERSANT PEU DOCUMENTÉ],
et dis-moi explicitement où les sources manquent ou sont de faible qualité — cette lacune est en soi
une information. Ne répète pas les entrées déjà données ; ajoute 15 nouvelles entrées sur ce seul angle.`

const P_PRIMAIRES = `Reprends, mais je ne veux QUE des sources primaires vérifiables : études évaluées par les
pairs, méta-analyses (Cochrane), rapports d'agences publiques (HAS, Santé publique France, INSPQ, OMS),
données de cohortes. Pour chaque source : auteurs, revue, année, DOI ou lien officiel, type d'étude,
taille d'échantillon, principal résultat en une phrase, et la principale limite méthodologique.
Si une croyance répandue n'est pas soutenue par les données, dis-le et cite l'étude qui la contredit.`

const P_PLAN = `À partir de la bibliographie obtenue, transforme-la en [PLAN D'ARTICLE / SCRIPT DE VIDÉO / DÉROULÉ
D'ATELIER] pour [PUBLIC]. Structure en sections, et pour chaque section cite les 2-3 ressources de la
biblio qui la soutiennent. Signale les points où il manque une source solide.`

const P_LIENS = `Voici une liste de ressources (titres + liens). Pour chacune, vérifie sur le web si elle est
TOUJOURS disponible aujourd'hui (podcast actif, replay non expiré, page en ligne, édition en vente).
Rends un tableau : Titre | Statut (disponible / déplacé / indisponible) | Nouveau lien si déplacé |
Remarque. N'invente pas de lien : si tu ne trouves pas, écris « introuvable, à vérifier ».
[COLLE ICI LA LISTE]`

const P_LACUNES = `À partir de tout ce qui précède, fais un état des MANQUES : quels angles, publics, points de vue
ou types de sources sont absents ou faibles dans cette bibliographie ? Classe-les par priorité et propose,
pour chaque manque, une piste de recherche concrète (requête, base, expert à suivre).`

const EXEMPLES: Exemple[] = [
  { emoji: '📚', titre: 'Bibliographie sur un sujet', quand: 'Démarrer un dossier sur un thème.', prompt: P_SUJET },
  { emoji: '👶', titre: 'Bibliographie par tranche d’âge', quand: 'Un sous-dossier « 0-1 an », « 2-5 ans »…', prompt: P_AGE },
  { emoji: '🎯', titre: 'Recentrer sur un sous-thème', quand: 'Approfondir un angle ou le versant peu couvert.', prompt: P_RECENTRER },
  { emoji: '🔬', titre: 'Sources primaires uniquement', quand: 'Ne garder que de l’évalué par les pairs (DOI, échantillon, limite).', prompt: P_PRIMAIRES },
  { emoji: '🗂️', titre: 'Transformer en plan', quand: 'Passer de la biblio à un article / une vidéo / un atelier.', prompt: P_PLAN },
  { emoji: '🔗', titre: 'Vérifier / mettre à jour des liens', quand: 'Contrôler des ressources qui datent (replay expiré…).', prompt: P_LIENS },
  { emoji: '🕳️', titre: 'Trouver ce qui manque', quand: 'Repérer les lacunes d’un dossier existant.', prompt: P_LACUNES },
]

function PromptCarte({ ex }: { ex: Exemple }) {
  const [copie, setCopie] = useState(false)
  const copier = async () => {
    if (await copierTexte(ex.prompt)) { setCopie(true); setTimeout(() => setCopie(false), 1800) }
  }
  return (
    <section className="bg-white border border-gray-200 rounded-lg p-3.5">
      <div className="flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <h2 className="text-sm font-semibold text-gray-800">{ex.emoji} {ex.titre}</h2>
          <p className="text-xs text-gray-500 mt-0.5">{ex.quand}</p>
        </div>
        <button type="button" onClick={copier}
          className="shrink-0 flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-md bg-blue-600 text-white hover:bg-blue-700">
          {copie ? <Check size={13} /> : <Copy size={13} />} {copie ? 'Copié' : 'Copier'}
        </button>
      </div>
      <pre className="mt-2 text-[11px] leading-relaxed text-gray-600 bg-gray-50 border border-gray-100 rounded-md p-2.5 whitespace-pre-wrap font-mono max-h-52 overflow-auto">
        {ex.prompt}
      </pre>
    </section>
  )
}

export default function AideDossiersPage() {
  return (
    <div className="h-full overflow-y-auto bg-gray-50">
      <div className="max-w-4xl mx-auto p-4 md:p-6 space-y-4">
        <header className="space-y-1">
          <Link to="/dossiers" className="inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700">
            <ArrowLeft size={13} /> Dossiers thématiques
          </Link>
          <h1 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <HelpCircle size={20} className="text-blue-600" /> Aide — Prompts
          </h1>
          <p className="text-sm text-gray-500 max-w-3xl leading-relaxed">
            Copie un prompt, remplace le texte entre <strong>[CROCHETS]</strong>, puis colle-le dans une IA
            connectée au web (Claude, ChatGPT, Perplexity, Gemini). Reporte ensuite les sources trouvées
            comme ressources de ton dossier. <strong>Règle d'or</strong> : ne demande pas les 6 catégories
            d'un seul jet — lance le prompt, puis relance <em>catégorie par catégorie</em> (« approfondis
            uniquement la catégorie 3, 15 entrées de plus »). Au-delà d'une soixantaine d'entrées d'un coup,
            la qualité chute et des URL inventées apparaissent — recoupe à la main les sources que tu retiens.
          </p>
        </header>

        <div className="space-y-3">
          {EXEMPLES.map(ex => <PromptCarte key={ex.titre} ex={ex} />)}
        </div>
      </div>
    </div>
  )
}
