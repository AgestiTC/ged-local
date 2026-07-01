/**
 * AdminPage — Administration : liens externes utiles, regroupés par section (pliable).
 * Les liens sont gérés dynamiquement dans Paramètres → « Administration — liens ».
 * Ouverture en nouvel onglet.
 */
import { useEffect, useState } from 'react'
import { ExternalLink, Stethoscope, Landmark, Link2, Settings } from 'lucide-react'
import { Link } from 'react-router-dom'
import CollapsibleSection from '../components/common/CollapsibleSection'
import LoadingSpinner from '../components/common/LoadingSpinner'
import { systemApi, type AdminLink } from '../api'

function iconePour(section: string) {
  const s = section.toLowerCase()
  if (/m[ée]dic|sant[ée]|docto/.test(s)) return <Stethoscope size={16} className="text-red-500" />
  if (/gouv|impot|impôt|ants|admin|etat|état/.test(s)) return <Landmark size={16} className="text-blue-600" />
  return <Link2 size={16} className="text-gray-500" />
}

export default function AdminPage() {
  const [links, setLinks] = useState<AdminLink[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    systemApi.getConfig()
      .then(c => { try { setLinks(JSON.parse(c.admin_links?.valeur || '[]')) } catch { setLinks([]) } })
      .catch(() => setLinks([]))
      .finally(() => setLoading(false))
  }, [])

  // Sections dans l'ordre d'apparition.
  const sections = links.reduce<string[]>((acc, l) => (acc.includes(l.section) ? acc : [...acc, l.section]), [])

  return (
    <div className="max-w-4xl mx-auto p-6 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-bold text-gray-800 flex items-center gap-2">🗂️ Administration</h1>
        <Link to="/settings" className="text-xs text-gray-400 hover:text-blue-600 flex items-center gap-1">
          <Settings size={13} /> Gérer les liens
        </Link>
      </div>

      {loading ? (
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
