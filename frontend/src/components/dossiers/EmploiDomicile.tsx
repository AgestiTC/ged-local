/**
 * EmploiDomicile — onglet « Nounou » (et ses autres profils) d'un dossier
 * =======================================================================
 * Troisième geste du dossier, après **lire** (Ressources) et **se situer** (Planning) :
 * devenir **particulier employeur**. Phase 1 = savoir. Les fiches se lisent, la checklist
 * s'imprime.
 *
 * L'onglet n'apparaît que si le dossier **déclare la capacité** `emploi-domicile` — pas sur
 * un test de son slug. C'est ce qui permettra au futur dossier « Employer chez soi » de
 * l'afficher avec le profil `aide_domicile`, sans toucher une ligne d'écran.
 *
 * **Le rendu est générique** : le backend envoie des blocs typés (`texte`, `vis_a_vis`,
 * `tableau`, `points`) et ce composant les rend sans rien connaître de leur sujet. Ajouter
 * une fiche côté serveur ne demande donc aucune modification ici.
 *
 * ⚠️ **La checklist n'a pas de cases à cocher.** Elle est faite pour être imprimée et
 * remplie au stylo pendant la visite. Offrir des cases qui oublient tout au changement de
 * page serait pire que ne rien offrir — la saisie par candidate arrive en phase 2, avec sa
 * table. Les carrés dessinés sont décoratifs, et c'est assumé.
 */
import { useEffect, useState } from 'react'
import {
  AlertTriangle, BadgeCheck, BookOpen, ExternalLink, HelpCircle, Landmark, Printer,
  ScrollText, Users,
} from 'lucide-react'
import { clsx } from 'clsx'
import {
  emploiDomicileApi, type BlocFiche, type ContenuEmploiDomicile,
} from '../../api'
import VisitesNounou from './VisitesNounou'
import CollapsibleSection from '../common/CollapsibleSection'
import LoadingSpinner from '../common/LoadingSpinner'
import { useToast } from '../common/Toast'

const jolieDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('fr-FR',
    { day: 'numeric', month: 'long', year: 'numeric' })

/** Un contenu réglementaire de plus d'un an doit se voir : les règles bougent chaque année. */
function estPerime(iso: string): boolean {
  const limite = new Date(`${iso}T00:00:00`)
  limite.setFullYear(limite.getFullYear() + 1)
  return limite < new Date()
}

