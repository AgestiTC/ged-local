/**
 * uuid() — identifiant unique, robuste HORS contexte sécurisé.
 * ==========================================================
 * `crypto.randomUUID()` n'existe QUE dans un contexte sécurisé (HTTPS ou localhost).
 * En HTTP simple (ex. http://<ip-LAN>:3003) elle est **absente** → « crypto.randomUUID is
 * not a function » faisait planter toasts, ids de rapport, etc. On tombe alors sur
 * `crypto.getRandomValues` (disponible en HTTP) puis, en dernier recours, `Math.random`.
 */
export function uuid(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto
  if (c?.randomUUID) {
    try { return c.randomUUID() } catch { /* contexte non sécurisé → repli ci-dessous */ }
  }
  if (c?.getRandomValues) {
    const b = c.getRandomValues(new Uint8Array(16))
    b[6] = (b[6] & 0x0f) | 0x40   // version 4
    b[8] = (b[8] & 0x3f) | 0x80   // variante
    const h = Array.from(b, x => x.toString(16).padStart(2, '0'))
    return `${h.slice(0, 4).join('')}-${h.slice(4, 6).join('')}-${h.slice(6, 8).join('')}-${h.slice(8, 10).join('')}-${h.slice(10, 16).join('')}`
  }
  // Dernier recours (non cryptographique, mais suffisant pour des ids d'UI).
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, ch => {
    const r = (Math.random() * 16) | 0
    return (ch === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}
