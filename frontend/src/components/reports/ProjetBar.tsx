/**
 * ProjetBar — barre « Projet » en tête de Créer, quelle que soit la tuile, et fenêtre « Mes projets »
 * (brouillons, archivés, corbeille). Plan : docs/plan-projets-creer.md.
 * Confirmations dans la page, jamais de boîte du navigateur.
 */
import { useEffect, useState } from 'react'
import { Archive, Check, Copy, FolderOpen, Loader2, Pencil, RotateCcw, Save, Trash2, X } from 'lucide-react'
import { clsx } from 'clsx'
import { projetsApi, type ProjetResume } from '../../api'
import { useProjetStore } from '../../stores/projetStore'
import { useToast } from '../common/Toast'

const LIBELLE_MODE: Record<string, string> = {
  rapport_libre: 'Rapport', remplir_template: 'Modèle Word', classement: 'Classement',
  comparatif: 'Comparatif', wiki: 'Tuto wiki', musique: 'Musique', video: 'Vidéo',
}

function depuis(iso: string | null) {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return "à l'instant"
  if (s < 3600) return `il y a ${Math.floor(s / 60)} min`
  if (s < 86400) return `il y a ${Math.floor(s / 3600)} h`
  return new Date(iso).toLocaleDateString('fr-FR')
}

