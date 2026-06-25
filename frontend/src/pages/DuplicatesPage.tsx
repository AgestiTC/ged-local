/**
 * Page Doublons — Matothèque
 * ==========================
 * Scanne le volume des documents, affiche les fichiers en double groupés par
 * contenu, avec une case à cocher devant chacun. Le fichier « à garder » est
 * pré-décoché (badge), les autres pré-cochés. Le déplacement vers
 * DOUBLON-MATOTEQUE demande une confirmation explicite.
 */
import { useMemo, useState } from 'react'
import { Copy, FolderInput, Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import { duplicatesApi, type DuplicatesResponse } from '../api'
import { useToast } from '../components/common/Toast'

function formatBytes(n?: number) {
  if (!n || n <= 0) return '0 o'
  const u = ['o', 'Ko', 'Mo', 'Go', 'To']
  const i = Math.floor(Math.log(n) / Math.log(1024))
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
}

export default function DuplicatesPage() {
  const toast = useToast()
  const [data, setData] = useState<DuplicatesResponse | null>(null)
  const [scanning, setScanning] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [moving, setMoving] = useState(false)

  const scan = async () => {
    setScanning(true)
    setData(null)
    setSelected(new Set())
    try {
      const res = await duplicatesApi.scan()
      setData(res)
      // Pré-cocher tous les fichiers SAUF celui à garder
      const pre = new Set<string>()
      res.groupes.forEach(g => g.fichiers.forEach(f => { if (!f.garder) pre.add(f.chemin) }))
      setSelected(pre)
      if (res.nb_groupes === 0) toast.info('Aucun doublon trouvé 🎉')
    } catch {
      toast.error('Échec du scan des doublons')
    } finally {
      setScanning(false)
    }
  }

  const toggle = (chemin: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(chemin) ? next.delete(chemin) : next.add(chemin)
      return next
    })
  }

  const octetsSelection = useMemo(() => {
    if (!data) return 0
    let total = 0
    data.groupes.forEach(g => g.fichiers.forEach(f => { if (selected.has(f.chemin)) total += f.taille_octets }))
    return total
  }, [data, selected])

  const confirmQuarantine = async () => {
    setMoving(true)
    try {
      const res = await duplicatesApi.quarantine([...selected])
      if (res.nb_erreurs > 0) {
        toast.error(`${res.nb_deplaces} déplacé(s), ${res.nb_erreurs} en erreur`)
      } else {
        toast.success(`${res.nb_deplaces} doublon(s) déplacé(s) vers ${res.dossier_quarantaine}`)
      }
      setConfirmOpen(false)
      await scan()  // rafraîchit la liste
    } catch {
      toast.error('Échec du déplacement')
    } finally {
      setMoving(false)
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* En-tête */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Copy size={20} className="text-blue-600" /> Doublons
          </h1>
          <p className="text-sm text-gray-500">
            Fichiers en double sur le serveur. Les fichiers cochés seront <strong>déplacés</strong> vers
            le dossier de quarantaine — jamais supprimés.
          </p>
        </div>
        <button
          onClick={scan}
          disabled={scanning}
          className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {scanning ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          {scanning ? 'Scan en cours…' : (data ? 'Re-scanner' : 'Lancer le scan')}
        </button>
      </div>

      {/* État initial */}
      {!data && !scanning && (
        <div className="text-center text-gray-400 py-20">
          <Copy size={40} strokeWidth={1} className="mx-auto mb-3" />
          <p>Lance un scan pour détecter les fichiers en double.</p>
        </div>
      )}

      {scanning && (
        <div className="text-center text-gray-500 py-20">
          <Loader2 size={32} className="animate-spin mx-auto mb-3" />
          <p>Analyse du volume (regroupement par taille puis empreinte)…</p>
        </div>
      )}

      {/* Résumé */}
      {data && data.nb_groupes > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4 text-sm text-blue-800 flex flex-wrap gap-x-6 gap-y-1">
          <span><strong>{data.nb_groupes}</strong> groupe(s)</span>
          <span><strong>{data.nb_fichiers}</strong> fichier(s) en double</span>
          <span>Espace récupérable : <strong>{formatBytes(data.octets_recuperables)}</strong></span>
          <span>Quarantaine : <code className="bg-white px-1 rounded">{data.dossier_quarantaine}/</code></span>
        </div>
      )}

      {data && data.nb_groupes === 0 && !scanning && (
        <div className="text-center text-green-600 py-20">
          <ShieldCheck size={40} strokeWidth={1} className="mx-auto mb-3" />
          <p>Aucun doublon détecté. 🎉</p>
        </div>
      )}

      {/* Groupes */}
      <div className="space-y-4 pb-24">
        {data?.groupes.map(g => (
          <div key={g.hash} className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="bg-gray-50 px-4 py-2 text-xs text-gray-500 flex justify-between">
              <span>{g.fichiers.length} copies · {formatBytes(g.taille_octets)} chacune</span>
              <span className="font-mono">#{g.hash.slice(0, 10)}</span>
            </div>
            <ul className="divide-y divide-gray-100">
              {g.fichiers.map(f => (
                <li key={f.chemin} className="flex items-center gap-3 px-4 py-2 hover:bg-gray-50">
                  <input
                    type="checkbox"
                    checked={selected.has(f.chemin)}
                    onChange={() => toggle(f.chemin)}
                    className="w-4 h-4 accent-blue-600 shrink-0"
                    aria-label={`Sélectionner ${f.nom}`}
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm truncate">{f.nom}</p>
                    <p className="text-xs text-gray-400 truncate">{f.relatif}</p>
                  </div>
                  {f.garder && (
                    <span className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded-full shrink-0">
                      à garder
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Barre d'action flottante */}
      {data && selected.size > 0 && (
        <div className="fixed bottom-0 left-52 right-0 bg-white border-t border-gray-200 px-6 py-3 flex items-center justify-between shadow-lg">
          <span className="text-sm text-gray-600">
            <strong>{selected.size}</strong> fichier(s) sélectionné(s) · {formatBytes(octetsSelection)}
          </span>
          <button
            onClick={() => setConfirmOpen(true)}
            className="flex items-center gap-2 px-4 py-2 bg-amber-600 text-white text-sm rounded-lg hover:bg-amber-700"
          >
            <FolderInput size={16} /> Déplacer la sélection
          </button>
        </div>
      )}

      {/* Modal de confirmation */}
      {confirmOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5">
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2">
              <FolderInput size={18} className="text-amber-600" /> Confirmer le déplacement
            </h2>
            <p className="text-sm text-gray-600 mb-4">
              <strong>{selected.size}</strong> fichier(s) ({formatBytes(octetsSelection)}) vont être
              <strong> déplacés</strong> vers le dossier{' '}
              <code className="bg-gray-100 px-1 rounded">{data?.dossier_quarantaine}/</code>.
              Les fichiers ne sont <strong>pas supprimés</strong> : tu pourras les vérifier puis les
              effacer manuellement.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmOpen(false)}
                disabled={moving}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50"
              >
                Annuler
              </button>
              <button
                onClick={confirmQuarantine}
                disabled={moving}
                className="flex items-center gap-2 px-4 py-2 bg-amber-600 text-white text-sm rounded-lg hover:bg-amber-700 disabled:opacity-50"
              >
                {moving ? <Loader2 size={16} className="animate-spin" /> : <FolderInput size={16} />}
                Déplacer {selected.size} fichier(s)
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
