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
  const avecUserAgent = (ua: string) =>
    Object.defineProperty(navigator, 'userAgent', { value: ua, configurable: true })

  it('rend un lien geo: sur Android, où le système sait l’honorer', () => {
    avecUserAgent('Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36')
    const lien = lienCarte('12 rue des Lilas, Rennes')
    expect(lien).toBe(`geo:0,0?q=${encodeURIComponent('12 rue des Lilas, Rennes')}`)
  })

  it('ne renvoie JAMAIS vers un service de cartographie en ligne', () => {
    // Le point de la décision du 09/09 : ouvrir openstreetmap.org enverrait le domicile
    // d'une personne identifiée à un tiers. Hors Android, on ne propose rien — l'écran
    // bascule sur « copier l'adresse ».
    for (const ua of [
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
      'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)',
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
    ]) {
      avecUserAgent(ua)
      expect(lienCarte('12 rue des Lilas, Rennes')).toBeNull()
    }
  })

  it('ne rend rien sans adresse', () => {
    avecUserAgent('Mozilla/5.0 (Linux; Android 14)')
    expect(lienCarte(null)).toBeNull()
    expect(lienCarte('')).toBeNull()
  })
})
