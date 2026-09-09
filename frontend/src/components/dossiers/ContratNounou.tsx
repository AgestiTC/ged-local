/**
 * ContratNounou — le contrat de travail d'un intervenant
 * ======================================================
 * Phase 3 du module, et le geste que ni les fiches ni les entretiens ne rendaient :
 * **produire un document opposable**.
 *
 * ## Un formulaire qui calcule, pas qui fait saisir
 *
 * Le salaire d'une assistante maternelle est **mensualisé** — lissé sur douze mois, identique
 * en février comme en juillet. Demander directement le montant mensuel reviendrait à faire
 * faire le calcul par l'utilisateur, et c'est exactement là que les contrats se trompent.
 * Chaque montant s'affiche donc **avec sa formule en toutes lettres** : vérifiable sans avoir
 * à faire confiance.
 *
 * ## Le texte est un brouillon, pas un verdict
 *
 * Le contrat généré se relit et se corrige dans la zone de texte avant export. Régénérer
 * **refuse d'écraser** une version corrigée sans confirmation : le moment où l'on régénère
 * sans y penser est précisément celui qui suit un ajustement de chiffre.
 *
 * L'export réutilise `exportApi` (Markdown → PDF / DOCX), déjà en place : aucun gabarit à
 * maintenir, aucune dépendance nouvelle.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle, BookOpen, Calculator, CheckCircle2, ExternalLink, FileDown, FileText,
  Info, Plus, RefreshCw, Trash2, Wand2,
} from 'lucide-react'
import { clsx } from 'clsx'
import { contratsApi, exportApi, type Contrat } from '../../api'
import LoadingSpinner from '../common/LoadingSpinner'
import { useToast } from '../common/Toast'

const STATUTS: Record<string, string> = {
  brouillon: 'brouillon', a_signer: 'à signer', signe: 'signé', termine: 'terminé',
}

/** Champs du formulaire, groupés comme on les remplit — pas comme la base les range. */
const GROUPES: { titre: string; champs: [string, string, string, string?][] }[] = [
  {
    titre: 'L\'enfant et le démarrage',
    champs: [
      ['enfant_nom', 'Prénom et nom de l\'enfant', 'text'],
      ['enfant_naissance', 'Né(e) le', 'date'],
      ['date_debut', 'Début du contrat', 'date'],
      ['adaptation', 'Période d\'adaptation', 'text', 'ex. 5 demi-journées sur 2 semaines'],
      ['essai', 'Période d\'essai', 'text', 'ex. 2 mois'],
    ],
  },
  {
    titre: 'Jours et horaires',
    champs: [
      ['jours', 'Jours d\'accueil', 'text', 'ex. lundi au jeudi'],
      ['horaires', 'Horaires', 'text', 'ex. 8h30 – 17h30'],
      ['jours_semaine', 'Jours par semaine', 'number'],
      ['heures_jour', 'Heures par jour', 'number'],
    ],
  },
  {
    titre: 'Indemnités (par jour d\'accueil réel)',
    champs: [
      ['entretien_jour', 'Indemnité d\'entretien / jour (€)', 'text'],
      ['repas_jour', 'Repas / jour (€)', 'text'],
      ['repas_fourni_par', 'Repas fournis par', 'text', 'ex. l\'assistante maternelle'],
      ['km_semaine', 'Kilomètres / semaine', 'number'],
      ['tarif_km', 'Tarif au kilomètre (€)', 'text'],
    ],
  },
  {
    titre: 'Congés, absences, fériés',
    champs: [
      ['conges', 'Dates de congés', 'text', 'ex. 3 semaines en août, 1 à Noël'],
      ['absences', 'Absences de l\'enfant', 'text'],
      ['feries', 'Jours fériés travaillés', 'text'],
      ['jour_paie', 'Jour de paie', 'text', 'ex. le 2 du mois'],
    ],
  },
  {
    titre: 'Autorisations et santé',
    champs: [
      ['autorisation_sorties', 'Sorties', 'text'],
      ['autorisation_transport', 'Transport en véhicule', 'text'],
      ['autorisation_photos', 'Photographies', 'text'],
      ['autorisation_soins', 'Soins d\'urgence', 'text'],
      ['pai', 'PAI (allergie, traitement)', 'text'],
      ['urgence', 'Personnes à prévenir', 'text'],
    ],
  },
  {
    titre: 'Assurances et signature',
    champs: [
      ['assurance_rc', 'RC professionnelle', 'text', 'assureur et n° de police'],
      ['assurance_auto', 'Auto avec transport d\'enfants', 'text'],
      ['fait_a', 'Fait à', 'text'],
      ['fait_le', 'Le', 'date'],
    ],
  },
]

