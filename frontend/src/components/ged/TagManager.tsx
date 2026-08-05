/**
 * TagManager — Gestion éditable des TAGS ou des MOTS-CLÉS d'un document
 * Ajoute / supprime / sauvegarde via PATCH /api/documents/{id}/metadata (champ `tags` ou `mots_cles`).
 */
import { useState } from 'react'
import { Tag, X, Plus, Check } from 'lucide-react'
import { clsx } from 'clsx'
import { documentsApi } from '../../api'
import { useToast } from '../common/Toast'

interface Props {
  documentId: string
  /** Valeurs actuelles (tags ou mots-clés selon `field`). */
  tags: string[]
  /** Champ de métadonnée ciblé. `tags` (défaut) est mis en minuscules ; `mots_cles` garde la casse. */
  field?: 'tags' | 'mots_cles'
  onUpdate?: (valeurs: string[]) => void
  readonly?: boolean
}

export default function TagManager({ documentId, tags, field = 'tags', onUpdate, readonly = false }: Props) {
  const [editing, setEditing] = useState(false)
  const [localTags, setLocalTags] = useState<string[]>(tags)
  const [nouveauTag, setNouveauTag] = useState('')
  const [saving, setSaving] = useState(false)
  const toast = useToast()

  const estTag = field === 'tags'
  const libelle = estTag ? 'tag' : 'mot-clé'
  const chipClass = estTag ? 'bg-blue-50 text-blue-700' : 'bg-gray-100 text-gray-600'

  // Normalise une saisie ; renvoie '' si vide ou déjà présente. Tags → minuscules ; mots-clés → casse conservée.
  const normaliser = (brut: string, liste: string[]): string => {
    const v = estTag ? brut.trim().toLowerCase() : brut.trim()
    return !v || liste.includes(v) ? '' : v
  }

  // Ajoute la saisie courante à la liste (via `+` ou Entrée). Renvoie la liste résultante.
  const ajouterTag = (): string[] => {
    const v = normaliser(nouveauTag, localTags)
    if (!v) return localTags
    const suivante = [...localTags, v]
    setLocalTags(suivante)
    setNouveauTag('')
    return suivante
  }

  const supprimerTag = (tag: string) => setLocalTags(t => t.filter(x => x !== tag))

  const sauvegarder = async () => {
    // ⚠️ Flush de la saisie EN COURS : sans ça, taper un tag puis cliquer « Sauvegarder »
    // (sans faire « + » d'abord) le perdait silencieusement — bug remonté par l'utilisateur.
    const aEnvoyer = ajouterTag()
    setSaving(true)
    try {
      const payload = estTag ? { tags: aEnvoyer } : { mots_cles: aEnvoyer }
      const meta = await documentsApi.patchMetadata(documentId, payload)
      onUpdate?.((estTag ? meta.tags : meta.mots_cles) ?? aEnvoyer)
      setEditing(false)
      toast.success(estTag ? 'Tags mis à jour' : 'Mots-clés mis à jour')
    } catch {
      toast.error(`Erreur mise à jour des ${estTag ? 'tags' : 'mots-clés'}`)
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
        {tags.map(tag => (
          <span key={tag} className={clsx('flex items-center gap-1 text-xs px-2 py-0.5 rounded-full', chipClass)}>
            <Tag size={9} />{tag}
          </span>
        ))}
        {tags.length === 0 && <span className="text-xs text-gray-400">Aucun {libelle}</span>}
        {!readonly && (
          <button type="button" onClick={() => { setLocalTags(tags); setEditing(true) }}
            className="text-xs px-2 py-0.5 border border-dashed border-gray-300 text-gray-400 rounded-full hover:border-blue-400 hover:text-blue-500 transition-colors">
            <Plus size={10} className="inline" /> Modifier
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {/* Valeurs actuelles avec bouton supprimer */}
      <div className="flex flex-wrap gap-1">
        {localTags.map(tag => (
          <span key={tag} className={clsx('flex items-center gap-1 text-xs px-2 py-0.5 rounded-full', chipClass)}>
            <Tag size={9} />{tag}
            <button type="button" onClick={() => supprimerTag(tag)} className="hover:text-red-500"><X size={9} /></button>
          </span>
        ))}
      </div>

      {/* Ajout */}
      <div className="flex gap-1">
        <input
          type="text"
          value={nouveauTag}
          onChange={e => setNouveauTag(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); ajouterTag() } }}
          placeholder={`Nouveau ${libelle}…`}
          className="flex-1 text-xs border border-gray-200 rounded-md px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
          autoFocus
        />
        <button type="button" onClick={ajouterTag} disabled={!nouveauTag.trim()}
          className="text-xs px-2 py-1 bg-gray-100 hover:bg-gray-200 rounded-md disabled:opacity-40">
          <Plus size={12} />
        </button>
      </div>

      {/* Actions */}
      <div className="flex gap-2">
        <button type="button" onClick={sauvegarder} disabled={saving}
          className={clsx('flex items-center gap-1 text-xs px-3 py-1.5 rounded-md transition-colors',
            saving ? 'bg-gray-100 text-gray-400' : 'bg-blue-600 text-white hover:bg-blue-700')}>
          <Check size={11} />{saving ? 'Sauvegarde…' : 'Sauvegarder'}
        </button>
        <button type="button" onClick={annuler} className="text-xs px-3 py-1.5 rounded-md text-gray-500 hover:bg-gray-100">
          Annuler
        </button>
      </div>
    </div>
  )
}
