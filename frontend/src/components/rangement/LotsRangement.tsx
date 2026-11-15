/**
 * Rangement › Plan de classement › Ranger (étape 10) — déplacer pour de vrai, par lots, avec annulation.
 * Seules les propositions VALIDÉES entrent dans un lot ; l'aperçu est obligatoire ; on déplace sans jamais
 * supprimer ; un lot s'annule d'un clic (les fichiers reviennent, le journal garde tout).
 */
import { useEffect, useState } from 'react'
import { ChevronRight, FolderMinus, Loader2, PackageCheck, Undo2 } from 'lucide-react'
import { extractApiError } from '../../api'
import { rangementApi, type LotRangement, type OperationLot } from '../../api/inventaire'
import { useToast } from '../common/Toast'
import { confirmerTexte } from '../common/Confirmation'
import { tailleLisible } from '../../utils/formatInventaire'

const STATUTS: Record<string, string> = {
  pret: 'prêt', en_cours: 'en cours', range: 'rangé', partiel: 'rangé en partie', refuse: 'refusé',
  annule: 'annulé', annule_partiel: 'annulé en partie',
}

export default function LotsRangement({ emplacementId, apresChangement }: { emplacementId: number; apresChangement: () => void }) {
  const toast = useToast()
  const [apercu, setApercu] = useState<{ operations: OperationLot[]; octets: number } | null>(null)
  const [lots, setLots] = useState<LotRangement[]>([])
  const [occupe, setOccupe] = useState(false)
  // Retirer ensuite les dossiers que le lot aura vidés (packs de série) : demandé par Thomas, 15/11/2026.
  const [retirerVides, setRetirerVides] = useState(true)

  const chargerLots = async () => {
    try { setLots(await rangementApi.lots(emplacementId)) } catch { setLots([]) }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setApercu(null); void chargerLots() }, [emplacementId])

  const voirApercu = async () => {
    setOccupe(true)
    try { setApercu(await rangementApi.apercu(emplacementId)) }
    catch (err) { toast.error(extractApiError(err, 'Aperçu impossible')) }
    finally { setOccupe(false) }
  }

  const ranger = async () => {
    if (!apercu) return
    const ok = await confirmerTexte(
      `Déplacer ${apercu.operations.length} élément(s) (${tailleLisible(apercu.octets)}) sur le NAS ? Rien n'est supprimé, et le lot s'annule d'un clic.`,
      'Ranger ce lot')
    if (!ok) return
    setOccupe(true)
    try {
      const lot = await rangementApi.creerLot(emplacementId, `Lot du ${new Date().toLocaleString('fr-FR')}`)
      await rangementApi.appliquer(lot.id, retirerVides)
      toast.success('Rangement lancé — il se suit dans « Tâches ». Actualise ensuite.')
      setApercu(null); await chargerLots(); apresChangement()
    } catch (err) { toast.error(extractApiError(err, 'Rangement impossible')) }
    finally { setOccupe(false) }
  }

  const retirer = async (lot: LotRangement) => {
    if (!(await confirmerTexte(`Retirer les dossiers que « ${lot.libelle} » a vidés ? Seuls les dossiers vides sont retirés ; annuler le lot les recrée.`, 'Retirer les dossiers vidés'))) return
    setOccupe(true)
    try { await rangementApi.retirerVides(lot.id); toast.success('Retrait lancé — il se suit dans « Tâches ».'); await chargerLots() }
    catch (err) { toast.error(extractApiError(err, 'Retrait impossible')) }
    finally { setOccupe(false) }
  }

  const annuler = async (lot: LotRangement) => {
    if (!(await confirmerTexte(`Annuler « ${lot.libelle} » ? Chaque fichier revient à son ancienne place.`, 'Annuler ce lot'))) return
    setOccupe(true)
    try { await rangementApi.annuler(lot.id); toast.success('Annulation lancée — elle se suit dans « Tâches ».'); await chargerLots() }
    catch (err) { toast.error(extractApiError(err, 'Annulation impossible')) }
    finally { setOccupe(false) }
  }

  return (
    <section className="border border-gray-200 rounded-lg p-3 space-y-3 min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2"><PackageCheck size={16} /> Ranger ce qui est validé</h2>
        <button type="button" disabled={occupe} onClick={() => void voirApercu()}
          className="text-sm px-3 py-1.5 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50">Voir l'aperçu du lot</button>
      </div>
      <p className="text-xs text-gray-500">Seules les propositions <strong>validées</strong> sont rangées. On déplace sans jamais supprimer un fichier
        (seuls les dossiers qu'un lot a vidés peuvent être retirés, et l'annulation les recrée) ;
        si la place est prise, le nom reçoit un suffixe « _(2) ». Tant que le NAS est en lecture seule pour Matothèque, le lot est refusé et rien ne bouge.</p>

      {apercu && (
        <div className="space-y-2">
          {apercu.operations.length === 0
            ? <p className="text-sm text-gray-500">Rien à ranger : valide d'abord des propositions.</p>
            : <>
                <ul className="max-h-72 overflow-auto text-xs space-y-1 border border-gray-100 rounded p-2">
                  {apercu.operations.map(o => (
                    <li key={o.proposition_id} className="flex flex-wrap items-center gap-1 min-w-0">
                      <span className="font-mono truncate" title={o.source}>{o.source}</span>
                      <ChevronRight size={12} className="text-gray-400" />
                      <span className="font-mono text-blue-700 truncate">{o.dossier}/{o.nom}</span>
                      {o.renomme && <span className="text-amber-700">(nom pris : suffixé)</span>}
                    </li>
                  ))}
                </ul>
                <div className="flex flex-wrap items-center gap-3">
                  <button type="button" disabled={occupe} onClick={() => void ranger()}
                    className="flex items-center gap-1 text-sm px-3 py-1.5 bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50">
                    {occupe ? <Loader2 size={15} className="animate-spin" /> : <PackageCheck size={15} />} Ranger ce lot
                  </button>
                  <span className="text-xs text-gray-600">{apercu.operations.length} élément(s) · {tailleLisible(apercu.octets)}</span>
                  <label className="flex items-center gap-1 text-xs text-gray-700">
                    <input type="checkbox" checked={retirerVides} onChange={e => setRetirerVides(e.target.checked)} />
                    Retirer ensuite les dossiers vidés (packs de séries)
                  </label>
                </div>
              </>}
        </div>
      )}

      {lots.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-600 mb-1">Lots</h3>
          <ul className="space-y-1.5">
            {lots.map(l => (
              <li key={l.id} className="text-sm border border-gray-100 rounded p-2 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium truncate">{l.libelle}</span>
                  <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100">{STATUTS[l.statut] ?? l.statut}</span>
                  <span className="text-xs text-gray-500">{l.nb} élément(s) · {tailleLisible(l.octets)}</span>
                  {['range', 'partiel'].includes(l.statut) && (
                    <button type="button" disabled={occupe} onClick={() => void retirer(l)}
                      className="ml-auto flex items-center gap-1 text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-50"><FolderMinus size={13} /> Retirer les dossiers vidés</button>
                  )}
                  {['range', 'partiel', 'annule_partiel'].includes(l.statut) && (
                    <button type="button" disabled={occupe} onClick={() => void annuler(l)}
                      className="ml-auto flex items-center gap-1 text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-50"><Undo2 size={13} /> Annuler ce lot</button>
                  )}
                </div>
                {l.message && <p className="text-xs text-gray-500 mt-0.5 break-words">{l.message}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
