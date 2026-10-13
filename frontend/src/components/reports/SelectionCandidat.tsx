/**
 * SelectionCandidat — des documents cochés vers un candidat, en un clic (12/10/2026).
 * ==================================================================================
 * Sous « Quels documents ? » (Tableau comparatif), dès que des documents sont cochés :
 *   ➕ Créer un candidat — nommé d'après le DOSSIER des documents (« OFFRE_CES » → « CES ») ;
 *   📎 Compléter un candidat — liste des candidats existants, celui dont le dossier correspond
 *      étant présélectionné ; seuls les documents qu'il n'a pas encore sont ajoutés.
 * Avant : il fallait supprimer puis recréer un candidat pour lui ajouter un document oublié.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Paperclip, UserPlus } from 'lucide-react'
import { documentsApi } from '../../api'
import type { GroupeComparatif } from '../../types'
import { dossierCommun, nomCandidat, nomUnique } from '../../utils/dossierCommun'
import { uuid } from '../../utils/uuid'
import { useToast } from '../common/Toast'

interface Props {
  selectionIds: string[]
  groupes: GroupeComparatif[]
  onGroupes: (groupes: GroupeComparatif[]) => void
  /** Vide la sélection une fois les documents rangés (évite de les ajouter deux fois). */
  onRange: () => void
}

export default function SelectionCandidat({ selectionIds, groupes, onGroupes, onRange }: Props) {
  const chemins = useRef(new Map<string, string>())     // id → chemin, chargé à la demande
  const [version, setVersion] = useState(0)
  const [cible, setCible] = useState<string>('')
  const toast = useToast()

  // Chemins des documents cochés ET de ceux des candidats (pour présélectionner le bon).
  const ids = useMemo(() => [...new Set([...selectionIds, ...groupes.flatMap(g => g.document_ids)])],
    [selectionIds, groupes])
  useEffect(() => {
    const manquants = ids.filter(id => !chemins.current.has(id))
    if (!manquants.length) return
    Promise.all(manquants.map(id => documentsApi.get(id).then(d => [id, d.chemin] as const).catch(() => null)))
      .then(res => {
        res.forEach(r => { if (r) chemins.current.set(r[0], r[1]) })
        setVersion(v => v + 1)
      })
  }, [ids])

  const cheminsDe = (liste: string[]) =>
    liste.map(id => chemins.current.get(id)).filter((c): c is string => !!c)

  const dossierSelection = useMemo(() => dossierCommun(cheminsDe(selectionIds)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectionIds, version])
  const nomPropose = nomUnique(nomCandidat(dossierSelection) || 'Nouveau candidat', groupes.map(g => g.nom))

  // Candidat présélectionné : celui dont le dossier contient (ou est contenu dans) celui de la sélection.
  const preselection = useMemo(() => {
    if (!dossierSelection) return ''
    const g = groupes.find(gr => {
      const d = dossierCommun(cheminsDe(gr.document_ids))
      return !!d && (dossierSelection.startsWith(`${d}/`) || d === dossierSelection || d.startsWith(`${dossierSelection}/`))
    })
    return g?.id ?? ''
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dossierSelection, groupes, version])
  useEffect(() => { setCible(preselection || groupes[0]?.id || '') }, [preselection, groupes])

  if (!selectionIds.length) return null

  const creer = () => {
    onGroupes([...groupes, { id: uuid(), nom: nomPropose, document_ids: [...selectionIds] }])
    toast.success(`Candidat « ${nomPropose} » créé avec ${selectionIds.length} document(s) — renommable dans « Candidats »`)
    onRange()
  }

  const completer = () => {
    const g = groupes.find(x => x.id === cible)
    if (!g) return
    const nouveaux = selectionIds.filter(id => !g.document_ids.includes(id))
    if (!nouveaux.length) { toast.success(`« ${g.nom || 'Candidat'} » a déjà ces documents`); return }
    onGroupes(groupes.map(x => x.id === g.id ? { ...x, document_ids: [...x.document_ids, ...nouveaux] } : x))
    toast.success(`${nouveaux.length} document(s) ajouté(s) à « ${g.nom || 'Candidat'} »`)
    onRange()
  }

  return (
    <div className="rounded-lg border border-blue-200 bg-blue-50/60 p-2.5 space-y-2 text-xs">
      <p className="text-blue-900 font-medium">{selectionIds.length} document(s) coché(s) :</p>
      <button type="button" onClick={creer}
        className="flex items-center justify-center gap-1.5 w-full py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium">
        <UserPlus size={13} /> Créer le candidat « {nomPropose} »
      </button>
      {groupes.length > 0 && (
        <div className="flex items-center gap-1.5">
          <select value={cible} onChange={e => setCible(e.target.value)}
            className="flex-1 min-w-0 w-0 truncate border border-blue-200 rounded-md px-2 py-1.5 bg-white text-gray-700">
            {groupes.map((g, i) => (
              <option key={g.id} value={g.id}>
                {g.nom || `Candidat ${i + 1}`} ({g.document_ids.length} doc.){g.id === preselection ? ' — même dossier' : ''}
              </option>
            ))}
          </select>
          <button type="button" onClick={completer} disabled={!cible}
            title="Ajouter les documents cochés à ce candidat"
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-blue-300 bg-white text-blue-700 font-medium hover:bg-blue-100 shrink-0">
            <Paperclip size={12} /> Compléter
          </button>
        </div>
      )}
    </div>
  )
}
