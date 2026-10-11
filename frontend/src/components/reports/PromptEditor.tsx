/**
 * PromptEditor — Éditeur de prompt avec presets
 * Charge les prompts depuis l'API et permet de sauvegarder le prompt courant.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ChevronDown, Save, Settings, Trash2 } from 'lucide-react'
import { useReportStore } from '../../stores/reportStore'
import { promptsApi } from '../../api'
import { useToast } from '../common/Toast'
import type { PromptPreset } from '../../types'
import RelirePromptButton from './RelirePromptButton'

const PLACEHOLDER_RAPPORT = `Décrivez le rapport à générer…

Exemples :
• Fais un classement des candidats par compétences
• Résume les points clés et identifie les risques
• Compare les offres et recommande la meilleure`

export default function PromptEditor({ placeholder = PLACEHOLDER_RAPPORT }: { placeholder?: string }) {
  const { prompt, setPrompt, model, setModel, outputMode } = useReportStore()
  const [presets, setPresets] = useState<PromptPreset[]>([])
  const [showPresets, setShowPresets] = useState(false)
  const [showSave, setShowSave] = useState(false)
  const [nomPreset, setNomPreset] = useState('')
  const toast = useToast()

  useEffect(() => {
    promptsApi.list().then(d => setPresets(d.prompts)).catch(() => {})
  }, [])

  const appliquerPreset = (preset: PromptPreset) => {
    setPrompt(preset.prompt_text)
    // Le « modèle préféré » du prompt était enregistré mais jamais appliqué (constat du 11/10/2026).
    // Paramètres ne propose que des modèles installés ; s'il a été désinstallé depuis, useModeles
    // remet « Auto » au prochain chargement de la page.
    if (preset.modele_prefere) {
      setModel(preset.modele_prefere)
      toast.success(`Modèle du prompt appliqué : ${preset.modele_prefere}`)
    }
    setShowPresets(false)
  }

  const sauvegarder = async () => {
    if (!nomPreset.trim() || !prompt.trim()) return
    try {
      const nouveau = await promptsApi.create({
        nom: nomPreset,
        prompt_text: prompt,
        modele_prefere: model,
        categorie: 'rapport',
      })
      setPresets(p => [...p, nouveau])
      setNomPreset('')
      setShowSave(false)
      toast.success('Prompt sauvegardé')
    } catch {
      toast.error('Erreur lors de la sauvegarde')
    }
  }

  const supprimerPreset = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await promptsApi.delete(id)
      setPresets(p => p.filter(x => x.id !== id))
    } catch {
      toast.error('Erreur suppression')
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Barre presets */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <button
            onClick={() => setShowPresets(s => !s)}
            className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded-md px-2.5 py-1.5 bg-white w-full"
          >
            <span className="flex-1 text-left">Prompts pré-enregistrés…</span>
            <ChevronDown size={12} />
          </button>

          {showPresets && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-lg shadow-lg z-10 max-h-52 overflow-y-auto">
              {presets.length === 0 && (
                <p className="text-xs text-gray-400 px-3 py-2">Aucun preset sauvegardé</p>
              )}
              {presets.map(p => (
                <div
                  key={p.id}
                  onClick={() => appliquerPreset(p)}
                  className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 cursor-pointer group"
                >
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-gray-800 truncate">{p.nom}</p>
                    {p.description && (
                      <p className="text-xs text-gray-400 truncate">{p.description}</p>
                    )}
                  </div>
                  <button
                    onClick={e => supprimerPreset(p.id, e)}
                    className="opacity-100 md:opacity-0 md:group-hover:opacity-100 text-red-400 hover:text-red-600"
                  >
                    <Trash2 size={11} />
                  </button>
                </div>
              ))}
              <Link
                to="/settings?section=set-generation"
                className="flex items-center gap-1.5 px-3 py-2 border-t border-gray-100 text-xs text-blue-600 hover:bg-blue-50"
              >
                <Settings size={11} /> Gérer les prompts (modifier, renommer)…
              </Link>
            </div>
          )}
        </div>

        <button
          onClick={() => setShowSave(s => !s)}
          title="Sauvegarder ce prompt (réutilisable via « Prompts pré-enregistrés »)"
          className="text-gray-400 hover:text-blue-500 border border-gray-200 rounded-md p-1.5"
        >
          <Save size={13} />
        </button>
        {/* Modifier un prompt enregistré : c'est dans Paramètres › Génération (11/10/2026 — demandé
            pour ne pas recréer le prompt d'analyse d'offres à chaque fois). */}
        <Link
          to="/settings?section=set-generation"
          title="Gérer les prompts enregistrés (Paramètres › Génération)"
          className="text-gray-400 hover:text-blue-500 border border-gray-200 rounded-md p-1.5"
        >
          <Settings size={13} />
        </Link>
      </div>

      {/* Formulaire sauvegarde */}
      {showSave && (
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="Nom du preset…"
            value={nomPreset}
            onChange={e => setNomPreset(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && sauvegarder()}
            className="flex-1 text-xs border border-gray-200 rounded-md px-2.5 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400"
          />
          <button
            onClick={sauvegarder}
            disabled={!nomPreset.trim()}
            className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md hover:bg-blue-700 disabled:opacity-40"
          >
            Sauvegarder
          </button>
        </div>
      )}

      {/* Zone de texte principale */}
      <textarea
        value={prompt}
        onChange={e => setPrompt(e.target.value)}
        placeholder={placeholder}
        className="w-full min-h-[160px] resize-y text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-400 placeholder:text-gray-300 leading-relaxed"
        onClick={() => setShowPresets(false)}
      />

      <div className="flex justify-between text-xs text-gray-400">
        <span>{prompt.length} caractères</span>
        {prompt.length > 0 && (
          <button onClick={() => setPrompt('')} className="hover:text-gray-600">Effacer</button>
        )}
      </div>

      {prompt.trim().length > 0 && (
        <RelirePromptButton texte={prompt} mode={outputMode} model={model} onRemplacer={setPrompt} />
      )}
    </div>
  )
}
