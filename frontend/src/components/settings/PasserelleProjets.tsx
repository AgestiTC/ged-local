/**
 * PasserelleProjets — gestion des projets/jetons de la passerelle de publication
 * ==============================================================================
 * Versant ENTRANT de l'intégration wiki : chaque projet externe (ex. « sapyn ») reçoit un
 * jeton (affiché UNE seule fois) et une liste blanche de livres BookStack où il peut publier.
 * S'appuie sur `passerelleApi` (endpoints admin, confiance réseau — pas d'auth entrante).
 */
import { useEffect, useState } from 'react'
import { KeyRound, Copy, Check, Plus, RefreshCw, Power, Trash2, ShieldCheck, ChevronRight, ChevronDown } from 'lucide-react'
import { passerelleApi, type PasserelleProjet, type PasserelleJeton } from '../../api'
import { useToast } from '../common/Toast'
import LoadingSpinner from '../common/LoadingSpinner'

function extractApiError(e: unknown): string {
  if (e && typeof e === 'object') {
    const ax = e as { response?: { data?: { detail?: string } }; message?: string }
    if (ax.response?.data?.detail) return ax.response.data.detail
    if (ax.message) return ax.message
  }
  return 'Erreur inconnue'
}

/** Découpe une saisie « a, b ; c » en liste de livres nettoyée. */
function parseLivres(s: string): string[] {
  return s.split(/[,;\n]/).map(x => x.trim()).filter(Boolean)
}

/**
 * Construit le message prêt-à-coller destiné au « claude projet » (le Claude qui travaille sur le
 * dépôt à publier). Adresse déduite de l'hôte courant + port backend 8008 (éditable ensuite).
 */
function construireMessage(nom: string, jeton: string, livres: string[]): string {
  const hote = typeof window !== 'undefined' ? window.location.hostname : '<ip-du-serveur>'
  const adresse = `http://${hote}:8008`
  const livre = livres[0] || '<Livre>'
  const listeLivres = livres.length ? livres.join(', ') : '(aucun — à définir)'
  return `Contexte : publier la doc de ce projet (« ${nom} ») sur le wiki BookStack via la passerelle Matothèque.

Passerelle (endpoint)      : ${adresse}/api/passerelle/publish
Jeton d'authentification   : ${jeton}
  → en-tête HTTP           : Authorization: Bearer ${jeton}   (⚠ secret, ne pas versionner)
Livre(s) autorisé(s)       : ${listeLivres}   (tout autre livre = 403)

Corps du POST = manifeste JSON :
{
  "etagere": "Projets AgestiTC",
  "pages": [
    {
      "cle": "guide-utilisateur",
      "livre": "${livre}",
      "chapitre": "Utilisation",
      "titre": "Guide utilisateur",
      "markdown": "# Guide\\n\\n...",
      "genere_le": "2026-08-26"
    }
  ]
}

Étapes :
1. Lister les pages à publier (1 projet = 1 livre de la liste blanche).
2. POST le manifeste sur l'endpoint ci-dessus avec l'en-tête Authorization.
3. La passerelle rapproche (crée/met à jour), range le livre dans l'étagère
   « Projets AgestiTC » et préfixe chaque page d'un bandeau « générée automatiquement ».
   Réponse : { creees, mises_a_jour, erreurs, etagere }.
4. Faire d'abord une SIMULATION (montrer ce qui partirait), puis publier pour de vrai.

⚠ Si le manifeste vit dans .claude/ (gitignoré en bloc) : ajouter « .claude/* » puis
  « !.claude/wiki.toml » dans .gitignore, sinon il n'est jamais versionné.`
}

