/**
 * Tests — liens de contact (téléphoner, ouvrir une carte).
 *
 * Ce qui compte ici : ne **jamais** proposer un lien qui ouvrirait le composeur sur du vide,
 * et savoir nettoyer un numéro noté à la volée pendant un appel — « 06 12 34 56 78
 * (après 18 h) » est ce qu'on écrit vraiment dans une fiche, pas un numéro normalisé.
 */
import { describe, expect, it } from 'vitest'
import { adressePostale, lienCarte, lienTelephone } from '../../utils/contact'

describe('lienTelephone', () => {
  it('nettoie les séparateurs et les annotations', () => {
    // Le cas qui a révélé un vrai défaut : sans coupure à l'annotation, le « 18 » de
    // « après 18 h » se collait au numéro et le lien composait 061234567818.
    expect(lienTelephone('06 12 34 56 78 (après 18 h)')).toBe('tel:0612345678')
    expect(lienTelephone('06 12 34 56 78 à partir de 9h')).toBe('tel:0612345678')
    expect(lienTelephone('+33 6.12.34.56.78')).toBe('tel:+33612345678')
    expect(lienTelephone('06-12-34-56-78')).toBe('tel:0612345678')
  })

  it('refuse ce qui n’est pas un numéro appelable', () => {
    expect(lienTelephone('à demander')).toBeNull()
    expect(lienTelephone('')).toBeNull()
    expect(lienTelephone(null)).toBeNull()
    expect(lienTelephone('12345')).toBeNull()   // trop court : une note, pas un numéro
  })
})

describe('adressePostale', () => {
  it('assemble ce qui existe et ignore les trous', () => {
    expect(adressePostale('12 rue des Lilas', 'Rennes')).toBe('12 rue des Lilas, Rennes')
    expect(adressePostale(null, 'Rennes')).toBe('Rennes')
    expect(adressePostale(null, null)).toBeNull()
  })
})

describe('lienCarte', () => {
  it('encode l’adresse et rend un lien exploitable', () => {
    const lien = lienCarte('12 rue des Lilas, Rennes')
    expect(lien).toContain(encodeURIComponent('12 rue des Lilas, Rennes'))
    // Hors Android, on retombe sur OpenStreetMap — cohérent avec le reste du projet.
    expect(lien!.startsWith('https://www.openstreetmap.org/') || lien!.startsWith('geo:')).toBe(true)
  })

  it('ne rend rien sans adresse', () => {
    expect(lienCarte(null)).toBeNull()
    expect(lienCarte('')).toBeNull()
  })
})
