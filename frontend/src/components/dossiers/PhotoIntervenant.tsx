/**
 * PhotoIntervenant — le portrait d'une personne suivie
 * ====================================================
 * **Trois entrées, un seul chemin de code** : glisser-déposer, import classique, et appareil
 * photo. Les trois produisent un `File`, donc un seul gestionnaire — et une quatrième entrée
 * s'ajoute quand le navigateur le permet (voir plus bas).
 *
 * ## L'aperçu caméra dépend de la ROUTE d'accès, pas de l'appareil
 *
 * `getUserMedia()` n'existe que dans un **contexte sécurisé**. Matothèque est joignable par
 * deux chemins : `https://ged.tclement.fr` (proxy TLS) en offre un, `http://<ip>:3003` non.
 * Le même utilisateur bascule de l'un à l'autre selon qu'il est chez lui ou en VPN — on
 * **teste donc `window.isSecureContext`** plutôt que de supposer.
 *
 * Et même là où l'aperçu est possible, `<input capture>` reste proposé : il ouvre
 * l'application photo **du système**, qui fait de meilleurs clichés qu'un flux vidéo dans une
 * page, et fonctionne partout.
 *
 * ## Ce qui part sur le réseau
 *
 * La photo est **redimensionnée dans le navigateur** avant l'envoi (voir `utils/image`) :
 * 5 Mo deviennent ~150 Ko. La fiche se remplit debout, pendant la visite, au bout d'un VPN
 * sur données mobiles — c'est la différence entre un envoi qui aboutit et un envoi qu'on
 * abandonne. L'envoi est **séparé de la saisie** : une photo qui échoue n'emporte jamais les
 * champs déjà remplis.
 */
import { useEffect, useRef, useState } from 'react'
import { Camera, ImageUp, Loader2, Trash2, UserRound, X } from 'lucide-react'
import { clsx } from 'clsx'
import { visitesApi } from '../../api'
import { preparerPhoto } from '../../utils/image'
import { useToast } from '../common/Toast'

/** Initiales, tant qu'il n'y a pas de photo. Mieux qu'une silhouette générique. */
function initiales(prenom: string | null, nom: string): string {
  return [(prenom ?? '')[0], nom[0]].filter(Boolean).join('').toUpperCase() || '?'
}

interface Props {
  id: string
  nom: string
  prenom: string | null
  photo: boolean
  accord: boolean
  onChange: () => void
  onAccord: (v: boolean) => void
}

