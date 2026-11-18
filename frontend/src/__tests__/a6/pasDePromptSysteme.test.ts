import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

// Étape A6 (plan docs/plan-prompts-et-rag-apprenant.md) : aucun texte de prompt système dans le
// frontend. Les consignes envoyées à l'IA vivent dans le registre du backend (services/prompts.py).
// Exception : AideDossiersPage — exemples que l'utilisateur COPIE dans une IA web extérieure,
// jamais envoyés par Matothèque (texte d'aide).
const SRC = join(__dirname, '..', '..')
const EXCEPTIONS = [join('pages', 'AideDossiersPage.tsx')]

function fichiers(dossier: string): string[] {
  return readdirSync(dossier).flatMap(nom => {
    const p = join(dossier, nom)
    if (statSync(p).isDirectory()) return nom === '__tests__' || nom === 'node_modules' ? [] : fichiers(p)
    return /\.tsx?$/.test(nom) ? [p] : []
  })
}

describe('pas de prompt système dans le frontend (A6)', () => {
  it('aucune consigne « Tu es … » / « Respecte EXACTEMENT » hors exceptions', () => {
    const fautifs = fichiers(SRC)
      .filter(f => !EXCEPTIONS.some(e => f.endsWith(e)))
      .filter(f => /Tu es |Respecte EXACTEMENT/.test(readFileSync(f, 'utf8')))
      .map(f => relative(SRC, f))
    expect(fautifs).toEqual([])
  })
})
