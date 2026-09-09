/**
 * AideDeclaration — Administration › « Aide à la déclaration d'impôts »
 * =====================================================================
 * Répond à une seule question, et l'écran est construit autour d'elle :
 * **« j'ai payé ça — dans quelle case je le mets ? »**
 *
 * D'où trois partis pris qui ne sont pas cosmétiques :
 *
 * 1. **Le regroupement est celui du FORMULAIRE, pas celui des modules.** On remplit une
 *    déclaration en la descendant. Le module d'origine reste affiché sur la ligne, comme
 *    une provenance. Et le formulaire est nommé : chercher 7GA sur la 2042 alors qu'elle
 *    est sur l'annexe 2042-RICI est la moitié du problème.
 * 2. **Ce qui demande une décision passe devant.** Une ligne dont la case dépend de la
 *    situation (rang de l'enfant, type d'organisme) remonte en tête avec sa question.
 * 3. **Ce qui manque s'affiche.** Un contributeur sans donnée est listé en pied (« rien
 *    pour 2026 »), un contributeur en échec aussi : le silence se lirait « à jour ».
 *
 * ⚠️ Aucun montant n'est calculé ni lu par l'IA ici — le backend n'en produit pas (voir
 * `services/fiscalite`). L'écran dit **où**, l'utilisateur saisit **combien**.
 *
 * Copie : `utils/clipboard` obligatoire — l'application est servie en HTTP, où
 * `navigator.clipboard` est absent.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle, CalendarDays, CalendarSearch, CheckCircle2, ClipboardCopy, ExternalLink,
  FileText, HelpCircle, Info, Landmark, RefreshCw, X,
} from 'lucide-react'
import { clsx } from 'clsx'
import { fiscaliteApi, type EtatDatation, type LigneFiscale, type SyntheseFiscale } from '../../api'
import CollapsibleSection from '../common/CollapsibleSection'
import EcranEnEchec, { causeLisible } from '../common/EcranEnEchec'
import LoadingSpinner from '../common/LoadingSpinner'
import { useToast } from '../common/Toast'
import { copierTexte } from '../../utils/clipboard'

/** Aspect d'une pastille de confiance. Le vocabulaire est fermé côté backend. */
const CONFIANCE: Record<string, { label: string; classe: string; titre: string }> = {
  calcule: {
    label: 'calculé', classe: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    titre: 'Reconstitué à partir de vos données, sources à l\'appui.',
  },
  partiel: {
    label: 'partiel', classe: 'bg-amber-50 text-amber-700 border-amber-200',
    titre: 'Une partie seulement des pièces est connue : ce total est un plancher.',
  },
  a_verifier: {
    label: 'à vérifier', classe: 'bg-amber-50 text-amber-700 border-amber-200',
    titre: 'Proposition à confronter au document d\'origine avant report.',
  },
  a_saisir: {
    label: 'à saisir', classe: 'bg-gray-100 text-gray-600 border-gray-200',
    titre: 'Matothèque sait OÙ reporter, pas COMBIEN : aucun montant n\'est lu dans un document.',
  },
}

