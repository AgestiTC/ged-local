/**
 * Sidebar — Navigation principale Matothèque
 * Menus DYNAMIQUES : un item n'apparaît que si le service correspondant est configuré
 * (BookStack → Publier + WIKI ; token HuggingFace → HuggingFace).
 * Pas de menu parasite.
 *
 * ⚠️ « Dynamique » ne veut pas dire « conditionné à n'importe quelle donnée ». Administration
 * n'apparaissait que si des LIENS externes existaient — condition devenue fausse le jour où la
 * page a gagné l'onglet « Aide à la déclaration » : la fonctionnalité était livrée et invisible
 * pour une raison sans rapport avec elle. La condition couvre désormais les DEUX onglets
 * (leçon v1.84.3).
 */
import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { BookOpen, Boxes, ChevronDown, Copy, ExternalLink, Folder, Layers, LayoutGrid, Library, Link2, Notebook, PenSquare, FolderOpen, FolderTree, ScanLine, Settings, Upload, X } from 'lucide-react'
import { dossiersApi, fiscaliteApi, systemApi, type DossierResume } from '../../api'
import { DOSSIERS_MAJ } from '../../utils/evenements'
import Logo from './Logo'

export default function Sidebar({ drawerOpen = false, onClose }: { drawerOpen?: boolean; onClose?: () => void }) {
  const location = useLocation()
  const [version, setVersion] = useState<string | null>(null)
  const [bookstackUrl, setBookstackUrl] = useState('')
  const [hfConfig, setHfConfig] = useState(false)
  const [adminCount, setAdminCount] = useState(0)
  // Administration porte aussi l'aide à la déclaration : elle suffit à justifier le menu.
  const [fiscaliteDispo, setFiscaliteDispo] = useState(false)
  // État déplié/replié du menu Wiki, mémorisé entre les visites.
  const [wikiOpen, setWikiOpen] = useState(() => localStorage.getItem('mtq_wiki_open') !== 'false')

  // ── Arborescence des dossiers thématiques ────────────────────────────────
  // Racines chargées d'emblée ; sous-dossiers à la demande. Une barre latérale de 208 px
  // ne peut pas porter un arbre complet, et charger le détail de chaque dossier au montage
  // ferait N requêtes pour un menu que l'on n'ouvrira peut-être pas.
  const [dossiersOpen, setDossiersOpen] = useState(() => localStorage.getItem('mtq_dossiers_open') !== 'false')
  const [racines, setRacines] = useState<DossierResume[]>([])
  const [deplies, setDeplies] = useState<Record<string, boolean>>({})
  const [enfants, setEnfants] = useState<Record<string, DossierResume[]>>({})

  const chargerEnfants = useCallback(async (slug: string) => {
    try {
      const d = await dossiersApi.get(slug)
      setEnfants(e => ({ ...e, [slug]: d.sous_dossiers }))
    } catch { /* un menu ne doit jamais faire d'esclandre : au pire il n'affiche rien */ }
  }, [])

  const chargerRacines = useCallback(async (deplieesActuelles: Record<string, boolean>) => {
    try {
      setRacines(await dossiersApi.list())
    } catch { return }
    // Les branches ouvertes sont relues : un sous-dossier créé à l'instant doit apparaître
    // sans qu'on ait à replier puis redéplier son parent.
    for (const slug of Object.keys(deplieesActuelles).filter(s => deplieesActuelles[s])) {
      void chargerEnfants(slug)
    }
  }, [chargerEnfants])

  useEffect(() => { void chargerRacines(deplies) }, [])

  // « Ajout dynamique » : les pages qui créent ou suppriment un dossier crient, on relit.
  // Elles n'ont pas à connaître la barre latérale (cf. utils/evenements).
  useEffect(() => {
    const relire = () => void chargerRacines(deplies)
    window.addEventListener(DOSSIERS_MAJ, relire)
    return () => window.removeEventListener(DOSSIERS_MAJ, relire)
  }, [chargerRacines, deplies])

  const basculerDossier = (slug: string) => {
    setDeplies(d => {
      const ouvert = !d[slug]
      if (ouvert && !enfants[slug]) void chargerEnfants(slug)
      return { ...d, [slug]: ouvert }
    })
  }

  useEffect(() => { systemApi.version().then(v => setVersion(v.version)).catch(() => {}) }, [])
  useEffect(() => {
    fiscaliteApi.disponible().then(d => setFiscaliteDispo(d.disponible)).catch(() => {})
  }, [])
  useEffect(() => {
    systemApi.getConfig().then(c => {
      setBookstackUrl(c.bookstack_url?.valeur ?? '')
      setHfConfig(!!(c.huggingface_token?.defini || c.huggingface_token?.valeur))
      try { setAdminCount((JSON.parse(c.admin_links?.valeur || '[]') as unknown[]).length) } catch { setAdminCount(0) }
    }).catch(() => {})
  }, [])

  // Items internes conditionnels (pas de menu inutile si non configuré).
  const items = [
    { to: '/', label: 'Créer', Icon: PenSquare, show: true },
    { to: '/ged', label: 'GED', Icon: FolderOpen, show: true },
    { to: '/scans', label: 'Scans', Icon: ScanLine, show: true },
    { to: '/regroupements', label: 'Regroupements', Icon: Layers, show: true },
    { to: '/doublons', label: 'Doublons', Icon: Copy, show: true },
    { to: '/liens', label: 'Liens', Icon: Link2, show: true },
    { to: '/dossiers', label: 'Dossiers', Icon: Notebook, show: true },
    { to: '/reorganiser', label: 'Réorganiser', Icon: FolderTree, show: true },
    { to: '/huggingface', label: 'HuggingFace', Icon: Boxes, show: hfConfig },
    { to: '/admin', label: 'Administration', Icon: LayoutGrid, show: adminCount > 0 || fiscaliteDispo },
  ].filter(i => i.show)

  const cls = (active: boolean) =>
    `flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
      active ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-800 hover:text-white'
    }`

  // « Dossiers » est actif sur la liste ET sur n'importe quel dossier ouvert.
  const dansDossiers = location.pathname === '/dossiers' || location.pathname.startsWith('/dossiers/')

  return (
    <nav className={
      // Desktop (≥ md) : colonne fixe. Mobile : tiroir off-canvas glissant, masqué par défaut.
      'w-60 max-w-[80vw] bg-gray-900 text-white flex flex-col shrink-0 z-40 ' +
      'fixed inset-y-0 left-0 transform transition-transform duration-200 md:static md:translate-x-0 md:w-52 ' +
      (drawerOpen ? 'translate-x-0' : '-translate-x-full')
    }>
      <div className="p-4 border-b border-gray-700 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          {/* En thème sombre, on atténue le badge (feuilles blanches pleines) pour retirer la sur-brillance. */}
          <Logo size={32} className="shrink-0 dark:brightness-75" />
          <div>
            <h1 className="font-bold text-base tracking-tight">Matothèque</h1>
            <p className="text-xs text-gray-500 mt-0.5">{version ? `v${version} — ` : ''}100% local</p>
          </div>
        </div>
        {/* Fermer le tiroir (mobile uniquement) */}
        <button type="button" onClick={onClose} className="md:hidden p-1 text-gray-400 hover:text-white" aria-label="Fermer le menu">
          <X size={18} />
        </button>
      </div>
      <ul className="flex-1 p-2 space-y-0.5">
        {items.map(({ to, label, Icon }) => to === '/dossiers' ? (
          /* Dossiers — le lien reste un lien (on clique le mot pour aller à la liste) ;
             seul le chevron déplie l'arborescence. Mélanger les deux gestes sur la même
             zone est le défaut classique de ces menus. */
          <li key={to}>
            <div className={`flex items-center rounded-md ${dansDossiers ? 'bg-blue-600' : ''}`}>
              <Link to={to} className={`flex-1 min-w-0 ${cls(dansDossiers)}`}>
                <Icon size={15} />
                <span className="truncate">{label}</span>
              </Link>
              {racines.length > 0 && (
                <button type="button"
                  onClick={() => setDossiersOpen(o => { localStorage.setItem('mtq_dossiers_open', String(!o)); return !o })}
                  aria-expanded={dossiersOpen}
                  title={dossiersOpen ? "Replier l'arborescence" : "Déplier l'arborescence"}
                  className="px-2 py-2 text-gray-500 hover:text-white">
                  <ChevronDown size={14} className={`transition-transform ${dossiersOpen ? '' : '-rotate-90'}`} />
                </button>
              )}
            </div>

            {dossiersOpen && racines.length > 0 && (
              <ul className="mt-0.5 ml-4 pl-2 border-l border-gray-800 space-y-0.5">
                {racines.map(d => (
                  <li key={d.id}>
                    <div className="flex items-center rounded-md">
                      <Link to={`/dossiers/${d.slug}`} title={d.titre}
                        className={`flex-1 min-w-0 ${cls(location.pathname === `/dossiers/${d.slug}`)}`}>
                        <Folder size={14} className="shrink-0" />
                        <span className="truncate">{d.titre}</span>
                      </Link>
                      {d.nb_sous_dossiers > 0 && (
                        <button type="button" onClick={() => basculerDossier(d.slug)}
                          aria-expanded={!!deplies[d.slug]}
                          title={`${d.nb_sous_dossiers} sous-dossier${d.nb_sous_dossiers > 1 ? 's' : ''}`}
                          className="px-1.5 py-2 text-gray-500 hover:text-white">
                          <ChevronDown size={13} className={`transition-transform ${deplies[d.slug] ? '' : '-rotate-90'}`} />
                        </button>
                      )}
                    </div>

                    {deplies[d.slug] && (
                      <ul className="mt-0.5 ml-3 pl-2 border-l border-gray-800 space-y-0.5">
                        {(enfants[d.slug] ?? []).map(s => (
                          <li key={s.id}>
                            <Link to={`/dossiers/${s.slug}`} title={s.titre}
                              className={cls(location.pathname === `/dossiers/${s.slug}`)}>
                              <Folder size={13} className="shrink-0 text-gray-500" />
                              <span className="truncate text-[13px]">{s.titre}</span>
                            </Link>
                          </li>
                        ))}
                        {/* Le temps du chargement, on le dit plutôt que d'afficher un trou. */}
                        {!enfants[d.slug] && (
                          <li className="px-3 py-1.5 text-xs text-gray-600">Chargement…</li>
                        )}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ) : (
          <li key={to}>
            {/* Actif aussi sur les sous-routes (ex. /dossiers/devenir-parent), sauf pour « / ». */}
            <Link to={to} className={cls(location.pathname === to || (to !== '/' && location.pathname.startsWith(to + '/')))}>
              <Icon size={15} />
              <span>{label}</span>
            </Link>
          </li>
        ))}

        {/* Wiki — groupe dépliable : « Publier » (page interne) + « Ouvrir WIKI » (BookStack
            externe). Affiché seulement si BookStack est configuré. */}
        {bookstackUrl && (
          <li>
            <button
              type="button"
              onClick={() => setWikiOpen(o => { localStorage.setItem('mtq_wiki_open', String(!o)); return !o })}
              aria-expanded={wikiOpen}
              title={wikiOpen ? 'Replier le menu Wiki' : 'Déplier le menu Wiki'}
              className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors">
              <BookOpen size={15} />
              <span className="flex-1 text-left">Wiki</span>
              <ChevronDown size={14} className={`text-gray-500 transition-transform ${wikiOpen ? '' : '-rotate-90'}`} />
            </button>
            {wikiOpen && (
              <ul className="mt-0.5 ml-4 pl-2 border-l border-gray-800 space-y-0.5">
                <li>
                  <Link to="/wiki/livres" className={cls(location.pathname.startsWith('/wiki/livres'))}>
                    <Library size={15} />
                    <span>Liste des livres</span>
                  </Link>
                </li>
                <li>
                  <Link to="/wiki" className={cls(location.pathname === '/wiki')}>
                    <Upload size={15} />
                    <span>Publier</span>
                  </Link>
                </li>
                <li>
                  <a href={bookstackUrl} target="_blank" rel="noopener noreferrer"
                    title="Ouvrir BookStack dans un nouvel onglet"
                    className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-gray-300 hover:bg-gray-800 hover:text-white transition-colors">
                    <ExternalLink size={15} />
                    <span className="flex-1">Ouvrir WIKI</span>
                  </a>
                </li>
              </ul>
            )}
          </li>
        )}

        <li>
          <Link to="/settings" className={cls(location.pathname === '/settings')}>
            <Settings size={15} />
            <span>Paramètres</span>
          </Link>
        </li>
      </ul>
      <div className="p-3 border-t border-gray-700 text-xs text-gray-500">
        Ollama · Tika · pgvector · n8n
      </div>
    </nav>
  )
}
