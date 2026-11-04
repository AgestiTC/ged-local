import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { describe, expect, it } from 'vitest'

// Demande du 04/11/2026 : « pas de popup navigateur mais la popup application ».
// Toute confirmation passe par components/common/Confirmation (confirmerTexte / useConfirmation).
const SRC = join(__dirname, '..', '..')

function fichiers(dossier: string): string[] {
  return readdirSync(dossier).flatMap(nom => {
    const p = join(dossier, nom)
    if (statSync(p).isDirectory()) return nom === '__tests__' ? [] : fichiers(p)
    return /\.tsx?$/.test(nom) ? [p] : []
  })
}

describe('boîtes du navigateur', () => {
  it('aucun confirm/alert/prompt natif dans le code de l’application', () => {
    const fautifs = fichiers(SRC)
      .filter(f => !f.includes(join('common', 'Confirmation')))
      .filter(f => /(?<![.\w])(?:window\.)?(?:confirm|alert|prompt)\(/.test(readFileSync(f, 'utf8')))
      .map(f => relative(SRC, f))
    expect(fautifs).toEqual([])
  })
})