export default function ContratNounou({ intervenantId }: { intervenantId: string }) {
  const toast = useToast()
  const [contrats, setContrats] = useState<Contrat[] | null>(null)
  const [bareme, setBareme] = useState<{ renseigne: boolean; verifie_le: string | null }>()
  const [sources, setSources] = useState<{ libelle: string; url: string }[]>([])
  const [avertissement, setAvertissement] = useState('')
  const [ouvert, setOuvert] = useState<string | null>(null)
  const [detail, setDetail] = useState<Contrat | null>(null)
  const [occupe, setOccupe] = useState(false)

  const charger = useCallback(async () => {
    try {
      const d = await contratsApi.lister(intervenantId)
      setContrats(d.contrats)
      setBareme(d.bareme)
      setSources(d.sources ?? [])
      setAvertissement(d.avertissement ?? '')
      setOuvert(o => o ?? (d.contrats.length ? d.contrats[d.contrats.length - 1].id : null))
    } catch { toast.error('Contrats indisponibles') }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervenantId])

  useEffect(() => { charger() }, [charger])
  useEffect(() => {
    if (!ouvert) { setDetail(null); return }
    contratsApi.detail(ouvert).then(setDetail).catch(() => {})
  }, [ouvert])

  const majChamp = async (cle: string, valeur: string | boolean) => {
    if (!detail) return
    // Fusion côté serveur : on envoie le champ modifié, jamais le formulaire entier.
    setDetail(await contratsApi.modifier(detail.id, { champs: { [cle]: valeur } }))
  }

  const generer = async (ecraser = false) => {
    if (!detail) return
    setOccupe(true)
    try {
      setDetail(await contratsApi.generer(detail.id, ecraser))
      toast.success('Contrat généré')
    } catch (e) {
      const status = (e as { response?: { status?: number } }).response?.status
      if (status === 409) {
        if (confirm('Ce contrat a déjà un texte, peut-être corrigé à la main.\n\n'
          + 'Le régénérer depuis les champs effacera ces corrections. Continuer ?')) {
          await generer(true)
        }
      } else toast.error('Génération impossible')
    } finally { setOccupe(false) }
  }

  if (!contrats) return <LoadingSpinner label="Chargement…" className="justify-center py-8" />

  const bloquantes = (detail?.alertes ?? []).filter(a => a.bloquant)
  const avertissements = (detail?.alertes ?? []).filter(a => !a.bloquant)

  return (
    <div className="flex flex-col gap-3">

      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex flex-wrap items-center gap-1.5">
          {contrats.map(ct => (
            <button key={ct.id} type="button" onClick={() => setOuvert(ct.id)}
              className={clsx('text-xs px-2.5 py-1.5 rounded-md border',
                ouvert === ct.id ? 'bg-gray-800 text-white border-gray-800'
                                 : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50')}>
              {ct.titre} · {STATUTS[ct.statut] ?? ct.statut}
            </button>
          ))}
        </div>
        <button type="button"
          onClick={async () => {
            const ct = await contratsApi.creer(intervenantId)
            await charger(); setOuvert(ct.id)
          }}
          className="flex items-center gap-1 text-sm px-3 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700">
          <Plus size={15} /> Nouveau contrat
        </button>
      </div>

      {!detail ? (
        <p className="text-center text-sm text-gray-400 py-10">
          Aucun contrat. Il se pré-remplit depuis la fiche — agrément, adresse, tarif annoncé.
        </p>
      ) : <>

        {/* Le calcul, en tête : c'est ce qu'on vient chercher. */}
        <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2">
          <h3 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5">
            <Calculator size={15} className="text-blue-600" /> Rémunération
          </h3>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Taux horaire net (€)</span>
              <input type="text" inputMode="decimal" defaultValue={String(detail.champs.taux_horaire ?? '')}
                onBlur={e => majChamp('taux_horaire', e.target.value)}
                className="text-sm border border-gray-300 rounded-md px-2 py-1.5" />
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Heures par semaine</span>
              <input type="text" inputMode="decimal" defaultValue={String(detail.champs.heures_semaine ?? '')}
                onBlur={e => majChamp('heures_semaine', e.target.value)}
                className="text-sm border border-gray-300 rounded-md px-2 py-1.5" />
            </label>
            <label className="flex flex-col gap-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Majoration au-delà de 45 h (%)</span>
              <input type="text" inputMode="decimal" defaultValue={String(detail.champs.majoration_pct ?? '')}
                onBlur={e => majChamp('majoration_pct', e.target.value)} placeholder="10"
                className="text-sm border border-gray-300 rounded-md px-2 py-1.5" />
            </label>
          </div>

          {/* Le régime : deux salaires différents pour les mêmes entrées. On ne choisit pas
              à la place de l'utilisateur, et on dit ce que ça change. */}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {([[true, 'Année complète'], [false, 'Année incomplète']] as const).map(([v, label]) => (
              <button key={label} type="button" onClick={() => majChamp('annee_complete', v)}
                className={clsx('text-xs px-2.5 py-1.5 rounded-md border',
                  Boolean(detail.champs.annee_complete) === v
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50')}>
                {label}
              </button>
            ))}
            {!detail.champs.annee_complete && (
              <label className="flex items-center gap-1.5 text-xs text-gray-500">
                Semaines d'accueil
                <input type="text" inputMode="numeric" defaultValue={String(detail.champs.semaines ?? '')}
                  onBlur={e => majChamp('semaines', e.target.value)}
                  className="w-16 text-sm border border-gray-300 rounded-md px-2 py-1" />
              </label>
            )}
          </div>

          {detail.calcul ? (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-2.5">
              <p className="text-sm">
                Salaire mensualisé :{' '}
                <strong className="text-lg text-emerald-800">{detail.calcul.salaire_mensuel} €</strong>
                <span className="text-gray-500"> · {detail.calcul.heures_mensualisees} h par mois</span>
              </p>
              <p className="text-xs text-emerald-900/70 mt-1 font-mono">{detail.calcul.formule}</p>
              {detail.calcul.detail.map((d, i) => (
                <p key={i} className="text-[11px] text-gray-600 mt-1">{d}</p>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-400">
              Renseignez le taux horaire et la durée hebdomadaire pour obtenir le salaire mensualisé.
            </p>
          )}

          {detail.frais && Number(detail.frais.total_mensuel) > 0 && (
            <p className="text-xs text-gray-500">
              Indemnités estimées : <strong>{detail.frais.total_mensuel} €</strong> par mois —
              entretien {detail.frais.entretien_mensuel} €, repas {detail.frais.repas_mensuel} €,
              kilomètres {detail.frais.km_mensuel} €. Elles sont dues par jour d'accueil réel :
              ce sont des estimations, pas des montants fixes.
            </p>
          )}
        </section>

        {/* Alertes : bloquantes d'abord, et le barème absent est lui-même une alerte. */}
        {(bloquantes.length > 0 || avertissements.length > 0) && (
          <section className="flex flex-col gap-1.5">
            {bloquantes.map(a => (
              <p key={a.cle} className="flex items-start gap-1.5 text-xs text-rose-800 bg-rose-50 border border-rose-200 rounded-lg p-2">
                <AlertTriangle size={14} className="shrink-0 mt-0.5" /> {a.message}
              </p>
            ))}
            {avertissements.map(a => (
              <p key={a.cle} className="flex items-start gap-1.5 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg p-2">
                <Info size={14} className="shrink-0 mt-0.5" /> {a.message}
              </p>
            ))}
            {!bareme?.renseigne && (
              <p className="text-[11px] text-gray-400">
                Le barème (SMIC horaire, minimum garanti) se saisit dans
                <strong> Paramètres → Barème emploi à domicile</strong>. Rien n'est livré en dur :
                ces montants changent chaque année.
              </p>
            )}
          </section>
        )}

        {/* Le reste du formulaire */}
        {GROUPES.map(groupe => (
          <section key={groupe.titre} className="bg-white border border-gray-200 rounded-lg p-3">
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{groupe.titre}</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {groupe.champs.map(([cle, label, type, aide]) => (
                <label key={cle} className="flex flex-col gap-0.5">
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">{label}</span>
                  <input type={type} placeholder={aide}
                    defaultValue={String(detail.champs[cle] ?? '')}
                    onBlur={e => {
                      if (e.target.value !== String(detail.champs[cle] ?? '')) majChamp(cle, e.target.value)
                    }}
                    className="text-sm border border-gray-300 rounded-md px-2 py-1.5" />
                </label>
              ))}
            </div>
          </section>
        ))}

        {/* Génération, relecture, export */}
        <section className="bg-white border border-gray-200 rounded-lg p-3 flex flex-col gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="text-sm font-semibold text-gray-800 flex items-center gap-1.5 flex-1">
              <FileText size={15} className="text-violet-600" /> Le contrat
            </h4>
            <select value={detail.statut}
              onChange={async e => setDetail(await contratsApi.modifier(detail.id, { statut: e.target.value }))}
              className="text-xs border border-gray-200 rounded-md px-2 py-1 bg-white">
              {Object.entries(STATUTS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <button type="button" disabled={occupe}
              onClick={async () => {
                setOccupe(true)
                try {
                  const maj = await contratsApi.exemple(detail.id)
                  setDetail(maj)
                  toast.success(`${maj.champs_remplis} champs vides remplis — à relire et à remplacer`)
                } catch { toast.error('Exemple non appliqué') } finally { setOccupe(false) }
              }}
              title="Remplit uniquement les champs encore vides — votre saisie n'est jamais écrasée"
              className="flex items-center gap-1 text-sm px-3 py-1.5 rounded-md border border-gray-200 text-gray-700 hover:bg-gray-50 disabled:opacity-50">
              <Wand2 size={14} /> Remplir un exemple
            </button>
            <button type="button" onClick={() => generer()} disabled={occupe}
              className="flex items-center gap-1 text-sm px-3 py-1.5 rounded-md bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-50">
              <RefreshCw size={14} className={occupe ? 'animate-spin' : undefined} />
              {detail.texte ? 'Régénérer' : 'Générer'}
            </button>
          </div>

          {detail.texte ? <>
            <p className="text-[11px] text-gray-400">
              Relisez et corrigez ci-dessous : c'est <strong>ce texte</strong> qui sera exporté.
              {detail.genere_le && ' Régénérer depuis les champs effacera vos corrections.'}
            </p>
            <textarea value={detail.texte} rows={18}
              onChange={e => setDetail({ ...detail, texte: e.target.value })}
              onBlur={e => contratsApi.modifier(detail.id, { texte: e.target.value })}
              className="text-xs font-mono border border-gray-200 rounded-md px-2 py-2 resize-y leading-relaxed" />
            <div className="flex items-center gap-2 flex-wrap">
              <button type="button"
                onClick={() => exportApi.toPdf(detail.texte!, detail.titre).catch(() => toast.error('Export PDF échoué'))}
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-gray-200 text-gray-700 hover:bg-gray-50">
                <FileDown size={14} /> PDF
              </button>
              <button type="button"
                onClick={() => exportApi.toDocx(detail.texte!, detail.titre).catch(() => toast.error('Export DOCX échoué'))}
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-gray-200 text-gray-700 hover:bg-gray-50">
                <FileDown size={14} /> DOCX
              </button>
              {detail.bareme_verifie_le && (
                <span className="flex items-center gap-1 text-[11px] text-gray-400">
                  <CheckCircle2 size={12} /> barème vérifié le {detail.bareme_verifie_le}
                </span>
              )}
            </div>
          </> : (
            <p className="text-sm text-gray-400">
              Le contrat n'a pas encore été généré. Les champs vides apparaîtront comme
              <strong> [À COMPLÉTER]</strong> — un trou visible se remplit, un trou invisible se signe.
            </p>
          )}

          <button type="button"
            onClick={async () => {
              if (!confirm(`Supprimer « ${detail.titre} » ?`)) return
              await contratsApi.supprimer(detail.id); setOuvert(null); charger()
            }}
            className="self-start flex items-center gap-1 text-xs text-gray-400 hover:text-rose-600">
            <Trash2 size={13} /> Supprimer ce contrat
          </button>
        </section>

        {/* Ce que la trame est, et ce qu'elle n'est pas. Dire qu'un document « a l'air
            officiel » sans l'être serait plus dangereux que de l'annoncer franchement —
            d'où les sources qui font foi, juste à côté. */}
        <section className="bg-gray-50 border border-gray-200 rounded-lg p-3 flex flex-col gap-2">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
            <BookOpen size={13} /> Ce document et les sources qui font foi
          </h4>
          <p className="text-xs text-gray-500 leading-relaxed">{avertissement}</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {sources.map(src => (
              <a key={src.url} href={src.url} target="_blank" rel="noopener noreferrer"
                className="flex items-center justify-between gap-2 px-2.5 py-2 bg-white border border-gray-200 rounded-lg hover:border-blue-300 text-xs text-gray-700">
                <span className="truncate">{src.libelle}</span>
                <ExternalLink size={12} className="text-gray-300 shrink-0" />
              </a>
            ))}
          </div>
        </section>
      </>}
    </div>
  )
}
