/**
 * Page Paramètres — Configuration des dossiers surveillés, stats, services
 */
import { useEffect, useState } from 'react'
import { Plus, Trash2, RefreshCw, FolderOpen, CheckCircle, XCircle, Database, FileText, HardDrive } from 'lucide-react'
import { foldersApi, systemApi, statsApi, type DocumentStats } from '../api'
import { useToast } from '../components/common/Toast'
import LoadingSpinner from '../components/common/LoadingSpinner'
import type { DossierSurveille } from '../types'

function ServiceBadge({ label, ok }: { label: string; ok: boolean | null }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      {ok === null ? (
        <LoadingSpinner size={14} />
      ) : ok ? (
        <CheckCircle size={16} className="text-green-500" />
      ) : (
        <XCircle size={16} className="text-red-500" />
      )}
      <span className={ok ? 'text-gray-700' : 'text-gray-400'}>{label}</span>
    </div>
  )
}

function formatBytes(octets: number): string {
  if (octets < 1024) return `${octets} o`
  if (octets < 1024 * 1024) return `${(octets / 1024).toFixed(0)} Ko`
  if (octets < 1024 * 1024 * 1024) return `${(octets / (1024 * 1024)).toFixed(1)} Mo`
  return `${(octets / (1024 * 1024 * 1024)).toFixed(2)} Go`
}

const STATUT_LABELS: Record<string, { label: string; color: string }> = {
  enriched: { label: 'Enrichis', color: 'text-green-600 bg-green-50' },
  extracted: { label: 'Extraits', color: 'text-blue-600 bg-blue-50' },
  pending: { label: 'En attente', color: 'text-yellow-600 bg-yellow-50' },
  error: { label: 'Erreurs', color: 'text-red-600 bg-red-50' },
}

