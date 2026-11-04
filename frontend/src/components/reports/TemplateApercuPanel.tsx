/**
 * TemplateApercuPanel — ce que Matothèque reconnaît dans un modèle Excel.
 * =======================================================================
 * Grille d'analyse, liste de critères en lignes, colonnes de la ligne 1… ou rien : affiché AVANT
 * de lancer un Tableau comparatif (le 11/10/2026, une grille non reconnue n'a été découverte qu'au
 * sixième refus de lancement). Partagé par la page Créer et Paramètres › Génération.
 */
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { extractApiError, templatesApi, type TemplateApercu } from '../../api'

export default function TemplateApercuPanel({ templateId }: { templateId: string }) {
  const [apercu, setApercu] = useState<TemplateApercu | 'chargement' | 'erreur'>('chargement')
  // Autonomie (04/11/2026) : une grille que les règles ne reconnaissent pas est confiée à l'IA
  // LOCALE, qui en apprend la structure ; Matothèque la vérifie et la retient pour la suite.
  const [apprentissage, setApprentissage] = useState<'en cours' | string | null>(null)

  const apprendre = (actif: () => boolean) => {
    setApprentissage('en cours')
    templatesApi.apprendre(templateId)
      .then(a => { if (actif()) { setApercu(a); setApprentissage(null) } })
      .catch(e => { if (actif()) setApprentissage(extractApiError(e, "L'IA locale n'a pas su lire la grille")) })
  }

  useEffect(() => {
    let actif = true
    setApercu('chargement')
    setApprentissage(null)
    templatesApi.apercu(templateId)
      .then(a => {
        if (!actif) return
        setApercu(a)
        if (a.type === 'inconnu') apprendre(() => actif)
      })
      .catch(() => { if (actif) setApercu('erreur') })
    return () => { actif = false }
  }, [templateId])

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-2.5 text-xs space-y-1.5">
      {apercu === 'chargement' ? (
        <p className="flex items-center gap-1.5 text-gray-400">
          <Loader2 size={12} className="animate-spin" /> Lecture du classeur…
        </p>
      ) : apercu === 'erreur' ? (
        <p className="text-red-600">Aperçu impossible (fichier introuvable sur le serveur ?)</p>
      ) : (
        <>
          {apprentissage === 'en cours' ? (
            <p className="flex items-center gap-1.5 text-blue-600">
              <Loader2 size={12} className="animate-spin" />
              Grille d'une forme nouvelle : l'IA locale en analyse la structure (critères, avis, notes,
              candidats)… Matothèque la retiendra pour les prochaines.
            </p>
          ) : apprentissage ? (
            <div className="space-y-1">
              <p className="text-red-700">{apprentissage}</p>
              <button type="button" onClick={() => apprendre(() => true)}
                className="text-blue-600 hover:underline">Réessayer l'analyse par l'IA</button>
            </div>
          ) : (
            <p className={clsx(apercu.type === 'inconnu' ? 'text-red-700' : 'text-gray-600')}>{apercu.message}</p>
          )}
          {apercu.criteres.length > 0 && (
            <ol className="list-decimal pl-5 text-gray-700 space-y-0.5 max-h-48 overflow-y-auto">
              {apercu.criteres.map((c, i) => (
                <li key={i}>
                  {c.nom}
                  {c.points != null && <span className="text-gray-400"> — {c.points} pts</span>}
                </li>
              ))}
            </ol>
          )}
          {apercu.bareme && apercu.bareme.length > 0 && (
            <div>
              <p className="font-medium text-gray-600">Barème lu dans le classeur</p>
              <ul className="pl-1 text-gray-700 space-y-0.5">
                {apercu.bareme.map(b => (
                  <li key={b.note}>
                    <span className="font-mono text-gray-500">{b.note}</span> = {b.libelle}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}
