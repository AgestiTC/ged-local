/**
 * Tests — décisions pures du bouton « IA LOCAL / IA GECO » (plan-liste-modeles, étape 5b).
 */
import { describe, it, expect } from 'vitest'
import {
  badgeConfiance, confirmationBascule, decisionEnvoi, destinationValide, detailServeur, libelleAuto, mentionSidebar,
  modeleAuto, modeleChatValide, modelesGecoChoisissables, MSG_ENVOI_GECO_ACTIVE, MSG_ENVOI_INCONNU,
  peutBasculerVersGeco, proposerRepli, sansEmbeddings, texteBandeau,
} from '../../utils/iaDestination'

describe('destinationValide (contrat strict)', () => {
  it('seuls « local » et « geco » exacts sont valides', () => {
    expect(destinationValide('geco')).toBe('geco')
    expect(destinationValide('local')).toBe('local')
  })
  it('toute valeur hors contrat est un ÉCHEC de lecture (null), jamais « local »', () => {
    for (const v of [undefined, null, 'GECO ', 'Local', '', 42, {}, 'n_importe_quoi']) expect(destinationValide(v)).toBeNull()
  })
})

describe('filtre des embeddings GECO', () => {
  const liste = [
    { name: 'geco/chat-a', embedding: false },
    { name: 'geco/text-embedding-nomic', embedding: true },
    { name: 'geco/sans-champ' },
  ]
  it("retire les modèles d'embeddings, garde les autres (champ absent = gardé)", () => {
    expect(sansEmbeddings(liste).map(m => m.name)).toEqual(['geco/chat-a', 'geco/sans-champ'])
  })
  it('liste absente ou vide : tableau vide', () => {
    expect(sansEmbeddings(undefined)).toEqual([])
    expect(modelesGecoChoisissables([])).toEqual([])
  })
  it("ne mute pas l'entrée", () => {
    sansEmbeddings(liste)
    expect(liste).toHaveLength(3)
  })
})

describe('libellé « Auto »', () => {
  it('mode local : le modèle local, sans mention internet', () => {
    const a = modeleAuto({ destination: 'local', gecoModele: 'geco/x', defautLocal: 'ministral-3:14b' })
    expect(a).toEqual({ nom: 'ministral-3:14b', internet: false })
    expect(libelleAuto(a)).toBe('Auto — ministral-3:14b')
  })
  it('mode local sans défaut connu (non-admin) : « Auto » seul, ou le repli fourni', () => {
    const a = modeleAuto({ destination: 'local', gecoModele: '', defautLocal: '' })
    expect(libelleAuto(a)).toBe('Auto')
    expect(libelleAuto(a, { repli: 'Auto (choix automatique)' })).toBe('Auto (choix automatique)')
  })
  it('mode GECO : le modèle GECO + mention internet, jamais le modèle local', () => {
    const a = modeleAuto({ destination: 'geco', gecoModele: 'geco/gros', defautLocal: 'llama3.1' })
    expect(a).toEqual({ nom: 'geco/gros', internet: true })
    const t = libelleAuto(a)
    expect(t).toBe('Auto — geco/gros (internet)')
    expect(t).not.toContain('llama3.1')
  })
  it('mode GECO sans modèle (incohérent) : dit quand même internet', () => {
    expect(libelleAuto(modeleAuto({ destination: 'geco', gecoModele: '', defautLocal: 'x' }))).toBe('Auto — GECO (internet)')
  })
  it('état inconnu : aucun modèle affirmé, ni « internet », ni modèle local', () => {
    const a = modeleAuto({ destination: 'inconnu', gecoModele: 'geco/x', defautLocal: 'llama3.1' })
    expect(a).toEqual({ nom: '', internet: false })
    expect(libelleAuto(a)).toBe('Auto')
  })
  it('« internet » en tête pour les sélecteurs étroits', () => {
    const a = modeleAuto({ destination: 'geco', gecoModele: 'geco/gros', defautLocal: '' })
    expect(libelleAuto(a, { sep: ' · ', internetEnTete: true })).toBe('Auto · internet · geco/gros')
  })
  it('nom court et séparateur personnalisés', () => {
    const a = modeleAuto({ destination: 'local', gecoModele: '', defautLocal: 'hf.co/org/Zebre:latest' })
    expect(libelleAuto(a, { sep: ' : ', court: n => n.split('/').pop() ?? n })).toBe('Auto : Zebre:latest')
  })
})

