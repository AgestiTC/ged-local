/** Barre horizontale de proportion, avec la valeur ÉCRITE à côté (jamais la couleur seule). */
export default function Barre({ pourcent, libelle }: { pourcent: number; libelle?: string }) {
  const largeur = Math.max(0, Math.min(100, pourcent))
  return (
    <div className="flex items-center gap-2 min-w-0" title={libelle}>
      <div className="h-2 flex-1 min-w-[3rem] rounded bg-gray-100 overflow-hidden" aria-hidden="true">
        <div className="h-full rounded bg-blue-500" style={{ width: `${largeur}%` }} />
      </div>
      <span className="text-xs tabular-nums text-gray-600 w-11 text-right shrink-0">{`${pourcent}\u00a0%`}</span>
    </div>
  )
}
