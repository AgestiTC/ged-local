/**
 * copierTexte() — copie presse-papiers robuste HORS contexte sécurisé.
 * ===================================================================
 * `navigator.clipboard` n'existe QUE dans un contexte sécurisé (HTTPS ou localhost).
 * En HTTP simple (ex. http://<ip-LAN>:3003) il est **absent** → les boutons « Copier »
 * échouaient. On tente d'abord l'API moderne, puis on retombe sur la méthode historique
 * (`<textarea>` + `document.execCommand('copy')`), qui marche en HTTP.
 *
 * Retourne `true` si la copie a réussi, `false` sinon (l'appelant peut alors proposer
 * une sélection manuelle).
 */
export async function copierTexte(texte: string): Promise<boolean> {
  // 1) API moderne (contexte sécurisé).
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(texte)
      return true
    }
  } catch { /* repli ci-dessous (permission refusée / contexte non sécurisé) */ }

  // 2) Repli historique : textarea temporaire hors écran + execCommand.
  try {
    const ta = document.createElement('textarea')
    ta.value = texte
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '0'
    ta.style.left = '0'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
