/**
 * AdminPage — Administration
 * ==========================
 * Deux onglets :
 *
 * - **Liens** : raccourcis externes utiles, regroupés par section, **réorganisables**.
 * - **Aide à la déclaration** : où reporter quoi sur sa déclaration de revenus, à partir
 *   de ce que Matothèque connaît déjà. Voir `components/admin/AideDeclaration`.
 *
 * ## Réorganiser les cartes
 *
 * L'ordre des liens est celui du tableau `admin_links` en configuration : le déplacement
 * réécrit ce tableau, il n'y a donc **aucun champ « position » à tenir cohérent**. Déplacer
 * une carte vers une autre section change aussi sa `section` — c'est le même geste, et
 * demander deux manipulations pour un seul mouvement serait une invention gratuite.
 *
 * **Deux façons de déplacer, et ce n'est pas de la redondance** : le glisser-déposer (HTML5)
 * ne fonctionne pas sur écran tactile, et cette application se consulte aussi au téléphone.
 * Les flèches ◄ ► de chaque carte font le même travail partout — souris, clavier, doigt.
 *
 * ⚠️ La page ne s'affichait dans la barre latérale que si des **liens** existaient. Livrer
 * l'aide à la déclaration sans toucher à cette condition l'aurait rendue **invisible pour
 * une raison sans rapport** — la leçon v1.84.3, déjà payée une fois. La condition vit dans
 * `Sidebar`, et couvre désormais les deux onglets.
 */
