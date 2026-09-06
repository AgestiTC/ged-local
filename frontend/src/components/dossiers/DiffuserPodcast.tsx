/**
 * Diffuser un épisode de podcast sur une enceinte de la maison (via Home Assistant).
 *
 * Matothèque **catalogue**, elle ne rejoue pas : il n'y a volontairement aucun lecteur ici.
 * On n'écoute pas un podcast devant sa GED — on l'écoute en cuisinant. Ce panneau fait donc
 * le seul geste qui apporte quelque chose : envoyer l'épisode dans la pièce où l'on est.
 *
 * Deux sorties réseau, toutes deux sur clic explicite et annoncées avant :
 *   1. lire le flux du podcast (chez son éditeur) → la liste des épisodes ;
 *   2. demander à Home Assistant (LAN) de jouer l'audio sur l'enceinte choisie.
 * L'audio lui-même ne transite jamais par Matothèque : c'est l'enceinte qui va le chercher.
 */
import { useState } from 'react'
import { Cast, Globe, Loader2, Radio, Rss, ShieldCheck } from 'lucide-react'
import { clsx } from 'clsx'
import { dossiersApi, maisonApi, type EpisodePodcast, type Enceinte, type Ressource } from '../../api'
import { useToast } from '../common/Toast'

/** « 3723 » → « 1 h 02 ». Une durée en secondes ne se lit pas. */
function duree(s: number | null): string {
  if (!s) return ''
  const h = Math.floor(s / 3600)
  const m = Math.round((s % 3600) / 60)
  return h ? `${h} h ${String(m).padStart(2, '0')}` : `${m} min`
}