/** « 2026-09-09 » → « 9 sept. 2026 ». */
const jolieDate = (iso: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('fr-FR',
    { day: 'numeric', month: 'short', year: 'numeric' }) : null

/** Un barème de plus d'un an doit se voir : les montants et les cases changent chaque année. */
function estPerime(iso: string | null): boolean {
  if (!iso) return false
  const limite = new Date(`${iso}T00:00:00`)
  limite.setFullYear(limite.getFullYear() + 1)
  return limite < new Date()
}

/**
 * Panneau « Dater cette pièce ».
 *
 * Le rattachement d'une pièce à une année reposait sur la date du FICHIER, qui ne dit pas
 * quand la dépense a eu lieu. Ce panneau propose les années trouvées **dans le texte déjà
 * extrait** par Tika, chacune avec l'extrait qui la justifie — voir *pourquoi* on propose
 * 2025 est ce qui distingue une aide d'une devinette.
 *
 * ⚠️ **Rien ne sort sur le réseau ici**, et ce n'est pas un oubli : la date d'une
 * attestation est écrite dans l'attestation. Poser une confirmation de sortie Internet
 * devant une lecture locale apprendrait qu'elle ne veut rien dire.
 */
function PanneauDatation({ documentId, onFerme, onDate }: {
  documentId: string
  onFerme: () => void
  onDate: () => void
}) {
  const toast = useToast()
  const [etat, setEtat] = useState<EtatDatation | null>(null)
  const [saisie, setSaisie] = useState('')
  const [occupe, setOccupe] = useState(false)

  useEffect(() => {
    setEtat(null)
    fiscaliteApi.datation(documentId)
      .then(setEtat)
      .catch(() => toast.error('Datation indisponible'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [documentId])

  const fixer = async (annee: number | null) => {
    setOccupe(true)
    try {
      await fiscaliteApi.dater(documentId, annee)
      toast.success(annee ? `Pièce rattachée à ${annee}` : 'Année relâchée')
      onDate()
      onFerme()
    } catch {
      toast.error('Enregistrement impossible')
    } finally {
      setOccupe(false)
    }
  }

  return (
    <div className="mt-1 border border-blue-200 bg-blue-50/60 rounded-lg p-2.5 flex flex-col gap-2 text-xs">
      {!etat ? <LoadingSpinner label="Lecture du texte extrait…" className="py-2" /> : <>
        <div className="flex items-start gap-2">
          <CalendarSearch size={14} className="text-blue-600 mt-0.5 shrink-0" />
          <div className="flex-1">
            <p className="font-medium text-blue-900 break-all">{etat.nom}</p>
            <p className="text-blue-700/80">
              {etat.confirmee
                ? <>Rattachée à <strong>{etat.annee}</strong>, confirmée à la main.</>
                : <>Rattachée à <strong>{etat.annee_deduite}</strong> d'après la {etat.origine_deduite} — ce n'est pas la date de la dépense.</>}
            </p>
          </div>
          <button type="button" onClick={onFerme} className="text-blue-400 hover:text-blue-700 p-0.5">
            <X size={14} />
          </button>
        </div>

        {etat.candidats && etat.candidats.length > 0 ? (
          <div className="flex flex-col gap-1">
            <p className="text-blue-900/70">Années trouvées dans le document :</p>
            {etat.candidats.map(c => (
              <button key={c.annee} type="button" disabled={occupe} onClick={() => fixer(c.annee)}
                className="text-left bg-white border border-blue-200 rounded-md px-2 py-1.5 hover:border-blue-400 hover:bg-blue-50 disabled:opacity-50">
                <span className="font-semibold text-blue-800">{c.annee}</span>
                <span className="text-gray-400"> · {c.motif}</span>
                {c.extrait && <span className="block text-gray-500 italic truncate">« {c.extrait} »</span>}
              </button>
            ))}
          </div>
        ) : (
          <p className="text-blue-700/70">
            {etat.texte_disponible === false
              ? 'Aucun texte extrait pour cette pièce (image non océrisée) — saisis l\'année à la main.'
              : 'Aucune année repérée dans le texte — saisis-la à la main.'}
          </p>
        )}

        <div className="flex items-center gap-2 flex-wrap pt-1 border-t border-blue-100">
          <input type="text" inputMode="numeric" placeholder="Année" value={saisie}
            onChange={e => setSaisie(e.target.value.replace(/\D/g, '').slice(0, 4))}
            className="w-20 border border-blue-300 rounded-md px-2 py-1 bg-white" />
          <button type="button" disabled={occupe || saisie.length !== 4}
            onClick={() => fixer(Number(saisie))}
            className="px-2.5 py-1 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40">
            Confirmer
          </button>
          {etat.confirmee && (
            // Pouvoir DÉFAIRE compte autant que pouvoir trancher : une confirmation erronée
            // qu'on ne peut pas retirer serait pire que l'approximation de départ.
            <button type="button" disabled={occupe} onClick={() => fixer(null)}
              className="px-2 py-1 text-blue-700 hover:underline disabled:opacity-40">
              Retirer la confirmation
            </button>
          )}
        </div>
      </>}
    </div>
  )
}

interface LigneProps {
  ligne: LigneFiscale
  reponses: Record<string, string>
  onRepondre: (cle: string, valeur: string) => void
  onRafraichir: () => void
  enCours: boolean
}

function Ligne({ ligne, reponses, onRepondre, onRafraichir, enCours }: LigneProps) {
  const toast = useToast()
  const [datation, setDatation] = useState<string | null>(null)
  const conf = CONFIANCE[ligne.confiance] ?? CONFIANCE.a_saisir
  const aCopier = ligne.montant ?? ligne.case ?? ''

  const copier = async () => {
    if (!aCopier) return
    const ok = await copierTexte(aCopier)
    toast[ok ? 'success' : 'error'](ok ? `Copié : ${aCopier}` : 'Copie impossible')
  }

  return (
    <div className={clsx('border rounded-lg p-3 flex flex-col gap-2',
      ligne.question ? 'border-blue-200 bg-blue-50/40' : 'border-gray-200 bg-white')}>

      {/* Ligne 1 : la case (ce qu'on cherche), le libellé, le montant */}
      <div className="flex items-start gap-2 flex-wrap">
        {ligne.case ? (
          <span className="font-mono text-sm font-bold px-2 py-0.5 rounded bg-blue-600 text-white shrink-0">
            {ligne.case}
          </span>
        ) : (
          <span className="text-xs font-semibold px-2 py-1 rounded bg-blue-100 text-blue-700 border border-blue-200 shrink-0 flex items-center gap-1">
            <HelpCircle size={12} /> case à déterminer
          </span>
        )}

        <span className="text-sm text-gray-800 flex-1 min-w-[12rem]">{ligne.libelle}</span>

        <span className="text-sm font-semibold text-gray-900 whitespace-nowrap">
          {ligne.montant ? `${ligne.montant} €` : <span className="text-gray-400 font-normal">—</span>}
        </span>

        <span title={conf.titre}
          className={clsx('text-[10px] font-semibold px-1.5 py-0.5 rounded-full border whitespace-nowrap cursor-help', conf.classe)}>
          {conf.label}
        </span>

        {aCopier && (
          <button type="button" onClick={copier}
            title={ligne.montant ? 'Copier le montant' : 'Copier le numéro de case'}
            className="p-1 text-gray-400 hover:text-blue-600 rounded hover:bg-gray-100 shrink-0">
            <ClipboardCopy size={14} />
          </button>
        )}
      </div>

      {ligne.note && <p className="text-xs text-gray-500 leading-relaxed">{ligne.note}</p>}

      {/* La question qui tranche la case — le vrai apport de l'écran. */}
      {ligne.question && (
        <div className="flex flex-col gap-1.5 pt-1 border-t border-blue-100">
          <label className="text-xs font-medium text-blue-900">{ligne.question.intitule}</label>
          {ligne.question.aide && <p className="text-[11px] text-blue-700/80">{ligne.question.aide}</p>}
          <div className="flex flex-wrap items-center gap-2">
            {ligne.question.options.length > 0 ? (
              <select
                value={reponses[ligne.question.cle] ?? ''}
                disabled={enCours}
                onChange={e => onRepondre(ligne.question!.cle, e.target.value)}
                className="text-sm border border-blue-300 rounded-md px-2 py-1.5 bg-white max-w-full">
                <option value="">Choisir…</option>
                {ligne.question.options.map(o => (
                  <option key={o.valeur} value={o.valeur}>{o.libelle}</option>
                ))}
              </select>
            ) : (
              <input
                type="text" inputMode="numeric" defaultValue={reponses[ligne.question.cle] ?? ''}
                disabled={enCours}
                onBlur={e => onRepondre(ligne.question!.cle, e.target.value)}
                className="text-sm border border-blue-300 rounded-md px-2 py-1.5" />
            )}
          </div>
        </div>
      )}

      {/* Provenance + pièces : aucun montant ne s'affiche sans pouvoir remonter à sa pièce. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-400">
        <span className="flex items-center gap-1"><Info size={11} /> {ligne.provenance}</span>
        {ligne.sources.map((s, i) => (
          <span key={`${s.ref ?? s.libelle}-${i}`} className="flex items-center gap-1 text-gray-500">
            <FileText size={11} className="text-gray-300" />
            {/* Le contributeur dit OÙ ouvrir l'objet ; à défaut, un document va dans la GED.
                Envoyer un contrat vers `/ged?doc=…` ouvrirait une fiche document inexistante. */}
            {s.lien_interne || (s.ref && s.type === 'document') ? (
              <a href={s.lien_interne ?? `/ged?doc=${s.ref}`}
                className="hover:text-blue-600 hover:underline truncate max-w-[16rem]">
                {s.libelle}
              </a>
            ) : <span className="truncate max-w-[16rem]">{s.libelle}</span>}
            {/* L'année de la pièce, et surtout SON STATUT : confirmée (un fait) ou déduite
                de la date du fichier (une approximation). Cliquer ouvre de quoi trancher.
                Réservé aux DOCUMENTS : « Dater » agit sur `documents.annee_fiscale`, et
                l'année d'un contrat vient de son journal — il n'y a rien à trancher. */}
            {s.ref && s.annee && s.type === 'document' && (
              <button type="button" onClick={() => setDatation(d => d === s.ref ? null : s.ref)}
                title={s.annee_confirmee
                  ? 'Année confirmée pour cette pièce — cliquer pour revoir'
                  : 'Année déduite de la date du fichier, pas de la dépense — cliquer pour la fixer'}
                className={clsx('px-1 rounded border text-[10px] font-medium transition-colors',
                  s.annee_confirmee
                    ? 'bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100'
                    : 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100')}>
                {s.annee}{s.annee_confirmee ? ' ✓' : ' ?'}
              </button>
            )}
          </span>
        ))}
        {ligne.notice_url && (
          <a href={ligne.notice_url} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1 hover:text-blue-600">
            notice <ExternalLink size={10} />
          </a>
        )}
      </div>

      {datation && (
        <PanneauDatation documentId={datation} onFerme={() => setDatation(null)}
          onDate={onRafraichir} />
      )}
    </div>
  )
}

export default function AideDeclaration() {
  const toast = useToast()
  const [data, setData] = useState<SyntheseFiscale | null>(null)
  const [annee, setAnnee] = useState<number | undefined>(undefined)
  const [chargement, setChargement] = useState(true)
  const [envoi, setEnvoi] = useState(false)
  // La CAUSE de l'échec, pas seulement le fait qu'il y en ait eu un.
  const [erreur, setErreur] = useState<string | null>(null)

  const charger = useCallback((an?: number) => {
    setChargement(true)
    setErreur(null)
    fiscaliteApi.synthese(an)
      .then(d => { setData(d); setAnnee(d.annee) })
      .catch(e => setErreur(causeLisible(e)))
      .finally(() => setChargement(false))
    // `toast` est recréé à chaque rendu du provider : le mettre en dépendance relancerait
    // le chargement en boucle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { charger() }, [charger])

  const repondre = async (cle: string, valeur: string) => {
    if (!annee) return
    setEnvoi(true)
    try {
      setData(await fiscaliteApi.repondre(annee, cle, valeur))
    } catch {
      toast.error('Réponse non enregistrée')
    } finally {
      setEnvoi(false)
    }
  }

  if (chargement && !data) return <LoadingSpinner label="Chargement…" className="justify-center py-10" />

  // Jamais une page blanche : voir `EcranEnEchec`.
  if (!data) {
    return <EcranEnEchec titre="Synthèse fiscale indisponible" cause={erreur}
      onReessayer={() => charger(annee)} />
  }

  const perime = estPerime(data.millesime.verifie_le)
  const vides = data.contributeurs.filter(c => c.etat !== 'ok')

  return (
    <div className="flex flex-col gap-3">

      {/* Année + fraîcheur du millésime */}
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-sm text-gray-600">
          <CalendarDays size={15} className="text-blue-600" />
          Revenus de l'année
          <select value={annee ?? ''} disabled={chargement}
            onChange={e => { const a = Number(e.target.value); setAnnee(a); charger(a) }}
            className="text-sm border border-gray-300 rounded-md px-2 py-1 bg-white">
            {data.annees_disponibles.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>

        <span title={`Cases et libellés du millésime ${data.millesime.annee}, relus à cette date.`}
          className={clsx('text-[11px] px-2 py-1 rounded-full border cursor-help',
            perime ? 'bg-amber-50 text-amber-800 border-amber-300'
                   : 'bg-gray-50 text-gray-500 border-gray-200')}>
          {perime && <AlertTriangle size={11} className="inline mr-1 -mt-0.5" />}
          Cases vérifiées le {jolieDate(data.millesime.verifie_le)}
        </span>

        <button type="button" onClick={() => charger(annee)} disabled={chargement}
          className="ml-auto flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50">
          <RefreshCw size={13} className={chargement ? 'animate-spin' : undefined} /> Actualiser
        </button>
      </div>

      {/* L'avertissement n'est jamais optionnel. */}
      <p className="text-xs text-gray-500 bg-gray-50 border border-gray-200 rounded-lg p-2.5 leading-relaxed">
        {data.millesime.avertissement}{' '}
        <a href={data.millesime.url_officielle} target="_blank" rel="noopener noreferrer"
          className="text-blue-600 hover:underline inline-flex items-center gap-0.5">
          impots.gouv.fr <ExternalLink size={11} />
        </a>
      </p>

      {/* Ce qui explique, avant ce qu'on reporte. Un « rien trouvé » sans chiffre laisse
          croire à une année vide alors que c'est peut-être le rattachement qui a échoué. */}
      {(data.alertes ?? []).map((a, i) => (
        <section key={i} className="border border-blue-200 bg-blue-50/60 rounded-lg p-3 flex items-start gap-2">
          <Info size={15} className="text-blue-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-blue-900">{a.libelle}</p>
            {a.note && <p className="text-xs text-blue-800/80 leading-relaxed mt-0.5">{a.note}</p>}
          </div>
        </section>
      ))}

      {data.formulaires.length === 0 ? (
        (data.alertes ?? []).length === 0 && (
          <div className="text-center text-sm text-gray-400 py-12">
            Rien à reporter pour {data.annee} d'après ce que Matothèque connaît.
          </div>
        )
      ) : data.formulaires.map(f => (
        <CollapsibleSection key={f.code} id={`fisc-${f.code}`} defaultOpen
          icon={<Landmark size={16} className="text-blue-600" />}
          title={<span className="flex items-baseline gap-2 flex-wrap">
            <span className="font-mono">{f.code}</span>
            <span className="text-xs font-normal text-gray-400">{f.libelle}</span>
          </span>}
          right={<span className="text-xs text-gray-400 mr-1">
            {f.lignes.length} ligne{f.lignes.length > 1 ? 's' : ''}
          </span>}>
          <div className="flex flex-col gap-2 pt-1">
            {f.lignes.map((l, i) => (
              <Ligne key={`${l.case ?? 'x'}-${i}`} ligne={l} reponses={data.reponses}
                onRepondre={repondre} onRafraichir={() => charger(annee)} enCours={envoi} />
            ))}
          </div>
        </CollapsibleSection>
      ))}

      {/* Ce qui n'a rien donné — affiché, car le silence se lirait « à jour ». */}
      {vides.length > 0 && (
        <div className="text-xs text-gray-400 border-t border-gray-100 pt-2 flex flex-col gap-1">
          {vides.map(c => (
            <span key={c.cle} className="flex items-center gap-1.5">
              {c.etat === 'erreur'
                ? <AlertTriangle size={12} className="text-amber-500 shrink-0" />
                : <CheckCircle2 size={12} className="text-gray-300 shrink-0" />}
              <strong className="font-medium text-gray-500">{c.libelle}</strong> — {c.message}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
