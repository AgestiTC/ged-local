/**
 * Panneau Veille RSS d'un dossier thématique
 * ==========================================
 * Un dossier peut s'abonner à des flux RSS/Atom. Ce panneau permet de :
 *   - gérer les flux (ajouter une URL, voir l'état du dernier fetch, désabonner) ;
 *   - RAFRAÎCHIR (seule sortie réseau, sur clic explicite — jamais en tâche de fond) ;
 *   - parcourir les nouveautés, les marquer lues, en PROMOUVOIR en ressources permanentes.
 *
 * Repliable et fermé par défaut : la veille est un « plus » qu'on ouvre quand on veut.
 */
import { useEffect, useState } from 'react'
import { ChevronDown, ExternalLink, Globe, Plus, RefreshCw, Rss, ShieldCheck, Star, Trash2, X } from 'lucide-react'
import clsx from 'clsx'
import { dossiersApi, type FluxRss, type VeilleItem } from '../../api'
import { useToast } from '../common/Toast'

function dateCourte(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })
}

interface Props {
  slug: string
  /** Appelé après une promotion (l'appelant recharge le dossier pour afficher la nouvelle ressource). */
  onPromu?: () => void
}

export default function VeillePanel({ slug, onPromu }: Props) {
  const toast = useToast()
  const [ouvert, setOuvert] = useState(false)
  const [flux, setFlux] = useState<FluxRss[]>([])
  const [items, setItems] = useState<VeilleItem[]>([])
  const [nonLus, setNonLus] = useState(0)
  const [nouvelleUrl, setNouvelleUrl] = useState('')
  const [busy, setBusy] = useState(false)          // rafraîchissement réseau en cours
  const [charge, setCharge] = useState(false)      // premier chargement effectué ?
  const [confirmer, setConfirmer] = useState(false) // garde-fou : confirmation avant la sortie réseau

  const charger = async () => {
    try {
      const [f, v] = await Promise.all([dossiersApi.listFlux(slug), dossiersApi.listVeille(slug)])
      setFlux(f.flux); setNonLus(f.non_lus); setItems(v.items)
    } catch { /* dossier peut ne pas encore avoir de veille — silencieux */ }
    finally { setCharge(true) }
  }

  // Charge la veille dès l'ouverture du panneau (et une seule fois).
  useEffect(() => { if (ouvert && !charge) charger() }, [ouvert]) // eslint-disable-line react-hooks/exhaustive-deps

  const ajouterFlux = async () => {
    const url = nouvelleUrl.trim()
    if (!url) return
    try {
      await dossiersApi.addFlux(slug, url)
      setNouvelleUrl('')
      toast.success('Flux abonné — clique « Rafraîchir » pour récupérer les nouveautés.')
      charger()
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || 'Ajout du flux impossible.')
    }
  }

  const supprimerFlux = async (f: FluxRss) => {
    if (!confirm(`Désabonner « ${f.titre || f.url} » ? Ses items de veille seront retirés.`)) return
    try { await dossiersApi.removeFlux(f.id); charger() }
    catch { toast.error('Désabonnement impossible.') }
  }

  // 1er clic → demande de confirmation (aucune sortie réseau). C'est « Confirmer » qui déclenche le fetch.
  const demanderRafraichir = () => {
    if (flux.length === 0) { toast.error('Ajoute d’abord au moins un flux.'); return }
    setConfirmer(true)
  }

  const rafraichir = async () => {
    setConfirmer(false)
    if (flux.length === 0) { toast.error('Ajoute d’abord au moins un flux.'); return }
    setBusy(true)
    try {
      const r = await dossiersApi.refreshVeille(slug)
      const erreurs = r.flux.filter(f => f.etat !== 'ok')
      if (r.nouveaux > 0) toast.success(`${r.nouveaux} nouveauté(s) récupérée(s).`)
      else toast.info('Aucune nouveauté depuis le dernier passage.')
      if (erreurs.length) toast.error(`${erreurs.length} flux en erreur (voir l’état sous chaque flux).`)
      await charger()
    } catch { toast.error('Rafraîchissement impossible (réseau ?).') }
    finally { setBusy(false) }
  }

  const marquerLu = async (it: VeilleItem, lu: boolean) => {
    setItems(xs => xs.map(x => x.id === it.id ? { ...x, lu } : x))
    setNonLus(n => Math.max(0, n + (lu ? -1 : 1)))
    try { await dossiersApi.markItemLu(it.id, lu) } catch { /* optimiste */ }
  }

  const marquerToutLu = async () => {
    try { await dossiersApi.markAllLu(slug); charger() }
    catch { toast.error('Action impossible.') }
  }

  const retirer = async (it: VeilleItem) => {
    setItems(xs => xs.filter(x => x.id !== it.id))
    if (!it.lu) setNonLus(n => Math.max(0, n - 1))
    try { await dossiersApi.removeItem(it.id) } catch { charger() }
  }

  const promouvoir = async (it: VeilleItem) => {
    try {
      const r = await dossiersApi.promouvoirItem(it.id)
      setItems(xs => xs.filter(x => x.id !== it.id))
      if (!it.lu) setNonLus(n => Math.max(0, n - 1))
      toast.success(r.deja_present ? 'Déjà dans le dossier — item classé.' : 'Ajouté aux ressources du dossier.')
      onPromu?.()
    } catch { toast.error('Promotion impossible.') }
  }

  return (
    <div className="border border-gray-200 rounded-lg bg-white">
      {/* En-tête repliable */}
      <button type="button" onClick={() => setOuvert(o => !o)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 rounded-lg">
        <Rss size={15} className="text-orange-500 shrink-0" />
        <span>Veille RSS</span>
        {nonLus > 0 && (
          <span className="text-[10px] font-semibold bg-orange-100 text-orange-700 rounded-full px-1.5 py-0.5">
            {nonLus} à lire
          </span>
        )}
        <ChevronDown size={15} className={clsx('ml-auto text-gray-400 transition-transform', !ouvert && '-rotate-90')} />
      </button>

      {ouvert && (
        <div className="px-4 pb-4 space-y-4 border-t border-gray-100 pt-3">
          {/* Barre d'action : rafraîchir (sortie réseau explicite, confirmée) */}
          <div className="flex items-center gap-2 flex-wrap">
            <button type="button" onClick={demanderRafraichir} disabled={busy || confirmer}
              className="inline-flex items-center gap-1.5 text-xs font-medium bg-orange-600 text-white rounded-md px-3 py-1.5 hover:bg-orange-700 disabled:opacity-50">
              <RefreshCw size={13} className={clsx(busy && 'animate-spin')} />
              {busy ? 'Rafraîchissement…' : 'Rafraîchir la veille'}
            </button>
            {items.some(i => !i.lu) && (
              <button type="button" onClick={marquerToutLu}
                className="text-xs text-gray-500 hover:text-gray-700">Tout marquer lu</button>
            )}
            <span className="inline-flex items-center gap-1 text-[11px] text-emerald-700">
              <ShieldCheck size={12} /> Sortie réseau confirmée, jamais automatique.
            </span>
          </div>

          {/* Garde-fou 100% local : ce qui sort (et surtout ce qui NE sort PAS) avant tout téléchargement. */}
          {confirmer && (
            <div className="rounded-lg border border-orange-200 bg-orange-50 p-3 text-xs text-orange-900">
              <div className="flex items-center gap-1.5 font-semibold mb-1">
                <Globe size={13} /> Contacter Internet pour rafraîchir la veille ?
              </div>
              <p className="leading-relaxed">
                Matothèque va télécharger le contenu des <strong>{flux.length} flux</strong> que tu as ajoutés — et
                <strong> rien d'autre</strong>. Seules les <strong>URLs de ces flux</strong> sont contactées.
                <strong> Aucun</strong> document, tag, résumé, chemin ni nom de fichier n'est envoyé — c'est un
                téléchargement <strong>entrant</strong>. Le reste de Matothèque demeure 100&nbsp;% local.
              </p>
              <div className="flex items-center gap-2 mt-2">
                <button type="button" onClick={rafraichir}
                  className="inline-flex items-center gap-1.5 text-xs font-medium bg-orange-600 text-white rounded-md px-3 py-1.5 hover:bg-orange-700">
                  <RefreshCw size={13} /> Confirmer et rafraîchir
                </button>
                <button type="button" onClick={() => setConfirmer(false)}
                  className="text-xs text-gray-500 hover:text-gray-700">Annuler</button>
              </div>
            </div>
          )}

          {/* Gestion des flux */}
          <div className="space-y-1.5">
            {flux.map(f => (
              <div key={f.id} className="flex items-center gap-2 text-xs">
                <span className="truncate flex-1 text-gray-700" title={f.url}>
                  {f.titre || f.url}
                  {f.non_lus > 0 && <span className="ml-1.5 text-orange-600">· {f.non_lus} à lire</span>}
                  {f.dernier_etat && f.dernier_etat !== 'ok' && (
                    <span className="ml-1.5 text-red-500" title={f.dernier_etat}>· {f.dernier_etat}</span>
                  )}
                </span>
                <button type="button" onClick={() => supprimerFlux(f)} title="Désabonner"
                  className="p-1 text-gray-300 hover:text-red-500 shrink-0"><X size={13} /></button>
              </div>
            ))}
            <div className="flex items-center gap-1.5 pt-1">
              <input value={nouvelleUrl} onChange={e => setNouvelleUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && ajouterFlux()}
                placeholder="https://… (URL d'un flux RSS/Atom)"
                className="flex-1 text-xs border border-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-orange-400" />
              <button type="button" onClick={ajouterFlux} title="Abonner ce flux"
                className="inline-flex items-center gap-1 text-xs border border-gray-200 rounded-md px-2 py-1.5 text-gray-600 hover:bg-gray-50">
                <Plus size={13} /> Ajouter
              </button>
            </div>
          </div>

          {/* Items de veille */}
          {charge && items.length === 0 && (
            <p className="text-xs text-gray-400 text-center py-4">
              {flux.length === 0 ? 'Aucun flux abonné. Ajoute une URL RSS ci-dessus.' : 'Aucune nouveauté — clique « Rafraîchir la veille ».'}
            </p>
          )}
          {items.length > 0 && (
            <ul className="divide-y divide-gray-100 border border-gray-100 rounded-lg">
              {items.map(it => (
                <li key={it.id} className={clsx('px-3 py-2.5 group', it.lu && 'opacity-60')}>
                  <div className="flex items-start gap-2">
                    {!it.lu && <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-orange-500 shrink-0" title="Non lu" />}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2 flex-wrap">
                        {it.url
                          ? <a href={it.url} target="_blank" rel="noopener noreferrer"
                              onClick={() => marquerLu(it, true)}
                              className="text-sm font-medium text-gray-800 hover:text-blue-600 inline-flex items-center gap-1">
                              {it.titre}<ExternalLink size={11} className="text-gray-400 shrink-0" />
                            </a>
                          : <span className="text-sm font-medium text-gray-800">{it.titre}</span>}
                        {it.source && <span className="text-[11px] text-gray-400">· {it.source}</span>}
                        {it.date_pub && <span className="text-[11px] text-gray-400">· {dateCourte(it.date_pub)}</span>}
                      </div>
                      {it.resume && <p className="text-xs text-gray-500 mt-1 leading-relaxed line-clamp-3">{it.resume}</p>}
                    </div>
                    {/* Actions */}
                    <div className="flex items-center gap-0.5 shrink-0 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-opacity">
                      <button type="button" onClick={() => promouvoir(it)} title="Garder dans le dossier (→ ressource)"
                        className="p-1.5 text-gray-300 hover:text-amber-500"><Star size={13} /></button>
                      <button type="button" onClick={() => marquerLu(it, !it.lu)} title={it.lu ? 'Marquer non lu' : 'Marquer lu'}
                        className="p-1.5 text-gray-300 hover:text-blue-600 text-[10px] font-semibold w-6">{it.lu ? '•' : '✓'}</button>
                      <button type="button" onClick={() => retirer(it)} title="Écarter"
                        className="p-1.5 text-gray-300 hover:text-red-500"><Trash2 size={13} /></button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
