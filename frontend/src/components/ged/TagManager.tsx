/**
 * TagManager — Gestion des tags éditables d'un document
 * Permet d'ajouter, supprimer et sauvegarder les tags via PATCH /api/documents/{id}/metadata
 */
import { useState } from 'react'
import { Tag, X, Plus, Check } from 'lucide-react'
import { clsx } from 'clsx'
import { documentsApi } from '../../api'
import { useToast } from '../common/Toast'

interface Props {
  documentId: string
  tags: string[]
  onUpdate?: (tags: string[]) => void
  readonly?: boolean
}

export default function TagManager({ documentId, tags, onUpdate, readonly = false }: Props) {
  const [editing, setEditing] = useState(false)
  const [localTags, setLocalTags] = useState<string[]>(tags)
  const [nouveauTag, setNouveauTag] = useState('')
  const [saving, setSaving] = useState(false)
  const toast = useToast()

  const ajouterTag = () => {
    const tag = nouveauTag.trim().toLowerCase()
    if (!tag || localTags.includes(tag)) return
    setLocalTags(t => [...t, tag])
    setNouveauTag('')
  }

  const supprimerTag = (tag: string) => {
    setLocalTags(t => t.filter(x => x !== tag))
  }

  const sauvegarder = async () => {
    setSaving(true)
    try {
      const meta = await documentsApi.patchMetadata(documentId, { tags: localTags })
      onUpdate?.(meta.tags ?? localTags)
      setEditing(false)
      toast.success('Tags mis à jour')
    } catch {
      toast.error('Erreur mise à jour des tags')
    } finally {
      setSaving(false)
    }
  }

  const annuler = () => {
    setLocalTags(tags)
    setNouveauTag('')
    setEditing(false)
  }

  if (readonly || !editing) {
    return (
      <div className="flex flex-wrap gap-1 items-center">
        {(editing ? localTags : tags).map(tag => (
          <span
            key={tag}
            className="flex items-center gap-1 text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full"
          >
            <Tag size={9} />
            {tag}
          </span>
        ))}
        {tags.length === 0 && !editing && (
          <span className="text-xs text-gray-400">Aucun tag</span>
        )}
        {!readonly && (
          <button
            onClick={() => setEditing(true)}
            className="text-xs px-2 py-0.5 border border-dashed border-gray-300 text-gray-400 rounded-full hover:border-blue-400 hover:text-blue-500 transition-colors"
          >
            <Plus size={10} className="inline" /> Modifier
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Tags actuels avec bouton supprimer */}
      <div className="flex flex-wrap gap-1">
        {localTags.map(tag => (
          <span
            key={tag}
            className="flex items-center gap-1 text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full"
          >
            <Tag size={9} />
            {tag}
            <button onClick={() => supprimerTag(tag)} className="hover:text-red-500">
              <X size={9} />
            </button>
          </span>
        ))}
      </div>

      {/* Ajout tag */}
      <div className="flex gap-1">
        <input
          type="text"
          value={nouveauTag}
          onChange={e => setNouveauTag(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') ajouterTag() }}
          placeholder="Nouveau tag…"
          className="flex-1 text-xs border border-gray-200 rounded-md px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
          autoFocus
        />
        <button
          onClick={ajouterTag}
          disabled={!nouveauTag.trim()}
          className="text-xs px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded-md disabled:opacity-40"
        >
          <Plus size={12} />
        </button>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={sauvegarder}
          disabled={saving}
          className={clsx(
            'flex items-center gap-1 text-xs px-3 py-1.5 rounded-md transition-colors',
            saving ? 'bg-gray-100 text-gray-400' : 'bg-blue-600 text-white hover:bg-blue-700',
          )}
        >
          <Check size={11} />
          {saving ? 'Sauvegarde…' : 'Sauvegarder'}
        </button>
        <button
          onClick={annuler}
          className="text-xs px-3 py-1.5 rounded-md text-gray-500 hover:bg-gray-100"
        >
          Annuler
        </button>
      </div>
    </div>
  )
}