describe('texte du bandeau', () => {
  it("dit internet, le modèle, et que l'indexation reste locale", () => {
    const t = texteBandeau('geco/gros')
    expect(t).toContain('IA GECO activée')
    expect(t).toContain('internet')
    expect(t).toContain('geco/gros')
    expect(t).toContain("L'indexation reste locale")
  })
  it('sans modèle connu : pas de parenthèse vide', () => {
    expect(texteBandeau('')).not.toContain('()')
  })
})

describe('peutBasculerVersGeco', () => {
  const base = { admin: true, destination: 'local' as const, gecoModele: 'geco/x' }
  it('admin, modèle choisi : oui', () => expect(peutBasculerVersGeco(base)).toEqual({ ok: true }))
  it('état inconnu : refus (le store relit avant de décider)', () => {
    expect(peutBasculerVersGeco({ ...base, destination: 'inconnu' })).toMatchObject({ ok: false, raison: 'inconnu' })
  })
  it('non-admin : non', () => {
    expect(peutBasculerVersGeco({ ...base, admin: false })).toMatchObject({ ok: false, raison: 'non_admin' })
  })
  it('déjà sur GECO : non', () => {
    expect(peutBasculerVersGeco({ ...base, destination: 'geco' })).toMatchObject({ ok: false, raison: 'deja_geco' })
  })
  it('aucun modèle GECO choisi : non, avec renvoi vers les Paramètres', () => {
    const r = peutBasculerVersGeco({ ...base, gecoModele: '' })
    expect(r).toMatchObject({ ok: false, raison: 'modele_manquant' })
    if (!r.ok) expect(r.message).toContain('Paramètres')
  })
  it('liste GECO indisponible : non, avec renvoi vers les Paramètres', () => {
    const r = peutBasculerVersGeco({ ...base, listeDisponible: false })
    expect(r).toMatchObject({ ok: false, raison: 'liste_indisponible' })
    if (!r.ok) expect(r.message).toContain('Paramètres')
  })
  it("état de la liste inconnu (undefined) : le serveur tranchera", () => {
    expect(peutBasculerVersGeco({ ...base, listeDisponible: undefined }).ok).toBe(true)
  })
})

describe('confirmationBascule', () => {
  const c = confirmationBascule('geco/gros')
  const tout = [c.titre, c.envoye, c.jamaisEnvoye, c.modele, c.bandeau].join(' | ')
  it('dit ce qui part', () => {
    expect(c.envoye).toMatch(/questions/)
    expect(c.envoye).toMatch(/documents/)
    expect(c.envoye).toMatch(/discussion/)
    expect(c.envoye).toMatch(/rapports/)
    expect(c.envoye).toMatch(/comparatifs/)
  })
  it('dit ce qui ne part jamais', () => {
    for (const mot of ['indexation', 'enrichissement', 'recherche sémantique', 'images']) expect(c.jamaisEnvoye).toContain(mot)
  })
  it('nomme le modèle et le bandeau', () => {
    expect(c.modele).toContain('geco/gros')
    expect(c.bandeau).toMatch(/bandeau/)
  })
  it('ne prétend jamais que tout reste local', () => {
    expect(tout).not.toMatch(/100\s?%\s?local/i)
  })
})

describe('proposerRepli (point G)', () => {
  const ok = {
    destination: 'local' as const, gecoModele: 'geco/x', admin: true, enCours: false, erreurIaLocale: true,
  }
  it('toutes les conditions réunies : oui', () => expect(proposerRepli(ok)).toBe(true))
  it("l'échec ne vient pas de l'IA locale (refus serveur, erreur GECO, réponse normale) : non", () => {
    expect(proposerRepli({ ...ok, erreurIaLocale: false })).toBe(false)
  })
  it('destination GECO ou inconnue : non', () => {
    expect(proposerRepli({ ...ok, destination: 'geco' })).toBe(false)
    expect(proposerRepli({ ...ok, destination: 'inconnu' })).toBe(false)
  })
  it('aucun modèle GECO configuré : non', () => expect(proposerRepli({ ...ok, gecoModele: '' })).toBe(false))
  it('non-admin : non', () => expect(proposerRepli({ ...ok, admin: false })).toBe(false))
  it('flux en cours : non', () => expect(proposerRepli({ ...ok, enCours: true })).toBe(false))
})

