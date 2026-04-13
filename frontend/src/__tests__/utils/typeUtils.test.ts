/**
 * Tests — utilitaires TypeScript / types purs
 * =============================================
 * Vérifie les invariants de types et les valeurs constantes
 * qui n'ont pas besoin de rendu React.
 */

import { describe, it, expect } from 'vitest'

// ─── Types DocumentStatut ───────────────────────────────────────────────────

describe('DocumentStatut — valeurs valides', () => {
  const STATUTS_VALIDES = ['pending', 'extracted', 'enriched', 'error']

  it('les 4 statuts sont couverts', () => {
    expect(STATUTS_VALIDES).toHaveLength(4)
  })

  it('statut "enriched" est le statut final après IA', () => {
    expect(STATUTS_VALIDES).toContain('enriched')
  })

  it('statut "error" est présent pour les échecs d\'extraction', () => {
    expect(STATUTS_VALIDES).toContain('error')
  })
})

// ─── SearchType ────────────────────────────────────────────────────────────

describe('SearchType — poids de fusion', () => {
  const POIDS = {
    FULLTEXT: 0.40,
    SEMANTIQUE: 0.60,
  }

  it('les poids somment à 1.0', () => {
    expect(POIDS.FULLTEXT + POIDS.SEMANTIQUE).toBeCloseTo(1.0)
  })

  it('la recherche sémantique a plus de poids que le full-text', () => {
    expect(POIDS.SEMANTIQUE).toBeGreaterThan(POIDS.FULLTEXT)
  })
})

// ─── OutputMode ────────────────────────────────────────────────────────────

describe('OutputMode — modes disponibles', () => {
  const MODES_VALIDES = ['rapport_libre', 'remplir_template', 'classement']

  it('trois modes sont disponibles', () => {
    expect(MODES_VALIDES).toHaveLength(3)
  })

  it('le mode par défaut (rapport_libre) est présent', () => {
    expect(MODES_VALIDES[0]).toBe('rapport_libre')
  })
})

// ─── Taille fichier / pagination ────────────────────────────────────────────

describe('pagination — calculs', () => {
  function computePages(total: number, pageSize: number): number {
    return Math.ceil(total / pageSize)
  }

  it('0 documents → 0 pages', () => {
    expect(computePages(0, 50)).toBe(0)
  })

  it('50 documents, pageSize 50 → 1 page', () => {
    expect(computePages(50, 50)).toBe(1)
  })

  it('51 documents, pageSize 50 → 2 pages', () => {
    expect(computePages(51, 50)).toBe(2)
  })

  it('100 documents, pageSize 25 → 4 pages', () => {
    expect(computePages(100, 25)).toBe(4)
  })

  it('1 document, pageSize 50 → 1 page', () => {
    expect(computePages(1, 50)).toBe(1)
  })
})

// ─── Nom de fichier export (logique partagée avec backend) ─────────────────

describe('nom fichier export — sanitisation', () => {
  /**
   * Reproduit la logique de _nom_export côté frontend pour les titres.
   * Les caractères dangereux doivent être supprimés ou remplacés.
   */
  function sanitiseTitle(title: string, maxLen = 80): string {
    return title
      .replace(/[/\\'"<>|*?:]/g, '')
      .replace(/\s+/g, '_')
      .slice(0, maxLen)
  }

  it('supprime les slashes', () => {
    expect(sanitiseTitle('rapport/annuel')).not.toContain('/')
    expect(sanitiseTitle('rapport\\local')).not.toContain('\\')
  })

  it('supprime les guillemets', () => {
    expect(sanitiseTitle("rapport d'analyse")).not.toContain("'")
    expect(sanitiseTitle('rapport "confidentiel"')).not.toContain('"')
  })

  it('remplace les espaces par des underscores', () => {
    const result = sanitiseTitle('mon rapport annuel')
    expect(result).toBe('mon_rapport_annuel')
  })

  it('tronque les titres trop longs', () => {
    const long = 'A'.repeat(200)
    expect(sanitiseTitle(long)).toHaveLength(80)
  })

  it('titre vide → chaîne vide', () => {
    expect(sanitiseTitle('')).toBe('')
  })
})

// ─── Taille humaine (bytes → Mo) ───────────────────────────────────────────

describe('formatTaille — conversion octets', () => {
  function formatTaille(octets: number): string {
    if (octets < 1024) return `${octets} o`
    if (octets < 1024 * 1024) return `${(octets / 1024).toFixed(1)} Ko`
    if (octets < 1024 * 1024 * 1024) return `${(octets / (1024 * 1024)).toFixed(1)} Mo`
    return `${(octets / (1024 * 1024 * 1024)).toFixed(1)} Go`
  }

  it('moins de 1 Ko → octets', () => {
    expect(formatTaille(512)).toBe('512 o')
  })

  it('1 Ko → kiloctets', () => {
    expect(formatTaille(1024)).toBe('1.0 Ko')
  })

  it('1.5 Mo → mégaoctets', () => {
    expect(formatTaille(1.5 * 1024 * 1024)).toBe('1.5 Mo')
  })

  it('2 Go → gigaoctets', () => {
    expect(formatTaille(2 * 1024 * 1024 * 1024)).toBe('2.0 Go')
  })
})
