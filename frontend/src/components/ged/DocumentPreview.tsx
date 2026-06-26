/**
 * DocumentPreview — Aperçu d'un document + actions
 * ================================================
 * Le navigateur ne peut PAS lancer l'explorateur Windows ni le logiciel associé.
 * On fournit donc : aperçu intégré (PDF / image / texte), téléchargement de
 * l'original, et « copier le chemin » (UNC) à coller dans l'explorateur.
 */
import { useEffect, useState } from 'react'
import { X, Download, Copy, ExternalLink, Loader2, FileQuestion } from 'lucide-react'
import { documentsApi } from '../../api'
import { useToast } from '../common/Toast'
import type { Document } from '../../types'

const IMAGES = new Set(['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg'])
const IMAGES_NON_WEB = new Set(['heic', 'heif', 'tiff', 'tif'])  // non rendus par le navigateur
const TEXTE = new Set(['txt', 'md', 'csv', 'log', 'json', 'xml', 'yaml', 'yml', 'ini'])
const TEXTE_EXTRAIT = new Set(['docx', 'xlsx', 'pptx', 'ppsx', 'doc', 'xls', 'ppt', 'odt', 'ods'])

export default function DocumentPreview({ doc, onClose }: { doc: Document; onClose: () => void }) {
  const toast = useToast()
  const ext = (doc.extension || '').toLowerCase()
  const url = documentsApi.fileUrl(doc.id)
  const [texte, setTexte] = useState<string | null>(null)
  const [loadingTexte, setLoadingTexte] = useState(false)

  const besoinTexte = TEXTE.has(ext) || TEXTE_EXTRAIT.has(ext)

  useEffect(() => {
    if (!besoinTexte) return
    setLoadingTexte(true)
    documentsApi.getText(doc.id)
      .then(r => setTexte(r.texte))
      .catch(() => setTexte(''))
      .finally(() => setLoadingTexte(false))
  }, [doc.id, besoinTexte])

  // Fermer sur Échap
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const copier = async () => {
    const chemin = doc.chemin_copie || doc.chemin
    try {
      await navigator.clipboard.writeText(chemin)
      toast.success('Chemin copié — collez-le dans l\'explorateur')
    } catch {
      toast.error('Copie impossible (presse-papiers refusé)')
    }
  }

  const telecharger = () => {
    const a = document.createElement('a')
    a.href = documentsApi.fileUrl(doc.id, true)
    a.download = doc.nom
    a.click()
  }

  const apercu = () => {
    if (ext === 'pdf') {
      return <iframe src={url} title={doc.nom} className="w-full h-full border-0" />
    }
    if (IMAGES.has(ext)) {
      return (
        <div className="w-full h-full flex items-center justify-center bg-gray-100 overflow-auto">
          <img src={url} alt={doc.nom} className="max-w-full max-h-full object-contain" />
        </div>
      )
    }
    if (besoinTexte) {
      if (loadingTexte) return <CenterMsg><Loader2 size={18} className="animate-spin" /> Chargement du texte…</CenterMsg>
      if (!texte) return <Indispo doc={doc} onTelecharger={telecharger} note="Aucun texte extrait disponible." />
      return (
        <pre className="w-full h-full overflow-auto p-4 text-xs whitespace-pre-wrap break-words bg-white text-gray-800 font-mono">
          {texte}
        </pre>
      )
    }
    return (
      <Indispo
        doc={doc}
        onTelecharger={telecharger}
        note={IMAGES_NON_WEB.has(ext)
          ? `Les fichiers ${ext.toUpperCase()} ne s'affichent pas dans le navigateur.`
          : 'Aperçu intégré non disponible pour ce format.'}
      />
    )
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* En-tête */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200">
          <span className="text-sm font-medium truncate flex-1" title={doc.nom}>{doc.nom}</span>
          <span className="text-xs text-gray-400 shrink-0">{ext.toUpperCase()}</span>
          <div className="flex items-center gap-1 shrink-0">
            <button onClick={copier} title="Copier le chemin (UNC)" className="p-1.5 text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded">
              <Copy size={16} />
            </button>
            <a href={url} target="_blank" rel="noreferrer" title="Ouvrir dans un onglet" className="p-1.5 text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded">
              <ExternalLink size={16} />
            </a>
            <button onClick={telecharger} title="Télécharger l'original" className="p-1.5 text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded">
              <Download size={16} />
            </button>
            <button onClick={onClose} title="Fermer" className="p-1.5 text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded">
              <X size={18} />
            </button>
          </div>
        </div>
        {/* Corps */}
        <div className="flex-1 overflow-hidden rounded-b-lg">{apercu()}</div>
      </div>
    </div>
  )
}

function CenterMsg({ children }: { children: React.ReactNode }) {
  return <div className="w-full h-full flex items-center justify-center gap-2 text-sm text-gray-500">{children}</div>
}

function Indispo({ doc, onTelecharger, note }: { doc: Document; onTelecharger: () => void; note: string }) {
  return (
    <div className="w-full h-full flex flex-col items-center justify-center gap-3 text-gray-400 p-6 text-center">
      <FileQuestion size={44} strokeWidth={1} />
      <p className="text-sm">{note}</p>
      <button onClick={onTelecharger} className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
        <Download size={15} /> Télécharger « {doc.nom} »
      </button>
    </div>
  )
}
