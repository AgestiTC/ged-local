/**
 * Page Dossiers thématiques — liste des sujets de veille.
 * Chaque dossier rassemble des ressources EXTERNES (podcasts, documentaires, livres,
 * études…) autour d'un sujet. Les dossiers pré-remplis livrés avec l'application
 * s'installent d'un clic (idempotent). Backend : /api/dossiers.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Library, Plus, Trash2, RefreshCw, Download, ChevronRight } from 'lucide-react'
import { clsx } from 'clsx'
import { dossiersApi, type DossierResume, type SeedDisponible } from '../api'
import { useToast } from '../components/common/Toast'
import LoadingSpinner from '../components/common/LoadingSpinner'

export default function DossiersPage() {
  const toast = useToast()
  const [dossiers, setDossiers] = useState<DossierResume[]>([])
  const [seeds, setSeeds] = useState<SeedDisponible[]>([])
  const [loading, setLoading] = useState(true)
  const [creation, setCreation] = useState(false)
  const [titre, setTitre] = useState('')
  const [description, setDescription] = useState('')
  const [installe, setInstalle] = useState<string | null>(null)

  const charger = () => {
    setLoading(true)
    dossiersApi.list()
      .then(setDossiers)
      .catch(() => toast.error('Chargement des dossiers impossible'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { charger() }, [])
  useEffect(() => { dossiersApi.types().then(r => setSeeds(r.seeds)).catch(() => {}) }, [])

  const creer = async () => {
    if (!titre.trim()) return
    try {
      await dossiersApi.create({ titre: titre.trim(), description: description.trim() || undefined })
      toast.success(`Dossier « ${titre.trim()} » créé`)
      setTitre(''); setDescription(''); setCreation(false)
      charger()
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(detail || 'Création impossible')
    }
  }

  const supprimer = async (d: DossierResume) => {
    if (!confirm(`Supprimer « ${d.titre} » et ses ${d.nb_ressources} ressources ?`)) return
    try {
      await dossiersApi.remove(d.id)
      toast.success('Dossier supprimé')
      charger()
    } catch { toast.error('Suppression échouée') }
  }

  const installer = async (seed: SeedDisponible) => {
    setInstalle(seed.cle)
    try {
      const r = await dossiersApi.installerSeed(seed.cle)
      // Réinstallation : le message doit dire ce qui s'est réellement passé, pas « installé ».
      if (r.cree) toast.success(`« ${seed.titre} » installé — ${r.ajoutees} ressources`)
      else if (r.ajoutees > 0) toast.success(`${r.ajoutees} ressource(s) ajoutée(s) à « ${seed.titre} »`)
      else toast.success(`« ${seed.titre} » est déjà à jour`)
      charger()
    } catch { toast.error('Installation impossible') } finally { setInstalle(null) }
  }

  const dejaInstalle = (cle: string) => dossiers.some(d => d.slug === cle)

  return (
    <div className="h-full overflow-y-auto bg-gray-50">
      <div className="max-w-4xl mx-auto p-4 md:p-6 space-y-6">

        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold flex items-center gap-2">
              <Library size={18} className="text-blue-600" /> Dossiers thématiques
            </h1>
            <p className="text-sm text-gray-500 mt-1 max-w-2xl">
              Veille par sujet : podcasts, chaînes, documentaires, livres, articles et études
              rassemblés autour d'un thème. Ressources externes — la GED, elle, indexe des fichiers.
            </p>
          </div>
          <button type="button" onClick={charger} title="Rafraîchir"
            className="text-gray-400 hover:text-gray-600 shrink-0 mt-1">
            <RefreshCw size={15} />
          </button>
        </header>

        {/* Création */}
        <section className="bg-white border border-gray-200 rounded-lg">
          {!creation ? (
            <button type="button" onClick={() => setCreation(true)}
              className="w-full flex items-center gap-2 px-4 py-3 text-sm text-blue-600 hover:bg-gray-50 rounded-lg transition-colors">
              <Plus size={15} /> Nouveau dossier
            </button>
          ) : (
            <div className="p-4 space-y-3">
              <input autoFocus value={titre} onChange={e => setTitre(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') creer(); if (e.key === 'Escape') setCreation(false) }}
                placeholder="Titre du dossier (ex. Devenir parent)"
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md bg-white" />
              <input value={description} onChange={e => setDescription(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') creer(); if (e.key === 'Escape') setCreation(false) }}
                placeholder="Description (optionnelle)"
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md bg-white" />
              <div className="flex gap-2">
                <button type="button" onClick={creer} disabled={!titre.trim()}
                  className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md disabled:opacity-40">
                  Créer
                </button>
                <button type="button" onClick={() => { setCreation(false); setTitre(''); setDescription('') }}
                  className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700">
                  Annuler
                </button>
              </div>
            </div>
          )}
        </section>

        {/* Dossiers existants */}
        {loading && <LoadingSpinner label="Chargement…" className="py-10 justify-center" />}

        {!loading && dossiers.length === 0 && (
          <p className="text-sm text-gray-400 text-center py-8">
            Aucun dossier. Crée-en un, ou installe un dossier pré-rempli ci-dessous.
          </p>
        )}

        {!loading && dossiers.length > 0 && (
          <ul className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
            {dossiers.map(d => (
              <li key={d.id} className="flex items-center gap-3 group">
                <Link to={`/dossiers/${d.slug}`} className="flex-1 min-w-0 px-4 py-3 hover:bg-gray-50 transition-colors">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-medium text-gray-800 truncate">{d.titre}</p>
                    {d.origine.startsWith('seed:') && (
                      <span className="shrink-0 text-[10px] uppercase tracking-wide text-gray-400 border border-gray-200 rounded px-1.5 py-0.5">
                        pré-rempli
                      </span>
                    )}
                  </div>
                  {d.description && <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{d.description}</p>}
                  <p className="text-xs text-gray-400 mt-1">
                    {d.nb_ressources} ressource{d.nb_ressources > 1 ? 's' : ''}
                  </p>
                </Link>
                <button type="button" onClick={() => supprimer(d)} title="Supprimer le dossier"
                  className="p-2 text-gray-300 hover:text-red-500 transition-colors">
                  <Trash2 size={14} />
                </button>
                <ChevronRight size={15} className="text-gray-300 mr-3 shrink-0" />
              </li>
            ))}
          </ul>
        )}

        {/* Dossiers pré-remplis livrés avec l'application */}
        {seeds.length > 0 && (
          <section>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
              Dossiers pré-remplis
            </h2>
            <ul className="bg-white border border-gray-200 rounded-lg divide-y divide-gray-100">
              {seeds.map(s => (
                <li key={s.cle} className="flex items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0">
                    <p className="text-sm text-gray-800">{s.titre}</p>
                    <p className="text-xs text-gray-400">{s.nb} ressources prêtes à l'emploi</p>
                  </div>
                  <button type="button" onClick={() => installer(s)} disabled={installe === s.cle}
                    title={dejaInstalle(s.cle)
                      ? 'Réinstaller : ajoute uniquement les ressources absentes, ne restaure rien de supprimé'
                      : 'Installer ce dossier'}
                    className={clsx(
                      'shrink-0 flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border transition-colors',
                      dejaInstalle(s.cle)
                        ? 'border-gray-200 text-gray-500 hover:bg-gray-50'
                        : 'border-blue-200 text-blue-600 bg-blue-50 hover:bg-blue-100',
                    )}>
                    <Download size={13} />
                    {installe === s.cle ? 'Installation…' : dejaInstalle(s.cle) ? 'Compléter' : 'Installer'}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  )
}
