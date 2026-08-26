/**
 * Page Doublons — Matothèque
 * ==========================
 * Deux modes :
 *  - « Fichiers indexés » (défaut) : doublons parmi les documents INDEXÉS —
 *    contenu identique (hash) + quasi-doublons sémantiques (IA / embeddings),
 *    scopés par dossier (explorateur). Tableau fichier | source, clic-ligne =
 *    sélection, envoi à la corbeille NAS (A-SUPPRIMER-MATOTEQUE, réversible).
 *  - « Scan disque » : ancien scan du volume local (regroupement par empreinte).
 */
import { useMemo, useState } from 'react'
import { Copy, FolderInput, Loader2, RefreshCw, ShieldCheck, Database, FolderSearch, Folder, Trash2, Sparkles, Info, Eye } from 'lucide-react'
import { clsx } from 'clsx'
import {
  duplicatesApi, corbeilleApi, sourcesApi, documentsApi,
  type DuplicatesResponse, type IndexedDupResponse, type Source, type BlurryImage,
} from '../api'
import SmbFolderPicker from '../components/ged/SmbFolderPicker'
import DocumentPreview from '../components/ged/DocumentPreview'
import { useToast } from '../components/common/Toast'
import type { Document } from '../types'

function formatBytes(n?: number) {
  if (!n || n <= 0) return '0 o'
  const u = ['o', 'Ko', 'Mo', 'Go', 'To']
  const i = Math.floor(Math.log(n) / Math.log(1024))
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
}

