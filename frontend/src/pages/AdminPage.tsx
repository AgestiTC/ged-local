/**
 * AdminPage — Administration
 * ==========================
 * Deux onglets :
 *
 * - **Liens** : raccourcis externes utiles, regroupés par section (gérés dans
 *   Paramètres → « Administration — liens »). Ouverture en nouvel onglet.
 * - **Aide à la déclaration** : où reporter quoi sur sa déclaration de revenus, à partir
 *   de ce que Matothèque connaît déjà. Voir `components/admin/AideDeclaration`.
 *
 * ⚠️ La page ne s'affichait dans la barre latérale que si des **liens** existaient. Livrer
 * l'aide à la déclaration sans toucher à cette condition l'aurait rendue **invisible pour
 * une raison sans rapport** — la leçon v1.84.3 (« ne plus masquer une commande faute de
 * donnée »), déjà payée une fois. La condition vit dans `Sidebar`, et couvre désormais les
 * deux onglets.
 */
import { useEffect, useState } from 'react'
import { ExternalLink, Stethoscope, Landmark, Link2, Settings, Receipt } from 'lucide-react'
import { Link } from 'react-router-dom'
import { clsx } from 'clsx'
import CollapsibleSection from '../components/common/CollapsibleSection'
import LoadingSpinner from '../components/common/LoadingSpinner'
import AideDeclaration from '../components/admin/AideDeclaration'
import { systemApi, type AdminLink } from '../api'

function iconePour(section: string) {
  const s = section.toLowerCase()
  if (/m[ée]dic|sant[ée]|docto/.test(s)) return <Stethoscope size={16} className="text-red-500" />
  if (/gouv|impot|impôt|ants|admin|etat|état/.test(s)) return <Landmark size={16} className="text-blue-600" />
  return <Link2 size={16} className="text-gray-500" />
}

type Onglet = 'liens' | 'impots'

export default function AdminPage() {
  const [links, setLinks] = useState<AdminLink[]>([])
  const [loading, setLoading] = useState(true)
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

  // Sections dans l'ordre d'apparition.
  const sections = links.reduce<string[]>((acc, l) => (acc.includes(l.section) ? acc : [...acc, l.section]), [])

  return (
    <div className="max-w-4xl mx-auto p-3 sm:p-6 flex flex-col gap-3">
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
      ) : (
        sections.map(sec => (
          <CollapsibleSection key={sec} id={`admin-${sec}`} defaultOpen icon={iconePour(sec)} title={sec}>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
              {links.filter(l => l.section === sec).map((l, i) => (
                <a key={`${l.url}-${i}`} href={l.url} target="_blank" rel="noopener noreferrer"
                  className="flex items-center justify-between gap-2 px-3 py-2.5 bg-white border border-gray-200 rounded-lg hover:border-blue-300 hover:shadow-sm transition-all text-sm">
                  <span className="font-medium text-gray-700 truncate">{l.label}</span>
                  <ExternalLink size={14} className="text-gray-300 shrink-0" />
                </a>
              ))}
            </div>
          </CollapsibleSection>
        ))
      )}
    </div>
  )
}
