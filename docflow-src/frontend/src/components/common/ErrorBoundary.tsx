/**
 * ErrorBoundary — Capture les erreurs React runtime
 * Affiche un message de repli au lieu de crasher l'arbre entier.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  reset = () => this.setState({ hasError: false, error: null })

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      return (
        <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
          <AlertTriangle size={32} className="text-red-400" strokeWidth={1.5} />
          <div>
            <p className="text-sm font-medium text-gray-700">Une erreur est survenue</p>
            <p className="text-xs text-gray-400 mt-1">{this.state.error?.message}</p>
          </div>
          <button
            onClick={this.reset}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 border border-gray-200 rounded-md hover:bg-gray-50 text-gray-600"
          >
            <RefreshCw size={12} />
            Réessayer
          </button>
        </div>
      )
    }

    return this.props.children
  }
}
