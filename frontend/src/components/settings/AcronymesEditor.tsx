/**
 * AcronymesEditor — dictionnaire d'acronymes (Sigle / Définition).
 * Sert à la NORMALISATION de casse : ces sigles sont forcés en MAJUSCULES sur les
 * tags/catégories (IBAN, RIB, TVA…). Mêmes ergonomie et garde-fous qu'AdminLinksEditor :
 * édition en ligne + auto-enregistrement débouncé + brouillon localStorage.
 */
import { useEffect, useRef, useState } from 'react'
import { Check, Pencil, Plus, RotateCcw, Trash2, X } from 'lucide-react'
import { systemApi } from '../../api'

type Acronyme = { sigle: string; definition: string }

const DRAFT_KEY = 'mtq_acronymes_draft'

function parse(json: string): Acronyme[] {
  try {
    const a = JSON.parse(json || '[]')
    return Array.isArray(a) ? a.filter(x => x && typeof x.sigle === 'string') : []
  } catch {
    return []
  }
}

export default function AcronymesEditor({
  value,
  onChange,
}: {
  value: string
  onChange: (json: string) => void
}) {
  const [items, setItems] = useState<Acronyme[]>(() => parse(value))
  const [editIdx, setEditIdx] = useState<number | null>(null)
  const [edit, setEdit] = useState<Acronyme>({ sigle: '', definition: '' })
  const [form, setForm] = useState<Acronyme>({ sigle: '', definition: '' })
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [recover, setRecover] = useState<Acronyme[] | null>(null)

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const d = localStorage.getItem(DRAFT_KEY)
    if (d && d !== value) setRecover(parse(d))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  const commit = (next: Acronyme[]) => {
    setItems(next)
    const json = JSON.stringify(next)
    onChange(json)
    localStorage.setItem(DRAFT_KEY, json)
    setStatus('saving')
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      try {
        await systemApi.updateConfig({ acronymes: json })
        localStorage.removeItem(DRAFT_KEY)
        setStatus('saved')
      } catch {
        setStatus('error')
      }
    }, 1000)
  }

  const ajouter = () => {
    if (!form.sigle.trim()) return
    commit([...items, { sigle: form.sigle.trim().toUpperCase(), definition: form.definition.trim() }])
    setForm({ sigle: '', definition: '' })
  }
  const supprimer = (i: number) => {
    if (editIdx === i) setEditIdx(null)
    commit(items.filter((_, idx) => idx !== i))
  }
  const demarrerEdition = (i: number) => { setEditIdx(i); setEdit(items[i]) }
  const validerEdition = () => {
    if (editIdx === null || !edit.sigle.trim()) return
    commit(items.map((it, idx) => (idx === editIdx ? { sigle: edit.sigle.trim().toUpperCase(), definition: edit.definition.trim() } : it)))
    setEditIdx(null)
  }

  const inputCls = 'text-xs border border-gray-200 rounded-md px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400'

  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
      {recover && (
        <div className="flex items-center gap-2 text-xs bg-amber-50 border border-amber-200 text-amber-800 rounded-md px-3 py-2">
          <RotateCcw size={14} className="shrink-0" />
          <span className="flex-1">Un brouillon non enregistré a été retrouvé ({recover.length} sigle(s)).</span>
          <button type="button" onClick={() => { commit(recover); setRecover(null) }}
            className="px-2 py-0.5 bg-amber-600 text-white rounded hover:bg-amber-700">Restaurer</button>
          <button type="button" onClick={() => { localStorage.removeItem(DRAFT_KEY); setRecover(null) }}
            className="px-2 py-0.5 border border-amber-300 rounded hover:bg-amber-100">Ignorer</button>
        </div>
      )}

      {items.length === 0 ? (
        <p className="text-xs text-gray-400">Aucun acronyme.</p>
      ) : (
        <ul className="divide-y divide-gray-100 max-h-72 overflow-auto">
          {items.map((it, i) => (
            <li key={i} className="flex items-center gap-2 py-1.5 text-sm">
              {editIdx === i ? (
                <>
                  <input value={edit.sigle} onChange={e => setEdit(v => ({ ...v, sigle: e.target.value }))}
                    aria-label="Sigle" placeholder="Sigle" className={`${inputCls} w-24 font-mono uppercase`} />
                  <input value={edit.definition} onChange={e => setEdit(v => ({ ...v, definition: e.target.value }))}
                    onKeyDown={e => { if (e.key === 'Enter') validerEdition(); if (e.key === 'Escape') setEditIdx(null) }}
                    aria-label="Définition" placeholder="Définition" className={`${inputCls} flex-1 min-w-[9rem]`} />
                  <button type="button" onClick={validerEdition} title="Valider" className="text-green-600 hover:text-green-700 shrink-0"><Check size={15} /></button>
                  <button type="button" onClick={() => setEditIdx(null)} title="Annuler" className="text-gray-400 hover:text-gray-600 shrink-0"><X size={15} /></button>
                </>
              ) : (
                <>
                  <span className="text-[11px] font-mono font-semibold px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 shrink-0 w-24 text-center">{it.sigle}</span>
                  <span className="text-xs text-gray-500 truncate flex-1">{it.definition}</span>
                  <button type="button" onClick={() => demarrerEdition(i)} title="Modifier" className="text-gray-300 hover:text-blue-500 shrink-0"><Pencil size={13} /></button>
                  <button type="button" onClick={() => supprimer(i)} title="Retirer" className="text-gray-300 hover:text-red-500 shrink-0"><Trash2 size={13} /></button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      <div className="flex gap-2 flex-wrap pt-2 border-t border-gray-100">
        <input value={form.sigle} onChange={e => setForm(v => ({ ...v, sigle: e.target.value }))}
          placeholder="Sigle (ex. IBAN)" aria-label="Sigle" className={`${inputCls} w-28 py-1.5 font-mono uppercase`} />
        <input value={form.definition} onChange={e => setForm(v => ({ ...v, definition: e.target.value }))}
          onKeyDown={e => { if (e.key === 'Enter') ajouter() }}
          placeholder="Définition" aria-label="Définition" className={`${inputCls} flex-1 min-w-[10rem] py-1.5`} />
        <button type="button" onClick={ajouter}
          className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 flex items-center gap-1"><Plus size={13} /> Ajouter</button>
      </div>

      <div className="flex justify-between items-center gap-1.5 text-xs h-4">
        <span className="text-gray-400">{items.length} sigle(s)</span>
        {status === 'saving' && <span className="text-gray-400">Enregistrement…</span>}
        {status === 'saved' && <span className="text-green-600 flex items-center gap-1"><Check size={12} /> Enregistré automatiquement</span>}
        {status === 'error' && <span className="text-red-500">Échec de l'enregistrement — brouillon conservé</span>}
      </div>
    </div>
  )
}
