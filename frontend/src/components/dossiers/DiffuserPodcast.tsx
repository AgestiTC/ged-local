/**
 * Diffuser un épisode de podcast sur une enceinte de la maison (via Home Assistant).
 *
 * Matothèque **catalogue**, elle ne rejoue pas : il n'y a volontairement aucun lecteur ici.
 * On n'écoute pas un podcast devant sa GED — on l'écoute en cuisinant. Ce panneau fait donc
 * le seul geste qui apporte quelque chose : envoyer l'épisode dans la pièce où l'on est.
 *
 * Trois sorties réseau, toutes sur clic explicite et annoncées avant :
 *   1. chercher l'adresse du flux dans l'annuaire (sort : le nom du podcast) ;
 *   2. lire le flux chez son éditeur (sort : l'URL du flux) → la liste des épisodes ;
 *   3. demander à Home Assistant (LAN) de jouer l'audio sur l'enceinte choisie.
 * L'audio lui-même ne transite jamais par Matothèque : c'est l'enceinte qui va le chercher.
 */
import { useMemo, useState } from 'react'
import {
  AlertTriangle, ArrowDownWideNarrow, ArrowUpNarrowWide, Cast, Globe, Loader2, Pencil, Radio,
  Rss, Search, ShieldCheck,
} from 'lucide-react'
import { clsx } from 'clsx'
import {
  dossiersApi, maisonApi,
  type CandidatFlux, type EpisodePodcast, type Enceinte, type Ressource,
} from '../../api'
import { useToast } from '../common/Toast'

/** « 3723 » → « 1 h 02 ». Une durée en secondes ne se lit pas. */
function duree(s: number | null): string {
  if (!s) return ''
  const h = Math.floor(s / 3600)
  const m = Math.round((s % 3600) / 60)
  return h ? `${h} h ${String(m).padStart(2, '0')}` : `${m} min`
}

/**
 * Ces hôtes servent une PAGE d'écoute, jamais un flux. Le signaler tout de suite évite
 * l'erreur qu'on a eue en base : un lien de recherche Deezer rangé dans `flux_url`, qui ne
 * se révélait faux qu'au moment de lire les épisodes, sous la forme d'un « format illisible ».
 */
const PLATEFORMES = ['spotify.com', 'deezer.com', 'podcasts.apple.com', 'itunes.apple.com',
  'music.amazon', 'youtube.com', 'youtu.be']
