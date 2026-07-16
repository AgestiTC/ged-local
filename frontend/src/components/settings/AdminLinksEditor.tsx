/**
 * AdminLinksEditor — éditeur des liens de la page Administration.
 * - Lignes ÉDITABLES en ligne (Section / Libellé / Lien) via le crayon.
 * - AUTO-ENREGISTREMENT (debounce) : plus besoin de cliquer « Enregistrer ».
 * - GARDE-FOU : brouillon en localStorage, restauré si on quitte sans que
 *   l'auto-save ait abouti (réseau, fermeture d'onglet…).
 */
import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, ChevronRight, Landmark, Pencil, Plus, RotateCcw, Trash2, X } from 'lucide-react'
import { systemApi } from '../../api'

type Lien = { section: string; label: string; url: string }

const DRAFT_KEY = 'mtq_admin_links_draft'
const normUrl = (u: string) => (/^https?:\/\//.test(u) ? u : `https://${u.trim()}`)

// Hôte normalisé (sans protocole / « www. » / slash final) — sert à comparer deux liens
// indépendamment de leur écriture (impots.gouv.fr == https://www.impots.gouv.fr/).
const hote = (u: string) => {
  try { return new URL(normUrl(u)).host.replace(/^www\./, '').toLowerCase() }
  catch { return u.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/.*$/, '') }
}

// Catalogue de services publics activables d'un clic (interrupteur). Essentiellement *.gouv.fr
// + quelques services officiels équivalents. Activer = le lien apparaît dans la page Administration.
const CATALOGUE: Lien[] = [
  { section: 'Gouv', label: 'Service-Public.fr', url: 'https://www.service-public.fr' },
  { section: 'Gouv', label: 'Impôts', url: 'https://www.impots.gouv.fr' },
  { section: 'Gouv', label: 'ANTS — carte grise / permis', url: 'https://ants.gouv.fr' },
  { section: 'Gouv', label: 'FranceConnect', url: 'https://franceconnect.gouv.fr' },
  { section: 'Gouv', label: 'Légifrance', url: 'https://www.legifrance.gouv.fr' },
  { section: 'Gouv', label: 'Mon Compte Formation', url: 'https://www.moncompteformation.gouv.fr' },
  { section: 'Gouv', label: 'ANTAI — avis de contravention', url: 'https://www.antai.gouv.fr' },
  { section: 'Gouv', label: 'Amendes', url: 'https://www.amendes.gouv.fr' },
  { section: 'Gouv', label: 'Chèque énergie', url: 'https://chequeenergie.gouv.fr' },
  { section: 'Gouv', label: 'Mes Droits Sociaux', url: 'https://www.mesdroitssociaux.gouv.fr' },
  { section: 'Gouv', label: 'Géoportail', url: 'https://www.geoportail.gouv.fr' },
  { section: 'Gouv', label: 'Cadastre', url: 'https://www.cadastre.gouv.fr' },
  { section: 'Gouv', label: 'Cartes (cadastre / plans)', url: 'https://cartes.gouv.fr/explorer-les-cartes/' },
  { section: 'Gouv', label: 'data.gouv.fr', url: 'https://www.data.gouv.fr' },
  { section: 'Gouv', label: 'Démarches simplifiées', url: 'https://www.demarches-simplifiees.fr' },
  { section: 'Gouv', label: 'Justice.fr', url: 'https://www.justice.fr' },
  { section: 'Gouv', label: 'Éducation nationale', url: 'https://www.education.gouv.fr' },
  { section: 'Médical', label: 'Mon espace santé', url: 'https://www.monespacesante.fr' },
  { section: 'Médical', label: 'Ameli — Assurance Maladie', url: 'https://www.ameli.fr' },
]

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
  const [catalogueOuvert, setCatalogueOuvert] = useState(false)

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

  // Active/désactive un service du catalogue : présent → on retire toutes les lignes de même hôte ;
  // absent → on ajoute la suggestion. La comparaison par hôte tolère les variantes d'écriture.
  const hotesActifs = new Set(links.map(l => hote(l.url)))
  const basculer = (s: Lien) => {
    if (hotesActifs.has(hote(s.url))) commit(links.filter(l => hote(l.url) !== hote(s.url)))
    else commit([...links, { section: s.section, label: s.label, url: normUrl(s.url) }])
  }
  const nbActifs = CATALOGUE.filter(s => hotesActifs.has(hote(s.url))).length

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

      {/* Catalogue de services publics à activer d'un clic (interrupteur) */}
      <div className="border-t border-gray-100 pt-3">
        <button type="button" onClick={() => setCatalogueOuvert(o => !o)}
          className="flex items-center gap-2 text-xs font-medium text-gray-600 hover:text-blue-600 w-full">
          {catalogueOuvert ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Landmark size={14} className="text-blue-600" />
          <span>Services publics (gouv.fr) à activer</span>
          <span className="ml-auto text-[10px] text-gray-400">{nbActifs}/{CATALOGUE.length} activés</span>
        </button>

        {catalogueOuvert && (
          <div className="mt-2 space-y-1">
            <p className="text-[11px] text-gray-400 px-0.5">
              Active un service pour l'ajouter à la page Administration. Un service déjà présent apparaît activé.
            </p>
            <ul className="divide-y divide-gray-50 max-h-72 overflow-auto">
              {CATALOGUE.map(s => {
                const actif = hotesActifs.has(hote(s.url))
                return (
                  <li key={s.url} className="flex items-center gap-2 py-1.5">
                    <button type="button" role="switch" aria-checked={actif}
                      aria-label={`${actif ? 'Désactiver' : 'Activer'} ${s.label}`}
                      onClick={() => basculer(s)}
                      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${actif ? 'bg-blue-600' : 'bg-gray-300'}`}>
                      <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${actif ? 'translate-x-4' : 'translate-x-0.5'}`} />
                    </button>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 shrink-0 w-16 text-center">{s.section}</span>
                    <span className={`text-sm truncate ${actif ? 'font-medium text-gray-700' : 'text-gray-500'}`}>{s.label}</span>
                    <span className="text-[11px] text-gray-300 truncate flex-1 font-mono hidden sm:inline">{hote(s.url)}</span>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
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
