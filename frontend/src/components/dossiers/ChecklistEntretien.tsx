/**
 * ChecklistEntretien — la checklist d'UN entretien
 * ================================================
 * La checklist appartient à l'**entretien**, pas à la personne : une seconde visite chez la
 * même assistante maternelle a ses propres réponses, et c'est **l'écart entre les deux** qui
 * informe. Un second entretien peut reprendre les réponses du premier — celui-ci n'est
 * jamais modifié, donc la comparaison reste possible.
 *
 * **Chaque réponse part seule, au fil de la saisie.** Pas de bouton « Enregistrer » : la
 * fiche se remplit debout, pendant la visite, souvent au bout d'un VPN sur données mobiles.
 * Perdre vingt réponses sur une coupure serait le scénario le plus probable et le plus
 * coûteux — c'est aussi pour ça que le texte libre part au `blur` et non à chaque frappe.
 *
 * Trois avis seulement : **ça va / à revoir / non**. Une échelle plus fine donnerait
 * l'illusion d'une mesure là où il n'y a qu'une impression — et ralentirait une saisie qui
 * se fait en marchant.
 */
import { useState } from 'react'
import { Check, CircleSlash, HelpCircle, TriangleAlert } from 'lucide-react'
import { clsx } from 'clsx'
import {
  visitesApi, type AvisReponse, type Entretien, type GroupeChecklist,
} from '../../api'
import CollapsibleSection from '../common/CollapsibleSection'
import { useToast } from '../common/Toast'

const AVIS: { valeur: AvisReponse; label: string; Icon: typeof Check; actif: string }[] = [
  { valeur: 'ok', label: 'ça va', Icon: Check, actif: 'bg-emerald-600 text-white border-emerald-600' },
  { valeur: 'reserve', label: 'à revoir', Icon: TriangleAlert, actif: 'bg-amber-500 text-white border-amber-500' },
  { valeur: 'non', label: 'non', Icon: CircleSlash, actif: 'bg-rose-600 text-white border-rose-600' },
]

interface Props {
  entretien: Entretien
  checklist: GroupeChecklist[]
  /** Réponses de l'entretien PRÉCÉDENT, pour signaler ce qui a changé. */
  precedentes?: Entretien['reponses']
  onChange: (e: Entretien) => void
  lectureSeule?: boolean
}

export default function ChecklistEntretien({
  entretien, checklist, precedentes, onChange, lectureSeule,
}: Props) {
  const toast = useToast()
  const [enCours, setEnCours] = useState<string | null>(null)

  const enregistrer = async (cle: string, avis: AvisReponse | null, texte: string | null) => {
    if (lectureSeule) return
    setEnCours(cle)
    try {
      onChange(await visitesApi.repondre(entretien.id, cle, avis, texte))
    } catch {
      toast.error('Réponse non enregistrée')
    } finally {
      setEnCours(null)
    }
  }

  const total = checklist.reduce((n, g) => n + g.questions.length, 0)

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2 text-xs text-gray-500">
        <span className="font-medium text-gray-700">
          {entretien.nb_repondues} / {total} question{total > 1 ? 's' : ''} renseignée{entretien.nb_repondues > 1 ? 's' : ''}
        </span>
        <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden max-w-[12rem]">
          <div className="h-full bg-emerald-500 transition-all"
            style={{ width: `${total ? (entretien.nb_repondues / total) * 100 : 0}%` }} />
        </div>
        <span className="text-gray-300">·</span>
        <span>enregistrement automatique</span>
      </div>

      {checklist.map((groupe, gi) => {
        const repondues = groupe.questions.filter(q => entretien.reponses[q.cle]).length
        return (
          <CollapsibleSection key={groupe.titre} id={`chk-${entretien.id}-${gi}`}
            defaultOpen={gi === 0} title={groupe.titre}
            right={<span className="text-xs text-gray-400 mr-1">{repondues}/{groupe.questions.length}</span>}>
            <ul className="flex flex-col gap-3 pt-1">
              {groupe.questions.map(q => {
                const rep = entretien.reponses[q.cle]
                const avant = precedentes?.[q.cle]
                // « A changé » ne se calcule que sur l'AVIS : le texte libre bouge à chaque
                // reformulation, et signaler un changement à chaque virgule ne dirait rien.
                const change = avant && rep && avant.avis && rep.avis && avant.avis !== rep.avis
                return (
                  <li key={q.cle} className="flex flex-col gap-1.5">
                    <p className="text-sm text-gray-700 leading-snug">{q.texte}</p>
                    <p className="text-[11px] text-gray-400 italic leading-snug flex items-start gap-1">
                      <HelpCircle size={11} className="mt-0.5 shrink-0" /> {q.pourquoi}
                    </p>

                    <div className="flex flex-wrap items-center gap-1.5">
                      {AVIS.map(({ valeur, label, Icon, actif }) => {
                        const choisi = rep?.avis === valeur
                        return (
                          <button key={valeur} type="button" disabled={lectureSeule || enCours === q.cle}
                            onClick={() => enregistrer(q.cle, choisi ? null : valeur, rep?.texte ?? null)}
                            className={clsx(
                              'flex items-center gap-1 text-xs px-2 py-1.5 rounded-md border transition-colors disabled:opacity-50',
                              choisi ? actif : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50')}>
                            <Icon size={12} /> {label}
                          </button>
                        )
                      })}
                      {change && (
                        <span title={`Au précédent entretien : « ${avant?.avis} »`}
                          className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200 cursor-help">
                          a changé
                        </span>
                      )}
                    </div>

                    {/* Texte libre : enregistré au blur, pas à chaque frappe — une requête par
                        caractère au bout d'un VPN mobile ne tient pas. */}
                    <input type="text" defaultValue={rep?.texte ?? ''} disabled={lectureSeule}
                      key={`${q.cle}-${rep?.texte ?? ''}`}
                      onBlur={e => {
                        const v = e.target.value.trim()
                        if (v !== (rep?.texte ?? '')) enregistrer(q.cle, rep?.avis ?? null, v || null)
                      }}
                      placeholder="Ce qu'elle a répondu…"
                      className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white disabled:bg-gray-50" />
                  </li>
                )
              })}
            </ul>
          </CollapsibleSection>
        )
      })}
    </div>
  )
}
