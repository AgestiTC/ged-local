/**
 * CategoriesListeFermee — « Catégories : liste fermée » (Paramètres › Maintenance, prompts A3, 18/11/2026).
 * ===========================================================================================
 * L'IA classe désormais dans une liste fermée de catégories. Ici : SIMULER le regroupement des fiches
 * existantes (rien n'est écrit), puis l'appliquer — l'ancienne catégorie est gardée, « Annuler » la rend.
 * Les catégories corrigées à la main et celles des règles de classement ne sont jamais touchées.
 */
import { useState } from 'react'
import { ListChecks, Undo2 } from 'lucide-react'
import { extractApiError, systemApi, type SimulationCategories } from '../../api'
import { confirmerTexte } from '../common/Confirmation'
import { useToast } from '../common/Toast'

const nb = (n: number) => n.toLocaleString('fr-FR')

/** Phrase de bilan d'une simulation. PURE. */
export function bilanSimulation(s: SimulationCategories): string {
  if (s.fiches_changees === 0) {
    return s.deja_regroupees > 0
      ? `Toutes les fiches sont déjà dans la liste (${nb(s.deja_regroupees)} regroupées, annulable).`
      : 'Toutes les fiches sont déjà dans la liste.'
  }
  const manuelles = s.manuelles_ignorees ? `, ${nb(s.manuelles_ignorees)} corrigée(s) à la main laissée(s) telles quelles` : ''
  return `${nb(s.fiches_changees)} fiche(s) sur ${nb(s.fiches)} changeraient de catégorie `
    + `(${nb(s.categories_changees)} catégories ramenées à ${s.liste.length})${manuelles}.`
}

export function CategoriesListeFermee() {
  const toast = useToast()
  const [sim, setSim] = useState<SimulationCategories | null>(null)
  const [occupe, setOccupe] = useState<'simuler' | 'regrouper' | 'annuler' | null>(null)

  const simuler = async () => {
    setOccupe('simuler')
    try { setSim(await systemApi.categoriesSimulation()) }
    catch (e) { toast.error(extractApiError(e, 'Simulation impossible')) } finally { setOccupe(null) }
  }

  const regrouper = async () => {
    if (!sim || !await confirmerTexte(`${bilanSimulation(sim)}\nL'ancienne catégorie de chaque fiche est gardée : « Annuler le regroupement » la rend.`, 'Regrouper')) return
    setOccupe('regrouper')
    try {
      const r = await systemApi.categoriesRegrouper()
      toast.success(`${nb(r.fiches_changees)} fiche(s) regroupée(s) sur la liste fermée.`)
      setSim(await systemApi.categoriesSimulation())
    } catch (e) { toast.error(extractApiError(e, 'Regroupement impossible')) } finally { setOccupe(null) }
  }

  const annuler = async () => {
    if (!await confirmerTexte('Rendre à chaque fiche regroupée sa catégorie d\'avant ?', 'Annuler le regroupement')) return
    setOccupe('annuler')
    try {
      const r = await systemApi.categoriesAnnuler()
      toast.success(`${nb(r.fiches_restaurees)} fiche(s) ont retrouvé leur catégorie d'avant.`)
      setSim(await systemApi.categoriesSimulation())
    } catch (e) { toast.error(extractApiError(e, 'Annulation impossible')) } finally { setOccupe(null) }
  }

  const bouton = 'flex items-center gap-1.5 shrink-0 px-3 py-2 text-sm border rounded-lg disabled:opacity-40 transition-colors'
  return (
    <div className="px-4 py-3 border-t border-gray-100 space-y-2">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="min-w-[16rem] flex-1">
          <p className="text-sm font-medium text-gray-700 flex items-center gap-1.5">
            <ListChecks size={14} className="text-indigo-500" /> Catégories : liste fermée
          </p>
          <p className="text-xs text-gray-400 mt-0.5">
            L'IA classe chaque document dans une liste fixe de catégories. « Simuler » montre ce que deviendraient
            les fiches déjà classées, sans rien changer. Les catégories corrigées à la main et celles des règles de
            classement ne sont jamais touchées ; l'ancienne catégorie est gardée.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button type="button" onClick={simuler} disabled={occupe !== null}
            className={`${bouton} border-gray-200 text-gray-700 hover:bg-gray-50`}>Simuler</button>
          <button type="button" onClick={regrouper} disabled={occupe !== null || !sim || sim.fiches_changees === 0}
            className={`${bouton} border-blue-200 text-blue-600 hover:bg-blue-50`}>Regrouper</button>
          <button type="button" onClick={annuler} disabled={occupe !== null || !sim || sim.deja_regroupees === 0}
            className={`${bouton} border-gray-200 text-gray-600 hover:bg-gray-50`}><Undo2 size={14} /> Annuler le regroupement</button>
        </div>
      </div>
      {sim && (
        <div className="text-xs text-gray-600 space-y-2">
          <p>{bilanSimulation(sim)}</p>
          {sim.exemples.length > 0 && (
            <details>
              <summary className="cursor-pointer text-blue-600">Voir les correspondances ({nb(sim.categories_changees)})</summary>
              <ul className="mt-1 grid sm:grid-cols-2 gap-x-6 gap-y-0.5">
                {sim.exemples.map(e => (
                  <li key={e.ancienne} className="flex justify-between gap-2">
                    <span className="truncate">{e.ancienne} → <strong>{e.nouvelle}</strong></span>
                    <span className="text-gray-400 shrink-0">{nb(e.fiches)}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