export default function ProjetBar({ onOuvert }: { onOuvert?: (mode: string) => void }) {
  const toast = useToast()
  const { projet, enregistrement, commencer, ouvrir, fermer, renommer, enregistrerMaintenant } = useProjetStore()
  const [titre, setTitre] = useState('')
  const [edition, setEdition] = useState(false)
  const [liste, setListe] = useState(false)
  const [confirmer, setConfirmer] = useState<'archiver' | 'supprimer' | null>(null)

  const demarrer = async () => {
    if (!titre.trim()) return
    try { await commencer(titre.trim()); setTitre(''); toast.success("Projet créé — il s'enregistre tout seul") }
    catch { toast.error('Création du projet impossible') }
  }

  const agir = async (action: 'archiver' | 'supprimer' | 'dupliquer') => {
    if (!projet) return
    try {
      await enregistrerMaintenant()
      if (action === 'dupliquer') {
        const c = await projetsApi.dupliquer(projet.id)
        const p = await ouvrir(c.id)
        onOuvert?.(p.mode)
        toast.success('Copie ouverte')
      } else {
        if (action === 'archiver') await projetsApi.archiver(projet.id)
        else await projetsApi.supprimer(projet.id)
        fermer()
        toast.success(action === 'archiver' ? 'Projet archivé' : 'Projet mis à la corbeille (30 jours)')
      }
    } catch { toast.error('Action impossible') }
    setConfirmer(null)
  }

  const statut = enregistrement === 'en_cours' ? 'Enregistrement…'
    : enregistrement === 'ok' ? 'Enregistré'
    : enregistrement === 'conflit' ? 'Modifié dans un autre onglet — rouvre le projet'
    : enregistrement === 'erreur' ? "Échec de l'enregistrement" : ''

  return (
    <div className="flex items-center gap-2 flex-wrap rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm">
      <FolderOpen size={15} className="text-violet-600 shrink-0" />
      {!projet ? (
        <>
          <span className="text-gray-500">Aucun projet ouvert.</span>
          <input value={titre} onChange={e => setTitre(e.target.value)} onKeyDown={e => e.key === 'Enter' && demarrer()}
            placeholder="Nom du projet…" maxLength={200}
            className="flex-1 min-w-[160px] max-w-xs text-sm border border-gray-200 rounded-md px-2 py-1 focus:outline-none focus:ring-1 focus:ring-violet-400" />
          <button type="button" onClick={demarrer} disabled={!titre.trim()}
            className="flex items-center gap-1 px-2.5 py-1 rounded-md bg-violet-600 text-white text-xs font-medium hover:bg-violet-700 disabled:opacity-40">
            <Save size={13} /> Commencer un projet
          </button>
        </>
      ) : (
        <>
          {edition ? (
            <input autoFocus defaultValue={projet.titre} maxLength={200}
              onKeyDown={async e => {
                if (e.key === 'Escape') setEdition(false)
                if (e.key === 'Enter') { const v = e.currentTarget.value.trim(); if (v) await renommer(v); setEdition(false) }
              }}
              onBlur={async e => { const v = e.currentTarget.value.trim(); if (v && v !== projet.titre) await renommer(v); setEdition(false) }}
              className="text-sm border border-violet-300 rounded-md px-2 py-0.5 focus:outline-none" />
          ) : (
            <button type="button" onClick={() => setEdition(true)} title="Renommer"
              className="font-medium text-gray-800 flex items-center gap-1 hover:text-violet-700">
              {projet.titre} <Pencil size={11} className="text-gray-400" />
            </button>
          )}
          <span className={clsx('text-xs flex items-center gap-1',
            enregistrement === 'erreur' || enregistrement === 'conflit' ? 'text-red-600' : 'text-gray-400')}>
            {enregistrement === 'en_cours' ? <Loader2 size={11} className="animate-spin" /> : enregistrement === 'ok' ? <Check size={11} /> : null}
            {statut}
          </span>
          <span className="flex-1" />
          {confirmer ? (
            <span className="flex items-center gap-2 text-xs">
              <span className="text-amber-700">{confirmer === 'archiver' ? 'Archiver ce projet ?' : 'Mettre ce projet à la corbeille ?'}</span>
              <button type="button" onClick={() => agir(confirmer)} className="font-medium text-red-600 hover:underline">Confirmer</button>
              <button type="button" onClick={() => setConfirmer(null)} className="text-gray-500 hover:underline">Annuler</button>
            </span>
          ) : (
            <span className="flex items-center gap-1">
              <button type="button" onClick={() => agir('dupliquer')} title="Dupliquer" className="p-1 text-gray-400 hover:text-gray-700"><Copy size={14} /></button>
              <button type="button" onClick={() => setConfirmer('archiver')} title="Archiver" className="p-1 text-gray-400 hover:text-gray-700"><Archive size={14} /></button>
              <button type="button" onClick={() => setConfirmer('supprimer')} title="Mettre à la corbeille" className="p-1 text-gray-400 hover:text-red-600"><Trash2 size={14} /></button>
              <button type="button" onClick={async () => { await enregistrerMaintenant(); fermer() }} title="Fermer le projet (il reste enregistré)"
                className="p-1 text-gray-400 hover:text-gray-700"><X size={14} /></button>
            </span>
          )}
        </>
      )}
      <button type="button" onClick={() => setListe(true)}
        className="text-xs px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">Mes projets</button>

      {liste && <MesProjets onFermer={() => setListe(false)} onOuvrir={async id => {
        try {
          if (projet) await enregistrerMaintenant()
          const p = await ouvrir(id)
          onOuvert?.(p.mode)
          setListe(false)
        } catch { toast.error('Ouverture impossible') }
      }} />}
    </div>
  )
}

