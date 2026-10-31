/**
 * GrilleCorrectionPanel — vérifier et corriger la grille d'analyse détectée, AVANT de lancer.
 * ==========================================================================================
 * Critères (retenu / nom / points), échelle et barème tels que Matothèque les a lus dans le
 * classeur, éditables (ROADMAP step 2, 31/10/2026). Rien n'est modifié dans le fichier : la
 * correction part avec la demande de comparaison, et seulement si quelque chose a changé —
 * `onChange(null)` tant que la grille est conservée telle quelle.
 */
import { useEffect, useMemo, useState } from 'react'
import { Loader2, Plus, RotateCcw, X } from 'lucide-react'
import { clsx } from 'clsx'
import { templatesApi, type GrilleCorrection, type TemplateApercu } from '../../api'

interface LigneCritere { ligne: number; nom: string; points: string; actif: boolean }
interface Niveau { note: string; libelle: string }

export interface EtatGrille { criteres: LigneCritere[]; bareme: Niveau[]; noteMax: string }

export function depuisApercu(a: TemplateApercu): EtatGrille {
  return {
    criteres: a.criteres
      .filter((c): c is typeof c & { ligne: number } => typeof c.ligne === 'number')
      .map(c => ({ ligne: c.ligne, nom: c.nom, points: c.points == null ? '' : String(c.points), actif: true })),
    bareme: (a.bareme ?? []).map(b => ({ note: String(b.note), libelle: b.libelle })),
    noteMax: String(a.note_max ?? 10),
  }
}

const nombre = (v: string): number | null => {
  const n = Number(v.replace(',', '.'))
  return v.trim() === '' || Number.isNaN(n) ? null : n
}

/** Correction à envoyer : uniquement ce qui diffère de la grille lue (null si rien). */
export function correctionDepuis(initial: EtatGrille, courant: EtatGrille): GrilleCorrection | null {
  const correction: GrilleCorrection = {}
  const criteres = courant.criteres.filter((c, i) => {
    const o = initial.criteres[i]
    return c.actif !== o.actif || c.nom.trim() !== o.nom || nombre(c.points) !== nombre(o.points)
  })
  if (criteres.length) {
    correction.criteres = criteres.map(c => ({
      ligne: c.ligne, nom: c.nom.trim() || undefined, points: nombre(c.points), actif: c.actif,
    }))
  }
  const noteMax = nombre(courant.noteMax)
  if (noteMax && noteMax > 0 && noteMax !== nombre(initial.noteMax)) correction.note_max = noteMax
  const bareme = (b: Niveau[]) => b
    .map(n => ({ note: nombre(n.note), libelle: n.libelle.trim() }))
    .filter((n): n is { note: number; libelle: string } => n.note !== null && n.libelle !== '')
  if (JSON.stringify(bareme(courant.bareme)) !== JSON.stringify(bareme(initial.bareme))) {
    correction.bareme = bareme(courant.bareme)
  }
  return Object.keys(correction).length ? correction : null
}