export default function DiffuserPodcast({ ressource, onFerme, onMaj }: {
  ressource: Ressource
  onFerme: () => void
  /** Appelé après enregistrement du flux, pour que la fiche reflète la nouvelle URL. */
  onMaj?: () => void
}) {
  const toast = useToast()
  const [episodes, setEpisodes] = useState<EpisodePodcast[] | null>(null)
  const [enceintes, setEnceintes] = useState<Enceinte[]>([])
  const [cible, setCible] = useState('')
  const [busy, setBusy] = useState(false)
  const [envoi, setEnvoi] = useState<string | null>(null)
  // Le flux vit ici tant qu'il n'est pas enregistré : aucune ressource du dossier « Devenir
  // parent » n'en avait, et un bouton qui disparaît pour cette raison ne l'explique pas.
  const [flux, setFlux] = useState(ressource.flux_url ?? '')
  const [enregistre, setEnregistre] = useState(!!ressource.flux_url)
  const [sauve, setSauve] = useState(false)

  const enregistrerFlux = async () => {
    const url = flux.trim()
    if (!/^https?:\/\//i.test(url)) { toast.error('Une URL de flux commence par http:// ou https://'); return }
    setSauve(true)
    try {
      await dossiersApi.updateRessource(ressource.id, { flux_url: url })
      setEnregistre(true)
      onMaj?.()
      toast.success('Flux enregistré.')
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Enregistrement impossible.')
    } finally { setSauve(false) }
  }

  // Un seul bouton pour les deux lectures : lister les épisodes n'a d'intérêt que si l'on
  // peut les envoyer quelque part, et inversement. Les séparer ferait deux confirmations.
  const charger = async () => {
    setBusy(true)
    try {
      const [reponse, hp] = await Promise.all([
        dossiersApi.episodes(ressource.id),
        maisonApi.enceintes().catch(() => [] as Enceinte[]),   // HA absent ≠ flux illisible
      ])
      setEpisodes(reponse.episodes)
      setEnceintes(hp)
      setCible(hp.find(e => e.etat !== 'unavailable')?.entity_id ?? hp[0]?.entity_id ?? '')
      if (reponse.episodes.length === 0) toast.error('Ce flux ne contient aucun épisode audio.')
      if (hp.length === 0) toast.info('Aucune enceinte : configure Home Assistant dans les Paramètres.')
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Lecture du flux impossible.')
    } finally { setBusy(false) }
  }

  const envoyer = async (ep: EpisodePodcast) => {
    if (!cible) { toast.error('Choisis une enceinte.'); return }
    setEnvoi(ep.audio_url)
    try {
      await maisonApi.diffuser(cible, ep.audio_url, `${ressource.titre} — ${ep.titre}`)
      toast.success('Envoyé sur l’enceinte.')
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Diffusion impossible.')
    } finally { setEnvoi(null) }
  }

  return (
    <div className="mt-2 rounded-md border border-sky-200 bg-sky-50 p-2.5 space-y-2">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-sky-700">
        <Cast size={11} /> Diffuser sur une enceinte
        <button type="button" onClick={onFerme}
          className="ml-auto normal-case tracking-normal font-normal text-gray-400 hover:text-gray-600">
          Fermer
        </button>
      </div>

      {!enregistre ? (
        /* Sans flux RSS, il n'y a pas d'épisodes à lister — mais c'est réparable en dix
           secondes, alors on demande l'URL ici plutôt que de renvoyer vers le formulaire. */
        <>
          <p className="text-xs text-sky-900">
            Ce podcast n'a pas encore d'<strong>URL de flux RSS</strong>. C'est elle qui porte les
            épisodes et leur audio — la page du podcast ne suffit pas. On la trouve en général
            sur le site de l'émission, ou via le bouton « RSS » de son hébergeur.
          </p>
          <div className="flex items-center gap-2 flex-wrap">
            <input value={flux} onChange={e => setFlux(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') enregistrerFlux() }}
              placeholder="https://feeds.exemple.fr/mon-podcast.xml"
              className="flex-1 min-w-[16rem] text-xs border border-sky-200 rounded px-2 py-1.5 bg-white" />
            <button type="button" onClick={enregistrerFlux} disabled={sauve || !flux.trim()}
              className="inline-flex items-center gap-1.5 text-xs font-medium bg-sky-600 text-white rounded px-2.5 py-1.5 hover:bg-sky-700 disabled:opacity-50">
              {sauve ? <Loader2 size={12} className="animate-spin" /> : <Rss size={12} />} Enregistrer
            </button>
          </div>
          <p className="flex items-center gap-1 text-[11px] text-gray-500">
            <ShieldCheck size={11} className="text-emerald-600" />
            Enregistrer l'URL ne sort pas sur le réseau : la lecture du flux reste un clic à part.
          </p>
        </>
      ) : episodes === null ? (
        <>
          {/* Ce qui sort est annoncé AVANT le clic, comme pour la veille. */}
          <p className="flex items-start gap-1.5 text-xs text-sky-900">
            <Globe size={13} className="mt-0.5 shrink-0" />
            <span>
              Matothèque va lire le flux de ce podcast chez son éditeur et demander à Home
              Assistant la liste de tes enceintes. <strong>Seule l'URL du flux sort</strong> —
              aucun document, aucun tag, aucun nom. L'audio, lui, ira de l'éditeur à l'enceinte
              sans passer par ici.
            </span>
          </p>
          <button type="button" onClick={charger} disabled={busy}
            className="inline-flex items-center gap-1.5 text-xs font-medium bg-sky-600 text-white rounded px-2.5 py-1.5 hover:bg-sky-700 disabled:opacity-50">
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Radio size={12} />}
            {busy ? 'Lecture du flux…' : 'Voir les épisodes'}
          </button>
          <p className="flex items-center gap-1 text-[11px] text-emerald-700">
            <ShieldCheck size={11} /> Sortie réseau confirmée, jamais automatique.
          </p>
        </>
      ) : (
        <>
          <div className="flex items-center gap-2 flex-wrap">
            <label className="text-xs text-gray-600">Enceinte :</label>
            <select value={cible} onChange={e => setCible(e.target.value)}
              className="text-xs border border-gray-200 rounded px-2 py-1 bg-white">
              {enceintes.length === 0 && <option value="">— aucune enceinte —</option>}
              {enceintes.map(e => (
                <option key={e.entity_id} value={e.entity_id}>
                  {e.nom}{e.etat === 'unavailable' ? ' (hors ligne)' : ''}
                </option>
              ))}
            </select>
          </div>

          <ul className="divide-y divide-sky-100 rounded border border-sky-100 bg-white max-h-64 overflow-y-auto">
            {episodes.map(ep => (
              <li key={ep.audio_url} className="flex items-center gap-2 px-2.5 py-1.5">
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-gray-800 truncate" title={ep.titre}>{ep.titre}</p>
                  <p className="text-[10px] text-gray-400">
                    {ep.date_pub ? new Date(ep.date_pub).toLocaleDateString('fr-FR') : ''}
                    {ep.duree ? ` · ${duree(ep.duree)}` : ''}
                  </p>
                </div>
                <button type="button" onClick={() => envoyer(ep)} disabled={!cible || envoi !== null}
                  title={cible ? 'Envoyer sur l’enceinte' : 'Choisis d’abord une enceinte'}
                  className={clsx('flex items-center gap-1 text-[11px] px-2 py-1 rounded border shrink-0',
                    cible ? 'border-sky-300 text-sky-700 hover:bg-sky-50' : 'border-gray-200 text-gray-300')}>
                  {envoi === ep.audio_url
                    ? <Loader2 size={11} className="animate-spin" />
                    : <Cast size={11} />}
                  Diffuser
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
