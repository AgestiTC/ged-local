/**
 * SourcesGed — documents de la GED sur lesquels une réponse du chat s'appuie, avec les mêmes
 * actions que les cartes de la page GED : Aperçu, Fiche, Télécharger, Copier le chemin.
 *
 * Le chat ne reçoit que {id, nom} (en-tête X-Ged-Sources, borné en taille) : le chemin à copier
 * est demandé à la volée (`documentsApi.get`) plutôt que d'alourdir l'en-tête.
 */
import { useState } from 'react'
import { Copy, Database, Download, Eye, FileText } from 'lucide-react'
import { documentsApi } from '../../api'
import type { GedSource } from '../../api'
import type { Document } from '../../types'
import { copierTexte } from '../../utils/clipboard'
import { useToast } from '../common/Toast'
import DocumentCard from '../ged/DocumentCard'
import DocumentPreview from '../ged/DocumentPreview'

function extensionDe(nom: string): string {
  const i = nom.lastIndexOf('.')
  return i > 0 ? nom.slice(i + 1).toLowerCase() : ''
}

const BOUTON = 'flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed'

export default function SourcesGed({ sources }: { sources: GedSource[] }) {
  const toast = useToast()
  const [apercu, setApercu] = useState<Document | null>(null)
  const [ficheId, setFicheId] = useState<string | null>(null)

  const telecharger = (id: string, nom: string) => {
    const a = document.createElement('a'); a.href = documentsApi.fileUrl(id, true); a.download = nom; a.click()
  }
  const copierChemin = async (id: string) => {
    try {
      const doc = await documentsApi.get(id)
      const chemin = doc.chemin_copie || doc.chemin
      if (!chemin) { toast.error('Chemin indisponible'); return }
      if (await copierTexte(chemin)) toast.success('Chemin copié'); else toast.error('Copie impossible')
    } catch {
      toast.error('Document introuvable')
    }
  }

  return (
    <div className="mt-1 px-1 text-[11px] text-emerald-700" data-testid="chat-sources-ged">
      <p className="flex items-center gap-1">
        <Database size={11} className="shrink-0" /> Appuyé sur vos documents :
      </p>
      <ul className="mt-0.5 space-y-0.5">
        {sources.map((s, i) => {
          const id = s.id
          const sansId = !id
          return (
            <li key={id ?? `${s.nom}-${i}`}
              className="flex flex-wrap items-center gap-x-1 rounded-md bg-emerald-50/60 border border-emerald-100 pl-2 pr-1 py-0.5">
              <span className="font-medium text-gray-700 break-all mr-1">{s.nom}</span>
              <button type="button" title="Aperçu du fichier" disabled={sansId}
                onClick={() => id && setApercu({ id, nom: s.nom, extension: extensionDe(s.nom), chemin: '', chemin_copie: '' } as Document)}
                className={`${BOUTON} text-blue-600`}>
                <Eye size={12} /> Aperçu
              </button>
              <button type="button" title="Fiche IA" disabled={sansId}
                onClick={() => id && setFicheId(id)}
                className={`${BOUTON} text-violet-600`}>
                <FileText size={12} /> Fiche
              </button>
              <button type="button" title="Télécharger" aria-label={`Télécharger ${s.nom}`} disabled={sansId}
                onClick={() => id && telecharger(id, s.nom)}
                className={`${BOUTON} text-gray-500`}>
                <Download size={12} />
              </button>
              <button type="button" title="Copier le chemin (UNC)" aria-label={`Copier le chemin de ${s.nom}`} disabled={sansId}
                onClick={() => id && copierChemin(id)}
                className={`${BOUTON} text-gray-500`}>
                <Copy size={12} />
              </button>
            </li>
          )
        })}
      </ul>

      {apercu && <DocumentPreview doc={apercu} onClose={() => setApercu(null)} />}

      {/* Fiche : panneau latéral par-dessus la page, comme dans la GED. */}
      {ficheId && (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={() => setFicheId(null)}>
          <div className="w-80 max-w-full h-full bg-white shadow-xl overflow-hidden text-sm text-gray-800"
            onClick={e => e.stopPropagation()}>
            <DocumentCard documentId={ficheId} onClose={() => setFicheId(null)} onOpenDocument={setFicheId} />
          </div>
        </div>
      )}
    </div>
  )
}