export default function GrilleCorrectionPanel({ templateId, onChange }: {
  templateId: string
  onChange: (correction: GrilleCorrection | null) => void
}) {
  const [initial, setInitial] = useState<EtatGrille | null>(null)
  const [etat, setEtat] = useState<EtatGrille | null>(null)
  const [statut, setStatut] = useState<'chargement' | 'grille' | 'autre' | 'erreur'>('chargement')

  useEffect(() => {
    let actif = true
    setStatut('chargement')
    onChange(null)
    templatesApi.apercu(templateId)
      .then(a => {
        if (!actif) return
        if (a.type !== 'grille') { setStatut('autre'); return }
        const e = depuisApercu(a)
        setInitial(e)
        setEtat(e)
        setStatut('grille')
      })
      .catch(() => { if (actif) setStatut('erreur') })
    return () => { actif = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recharger seulement au changement de modèle
  }, [templateId])

  const correction = useMemo(
    () => (initial && etat ? correctionDepuis(initial, etat) : null), [initial, etat])
  useEffect(() => { if (statut === 'grille') onChange(correction) },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onChange est un setter stable du parent
    [correction, statut])

  if (statut === 'chargement') {
    return <p className="flex items-center gap-1.5 text-xs text-gray-400"><Loader2 size={12} className="animate-spin" /> Lecture de la grille…</p>
  }
  if (statut !== 'grille' || !etat || !initial) return null

  const majCritere = (i: number, champ: Partial<LigneCritere>) =>
    setEtat({ ...etat, criteres: etat.criteres.map((c, j) => (j === i ? { ...c, ...champ } : c)) })
  const majNiveau = (i: number, champ: Partial<Niveau>) =>
    setEtat({ ...etat, bareme: etat.bareme.map((n, j) => (j === i ? { ...n, ...champ } : n)) })
  const retenus = etat.criteres.filter(c => c.actif).length

  return (
    <div className="rounded-lg border border-blue-100 bg-blue-50/40 p-2.5 space-y-2.5 text-xs">
      <div className="flex items-center gap-2">
        <p className="font-medium text-gray-700 flex-1">Grille détectée — à vérifier avant de lancer</p>
        <span className={clsx('px-1.5 py-0.5 rounded text-[10px] font-semibold',
          correction ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500')}>
          {correction ? 'corrigée' : 'lue automatiquement'}
        </span>
        {correction && (
          <button type="button" onClick={() => setEtat(initial)} title="Revenir à la grille telle que lue"
            className="flex items-center gap-1 text-gray-500 hover:text-gray-700">
            <RotateCcw size={12} /> Rétablir
          </button>
        )}
      </div>

      <div className="space-y-1">
        {etat.criteres.map((c, i) => (
          <div key={c.ligne} className={clsx('flex items-center gap-1.5', !c.actif && 'opacity-50')}>
            <input type="checkbox" checked={c.actif} onChange={e => majCritere(i, { actif: e.target.checked })}
              title={c.actif ? 'Critère noté par l\'IA' : 'Écarté : la ligne reste à remplir par la commission'} />
            <input value={c.nom} onChange={e => majCritere(i, { nom: e.target.value })} disabled={!c.actif}
              aria-label={`Nom du critère ligne ${c.ligne}`}
              className="flex-1 min-w-0 border border-gray-200 rounded px-2 py-1 bg-white outline-none focus:border-blue-300" />
            <input value={c.points} onChange={e => majCritere(i, { points: e.target.value })} disabled={!c.actif}
              inputMode="decimal" placeholder="pts" aria-label={`Points du critère ligne ${c.ligne}`}
              className="w-14 border border-gray-200 rounded px-1.5 py-1 bg-white text-right outline-none focus:border-blue-300" />
          </div>
        ))}
        {retenus === 0 && <p className="text-red-600">Gardez au moins un critère.</p>}
      </div>

      <div className="space-y-1">
        <div className="flex items-center gap-1.5 text-gray-600">
          <span className="font-medium flex-1">Barème</span>
          Notes sur
          <input value={etat.noteMax} onChange={e => setEtat({ ...etat, noteMax: e.target.value })}
            inputMode="decimal" aria-label="Échelle des notes"
            className="w-12 border border-gray-200 rounded px-1.5 py-0.5 bg-white text-right outline-none focus:border-blue-300" />
        </div>
        {etat.bareme.length === 0 && (
          <p className="text-gray-400">Aucun barème lu dans le classeur — ajoutez des niveaux, ou précisez-le dans les consignes.</p>
        )}
        {etat.bareme.map((n, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <input value={n.note} onChange={e => majNiveau(i, { note: e.target.value })} inputMode="decimal"
              aria-label="Note du niveau"
              className="w-12 border border-gray-200 rounded px-1.5 py-1 bg-white text-right outline-none focus:border-blue-300" />
            <span className="text-gray-400">=</span>
            <input value={n.libelle} onChange={e => majNiveau(i, { libelle: e.target.value })}
              placeholder="Ex : Absent, Insuffisant, Complet…" aria-label="Libellé du niveau"
              className="flex-1 min-w-0 border border-gray-200 rounded px-2 py-1 bg-white outline-none focus:border-blue-300" />
            <button type="button" onClick={() => setEtat({ ...etat, bareme: etat.bareme.filter((_, j) => j !== i) })}
              title="Retirer ce niveau" className="p-1 text-gray-300 hover:text-red-500"><X size={12} /></button>
          </div>
        ))}
        <button type="button" onClick={() => setEtat({ ...etat, bareme: [...etat.bareme, { note: '', libelle: '' }] })}
          className="flex items-center gap-1 text-gray-500 hover:text-gray-700">
          <Plus size={12} /> Ajouter un niveau
        </button>
      </div>
      <p className="text-gray-400">Le fichier n'est pas modifié : la correction s'applique à cette analyse.</p>
    </div>
  )
}