export default function SettingsPage() {
  const [dossiers, setDossiers] = useState<DossierSurveille[]>([])
  const [nouveauChemin, setNouveauChemin] = useState('')
  const [ajoutLoading, setAjoutLoading] = useState(false)
  const [services, setServices] = useState<{ tika: boolean | null; ollama: boolean | null }>({ tika: null, ollama: null })
  const [stats, setStats] = useState<DocumentStats | null>(null)
  const toast = useToast()

  useEffect(() => {
    foldersApi.list().then(d => setDossiers(d.dossiers)).catch(() => {})

    systemApi.health().then(h => setServices({
      tika: h.services.tika.disponible,
      ollama: h.services.ollama.disponible,
    })).catch(() => setServices({ tika: false, ollama: false }))

    statsApi.getDocumentStats().then(setStats).catch(() => {})
  }, [])

  const ajouterDossier = async () => {
    if (!nouveauChemin.trim()) return
    setAjoutLoading(true)
    try {
      const d = await foldersApi.add({ chemin: nouveauChemin.trim() })
      setDossiers(prev => [...prev, d as unknown as DossierSurveille])
      setNouveauChemin('')
      toast.success('Dossier ajouté — scan en cours…')
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : 'Erreur ajout dossier')
    } finally {
      setAjoutLoading(false)
    }
  }

  const supprimerDossier = async (id: string) => {
    try {
      await foldersApi.remove(id)
      setDossiers(prev => prev.filter(d => d.id !== id))
      toast.success('Dossier retiré de la surveillance')
    } catch {
      toast.error('Erreur suppression dossier')
    }
  }

  const scannerDossier = async (id: string) => {
    try {
      await foldersApi.scan(id)
      toast.info('Scan lancé en arrière-plan')
    } catch {
      toast.error('Erreur lancement du scan')
    }
  }

  const toggleActif = async (d: DossierSurveille) => {
    try {
      const mis = await foldersApi.update(d.id, { actif: !d.actif }) as unknown as DossierSurveille
      setDossiers(prev => prev.map(x => x.id === d.id ? mis : x))
    } catch {
      toast.error('Erreur mise à jour')
    }
  }

  return (
    <div className="max-w-3xl mx-auto p-6 flex flex-col gap-8">

      {/* ── Statistiques ─────────────────────────────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-3">Statistiques</h2>
        {stats === null ? (
          <LoadingSpinner label="Chargement des statistiques…" />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {/* Total documents */}
            <div className="bg-white border border-gray-200 rounded-lg p-4 flex items-center gap-3">
              <Database size={20} className="text-blue-500 shrink-0" />
              <div>
                <p className="text-2xl font-bold text-gray-800">{stats.total_documents.toLocaleString('fr-FR')}</p>
                <p className="text-xs text-gray-500">Documents indexés</p>
              </div>
            </div>

            {/* Taille totale */}
            <div className="bg-white border border-gray-200 rounded-lg p-4 flex items-center gap-3">
              <HardDrive size={20} className="text-purple-500 shrink-0" />
              <div>
                <p className="text-2xl font-bold text-gray-800">{formatBytes(stats.taille_totale_octets)}</p>
                <p className="text-xs text-gray-500">Volume indexé</p>
              </div>
            </div>

            {/* Documents enrichis */}
            <div className="bg-white border border-gray-200 rounded-lg p-4 flex items-center gap-3">
              <FileText size={20} className="text-green-500 shrink-0" />
              <div>
                <p className="text-2xl font-bold text-gray-800">
                  {(stats.par_statut['enriched'] ?? 0).toLocaleString('fr-FR')}
                </p>
                <p className="text-xs text-gray-500">Enrichis par IA</p>
              </div>
            </div>

            {/* Répartition par statut */}
            {Object.entries(stats.par_statut).length > 0 && (
              <div className="sm:col-span-3 bg-white border border-gray-200 rounded-lg p-4">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Répartition par statut</p>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(stats.par_statut).map(([statut, nb]) => {
                    const s = STATUT_LABELS[statut] ?? { label: statut, color: 'text-gray-600 bg-gray-50' }
                    return (
                      <span key={statut} className={`text-xs px-2.5 py-1.5 rounded-lg font-medium ${s.color}`}>
                        {s.label} : {nb}
                      </span>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Top catégories */}
            {stats.categories.length > 0 && (
              <div className="sm:col-span-3 bg-white border border-gray-200 rounded-lg p-4">
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Catégories principales</p>
                <div className="space-y-1.5">
                  {stats.categories.slice(0, 6).map(c => {
                    const pct = stats.total_documents > 0
                      ? Math.round((c.nb_documents / stats.total_documents) * 100)
                      : 0
                    return (
                      <div key={c.categorie} className="flex items-center gap-2">
                        <span className="text-xs text-gray-600 w-32 shrink-0 truncate">{c.categorie}</span>
                        <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-blue-400 rounded-full"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-400 w-8 text-right shrink-0">{c.nb_documents}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* ── État des services ─────────────────────────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-3">État des services</h2>
        <div className="bg-white border border-gray-200 rounded-lg p-4 flex flex-col gap-2">
          <ServiceBadge
            label={`Tika — ${import.meta.env.VITE_TIKA_URL || 'http://localhost:9998'}`}
            ok={services.tika}
          />
          <ServiceBadge
            label={`Ollama — ${import.meta.env.VITE_OLLAMA_URL || 'http://localhost:11434'}`}
            ok={services.ollama}
          />
        </div>
      </section>

      {/* ── Dossiers surveillés ───────────────────────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-3">Dossiers surveillés</h2>

        {/* Ajouter un dossier */}
        <div className="flex gap-2 mb-3">
          <input
            type="text"
            value={nouveauChemin}
            onChange={e => setNouveauChemin(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && ajouterDossier()}
            placeholder="Chemin absolu du dossier (ex: C:\Users\…\Documents)"
            className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
          <button
            onClick={ajouterDossier}
            disabled={!nouveauChemin.trim() || ajoutLoading}
            className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg disabled:opacity-40 transition-colors"
          >
            {ajoutLoading ? <LoadingSpinner size={14} /> : <Plus size={15} />}
            Ajouter
          </button>
        </div>

        {/* Liste des dossiers */}
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          {dossiers.length === 0 && (
            <div className="flex flex-col items-center gap-2 py-8 text-gray-300">
              <FolderOpen size={32} strokeWidth={1} />
              <p className="text-sm">Aucun dossier surveillé</p>
              <p className="text-xs">Ajoutez un dossier pour que DocFlow AI indexe automatiquement vos documents</p>
            </div>
          )}
          {dossiers.map((d, i) => (
            <div
              key={d.id}
              className={`flex items-center gap-3 px-4 py-3 ${i > 0 ? 'border-t border-gray-100' : ''}`}
            >
              {/* Toggle actif */}
              <button
                onClick={() => toggleActif(d)}
                className={`w-2.5 h-2.5 rounded-full shrink-0 transition-colors ${d.actif ? 'bg-green-400' : 'bg-gray-300'}`}
                title={d.actif ? 'Actif — cliquer pour désactiver' : 'Inactif — cliquer pour activer'}
              />

              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-800 truncate">{d.nom_affichage || d.chemin}</p>
                {d.nom_affichage && (
                  <p className="text-xs text-gray-400 truncate font-mono">{d.chemin}</p>
                )}
                {d.dernier_scan && (
                  <p className="text-xs text-gray-400">
                    Dernier scan : {new Date(d.dernier_scan).toLocaleString('fr-FR')}
                  </p>
                )}
              </div>

              <div className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => scannerDossier(d.id)}
                  title="Forcer un scan immédiat"
                  className="p-1.5 text-gray-400 hover:text-blue-500 hover:bg-blue-50 rounded-md transition-colors"
                >
                  <RefreshCw size={14} />
                </button>
                <button
                  onClick={() => supprimerDossier(d.id)}
                  title="Retirer de la surveillance"
                  className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-400 mt-2">
          Les fichiers des dossiers surveillés sont indexés automatiquement (PDF, DOCX, PPTX, XLSX, ZIP…).
          Le scan se déclenche toutes les 5 minutes ou sur demande.
        </p>
      </section>

      {/* ── À propos ──────────────────────────────────────── */}
      <section>
        <h2 className="text-base font-semibold text-gray-800 mb-3">À propos</h2>
        <div className="bg-white border border-gray-200 rounded-lg p-4 text-sm text-gray-600 space-y-1">
          <p><strong>DocFlow AI v0.5.0</strong> — Plateforme locale de gestion documentaire intelligente</p>
          <p className="text-gray-400">100% local · Aucune donnée envoyée vers le cloud</p>
          <div className="flex flex-wrap gap-2 pt-2">
            {['Ollama', 'Apache Tika', 'PostgreSQL + pgvector', 'FastAPI', 'React 18'].map(tech => (
              <span key={tech} className="text-xs px-2 py-0.5 bg-gray-100 text-gray-500 rounded-full">{tech}</span>
            ))}
          </div>
        </div>
      </section>

    </div>
  )
}