export default function PasserelleProjets() {
  const toast = useToast()
  const [projets, setProjets] = useState<PasserelleProjet[]>([])
  const [loading, setLoading] = useState(true)
  const [indispo, setIndispo] = useState(false)          // passerelle non déployée (404)
  const [nom, setNom] = useState('')
  const [livres, setLivres] = useState('')
  const [busy, setBusy] = useState(false)
  const [jeton, setJeton] = useState<PasserelleJeton | null>(null)   // jeton montré 1×
  const [copie, setCopie] = useState(false)
  const [exempleOuvert, setExempleOuvert] = useState(false)          // chevron « exemple de message »
  const [message, setMessage] = useState('')                         // message éditable pour le « claude projet »
  const [copieMsg, setCopieMsg] = useState(false)

  // À l'apparition d'un jeton, prépare le message prêt-à-coller (livres pris du projet si absents).
  const poserJeton = (j: PasserelleJeton) => {
    const livres = j.livres_autorises ?? projets.find(p => p.nom === j.nom)?.livres_autorises ?? []
    setJeton(j); setCopie(false)
    setMessage(construireMessage(j.nom, j.jeton, livres))
    setExempleOuvert(false); setCopieMsg(false)
  }

  const charger = () => {
    setLoading(true)
    passerelleApi.projets()
      .then(p => { setProjets(p); setIndispo(false) })
      .catch(e => {
        // 404 = router non monté (image backend trop ancienne) → message dédié.
        const ax = e as { response?: { status?: number } }
        if (ax.response?.status === 404) setIndispo(true)
        else toast.error(extractApiError(e))
      })
      .finally(() => setLoading(false))
  }
  useEffect(charger, [])   // eslint-disable-line react-hooks/exhaustive-deps

  const creer = async () => {
    if (!nom.trim()) { toast.error('Indiquez un nom de projet.'); return }
    setBusy(true)
    try {
      const res = await passerelleApi.creer(nom.trim(), parseLivres(livres))
      poserJeton(res)
      setNom(''); setLivres('')
      toast.success(`Projet « ${res.nom} » créé`)
      charger()
    } catch (e) { toast.error(extractApiError(e)) } finally { setBusy(false) }
  }

  const regenerer = async (p: PasserelleProjet) => {
    if (!confirm(`Régénérer le jeton de « ${p.nom} » ? L'ancien cessera immédiatement de fonctionner.`)) return
    setBusy(true)
    try {
      const res = await passerelleApi.regenerer(p.nom)
      poserJeton(res)
      toast.success(`Jeton de « ${p.nom} » régénéré`)
    } catch (e) { toast.error(extractApiError(e)) } finally { setBusy(false) }
  }

  const basculerActif = async (p: PasserelleProjet) => {
    try {
      const maj = await passerelleApi.modifier(p.nom, { actif: !p.actif })
      setProjets(ps => ps.map(x => x.nom === p.nom ? maj : x))
    } catch (e) { toast.error(extractApiError(e)) }
  }

  const editerLivres = async (p: PasserelleProjet) => {
    const saisie = prompt(`Livres autorisés pour « ${p.nom} » (séparés par des virgules) :`,
      p.livres_autorises.join(', '))
    if (saisie === null) return
    try {
      const maj = await passerelleApi.modifier(p.nom, { livres_autorises: parseLivres(saisie) })
      setProjets(ps => ps.map(x => x.nom === p.nom ? maj : x))
      toast.success('Liste blanche mise à jour')
    } catch (e) { toast.error(extractApiError(e)) }
  }

  const copier = async () => {
    if (!jeton) return
    try { await navigator.clipboard.writeText(jeton.jeton); setCopie(true); setTimeout(() => setCopie(false), 2500) }
    catch { toast.error('Copie impossible — sélectionnez le jeton à la main.') }
  }

  const copierMessage = async () => {
    try { await navigator.clipboard.writeText(message); setCopieMsg(true); setTimeout(() => setCopieMsg(false), 2500) }
    catch { toast.error('Copie impossible — sélectionnez le message à la main.') }
  }

  const inputCls = 'text-sm border border-gray-200 rounded-md px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-purple-400'

  return (
    <section className="mt-4">
      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2 flex items-center gap-1.5">
        <KeyRound size={13} className="text-purple-600" /> Passerelle de publication (projets &amp; jetons)
      </h3>
      <p className="text-xs text-gray-400 mb-3">
        Chaque projet externe (ex. « sapyn ») publie sa doc sur le wiki via un <strong>jeton</strong>
        (porté en <code>Authorization: Bearer …</code>) et une <strong>liste blanche</strong> de livres.
        Le jeton n'est <strong>affiché qu'une seule fois</strong> à la création/rotation.
      </p>

      {indispo ? (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-700">
          Passerelle non disponible (endpoint absent) — l'image backend déployée ne contient pas encore
          le routeur passerelle. Déployez une version ≥ 1.56 puis rechargez.
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-4">
          {/* Jeton fraîchement généré — à copier maintenant */}
          {jeton && (
            <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 space-y-2">
              <div className="text-xs font-medium text-purple-800 flex items-center gap-1.5">
                <ShieldCheck size={13} /> Jeton de « {jeton.nom} » — {jeton.avertissement}
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 text-xs bg-white border border-purple-200 rounded px-2 py-1.5 break-all font-mono">
                  {jeton.jeton}
                </code>
                <button type="button" onClick={copier}
                  className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-purple-600 text-white hover:bg-purple-700 shrink-0">
                  {copie ? <Check size={13} /> : <Copy size={13} />} {copie ? 'Copié' : 'Copier'}
                </button>
              </div>
              {/* Exemple repliable : message prêt-à-coller pour le « claude projet » (éditable). */}
              <div className="pt-1 border-t border-purple-100">
                <button type="button" onClick={() => setExempleOuvert(o => !o)}
                  className="flex items-center gap-1 text-[11px] text-purple-700 hover:text-purple-900 font-medium">
                  {exempleOuvert ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  Voir le message à donner au « claude projet »
                </button>
                {exempleOuvert && (
                  <div className="mt-2 space-y-1.5">
                    <textarea
                      value={message} onChange={e => setMessage(e.target.value)}
                      spellCheck={false} rows={14}
                      className="w-full text-[11px] font-mono bg-white border border-purple-200 rounded-md p-2 resize-y focus:outline-none focus:ring-1 focus:ring-purple-400"
                    />
                    <div className="flex items-center gap-2">
                      <button type="button" onClick={copierMessage}
                        className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-purple-600 text-white hover:bg-purple-700">
                        {copieMsg ? <Check size={13} /> : <Copy size={13} />} {copieMsg ? 'Copié' : 'Copier le message'}
                      </button>
                      <span className="text-[11px] text-purple-400">Éditable — ajuste l'adresse/le port si besoin avant de copier.</span>
                    </div>
                  </div>
                )}
              </div>

              <button type="button" onClick={() => setJeton(null)} className="text-[11px] text-purple-500 hover:underline">
                J'ai copié le jeton — masquer
              </button>
            </div>
          )}

          {/* Création d'un projet */}
          <div className="flex items-end gap-2 flex-wrap">
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-gray-500">Nom du projet</span>
              <input value={nom} onChange={e => setNom(e.target.value)} placeholder="sapyn" className={inputCls + ' w-40'} />
            </label>
            <label className="flex flex-col gap-1 flex-1 min-w-[200px]">
              <span className="text-[11px] text-gray-500">Livres autorisés (séparés par des virgules)</span>
              <input value={livres} onChange={e => setLivres(e.target.value)} placeholder="Sapyn" className={inputCls + ' w-full'} />
            </label>
            <button type="button" onClick={creer} disabled={busy}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50">
              {busy ? <LoadingSpinner size={14} /> : <Plus size={15} />} Créer
            </button>
          </div>

          {/* Liste des projets */}
          {loading ? (
            <div className="py-3"><LoadingSpinner size={16} label="Chargement…" /></div>
          ) : projets.length === 0 ? (
            <p className="text-xs text-gray-400">Aucun projet. Créez-en un ci-dessus (ex. « sapyn » → livre « Sapyn »).</p>
          ) : (
            <ul className="divide-y divide-gray-100 border border-gray-100 rounded-lg">
              {projets.map(p => (
                <li key={p.nom} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <span className={`w-2 h-2 rounded-full shrink-0 ${p.actif ? 'bg-green-500' : 'bg-gray-300'}`}
                    title={p.actif ? 'Actif' : 'Révoqué'} />
                  <span className="font-medium text-gray-800 w-32 truncate">{p.nom}</span>
                  <button type="button" onClick={() => editerLivres(p)}
                    className="flex-1 text-left text-xs text-gray-500 hover:text-gray-800 truncate"
                    title="Modifier la liste blanche des livres">
                    {p.livres_autorises.length ? `📘 ${p.livres_autorises.join(', ')}` : '📘 (aucun livre autorisé)'}
                  </button>
                  {p.last_used_at && (
                    <span className="text-[11px] text-gray-400 shrink-0 hidden sm:block">
                      utilisé {new Date(p.last_used_at).toLocaleDateString('fr-FR')}
                    </span>
                  )}
                  <button type="button" onClick={() => regenerer(p)} title="Régénérer le jeton"
                    className="p-1.5 text-gray-400 hover:text-purple-600 rounded-md hover:bg-gray-50 shrink-0">
                    <RefreshCw size={14} />
                  </button>
                  <button type="button" onClick={() => basculerActif(p)}
                    title={p.actif ? 'Révoquer (désactiver le jeton)' : 'Réactiver'}
                    className={`p-1.5 rounded-md hover:bg-gray-50 shrink-0 ${p.actif ? 'text-gray-400 hover:text-red-600' : 'text-gray-300 hover:text-green-600'}`}>
                    {p.actif ? <Power size={14} /> : <Trash2 size={14} className="rotate-180" />}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  )
}
