/**
 * AdminLinksEditor — éditeur des liens de la page Administration.
 * - Lignes ÉDITABLES en ligne (Section / Libellé / Lien) via le crayon.
 * - AUTO-ENREGISTREMENT (debounce) : plus besoin de cliquer « Enregistrer ».
 * - GARDE-FOU : brouillon en localStorage, restauré si on quitte sans que
 *   l'auto-save ait abouti (réseau, fermeture d'onglet…).
 */
import { useEffect, useRef, useState } from 'react'
import { Check, Pencil, Plus, RotateCcw, Trash2, X } from 'lucide-react'
import { systemApi } from '../../api'

type Lien = { section: string; label: string; url: string }

const DRAFT_KEY = 'mtq_admin_links_draft'
const normUrl = (u: string) => (/^https?:\/\//.test(u) ? u : `https://${u.trim()}`)

function parse(json: string): Lien[] {
  try {
    const a = JSON.parse(json || '[]')
    return Array.isArray(a) ? a : []
  } catch {
    return []
  }
}

export default function AdminLinksEditor({
  value,
  onChange,
}: {
  value: string
  onChange: (json: string) => void
}) {
  const [links, setLinks] = useState<Lien[]>(() => parse(value))
  const [editIdx, setEditIdx] = useState<number | null>(null)
  const [edit, setEdit] = useState<Lien>({ section: '', label: '', url: '' })
  const [form, setForm] = useState<Lien>({ section: '', label: '', url: '' })
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [recover, setRecover] = useState<Lien[] | null>(null)

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Au montage : proposer un éventuel brouillon non enregistré (garde-fou).
  useEffect(() => {
    const d = localStorage.getItem(DRAFT_KEY)
    if (d && d !== value) setRecover(parse(d))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  // Applique une nouvelle liste : sync parent + brouillon + auto-save débouncé.
  const commit = (next: Lien[]) => {
    setLinks(next)
    const json = JSON.stringify(next)
    onChange(json)
    localStorage.setItem(DRAFT_KEY, json) // brouillon avant confirmation serveur
    setStatus('saving')
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      try {
        await systemApi.updateConfig({ admin_links: json })
        localStorage.removeItem(DRAFT_KEY) // enregistré → plus de brouillon
        setStatus('saved')
      } catch {
        setStatus('error') // échec → on GARDE le brouillon
      }
    }, 1000)
  }

  const ajouter = () => {
    if (!form.label.trim() || !form.url.trim()) return
    commit([...links, { section: form.section.trim() || 'Divers', label: form.label.trim(), url: normUrl(form.url) }])
    setForm({ section: form.section, label: '', url: '' })
  }
  const supprimer = (i: number) => {
    if (editIdx === i) setEditIdx(null)
    commit(links.filter((_, idx) => idx !== i))
  }
  const demarrerEdition = (i: number) => { setEditIdx(i); setEdit(links[i]) }
  const validerEdition = () => {
    if (editIdx === null) return
    if (!edit.label.trim() || !edit.url.trim()) return
    commit(links.map((l, idx) => (idx === editIdx ? { section: edit.section.trim() || 'Divers', label: edit.label.trim(), url: normUrl(edit.url) } : l)))
    setEditIdx(null)
  }

  const sections = [...new Set(links.map(l => l.section))]
  const inputCls = 'text-xs border border-gray-200 rounded-md px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400'

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
      {/* Bandeau récupération de brouillon */}
      {recover && (
        <div className="flex items-center gap-2 text-xs bg-amber-50 border border-amber-200 text-amber-800 rounded-md px-3 py-2">
          <RotateCcw size={14} className="shrink-0" />
          <span className="flex-1">Un brouillon non enregistré a été retrouvé ({recover.length} lien(s)).</span>
          <button type="button" onClick={() => { commit(recover); setRecover(null) }}
            className="px-2 py-0.5 bg-amber-600 text-white rounded hover:bg-amber-700">Restaurer</button>
          <button type="button" onClick={() => { localStorage.removeItem(DRAFT_KEY); setRecover(null) }}
            className="px-2 py-0.5 border border-amber-300 rounded hover:bg-amber-100">Ignorer</button>
        </div>
      )}

      {/* Liste des liens */}
      {links.length === 0 ? (
        <p className="text-xs text-gray-400">Aucun lien.</p>
      ) : (
        <ul className="divide-y divide-gray-100">
          {links.map((l, i) => (
            <li key={i} className="flex items-center gap-2 py-1.5 text-sm">
              {editIdx === i ? (
                <>
                  <input value={edit.section} onChange={e => setEdit(v => ({ ...v, section: e.target.value }))}
                    list="admin-sections" aria-label="Section" placeholder="Section" className={`${inputCls} w-28`} />
                  <input value={edit.label} onChange={e => setEdit(v => ({ ...v, label: e.target.value }))}
                    aria-label="Libellé" placeholder="Libellé" className={`${inputCls} flex-1 min-w-[7rem]`} />
                  <input value={edit.url} onChange={e => setEdit(v => ({ ...v, url: e.target.value }))}
                    onKeyDown={e => { if (e.key === 'Enter') validerEdition(); if (e.key === 'Escape') setEditIdx(null) }}
                    aria-label="Lien" placeholder="https://…" className={`${inputCls} flex-1 min-w-[9rem] font-mono`} />
                  <button type="button" onClick={validerEdition} title="Valider" className="text-green-600 hover:text-green-700 shrink-0"><Check size={15} /></button>
                  <button type="button" onClick={() => setEditIdx(null)} title="Annuler" className="text-gray-400 hover:text-gray-600 shrink-0"><X size={15} /></button>
                </>
              ) : (
                <>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 shrink-0">{l.section}</span>
                  <span className="font-medium text-gray-700 truncate">{l.label}</span>
                  <span className="text-xs text-gray-400 truncate flex-1">{l.url}</span>
                  <button type="button" onClick={() => demarrerEdition(i)} title="Modifier" className="text-gray-300 hover:text-blue-500 shrink-0"><Pencil size={13} /></button>
                  <button type="button" onClick={() => supprimer(i)} title="Retirer" className="text-gray-300 hover:text-red-500 shrink-0"><Trash2 size={13} /></button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {/* Ajout d'un lien */}
      <div className="flex gap-2 flex-wrap pt-2 border-t border-gray-100">
        <input value={form.section} onChange={e => setForm(v => ({ ...v, section: e.target.value }))}
          placeholder="Section (ex. Médical)" list="admin-sections" aria-label="Section" className={`${inputCls} w-36 py-1.5`} />
        <datalist id="admin-sections">{sections.map(s => <option key={s} value={s} />)}</datalist>
        <input value={form.label} onChange={e => setForm(v => ({ ...v, label: e.target.value }))}
          placeholder="Libellé (ex. Doctolib)" aria-label="Libellé" className={`${inputCls} flex-1 min-w-[8rem] py-1.5`} />
        <input value={form.url} onChange={e => setForm(v => ({ ...v, url: e.target.value }))}
          onKeyDown={e => { if (e.key === 'Enter') ajouter() }}
          placeholder="https://…" aria-label="URL" className={`${inputCls} flex-1 min-w-[10rem] font-mono py-1.5`} />
        <button type="button" onClick={ajouter}
          className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 flex items-center gap-1"><Plus size={13} /> Ajouter</button>
      </div>

      {/* État de l'auto-enregistrement */}
      <div className="flex justify-end items-center gap-1.5 text-xs h-4">
        {status === 'saving' && <span className="text-gray-400">Enregistrement…</span>}
        {status === 'saved' && <span className="text-green-600 flex items-center gap-1"><Check size={12} /> Enregistré automatiquement</span>}
        {status === 'error' && <span className="text-red-500">Échec de l'enregistrement — brouillon conservé</span>}
      </div>
    </div>
  )
}
