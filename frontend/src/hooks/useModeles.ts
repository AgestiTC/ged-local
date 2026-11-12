/**
 * useModeles — liste des modèles Ollama installés + résolution du modèle « Auto »
 * ==============================================================================
 * À appeler au montage de la PAGE, jamais depuis un panneau repliable : c'est
 * précisément l'erreur qui a causé le bug « mixtral ». L'auto-réparation vivait dans
 * `ModelSelector`, monté seulement si l'utilisateur dépliait le réglage — donc elle ne
 * s'exécutait jamais dans le cas qu'elle devait couvrir (modèle par défaut invalide).
 *
 * Sémantique « Auto » (= celle des Paramètres → « routage dynamique, Auto = défaut ») :
 * `model === ''` → on n'impose rien, le backend route selon `usage_models`.
 */
import { useCallback, useEffect, useState } from 'react'
import { useReportStore } from '../stores/reportStore'
import { systemApi, type OllamaModel, type ModeleExterne, type ExternesEtat } from '../api'
import { useAuthStore } from '../stores/authStore'
import { estAdmin } from '../utils/acces'
import { useIaDestinationStore } from '../stores/iaDestinationStore'
import { destinationValide, estModeleGeco, modeleAuto } from '../utils/iaDestination'

export interface Modeles {
  modeles: OllamaModel[]    // modèles INSTALLÉS (Ollama) uniquement
  externes: ModeleExterne[] // modèles d'une IA externe (GECO) : jamais pris pour des modèles installés
  externesEtat: ExternesEtat
  defaut: string            // modèle que le backend appliquera en « Auto » (le modèle GECO quand le bouton est sur IA GECO)
  autoInternet: boolean     // « Auto » part par internet (bouton sur IA GECO) : à dire dans le libellé
  loading: boolean
  erreur: boolean
  charge: boolean           // les listes ont été lues au moins une fois (ou rôle restreint : rien à lire)
  restreint: boolean        // rôle utilisateur : la liste (/api/system/models, admin) n'est pas lue → « Auto » seul
  recharger: () => void
}

export function useModeles(usage: 'rapport' | 'enrichissement' | 'vision' | 'embeddings' = 'rapport'): Modeles {
  const [modeles, setModeles] = useState<OllamaModel[]>([])
  const [externes, setExternes] = useState<ModeleExterne[]>([])
  const [externesEtat, setExternesEtat] = useState<ExternesEtat>('non_configure')
  const [defaut, setDefaut] = useState('')
  const [loading, setLoading] = useState(false)
  const [erreur, setErreur] = useState(false)
  const [charge, setCharge] = useState(false)

  const restreint = !estAdmin(useAuthStore.getState())
  // Destination de l'IA : lue par tout utilisateur (route `/api/system/ia/destination`), même restreint.
  const destination = useIaDestinationStore(s => s.destination)
  const gecoModele = useIaDestinationStore(s => s.gecoModele)
  const destinationConnue = useIaDestinationStore(s => s.connu)

  // Bouton sur IA LOCAL : un modèle GECO resté sélectionné serait refusé (400) → retour à « Auto ».
  useEffect(() => {
    if (destination === 'geco' || !destinationConnue) return   // pas de remise à « Auto » avant la 1re lecture
    const { model, setModel } = useReportStore.getState()
    if (estModeleGeco(model)) setModel('')
  }, [destination, destinationConnue])

  const charger = useCallback(async () => {
    if (restreint) {   // pas d'appel voué au 403 : le routage « Auto » du serveur s'applique
      const { model, setModel } = useReportStore.getState()
      if (model) setModel('')
      setCharge(true)
      return
    }
    setLoading(true)
    setErreur(false)
    try {
      const r = await systemApi.models()
      setModeles(r.models)
      setExternes(r.externes ?? [])
      setExternesEtat(r.externes_etat ?? 'non_configure')
      // Le modèle appliqué en « Auto » dépend de l'USAGE (`usage_models`), pas de `default_model` :
      // afficher ce dernier faisait croire à llama3.1 (4,9 Go) alors qu'un rapport partait sur
      // Qwen3.6-35B (43 Go) — d'où des attentes interminables et des délais dépassés inexpliqués.
      setDefaut(r.par_usage?.[usage] || r.defaut)
      // Auto-réparation : un modèle CHOISI qui n'est plus installé (supprimé d'Ollama, ou
      // hérité d'un ancien état persisté) → retour à « Auto ». On préfère rendre la main au
      // routage backend plutôt que d'imposer en silence un autre modèle.
      // Lecture via getState() : `charger` reste stable, et on évite une closure périmée
      // qui testerait l'ANCIENNE sélection lors d'un rechargement manuel (♻️).
      const { model, setModel } = useReportStore.getState()
      // Un modèle GECO choisi n'est pas « installé » : on le cherche aussi dans la liste GECO.
      const connu = r.models.some(m => m.name === model) || (r.externes ?? []).some(m => m.name === model)
      const etat = useIaDestinationStore.getState().destination
      // Un modèle GECO n'est jamais retiré tant que l'état de l'IA est inconnu (liste GECO peut-être momentanément vide).
      if (model && r.models.length && !connu && !(estModeleGeco(model) && etat === 'inconnu')) setModel('')
      // Destination : celle du serveur si conforme, sinon celle du store ; « inconnu » ne retire rien.
      const dest = destinationValide(r.ia_destination) ?? useIaDestinationStore.getState().destination
      if (model && estModeleGeco(model) && dest === 'local') setModel('')
      setCharge(true)
    } catch {
      setErreur(true)
    } finally {
      setLoading(false)
    }
  }, [usage, restreint])

  // Relance aussi quand la destination change : les options GECO se dégrisent / regrisent sans recharger la page.
  useEffect(() => { charger() }, [charger, destination])

  // « Auto » désigne le modèle GECO en mode GECO, le défaut local sinon (jamais le local en mode GECO).
  const auto = modeleAuto({ destination, gecoModele, defautLocal: defaut })
  return { modeles, externes, externesEtat, defaut: auto.nom, autoInternet: auto.internet, loading, erreur, charge, restreint, recharger: charger }
}
