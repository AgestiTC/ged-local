/**
 * Système de toasts léger — sans dépendance externe
 * Usage : import { toast } from './Toast'
 *         toast.success('Fichier uploadé')
 *         toast.error('Erreur réseau')
 */
import { createContext, useCallback, useContext, useState } from 'react'
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react'
import { clsx } from 'clsx'

type ToastType = 'success' | 'error' | 'info'

interface ToastItem {
  id: string
  type: ToastType
  message: string
}

interface ToastContextValue {
  addToast: (message: string, type: ToastType) => void
}

const ToastContext = createContext<ToastContextValue>({ addToast: () => {} })

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const addToast = useCallback((message: string, type: ToastType = 'info') => {
    const id = crypto.randomUUID()
    setToasts(t => [...t, { id, type, message }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000)
  }, [])

  const remove = (id: string) => setToasts(t => t.filter(x => x.id !== id))

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      <div className="fixed bottom-4 right-4 flex flex-col gap-2 z-50 max-w-sm">
        {toasts.map(t => (
          <div
            key={t.id}
            className={clsx(
              'flex items-start gap-2 px-4 py-3 rounded-lg shadow-lg text-sm text-white',
              t.type === 'success' && 'bg-green-600',
              t.type === 'error' && 'bg-red-600',
              t.type === 'info' && 'bg-blue-600',
            )}
          >
            {t.type === 'success' && <CheckCircle size={16} className="mt-0.5 shrink-0" />}
            {t.type === 'error' && <AlertCircle size={16} className="mt-0.5 shrink-0" />}
            {t.type === 'info' && <Info size={16} className="mt-0.5 shrink-0" />}
            <span className="flex-1">{t.message}</span>
            <button onClick={() => remove(t.id)} className="shrink-0 opacity-70 hover:opacity-100">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const { addToast } = useContext(ToastContext)
  return {
    success: (msg: string) => addToast(msg, 'success'),
    error: (msg: string) => addToast(msg, 'error'),
    info: (msg: string) => addToast(msg, 'info'),
  }
}
