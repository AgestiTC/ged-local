/**
 * VisitesNounou — les personnes qu'on envisage d'employer, et les visites qu'on leur fait
 * =======================================================================================
 * Deux niveaux, un seul écran :
 *
 * 1. **la liste** — qui reste à appeler, qui on voit jeudi, qui a un agrément périmé ;
 * 2. **la fiche** — les coordonnées, l'historique des entretiens, et la checklist de
 *    l'entretien ouvert.
 *
 * **Une personne = N entretiens, et la checklist appartient à l'entretien.** On revient chez
 * la même assistante maternelle, certaines réponses changent : les écraser ferait disparaître
 * l'information la plus utile, *ce qui a bougé entre les deux visites*. Un second entretien
 * peut reprendre les réponses du premier, qui n'est jamais modifié.
 *
 * **Écran mobile d'abord** — exception assumée au « desktop-first » du projet : il se remplit
 * debout, dans une entrée d'immeuble, au bout d'un VPN. D'où une colonne, des cibles larges,
 * les bons claviers (`tel`, `email`, `date`) et l'enregistrement au fil de la saisie.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  ArrowLeft, BadgeAlert, CalendarPlus, ChevronRight, Copy, FileSignature, MapPin, Phone,
  Plus, Star, Trash2, UserPlus, Users, X,
} from 'lucide-react'
import { adressePostale, lienCarte, lienTelephone } from '../../utils/contact'
import { copierTexte } from '../../utils/clipboard'
import { clsx } from 'clsx'
import {
  visitesApi, type Entretien, type GroupeChecklist, type Intervenant, type IntervenantDetail,
} from '../../api'
import ChecklistEntretien from './ChecklistEntretien'
import ContratNounou from './ContratNounou'
import LoadingSpinner from '../common/LoadingSpinner'
import { useToast } from '../common/Toast'

const STATUTS: Record<string, { label: string; classe: string }> = {
  a_contacter: { label: 'à contacter', classe: 'bg-gray-100 text-gray-600 border-gray-200' },
  entretien: { label: 'en entretien', classe: 'bg-blue-50 text-blue-700 border-blue-200' },
  retenue: { label: 'retenue', classe: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  employee: { label: 'employée', classe: 'bg-emerald-600 text-white border-emerald-600' },
  ecartee: { label: 'écartée', classe: 'bg-gray-50 text-gray-400 border-gray-200' },
  terminee: { label: 'contrat terminé', classe: 'bg-gray-50 text-gray-400 border-gray-200' },
}

const TYPES_ENTRETIEN: Record<string, string> = {
  telephone: 'Appel téléphonique',
  visite: 'Visite',
  seconde_visite: 'Seconde visite',
  suivi: 'Point de suivi',
}

const jolieDate = (iso: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('fr-FR',
    { weekday: 'short', day: 'numeric', month: 'short' }) : null

/** Créneau lisible : « jeu. 2 oct. · 14:00–15:30 ». */
function creneau(e: Entretien): string {
  const d = jolieDate(e.date_prevue)
  if (!d) return 'date à fixer'
  const h = [e.heure_debut, e.heure_fin].filter(Boolean).join('–')
  return h ? `${d} · ${h}` : d
}

// ─── Fiche d'une personne ─────────────────────────────────────────────────────────────

