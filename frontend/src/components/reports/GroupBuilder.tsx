/**
 * GroupBuilder — Construction des groupes pour le rapport comparatif.
 * Chaque groupe = un candidat / une société + ses documents sélectionnés.
 * Supporte le chargement automatique depuis les tags dossier.
 */
import { useEffect, useState } from 'react'
import { Plus, Trash2, ChevronDown, ChevronUp, FileText, Search, FolderOpen, ArrowRight, X } from 'lucide-react'
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
  const [deplacerDocId, setDeplacerDocId] = useState<string | null>(null)
  const [chargement, setChargement] = useState(false)

  const chargerDocuments = () =>
    documentsApi.list({ page_size: 500 }).then(r => setDocuments(r.documents))

  useEffect(() => { chargerDocuments() }, [])

  // Auto-charger les groupes depuis les tags dossier
  const chargerDepuisDossiers = async () => {
    setChargement(true)
    const data = await documentsApi.list({ page_size: 500 })
    setDocuments(data.documents)

    const parTag = new Map<string, string[]>()
    for (const doc of data.documents) {
      const tags: string[] = (doc as Document & { tags?: string[] }).tags ?? []
      if (tags.length > 0) {
        const tag = tags[0]  // Le premier tag = tag dossier
        if (!parTag.has(tag)) parTag.set(tag, [])
        parTag.get(tag)!.push(doc.id)
      }
    }

    if (parTag.size === 0) {
      setChargement(false)
      return
    }

    const nouveauxGroupes: GroupeComparatif[] = []
    for (const [nom, document_ids] of parTag) {
      // Ne pas écraser un groupe existant avec le même nom
      const existeDeja = groupes.some(g => g.nom === nom)
      if (!existeDeja) {
        nouveauxGroupes.push({ id: genId(), nom, document_ids })
      }
    }
    onChange([...groupes, ...nouveauxGroupes])
    setChargement(false)
  }

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

  // Déplacer un doc d'un groupe vers un autre
  const deplacerVers = (docId: string, versGroupeId: string) => {
    onChange(groupes.map(g => {
      if (g.document_ids.includes(docId) && g.id !== versGroupeId) {
        return { ...g, document_ids: g.document_ids.filter(d => d !== docId) }
      }
      if (g.id === versGroupeId && !g.document_ids.includes(docId)) {
        return { ...g, document_ids: [...g.document_ids, docId] }
      }
      return g
    }))
    setDeplacerDocId(null)
  }

  const retirerDoc = (groupeId: string, docId: string) => {
    onChange(groupes.map(g =>
      g.id === groupeId ? { ...g, document_ids: g.document_ids.filter(d => d !== docId) } : g
    ))
  }

  const docsFiltres = (groupeId: string) => {
    const q = (recherche[groupeId] || '').toLowerCase()
    return documents.filter(d => !q || d.nom.toLowerCase().includes(q))
  }

  const getDoc = (id: string) => documents.find(d => d.id === id)

  return (
    <div className="space-y-2">
      {/* Bouton chargement automatique depuis les tags dossier */}
      <button
        type="button"
        onClick={chargerDepuisDossiers}
        disabled={chargement}
        className="w-full flex items-center justify-center gap-1.5 py-1.5 bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-500 hover:bg-blue-50 hover:border-blue-200 hover:text-blue-600 transition-colors"
      >
        <FolderOpen size={12} />
        {chargement ? 'Chargement…' : 'Charger les groupes depuis les dossiers importés'}
      </button>

      {/* Groupes */}
      {groupes.map((groupe, idx) => {
        const expanded = expandedId === groupe.id
        const nbDocs = groupe.document_ids.length
        const docsGroupe = groupe.document_ids.map(id => getDoc(id)).filter(Boolean) as Document[]

        return (
          <div key={groupe.id} className="border border-gray-200 rounded-lg overflow-hidden">
            {/* En-tête */}
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
                aria-label={expanded ? 'Réduire' : 'Voir / ajouter des documents'}
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
              <div className="border-t border-gray-100 p-2 space-y-2">

                {/* Docs du groupe avec actions déplacer/retirer */}
                {docsGroupe.length > 0 && (
                  <div className="space-y-0.5">
                    {docsGroupe.map(doc => (
                      <div key={doc.id} className="flex items-center gap-1.5 text-xs px-2 py-1 bg-blue-50 rounded group">
                        <FileText size={11} className="text-blue-400 shrink-0" />
                        <span className="flex-1 truncate text-blue-700">{doc.nom}</span>

                        {/* Déplacer vers un autre groupe */}
                        {deplacerDocId === doc.id ? (
                          <div className="flex items-center gap-1 ml-auto">
                            {groupes.filter(g => g.id !== groupe.id).map(g => (
                              <button
                                key={g.id}
                                type="button"
                                onClick={() => deplacerVers(doc.id, g.id)}
                                className="text-xs px-1.5 py-0.5 bg-white border border-blue-200 rounded text-blue-600 hover:bg-blue-100 max-w-[80px] truncate"
                                title={g.nom || 'Groupe sans nom'}
                              >
                                {g.nom || `Groupe ${groupes.indexOf(g) + 1}`}
                              </button>
                            ))}
                            <button
                              type="button"
                              title="Annuler"
                              onClick={() => setDeplacerDocId(null)}
                              className="text-gray-400 hover:text-gray-600"
                            >
                              <X size={11} />
                            </button>
                          </div>
                        ) : (
                          <div className="ml-auto flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                            {groupes.length > 1 && (
                              <button
                                type="button"
                                title="Déplacer vers un autre groupe"
                                onClick={() => setDeplacerDocId(doc.id)}
                                className="text-gray-400 hover:text-blue-500"
                              >
                                <ArrowRight size={11} />
                              </button>
                            )}
                            <button
                              type="button"
                              title="Retirer de ce groupe"
                              onClick={() => retirerDoc(groupe.id, doc.id)}
                              className="text-gray-400 hover:text-red-500"
                            >
                              <X size={11} />
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {/* Séparateur */}
                {docsGroupe.length > 0 && (
                  <p className="text-xs text-gray-400 px-1">Ajouter des documents :</p>
                )}

                {/* Sélecteur de documents à ajouter */}
                <div className="relative">
                  <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    type="text"
                    value={recherche[groupe.id] || ''}
                    onChange={e => setRecherche(r => ({ ...r, [groupe.id]: e.target.value }))}
                    placeholder="Rechercher un document…"
                    className="w-full pl-6 pr-2 py-1 text-xs border border-gray-200 rounded bg-white outline-none focus:border-blue-300"
                  />
                </div>
                <div className="max-h-36 overflow-y-auto space-y-0.5">
                  {docsFiltres(groupe.id)
                    .filter(d => !groupe.document_ids.includes(d.id))
                    .map(doc => (
                      <label
                        key={doc.id}
                        className="flex items-center gap-2 px-2 py-1 rounded cursor-pointer text-xs hover:bg-gray-50 text-gray-600"
                      >
                        <input
                          type="checkbox"
                          checked={false}
                          onChange={() => toggleDocument(groupe.id, doc.id)}
                          className="accent-blue-600 shrink-0"
                        />
                        <FileText size={11} className="shrink-0 text-gray-400" />
                        <span className="truncate">{doc.nom}</span>
                        {((doc as Document & { tags?: string[] }).tags ?? []).length > 0 && (
                          <span className="ml-auto shrink-0 text-gray-300 text-xs truncate max-w-[60px]">
                            {((doc as Document & { tags?: string[] }).tags ?? [])[0]}
                          </span>
                        )}
                      </label>
                    ))}
                  {docsFiltres(groupe.id).filter(d => !groupe.document_ids.includes(d.id)).length === 0 && (
                    <p className="text-xs text-gray-400 text-center py-2">Tous les documents sont déjà dans ce groupe</p>
                  )}
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
