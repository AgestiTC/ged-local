/**
 * IdentiteIntervenant — n° de sécurité sociale et IBAN, chiffrés
 * ==============================================================
 * Les deux seules données de cette fiche dont la fuite ferait un vrai dégât : l'une
 * identifie la personne de façon définitive, l'autre permet un prélèvement. Elles ne
 * servent qu'à remplir la déclaration mensuelle.
 *
 * ## Rien n'est affiché en clair par défaut
 *
 * L'écran ne reçoit qu'un **aperçu masqué** (`•••• 0189`). Le clair s'obtient d'un clic, une
 * donnée à la fois, et **se referme**. Un champ affiché par défaut finit dans une capture
 * d'écran, un partage de session ou une impression — sans que personne l'ait décidé.
 *
 * L'aperçu n'est pas un simple « renseigné / pas renseigné » : les derniers caractères
 * permettent de reconnaître la bonne valeur sans la divulguer. Sans eux, il faudrait ouvrir
 * le clair juste pour vérifier qu'on n'a pas saisi deux fois la même chose au mauvais
 * endroit — l'inverse du but.
 */
import { useState } from 'react'
import { Eye, EyeOff, KeyRound, Loader2, Save, Trash2 } from 'lucide-react'
import { visitesExtrasApi, type Intervenant } from '../../api'
import { useToast } from '../common/Toast'

const CHAMPS = [
  { cle: 'numero_secu' as const, label: 'N° de sécurité sociale',
    aide: 'Tel qu\'il figure sur la carte Vitale — il est demandé à chaque déclaration.' },
  { cle: 'iban' as const, label: 'IBAN',
    aide: 'Pour le virement du salaire. Les espaces sont retirés à l\'enregistrement.' },
]

export default function IdentiteIntervenant({ intervenant, onMaj }:
  { intervenant: Intervenant; onMaj: (i: Intervenant) => void }) {
  const toast = useToast()
  const [saisie, setSaisie] = useState<Record<string, string>>({})
  const [clair, setClair] = useState<Record<string, string>>({})
  const [occupe, setOccupe] = useState<string | null>(null)

  const enregistrer = async (cle: 'numero_secu' | 'iban') => {
    const valeur = (saisie[cle] ?? '').trim()
    if (!valeur) return
    setOccupe(cle)
    try {
      onMaj(await visitesExtrasApi.identite(intervenant.id, { [cle]: valeur }))
      // La saisie est vidée aussitôt enregistrée : laisser la valeur en clair dans un
      // champ de formulaire annulerait tout l'intérêt du chiffrement.
      setSaisie(s => ({ ...s, [cle]: '' }))
      setClair(c => { const { [cle]: _, ...reste } = c; return reste })
      toast.success('Enregistré, chiffré')
    } catch { toast.error('Enregistrement impossible') } finally { setOccupe(null) }
  }

  const basculer = async (cle: 'numero_secu' | 'iban') => {
    if (clair[cle]) { setClair(c => { const { [cle]: _, ...reste } = c; return reste }); return }
    setOccupe(cle)
    try {
      const r = await visitesExtrasApi.reveler(intervenant.id, cle)
      setClair(c => ({ ...c, [cle]: r.valeur }))
    } catch { toast.error('Lecture impossible') } finally { setOccupe(null) }
  }

  return (
    <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2">
      <h4 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
        <KeyRound size={15} className="text-violet-600" /> Identité administrative
      </h4>
      <p className="text-[11px] text-gray-400 leading-relaxed">
        <strong>Chiffrées en base</strong>, jamais affichées en clair par défaut. Elles ne
        servent qu'à remplir la déclaration mensuelle.
      </p>

      {CHAMPS.map(({ cle, label, aide }) => {
        const enregistre = intervenant[cle]
        return (
          <div key={cle} className="border-t border-gray-100 pt-2 flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">
              {label}
            </span>

            {enregistre ? (
              <div className="flex items-center gap-2 flex-wrap">
                <code className="text-sm bg-gray-50 border border-gray-200 rounded px-2 py-1 font-mono">
                  {clair[cle] ?? enregistre}
                </code>
                <button type="button" onClick={() => basculer(cle)} disabled={occupe === cle}
                  title={clair[cle] ? 'Masquer' : 'Afficher en clair — le temps de le recopier'}
                  className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50">
                  {occupe === cle ? <Loader2 size={12} className="animate-spin" />
                    : clair[cle] ? <EyeOff size={12} /> : <Eye size={12} />}
                  {clair[cle] ? 'Masquer' : 'Afficher'}
                </button>
                <button type="button" disabled={occupe === cle}
                  onClick={async () => {
                    if (!confirm(`Effacer ${label.toLowerCase()} ?`)) return
                    setOccupe(cle)
                    try {
                      onMaj(await visitesExtrasApi.identite(intervenant.id, { [cle]: null }))
                      setClair(c => { const { [cle]: _, ...reste } = c; return reste })
                    } finally { setOccupe(null) }
                  }}
                  className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-rose-600">
                  <Trash2 size={12} /> Effacer
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <input value={saisie[cle] ?? ''} autoComplete="off"
                  onChange={e => setSaisie(s => ({ ...s, [cle]: e.target.value }))}
                  onKeyDown={e => { if (e.key === 'Enter') enregistrer(cle) }}
                  placeholder={aide}
                  className="flex-1 text-sm border border-gray-300 rounded-md px-2 py-1.5" />
                <button type="button" onClick={() => enregistrer(cle)}
                  disabled={!((saisie[cle] ?? '').trim()) || occupe === cle}
                  className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-40">
                  <Save size={13} /> Enregistrer
                </button>
              </div>
            )}
          </div>
        )
      })}
    </section>
  )
}
