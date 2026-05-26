import { useEffect, useState } from 'react'
import { checkExternalAuthorization } from '../../services/externalAuthService'
import './AuthGate.css'

function UnauthorizedContent() {
  return (
    <main className="lt-auth-page" aria-live="polite">
      <h1>Conteudo nao autorizado</h1>
    </main>
  )
}

function AuthGate({ children }) {
  const [authorizationStatus, setAuthorizationStatus] = useState('checking')

  useEffect(() => {
    let isActive = true

    checkExternalAuthorization().then((isAuthorized) => {
      if (!isActive) return
      setAuthorizationStatus(isAuthorized ? 'authorized' : 'unauthorized')
    })

    return () => {
      isActive = false
    }
  }, [])

  if (authorizationStatus === 'checking') {
    return <main className="lt-auth-page" aria-label="Verificando autorizacao" />
  }

  if (authorizationStatus === 'unauthorized') {
    return <UnauthorizedContent />
  }

  return children
}

export default AuthGate