import { useEffect, useState } from 'react'
import {
  ChevronLeft, ChevronRight, ExternalLink, GripVertical, Landmark, Link2, Receipt,
  Settings, Stethoscope,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { clsx } from 'clsx'
import CollapsibleSection from '../components/common/CollapsibleSection'
import LoadingSpinner from '../components/common/LoadingSpinner'
import AideDeclaration from '../components/admin/AideDeclaration'
import { systemApi, type AdminLink } from '../api'
import { useToast } from '../components/common/Toast'

function iconePour(section: string) {
  const s = section.toLowerCase()
  if (/m[ée]dic|sant[ée]|docto/.test(s)) return <Stethoscope size={16} className="text-red-500" />
  if (/gouv|impot|impôt|ants|admin|etat|état/.test(s)) return <Landmark size={16} className="text-blue-600" />
  return <Link2 size={16} className="text-gray-500" />
}

type Onglet = 'liens' | 'impots'

export default function AdminPage() {
  const toast = useToast()
  const [links, setLinks] = useState<AdminLink[]>([])
  const [loading, setLoading] = useState(true)
  // Index (dans `links`) de la carte en cours de déplacement, et de celle qu'on survole.
  const [pris, setPris] = useState<number | null>(null)
  const [cible, setCible] = useState<number | null>(null)
  // L'onglet ouvert survit à la navigation : on revient souvent sur la déclaration.
  const [onglet, setOnglet] = useState<Onglet>(
    () => (localStorage.getItem('admin:onglet') as Onglet) || 'liens'
  )

  const choisir = (o: Onglet) => { setOnglet(o); localStorage.setItem('admin:onglet', o) }

  useEffect(() => {
    systemApi.getConfig()
      .then(c => { try { setLinks(JSON.parse(c.admin_links?.valeur || '[]')) } catch { setLinks([]) } })
      .catch(() => setLinks([]))
      .finally(() => setLoading(false))
  }, [])

  /**
   * Applique un nouvel ordre et l'enregistre.
   *
   * L'affichage change d'abord (le déplacement doit être immédiat sous la main), mais on
   * **restaure l'ordre précédent si l'enregistrement échoue** : laisser une carte à sa
   * nouvelle place après un échec ferait croire que c'est rangé, jusqu'au prochain
   * rechargement qui remettrait tout comme avant.
   */
  const enregistrer = async (suivant: AdminLink[]) => {
    const precedent = links
    setLinks(suivant)
    try {
      await systemApi.updateConfig({ admin_links: JSON.stringify(suivant) })
    } catch {
      setLinks(precedent)
      toast.error('Réorganisation non enregistrée')
    }
  }

  /** Retire la carte `de` et la réinsère en `vers`, en reprenant la section de destination. */
  const deplacer = (de: number, vers: number, section?: string) => {
    if (de === vers) return
    const suivant = [...links]
    const [carte] = suivant.splice(de, 1)
    suivant.splice(vers, 0, section === undefined ? carte : { ...carte, section })
    enregistrer(suivant)
  }

  /**
   * Décale une carte d'un cran DANS SA SECTION. Les flèches ne traversent pas les sections :
   * un déplacement qui changerait de rubrique sans qu'on l'ait demandé serait une surprise.
   */
  const decaler = (index: number, sens: -1 | 1) => {
    const meme = links.map((l, i) => ({ l, i })).filter(({ l }) => l.section === links[index].section)
    const rang = meme.findIndex(({ i }) => i === index)
    const voisin = meme[rang + sens]
    if (!voisin) return
    const suivant = [...links]
    ;[suivant[index], suivant[voisin.i]] = [suivant[voisin.i], suivant[index]]
    enregistrer(suivant)
  }

  // Sections dans l'ordre d'apparition.
  const sections = links.reduce<string[]>((acc, l) => (acc.includes(l.section) ? acc : [...acc, l.section]), [])

  return (
    // Large : la page porte désormais une GRILLE de quatre colonnes, plus une liste de liens.
    <div className="max-w-7xl mx-auto p-3 sm:p-6 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold text-gray-800 flex items-center gap-2">🗂️ Administration</h1>
        <Link to="/settings" className="text-xs text-gray-400 hover:text-blue-600 flex items-center gap-1">
          <Settings size={13} /> Gérer les liens
        </Link>
      </div>

      <nav className="flex items-center gap-1 border-b border-gray-200">
        {([
          { cle: 'liens', label: 'Liens', Icon: Link2 },
          { cle: 'impots', label: 'Aide à la déclaration', Icon: Receipt },
        ] as const).map(({ cle, label, Icon }) => (
          <button key={cle} type="button" onClick={() => choisir(cle)}
            aria-current={onglet === cle ? 'page' : undefined}
            className={clsx('flex items-center gap-1.5 px-3 py-2 text-sm border-b-2 -mb-px transition-colors',
              onglet === cle
                ? 'border-blue-500 text-blue-700'
                : 'border-transparent text-gray-500 hover:text-gray-700')}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </nav>

      {onglet === 'impots' ? <AideDeclaration /> : loading ? (
        <LoadingSpinner label="Chargement…" className="justify-center py-10" />
      ) : sections.length === 0 ? (
        <div className="text-center text-sm text-gray-400 py-16">
          Aucun lien. Ajoute-les dans <Link to="/settings" className="text-blue-600 hover:underline">Paramètres → Administration — liens</Link>.
        </div>
      ) : <>
        <p className="text-xs text-gray-400">
          Glissez une carte pour la déplacer — y compris <strong>vers une autre section</strong>.
          Les flèches ◄ ► la décalent dans sa section, et fonctionnent aussi au doigt.
        </p>

        {sections.map(sec => (
          <CollapsibleSection key={sec} id={`admin-${sec}`} defaultOpen icon={iconePour(sec)} title={sec}>
            <div
              className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 pt-1"
              // Déposer dans le vide d'une section = ranger la carte à la fin de CETTE
              // section. Sans ça, viser une section presque vide serait impossible.
              onDragOver={e => e.preventDefault()}
              onDrop={() => {
                if (pris === null) return
                const dernier = links.map((l, i) => (l.section === sec ? i : -1))
                  .filter(i => i >= 0).pop()
                deplacer(pris, dernier ?? links.length - 1, sec)
                setPris(null); setCible(null)
              }}>
              {links.map((l, i) => ({ l, i })).filter(({ l }) => l.section === sec).map(({ l, i }, rang, tous) => (
                <div key={`${l.url}-${i}`}
                  draggable
                  onDragStart={() => setPris(i)}
                  onDragEnd={() => { setPris(null); setCible(null) }}
                  onDragOver={e => { e.preventDefault(); setCible(i) }}
                  onDragLeave={() => setCible(c => (c === i ? null : c))}
                  onDrop={e => {
                    e.stopPropagation()   // sinon la zone de section reprend la main
                    if (pris !== null) deplacer(pris, i, l.section)
                    setPris(null); setCible(null)
                  }}
                  className={clsx(
                    'group flex items-center gap-1 px-2 py-2 bg-white border rounded-lg transition-all',
                    pris === i ? 'opacity-40 border-blue-400'
                      : cible === i ? 'border-blue-400 ring-2 ring-blue-100'
                      : 'border-gray-200 hover:border-blue-300 hover:shadow-sm')}>

                  <GripVertical size={14}
                    className="text-gray-300 shrink-0 cursor-grab active:cursor-grabbing" />

                  <a href={l.url} target="_blank" rel="noopener noreferrer"
                    className="flex items-center justify-between gap-1.5 flex-1 min-w-0 text-sm">
                    <span className="font-medium text-gray-700 truncate">{l.label}</span>
                    <ExternalLink size={13} className="text-gray-300 shrink-0" />
                  </a>

                  {/* Repli tactile et clavier du glisser-déposer. Discret au repos, mais
                      toujours atteignable : masqué au survol seulement, il serait inutilisable
                      là où il sert le plus. */}
                  <span className="flex items-center shrink-0">
                    <button type="button" onClick={() => decaler(i, -1)} disabled={rang === 0}
                      aria-label="Déplacer vers la gauche"
                      className="p-0.5 text-gray-300 hover:text-blue-600 disabled:opacity-0">
                      <ChevronLeft size={14} />
                    </button>
                    <button type="button" onClick={() => decaler(i, 1)} disabled={rang === tous.length - 1}
                      aria-label="Déplacer vers la droite"
                      className="p-0.5 text-gray-300 hover:text-blue-600 disabled:opacity-0">
                      <ChevronRight size={14} />
                    </button>
                  </span>
                </div>
              ))}
            </div>
          </CollapsibleSection>
        ))}
      </>}
    </div>
  )
}
