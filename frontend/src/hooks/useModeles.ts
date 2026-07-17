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
import { systemApi, type OllamaModel } from '../api'

export interface Modeles {
  modeles: OllamaModel[]
  defaut: string            // modèle que le backend appliquera en « Auto »
  loading: boolean
  erreur: boolean
  recharger: () => void
}

export function useModeles(): Modeles {
  const [modeles, setModeles] = useState<OllamaModel[]>([])
  const [defaut, setDefaut] = useState('')
  const [loading, setLoading] = useState(false)
  const [erreur, setErreur] = useState(false)

  const charger = useCallback(async () => {
    setLoading(true)
    setErreur(false)
    try {
      const r = await systemApi.models()
      setModeles(r.models)
      setDefaut(r.defaut)
      // Auto-réparation : un modèle CHOISI qui n'est plus installé (supprimé d'Ollama, ou
      // hérité d'un ancien état persisté) → retour à « Auto ». On préfère rendre la main au
      // routage backend plutôt que d'imposer en silence un autre modèle.
      // Lecture via getState() : `charger` reste stable, et on évite une closure périmée
      // qui testerait l'ANCIENNE sélection lors d'un rechargement manuel (♻️).
      const { model, setModel } = useReportStore.getState()
      if (model && r.models.length && !r.models.some(m => m.name === model)) setModel('')
    } catch {
      setErreur(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { charger() }, [charger])

  return { modeles, defaut, loading, erreur, recharger: charger }
}
