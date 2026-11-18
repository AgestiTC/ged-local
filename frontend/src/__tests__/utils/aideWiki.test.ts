import { describe, expect, it } from 'vitest'
import { lienAideWiki } from '../../utils/aideWiki'

describe('lienAideWiki', () => {
  it('cherche la phrase exacte du titre dans le wiki', () => {
    expect(lienAideWiki('https://wiki.exemple.fr/', 'Pourquoi ma tâche attend'))
      .toBe('https://wiki.exemple.fr/search?term=%22Pourquoi%20ma%20t%C3%A2che%20attend%22')
  })

  it('aucun lien sans adresse de wiki', () => {
    expect(lienAideWiki(null, 'x')).toBeNull()
    expect(lienAideWiki('  ', 'x')).toBeNull()
  })
})
