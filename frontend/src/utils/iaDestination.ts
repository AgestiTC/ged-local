/**
 * Bouton « IA LOCAL / IA GECO » — décisions pures (plan-liste-modeles, étape 5b)
 * ==============================================================================
 * « MATO » = IA locale (Ollama), « GECO » = IA externe, par INTERNET. Un réglage global
 * (`ia_destination`) dit où partent les demandes INTERACTIVES (chat, rapports, comparatifs…) en
 * « Auto » ; les traitements de fond restent locaux. Le serveur est la seule barrière : ce module
 * ne décide que de ce qu'on AFFICHE et de ce qu'on propose. Aucun état, aucun effet de bord.
 */

export type IaDestination = 'local' | 'geco'
/** État AFFICHABLE : « inconnu » tant que la destination n'est pas lue et confirmée (jamais « local » par défaut). */
export type EtatIa = IaDestination | 'inconnu'

/** Un modèle GECO est nommé « geco/… » (contrat du serveur). */
export const estModeleGeco = (nom: string): boolean => nom.startsWith('geco/')

/**
 * Valeur lue au serveur. Contrat strict : exactement « local » ou « geco ». Tout le reste (absent, autre
 * casse, type inattendu) est un ÉCHEC de lecture (null), JAMAIS « local » : on n'affirme pas ce qu'on n'a pas lu.
 */
export function destinationValide(v: unknown): IaDestination | null {
  return v === 'geco' || v === 'local' ? v : null
}