function Bloc({ bloc }: { bloc: BlocFiche }) {
  const attention = bloc.ton === 'attention'

  if (bloc.type === 'texte') {
    return (
      <div className="flex flex-col gap-1.5">
        <h4 className="text-sm font-semibold text-gray-800">{bloc.titre}</h4>
        {(bloc.paragraphes ?? []).map((p, i) => (
          <p key={i} className="text-sm text-gray-600 leading-relaxed">{p}</p>
        ))}
      </div>
    )
  }

  if (bloc.type === 'vis_a_vis') {
    const lignes = (bloc.lignes ?? []) as { sujet: string; employeur: string; salarie: string }[]
    return (
      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-semibold text-gray-800">{bloc.titre}</h4>
        {/* Sur mobile les deux colonnes s'empilent en gardant leur étiquette : un vis-à-vis
            écrasé en deux colonnes de 140 px ne se lit plus. */}
        <div className="hidden sm:grid grid-cols-[9rem_1fr_1fr] gap-px text-[11px] font-semibold text-gray-400 uppercase tracking-wide px-1">
          <span /><span>{bloc.gauche}</span><span>{bloc.droite}</span>
        </div>
        <div className="flex flex-col gap-2">
          {lignes.map((l, i) => (
            <div key={i} className="sm:grid sm:grid-cols-[9rem_1fr_1fr] gap-3 border border-gray-200 rounded-lg p-2.5 bg-white">
              <span className="text-xs font-semibold text-gray-700 sm:pt-0.5">{l.sujet}</span>
              <p className="text-sm text-gray-600 leading-relaxed mt-1 sm:mt-0">
                <span className="sm:hidden block text-[10px] font-semibold text-gray-400 uppercase">{bloc.gauche}</span>
                {l.employeur}
              </p>
              <p className="text-sm text-gray-600 leading-relaxed mt-2 sm:mt-0">
                <span className="sm:hidden block text-[10px] font-semibold text-gray-400 uppercase">{bloc.droite}</span>
                {l.salarie}
              </p>
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (bloc.type === 'tableau') {
    const lignes = (bloc.lignes ?? []) as string[][]
    return (
      <div className="flex flex-col gap-2">
        <h4 className="text-sm font-semibold text-gray-800">{bloc.titre}</h4>
        {/* Le tableau défile dans SON conteneur : la page ne doit jamais défiler en largeur. */}
        <div className="overflow-x-auto border border-gray-200 rounded-lg bg-white">
          <table className="w-full text-sm min-w-[36rem]">
            <thead>
              <tr className="bg-gray-50 text-left">
                {(bloc.entetes ?? []).map(e => (
                  <th key={e} className="px-3 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">{e}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {lignes.map((l, i) => (
                <tr key={i} className="border-t border-gray-100 align-top">
                  {l.map((cell, j) => (
                    <td key={j} className={clsx('px-3 py-2 text-gray-600 leading-relaxed',
                      j === 0 && 'font-medium text-gray-800 whitespace-nowrap')}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {bloc.note && <p className="text-xs text-gray-400 italic leading-relaxed">{bloc.note}</p>}
      </div>
    )
  }

  // 'points'
  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-sm font-semibold text-gray-800">{bloc.titre}</h4>
      <div className="flex flex-col gap-2">
        {(bloc.items ?? []).map((it, i) => (
          <div key={i} className={clsx('border rounded-lg p-2.5',
            attention ? 'border-amber-200 bg-amber-50/50' : 'border-gray-200 bg-white')}>
            <p className={clsx('text-sm font-medium', attention ? 'text-amber-900' : 'text-gray-800')}>
              {it.titre}
            </p>
            <p className="text-sm text-gray-600 leading-relaxed mt-0.5">{it.detail}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function EmploiDomicile({ slug, profil }: { slug: string; profil?: string }) {
  const toast = useToast()
  // Deux temps du même sujet : SAVOIR (les fiches, la checklist vierge à imprimer) et
  // FAIRE (les personnes, leurs entretiens, la checklist remplie). Les empiler sur une
  // seule page rendrait illisible celui qu'on ouvre le plus souvent — les visites.
  const [vue, setVue] = useState<'fiches' | 'visites'>(
    () => (localStorage.getItem('emploi:vue') as 'fiches' | 'visites') || 'fiches'
  )
  const choisir = (v: 'fiches' | 'visites') => { setVue(v); localStorage.setItem('emploi:vue', v) }
  const [data, setData] = useState<ContenuEmploiDomicile | null>(null)
  const [chargement, setChargement] = useState(true)

  useEffect(() => {
    setChargement(true)
    emploiDomicileApi.fiches(profil)
      .then(setData)
      .catch(() => toast.error('Fiches indisponibles'))
      .finally(() => setChargement(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profil])

  if (chargement && !data) return <LoadingSpinner label="Chargement…" className="justify-center py-10" />
  if (!data) return null

  const perime = estPerime(data.verifie_le)

  return (
    <div className="flex flex-col gap-3">

      {/* Le profil, et surtout SON GUICHET : c'est le lieu qui décide, pas le métier. */}
      <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2">
        <div className="flex items-start gap-2 flex-wrap">
          <BadgeCheck size={18} className="text-emerald-600 mt-0.5 shrink-0" />
          <div className="flex-1 min-w-[14rem]">
            <h2 className="text-sm font-semibold text-gray-800">{data.profil.libelle}</h2>
            <p className="text-sm text-gray-500 leading-relaxed">{data.profil.resume}</p>
          </div>
          <span className={clsx('text-[11px] px-2 py-1 rounded-full border whitespace-nowrap cursor-help',
            perime ? 'bg-amber-50 text-amber-800 border-amber-300' : 'bg-gray-50 text-gray-500 border-gray-200')}
            title="Ces fiches décrivent des mécanismes, pas des montants. Relues à cette date.">
            {perime && <AlertTriangle size={11} className="inline mr-1 -mt-0.5" />}
            Vérifié le {jolieDate(data.verifie_le)}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
          {[
            { label: 'Lieu de travail', valeur: data.profil.lieu },
            { label: 'Guichet de déclaration', valeur: data.profil.guichet, fort: true },
            { label: 'Aide mobilisable', valeur: data.profil.aide },
          ].map(({ label, valeur, fort }) => (
            <div key={label} className={clsx('rounded-lg border p-2',
              fort ? 'border-blue-200 bg-blue-50' : 'border-gray-200 bg-gray-50')}>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>
              <p className={clsx('text-sm', fort ? 'font-semibold text-blue-800' : 'text-gray-700')}>{valeur}</p>
            </div>
          ))}
        </div>

        <p className="text-xs text-gray-500 leading-relaxed border-t border-gray-100 pt-2">
          {data.avertissement}
        </p>
        {data.avertissements.map((a, i) => (
          <p key={i} className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-2 leading-relaxed">
            {a}
          </p>
        ))}
      </section>

      {/* Savoir / Faire */}
      <nav className="flex items-center gap-1 border-b border-gray-200">
        {([
          { cle: 'fiches', label: 'Ce qu’il faut savoir', Icon: BookOpen },
          { cle: 'visites', label: 'Visites et entretiens', Icon: Users },
        ] as const).map(({ cle, label, Icon }) => (
          <button key={cle} type="button" onClick={() => choisir(cle)}
            aria-current={vue === cle ? 'page' : undefined}
            className={clsx('flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px transition-colors',
              vue === cle ? 'border-blue-500 text-blue-700'
                          : 'border-transparent text-gray-500 hover:text-gray-700')}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </nav>

      {vue === 'visites' ? (
        <VisitesNounou slug={slug} checklist={data.checklist} />
      ) : <>

      {/* Les fiches — rendu générique : ajouter une fiche côté serveur ne touche rien ici. */}
      {data.fiches.map(f => (
        <CollapsibleSection key={f.cle} id={`emploi-${f.cle}`} defaultOpen={f.cle === 'guichet'}
          icon={<Landmark size={16} className="text-blue-600" />} title={f.titre}>
          <div className="flex flex-col gap-4 pt-1">
            <p className="text-sm text-gray-500 leading-relaxed">{f.chapeau}</p>
            {f.blocs.map((b, i) => <Bloc key={i} bloc={b} />)}
          </div>
        </CollapsibleSection>
      ))}

      {/* La checklist — à imprimer et à remplir au stylo (cf. en-tête du fichier). */}
      <CollapsibleSection id="emploi-checklist" defaultOpen={false}
        icon={<ScrollText size={16} className="text-violet-600" />}
        title="Checklist d'entretien"
        right={
          <button type="button"
            onClick={e => { e.stopPropagation(); window.print() }}
            className="flex items-center gap-1 text-xs px-2 py-1 mr-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50">
            <Printer size={13} /> Imprimer
          </button>
        }>
        <div className="flex flex-col gap-3 pt-1">
          <p className="text-xs text-gray-400 leading-relaxed">
            Chaque question dit <strong className="text-gray-500">ce qu'on fait de la réponse</strong> —
            c'est ce qui permet de l'adapter plutôt que de la réciter. À imprimer : les cases
            se cochent au stylo, rien n'est enregistré à ce stade.
          </p>
          {data.checklist.map(groupe => (
            <div key={groupe.titre} className="border border-gray-200 rounded-lg bg-white p-3">
              <h4 className="text-sm font-semibold text-gray-800 mb-2">{groupe.titre}</h4>
              <ul className="flex flex-col gap-2">
                {groupe.questions.map((q, i) => (
                  <li key={i} className="flex items-start gap-2">
                    {/* Carré DÉCORATIF : pas un <input>, pour ne rien promettre qu'on n'enregistre. */}
                    <span aria-hidden className="mt-0.5 w-3.5 h-3.5 border border-gray-300 rounded-sm shrink-0" />
                    <div className="flex-1">
                      <p className="text-sm text-gray-700 leading-snug">{q.texte}</p>
                      <p className="text-[11px] text-gray-400 italic leading-snug flex items-start gap-1">
                        <HelpCircle size={11} className="mt-0.5 shrink-0" /> {q.pourquoi}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </CollapsibleSection>

      {/* Liens officiels : des ancres que l'utilisateur clique, pas des appels que
          l'application émet — Matothèque ne sort jamais sur le réseau toute seule. */}
      <section className="bg-white border border-gray-200 rounded-lg p-3">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Sources officielles
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {data.liens.map(l => (
            <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer"
              className="flex items-center justify-between gap-2 px-3 py-2 border border-gray-200 rounded-lg hover:border-blue-300 text-sm text-gray-700">
              <span className="truncate">{l.libelle}</span>
              <span className="flex items-center gap-1.5 shrink-0">
                {/* Un lien venant d'Administration se distingue : il vient de VOTRE liste,
                    pas des guichets livrés avec le module. */}
                {l.origine === 'administration' && (
                  <span title="Repris de Administration → liens"
                    className="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-500 border border-gray-200">
                    à vous
                  </span>
                )}
                <ExternalLink size={13} className="text-gray-300" />
              </span>
            </a>
          ))}
        </div>
        <p className="text-[11px] text-gray-400 mt-2">
          Les liens pertinents ajoutés dans <strong>Administration → liens</strong> apparaissent
          ici automatiquement — rien à ressaisir.
        </p>
      </section>
      </>}
    </div>
  )
}
