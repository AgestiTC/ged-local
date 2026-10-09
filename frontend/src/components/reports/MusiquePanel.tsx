/**
 * MusiquePanel — « Créer une musique ! » (ACE-Step 1.5 dans ComfyUI, sur PC-GAME).
 *
 * Le rendu est une tâche durable du worker (`musique`) : on la suit, puis on lit le MP3. Avant
 * de proposer « Composer », on dit honnêtement si c'est possible : ComfyUI non configuré, PC-GAME
 * éteint, ou carte trop occupée (Matothèque ne décharge jamais les modèles des autres — JARVIS).
 */
import { useEffect, useState } from 'react'
import { Download, Loader2, Music, RefreshCw } from 'lucide-react'
import { musiqueApi, suivreJob, type EtatMusique } from '../../api'
import { useToast } from '../common/Toast'

const DUREES = [30, 60, 120, 180, 240]
const LANGUES: [string, string][] = [['fr', 'Français'], ['en', 'Anglais'], ['es', 'Espagnol'], ['it', 'Italien'], ['de', 'Allemand']]

function libelleDuree(s: number) {
  return s < 60 ? `${s} s` : `${s / 60} min`
}

export default function MusiquePanel() {
  const toast = useToast()
  const [etat, setEtat] = useState<EtatMusique | null>(null)
  const [style, setStyle] = useState('')
  const [paroles, setParoles] = useState('')
  const [duree, setDuree] = useState(60)
  const [langue, setLangue] = useState('fr')
  const [enCours, setEnCours] = useState<{ progres: number; message: string } | null>(null)
  const [morceaux, setMorceaux] = useState<{ id: string; style: string; duree: number }[]>([])

  const verifier = () => { musiqueApi.etat().then(setEtat).catch(() => setEtat(null)) }
  useEffect(verifier, [])

  const blocage = !etat ? 'Vérification…'
    : !etat.configure ? "La génération musicale n'est pas encore reliée à Matothèque (ComfyUI de PC-GAME en cours d'ouverture au réseau)."
    : !etat.joignable ? 'ComfyUI injoignable : PC-GAME éteint, ou ComfyUI arrêté.'
    : !etat.pret ? `Carte graphique occupée : ${etat.vram_libre_go} Gio libres, ${etat.seuil_go} requis. Réessaie plus tard.`
    : null

  const composer = async () => {
    if (!style.trim() && !paroles.trim()) { toast.error('Décris un style ou écris des paroles'); return }
    setEnCours({ progres: 0, message: 'Mise en file…' })
    try {
      const { job_id } = await musiqueApi.creer({ style, paroles, duree, langue })
      const job = await suivreJob(job_id, j => setEnCours({ progres: j.progress, message: j.progress_message ?? '' }), 2000)
      if (job.statut === 'completed') {
        setMorceaux(m => [{ id: job_id, style: style || 'Sans titre', duree }, ...m])
        toast.success('Morceau prêt')
      } else {
        toast.error(job.erreur ?? 'Composition impossible')
      }
    } catch {
      toast.error('Composition impossible')
    } finally {
      setEnCours(null)
      verifier()
    }
  }

  return (
    <div className="flex flex-col lg:flex-row gap-4 flex-1 min-h-0">
      <section className="w-full lg:w-[460px] shrink-0 bg-white border border-gray-200 rounded-lg p-4 flex flex-col gap-3">
        <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2"><Music size={15} /> Créer une musique</h2>

        <label className="text-xs text-gray-600">Style
          <textarea value={style} onChange={e => setStyle(e.target.value)} rows={3}
            placeholder="Ex. : chanson française acoustique, guitare folk, voix féminine douce, mélancolique"
            className="mt-1 w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400 placeholder:text-gray-300" />
        </label>

        <label className="text-xs text-gray-600">Paroles (facultatif)
          <textarea value={paroles} onChange={e => setParoles(e.target.value)} rows={9}
            placeholder={'[Verse]\nPremier couplet…\n\n[Chorus]\nRefrain…\n\nVide = musique instrumentale ou paroles inventées.'}
            className="mt-1 w-full text-sm border border-gray-200 rounded-lg px-3 py-2 font-mono focus:outline-none focus:ring-2 focus:ring-blue-400 placeholder:text-gray-300" />
        </label>

        <div className="flex gap-3">
          <label className="text-xs text-gray-600 flex-1">Durée
            <select value={duree} onChange={e => setDuree(Number(e.target.value))}
              className="mt-1 w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white">
              {DUREES.map(d => <option key={d} value={d}>{libelleDuree(d)}</option>)}
            </select>
          </label>
          <label className="text-xs text-gray-600 flex-1">Langue du chant
            <select value={langue} onChange={e => setLangue(e.target.value)}
              className="mt-1 w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white">
              {LANGUES.map(([c, l]) => <option key={c} value={c}>{l}</option>)}
            </select>
          </label>
        </div>

        {blocage && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 flex items-start gap-2">
            <span className="flex-1">{blocage}</span>
            <button type="button" onClick={verifier} title="Vérifier à nouveau" className="text-amber-600 hover:text-amber-800"><RefreshCw size={13} /></button>
          </p>
        )}

        <button type="button" onClick={composer} disabled={!!blocage || !!enCours}
          className="mt-1 flex items-center justify-center gap-2 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed">
          {enCours ? <Loader2 size={15} className="animate-spin" /> : <Music size={15} />}
          {enCours ? `${enCours.message || 'Composition…'} ${enCours.progres}%` : 'Composer'}
        </button>
        <p className="text-xs text-gray-400">Calculé sur la carte graphique de PC-GAME : compter environ 1 à 2 fois la durée du morceau.</p>
      </section>

      <section className="flex-1 min-w-0 bg-white border border-gray-200 rounded-lg p-4 flex flex-col gap-3">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Morceaux</h2>
        {morceaux.length === 0 && <p className="text-sm text-gray-400">Les morceaux composés apparaîtront ici.</p>}
        {morceaux.map(m => (
          <div key={m.id} className="border border-gray-100 rounded-lg p-3 flex flex-col gap-2">
            <div className="flex items-center gap-2 text-sm">
              <span className="flex-1 truncate font-medium text-gray-700" title={m.style}>{m.style}</span>
              <span className="text-xs text-gray-400">{libelleDuree(m.duree)}</span>
              <a href={musiqueApi.fichierUrl(m.id)} download className="text-gray-400 hover:text-blue-600" title="Télécharger le MP3"><Download size={15} /></a>
            </div>
            <audio controls src={musiqueApi.fichierUrl(m.id)} className="w-full" />
          </div>
        ))}
      </section>
    </div>
  )
}