/** `detail` (français) d'une erreur HTTP du serveur, tel quel ; null pour une panne réseau ou autre. */
export function detailServeur(e: unknown): string | null {
  if (e && typeof e === 'object') {
    const detail = (e as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
  }
  return null
}

// ─── Modèles ─────────────────────────────────────────────────────────────────

/** Retire les modèles d'embeddings (`embedding === true`) : ni pour le chat, ni comme modèle GECO. */
export function sansEmbeddings<T extends { embedding?: boolean }>(liste?: T[]): T[] {
  return (liste ?? []).filter(m => m.embedding !== true)
}

/** Modèles GECO proposables comme « modèle GECO utilisé ». */
export const modelesGecoChoisissables = sansEmbeddings

/** Ce que « Auto » désigne réellement : le modèle GECO en mode GECO, sinon le défaut local. */
export function modeleAuto(e: { destination: EtatIa; gecoModele: string; defautLocal: string }):
  { nom: string; internet: boolean } {
  if (e.destination === 'geco') return { nom: e.gecoModele, internet: true }
  if (e.destination === 'inconnu') return { nom: '', internet: false }   // rien d'affirmé tant que non lu
  return { nom: e.defautLocal, internet: false }
}

export interface OptionsLibelleAuto {
  sep?: string                    // séparateur entre « Auto » et le modèle (défaut « — »)
  court?: (nom: string) => string // nom raccourci pour les colonnes étroites
  repli?: string                  // texte quand aucun modèle n'est connu (non-admin en mode local)
  internetEnTete?: boolean        // « Auto · internet · geco/… » : le mot « internet » n'est jamais tronqué
}

export function libelleAuto(auto: { nom: string; internet: boolean }, o: OptionsLibelleAuto = {}): string {
  const sep = o.sep ?? ' — '
  if (auto.internet) {
    const nom = auto.nom ? (o.court ? o.court(auto.nom) : auto.nom) : 'GECO'
    return o.internetEnTete ? `Auto${sep}internet${sep}${nom}` : `Auto${sep}${nom} (internet)`
  }
  if (!auto.nom) return o.repli ?? 'Auto'
  return `Auto${sep}${o.court ? o.court(auto.nom) : auto.nom}`
}

// ─── Bandeau, badges ─────────────────────────────────────────────────────────

export function texteBandeau(gecoModele: string): string {
  const modele = gecoModele ? ` (modèle ${gecoModele})` : ''
  return `IA GECO activée — les demandes interactives partent par internet chez GECO${modele}. `
    + "L'indexation reste locale."
}

/** Badge de confiance du chat : « 100% local » SEULEMENT quand rien ne part chez GECO. */
export function badgeConfiance(destination: EtatIa): { local: boolean; libelle: string } {
  if (destination === 'inconnu') return { local: false, libelle: 'IA : vérification en cours…' }
  return destination === 'geco'
    ? { local: false, libelle: 'IA GECO — internet' }
    : { local: true, libelle: '100% local' }
}

/** Sous le nom de l'appli dans la barre latérale. */
export function mentionSidebar(version: string, destination: EtatIa): string {
  return `${version ? `v${version} — ` : ''}${badgeConfiance(destination).libelle}`
}

// ─── Bascule ─────────────────────────────────────────────────────────────────

export type RaisonRefus = 'non_admin' | 'deja_geco' | 'modele_manquant' | 'liste_indisponible' | 'inconnu'
export type DecisionBascule = { ok: true } | { ok: false; raison: RaisonRefus; message: string }

/**
 * Peut-on OUVRIR la confirmation pour passer sur IA GECO ? `listeDisponible` : vrai/faux quand
 * l'écran connaît l'état de la liste GECO, `undefined` quand il l'ignore (l'en-tête ne lit pas
 * /api/system/models) : le serveur refuse alors en 422, avec son message.
 */
export function peutBasculerVersGeco(e: {
  admin: boolean; destination: EtatIa; gecoModele: string; listeDisponible?: boolean
}): DecisionBascule {
  if (!e.admin) return { ok: false, raison: 'non_admin', message: "Réservé à l'administrateur." }
  if (e.destination === 'inconnu') {
    return { ok: false, raison: 'inconnu', message: "Impossible de vérifier l'état actuel de l'IA (locale ou GECO). Réessayez dans un instant." }
  }
  if (e.destination === 'geco') return { ok: false, raison: 'deja_geco', message: "L'IA GECO est déjà activée." }
  if (!e.gecoModele) {
    return {
      ok: false, raison: 'modele_manquant',
      message: "Aucun modèle GECO n'est choisi. Choisissez-le dans Paramètres › Services & modèles IA "
        + '(« Modèle GECO utilisé »), puis réessayez.',
    }
  }
  if (e.listeDisponible === false) {
    return {
      ok: false, raison: 'liste_indisponible',
      message: "La liste des modèles GECO n'est pas disponible (adresse de l'AIGUILLEUR à renseigner, ou injoignable). "
        + 'Voyez Paramètres › Services & modèles IA.',
    }
  }
  return { ok: true }
}

/** Contenu de la confirmation (même fenêtre que les autres sorties internet du projet). */
export function confirmationBascule(gecoModele: string): {
  titre: string; envoye: string; jamaisEnvoye: string; modele: string; bandeau: string
} {
  return {
    titre: "Passer sur l'IA GECO (internet)",
    envoye: 'Partiront par internet chez GECO : vos questions, ainsi que les extraits et documents joints aux demandes '
      + 'interactives (discussion, rapports, comparatifs…).',
    jamaisEnvoye: "Ne partent jamais : l'indexation, l'enrichissement, la recherche sémantique et la lecture d'images "
      + 'restent sur votre serveur.',
    modele: `Modèle utilisé : ${gecoModele}.`,
    bandeau: "Un bandeau restera affiché sur toutes les pages tant que l'IA GECO est activée.",
  }
}

/**
 * Faut-il proposer « passer sur IA GECO ? » sous un message du chat ? Seulement quand l'échec vient de l'IA
 * locale (champ structuré posé par le store), que le bouton est sur LOCAL (lu et confirmé), qu'un modèle GECO
 * est configuré et que l'utilisateur est admin. Jamais de bascule automatique : la proposition ouvre la
 * même confirmation.
 */
export function proposerRepli(e: {
  destination: EtatIa; gecoModele: string; admin: boolean; enCours: boolean; erreurIaLocale: boolean
}): boolean {
  if (e.enCours || !e.admin || e.destination !== 'local' || !e.gecoModele) return false
  return e.erreurIaLocale
}

// ─── Garde avant envoi ───────────────────────────────────────────────────────

export const MSG_ENVOI_GECO_ACTIVE =
  "L'IA GECO vient d'être activée : cette demande partirait par internet chez GECO. Renvoyez-la pour confirmer."
export const MSG_ENVOI_INCONNU =
  'Impossible de vérifier où part la demande (IA locale ou IA GECO). Réessayez.'

export type VerdictVerification = 'ok' | 'change' | 'inconnu'

/**
 * Que faire d'une relecture faite juste avant l'envoi ? `destinationApres` = état du store APRÈS la relecture.
 * ok → envoyer · change vers GECO → NE PAS envoyer (rien ne doit partir sur internet sans que l'utilisateur
 * l'ait vu) · change vers local → envoyer (sens sûr) · inconnu → NE PAS envoyer.
 */
export function decisionEnvoi(verdict: VerdictVerification, destinationApres: EtatIa):
  { autorise: true } | { autorise: false; message: string } {
  if (verdict === 'ok') return { autorise: true }
  if (verdict === 'inconnu') return { autorise: false, message: MSG_ENVOI_INCONNU }
  return destinationApres === 'geco'
    ? { autorise: false, message: MSG_ENVOI_GECO_ACTIVE }
    : { autorise: true }
}

// ─── Sélecteurs ──────────────────────────────────────────────────────────────

/**
 * Le modèle mémorisé (chat) existe-t-il encore parmi les options ? Faux → à remettre sur « Auto ».
 * Toujours vrai tant que la destination est inconnue ou que les listes ne sont pas chargées : on ne
 * détruit pas un choix sur un état non vérifié.
 */
export function modeleChatValide(e: {
  model: string; destination: EtatIa; restreint: boolean; charge: boolean
  modeles: { name: string }[]; externes: { name: string; selectionnable?: boolean; embedding?: boolean }[]
}): boolean {
  if (!e.model || e.destination === 'inconnu') return true
  if (!e.restreint && !e.charge) return true
  if (e.modeles.some(m => m.name === e.model)) return true
  return e.destination === 'geco'
    && e.externes.some(m => m.name === e.model && m.selectionnable !== false && m.embedding !== true)
}
