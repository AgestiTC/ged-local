/**
 * Header — Barre du haut avec état des services
 * TODO Phase 2 : indicateurs Tika/Ollama online/offline
 */
export default function Header() {
  return (
    <header className="h-12 bg-white border-b border-gray-200 flex items-center justify-between px-4">
      <div className="text-sm text-gray-500">DocFlow AI</div>
      <div className="flex items-center gap-3 text-xs text-gray-400">
        <span>🔵 Tika</span>
        <span>🔵 Ollama</span>
        <span>🔵 DB</span>
      </div>
    </header>
  )
}
