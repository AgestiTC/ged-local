/**
 * Paramètres › Sources & indexation › Règles de classement
 * (plan docs/plan-reception-doc-applications.md, étape 1).
 *
 * Une règle impose catégorie / tags à tout document dont le chemin commence par un préfixe — ex. la
 * zone de dépôt de la doc des applications. Le compte qui LIT ce dossier n'est pas ici : c'est celui
 * de la Source SMB (identifiant + mot de passe chiffré), modifiable dans « Sources de fichiers ».
 */
import { useEffect, useState } from 'react'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { extractApiError } from '../../api'
import { confirmerTexte } from '../common/Confirmation'
import {
  reglesClassementApi, type Classement, type RegleClassement, type RegleClassementIn,
} from '../../api/docApplications'
import { lireTags, versPrefixe } from '../../utils/docApplications'

const VIDE: RegleClassementIn = {
  libelle: '', prefixe_chemin: '', categorie: 'Documentation', sous_categorie: 'Applications',
  tags: ['doc-appli'], tag_depuis_sous_dossier: true, classement: 'fixe', actif: true,
}

export default function ReglesClassementManager() {
  const [regles, setRegles] = useState<RegleClassement[]>([])
  const [edition, setEdition] = useState<{ id: string | null; r: RegleClassementIn; tags: string } | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)

  const charger = () => reglesClassementApi.lister().then(setRegles).catch(e => setErreur(extractApiError(e)))
  useEffect(() => { charger() }, [])

  const enregistrer = async () => {
    if (!edition) return
    const r = { ...edition.r, prefixe_chemin: versPrefixe(edition.r.prefixe_chemin), tags: lireTags(edition.tags) }
    try {
      if (edition.id) await reglesClassementApi.modifier(edition.id, r)
      else await reglesClassementApi.creer(r)
      setEdition(null)
      setErreur(null)
      charger()
    } catch (e) {
      setErreur(extractApiError(e))
    }
  }

  const supprimer = async (r: RegleClassement) => {
    if (!(await confirmerTexte(
      `Supprimer la règle « ${r.libelle} » ? Les documents déjà classés gardent leur classement.`, 'Supprimer'))) return
    try { await reglesClassementApi.supprimer(r.id); charger() } catch (e) { setErreur(extractApiError(e)) }
  }

  const champ = (k: keyof RegleClassementIn, v: string | boolean) =>
    setEdition(ed => ed && { ...ed, r: { ...ed.r, [k]: v } })

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Classement imposé selon l'<strong>emplacement</strong> du fichier. Exemple : la zone de dépôt de la doc des
        applications <code>\\NAS-MATO\Partage-Nas-Mato\[GED]\Docs-applications</code>, un sous-dossier par application.
        En « fixe », l'IA ne change ni la catégorie ni les tags, même à chaque nouvelle version.
      </p>
      {erreur && <p className="text-xs text-red-600">{erreur}</p>}

      {regles.map(r => (
        <div key={r.id} className="flex items-start gap-2 text-sm border rounded px-3 py-2">
          <div className="flex-1 min-w-0">
            <div className="font-medium">{r.libelle} {!r.actif && <span className="text-xs text-gray-400">(inactive)</span>}</div>
            <div className="text-xs text-gray-500 font-mono truncate" title={r.prefixe_chemin}>{r.prefixe_chemin}</div>
            <div className="text-xs text-gray-600">
              {r.categorie ?? '—'}{r.sous_categorie ? ` › ${r.sous_categorie}` : ''} · tags : {r.tags.join(', ') || '—'}
              {r.tag_depuis_sous_dossier ? ' + nom du sous-dossier' : ''} · {r.classement === 'fixe' ? 'fixe' : 'proposé, puis IA'}
            </div>
          </div>
          <button type="button" title="Modifier" onClick={() => setEdition({ id: r.id, r: { ...r }, tags: r.tags.join(', ') })}
            className="text-gray-500 hover:text-gray-800"><Pencil size={14} /></button>
          <button type="button" title="Supprimer" onClick={() => supprimer(r)}
            className="text-gray-500 hover:text-red-600"><Trash2 size={14} /></button>
        </div>
      ))}

      {!edition && (
        <button type="button" onClick={() => setEdition({ id: null, r: { ...VIDE }, tags: VIDE.tags.join(', ') })}
          className="text-sm text-blue-600 hover:underline flex items-center gap-1"><Plus size={14} /> Ajouter une règle</button>
      )}

      {edition && (
        <div className="border rounded p-3 space-y-2 bg-gray-50 text-sm">
          <label className="block">Nom
            <input className="mt-0.5 w-full border rounded px-2 py-1" value={edition.r.libelle}
              onChange={e => champ('libelle', e.target.value)} placeholder="Docs des applications" />
          </label>
          <label className="block">Dossier (chemin du NAS ou smb://…)
            <input className="mt-0.5 w-full border rounded px-2 py-1 font-mono text-xs" value={edition.r.prefixe_chemin}
              onChange={e => champ('prefixe_chemin', e.target.value)}
              placeholder="\\192.168.42.200\Partage-Nas-Mato\[GED]\Docs-applications" />
            {edition.r.prefixe_chemin && (
              <span className="text-xs text-gray-500">Enregistré sous : <code>{versPrefixe(edition.r.prefixe_chemin)}</code></span>
            )}
          </label>
          <div className="flex gap-2">
            <label className="flex-1">Catégorie
              <input className="mt-0.5 w-full border rounded px-2 py-1" value={edition.r.categorie ?? ''}
                onChange={e => champ('categorie', e.target.value)} />
            </label>
            <label className="flex-1">Sous-catégorie
              <input className="mt-0.5 w-full border rounded px-2 py-1" value={edition.r.sous_categorie ?? ''}
                onChange={e => champ('sous_categorie', e.target.value)} />
            </label>
          </div>
          <label className="block">Tags (séparés par des virgules)
            <input className="mt-0.5 w-full border rounded px-2 py-1" value={edition.tags}
              onChange={e => setEdition(ed => ed && { ...ed, tags: e.target.value })} />
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={edition.r.tag_depuis_sous_dossier}
              onChange={e => champ('tag_depuis_sous_dossier', e.target.checked)} />
            Ajouter le nom du sous-dossier en tag (un sous-dossier par application)
          </label>
          <label className="block">Classement
            <select className="mt-0.5 ml-2 border rounded px-2 py-1" value={edition.r.classement}
              onChange={e => champ('classement', e.target.value as Classement)}>
              <option value="fixe">Fixe — l'IA ne change ni catégorie ni tags</option>
              <option value="ia">Proposé — posé à l'import, puis l'IA reclasse</option>
            </select>
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={edition.r.actif} onChange={e => champ('actif', e.target.checked)} /> Active
          </label>
          <div className="flex gap-2 pt-1">
            <button type="button" onClick={enregistrer}
              disabled={!edition.r.libelle.trim() || !versPrefixe(edition.r.prefixe_chemin)}
              className="px-3 py-1 rounded bg-blue-600 text-white disabled:opacity-50">Enregistrer</button>
            <button type="button" onClick={() => setEdition(null)} className="px-3 py-1 rounded border">Annuler</button>
          </div>
        </div>
      )}
    </div>
  )
}