export default function PhotoIntervenant({ id, nom, prenom, photo, accord, onChange, onAccord }: Props) {
  const toast = useToast()
  const [envoi, setEnvoi] = useState(false)
  const [survol, setSurvol] = useState(false)
  const [camera, setCamera] = useState(false)
  // Change à chaque dépôt : sans lui, le navigateur re-servirait l'ancienne photo depuis
  // son cache, et on croirait l'envoi raté.
  const [version, setVersion] = useState(0)
  const fluxRef = useRef<MediaStream | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)

  const url = `${import.meta.env.VITE_API_URL ?? ''}/api/emploi-domicile/intervenants/${id}/photo?v=${version}`
  // Le seul cas SANS repli possible : l'aperçu intégré demande un contexte sécurisé.
  const apercuPossible = window.isSecureContext && !!navigator.mediaDevices?.getUserMedia

  const arreterCamera = () => {
    fluxRef.current?.getTracks().forEach(t => t.stop())
    fluxRef.current = null
    setCamera(false)
  }

  // Le flux vidéo continue tant qu'on ne l'arrête pas : quitter la fiche sans couper
  // laisserait la LED de la caméra allumée, ce qui est le genre de détail qui inquiète.
  useEffect(() => arreterCamera, [])

  const envoyer = async (fichier: File) => {
    setEnvoi(true)
    try {
      await visitesApi.envoyerPhoto(id, await preparerPhoto(fichier))
      setVersion(v => v + 1)
      onChange()
      toast.success('Photo enregistrée')
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
      toast.error(detail || 'Photo non enregistrée')
    } finally {
      setEnvoi(false)
    }
  }

  const ouvrirCamera = async () => {
    try {
      const flux = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' }, audio: false,
      })
      fluxRef.current = flux
      setCamera(true)
      // Le rendu doit avoir eu lieu pour que la balise <video> existe.
      requestAnimationFrame(() => { if (videoRef.current) videoRef.current.srcObject = flux })
    } catch {
      toast.error('Caméra indisponible — utilisez « Appareil photo »')
    }
  }

  const capturer = () => {
    const video = videoRef.current
    if (!video) return
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d')?.drawImage(video, 0, 0)
    canvas.toBlob(blob => {
      if (blob) envoyer(new File([blob], 'portrait.jpg', { type: 'image/jpeg' }))
      arreterCamera()
    }, 'image/jpeg', 0.9)
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-start gap-3">
        {/* La vignette est aussi la zone de dépôt : viser une zone séparée quand on a déjà
            le fichier sous le curseur serait un pas de plus pour rien. */}
        <div
          onDragOver={e => { e.preventDefault(); setSurvol(true) }}
          onDragLeave={() => setSurvol(false)}
          onDrop={e => {
            e.preventDefault(); setSurvol(false)
            const f = e.dataTransfer.files?.[0]
            if (f) envoyer(f)
          }}
          className={clsx(
            'relative w-24 h-24 rounded-xl border-2 border-dashed shrink-0 overflow-hidden',
            'flex items-center justify-center bg-gray-50 transition-colors',
            survol ? 'border-blue-400 bg-blue-50' : 'border-gray-200')}>
          {photo ? (
            <img src={url} alt={`Portrait de ${prenom ?? ''} ${nom}`.trim()}
              className="w-full h-full object-cover" />
          ) : (
            <span className="text-xl font-semibold text-gray-300">{initiales(prenom, nom)}</span>
          )}
          {envoi && (
            <span className="absolute inset-0 bg-white/70 flex items-center justify-center">
              <Loader2 size={20} className="animate-spin text-blue-600" />
            </span>
          )}
        </div>

        <div className="flex flex-col gap-1.5 min-w-0">
          <p className="text-[11px] text-gray-400 leading-relaxed">
            Glissez une image sur la vignette, ou&nbsp;:
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            <label className="flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 cursor-pointer">
              <ImageUp size={13} /> Importer
              <input type="file" accept="image/*" className="hidden" disabled={envoi}
                onChange={e => { const f = e.target.files?.[0]; if (f) envoyer(f); e.target.value = '' }} />
            </label>

            {/* `capture` ouvre l'appareil photo DU SYSTÈME : meilleurs clichés qu'un flux
                dans une page, et aucun contexte sécurisé requis. */}
            <label className="flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 cursor-pointer">
              <Camera size={13} /> Appareil photo
              <input type="file" accept="image/*" capture="environment" className="hidden" disabled={envoi}
                onChange={e => { const f = e.target.files?.[0]; if (f) envoyer(f); e.target.value = '' }} />
            </label>

            {apercuPossible && !camera && (
              <button type="button" onClick={ouvrirCamera} disabled={envoi}
                title="Aperçu dans la page — disponible parce que vous êtes en HTTPS"
                className="flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">
                <Camera size={13} /> Prendre ici
              </button>
            )}

            {photo && (
              <button type="button" disabled={envoi}
                onClick={async () => {
                  if (!confirm('Supprimer le portrait ?')) return
                  await visitesApi.supprimerPhoto(id)
                  setVersion(v => v + 1); onChange()
                }}
                className="flex items-center gap-1 text-xs px-2 py-1.5 text-gray-400 hover:text-rose-600">
                <Trash2 size={13} /> Retirer
              </button>
            )}
          </div>

          {photo && (
            // Le portrait d'une personne identifiée n'est pas notre donnée : l'accord se
            // demande une fois, et se voit.
            <label className="flex items-start gap-1.5 text-[11px] text-gray-500">
              <input type="checkbox" checked={accord} className="mt-0.5"
                onChange={e => onAccord(e.target.checked)} />
              <span>Photo ajoutée <strong>avec son accord</strong>. Elle reste sur votre
                serveur, n'est pas indexée dans la GED, et part avec la fiche.</span>
            </label>
          )}
        </div>
      </div>

      {camera && (
        <div className="border border-blue-200 bg-blue-50/50 rounded-lg p-2 flex flex-col gap-2">
          <video ref={videoRef} autoPlay playsInline muted
            className="w-full max-w-sm rounded-md bg-black" />
          <div className="flex items-center gap-2">
            <button type="button" onClick={capturer} disabled={envoi}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700">
              <Camera size={14} /> Photographier
            </button>
            <button type="button" onClick={arreterCamera}
              className="flex items-center gap-1 text-sm px-2 py-1.5 text-gray-500 hover:text-gray-700">
              <X size={14} /> Annuler
            </button>
          </div>
        </div>
      )}

      {!photo && !apercuPossible && (
        <p className="text-[11px] text-gray-400">
          <UserRound size={11} className="inline -mt-0.5" /> L'aperçu dans la page demande une
          connexion sécurisée (HTTPS). « Appareil photo » fonctionne dans tous les cas.
        </p>
      )}
    </div>
  )
}