export default function DuplicatesPage() {
  const toast = useToast()
  const [onglet, setOnglet] = useState<'indexed' | 'disk' | 'flou'>('indexed')
  return (
    <div className="p-3 sm:p-6 max-w-5xl mx-auto">
      <div className="mb-4">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <Copy size={20} className="text-blue-600" /> Doublons
        </h1>
        <p className="text-sm text-gray-500">
          Repère les fichiers en double — jamais supprimés, déplacés vers la corbeille (réversible).
        </p>
      </div>

      {/* Onglets */}
      <div className="flex gap-1 mb-4 border-b border-gray-200">
        {([
          { k: 'indexed' as const, label: 'Fichiers indexés (hash + IA)' },
          { k: 'disk' as const, label: 'Scan disque' },
          { k: 'flou' as const, label: 'Photos floues' },
        ]).map(o => (
          <button key={o.k} type="button" onClick={() => setOnglet(o.k)}
            className={clsx('px-3 py-2 text-sm border-b-2 -mb-px transition-colors',
              onglet === o.k ? 'border-blue-600 text-blue-700 font-medium' : 'border-transparent text-gray-500 hover:text-gray-700')}>
            {o.label}
          </button>
        ))}
      </div>

      {onglet === 'indexed' ? <IndexedDuplicates toast={toast} />
        : onglet === 'disk' ? <DiskDuplicates toast={toast} />
        : <BlurryImages toast={toast} />}
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Doublons des fichiers INDEXÉS (hash + IA)
// ══════════════════════════════════════════════════════════════════════════════

function IndexedDuplicates({ toast }: { toast: ReturnType<typeof useToast> }) {
  const [sources, setSources] = useState<Source[]>([])
  const [sourceId, setSourceId] = useState('')
  const [prefixe, setPrefixe] = useState('')
  const [prefixeLabel, setPrefixeLabel] = useState('')
  const [showPicker, setShowPicker] = useState(false)
  const [mode, setMode] = useState<'hash' | 'ia' | 'both'>('both')
  const [seuil, setSeuil] = useState(0.92)

  const [data, setData] = useState<IndexedDupResponse | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [apercu, setApercu] = useState<Document | null>(null)   // doc affiché en aperçu (modal)

  useMemo(() => { sourcesApi.list().then(setSources).catch(() => {}) }, [])

  const analyser = async () => {
    setAnalyzing(true); setData(null); setSelected(new Set())
    try {
      const res = await duplicatesApi.indexed({ prefixe: prefixe || undefined, mode, seuil })
      setData(res)
      // Pré-sélection : tout sauf le fichier « à garder » de chaque groupe
      const pre = new Set<string>()
      res.groupes.forEach(g => g.fichiers.forEach(f => { if (!f.garder) pre.add(f.id) }))
      setSelected(pre)
      if (res.nb_groupes === 0) toast.info('Aucun doublon trouvé dans ce périmètre 🎉')
    } catch { toast.error('Analyse impossible') } finally { setAnalyzing(false) }
  }

  const toggle = (id: string) => setSelected(prev => {
    const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n
  })

  // Aperçu : charge le document complet puis ouvre le composant DocumentPreview.
  const ouvrirApercu = async (id: string) => {
    try { setApercu(await documentsApi.get(id)) }
    catch { toast.error('Aperçu impossible (document introuvable ?)') }
  }

  const octetsSelection = useMemo(() => {
    if (!data) return 0
    let t = 0
    data.groupes.forEach(g => g.fichiers.forEach(f => { if (selected.has(f.id)) t += f.taille_octets }))
    return t
  }, [data, selected])

  // Envoi à la corbeille NAS (réversible) — un appel par fichier sélectionné.
  const envoyerCorbeille = async () => {
    setBusy(true)
    let ok = 0, ko = 0
    for (const id of [...selected]) {
      try { await corbeilleApi.envoyer(id); ok++ } catch { ko++ }
    }
    setBusy(false); setConfirmOpen(false)
    ok && toast.success(`${ok} fichier(s) envoyé(s) à la corbeille`)
    ko && toast.error(`${ko} échec(s)`)
    await analyser()
  }

  return (
    <>
      {/* Périmètre + options */}
      <div className="bg-white border border-gray-200 rounded-lg p-3 space-y-3 mb-4">
        <div className="flex items-center gap-2 text-sm text-gray-600 flex-wrap">
          <Database size={15} className="text-blue-500 shrink-0" />
          <span className="shrink-0">Périmètre :</span>
          {prefixe ? (
            <span className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-blue-50 text-blue-700 border border-blue-200 text-xs min-w-0">
              <Folder size={12} className="shrink-0" />
              <span className="truncate font-mono" title={prefixe}>{prefixeLabel}</span>
              <button type="button" onClick={() => { setPrefixe(''); setPrefixeLabel('') }} title="Retirer" className="hover:text-blue-900 shrink-0">✕</button>
            </span>
          ) : (
            <select value={sourceId} onChange={e => setSourceId(e.target.value)}
              title="Source (info) — utilise « Explorer » pour cibler un dossier"
              className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white">
              <option value="">Tout l'index</option>
              {sources.map(s => <option key={s.id} value={s.id}>{s.libelle}{s.hote ? ` (${s.hote})` : ''}</option>)}
            </select>
          )}
          {sources.length > 0 && (
            <button type="button" onClick={() => setShowPicker(v => !v)}
              className="flex items-center gap-1.5 text-xs px-2.5 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 shrink-0">
              <FolderSearch size={14} /> {showPicker ? 'Fermer' : 'Explorer un dossier…'}
            </button>
          )}
        </div>

        {showPicker && sources.length > 0 && (
          <SmbFolderPicker
            source={sources.find(s => s.id === sourceId) ?? sources[0]}
            onPick={(p, label) => { setPrefixe(p); setPrefixeLabel(label); setShowPicker(false) }}
            onClose={() => setShowPicker(false)}
          />
        )}

        <div className="flex items-center gap-3 flex-wrap">
          <label className="flex items-center gap-1.5 text-sm text-gray-600">
            Détection :
            <select value={mode} onChange={e => setMode(e.target.value as 'hash' | 'ia' | 'both')}
              className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white">
              <option value="both">Identique + IA</option>
              <option value="hash">Contenu identique (hash)</option>
              <option value="ia">Quasi-doublons IA</option>
            </select>
          </label>
          {mode !== 'hash' && (
            <label className="flex items-center gap-1.5 text-xs text-gray-500" title="Seuil de similarité sémantique">
              Seuil IA : <strong className="text-gray-700">{Math.round(seuil * 100)}%</strong>
              <input type="range" min={0.80} max={0.99} step={0.01} value={seuil}
                onChange={e => setSeuil(parseFloat(e.target.value))} className="accent-violet-600" />
            </label>
          )}
          <div className="flex-1" />
          <button type="button" onClick={analyser} disabled={analyzing}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {analyzing ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {analyzing ? 'Analyse…' : 'Analyser les doublons'}
          </button>
        </div>
      </div>

      {data?.note && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-2.5 mb-3 text-xs text-amber-800 flex items-start gap-2">
          <Info size={14} className="shrink-0 mt-0.5" /> {data.note}
        </div>
      )}

      {/* Résumé */}
      {data && data.nb_groupes > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4 text-sm text-blue-800 flex flex-wrap gap-x-6 gap-y-1">
          <span><strong>{data.nb_groupes}</strong> groupe(s)</span>
          <span><strong>{data.nb_fichiers}</strong> fichier(s) en double</span>
          <span>Espace récupérable : <strong>{formatBytes(data.octets_recuperables)}</strong></span>
        </div>
      )}

      {data && data.nb_groupes === 0 && !analyzing && (
        <div className="text-center text-green-600 py-16">
          <ShieldCheck size={40} strokeWidth={1} className="mx-auto mb-3" />
          <p>Aucun doublon détecté dans ce périmètre. 🎉</p>
        </div>
      )}

      {!data && !analyzing && (
        <div className="text-center text-gray-400 py-16">
          <Copy size={40} strokeWidth={1} className="mx-auto mb-3" />
          <p>Choisis un périmètre puis lance l'analyse (contenu identique + quasi-doublons IA).</p>
        </div>
      )}

      {/* Tableau des groupes */}
      <div className="space-y-4 pb-24">
        {data?.groupes.map(g => (
          <div key={g.cle} className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="bg-gray-50 px-4 py-2 text-xs flex items-center justify-between gap-2">
              <span className="flex items-center gap-2">
                {g.type === 'hash' ? (
                  <span className="px-1.5 py-0.5 rounded-full bg-green-100 text-green-700 font-medium">Contenu identique</span>
                ) : (
                  <span className="px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 font-medium">Similaire (IA {Math.round(g.score * 100)}%)</span>
                )}
                <span className="text-gray-500">{g.fichiers.length} fichiers</span>
              </span>
              <span className="font-mono text-gray-400">#{g.cle}</span>
            </div>
            {/* En-tête de tableau */}
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-2 px-4 py-1.5 text-[11px] uppercase tracking-wide text-gray-400 border-b border-gray-100">
              <span>Fichier</span><span>Source</span><span className="text-right">Taille</span><span className="text-right">Corbeille</span>
            </div>
            <ul className="divide-y divide-gray-100">
              {g.fichiers.map(f => (
                <li key={f.id}
                  onClick={() => toggle(f.id)}
                  className={clsx('grid grid-cols-[1fr_auto_auto_auto] gap-2 items-center px-4 py-2 cursor-pointer',
                    selected.has(f.id) ? 'bg-amber-50' : 'hover:bg-gray-50')}>
                  <div className="flex items-center gap-2 min-w-0">
                    <input type="checkbox" checked={selected.has(f.id)} onChange={() => toggle(f.id)} onClick={e => e.stopPropagation()}
                      className="w-4 h-4 accent-amber-600 shrink-0" aria-label={`Sélectionner ${f.nom}`} />
                    <span className="text-sm truncate" title={f.chemin}>{f.nom}</span>
                    {f.garder && <span className="text-[10px] px-1.5 py-0.5 bg-green-100 text-green-700 rounded-full shrink-0">à garder</span>}
                  </div>
                  <span className="text-xs text-gray-500 font-mono truncate max-w-[12rem]" title={f.chemin}>{f.source}</span>
                  <span className="text-xs text-gray-400 text-right shrink-0 w-20">{formatBytes(f.taille_octets)}</span>
                  <div className="justify-self-end flex items-center gap-1">
                    <button type="button" title="Aperçu du fichier"
                      onClick={e => { e.stopPropagation(); ouvrirApercu(f.id) }}
                      className="p-1 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded">
                      <Eye size={14} />
                    </button>
                    <button type="button" title="Envoyer ce fichier à la corbeille"
                      onClick={e => { e.stopPropagation(); setSelected(new Set([f.id])); setConfirmOpen(true) }}
                      className="p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded">
                      <Trash2 size={14} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Barre d'action */}
      {data && selected.size > 0 && (
        <div className="fixed bottom-0 left-52 right-0 bg-white border-t border-gray-200 px-6 py-3 flex items-center justify-between shadow-lg z-30">
          <span className="text-sm text-gray-600">
            <strong>{selected.size}</strong> fichier(s) · {formatBytes(octetsSelection)}
          </span>
          <button type="button" onClick={() => setConfirmOpen(true)}
            className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700">
            <Trash2 size={16} /> Envoyer à la corbeille
          </button>
        </div>
      )}

      {/* Aperçu (réutilise le composant DocumentPreview de la GED) */}
      {apercu && <DocumentPreview doc={apercu} onClose={() => setApercu(null)} />}

      {/* Confirmation */}
      {confirmOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => !busy && setConfirmOpen(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2"><Trash2 size={18} className="text-red-600" /> Envoyer à la corbeille</h2>
            <p className="text-sm text-gray-600 mb-4">
              <strong>{selected.size}</strong> fichier(s) vont être déplacés vers
              <strong> A-SUPPRIMER-MATOTEQUE</strong> sur le NAS et retirés de l'index. Les fichiers ne
              sont <strong>pas supprimés</strong> — restaurables depuis la corbeille.
            </p>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setConfirmOpen(false)} disabled={busy}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">Annuler</button>
              <button type="button" onClick={envoyerCorbeille} disabled={busy}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 disabled:opacity-50">
                {busy ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />} Confirmer
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// Scan disque (ancien mode, conservé)
// ══════════════════════════════════════════════════════════════════════════════

function DiskDuplicates({ toast }: { toast: ReturnType<typeof useToast> }) {
  const [data, setData] = useState<DuplicatesResponse | null>(null)
  const [scanning, setScanning] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [moving, setMoving] = useState(false)

  const scan = async () => {
    setScanning(true); setData(null); setSelected(new Set())
    try {
      const res = await duplicatesApi.scan()
      setData(res)
      const pre = new Set<string>()
      res.groupes.forEach(g => g.fichiers.forEach(f => { if (!f.garder) pre.add(f.chemin) }))
      setSelected(pre)
      if (res.nb_groupes === 0) toast.info('Aucun doublon trouvé 🎉')
    } catch { toast.error('Échec du scan des doublons') } finally { setScanning(false) }
  }

  const toggle = (chemin: string) => setSelected(prev => {
    const next = new Set(prev); next.has(chemin) ? next.delete(chemin) : next.add(chemin); return next
  })

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
      res.nb_erreurs > 0
        ? toast.error(`${res.nb_deplaces} déplacé(s), ${res.nb_erreurs} en erreur`)
        : toast.success(`${res.nb_deplaces} doublon(s) déplacé(s) vers ${res.dossier_quarantaine}`)
      setConfirmOpen(false)
      await scan()
    } catch { toast.error('Échec du déplacement') } finally { setMoving(false) }
  }

  return (
    <>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">
          Scan du volume local (regroupement par empreinte). Les cochés sont <strong>déplacés</strong>
          vers la quarantaine — jamais supprimés.
        </p>
        <button onClick={scan} disabled={scanning}
          className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50 shrink-0">
          {scanning ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
          {scanning ? 'Scan en cours…' : (data ? 'Re-scanner' : 'Lancer le scan')}
        </button>
      </div>

      {!data && !scanning && (
        <div className="text-center text-gray-400 py-16">
          <Copy size={40} strokeWidth={1} className="mx-auto mb-3" />
          <p>Lance un scan pour détecter les fichiers en double sur le disque.</p>
        </div>
      )}
      {scanning && (
        <div className="text-center text-gray-500 py-16">
          <Loader2 size={32} className="animate-spin mx-auto mb-3" />
          <p>Analyse du volume (regroupement par taille puis empreinte)…</p>
        </div>
      )}

      {data && data.nb_groupes > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4 text-sm text-blue-800 flex flex-wrap gap-x-6 gap-y-1">
          <span><strong>{data.nb_groupes}</strong> groupe(s)</span>
          <span><strong>{data.nb_fichiers}</strong> fichier(s) en double</span>
          <span>Espace récupérable : <strong>{formatBytes(data.octets_recuperables)}</strong></span>
          <span>Quarantaine : <code className="bg-white px-1 rounded">{data.dossier_quarantaine}/</code></span>
        </div>
      )}
      {data && data.nb_groupes === 0 && !scanning && (
        <div className="text-center text-green-600 py-16">
          <ShieldCheck size={40} strokeWidth={1} className="mx-auto mb-3" />
          <p>Aucun doublon détecté. 🎉</p>
        </div>
      )}

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
                  <input type="checkbox" checked={selected.has(f.chemin)} onChange={() => toggle(f.chemin)}
                    className="w-4 h-4 accent-blue-600 shrink-0" aria-label={`Sélectionner ${f.nom}`} />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm truncate">{f.nom}</p>
                    <p className="text-xs text-gray-400 truncate">{f.relatif}</p>
                  </div>
                  {f.garder && <span className="text-xs px-2 py-0.5 bg-green-100 text-green-700 rounded-full shrink-0">à garder</span>}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {data && selected.size > 0 && (
        <div className="fixed bottom-0 left-52 right-0 bg-white border-t border-gray-200 px-6 py-3 flex items-center justify-between shadow-lg z-30">
          <span className="text-sm text-gray-600"><strong>{selected.size}</strong> fichier(s) · {formatBytes(octetsSelection)}</span>
          <button onClick={() => setConfirmOpen(true)}
            className="flex items-center gap-2 px-4 py-2 bg-amber-600 text-white text-sm rounded-lg hover:bg-amber-700">
            <FolderInput size={16} /> Déplacer la sélection
          </button>
        </div>
      )}

      {confirmOpen && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4" onClick={() => !moving && setConfirmOpen(false)}>
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-bold mb-2 flex items-center gap-2"><FolderInput size={18} className="text-amber-600" /> Confirmer le déplacement</h2>
            <p className="text-sm text-gray-600 mb-4">
              <strong>{selected.size}</strong> fichier(s) ({formatBytes(octetsSelection)}) vont être
              <strong> déplacés</strong> vers <code className="bg-gray-100 px-1 rounded">{data?.dossier_quarantaine}/</code>.
              Les fichiers ne sont <strong>pas supprimés</strong>.
            </p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmOpen(false)} disabled={moving}
                className="px-3 py-2 text-sm rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50">Annuler</button>
              <button onClick={confirmQuarantine} disabled={moving}
                className="flex items-center gap-2 px-4 py-2 bg-amber-600 text-white text-sm rounded-lg hover:bg-amber-700 disabled:opacity-50">
                {moving ? <Loader2 size={16} className="animate-spin" /> : <FolderInput size={16} />} Déplacer
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ── Photos floues : détection par variance du Laplacien + mise en quarantaine ──
function BlurryImages({ toast }: { toast: ReturnType<typeof useToast> }) {
  const [seuil, setSeuil] = useState(100)
  const [images, setImages] = useState<BlurryImage[] | null>(null)
  const [scanning, setScanning] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  const scanner = async () => {
    setScanning(true); setImages(null); setSelected(new Set())
    try { setImages((await duplicatesApi.blurry(seuil)).images) }
    catch { toast.error('Scan des images impossible') }
    finally { setScanning(false) }
  }
  const toggle = (c: string) => setSelected(s => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n })
  const mettreEnQuarantaine = async () => {
    if (selected.size === 0) return
    if (!confirm(`Déplacer ${selected.size} image(s) floue(s) vers la corbeille (réversible) ?`)) return
    setBusy(true)
    try {
      const r = await duplicatesApi.quarantine([...selected])
      toast.success(`${r.deplaces.length} image(s) déplacée(s)`)
      setImages(imgs => (imgs ?? []).filter(i => !selected.has(i.chemin))); setSelected(new Set())
    } catch { toast.error('Déplacement impossible') } finally { setBusy(false) }
  }

  return (
    <>
      <div className="flex items-center gap-3 flex-wrap mb-3 text-sm">
        <label className="flex items-center gap-2 text-gray-600">
          Seuil de netteté
          <input type="range" min={20} max={500} step={10} value={seuil}
            onChange={e => setSeuil(Number(e.target.value))} className="accent-blue-600" />
          <span className="tabular-nums w-10">{seuil}</span>
        </label>
        <span className="text-xs text-gray-400">plus bas = seulement les très floues · plus haut = plus permissif</span>
        <button type="button" onClick={scanner} disabled={scanning}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
          {scanning ? <Loader2 size={14} className="animate-spin" /> : <FolderSearch size={14} />}
          {scanning ? 'Analyse…' : 'Détecter les images floues'}
        </button>
      </div>

      {scanning && <p className="text-xs text-gray-400 flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Analyse de la netteté de chaque image… (peut prendre du temps)</p>}

      {images && images.length === 0 && (
        <p className="text-sm text-gray-400 py-6 text-center">Aucune image en dessous du seuil de netteté. Baisse/augmente le seuil et relance.</p>
      )}

      {images && images.length > 0 && (
        <>
          <p className="text-sm text-gray-600 mb-2">{images.length} image(s) potentiellement floue(s) — les plus floues en premier.</p>
          <ul className="divide-y divide-gray-100 border border-gray-200 rounded-lg overflow-hidden">
            {images.map(im => (
              <li key={im.chemin} className={clsx('flex items-center gap-2 px-3 py-2 text-sm', selected.has(im.chemin) ? 'bg-blue-50' : 'hover:bg-gray-50')}>
                <input type="checkbox" checked={selected.has(im.chemin)} onChange={() => toggle(im.chemin)} className="w-4 h-4 accent-blue-600 shrink-0" />
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-gray-700 truncate">{im.nom}</p>
                  <p className="text-xs text-gray-400 truncate">{im.relatif}</p>
                </div>
                <span className="text-xs text-amber-600 shrink-0" title="Variance du Laplacien (plus c'est bas, plus c'est flou)">netteté {im.nettete}</span>
                <span className="text-xs text-gray-400 shrink-0 w-16 text-right">{formatBytes(im.taille_octets)}</span>
              </li>
            ))}
          </ul>
          {selected.size > 0 && (
            <div className="mt-3 flex items-center gap-3">
              <span className="text-sm text-gray-600"><strong>{selected.size}</strong> sélectionnée(s)</span>
              <button type="button" onClick={mettreEnQuarantaine} disabled={busy}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-red-600 text-white hover:bg-red-700 disabled:opacity-50">
                {busy ? <Loader2 size={14} className="animate-spin" /> : <FolderInput size={14} />} Déplacer vers la corbeille
              </button>
            </div>
          )}
        </>
      )}
    </>
  )
}
