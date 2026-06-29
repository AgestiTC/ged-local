/**
 * DocumentCard — Fiche complète d'un document dans la GED
 * Affiche métadonnées, résumé éditable, tags, entités, versions.
 * Onglets : Métadonnées | Texte extrait
 */
import { useEffect, useState } from 'react'
import {
  X, FileText, FolderOpen, Clock, Hash, HardDrive,
  RefreshCw, ExternalLink, Globe, Shield, AlignLeft, Copy, Check,
} from 'lucide-react'
import { documentsApi } from '../../api'
import type { Document, MetadonneeIA } from '../../types'
import TagManager from './TagManager'
import VersionHistory from './VersionHistory'
import LoadingSpinner from '../common/LoadingSpinner'
import { useToast } from '../common/Toast'
import { useDocumentStore } from '../../stores/documentStore'

interface Props {
  documentId: string
  onClose: () => void
  onUseInReport?: (id: string) => void
}

type Tab = 'meta' | 'texte'

function formatBytes(n?: number) {
  if (!n) return '—'
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} Ko`
  return `${(n / 1024 / 1024).toFixed(1)} Mo`
}

function Badge({ children, color = 'gray' }: { children: React.ReactNode; color?: string }) {
  const styles: Record<string, string> = {
    gray: 'bg-gray-100 text-gray-600',
    blue: 'bg-blue-50 text-blue-700',
    green: 'bg-green-50 text-green-700',
    yellow: 'bg-yellow-50 text-yellow-700',
    red: 'bg-red-50 text-red-600',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full ${styles[color] ?? styles.gray}`}>
      {children}
    </span>
  )
}

const STATUT: Record<string, { label: string; color: string }> = {
  enriched: { label: 'Enrichi par IA', color: 'green' },
  extracted: { label: '⏳ En cours d\'analyse', color: 'yellow' },
  pending: { label: '⏳ En cours d\'analyse', color: 'yellow' },
  catalogued: { label: 'Média (catalogué)', color: 'blue' },
  error: { label: 'Erreur', color: 'red' },
}

