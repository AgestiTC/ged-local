/**
 * DocumentLinks — liens validés d'un document (BC ↔ facture…)
 * ===========================================================
 * Affiché dans la fiche document (DocumentCard). Liste les documents **liés** (liens
 * validés partageant une référence), avec la référence et la nature du lien. Un clic
 * ouvre la fiche du document lié (si le parent fournit `onOpen`). Alimenté par
 * `GET /links/document/{id}` — géré dans la page « Liens ».
 */
import { useEffect, useState } from 'react'
import { Link2, FileText, Loader2 } from 'lucide-react'
import { linksApi, type DocumentLink, type LinkedDoc } from '../../api'

const TYPE_LABEL: Record<string, string> = {
  bc_facture: 'BC ↔ facture',
  reference: 'même réf.',
  manuel: 'manuel',
}

export default function DocumentLinks({ documentId, onOpen }: {
  documentId: string
  onOpen?: (id: string) => void
}) {
  const [liens, setLiens] = useState<DocumentLink[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let vivant = true
    setLoading(true)
    linksApi.forDocument(documentId)
      .then(r => { if (vivant) setLiens(r.liens) })
      .catch(() => { if (vivant) setLiens([]) })
      .finally(() => { if (vivant) setLoading(false) })
    return () => { vivant = false }
  }, [documentId])

  // Le « bon » document d'un lien = celui qui n'est pas le document courant.
  const autre = (l: DocumentLink): LinkedDoc =>
    l.source.id === documentId ? l.cible : l.source

  if (loading) {
    return <p className="text-xs text-gray-400 flex items-center gap-1"><Loader2 size={11} className="animate-spin" /> Chargement…</p>
  }
  if (liens.length === 0) {
    return <p className="text-xs text-gray-400">Aucun document lié. Propose des liens dans « Liens ».</p>
  }

  return (
    <ul className="space-y-1.5">
      {liens.map(l => {
        const a = autre(l)
        const cliquable = a.existe && !!onOpen
        return (
          <li key={l.id}>
            <button
              type="button"
              disabled={!cliquable}
              onClick={() => cliquable && onOpen!(a.id)}
              title={cliquable ? 'Ouvrir la fiche du document lié' : a.chemin ?? a.nom}
              className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-md border text-xs transition-colors ${
                cliquable ? 'border-gray-200 hover:bg-blue-50 hover:border-blue-200 cursor-pointer' : 'border-gray-100 cursor-default'
              }`}
            >
              <Link2 size={12} className="text-blue-500 shrink-0" />
              <FileText size={12} className="text-gray-400 shrink-0" />
              <span className="min-w-0 flex-1 truncate font-medium text-gray-700">{a.nom}</span>
              <span className="shrink-0 px-1.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">
                {TYPE_LABEL[l.type_lien] ?? l.type_lien}
              </span>
              {l.reference && <span className="shrink-0 font-mono text-gray-400">{l.reference}</span>}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
