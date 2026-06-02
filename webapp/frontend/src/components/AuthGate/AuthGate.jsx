import { useEffect, useState } from 'react'
import { checkExternalAuthorization } from '../../services/externalAuthService'
import './AuthGate.css'

const LOGIN_URL = import.meta.env.VITE_LOGIN_URL || 'https://previsoesbrblueocean.com.br/login'

function RedirectingContent() {
  return (
    <main className="lt-auth-page" aria-live="polite">
      <h1>Redirecionando para login...</h1>
    </main>
  )
}

function AuthGate({ children }) {
  const [authorizationStatus, setAuthorizationStatus] = useState('checking')

  useEffect(() => {
    let isActive = true

    checkExternalAuthorization().then((isAuthorized) => {
      if (!isActive) return

      if (!isAuthorized) {
        setAuthorizationStatus('unauthorized')
        window.location.replace(LOGIN_URL)
        return
      }

      setAuthorizationStatus('authorized')
    })

    return () => {
      isActive = false
    }
  }, [])

  if (authorizationStatus === 'checking') {
    return <main className="lt-auth-page" aria-label="Verificando autorizacao" />
  }

  if (authorizationStatus === 'unauthorized') {
    return <RedirectingContent />
  }

  return children
}

export default AuthGate