export default function DocumentCard({ documentId, onClose, onUseInReport }: Props) {
  const [doc, setDoc] = useState<Document | null>(null)
  const [meta, setMeta] = useState<MetadonneeIA | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<Tab>('meta')
  const [texte, setTexte] = useState<string | null>(null)
  const [texteLoading, setTexteLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [editingResume, setEditingResume] = useState(false)
  const [resumeEdit, setResumeEdit] = useState('')
  const [savingResume, setSavingResume] = useState(false)
  const toast = useToast()
  const { relaunchExtraction, selectDocument } = useDocumentStore()

  useEffect(() => {
    setLoading(true)
    setActiveTab('meta')
    setTexte(null)
    Promise.all([
      documentsApi.get(documentId),
      documentsApi.getMetadata(documentId).catch(() => null),
    ]).then(([d, m]) => {
      setDoc(d)
      setMeta(m)
    }).finally(() => setLoading(false))
  }, [documentId])

  // Chargement paresseux du texte extrait (seulement à l'activation de l'onglet)
  useEffect(() => {
    if (activeTab !== 'texte' || texte !== null || texteLoading) return
    setTexteLoading(true)
    documentsApi.getText(documentId)
      .then(r => setTexte(r.texte || ''))
      .catch(() => setTexte(''))
      .finally(() => setTexteLoading(false))
  }, [activeTab, documentId, texte, texteLoading])

  const sauvegarderResume = async () => {
    if (!doc) return
    setSavingResume(true)
    try {
      const updated = await documentsApi.patchMetadata(doc.id, { resume: resumeEdit })
      setMeta(updated)
      setEditingResume(false)
      toast.success('Résumé mis à jour')
    } catch {
      toast.error('Erreur mise à jour résumé')
    } finally {
      setSavingResume(false)
    }
  }

  const handleUseInReport = () => {
    selectDocument(documentId)
    onUseInReport?.(documentId)
    onClose()
    toast.info(`"${doc?.nom}" ajouté à la sélection`)
  }

  const copierTexte = () => {
    if (!texte) return
    navigator.clipboard.writeText(texte).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  const statut = STATUT[doc?.statut ?? 'pending']

  return (
    <div className="flex flex-col h-full bg-white border-l border-gray-200">
      {/* En-tête */}
      <div className="flex items-start gap-3 p-4 border-b border-gray-200 shrink-0">
        <FileText size={18} className="text-gray-400 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          {loading ? <LoadingSpinner /> : (
            <>
              <h2 className="font-semibold text-gray-800 text-sm truncate" title={doc?.nom}>{doc?.nom}</h2>
              <div className="flex items-center gap-2 mt-1 flex-wrap">
                {statut && <Badge color={statut.color}>{statut.label}</Badge>}
                <span className="text-xs text-gray-400">{doc?.extension?.toUpperCase()}</span>
                <span className="text-xs text-gray-400">{formatBytes(doc?.taille_octets)}</span>
              </div>
            </>
          )}
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 shrink-0 p-0.5">
          <X size={15} />
        </button>
      </div>

      {/* Onglets */}
      <div className="flex border-b border-gray-200 shrink-0 px-1">
        <button
          onClick={() => setActiveTab('meta')}
          className={`flex items-center gap-1.5 text-xs px-3 py-2.5 border-b-2 transition-colors ${
            activeTab === 'meta'
              ? 'border-blue-500 text-blue-600 font-medium'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <FolderOpen size={12} />
          Métadonnées
        </button>
        <button
          onClick={() => setActiveTab('texte')}
          className={`flex items-center gap-1.5 text-xs px-3 py-2.5 border-b-2 transition-colors ${
            activeTab === 'texte'
              ? 'border-blue-500 text-blue-600 font-medium'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          <AlignLeft size={12} />
          Texte extrait
        </button>
      </div>

      {/* Corps */}
      <div className="flex-1 overflow-y-auto text-sm">

        {/* ── Onglet Texte extrait ────────────────────────── */}
        {activeTab === 'texte' && (
          <div className="h-full flex flex-col">
            {texteLoading && (
              <div className="flex justify-center py-12">
                <LoadingSpinner label="Chargement du texte…" />
              </div>
            )}
            {!texteLoading && texte !== null && (
              <>
                <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100 shrink-0">
                  <span className="text-xs text-gray-400">
                    {texte.length.toLocaleString('fr-FR')} caractères
                  </span>
                  {texte && (
                    <button
                      onClick={copierTexte}
                      className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 transition-colors"
                    >
                      {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
                      {copied ? 'Copié !' : 'Copier'}
                    </button>
                  )}
                </div>
                <div className="flex-1 overflow-y-auto p-4">
                  {texte ? (
                    <pre className="text-xs text-gray-700 whitespace-pre-wrap leading-relaxed font-mono">
                      {texte}
                    </pre>
                  ) : (
                    <p className="text-xs text-gray-400 italic text-center py-8">
                      Aucun texte extrait pour ce document.
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        )}

        {/* ── Onglet Métadonnées ──────────────────────────── */}
        {activeTab === 'meta' && (
          <div className="p-4 space-y-5">
            {loading && <LoadingSpinner label="Chargement…" className="justify-center py-8" />}

            {!loading && doc && (
              <>
                {/* Actions */}
                <div className="flex gap-2">
                  {onUseInReport && (
                    <button
                      onClick={handleUseInReport}
                      className="flex-1 flex items-center justify-center gap-1.5 text-xs py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors font-medium"
                    >
                      <ExternalLink size={12} />
                      Utiliser dans un rapport
                    </button>
                  )}
                  {doc.statut === 'error' && (
                    <button
                      onClick={() => { relaunchExtraction(doc.id); toast.info('Extraction relancée') }}
                      className="flex items-center gap-1.5 text-xs py-2 px-3 border border-orange-200 text-orange-600 hover:bg-orange-50 rounded-lg"
                    >
                      <RefreshCw size={12} />
                      Relancer
                    </button>
                  )}
                </div>

                {/* Erreur d'extraction */}
                {doc.erreur && (
                  <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-600">
                    {doc.erreur}
                  </div>
                )}

                {/* Infos techniques */}
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Informations</h3>
                  <div className="space-y-1.5 text-xs text-gray-600">
                    <div className="flex items-center gap-2">
                      <Clock size={11} className="text-gray-400 shrink-0" />
                      <span>Importé le {doc.date_import ? new Date(doc.date_import).toLocaleDateString('fr-FR') : '—'}</span>
                    </div>
                    <div className="flex items-start gap-2">
                      <HardDrive size={11} className="text-gray-400 shrink-0 mt-0.5" />
                      <span className="break-all text-gray-400 font-mono text-xs">{doc.chemin}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Hash size={11} className="text-gray-400 shrink-0" />
                      <span className="font-mono text-gray-400">{doc.hash_sha256.slice(0, 16)}…</span>
                    </div>
                  </div>
                </div>

                {/* Pas encore d'analyse IA : message clair plutôt qu'une fiche vide */}
                {!meta && (doc.statut === 'pending' || doc.statut === 'extracted') && (
                  <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 text-xs text-yellow-800 flex items-center gap-2">
                    <Clock size={14} className="shrink-0" />
                    <span><strong>⏳ Analyse IA en cours</strong> — résumé, catégorie et tags pas encore
                    disponibles. Relance possible via « Relancer l'IA ».</span>
                  </div>
                )}
                {!meta && doc.statut === 'catalogued' && (
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs text-blue-800">
                    <strong>Média catalogué</strong> — référencé par nom/taille (pas d'analyse de contenu).
                  </div>
                )}

                {meta && (
                  <>
                    {/* Catégorie */}
                    {meta.categorie && (
                      <div>
                        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Catégorie</h3>
                        <div className="flex items-center gap-2 text-sm">
                          <FolderOpen size={13} className="text-gray-400" />
                          <span className="text-gray-700">{meta.categorie}</span>
                          {meta.sous_categorie && (
                            <span className="text-gray-400 text-xs">/ {meta.sous_categorie}</span>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Tags */}
                    <div>
                      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Tags</h3>
                      <TagManager
                        documentId={doc.id}
                        tags={meta.tags ?? []}
                        onUpdate={tags => setMeta(m => m ? { ...m, tags } : m)}
                      />
                    </div>

                    {/* Résumé */}
                    <div>
                      <div className="flex items-center justify-between mb-2">
                        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Résumé</h3>
                        {!editingResume && (
                          <button
                            onClick={() => { setEditingResume(true); setResumeEdit(meta.resume ?? '') }}
                            className="text-xs text-gray-400 hover:text-blue-500"
                          >
                            Modifier
                          </button>
                        )}
                      </div>
                      {editingResume ? (
                        <div className="space-y-2">
                          <textarea
                            value={resumeEdit}
                            onChange={e => setResumeEdit(e.target.value)}
                            rows={4}
                            className="w-full text-xs border border-gray-200 rounded-lg px-2.5 py-2 focus:outline-none focus:ring-1 focus:ring-blue-400 resize-none"
                            autoFocus
                          />
                          <div className="flex gap-2">
                            <button
                              onClick={sauvegarderResume}
                              disabled={savingResume}
                              className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-40"
                            >
                              {savingResume ? 'Sauvegarde…' : 'Sauvegarder'}
                            </button>
                            <button
                              onClick={() => setEditingResume(false)}
                              className="text-xs px-3 py-1.5 text-gray-500 hover:bg-gray-100 rounded-md"
                            >
                              Annuler
                            </button>
                          </div>
                        </div>
                      ) : (
                        <p className="text-sm text-gray-700 leading-relaxed">
                          {meta.resume || <span className="text-gray-400 italic">Aucun résumé</span>}
                        </p>
                      )}
                    </div>

                    {/* Entités */}
                    {meta.entites && Object.values(meta.entites).some(v => v?.length > 0) && (
                      <div>
                        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Entités</h3>
                        <div className="space-y-1.5 text-xs">
                          {meta.entites.personnes?.length > 0 && (
                            <div className="flex items-start gap-2">
                              <span className="text-gray-400 w-20 shrink-0">Personnes</span>
                              <div className="flex flex-wrap gap-1">{meta.entites.personnes.map(p => <Badge key={p}>{p}</Badge>)}</div>
                            </div>
                          )}
                          {meta.entites.organisations?.length > 0 && (
                            <div className="flex items-start gap-2">
                              <span className="text-gray-400 w-20 shrink-0">Orgs</span>
                              <div className="flex flex-wrap gap-1">{meta.entites.organisations.map(o => <Badge key={o} color="blue">{o}</Badge>)}</div>
                            </div>
                          )}
                          {meta.entites.lieux?.length > 0 && (
                            <div className="flex items-start gap-2">
                              <span className="text-gray-400 w-20 shrink-0">Lieux</span>
                              <div className="flex flex-wrap gap-1">{meta.entites.lieux.map(l => <Badge key={l} color="green">{l}</Badge>)}</div>
                            </div>
                          )}
                          {meta.entites.dates?.length > 0 && (
                            <div className="flex items-start gap-2">
                              <span className="text-gray-400 w-20 shrink-0">Dates</span>
                              <div className="flex flex-wrap gap-1">{meta.entites.dates.map(d => <Badge key={d} color="yellow">{d}</Badge>)}</div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Mots-clés */}
                    {meta.mots_cles && meta.mots_cles.length > 0 && (
                      <div>
                        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Mots-clés</h3>
                        <div className="flex flex-wrap gap-1">
                          {meta.mots_cles.map(m => (
                            <span key={m} className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded-full">{m}</span>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Langue + Confidentialité */}
                    <div className="flex items-center gap-3 text-xs text-gray-400">
                      {meta.langue && <span className="flex items-center gap-1"><Globe size={11} />{meta.langue.toUpperCase()}</span>}
                      {meta.niveau_confidentialite && meta.niveau_confidentialite !== 'normal' && (
                        <span className="flex items-center gap-1"><Shield size={11} />{meta.niveau_confidentialite}</span>
                      )}
                      {meta.modele_utilise && <span>via {meta.modele_utilise}</span>}
                    </div>
                  </>
                )}

                {/* Versions */}
                <div>
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Versions</h3>
                  <VersionHistory documentId={doc.id} />
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
