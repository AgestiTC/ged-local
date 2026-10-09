/**
 * VideoPanel — « Créer une vidéo ! » : un dessin scanné, animé à partir d'un petit scénario
 * (Wan 2.2 dans le ComfyUI de PC-GAME, 5 s).
 *
 * Le scénario s'écrit ou se DICTE (Voxtral, 100 % local). L'enregistrement intégré a besoin
 * d'un contexte sécurisé (route HTTPS) ; par la route HTTP, on retombe sur l'enregistreur du
 * système (`<input capture>`), qui marche partout.
 *
 * La vidéo exige la carte ENTIÈRE : pas de dépassement possible. Le rendu attend qu'elle se
 * libère, sans jamais décharger les modèles des autres (JARVIS).
 */
import { useEffect, useRef, useState } from 'react'
import { Clapperboard, Download, ImagePlus, Loader2, Mic, RefreshCw, Square } from 'lucide-react'
import { videoApi, suivreJob, type EtatVideo } from '../../api'
import { useToast } from '../common/Toast'
import { useProjetPart, useProjetStore } from '../../stores/projetStore'

type Video = { id: string; scenario: string; orientation: string }

function detailErreur(e: unknown, defaut: string) {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  return typeof detail === 'string' ? detail : defaut
}

export default function VideoPanel() {
  const toast = useToast()
  const [etat, setEtat] = useState<EtatVideo | null>(null)
  const [dessin, setDessin] = useState<File | null>(null)
  const [apercu, setApercu] = useState<string | null>(null)
  const [orientation, setOrientation] = useState<string | null>(null)
  const [scenario, setScenario] = useState('')
  const [enCours, setEnCours] = useState<{ progres: number; message: string } | null>(null)
  const [videos, setVideos] = useState<Video[]>([])
  const [enregistre, setEnregistre] = useState(false)
  const [transcription, setTranscription] = useState(false)
  const enregistreur = useRef<MediaRecorder | null>(null)
  const entreeAudio = useRef<HTMLInputElement>(null)
  // Contexte sécurisé = enregistrement dans la page ; sinon, enregistreur du système.
  const micIntegre = typeof window !== 'undefined' && window.isSecureContext && !!navigator.mediaDevices?.getUserMedia

  // Projet ouvert : le scénario et les vidéos produites sont gardés (pas le dessin, trop lourd).
  const rattacher = useProjetStore(s => s.rattacher)
  useProjetPart('video', { scenario, videos }, v => { setScenario(v.scenario ?? ''); setVideos(v.videos ?? []) })

  const verifier = () => { videoApi.etat().then(setEtat).catch(() => setEtat(null)) }
  useEffect(verifier, [])
  useEffect(() => () => { if (apercu) URL.revokeObjectURL(apercu) }, [apercu])

  const choisirDessin = (f: File | undefined) => {
    if (!f) return
    if (!/^image\/(jpeg|png|webp)$/.test(f.type)) { toast.error('Dessin attendu en JPG, PNG ou WebP'); return }
    setDessin(f)
    const url = URL.createObjectURL(f)
    setApercu(url)
    const img = new Image()
    img.onload = () => setOrientation(img.naturalHeight > img.naturalWidth ? 'portrait' : 'paysage')
    img.src = url
  }

  const transcrire = async (audio: Blob) => {
    setTranscription(true)
    try {
      const { texte } = await videoApi.dictee(audio)
      setScenario(s => (s.trim() ? `${s.trim()} ${texte}` : texte))
    } catch (e) {
      toast.error(detailErreur(e, 'Dictée impossible'))
    } finally { setTranscription(false) }
  }

  const basculerMicro = async () => {
    if (!micIntegre) { entreeAudio.current?.click(); return }
    if (enregistre) { enregistreur.current?.stop(); return }
    try {
      const flux = await navigator.mediaDevices.getUserMedia({ audio: true })
      const morceaux: Blob[] = []
      const rec = new MediaRecorder(flux)
      rec.ondataavailable = e => { if (e.data.size) morceaux.push(e.data) }
      rec.onstop = () => {
        flux.getTracks().forEach(t => t.stop())
        setEnregistre(false)
        if (morceaux.length) void transcrire(new Blob(morceaux, { type: rec.mimeType || 'audio/webm' }))
      }
      enregistreur.current = rec
      rec.start()
      setEnregistre(true)
    } catch {
      toast.error('Micro inaccessible (autorisation refusée ?)')
    }
  }

  const blocage = !etat ? 'Vérification…'
    : !etat.configure ? "La création vidéo n'est pas encore reliée à Matothèque (ComfyUI de PC-GAME)."
    : !etat.joignable ? 'ComfyUI injoignable : PC-GAME éteint, ou ComfyUI arrêté.'
    : null
  const occupee = !!etat && etat.joignable && !etat.pret
    ? `La vidéo a besoin de toute la carte graphique, aujourd'hui occupée (${etat.occupants.join(', ') || 'autre usage'}).`
      + " Elle attendra qu'elle se libère (30 min au plus), sans rien décharger."
    : null

  const creer = async () => {
    if (!dessin) { toast.error('Ajoute un dessin'); return }
    if (!scenario.trim()) { toast.error('Décris ce qui doit bouger'); return }
    setEnCours({ progres: 0, message: 'Envoi du dessin…' })
    try {
      const r = await videoApi.creer(dessin, scenario, '')
      const job = await suivreJob(r.job_id, j => setEnCours({ progres: j.progress, message: j.progress_message ?? '' }), 3000)
      if (job.statut === 'completed') {
        setVideos(v => [{ id: r.job_id, scenario, orientation: r.orientation }, ...v])
        rattacher('job', r.job_id, `Vidéo — ${scenario.slice(0, 40)}`)
        toast.success('Vidéo prête')
      } else {
        toast.error(job.erreur ?? 'Création impossible')
      }
    } catch (e) {
      toast.error(detailErreur(e, 'Création impossible'))
    } finally {
      setEnCours(null)
      verifier()
    }
  }

  return (
    <div className="flex flex-col lg:flex-row gap-4 flex-1 min-h-0">
      <section className="w-full lg:w-[460px] shrink-0 bg-white border border-gray-200 rounded-lg p-4 flex flex-col gap-3 overflow-y-auto">
        <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2"><Clapperboard size={15} /> Créer une vidéo</h2>

        <label className="relative flex flex-col items-center justify-center gap-1 min-h-[140px] border-2 border-dashed border-gray-200 rounded-lg cursor-pointer hover:border-blue-400 hover:bg-blue-50/30 text-xs text-gray-500 overflow-hidden">
          {apercu
            ? <img src={apercu} alt="Dessin à animer" className="max-h-56 object-contain" />
            : <><ImagePlus size={22} className="text-gray-300" /> Le dessin scanné (JPG, PNG)</>}
          <input type="file" accept="image/jpeg,image/png,image/webp" className="hidden"
            onChange={e => choisirDessin(e.target.files?.[0])} />
        </label>
        {orientation && <p className="-mt-2 text-xs text-gray-400">Format {orientation} conservé.</p>}

        <div className="text-xs text-gray-600">
          <div className="flex items-center justify-between">
            <span>Scénario — ce qui doit bouger</span>
            {etat && !etat.dictee && (
              <span className="flex items-center gap-1 text-gray-400" title="Le service de transcription (Voxtral, PC-GAME) ne répond pas : écris le scénario.">
                <Mic size={13} /> Dictée indisponible
              </span>
            )}
            {etat?.dictee && (
              <button type="button" onClick={basculerMicro} disabled={transcription || !!enCours}
                title={micIntegre ? (enregistre ? "Arrêter l'enregistrement" : 'Dicter le scénario')
                  : "Dicter avec l'enregistreur de l'appareil (l'enregistrement dans la page demande la route https://ged.tclement.fr)"}
                className={`flex items-center gap-1 px-2 py-1 rounded-md border text-xs disabled:opacity-50 ${enregistre
                  ? 'border-red-300 bg-red-50 text-red-700 animate-pulse' : 'border-gray-200 text-gray-600 hover:bg-gray-50'}`}>
                {transcription ? <Loader2 size={13} className="animate-spin" /> : enregistre ? <Square size={12} /> : <Mic size={13} />}
                {transcription ? 'Transcription…' : enregistre ? 'Arrêter' : 'Dicter'}
              </button>
            )}
            <input ref={entreeAudio} type="file" accept="audio/*" capture className="hidden"
              onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void transcrire(f) }} />
          </div>
          <textarea value={scenario} onChange={e => setScenario(e.target.value)} rows={5}
            placeholder="Ex. : le chat tourne la tête vers nous et remue la queue, les fleurs bougent sous le vent."
            className="mt-1 w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400 placeholder:text-gray-300" />
          <p className="text-gray-400">Court et concret : 5 secondes d'animation. Le style du dessin est conservé.</p>
        </div>

        {(blocage || occupee) && !enCours && (
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 flex items-start gap-2">
            <span className="flex-1">{blocage ?? occupee}</span>
            <button type="button" onClick={verifier} title="Vérifier à nouveau" className="text-amber-600 hover:text-amber-800"><RefreshCw size={13} /></button>
          </p>
        )}

        <button type="button" onClick={creer} disabled={!!blocage || !!enCours || !dessin}
          className="mt-1 flex items-center justify-center gap-2 py-2.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed">
          {enCours ? <Loader2 size={15} className="animate-spin" /> : <Clapperboard size={15} />}
          {enCours ? `${enCours.message || 'Animation…'} ${enCours.progres}%` : 'Créer la vidéo'}
        </button>
        <p className="text-xs text-gray-400">Environ 4 à 5 minutes sur la carte de PC-GAME. Pendant le rendu, JARVIS peut répondre plus lentement.</p>
      </section>

      <section className="flex-1 min-w-0 bg-white border border-gray-200 rounded-lg p-4 flex flex-col gap-3 overflow-y-auto">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Vidéos</h2>
        {videos.length === 0 && <p className="text-sm text-gray-400">Les vidéos créées apparaîtront ici.</p>}
        {videos.map(v => (
          <div key={v.id} className="border border-gray-100 rounded-lg p-3 flex flex-col gap-2">
            <div className="flex items-center gap-2 text-sm">
              <span className="flex-1 truncate font-medium text-gray-700" title={v.scenario}>{v.scenario}</span>
              <a href={videoApi.fichierUrl(v.id)} download className="text-gray-400 hover:text-blue-600" title="Télécharger le MP4"><Download size={15} /></a>
            </div>
            <video controls loop src={videoApi.fichierUrl(v.id)}
              className={`rounded-md bg-black ${v.orientation === 'portrait' ? 'max-h-[480px] self-center' : 'w-full'}`} />
          </div>
        ))}
      </section>
    </div>
  )
}
