/**
 * Rangement › Carte › Déclarer — depuis une Source NAS (étape 7 du plan « Rangement sur Sources SMB »).
 * On choisit la Source « Rangement », le partage, puis le dossier, dans le navigateur des Sources
 * (`SmbFolderPicker`) : aucun chemin à taper, aucun montage à ajouter au serveur. Le serveur revérifie
 * le dossier par SMB, avec le compte de la Source, avant d'enregistrer l'emplacement.
 */
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { extractApiError, sourcesApi, type Source } from '../../api'
import { inventaireApi, type EmplacementInventaire } from '../../api/inventaire'
import { useToast } from '../common/Toast'
import SmbFolderPicker from '../ged/SmbFolderPicker'

/** Libellé proposé : le dernier dossier choisi, ou le nom du partage. */
export function libelleParDefaut(partage: string, chemin: string): string {
  const morceaux = chemin.split('/').filter(Boolean)
  return morceaux.length ? morceaux[morceaux.length - 1] : partage
}

export default function DeclarerSmb({ onDeclare, onAnnuler }: {
  onDeclare: (e: EmplacementInventaire) => void
  onAnnuler: () => void
}) {
  const toast = useToast()
  const [sources, setSources] = useState<Source[] | null>(null)
  const [sourceId, setSourceId] = useState('')
  const [libelle, setLibelle] = useState('')
  const [envoi, setEnvoi] = useState(false)

  useEffect(() => {
    sourcesApi.list()
      .then(toutes => {
        const rangement = toutes.filter(s => s.type === 'smb' && s.usage === 'rangement')
        setSources(rangement)
        if (rangement.length === 1) setSourceId(rangement[0].id)
      })
      .catch(err => { setSources([]); toast.error(extractApiError(err, 'Lecture des sources impossible')) })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const declarer = async (choix?: { partage: string | null; chemin: string }) => {
    if (!choix?.partage || envoi) return
    const nom = libelle.trim() || libelleParDefaut(choix.partage, choix.chemin)
    setEnvoi(true)
    try {
      const e = await inventaireApi.declarerSmb(nom, sourceId, choix.partage, choix.chemin)
      toast.success(`« ${e.libelle} » déclaré. Lance son premier scan, ou attends la tournée de nuit.`)
      onDeclare(e)
    } catch (err) {
      // Refus métier : {code, message} — dossier introuvable, NAS injoignable, déjà déclaré…
      const detail = (err as { response?: { data?: { detail?: { message?: string } | string } } })?.response?.data?.detail
      toast.error((typeof detail === 'object' && detail?.message) || extractApiError(err, 'Déclaration refusée'))
    } finally { setEnvoi(false) }
  }

  if (sources === null) return <p className="text-xs text-gray-500"><Loader2 size={13} className="inline animate-spin" /> Sources…</p>

  if (sources.length === 0) {
    return (
      <p className="text-xs text-gray-600 leading-relaxed">
        Aucune source n'est réservée au Rangement. Dans <b>Paramètres › Sources NAS/SMB</b>, ouvrez la source
        du compte de rangement et cochez <b>« Réservée au Rangement »</b> : ses partages apparaîtront ici.
      </p>
    )
  }

  const source = sources.find(s => s.id === sourceId) ?? null
  return (
    <div className="space-y-2">
      {sources.length > 1 && (
        <label className="block text-xs text-gray-600">Source
          <select value={sourceId} onChange={e => setSourceId(e.target.value)}
            className="mt-1 w-full px-2 py-1.5 text-sm border border-gray-300 rounded bg-white">
            <option value="">— choisir —</option>
            {sources.map(s => <option key={s.id} value={s.id}>{s.libelle} ({s.identifiant ?? 'invité'} sur {s.hote})</option>)}
          </select>
        </label>
      )}
      <label className="block text-xs text-gray-600">Libellé <span className="text-gray-400">(facultatif : le nom du dossier choisi)</span>
        <input value={libelle} onChange={e => setLibelle(e.target.value)} maxLength={100}
          className="mt-1 w-full px-2 py-1.5 text-sm border border-gray-300 rounded" />
      </label>
      {source && (
        <SmbFolderPicker key={source.id} source={source} libelleBouton={envoi ? 'Déclaration…' : 'Déclarer ce dossier'}
          onPick={(_prefixe, _label, choix) => void declarer(choix)} onClose={onAnnuler} />
      )}
      <p className="text-xs text-gray-500">
        Lu avec le compte de la source ({source?.identifiant ?? '—'}). L'inventaire ne fait que lire ; seul un lot
        que vous validez déplace des fichiers.
      </p>
    </div>
  )
}
