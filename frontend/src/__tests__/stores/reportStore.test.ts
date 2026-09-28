/**
 * Tests — reportStore (Zustand)
 * ================================
 * Teste la configuration du rapport, le streaming SSE,
 * l'historique, et l'annulation.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

vi.mock('../../api', () => ({
  generateApi: {
    startReport: vi.fn().mockResolvedValue({ job_id: 'job-abc' }),
    getStreamUrl: vi.fn().mockReturnValue('http://localhost:8000/api/generate/stream/job-abc'),
  },
  exportApi: {
    toPdf: vi.fn().mockResolvedValue(undefined),
    toDocx: vi.fn().mockResolvedValue(undefined),
  },
  jobsApi: {
    cancel: vi.fn().mockResolvedValue({ job_id: 'job-abc', statut: 'cancelled' }),
  },
}))

import { useReportStore } from '../../stores/reportStore'

describe('reportStore — configuration', () => {
  beforeEach(() => {
    useReportStore.setState({
      prompt: '',
      model: '',
      outputMode: 'rapport_libre',
      isGenerating: false,
      jobId: null,
      rapportEnCours: '',
      rapportFinal: '',
      error: null,
      historique: [],
    })
  })

  it('setPrompt met à jour le prompt', () => {
    useReportStore.getState().setPrompt('Analyse ce document')
    expect(useReportStore.getState().prompt).toBe('Analyse ce document')
  })

  it('setModel met à jour le modèle', () => {
    useReportStore.getState().setModel('llama3.1:latest')
    expect(useReportStore.getState().model).toBe('llama3.1:latest')
  })

  it('setOutputMode met à jour le mode', () => {
    useReportStore.getState().setOutputMode('classement')
    expect(useReportStore.getState().outputMode).toBe('classement')
  })
})

describe('reportStore — appendChunk / finishGeneration', () => {
  beforeEach(() => {
    useReportStore.setState({
      prompt: 'Analyse',
      model: '',
      outputMode: 'rapport_libre',
      isGenerating: true,
      jobId: 'job-abc',
      rapportEnCours: '',
      rapportFinal: '',
      error: null,
      historique: [],
    })
  })

  it('appendChunk accumule les chunks', () => {
    useReportStore.getState().appendChunk('Bonjour ')
    useReportStore.getState().appendChunk('le monde')
    expect(useReportStore.getState().rapportEnCours).toBe('Bonjour le monde')
  })

  it('finishGeneration termine la génération et ajoute à l\'historique', () => {
    useReportStore.getState().appendChunk('Contenu du rapport.')
    useReportStore.getState().finishGeneration('Contenu du rapport.')

    const state = useReportStore.getState()
    expect(state.isGenerating).toBe(false)
    expect(state.rapportFinal).toBe('Contenu du rapport.')
    expect(state.historique).toHaveLength(1)
    expect(state.historique[0].rapport).toBe('Contenu du rapport.')
    expect(state.historique[0].prompt).toBe('Analyse')
  })

  it('l\'historique est limité à 20 entrées', () => {
    // Pré-remplir avec 20 entrées
    const existing = Array.from({ length: 20 }, (_, i) => ({
      id: `id-${i}`,
      prompt: `prompt ${i}`,
      rapport: `rapport ${i}`,
      model: '',
      created_at: '2026-01-01T00:00:00Z',
      nb_documents: 0,
    }))
    useReportStore.setState({ historique: existing })

    useReportStore.getState().finishGeneration('Nouveau rapport')
    expect(useReportStore.getState().historique).toHaveLength(20)
    expect(useReportStore.getState().historique[0].rapport).toBe('Nouveau rapport')
  })
})

describe('reportStore — cancelGeneration / resetRapport', () => {
  beforeEach(() => {
    useReportStore.setState({
      prompt: '',
      model: '',
      outputMode: 'rapport_libre',
      isGenerating: true,
      jobId: 'job-abc',
      rapportEnCours: 'partiel...',
      rapportFinal: '',
      error: null,
      historique: [],
    })
  })

  it('cancelGeneration arrête la génération avec un message d\'erreur', () => {
    useReportStore.getState().cancelGeneration()
    expect(useReportStore.getState().isGenerating).toBe(false)
    expect(useReportStore.getState().error).toBe('Génération annulée')
  })

  it('resetRapport nettoie le rapport et l\'erreur', () => {
    useReportStore.setState({ error: 'Connexion perdue', rapportFinal: 'ancien', jobId: 'old-job' })
    useReportStore.getState().resetRapport()

    const state = useReportStore.getState()
    expect(state.rapportEnCours).toBe('')
    expect(state.rapportFinal).toBe('')
    expect(state.error).toBeNull()
    expect(state.jobId).toBeNull()
  })
})

describe('reportStore — startGeneration', () => {
  beforeEach(() => {
    useReportStore.setState({
      prompt: 'Analyse les documents',
      model: '',
      outputMode: 'rapport_libre',
      isGenerating: false,
      jobId: null,
      rapportEnCours: '',
      rapportFinal: '',
      error: null,
      historique: [],
    })
  })

  it('ne démarre pas si le prompt est vide', async () => {
    useReportStore.setState({ prompt: '   ' })
    await useReportStore.getState().startGeneration(['doc-1'])
    expect(useReportStore.getState().isGenerating).toBe(false)
  })

  it('passe isGenerating à true et définit jobId', async () => {
    const { generateApi } = await import('../../api')
    // La résolution sera bloquée pour vérifier l'état intermédiaire
    vi.mocked(generateApi.startReport).mockResolvedValueOnce({ job_id: 'job-xyz' })

    const promise = useReportStore.getState().startGeneration(['doc-1', 'doc-2'])
    // isGenerating devrait être true immédiatement (avant que la promesse résolve)
    expect(useReportStore.getState().isGenerating).toBe(true)
    await promise
    expect(useReportStore.getState().jobId).toBe('job-xyz')
  })

  it('stocke l\'erreur si l\'API échoue', async () => {
    const { generateApi } = await import('../../api')
    vi.mocked(generateApi.startReport).mockRejectedValueOnce(new Error('Ollama indisponible'))

    await useReportStore.getState().startGeneration(['doc-1'])

    const state = useReportStore.getState()
    expect(state.isGenerating).toBe(false)
    expect(state.error).toBe('Ollama indisponible')
  })
})

// Faux EventSource piloté par le test (jsdom n'en fournit pas).
class FluxSimule {
  static derniers: FluxSimule[] = []
  onmessage: ((e: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  ferme = false
  constructor(public url: string) { FluxSimule.derniers.push(this) }
  close() { this.ferme = true }
  emettre(data: object) { this.onmessage?.({ data: JSON.stringify(data) }) }
}

describe('reportStore — « Effacer » pendant une génération (audit H8)', () => {
  beforeEach(() => {
    FluxSimule.derniers = []
    vi.stubGlobal('EventSource', FluxSimule)
    useReportStore.setState({
      prompt: 'Analyse', model: '', outputMode: 'rapport_libre', isGenerating: false,
      jobId: null, rapportEnCours: '', rapportFinal: '', error: null, historique: [],
    })
  })

  it('le texte effacé ne réapparaît pas : le flux est fermé et ses messages ignorés', async () => {
    await useReportStore.getState().startGeneration(['doc-1'])
    const flux = FluxSimule.derniers[0]
    flux.emettre({ chunk: 'Début du rapport', done: false })
    expect(useReportStore.getState().rapportEnCours).toBe('Début du rapport')

    useReportStore.getState().resetRapport()
    expect(flux.ferme).toBe(true)
    expect(useReportStore.getState().isGenerating).toBe(false)

    // Un message déjà en route après l'effacement ne doit rien écrire.
    flux.emettre({ chunk: ' suite fantôme', done: false })
    flux.emettre({ done: true, rapport_complet: 'Rapport fantôme' })
    const s = useReportStore.getState()
    expect(s.rapportEnCours).toBe('')
    expect(s.rapportFinal).toBe('')
    expect(s.historique).toHaveLength(0)
  })

  it('« Effacer » annule aussi le job côté serveur (GPU partagé)', async () => {
    const { jobsApi } = await import('../../api')
    vi.mocked(jobsApi.cancel).mockClear()
    await useReportStore.getState().startGeneration(['doc-1'])
    useReportStore.getState().resetRapport()
    expect(jobsApi.cancel).toHaveBeenCalledWith('job-abc')
  })

  it('un job en échec n\'est pas un rapport : erreur posée, pas d\'historique (M11)', async () => {
    await useReportStore.getState().startGeneration(['doc-1'])
    const flux = FluxSimule.derniers[0]
    flux.emettre({ chunk: 'Début partiel', done: false })
    flux.emettre({ chunk: '', done: true, statut: 'failed', erreur: 'Ollama injoignable' })
    const s = useReportStore.getState()
    expect(s.isGenerating).toBe(false)
    expect(s.error).toContain('Ollama injoignable')
    expect(s.rapportFinal).toBe('')          // rien d'« achevé »
    expect(s.historique).toHaveLength(0)
    expect(s.rapportEnCours).toBe('Début partiel')   // le texte reste visible, marqué en échec
  })

  it('une nouvelle génération ferme la précédente', async () => {
    await useReportStore.getState().startGeneration(['doc-1'])
    const premier = FluxSimule.derniers[0]
    await useReportStore.getState().startGeneration(['doc-2'])
    expect(premier.ferme).toBe(true)
  })
})
