import { describe, expect, it } from 'vitest'
import { erreurPlage, heureValide, libellePlage } from '../../utils/plageLots'

describe('plage horaire des lots IA', () => {
  it('reconnaît une heure HH:MM', () => {
    for (const v of ['00:00', '06:00', '22:30', '23:59', ' 07:05 ']) expect(heureValide(v)).toBe(true)
    for (const v of ['', '22', '22h00', '24:00', '12:60', '7:05', '22:00:00']) expect(heureValide(v)).toBe(false)
  })

  it('accepte une plage complète ou vide, refuse une seule borne', () => {
    expect(erreurPlage('', '')).toBeNull()
    expect(erreurPlage('22:00', '06:00')).toBeNull()
    expect(erreurPlage('22:00', '')).toMatch(/début ET/)
    expect(erreurPlage('', '06:00')).toMatch(/début ET/)
    expect(erreurPlage('22h', '06:00')).toMatch(/HH:MM/)
  })

  it('dit en clair ce que la plage veut dire', () => {
    expect(libellePlage('', '')).toMatch(/^Toujours/)
    expect(libellePlage('22:00', '06:00')).toContain("jusqu'au lendemain")
    expect(libellePlage('08:00', '18:00')).not.toContain('lendemain')
    expect(libellePlage('10:00', '10:00')).toMatch(/Toute la journée/)
  })
})
