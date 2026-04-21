/**
 * GroupBuilder — Construction des groupes pour le rapport comparatif.
 * Chaque groupe = un candidat / une société + ses documents sélectionnés.
 */
import { useEffect, useState } from 'react'
import { Plus, Trash2, ChevronDown, ChevronUp, FileText, Search } from 'lucide-react'
import { clsx } from 'clsx'
import { documentsApi } from '../../api'
import type { Document, GroupeComparatif } from '../../types'

const genId = () =>
  typeof crypto !== 'undefined' && crypto.randomUUID
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36)

interface Props {
  groupes: GroupeComparatif[]
  onChange: (groupes: GroupeComparatif[]) => void
}

export default function GroupBuilder({ groupes, onChange }: Props) {
  const [documents, setDocuments] = useState<Document[]>([])
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [recherche, setRecherche] = useState<Record<string, string>>({})

  useEffect(() => {
    documentsApi.list({ page_size: 500 }).then(r => setDocuments(r.documents))
  }, [])

  const ajouterGroupe = () => {
    const nouveau: GroupeComparatif = { id: genId(), nom: '', document_ids: [] }
    onChange([...groupes, nouveau])
    setExpandedId(nouveau.id)
  }

  const supprimerGroupe = (id: string) => {
    onChange(groupes.filter(g => g.id !== id))
    if (expandedId === id) setExpandedId(null)
  }

  const mettreAJourNom = (id: string, nom: string) => {
    onChange(groupes.map(g => g.id === id ? { ...g, nom } : g))
  }

  const toggleDocument = (groupeId: string, docId: string) => {
    onChange(groupes.map(g => {
      if (g.id !== groupeId) return g
      const ids = g.document_ids.includes(docId)
        ? g.document_ids.filter(d => d !== docId)
        : [...g.document_ids, docId]
      return { ...g, document_ids: ids }
    }))
  }

  const docsFiltres = (groupeId: string) => {
    const q = (recherche[groupeId] || '').toLowerCase()
    return documents.filter(d => !q || d.nom.toLowerCase().includes(q))
  }

  return (
    <div className="space-y-2">
      {groupes.map((groupe, idx) => {
        const expanded = expandedId === groupe.id
        const nbDocs = groupe.document_ids.length
        return (
          <div key={groupe.id} className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="flex items-center gap-2 p-2.5 bg-gray-50">
              <span className="text-xs font-bold text-gray-400 w-5 text-center shrink-0">{idx + 1}</span>
              <input
                type="text"
                value={groupe.nom}
                onChange={e => mettreAJourNom(groupe.id, e.target.value)}
                placeholder="Nom du candidat / société…"
                className="flex-1 text-sm border-0 bg-transparent outline-none font-medium text-gray-700 placeholder-gray-400"
              />
              <span className={clsx(
                'text-xs px-1.5 py-0.5 rounded-full shrink-0',
                nbDocs > 0 ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-400'
              )}>
                {nbDocs} doc{nbDocs !== 1 ? 's' : ''}
              </span>
              <button
                type="button"
                aria-label={expanded ? 'Réduire' : 'Sélectionner des documents'}
                onClick={() => setExpandedId(expanded ? null : groupe.id)}
                className="text-gray-400 hover:text-gray-600 shrink-0"
              >
                {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
              <button
                type="button"
                aria-label="Supprimer ce groupe"
                onClick={() => supprimerGroupe(groupe.id)}
                className="text-red-300 hover:text-red-500 shrink-0"
              >
                <Trash2 size={13} />
              </button>
            </div>

            {expanded && (
              <div className="border-t border-gray-100 p-2">
                <div className="relative mb-2">
                  <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    value={recherche[groupe.id] || ''}
                    onChange={e => setRecherche(r => ({ ...r, [groupe.id]: e.target.value }))}
                    placeholder="Filtrer les documents…"
                    className="w-full pl-6 pr-2 py-1 text-xs border border-gray-200 rounded bg-white outline-none focus:border-blue-300"
                  />
                </div>
                <div className="max-h-40 overflow-y-auto space-y-0.5">
                  {docsFiltres(groupe.id).length === 0 && (
                    <p className="text-xs text-gray-400 text-center py-3">Aucun document</p>
                  )}
                  {docsFiltres(groupe.id).map(doc => {
                    const selected = groupe.document_ids.includes(doc.id)
                    return (
                      <label
                        key={doc.id}
                        className={clsx(
                          'flex items-center gap-2 px-2 py-1 rounded cursor-pointer text-xs transition-colors',
                          selected ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-50 text-gray-600'
                        )}
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          onChange={() => toggleDocument(groupe.id, doc.id)}
                          className="accent-blue-600 shrink-0"
                        />
                        <FileText size={11} className="shrink-0 text-gray-400" />
                        <span className="truncate">{doc.nom}</span>
                      </label>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )
      })}

      <button
        type="button"
        onClick={ajouterGroupe}
        className="w-full flex items-center justify-center gap-1.5 py-2 border-2 border-dashed border-gray-200 rounded-lg text-xs text-gray-400 hover:border-blue-300 hover:text-blue-500 transition-colors"
      >
        <Plus size={13} />
        Ajouter un candidat / société
      </button>
    </div>
  )
}
