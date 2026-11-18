/**
 * Capture des prompts du FRONTEND avant la migration A6 (plan docs/plan-prompts-et-rag-apprenant.md).
 * ===================================================================================================
 * Rend, avec le code frontend ACTUEL et des entrées FICTIVES, les textes finaux des consignes
 * « documents de référence » (promptAnalyseReference / promptVersionCorrigee + instructions
 * complémentaires ajoutées par ReportsPage) et le message système de la page « IA internet ».
 *
 *   CAPTURE_A6=1 npx vitest run src/__tests__/capture   # (ré)écrit la fixture
 *   npx vitest run                                       # compare à la fixture
 *
 * La fixture `backend/tests/donnees/prompts_origine_a6.json` sert ensuite au backend : la route de
 * rendu migrée doit produire EXACTEMENT ces textes (tests/test_prompts_a6.py).
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { promptAnalyseReference, promptVersionCorrigee } from '../../utils/promptAnalyseReference'
import { SYSTEME } from '../../pages/IAInternetPage'

const FIXTURE = resolve(process.cwd(), '../backend/tests/donnees/prompts_origine_a6.json')

// Copie EXACTE de l'ajout fait par ReportsPage.analyserReference (vérifiée ci-dessous dans la source).
const SUFFIXE = "\n\nInstructions complémentaires de l'acheteur (à respecter, sans changer la structure ci-dessus) :\n"
const avecInstructions = (base: string, consignes: string) =>
  consignes.trim() ? `${base}${SUFFIXE}${consignes.trim()}` : base

const CORPS_MODIFIE = '# Ma consigne fictive\n\n## Partie 1\nTexte {avec accolades} et « guillemets ».\n\n## Partie 2\n- puce\n\n## Partie 3\nFin.'

type Cas = { cle: 'reference_analyse' | 'reference_corrigee'; criteres: string[]; corps: string | null; instructions: string }

const CAS: Record<string, Cas> = {
  'analyse#origine': { cle: 'reference_analyse', criteres: [], corps: null, instructions: '' },
  'analyse#criteres': { cle: 'reference_analyse', criteres: ['Délais d’intervention', 'Moyens humains (50 %)'], corps: null, instructions: '' },
  'analyse#modifie': { cle: 'reference_analyse', criteres: ['Prix'], corps: CORPS_MODIFIE, instructions: '' },
  'analyse#modifie-sans-criteres': { cle: 'reference_analyse', criteres: [], corps: CORPS_MODIFIE, instructions: '' },
  'analyse#instructions': { cle: 'reference_analyse', criteres: ['Qualité {technique}'], corps: null, instructions: '  Insister sur les pénalités.\n\n' },
  'analyse#instructions-blanches': { cle: 'reference_analyse', criteres: [], corps: null, instructions: ' \n\t ' },
  'corrigee#origine': { cle: 'reference_corrigee', criteres: [], corps: null, instructions: '' },
  'corrigee#criteres': { cle: 'reference_corrigee', criteres: ['Délais', 'Qualité', 'Prix ; remises'], corps: null, instructions: '' },
  'corrigee#modifie': { cle: 'reference_corrigee', criteres: ['Prix'], corps: CORPS_MODIFIE, instructions: '' },
  'corrigee#instructions': { cle: 'reference_corrigee', criteres: [], corps: null, instructions: '\u00a0Ton sobre.\nPas d’emoji.\ufeff ' },
}

function capturer(): Record<string, unknown> {
  const sortie: Record<string, unknown> = {}
  for (const [nom, c] of Object.entries(CAS)) {
    const corps = c.corps ?? undefined
    const base = c.cle === 'reference_corrigee' ? promptVersionCorrigee(c.criteres, corps) : promptAnalyseReference(c.criteres, corps)
    sortie[nom] = { ...c, texte: avecInstructions(base, c.instructions) }
  }
  sortie['internet.formulation'] = { role: SYSTEME.role, texte: SYSTEME.content }
  return sortie
}

describe('capture des prompts du frontend (A6)', () => {
  it("le suffixe recopié est bien celui de ReportsPage", () => {
    const source = readFileSync(resolve(process.cwd(), 'src/pages/ReportsPage.tsx'), 'utf-8')
    const attendu = '? `' + '$' + '{base}' + '\\n\\n' + "Instructions complémentaires de l'acheteur (à respecter, sans changer la structure ci-dessus) :" + '\\n' + '$' + '{consignesReference.trim()}`'
    expect(source).toContain(attendu)
  })

  it('fixture identique au rendu du code actuel', () => {
    const rendu = capturer()
    if (process.env.CAPTURE_A6 === '1') writeFileSync(FIXTURE, JSON.stringify(rendu, null, 2) + '\n', 'utf-8')
    expect(JSON.parse(readFileSync(FIXTURE, 'utf-8'))).toEqual(rendu)
  })
})
