import { describe, expect, it } from 'vitest'
import { promptAnalyseReference, promptVersionCorrigee } from '../../utils/promptAnalyseReference'

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
})