const plateforme = (url: string): string | undefined =>
  PLATEFORMES.find(h => url.toLowerCase().includes(h))

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

  // ── Le flux ────────────────────────────────────────────────────────────────
  // `fluxActuel` est ce qui est EN BASE ; `saisie` est ce que l'utilisateur tape. Les séparer
  // permet d'afficher l'adresse enregistrée sans qu'un début de correction la fasse
  // disparaître de l'écran.
  const [fluxActuel, setFluxActuel] = useState(ressource.flux_url ?? '')
  const [saisie, setSaisie] = useState(ressource.flux_url ?? '')
  const [edition, setEdition] = useState(!ressource.flux_url)
  const [sauve, setSauve] = useState(false)
  const [candidats, setCandidats] = useState<CandidatFlux[] | null>(null)
  const [cherche, setCherche] = useState(false)

  // Ordre d'écoute. Le flux arrive du plus récent au plus ancien — c'est le bon défaut pour
  // suivre une émission, mais pas pour en découvrir une : on la reprend alors depuis le début.
  const [ordre, setOrdre] = useState<'recent' | 'ancien'>('recent')

  // Filtre sur le titre. Un catalogue de 500 épisodes ne se parcourt pas : on y cherche un
  // sujet (« sommeil », « allaitement »), et le tri seul n'y donne pas accès.
  const [filtre, setFiltre] = useState('')

  const episodesTries = useMemo(() => {
    if (!episodes) return []
    const q = filtre.trim().toLowerCase()
    // Recherche insensible à la casse ET aux accents : « épisode » doit se trouver en tapant
    // « episode », personne ne compose les accents dans un champ de filtre.
    // La plage des diacritiques est écrite en échappement et non en caractères bruts : des
    // marques combinantes sont invisibles dans un éditeur et se perdent au premier copier-coller.
    const sansAccent = (s: string) =>
      s.toLowerCase().normalize('NFD').replace(RegExp('[\u0300-\u036f]', 'g'), '')
    const cible = sansAccent(q)
    const retenus = cible
      ? episodes.filter(e => sansAccent(e.titre).includes(cible))
      : episodes
    const date = (e: EpisodePodcast) => (e.date_pub ? Date.parse(e.date_pub) : NaN)
    return [...retenus].sort((a, b) => {
      const [x, y] = [date(a), date(b)]
      // Un épisode sans date ne peut être placé nulle part de façon sensée : il va à la fin,
      // dans les deux sens, plutôt que de sauter d'un bout à l'autre selon le tri.
      if (Number.isNaN(x) && Number.isNaN(y)) return 0
      if (Number.isNaN(x)) return 1
      if (Number.isNaN(y)) return -1
      return ordre === 'recent' ? y - x : x - y
    })
  }, [episodes, ordre, filtre])

  const suspect = plateforme(fluxActuel)

  const enregistrerFlux = async (url: string) => {
    const propre = url.trim()
    if (!/^https?:\/\//i.test(propre)) { toast.error('Une URL de flux commence par http:// ou https://'); return }
    setSauve(true)
    try {
      await dossiersApi.updateRessource(ressource.id, { flux_url: propre })
      setFluxActuel(propre)
      setSaisie(propre)
      setEdition(false)
      setCandidats(null)
      setEpisodes(null)          // le flux a changé : la liste affichée n'est plus la sienne
      onMaj?.()
      toast.success('Flux enregistré.')
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Enregistrement impossible.')
    } finally { setSauve(false) }
  }

  // Sortie Internet : ne part QUE sur ce clic, et n'envoie que le nom du podcast.
  const chercherFlux = async () => {
    setCherche(true)
    try {
      const r = await dossiersApi.chercherFlux(ressource.id)
      setCandidats(r.candidats)
      if (r.candidats.length === 0) toast.info('Aucun flux trouvé sous ce nom — saisis l’adresse à la main.')
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Recherche impossible.')
    } finally { setCherche(false) }
  }

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

  /** Rappel discret de l'adresse en service, avec le moyen de la corriger. */
  const ligneFlux = (
    <p className="flex items-center gap-1.5 text-[11px] text-gray-500 min-w-0">
      <Rss size={11} className="shrink-0 text-sky-500" />
      <span className="truncate" title={fluxActuel}>{fluxActuel}</span>
      <button type="button" onClick={() => { setEdition(true); setSaisie(fluxActuel) }}
        className="ml-1 inline-flex items-center gap-1 shrink-0 text-sky-700 hover:underline">
        <Pencil size={10} /> Modifier
      </button>
    </p>
  )

  return (
    <div className="mt-2 rounded-md border border-sky-200 bg-sky-50 p-2.5 space-y-2">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-sky-700">
        <Cast size={11} /> Diffuser sur une enceinte
        <button type="button" onClick={onFerme}
          className="ml-auto normal-case tracking-normal font-normal text-gray-400 hover:text-gray-600">
          Fermer
        </button>
      </div>

      {edition ? (
        /* ── Choisir le flux ────────────────────────────────────────────────
           Sans flux RSS il n'y a pas d'épisodes — mais c'est réparable ici, plutôt que de
           renvoyer vers le formulaire d'édition de la fiche. */
        <>
          <p className="text-xs text-sky-900">
            Il faut l'<strong>URL du flux RSS</strong> de ce podcast : c'est elle qui porte les
            épisodes et leur audio. Une page Spotify, Deezer ou Apple Podcasts n'est pas un flux.
          </p>

          <div className="flex items-center gap-2 flex-wrap">
            <input value={saisie} onChange={e => setSaisie(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') enregistrerFlux(saisie) }}
              placeholder="https://feeds.exemple.fr/mon-podcast.xml"
              className="flex-1 min-w-[15rem] text-xs border border-sky-200 rounded px-2 py-1.5 bg-white" />
            <button type="button" onClick={() => enregistrerFlux(saisie)} disabled={sauve || !saisie.trim()}
              className="inline-flex items-center gap-1.5 text-xs font-medium bg-sky-600 text-white rounded px-2.5 py-1.5 hover:bg-sky-700 disabled:opacity-50">
              {sauve ? <Loader2 size={12} className="animate-spin" /> : <Rss size={12} />} Enregistrer
            </button>
            {fluxActuel && (
              <button type="button" onClick={() => { setEdition(false); setSaisie(fluxActuel) }}
                className="text-xs text-gray-500 hover:text-gray-700">Annuler</button>
            )}
          </div>

          {plateforme(saisie) && (
            <p className="flex items-start gap-1.5 text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <span>
                <strong>{plateforme(saisie)}</strong> sert une page d'écoute, pas un flux. Enregistrée
                telle quelle, cette adresse échouera à la lecture. Utilise « Chercher le flux ».
              </span>
            </p>
          )}

          {/* ── Le faire chercher ───────────────────────────────────────────── */}
          {candidats === null ? (
            <>
              <button type="button" onClick={chercherFlux} disabled={cherche}
                className="inline-flex items-center gap-1.5 text-xs font-medium border border-sky-300 text-sky-700 bg-white rounded px-2.5 py-1.5 hover:bg-sky-50 disabled:opacity-50">
                {cherche ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
                {cherche ? 'Recherche…' : 'Chercher le flux pour moi'}
              </button>
              <p className="flex items-start gap-1.5 text-[11px] text-gray-500">
                <Globe size={11} className="mt-0.5 shrink-0" />
                <span>
                  Interroge l'annuaire Apple Podcasts. <strong>Seuls le nom du podcast et son
                  auteur sortent</strong> — aucun document, aucun tag, aucun identifiant.
                  Rien n'est enregistré : tu choisis le bon résultat.
                </span>
              </p>
            </>
          ) : (
            <ul className="divide-y divide-sky-100 rounded border border-sky-100 bg-white max-h-56 overflow-y-auto">
              {candidats.length === 0 && (
                <li className="px-2.5 py-2 text-xs text-gray-500">
                  Aucun résultat. L'émission n'est peut-être pas dans l'annuaire : cherche
                  « {ressource.titre} RSS » dans un navigateur et colle l'adresse ci-dessus.
                </li>
              )}
              {candidats.map(c => (
                <li key={c.feed_url} className="flex items-center gap-2 px-2.5 py-1.5">
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-gray-800 truncate" title={c.titre}>{c.titre}</p>
                    <p className="text-[10px] text-gray-400 truncate">
                      {c.auteur}{c.nb_episodes ? ` · ${c.nb_episodes} épisodes` : ''}
                    </p>
                  </div>
                  <button type="button" onClick={() => enregistrerFlux(c.feed_url)} disabled={sauve}
                    className="shrink-0 text-[11px] px-2 py-1 rounded border border-sky-300 text-sky-700 hover:bg-sky-50 disabled:opacity-50">
                    C'est celui-ci
                  </button>
                </li>
              ))}
            </ul>
          )}
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

          {suspect && (
            <p className="flex items-start gap-1.5 text-[11px] text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1.5">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <span>
                L'adresse enregistrée pointe vers <strong>{suspect}</strong>, qui sert une page
                d'écoute et non un flux : la lecture va échouer. Corrige-la avec « Modifier »,
                ou laisse Matothèque la chercher.
              </span>
            </p>
          )}

          <button type="button" onClick={charger} disabled={busy}
            className="inline-flex items-center gap-1.5 text-xs font-medium bg-sky-600 text-white rounded px-2.5 py-1.5 hover:bg-sky-700 disabled:opacity-50">
            {busy ? <Loader2 size={12} className="animate-spin" /> : <Radio size={12} />}
            {busy ? 'Lecture du flux…' : 'Voir les épisodes'}
          </button>
          {ligneFlux}
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

            {/* Le compte dit ce qu'on regarde : filtrer sans le montrer laisse croire que
                l'émission ne compte que douze épisodes. */}
            <span className="text-[11px] text-gray-400">
              {filtre.trim() && episodesTries.length !== episodes.length
                ? `${episodesTries.length} sur ${episodes.length} épisodes`
                : `${episodes.length} épisodes`}
            </span>

            <button type="button" onClick={() => setOrdre(o => o === 'recent' ? 'ancien' : 'recent')}
              title={ordre === 'recent'
                ? 'Actuellement du plus récent au plus ancien — cliquer pour inverser'
                : 'Actuellement du plus ancien au plus récent — cliquer pour inverser'}
              className="ml-auto inline-flex items-center gap-1 text-[11px] text-gray-600 border border-gray-200 bg-white rounded px-2 py-1 hover:bg-gray-50">
              {ordre === 'recent'
                ? <><ArrowDownWideNarrow size={11} /> Plus récents d'abord</>
                : <><ArrowUpNarrowWide size={11} /> Plus anciens d'abord</>}
            </button>
          </div>

          {/* Le filtre reste LOCAL : la liste est déjà chargée, chercher ne redemande rien au
              réseau et ne sort donc pas. */}
          <div className="relative">
            <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400" />
            <input value={filtre} onChange={e => setFiltre(e.target.value)}
              placeholder="Filtrer les épisodes (sommeil, allaitement, portage…)"
              aria-label="Filtrer les épisodes par titre"
              className="w-full text-xs border border-sky-200 rounded pl-7 pr-7 py-1.5 bg-white" />
            {filtre && (
              <button type="button" onClick={() => setFiltre('')} aria-label="Effacer le filtre"
                className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700 px-1">
                ×
              </button>
            )}
          </div>

          <ul className="divide-y divide-sky-100 rounded border border-sky-100 bg-white max-h-64 overflow-y-auto">
            {episodesTries.length === 0 && (
              <li className="px-2.5 py-3 text-xs text-gray-500">
                Aucun épisode ne contient « {filtre.trim()} ».
              </li>
            )}
            {episodesTries.map(ep => (
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
          {ligneFlux}
        </>
      )}
    </div>
  )
}