describe('badge de confiance', () => {
  it('local : « 100% local »', () => {
    expect(badgeConfiance('local')).toEqual({ local: true, libelle: '100% local' })
  })
  it('GECO : mention exacte, jamais « 100 % local »', () => {
    const b = badgeConfiance('geco')
    expect(b.local).toBe(false)
    expect(b.libelle).toBe('IA GECO — internet')
  })
  it('état inconnu : vérification en cours, jamais « 100% local »', () => {
    const b = badgeConfiance('inconnu')
    expect(b).toEqual({ local: false, libelle: 'IA : vérification en cours…' })
    expect(mentionSidebar('1.0', 'inconnu')).toBe('v1.0 — IA : vérification en cours…')
    expect(mentionSidebar('1.0', 'inconnu')).not.toMatch(/100\s?%\s?local/)
  })
  it('sidebar', () => {
    expect(mentionSidebar('1.2.3', 'local')).toBe('v1.2.3 — 100% local')
    expect(mentionSidebar('', 'local')).toBe('100% local')
    expect(mentionSidebar('1.2.3', 'geco')).toBe('v1.2.3 — IA GECO — internet')
    expect(mentionSidebar('1.2.3', 'geco')).not.toMatch(/100\s?%\s?local/)
  })
})

describe('detailServeur', () => {
  it('rend le detail du serveur tel quel', () => {
    expect(detailServeur({ response: { data: { detail: 'Le modèle GECO est refusé.' } } })).toBe('Le modèle GECO est refusé.')
  })
  it('null pour une panne réseau, une erreur sans detail ou autre chose', () => {
    expect(detailServeur(new Error('Network Error'))).toBeNull()
    expect(detailServeur({ response: { data: {} } })).toBeNull()
    expect(detailServeur({ response: { data: { detail: [{ msg: 'x' }] } } })).toBeNull()
    expect(detailServeur(null)).toBeNull()
  })
})

describe('decisionEnvoi (garde partagée avant chaque envoi interactif)', () => {
  it('ok : on envoie', () => expect(decisionEnvoi('ok', 'local')).toEqual({ autorise: true }))
  it("changé vers GECO : on n'envoie PAS, message clair", () => {
    const d = decisionEnvoi('change', 'geco')
    expect(d).toEqual({ autorise: false, message: MSG_ENVOI_GECO_ACTIVE })
    expect(MSG_ENVOI_GECO_ACTIVE).toContain("L'IA GECO vient d'être activée")
    expect(MSG_ENVOI_GECO_ACTIVE).toContain('Renvoyez-la pour confirmer')
  })
  it('changé vers local : on envoie (sens sûr)', () => expect(decisionEnvoi('change', 'local')).toEqual({ autorise: true }))
  it("inconnu : on n'envoie PAS", () => {
    expect(decisionEnvoi('inconnu', 'local')).toEqual({ autorise: false, message: MSG_ENVOI_INCONNU })
    expect(MSG_ENVOI_INCONNU).toContain('Impossible de vérifier')
  })
})

describe('modeleChatValide (remise à « Auto »)', () => {
  const base = {
    destination: 'geco' as const, restreint: false, charge: true,
    modeles: [{ name: 'llama3.1' }],
    externes: [{ name: 'geco/a', selectionnable: true }, { name: 'geco/e', selectionnable: true, embedding: true }],
  }
  it('« Auto » est toujours valide', () => expect(modeleChatValide({ ...base, model: '' })).toBe(true))
  it('modèle installé : valide', () => expect(modeleChatValide({ ...base, model: 'llama3.1' })).toBe(true))
  it('modèle GECO listé, mode GECO : valide', () => expect(modeleChatValide({ ...base, model: 'geco/a' })).toBe(true))
  it('modèle GECO disparu de la liste : invalide', () => expect(modeleChatValide({ ...base, model: 'geco/parti' })).toBe(false))
  it("modèle GECO d'embeddings : invalide", () => expect(modeleChatValide({ ...base, model: 'geco/e' })).toBe(false))
  it('destination repassée à local : un modèle GECO devient invalide', () => {
    expect(modeleChatValide({ ...base, destination: 'local', model: 'geco/a' })).toBe(false)
  })
  it("JAMAIS pendant l'état inconnu, ni avant le chargement des listes", () => {
    expect(modeleChatValide({ ...base, destination: 'inconnu', model: 'geco/parti' })).toBe(true)
    expect(modeleChatValide({ ...base, charge: false, model: 'geco/parti' })).toBe(true)
  })
  it('non-admin (listes non lues) : un modèle précis est invalide', () => {
    expect(modeleChatValide({ ...base, restreint: true, modeles: [], externes: [], model: 'llama3.1' })).toBe(false)
  })
})
