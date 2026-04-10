# Module Frontend — Vue d'ensemble

## Stack

- **React 18** + TypeScript strict
- **Vite** (bundler + dev server)
- **TailwindCSS** (styling utility-first)
- **Zustand** (state management global)
- **TanStack Query** (cache + requêtes API)
- **react-dropzone** (drag & drop)
- **react-router-dom** (routing SPA)

## Structure

```
src/
├── main.tsx          ← Point d'entrée React + QueryClient
├── App.tsx           ← Router principal (3 routes)
├── index.css         ← Tailwind directives
├── api/
│   └── client.ts     ← Axios centralisé (+ timeout long pour Ollama)
├── types/
│   └── index.ts      ← Types TypeScript partagés avec le backend
├── components/
│   ├── layout/       ← MainLayout, Sidebar, Header
│   ├── files/        ← FileExplorer, DropZone, FileCard
│   ├── reports/      ← PromptEditor, ModelSelector, ReportPreview...
│   ├── ged/          ← SearchBar, DocumentCard, TagManager...
│   └── common/       ← LoadingSpinner, ErrorBoundary, Toast
├── pages/
│   ├── ReportsPage   ← Page principale (3 colonnes)
│   ├── GEDPage       ← Recherche + navigation
│   └── SettingsPage  ← Configuration
├── stores/
│   ├── documentStore ← Zustand : sélection documents
│   ├── reportStore   ← Zustand : prompt + modèle + résultat
│   └── gedStore      ← Zustand : recherche + filtres
└── hooks/
    ├── useDropZone   ← Drag & drop fichiers/dossiers/ZIP
    ├── useDocuments  ← TanStack Query : liste documents
    ├── useSearch     ← TanStack Query : recherche
    └── useReport     ← Génération rapport + SSE streaming
```

## Drag & Drop

Supporte trois modes via `react-dropzone` + `webkitGetAsEntry` API :
1. **Fichiers individuels** — PDF, DOCX, PPTX, PPSX, XLSX
2. **Dossiers entiers** — récursif via `webkitdirectory`
3. **Archives ZIP** — extraction automatique côté backend

## Streaming SSE

La génération de rapport utilise **Server-Sent Events** :
```typescript
const eventSource = new EventSource(`/api/generate/stream/${jobId}`)
eventSource.onmessage = (e) => {
  const { chunk, done } = JSON.parse(e.data)
  appendToResult(chunk)
  if (done) eventSource.close()
}
```

## TODO Phase 2

- [ ] Implémenter `DropZone.tsx` (drag & drop avec feedback visuel)
- [ ] Implémenter `FileExplorer.tsx` (arborescence + cases à cocher)
- [ ] Implémenter `PromptEditor.tsx` (textarea + présets)
- [ ] Implémenter `ModelSelector.tsx` (dropdown des modèles Ollama)
- [ ] Implémenter `ReportPreview.tsx` (Markdown rendu + export)
- [ ] Implémenter `GenerateButton.tsx` + SSE streaming
- [ ] Styling Tailwind complet
