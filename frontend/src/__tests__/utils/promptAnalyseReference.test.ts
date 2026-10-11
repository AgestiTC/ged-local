import { describe, expect, it } from 'vitest'
import {
  CORPS_ANALYSE_DEFAUT, promptAnalyseReference, promptVersionCorrigee, verifierConsigne,
} from '../../utils/promptAnalyseReference'

describe('promptAnalyseReference', () => {
  it('structure constructive et visuelle, sans tableau Markdown', () => {
    const p = promptAnalyseReference()
    for (const section of ['🎯 En bref', '📊 Tableau de bord', '✅ Points forts', "🛠️ Axes d'amélioration",
      '🧩 Points manquants', '💡 Les 3 actions prioritaires']) {
      expect(p).toContain(section)
    }
    expect(p).toContain('👉 Proposition')
    expect(p).toContain('pas de tableau Markdown')
    expect(p).not.toContain('Cohérence avec les critères')   // sans critères connus
  })

  it('confronte le document aux critères de notation quand ils sont connus', () => {
    const p = promptAnalyseReference(['Délais d’urgence', 'Moyens humains'])
    expect(p).toContain('- Délais d’urgence')
    expect(p).toContain('🔗 Cohérence avec les critères de notation')
  })

  it('une consigne MODIFIÉE garde les critères ajoutés par Matothèque', () => {
    const p = promptAnalyseReference(['Délais'], 'Ma consigne à moi')
    expect(p.startsWith('Ma consigne à moi')).toBe(true)
    expect(p).toContain('- Délais')
  })
})

describe('promptVersionCorrigee', () => {
  it('avant → après cités, valeurs jamais inventées, clauses prêtes à copier', () => {
    const p = promptVersionCorrigee(['Délais'])
    for (const s of ['✏️ Passages réécrits', '**Avant :**', '**Après :**', '➕ Clauses à ajouter', '[à préciser']) {
      expect(p).toContain(s)
    }
    expect(p).toContain('Délais')
    expect(p).toContain('à relire et valider')
  })
})

describe('verifierConsigne (garde-fou)', () => {
  it('accepte la consigne d\'origine', () => {
    expect(verifierConsigne(CORPS_ANALYSE_DEFAUT)).toEqual([])
  })
  it('refuse un texte trop court ou sans structure', () => {
    expect(verifierConsigne('trop court')).toHaveLength(2)
    expect(verifierConsigne('x'.repeat(300))[0]).toContain('section')
  })
})
