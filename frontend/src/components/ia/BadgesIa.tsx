/**
 * Mentions de confiance qui suivent la destination de l'IA : « 100% local » ne s'affiche que quand
 * rien ne part chez GECO. Les autres « 100 % local » de l'appli (transcription, notifications,
 * vidéo…) concernent d'autres fonctions et ne changent pas.
 */
import { Globe, ShieldCheck } from 'lucide-react'
import { badgeConfiance, mentionSidebar, type EtatIa } from '../../utils/iaDestination'

/** Badge de l'en-tête du chat. */
export function BadgeIaChat({ destination }: { destination: EtatIa }) {
  if (destination === 'inconnu') {
    return (
      <span title="La destination de l'IA (locale ou GECO) n'est pas encore vérifiée."
        className="flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-600 border border-gray-300 whitespace-nowrap cursor-help">
        <Globe size={11} /> {badgeConfiance('inconnu').libelle}
      </span>
    )
  }
  if (destination === 'geco') {
    return (
      <span title="Les demandes de ce chat partent par internet chez GECO (IA externe). L'indexation de vos documents reste locale."
        className="flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-300 whitespace-nowrap cursor-help">
        <Globe size={11} /> {badgeConfiance('geco').libelle}
      </span>
    )
  }
  return (
    // Badge de confiance : l'IA est locale — capital car Matothèque traite des documents personnels.
    <span title="L'IA tourne sur TON serveur (Ollama), en local. Tes documents personnels et tes messages ne quittent jamais Matothèque — aucune donnée n'est envoyée à un service externe."
      className="flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 whitespace-nowrap cursor-help">
      <ShieldCheck size={11} /> {badgeConfiance('local').libelle}
    </span>
  )
}

/** Phrase de l'écran vide du chat. */
export function PhraseVideChat({ destination }: { destination: EtatIa }) {
  if (destination === 'inconnu') {
    return (
      <p className="flex items-center gap-1.5 text-xs text-gray-600 bg-gray-100 border border-gray-200 rounded-full px-3 py-1">
        <Globe size={13} /> {badgeConfiance('inconnu').libelle}
      </p>
    )
  }
  if (destination === 'geco') {
    return (
      <p className="flex items-center gap-1.5 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-full px-3 py-1">
        <Globe size={13} /> {badgeConfiance('geco').libelle} — tes questions et les documents joints partent chez GECO.
      </p>
    )
  }
  return (
    <p className="flex items-center gap-1.5 text-xs text-emerald-600 bg-emerald-50 border border-emerald-100 rounded-full px-3 py-1">
      <ShieldCheck size={13} /> 100% local — tes documents personnels ne quittent jamais Matothèque.
    </p>
  )
}

/** Sous le nom de l'appli, dans la barre latérale (fond sombre). */
export function MentionSidebar({ version, destination }: { version: string; destination: EtatIa }) {
  return (
    <span className={destination === 'geco' ? 'text-amber-300 font-medium' : undefined}>
      {mentionSidebar(version, destination)}
    </span>
  )
}
