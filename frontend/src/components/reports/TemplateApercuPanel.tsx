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
import { templatesApi, type TemplateApercu } from '../../api'

export default function TemplateApercuPanel({ templateId }: { templateId: string }) {
  const [apercu, setApercu] = useState<TemplateApercu | 'chargement' | 'erreur'>('chargement')

  useEffect(() => {
    let actif = true
    setApercu('chargement')
    templatesApi.apercu(templateId)
      .then(a => { if (actif) setApercu(a) })
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
          <p className={clsx(apercu.type === 'inconnu' ? 'text-red-700' : 'text-gray-600')}>{apercu.message}</p>
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
        </>
      )}
    </div>
  )
}
