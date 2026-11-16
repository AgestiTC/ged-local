/**
 * Page « Documentation des applications » (plan docs/plan-reception-doc-applications.md, étape 4).
 *
 * Les applications DÉPOSENT leur doc dans une zone du NAS (un sous-dossier par application) ; la
 * Matothèque la ramasse, la classe et la versionne. Cette page montre, par application, les
 * documents reçus, la version annoncée, la date du dernier dépôt, et l'historique des versions
 * (texte des 5 dernières relisible).
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, BookText, ChevronDown, Eye, History, RefreshCw } from 'lucide-react'
import { extractApiError } from '../api'
import { docApplicationsApi, type Application, type VersionDoc } from '../api/docApplications'
import { ageDepot } from '../utils/docApplications'

function HistoriqueVersions({ documentId }: { documentId: string }) {
  const [versions, setVersions] = useState<VersionDoc[] | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [lu, setLu] = useState<{ titre: string; texte: string } | null>(null)

  useEffect(() => {
    docApplicationsApi.versions(documentId).then(setVersions).catch(e => setErreur(extractApiError(e)))
  }, [documentId])

  const lire = async (v: VersionDoc) => {
    try {
      const c = await docApplicationsApi.contenuVersion(documentId, v.id)
      setLu({ titre: `Version ${v.numero_version}${v.libelle ? ` (${v.libelle})` : ''}`, texte: c.texte })
    } catch (e) {
      setErreur(extractApiError(e))
    }
  }

  if (erreur) return <p className="text-xs text-red-600">{erreur}</p>
  if (!versions) return <p className="text-xs text-gray-500">Chargement de l'historique…</p>
  if (!versions.length) return <p className="text-xs text-gray-500">Aucune version précédente.</p>
  return (
    <div className="mt-2 space-y-1">
      {versions.map(v => (
        <div key={v.id} className="flex items-center gap-2 text-xs text-gray-600">
          <span className="font-mono">v{v.numero_version}</span>
          {v.libelle && <span className="px-1.5 rounded bg-gray-100">{v.libelle}</span>}
          <span>{v.date_detection ? new Date(v.date_detection).toLocaleDateString('fr-FR') : ''}</span>
          {v.diff_resume && <span className="italic truncate">— {v.diff_resume}</span>}
          {v.archive_disponible
            ? <button type="button" onClick={() => lire(v)} className="text-blue-600 hover:underline">lire</button>
            : <span className="text-gray-400">texte non conservé</span>}
        </div>
      ))}
      {lu && (
        <div className="mt-2 border rounded bg-gray-50 p-2">
          <div className="flex justify-between text-xs font-medium mb-1">
            <span>{lu.titre}</span>
            <button type="button" onClick={() => setLu(null)} className="text-gray-500 hover:text-gray-800">fermer</button>
          </div>
          <pre className="text-xs whitespace-pre-wrap max-h-80 overflow-auto">{lu.texte}</pre>
        </div>
      )}
    </div>
  )
}

export default function DocApplicationsPage() {
  const [applications, setApplications] = useState<Application[] | null>(null)
  const [jours, setJours] = useState(90)
  const [erreur, setErreur] = useState<string | null>(null)
  const [ouvert, setOuvert] = useState<string | null>(null)

  const charger = () => {
    setErreur(null)
    docApplicationsApi.lister()
      .then(r => { setApplications(r.applications); setJours(r.jours_sans_depot) })
      .catch(e => setErreur(extractApiError(e)))
  }
  useEffect(charger, [])

  return (
    <div className="p-6 max-w-5xl">
      <div className="flex items-center gap-2 mb-1">
        <BookText size={20} className="text-blue-600" />
        <h1 className="text-xl font-semibold">Documentation des applications</h1>
        <button type="button" onClick={charger} title="Actualiser" className="ml-auto text-gray-500 hover:text-gray-800">
          <RefreshCw size={16} />
        </button>
      </div>
      <p className="text-sm text-gray-500 mb-4">
        Chaque application dépose sa documentation dans sa zone du NAS ; la Matothèque la range et garde ses
        versions. Une application sans dépôt depuis {jours} jours est signalée.
      </p>

      {erreur && <p className="text-sm text-red-600 mb-3">{erreur}</p>}
      {!applications && !erreur && <p className="text-sm text-gray-500">Chargement…</p>}
      {applications && !applications.length && (
        <p className="text-sm text-gray-500">
          Aucune documentation reçue pour l'instant. Un administrateur déclare la zone de dépôt dans
          Paramètres › Sources & indexation › Règles de classement.
        </p>
      )}

      <div className="space-y-3">
        {applications?.map(a => (
          <div key={`${a.regle}/${a.appli}`} className="border rounded-lg bg-white">
            <div className="flex items-center gap-2 px-4 py-2 border-b">
              <span className="font-medium">{a.appli}</span>
              <span className="text-xs text-gray-500">dernier dépôt : {ageDepot(a.dernier_depot)}</span>
              {a.en_retard && (
                <span className="ml-auto flex items-center gap-1 text-xs text-amber-700">
                  <AlertTriangle size={13} /> pas de dépôt depuis plus de {jours} jours
                </span>
              )}
            </div>
            <ul className="divide-y">
              {a.documents.map(d => (
                <li key={d.id} className="px-4 py-2">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="flex-1 truncate" title={d.nom}>{d.titre}</span>
                    {d.version && <span className="text-xs px-1.5 rounded bg-blue-50 text-blue-700">v {d.version}</span>}
                    {d.statut === 'absent' && <span className="text-xs text-gray-400">retiré du NAS</span>}
                    <span className="text-xs text-gray-500">{d.nb_versions} version{d.nb_versions > 1 ? 's' : ''}</span>
                    <button type="button" onClick={() => setOuvert(ouvert === d.id ? null : d.id)}
                      className="text-xs text-gray-600 hover:text-gray-900 flex items-center gap-1" title="Historique des versions">
                      <History size={13} /> historique
                      <ChevronDown size={12} className={ouvert === d.id ? '' : '-rotate-90'} />
                    </button>
                    <Link to={`/ged?doc=${d.id}`} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
                      <Eye size={12} /> ouvrir
                    </Link>
                  </div>
                  {ouvert === d.id && <HistoriqueVersions documentId={d.id} />}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  )
}