function Fiche({ id, checklist, onRetour, onMaj }: {
  id: string
  checklist: GroupeChecklist[]
  onRetour: () => void
  onMaj: () => void
}) {
  const toast = useToast()
  const [data, setData] = useState<IntervenantDetail | null>(null)
  const [ouvert, setOuvert] = useState<string | null>(null)
  const [nouveau, setNouveau] = useState(false)
  // Rencontrer et contracter sont deux moments distincts de la même relation : les empiler
  // sur un seul écran rendrait illisible celui qu'on ouvre, et le contrat est long.
  const [vue, setVue] = useState<'entretiens' | 'contrat'>('entretiens')
  const [form, setForm] = useState({ type: 'visite', date_prevue: '', heure_debut: '', lieu: '', reprendre: true })

  const charger = useCallback(async () => {
    try {
      const d = await visitesApi.detail(id)
      setData(d)
      // On ouvre le dernier entretien : c'est celui qu'on vient de faire ou qu'on s'apprête
      // à faire. Ouvrir le premier obligerait à défiler chaque fois.
      // `.at(-1)` demanderait ES2022 : le projet cible plus bas, et changer la cible pour
      // deux lignes ferait payer un réglage global à un détail local.
      setOuvert(o => o ?? (d.entretiens.length ? d.entretiens[d.entretiens.length - 1].id : null))
    } catch { toast.error('Fiche indisponible') }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  useEffect(() => { charger() }, [charger])

  if (!data) return <LoadingSpinner label="Chargement…" className="justify-center py-8" />

  const majChamp = async (champ: string, valeur: unknown) => {
    try {
      await visitesApi.modifier(id, { [champ]: valeur } as never)
      await charger(); onMaj()
    } catch { toast.error('Modification refusée') }
  }

  const creerEntretien = async () => {
    try {
      const e = await visitesApi.creerEntretien(id, {
        type: form.type,
        date_prevue: form.date_prevue || null,
        heure_debut: form.heure_debut || null,
        lieu: form.lieu || null,
        // Reprendre les réponses du précédent : on ne repose pas quarante questions.
        ...(form.reprendre && data.entretiens.length > 0 ? { reprendre_de: 'precedent' } : {}),
      })
      setNouveau(false)
      setForm({ type: 'visite', date_prevue: '', heure_debut: '', lieu: '', reprendre: true })
      setOuvert(e.id)
      await charger(); onMaj()
      toast.success(`${TYPES_ENTRETIEN[e.type] ?? 'Entretien'} n°${e.rang} créé`)
    } catch { toast.error('Création impossible') }
  }

  const entretienOuvert = data.entretiens.find(e => e.id === ouvert) ?? null
  const anterieurs = entretienOuvert
    ? data.entretiens.filter(e => e.rang < entretienOuvert.rang)
    : []
  const precedent = anterieurs.length ? anterieurs[anterieurs.length - 1] : undefined

  return (
    <div className="flex flex-col gap-3">
      <button type="button" onClick={onRetour}
        className="self-start flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700">
        <ArrowLeft size={13} /> Toutes les personnes
      </button>

      {/* Identité + coordonnées, éditables en place */}
      <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2">
        <div className="flex items-start gap-2 flex-wrap">
          <h3 className="text-base font-semibold text-gray-900 flex-1">
            {[data.prenom, data.nom].filter(Boolean).join(' ')}
          </h3>
          <select value={data.statut} onChange={e => majChamp('statut', e.target.value)}
            className={clsx('text-xs font-medium px-2 py-1 rounded-full border', STATUTS[data.statut]?.classe)}>
            {Object.entries(STATUTS).map(([v, { label }]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </div>

        {/* Appeler et se rendre chez elle : deux gestes qu'on fait le téléphone à la main,
            et qui ne doivent pas demander de recopier quoi que ce soit. */}
        <div className="flex flex-wrap items-center gap-2">
          {lienTelephone(data.telephone) && (
            <a href={lienTelephone(data.telephone)!}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100">
              <Phone size={14} /> Appeler {data.telephone}
            </a>
          )}
          {/* « Y aller » n'existe que là où le système sait l'honorer (Android). Ailleurs on
              COPIE l'adresse : ouvrir un service de cartographie en ligne reviendrait à lui
              envoyer le domicile d'une personne identifiée. */}
          {adressePostale(data.adresse, data.commune) && (
            lienCarte(adressePostale(data.adresse, data.commune)) ? (
              <a href={lienCarte(adressePostale(data.adresse, data.commune))!}
                title="Ouvrir dans votre application de navigation"
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100">
                <MapPin size={14} /> Y aller
              </a>
            ) : (
              <button type="button"
                onClick={async () => {
                  const ok = await copierTexte(adressePostale(data.adresse, data.commune)!)
                  toast[ok ? 'success' : 'error'](ok ? 'Adresse copiée' : 'Copie impossible')
                }}
                title="Copier l'adresse — rien n'est envoyé à un service de cartographie"
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100">
                <MapPin size={14} /> Copier l'adresse
              </button>
            )
          )}
        </div>

        {data.agrement_perime && (
          <p className="flex items-center gap-1.5 text-xs text-rose-800 bg-rose-50 border border-rose-200 rounded-lg p-2">
            <BadgeAlert size={14} className="shrink-0" />
            <span><strong>Agrément expiré</strong> ({data.agrement_echeance}) — sans agrément valide,
              il n'y a ni aide ni accueil légal. À vérifier avant d'aller plus loin.</span>
          </p>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {([
            ['prenom', 'Prénom', 'text'], ['nom', 'Nom', 'text'],
            ['telephone', 'Téléphone', 'tel'], ['email', 'Email', 'email'],
            ['commune', 'Commune', 'text'], ['adresse', 'Adresse (lieu d\'accueil)', 'text'],
            ['agrement_numero', 'N° d\'agrément', 'text'], ['agrement_echeance', 'Agrément valable jusqu\'au', 'date'],
            ['tarif_annonce', 'Tarif annoncé', 'text'], ['disponibilite', 'Disponible à partir de', 'text'],
          ] as const).map(([champ, label, type]) => (
            <label key={champ} className="flex flex-col gap-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">{label}</span>
              <input type={type} defaultValue={(data as never as Record<string, string>)[champ] ?? ''}
                onBlur={e => {
                  const v = e.target.value.trim() || null
                  if (v !== ((data as never as Record<string, string>)[champ] ?? null)) majChamp(champ, v)
                }}
                className="text-sm border border-gray-200 rounded-md px-2 py-1.5" />
            </label>
          ))}
        </div>

        <label className="flex flex-col gap-0.5">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Note libre</span>
          <textarea defaultValue={data.note ?? ''} rows={2}
            onBlur={e => { const v = e.target.value.trim() || null; if (v !== data.note) majChamp('note', v) }}
            className="text-sm border border-gray-200 rounded-md px-2 py-1.5 resize-y" />
        </label>

        <button type="button"
          onClick={async () => {
            if (!confirm(`Supprimer ${data.nom} et ses ${data.nb_entretiens} entretien(s) ?`)) return
            await visitesApi.supprimer(id); onMaj(); onRetour()
          }}
          className="self-start flex items-center gap-1 text-xs text-gray-400 hover:text-rose-600">
          <Trash2 size={13} /> Supprimer cette fiche
        </button>
      </section>

      <nav className="flex items-center gap-1 border-b border-gray-200">
        {([
          { cle: 'entretiens', label: 'Entretiens', Icon: Users },
          { cle: 'contrat', label: 'Contrat', Icon: FileSignature },
        ] as const).map(({ cle, label, Icon }) => (
          <button key={cle} type="button" onClick={() => setVue(cle)}
            aria-current={vue === cle ? 'page' : undefined}
            className={clsx('flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px transition-colors',
              vue === cle ? 'border-blue-500 text-blue-700'
                          : 'border-transparent text-gray-500 hover:text-gray-700')}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </nav>

      {vue === 'contrat' ? <ContratNounou intervenantId={id} /> : <>

      {/* Entretiens : l'historique, puis la checklist de celui qu'on ouvre */}
      <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Entretiens ({data.entretiens.length})
          </h4>
          <button type="button" onClick={() => setNouveau(v => !v)}
            className="flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">
            <CalendarPlus size={13} /> Nouvel entretien
          </button>
        </div>

        {nouveau && (
          <div className="border border-blue-200 bg-blue-50/50 rounded-lg p-2.5 flex flex-col gap-2">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <select value={form.type} onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
                className="text-sm border border-gray-300 rounded-md px-2 py-1.5 bg-white">
                {Object.entries(TYPES_ENTRETIEN).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <input type="date" value={form.date_prevue}
                onChange={e => setForm(f => ({ ...f, date_prevue: e.target.value }))}
                className="text-sm border border-gray-300 rounded-md px-2 py-1.5" />
              <input type="time" value={form.heure_debut}
                onChange={e => setForm(f => ({ ...f, heure_debut: e.target.value }))}
                className="text-sm border border-gray-300 rounded-md px-2 py-1.5" />
              <input type="text" value={form.lieu} placeholder="Lieu (chez elle, au téléphone…)"
                onChange={e => setForm(f => ({ ...f, lieu: e.target.value }))}
                className="text-sm border border-gray-300 rounded-md px-2 py-1.5" />
            </div>
            {data.entretiens.length > 0 && (
              <label className="flex items-start gap-2 text-xs text-gray-600">
                <input type="checkbox" checked={form.reprendre} className="mt-0.5"
                  onChange={e => setForm(f => ({ ...f, reprendre: e.target.checked }))} />
                <span>
                  <strong>Reprendre les réponses du précédent.</strong> On ne repose pas tout :
                  on met à jour ce qui a changé, et l'entretien d'origine reste intact.
                </span>
              </label>
            )}
            <div className="flex items-center gap-2">
              <button type="button" onClick={creerEntretien}
                className="text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700">Créer</button>
              <button type="button" onClick={() => setNouveau(false)}
                className="text-sm px-2 py-1.5 text-gray-500 hover:text-gray-700">Annuler</button>
            </div>
          </div>
        )}

        {data.entretiens.length === 0 ? (
          <p className="text-sm text-gray-400 py-4 text-center">
            Aucun entretien. Le premier appel compte déjà comme un entretien.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {data.entretiens.map(e => (
              <button key={e.id} type="button" onClick={() => setOuvert(e.id)}
                className={clsx('text-xs px-2.5 py-1.5 rounded-md border transition-colors',
                  ouvert === e.id
                    ? 'bg-gray-800 text-white border-gray-800'
                    : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50')}>
                {e.rang}. {TYPES_ENTRETIEN[e.type] ?? e.type} · {creneau(e)}
                {e.nb_repondues > 0 && <span className="opacity-60"> · {e.nb_repondues} rép.</span>}
              </button>
            ))}
          </div>
        )}
      </section>

      {entretienOuvert && (
        <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-3">
          <div className="flex items-center gap-2 flex-wrap border-b border-gray-100 pb-2">
            <h4 className="text-sm font-semibold text-gray-800 flex-1">
              {TYPES_ENTRETIEN[entretienOuvert.type] ?? entretienOuvert.type} n°{entretienOuvert.rang}
              <span className="font-normal text-gray-400"> · {creneau(entretienOuvert)}</span>
            </h4>
            <select value={entretienOuvert.statut}
              onChange={async e => {
                await visitesApi.modifierEntretien(entretienOuvert.id, { statut: e.target.value })
                await charger(); onMaj()
              }}
              className="text-xs border border-gray-200 rounded-md px-2 py-1 bg-white">
              <option value="planifie">planifié</option>
              <option value="fait">fait</option>
              <option value="annule">annulé</option>
            </select>
          </div>

          {/* L'impression générale, séparée de la grille : une checklist parfaitement
              remplie ne fait pas une bonne rencontre. */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-gray-500">Impression générale</span>
            {[1, 2, 3, 4, 5].map(n => (
              <button key={n} type="button"
                onClick={async () => {
                  await visitesApi.modifierEntretien(entretienOuvert.id,
                    { impression: entretienOuvert.impression === n ? null : n })
                  await charger()
                }}
                className="p-0.5" aria-label={`${n} sur 5`}>
                <Star size={18} className={clsx('transition-colors',
                  (entretienOuvert.impression ?? 0) >= n
                    ? 'fill-amber-400 text-amber-400' : 'text-gray-300')} />
              </button>
            ))}
          </div>

          <ChecklistEntretien
            entretien={entretienOuvert} checklist={checklist}
            precedentes={precedent?.reponses}
            lectureSeule={entretienOuvert.statut === 'annule'}
            onChange={maj => setData(d => d && ({
              ...d, entretiens: d.entretiens.map(e => e.id === maj.id ? maj : e),
            }))} />
        </section>
      )}
      </>}
    </div>
  )
}

// ─── Liste ────────────────────────────────────────────────────────────────────────────

export default function VisitesNounou({ slug, checklist }: {
  slug: string
  checklist: GroupeChecklist[]
}) {
  const toast = useToast()
  const [liste, setListe] = useState<Intervenant[] | null>(null)
  const [selection, setSelection] = useState<string | null>(null)
  const [ajout, setAjout] = useState(false)
  const [nom, setNom] = useState('')
  const [prenom, setPrenom] = useState('')
  const [telephone, setTelephone] = useState('')

  const charger = useCallback(() => {
    visitesApi.lister(slug)
      .then(d => setListe(d.intervenants))
      .catch(() => toast.error('Liste indisponible'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug])

  useEffect(() => { charger() }, [charger])

  const creer = async () => {
    if (!nom.trim()) return
    try {
      // Seul le nom est requis : une fiche à moitié remplie pendant un premier appel vaut
      // mieux qu'un formulaire qu'on renonce à valider.
      const i = await visitesApi.creer(slug, {
        nom: nom.trim(),
        prenom: prenom.trim() || null,
        telephone: telephone.trim() || null,
      })
      setNom(''); setPrenom(''); setTelephone(''); setAjout(false)
      charger(); setSelection(i.id)
    } catch { toast.error('Création impossible') }
  }

  if (!liste) return <LoadingSpinner label="Chargement…" className="justify-center py-8" />

  if (selection) {
    return <Fiche id={selection} checklist={checklist}
      onRetour={() => setSelection(null)} onMaj={charger} />
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-sm text-gray-500">
          {liste.length === 0 ? 'Personne suivie pour l\'instant.'
            : `${liste.length} personne${liste.length > 1 ? 's' : ''} suivie${liste.length > 1 ? 's' : ''}.`}
        </p>
        <button type="button" onClick={() => setAjout(v => !v)}
          className="flex items-center gap-1 text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700">
          <UserPlus size={15} /> Ajouter une personne
        </button>
      </div>

      {ajout && (
        <form onSubmit={e => { e.preventDefault(); creer() }}
          className="border border-blue-200 bg-blue-50/50 rounded-lg p-2.5 flex flex-col sm:flex-row gap-2">
          <input autoFocus value={nom} onChange={e => setNom(e.target.value)}
            placeholder="Nom (seul champ obligatoire)"
            className="flex-1 text-sm border border-gray-300 rounded-md px-2.5 py-1.5" />
          <input value={prenom} onChange={e => setPrenom(e.target.value)}
            placeholder="Prénom"
            className="sm:w-40 text-sm border border-gray-300 rounded-md px-2.5 py-1.5" />
          <input type="tel" value={telephone} onChange={e => setTelephone(e.target.value)}
            placeholder="Téléphone"
            className="sm:w-44 text-sm border border-gray-300 rounded-md px-2.5 py-1.5" />
          <div className="flex items-center gap-2">
            <button type="submit" className="text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700">
              Créer
            </button>
            <button type="button" onClick={() => setAjout(false)}
              className="text-sm px-2 py-1.5 text-gray-500 hover:text-gray-700"><X size={15} /></button>
          </div>
        </form>
      )}

      {liste.length === 0 ? (
        <p className="text-center text-sm text-gray-400 py-10">
          Ajoutez la première personne dès le premier coup de téléphone : c'est déjà un entretien.
        </p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {liste.map(i => (
            <button key={i.id} type="button" onClick={() => setSelection(i.id)}
              className="text-left bg-white border border-gray-200 rounded-lg p-3 hover:border-blue-300 hover:shadow-sm transition-all flex flex-col gap-1.5">
              <div className="flex items-start gap-2">
                <span className="font-medium text-gray-900 flex-1">
                  {[i.prenom, i.nom].filter(Boolean).join(' ')}
                </span>
                <span className={clsx('text-[10px] font-semibold px-1.5 py-0.5 rounded-full border whitespace-nowrap',
                  STATUTS[i.statut]?.classe)}>
                  {STATUTS[i.statut]?.label ?? i.statut}
                </span>
              </div>

              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                {/* `stopPropagation` : la carte entière ouvre la fiche, ces deux liens non —
                    sinon appeler quelqu'un ferait aussi changer d'écran sous le doigt. */}
                {lienTelephone(i.telephone) && (
                  <a href={lienTelephone(i.telephone)!} onClick={e => e.stopPropagation()}
                    className="flex items-center gap-1 hover:text-emerald-700 hover:underline">
                    <Phone size={11} /> {i.telephone}
                  </a>
                )}
                {lienCarte(adressePostale(i.adresse, i.commune)) ? (
                  <a href={lienCarte(adressePostale(i.adresse, i.commune))!}
                    onClick={e => e.stopPropagation()}
                    title="Ouvrir dans votre application de navigation"
                    className="flex items-center gap-1 hover:text-blue-700 hover:underline">
                    <MapPin size={11} /> {i.commune ?? 'y aller'}
                  </a>
                ) : i.commune && (
                  <span className="flex items-center gap-1"><MapPin size={11} /> {i.commune}</span>
                )}
                {i.tarif_annonce && <span className="flex items-center gap-1"><Copy size={11} /> {i.tarif_annonce}</span>}
              </div>

              {i.agrement_perime && (
                <span className="flex items-center gap-1 text-[11px] text-rose-700">
                  <BadgeAlert size={12} /> agrément expiré
                </span>
              )}

              <div className="flex items-center gap-2 text-xs text-gray-400 mt-0.5">
                <span>{i.nb_entretiens} entretien{i.nb_entretiens > 1 ? 's' : ''}</span>
                {i.prochain_rdv && (
                  <>
                    <span className="text-gray-300">·</span>
                    <span className="text-blue-600 font-medium">
                      prochain : {creneau(i.prochain_rdv)}
                    </span>
                  </>
                )}
                <ChevronRight size={13} className="ml-auto text-gray-300" />
              </div>
            </button>
          ))}
        </div>
      )}

      <p className="text-xs text-gray-400 leading-relaxed">
        <Plus size={11} className="inline -mt-0.5" /> Une personne peut avoir <strong>plusieurs
        entretiens</strong> — appel, visite, seconde visite. Chacun a <strong>sa propre
        checklist</strong> : c'est ce qui permet de voir ce qui a changé entre deux rencontres.
      </p>
    </div>
  )
}
