/**
 * HistoriquePromptPreset — versions d'un prompt pré-enregistré (étape A6, 18/11/2026).
 * ===================================================================================
 * Chaque création ou modification d'un preset est une version (`prompts_presets_versions`) :
 * « Voir » montre le contenu d'une version, « Restaurer » la recopie EN UNE NOUVELLE version, après
 * confirmation — rien n'est jamais écrasé. Un preset créé avant l'historique reçoit sa version 1
 * (son contenu actuel) à la première lecture.
 */
import { useCallback, useEffect, useState } from 'react'
import { History, Loader2 } from 'lucide-react'
import { promptsApi, type PromptPresetVersion } from '../../api'
import type { PromptPreset } from '../../types'
import { useToast } from '../common/Toast'
import { confirmerTexte } from '../common/Confirmation'

const dateFr = (iso: string | null) => (iso ? new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' }) : '')

interface Props {
  presetId: string
  /** Appelé avec le preset restauré (pour rafraîchir la liste). */
  onRestaure: (preset: PromptPreset) => void
}

export default function HistoriquePromptPreset({ presetId, onRestaure }: Props) {
  const [versions, setVersions] = useState<PromptPresetVersion[] | null>(null)
  const [vue, setVue] = useState<number | null>(null)
  const [envoi, setEnvoi] = useState(false)
  const toast = useToast()

  const charger = useCallback(() => {
    promptsApi.versions(presetId)
      .then(r => setVersions(r.versions))
      .catch(() => { setVersions([]); toast.error('Historique illisible (serveur ?)') })
  }, [presetId, toast])

  useEffect(() => { charger() }, [charger])

  const restaurer = async (v: PromptPresetVersion) => {
    if (!await confirmerTexte(`Restaurer la version ${v.version} ?\n`
      + 'Son contenu devient une nouvelle version active ; la version actuelle reste dans l\'historique.')) return
    setEnvoi(true)
    try {
      const preset = await promptsApi.restaurer(presetId, v.version)
      toast.success(`Version ${v.version} restaurée (nouvelle version ${preset.version})`)
      onRestaure(preset)
      charger()
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
      toast.error(typeof detail === 'string' ? detail : 'Restauration impossible')
    } finally {
      setEnvoi(false)
    }
  }

  if (versions === null) {
    return <p className="flex items-center gap-1.5 text-gray-400 text-xs mt-2"><Loader2 size={12} className="animate-spin" /> Historique…</p>
  }

  return (
    <div className="mt-2 space-y-1.5" data-testid="historique-preset">
      <p className="flex items-center gap-1.5 text-xs font-semibold text-gray-700"><History size={12} /> Historique</p>
      <ul className="space-y-1">
        {versions.map((v, i) => (
          <li key={v.version} className="rounded-md border border-gray-200 text-xs">
            <div className="flex items-center gap-2 px-2.5 py-1.5">
              <span className="font-medium text-gray-800">v{v.version}</span>
              <span className="text-gray-400">{dateFr(v.created_at)}</span>
              {v.auteur && <span className="text-gray-400">{v.auteur}</span>}
              <span className="flex-1 min-w-0 truncate text-gray-600">{v.commentaire || v.nom}</span>
              {i === 0 && <span className="text-green-700">actuelle</span>}
              <button type="button" onClick={() => setVue(vue === v.version ? null : v.version)}
                className="text-blue-600 hover:underline">{vue === v.version ? 'Masquer' : 'Voir'}</button>
              {i > 0 && (
                <button type="button" onClick={() => restaurer(v)} disabled={envoi}
                  className="text-violet-700 hover:underline disabled:opacity-60">Restaurer</button>
              )}
            </div>
            {vue === v.version && (
              <div className="border-t border-gray-100 bg-gray-50 p-2.5 space-y-1 text-[11px] text-gray-600">
                <p><strong>{v.nom}</strong>{v.categorie ? ` · ${v.categorie}` : ''}{v.modele_prefere ? ` · ${v.modele_prefere}` : ' · modèle Auto'}</p>
                {v.description && <p>{v.description}</p>}
                <pre className="whitespace-pre-wrap font-mono max-h-60 overflow-y-auto">{v.prompt_text}</pre>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
