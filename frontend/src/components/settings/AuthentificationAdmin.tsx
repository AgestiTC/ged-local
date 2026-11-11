/**
 * Paramètres › Authentification (SSO du NAS) — réglages OpenID Connect, première connexion, activation
 * =====================================================================================================
 * Trois temps, dans l'ordre imposé par le serveur :
 *   1. saisir le SSO (émetteur, identifiant client, secret, adresse de retour, groupes) ;
 *   2. se connecter UNE fois avec un compte du groupe admin (possible tant que l'authentification est
 *      éteinte : la fiche est créée à cette occasion) ;
 *   3. activer.
 * Le serveur reste la barrière : `PUT /api/system/config` refuse un émetteur non https, une activation
 * sans SSO complet ou sans admin déjà connecté, et tout réglage d'authentification à un non-admin une
 * fois active. Le secret n'est JAMAIS relu (masqué) : champ vide = conserver l'existant.
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { CheckCircle2, KeyRound, LogIn, Power, Save } from 'lucide-react'
import { apiClient } from '../../api/client'
import { systemApi, type ConfigUpdate, type SystemConfig } from '../../api'
import { useAuthStore } from '../../stores/authStore'
import { urlConnexion } from '../../utils/acces'
import { useToast } from '../common/Toast'
import LoadingSpinner from '../common/LoadingSpinner'

const CHAMPS = [
  { cle: 'oidc_issuer', label: 'Émetteur (issuer)', placeholder: 'https://sso.exemple.fr/webman/sso',
    aide: 'Adresse https du SSO du NAS, sans « /.well-known/… ».' },
  { cle: 'oidc_client_id', label: 'Identifiant client (Application ID)', placeholder: '',
    aide: 'DSM › SSO Server › Applications › Matothèque.' },
  { cle: 'oidc_redirect_uri', label: 'Adresse de retour', placeholder: 'https://ged.exemple.fr/api/auth/callback',
    aide: "À déclarer À L'IDENTIQUE dans l'application SSO du NAS." },
  { cle: 'oidc_groupe_admin', label: 'Groupe des administrateurs', placeholder: 'matotheque-admin', aide: '' },
  { cle: 'oidc_groupe_utilisateurs', label: 'Groupe des utilisateurs', placeholder: 'matotheque-utilisateurs', aide: '' },
  { cle: 'auth_session_inactivite_heures', label: 'Session : inactivité maximale (heures)', placeholder: '12', aide: '' },
  { cle: 'auth_session_max_jours', label: 'Session : durée maximale (jours)', placeholder: '7', aide: '' },
] as const

type Cle = typeof CHAMPS[number]['cle']
type Valeurs = Record<Cle, string>

function lire(config: SystemConfig): Valeurs {
  return Object.fromEntries(CHAMPS.map(f => [f.cle, config[f.cle]?.valeur ?? ''])) as Valeurs
}

function messageErreur(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d) && typeof d[0]?.msg === 'string') return d[0].msg
  return "L'action a échoué."
}

export default function AuthentificationAdmin() {
  const toast = useToast()
  const authActive = useAuthStore(s => s.authActive)
  const moi = useAuthStore(s => s.utilisateur)
  const adresseConnexion = useAuthStore(s => s.adresseConnexion)
  const rechargerAuth = useAuthStore(s => s.charger)

  const [initial, setInitial] = useState<Valeurs | null>(null)
  const [valeurs, setValeurs] = useState<Valeurs | null>(null)
  const [secret, setSecret] = useState('')
  const [secretDefini, setSecretDefini] = useState(false)
  const [erreur, setErreur] = useState<string | null>(null)
  const [enCours, setEnCours] = useState(false)
  const [confirmer, setConfirmer] = useState<'activer' | 'eteindre' | null>(null)

  const appliquer = useCallback((config: SystemConfig) => {
    const v = lire(config)
    setInitial(v)
    setValeurs(v)
    setSecretDefini(!!config.oidc_client_secret?.defini)
  }, [])

  const charger = useCallback(async () => {
    try {
      appliquer(await systemApi.getConfig())
      setErreur(null)
    } catch (e) {
      setErreur(messageErreur(e))
    }
  }, [appliquer])

  useEffect(() => { void charger() }, [charger])

  if (erreur && !valeurs) return <p role="alert" className="text-sm text-red-700">{erreur}</p>
  if (!valeurs || !initial) return <LoadingSpinner label="Chargement…" />

  const modifies = CHAMPS.filter(f => valeurs[f.cle].trim() !== initial[f.cle].trim()).map(f => f.cle)
  const complet = !!initial.oidc_issuer.trim() && !!initial.oidc_client_id.trim() && secretDefini
  const moiAdmin = moi?.role === 'admin'

  const enregistrer = async (e: FormEvent) => {
    e.preventDefault()
    const corps: ConfigUpdate = {}
    for (const cle of modifies) corps[cle] = valeurs[cle].trim()
    if (secret.trim()) corps.oidc_client_secret = secret.trim()
    if (!Object.keys(corps).length) return
    setEnCours(true)
    try {
      const r = await systemApi.updateConfig(corps)
      appliquer(r.config)
      setSecret('')
      if ((r.reinitialises ?? []).includes('oidc_client_secret')) {
        toast.error("Émetteur, identifiant ou adresse de retour modifiés sans nouveau secret : l'ancien secret a été effacé. Ressaisissez-le.")
      } else {
        toast.success('Réglages du SSO enregistrés.')
      }
      void rechargerAuth()
    } catch (err) {
      toast.error(messageErreur(err))
    } finally {
      setEnCours(false)
    }
  }

  const basculer = async (activer: boolean) => {
    setEnCours(true)
    try {
      await systemApi.updateConfig({ auth_active: activer ? 'true' : 'false' })
      toast.success(activer ? 'Authentification activée.' : 'Authentification éteinte.')
      await charger()
      await rechargerAuth()
    } catch (err) {
      toast.error(messageErreur(err))
    } finally {
      setEnCours(false)
      setConfirmer(null)
    }
  }

  const { pathname, search, protocol } = window.location
  const { url: lienConnexion, versRouteTls } = urlConnexion({
    baseApi: apiClient.defaults.baseURL ?? '/api', adresseConnexion, protocole: protocol, pathname, search,
  })

  return (
    <div className="space-y-5">
      <p className="text-xs text-gray-500">
        Connexion à Matothèque avec les comptes du NAS (OpenID Connect). Dans l'ordre : <strong>1.</strong> saisir le
        SSO, <strong>2.</strong> se connecter une fois avec un compte administrateur, <strong>3.</strong> activer.
        Tant que l'authentification est éteinte, l'application reste ouverte à tout le réseau local.
      </p>

      <div className={`rounded-lg border px-3 py-2 text-sm ${authActive
        ? 'border-green-200 bg-green-50 text-green-800' : 'border-gray-200 bg-gray-50 text-gray-700'}`}>
        État : <strong>{authActive ? 'authentification active' : 'authentification éteinte'}</strong>
        {' · '}SSO {complet ? 'configuré' : <strong>incomplet</strong>}
      </div>

      {/* 1. Réglages du SSO */}
      <form onSubmit={e => void enregistrer(e)} className="space-y-3">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-gray-800">
          <KeyRound size={15} className="text-indigo-600" /> 1. Réglages du SSO
        </h3>
        <div className="grid gap-3 md:grid-cols-2">
          {CHAMPS.slice(0, 2).map(f => (
            <Champ key={f.cle} f={f} valeur={valeurs[f.cle]} onChange={v => setValeurs({ ...valeurs, [f.cle]: v })} />
          ))}
          <label className="flex flex-col text-xs text-gray-600">
            Secret client (Application secret)
            <input type="password" autoComplete="new-password" value={secret} onChange={e => setSecret(e.target.value)}
              placeholder={secretDefini ? '•••••••• enregistré — laisser vide pour le conserver' : 'à coller depuis DSM ou Bitwarden'}
              className="mt-0.5 px-2 py-1.5 text-sm border border-gray-300 rounded-lg" />
            <span className="mt-0.5 text-gray-400">Chiffré en base, jamais réaffiché.</span>
          </label>
          {CHAMPS.slice(2).map(f => (
            <Champ key={f.cle} f={f} valeur={valeurs[f.cle]} onChange={v => setValeurs({ ...valeurs, [f.cle]: v })} />
          ))}
        </div>
        <button type="submit" disabled={enCours || (!modifies.length && !secret.trim())}
          className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50">
          <Save size={14} /> Enregistrer
        </button>
      </form>

      {/* 2. Première connexion */}
      <div className="space-y-2 pt-4 border-t border-gray-200">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-gray-800">
          <LogIn size={15} className="text-indigo-600" /> 2. Connexion d'un administrateur
        </h3>
        {moi ? (
          <p className="flex items-center gap-1.5 text-sm text-gray-700">
            <CheckCircle2 size={15} className={moiAdmin ? 'text-green-600' : 'text-amber-500'} />
            Connecté : <strong>{moi.nom || moi.identifiant}</strong> ({moiAdmin ? 'administrateur' : 'utilisateur'})
            {!moiAdmin && ' — il faut un compte du groupe des administrateurs.'}
          </p>
        ) : (
          <>
            <p className="text-xs text-gray-500">
              Connectez-vous une fois avec un compte du groupe des administrateurs : c'est ce qui permet d'activer
              sans risquer de s'enfermer dehors.
              {versRouteTls && <> Vous passerez par l'adresse sécurisée <strong>{adresseConnexion}</strong>.</>}
            </p>
            {complet ? (
              <a href={lienConnexion}
                className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700">
                <LogIn size={14} /> Se connecter avec le SSO
              </a>
            ) : (
              <p className="text-xs text-amber-700">Enregistrez d'abord l'émetteur, l'identifiant et le secret client.</p>
            )}
          </>
        )}
      </div>

      {/* 3. Activation / extinction */}
      <div className="space-y-2 pt-4 border-t border-gray-200">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-gray-800">
          <Power size={15} className="text-indigo-600" /> 3. {authActive ? 'Extinction' : 'Activation'}
        </h3>
        <p className="text-xs text-gray-500">
          {authActive
            ? "Éteindre rouvre l'application à tout le réseau local, sans connexion."
            : 'Une fois active, chacun doit se connecter, et les automates (n8n, scripts) doivent présenter un jeton. Secours si le NAS est en panne : « python -m outils.auth » sur le serveur.'}
        </p>
        {confirmer ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-gray-700">
              {confirmer === 'activer' ? "Activer l'authentification ?" : "Éteindre l'authentification ?"}
            </span>
            <button type="button" disabled={enCours} onClick={() => void basculer(confirmer === 'activer')}
              className="px-3 py-1.5 text-sm text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-60">Confirmer</button>
            <button type="button" disabled={enCours} onClick={() => setConfirmer(null)}
              className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50">Annuler</button>
          </div>
        ) : authActive ? (
          <button type="button" onClick={() => setConfirmer('eteindre')}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm border border-red-300 text-red-700 rounded-lg hover:bg-red-50">
            <Power size={14} /> Éteindre l'authentification
          </button>
        ) : (
          <button type="button" disabled={!complet || !moiAdmin} onClick={() => setConfirmer('activer')}
            title={!complet ? 'SSO incomplet' : !moiAdmin ? "Connectez-vous d'abord avec un compte administrateur" : undefined}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-sm text-white bg-green-600 rounded-lg hover:bg-green-700 disabled:opacity-50">
            <Power size={14} /> Activer l'authentification
          </button>
        )}
      </div>
    </div>
  )
}

function Champ({ f, valeur, onChange }: {
  f: typeof CHAMPS[number]; valeur: string; onChange: (v: string) => void
}) {
  return (
    <label className="flex flex-col text-xs text-gray-600">
      {f.label}
      <input value={valeur} placeholder={f.placeholder} onChange={e => onChange(e.target.value)}
        className="mt-0.5 px-2 py-1.5 text-sm border border-gray-300 rounded-lg" />
      {f.aide && <span className="mt-0.5 text-gray-400">{f.aide}</span>}
    </label>
  )
}
