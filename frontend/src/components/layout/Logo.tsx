/**
 * Logo — Marque Matothèque (SVG inline)
 * =====================================
 * Un badge « pile de documents » (Matothèque = bibliothèque de documents/matériel), pensé pour un
 * fond SOMBRE (sidebar). Couleurs figées → même rendu partout ; se détache bien sur `bg-gray-900`.
 */
export default function Logo({ size = 30, className = '' }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none"
      className={className} role="img" aria-label="Logo Matothèque">
      {/* Badge arrondi — dégradé bleu (accent de l'app). */}
      <defs>
        <linearGradient id="mato-bg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3b82f6" />
          <stop offset="1" stopColor="#2563eb" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="8" fill="url(#mato-bg)" />
      {/* Pile de documents (du fond vers l'avant). */}
      <rect x="8.5" y="8" width="13" height="17" rx="2" fill="#ffffff" opacity="0.30" />
      <rect x="7" y="9.5" width="13" height="17" rx="2" fill="#ffffff" opacity="0.55" />
      <rect x="10" y="6.5" width="13" height="17" rx="2" fill="#ffffff" />
      {/* Lignes de texte sur la feuille de devant. */}
      <rect x="12.4" y="10.4" width="8.2" height="1.5" rx="0.75" fill="#2563eb" />
      <rect x="12.4" y="13.6" width="8.2" height="1.5" rx="0.75" fill="#93c5fd" />
      <rect x="12.4" y="16.8" width="5.2" height="1.5" rx="0.75" fill="#93c5fd" />
    </svg>
  )
}
