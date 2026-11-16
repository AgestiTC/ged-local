/**
 * Paramètres › Rangement — règles de nommage (16/11/2026). Une règle par CATÉGORIE (épisodes, films,
 * musique, photos) plus les défauts communs : allumée ou non, et le format attendu. Elles servent aux
 * statistiques « Noms de fichiers » de Rangement › Carte ; rien n'est renommé à partir d'ici.
 */
import { useEffect, useState } from 'react'
import { Loader2, Save } from 'lucide-react'
import { extractApiError } from '../../api'
import { nommageApi, type RegleNommage } from '../../api/inventaire'
import { useToast } from '../common/Toast'

export default function ReglesNommage() {
  const toast = useToast()
  const [regles, setRegles] = useState<RegleNommage[] | null>(null)
  const [occupe, setOccupe] = useState(false)

  useEffect(() => {
    nommageApi.regles().then(setRegles).catch(err => toast.error(extractApiError(err, 'Lecture des règles impossible')))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const changer = (code: string, champ: Partial<Pick<RegleNommage, 'actif' | 'format'>>) =>
    setRegles(rs => rs && rs.map(r => (r.code === code ? { ...r, ...champ } : r)))

  const enregistrer = async () => {
    if (!regles) return
    setOccupe(true)
    try {
      setRegles(await nommageApi.enregistrer(Object.fromEntries(regles.map(r => [r.code, { actif: r.actif, format: r.format }]))))
      toast.success('Règles de nommage enregistrées — les statistiques de Rangement › Carte en tiennent compte.')
    } catch (err) { toast.error(extractApiError(err, 'Enregistrement impossible')) }
    finally { setOccupe(false) }
  }

  if (regles === null) return <Loader2 size={18} className="animate-spin text-gray-400" />
  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Une règle par type de contenu : c'est ce qu'est le fichier (épisode, film, piste) qui fait un bon nom, l'extension
        sert seulement à le reconnaître. Les formats sont ceux de Plex. Elles alimentent « Noms de fichiers » dans
        Rangement › Carte ; rien n'est renommé d'ici.
      </p>
      <ul className="space-y-2">
        {regles.map(r => {
          const fmt = r.formats.find(f => f.code === r.format) ?? r.formats[0]
          return (
            <li key={r.code} className="border border-gray-200 rounded-lg p-3 text-sm space-y-1">
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 font-medium min-w-[11rem]">
                  <input type="checkbox" checked={r.actif} onChange={e => changer(r.code, { actif: e.target.checked })} />
                  {r.libelle}
                </label>
                {r.formats.length > 1
                  ? <select value={r.format} disabled={!r.actif} aria-label={`Format — ${r.libelle}`}
                      onChange={e => changer(r.code, { format: e.target.value })}
                      className="px-2 py-1 border border-gray-300 rounded text-sm disabled:opacity-50">
                      {r.formats.map(f => <option key={f.code} value={f.code}>{f.libelle}</option>)}
                    </select>
                  : <span className="text-gray-600">{fmt.libelle}</span>}
                <span className="font-mono text-xs text-gray-500">ex. {fmt.exemple}</span>
              </div>
              <p className="text-xs text-gray-500">{r.description}</p>
            </li>
          )
        })}
      </ul>
      <button type="button" disabled={occupe} onClick={() => void enregistrer()}
        className="flex items-center gap-1 text-sm px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
        <Save size={15} /> Enregistrer</button>
    </div>
  )
}