function MesProjets({ onFermer, onOuvrir }: { onFermer: () => void; onOuvrir: (id: string) => void }) {
  const toast = useToast()
  const [onglet, setOnglet] = useState<'brouillon' | 'archive' | 'corbeille'>('brouillon')
  const [q, setQ] = useState('')
  const [projets, setProjets] = useState<ProjetResume[] | null>(null)
  const [purge, setPurge] = useState<string | null>(null)

  const charger = () => { projetsApi.lister(onglet, q).then(setProjets).catch(() => setProjets([])) }
  useEffect(() => { const t = setTimeout(charger, 200); return () => clearTimeout(t) }, [onglet, q])

  const agir = async (fn: () => Promise<unknown>, message: string) => {
    try { await fn(); toast.success(message); charger() } catch { toast.error('Action impossible') }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onFermer}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl max-h-[80vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100">
          <h2 className="font-semibold text-gray-800 flex-1">Mes projets</h2>
          <button type="button" onClick={onFermer} className="text-gray-400 hover:text-gray-700"><X size={16} /></button>
        </div>
        <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-100">
          {(['brouillon', 'archive', 'corbeille'] as const).map(o => (
            <button key={o} type="button" onClick={() => setOnglet(o)}
              className={clsx('text-xs px-2.5 py-1 rounded-md', onglet === o ? 'bg-violet-100 text-violet-700 font-medium' : 'text-gray-500 hover:bg-gray-50')}>
              {o === 'brouillon' ? 'Brouillons' : o === 'archive' ? 'Archivés' : 'Corbeille'}
            </button>
          ))}
          <input value={q} onChange={e => setQ(e.target.value)} placeholder="Rechercher…"
            className="ml-auto text-xs border border-gray-200 rounded-md px-2 py-1 w-48 focus:outline-none focus:ring-1 focus:ring-violet-400" />
        </div>
        <div className="flex-1 overflow-y-auto">
          {projets === null && <p className="text-xs text-gray-400 p-4 flex items-center gap-1"><Loader2 size={12} className="animate-spin" /> Chargement…</p>}
          {projets?.length === 0 && <p className="text-sm text-gray-400 p-4">Aucun projet ici.</p>}
          {onglet === 'corbeille' && !!projets?.length && <p className="text-xs text-gray-400 px-4 pt-2">Les projets restent 30 jours dans la corbeille. Leurs résultats (rapports, morceaux…) ne sont jamais supprimés avec eux.</p>}
          {projets?.map(p => (
            <div key={p.id} className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-50 hover:bg-gray-50 text-sm">
              <div className="flex-1 min-w-0">
                <p className="font-medium text-gray-800 truncate">{p.titre}</p>
                <p className="text-xs text-gray-400">{LIBELLE_MODE[p.mode] ?? p.mode} · {depuis(p.updated_at)}
                  {p.nb_resultats ? ` · ${p.nb_resultats} résultat${p.nb_resultats > 1 ? 's' : ''}` : ''}</p>
              </div>
              {onglet === 'brouillon' && <>
                <button type="button" onClick={() => onOuvrir(p.id)} className="text-xs px-2.5 py-1 rounded-md bg-violet-600 text-white hover:bg-violet-700">Ouvrir</button>
                <button type="button" title="Archiver" onClick={() => agir(() => projetsApi.archiver(p.id), 'Projet archivé')} className="p-1 text-gray-400 hover:text-gray-700"><Archive size={14} /></button>
                <button type="button" title="Mettre à la corbeille" onClick={() => agir(() => projetsApi.supprimer(p.id), 'Mis à la corbeille')} className="p-1 text-gray-400 hover:text-red-600"><Trash2 size={14} /></button>
              </>}
              {onglet === 'archive' && <>
                <button type="button" onClick={() => agir(() => projetsApi.restaurer(p.id), 'Remis en brouillon')} className="text-xs flex items-center gap-1 px-2.5 py-1 rounded-md border border-gray-200 hover:bg-gray-100"><RotateCcw size={12} /> Remettre en brouillon</button>
                <button type="button" title="Mettre à la corbeille" onClick={() => agir(() => projetsApi.supprimer(p.id), 'Mis à la corbeille')} className="p-1 text-gray-400 hover:text-red-600"><Trash2 size={14} /></button>
              </>}
              {onglet === 'corbeille' && (purge === p.id ? (
                <span className="flex items-center gap-2 text-xs">
                  <span className="text-red-600">Supprimer définitivement ?</span>
                  <button type="button" onClick={() => { setPurge(null); void agir(() => projetsApi.supprimer(p.id, true), 'Supprimé définitivement') }} className="font-medium text-red-600 hover:underline">Oui</button>
                  <button type="button" onClick={() => setPurge(null)} className="text-gray-500 hover:underline">Non</button>
                </span>
              ) : <>
                <button type="button" onClick={() => agir(() => projetsApi.restaurer(p.id), 'Projet restauré')} className="text-xs flex items-center gap-1 px-2.5 py-1 rounded-md border border-gray-200 hover:bg-gray-100"><RotateCcw size={12} /> Restaurer</button>
                <button type="button" onClick={() => setPurge(p.id)} className="text-xs text-red-600 hover:underline">Supprimer définitivement</button>
              </>)}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
