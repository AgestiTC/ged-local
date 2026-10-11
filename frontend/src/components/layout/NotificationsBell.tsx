/**
 * NotificationsBell — la cloche de l'en-tête, entre « Tâches » et « Tika » (11/10/2026).
 * ======================================================================================
 * Pastille = notifications non lues. Un clic ouvre la liste ; une notification s'ouvre en grand
 * (Markdown rendu) et passe en « lue ». Premier usage : le bilan périodique « idées d'évolution »
 * tiré des instructions complémentaires (Paramètres › Notifications).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { Bell, CheckCheck, Settings, X } from 'lucide-react'
import { clsx } from 'clsx'
import { notificationsApi, type NotificationItem } from '../../api'

const RAFRAICHIR_MS = 60_000

export default function NotificationsBell() {
  const [items, setItems] = useState<NotificationItem[]>([])
  const [nonLues, setNonLues] = useState(0)
  const [ouvert, setOuvert] = useState(false)
  const [detail, setDetail] = useState<NotificationItem | null>(null)
  const zone = useRef<HTMLDivElement>(null)

  const charger = useCallback(() => {
    notificationsApi.list()
      .then(r => { setItems(r.notifications); setNonLues(r.non_lues) })
      .catch(() => { /* API injoignable : la cloche reste muette, sans erreur */ })
  }, [])

  useEffect(() => {
    charger()
    const id = setInterval(charger, RAFRAICHIR_MS)
    return () => clearInterval(id)
  }, [charger])

  // Fermer la liste au clic en dehors.
  useEffect(() => {
    if (!ouvert) return
    const fermer = (e: MouseEvent) => { if (!zone.current?.contains(e.target as Node)) setOuvert(false) }
    document.addEventListener('mousedown', fermer)
    return () => document.removeEventListener('mousedown', fermer)
  }, [ouvert])

  const ouvrir = (n: NotificationItem) => {
    setDetail(n)
    setOuvert(false)
    if (!n.lu) notificationsApi.lire(n.id).then(charger).catch(() => {})
  }

  return (
    <div ref={zone} className="relative">
      <button
        type="button"
        onClick={() => setOuvert(o => !o)}
        title={nonLues ? `${nonLues} notification(s) non lue(s)` : 'Notifications'}
        aria-label="Notifications"
        className="relative p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md"
      >
        <Bell size={15} />
        {nonLues > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[15px] h-[15px] px-0.5 rounded-full bg-red-500 text-white text-[10px] leading-[15px] text-center font-semibold">
            {nonLues > 9 ? '9+' : nonLues}
          </span>
        )}
      </button>

      {ouvert && (
        <div className="absolute right-0 top-full mt-1 w-80 max-w-[calc(100vw-2rem)] bg-white border border-gray-200 rounded-lg shadow-lg z-50 text-xs">
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
            <span className="font-semibold text-gray-700">Notifications</span>
            <div className="flex items-center gap-2">
              {nonLues > 0 && (
                <button type="button" onClick={() => notificationsApi.toutLire().then(charger).catch(() => {})}
                  title="Tout marquer comme lu" className="text-gray-400 hover:text-blue-600">
                  <CheckCheck size={14} />
                </button>
              )}
              <Link to="/settings?section=set-notifications" onClick={() => setOuvert(false)}
                title="Gérer les notifications" className="text-gray-400 hover:text-blue-600">
                <Settings size={14} />
              </Link>
            </div>
          </div>
          {items.length === 0 ? (
            <p className="px-3 py-4 text-gray-400 text-center">Aucune notification pour l'instant.</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto divide-y divide-gray-100">
              {items.slice(0, 10).map(n => (
                <li key={n.id}>
                  <button type="button" onClick={() => ouvrir(n)}
                    className={clsx('w-full text-left px-3 py-2 hover:bg-gray-50', !n.lu && 'bg-blue-50/50')}>
                    <span className={clsx('block truncate', n.lu ? 'text-gray-600' : 'text-gray-900 font-medium')}>
                      {!n.lu && <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 mr-1.5 align-middle" />}
                      {n.titre}
                    </span>
                    {n.created_at && (
                      <span className="text-gray-400">{new Date(n.created_at).toLocaleDateString('fr-FR')}</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {detail && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onClick={() => setDetail(null)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-800 truncate">{detail.titre}</h2>
              <button type="button" onClick={() => setDetail(null)} aria-label="Fermer" className="text-gray-400 hover:text-gray-700">
                <X size={16} />
              </button>
            </div>
            <div className="px-5 py-4 overflow-y-auto prose prose-sm max-w-none">
              <ReactMarkdown>{detail.contenu}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
