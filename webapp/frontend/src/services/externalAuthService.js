const AUTH_API_BASE_URL = (
  import.meta.env.VITE_AUTH_API_URL ||
  'https://previsoesbrblueocean.com.br/api'
).replace(/\/+$/, '')

const AUTH_STORAGE_KEY = 'auth'
const TOKEN_KEYS = ['accessToken', 'token', 'authToken']

function readStorageValue(key) {
  try {
    return window.localStorage.getItem(key) || window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function readCookieValue(key) {
  try {
    const cookie = document.cookie
      .split('; ')
      .find((item) => item.startsWith(`${encodeURIComponent(key)}=`))

    return cookie ? decodeURIComponent(cookie.split('=').slice(1).join('=')) : null
  } catch {
    return null
  }
}

function getStoredSession() {
  const rawSession = readStorageValue(AUTH_STORAGE_KEY)
  if (!rawSession) return null

  try {
    return JSON.parse(rawSession)
  } catch {
    return null
  }
}

function getStoredToken() {
  for (const key of TOKEN_KEYS) {
    const token = readStorageValue(key) || readCookieValue(key)
    if (token) return token
  }

  return getStoredSession()?.accessToken || null
}

function getStoredRefreshToken() {
  return readStorageValue('refreshToken') || readCookieValue('refreshToken') || getStoredSession()?.refreshToken || null
}

function storeSession(session) {
  if (!session?.accessToken) return

  try {
    window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session))
    window.localStorage.setItem('accessToken', session.accessToken)

    if (session.refreshToken) {
      window.localStorage.setItem('refreshToken', session.refreshToken)
    }
  } catch {
    // If storage is unavailable, the current validation result still decides access.
  }
}

async function validateToken(token) {
  const response = await fetch(`${AUTH_API_BASE_URL}/auth/me`, {
    credentials: 'include',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })

  return response.ok
}

async function validateCookieSession() {
  const response = await fetch(`${AUTH_API_BASE_URL}/auth/me`, {
    credentials: 'include',
  })

  return response.ok
}

async function refreshAccessToken() {
  const refreshToken = getStoredRefreshToken()

  const response = await fetch(`${AUTH_API_BASE_URL}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ refreshToken: refreshToken || '' }),
  })

  if (!response.ok) return null

  const payload = await response.json().catch(() => null)
  const session = payload?.data ?? payload

  if (!session?.accessToken) return null

  storeSession(session)
  return session.accessToken
}

export async function checkExternalAuthorization() {
  const token = getStoredToken()

  try {
    if (token && await validateToken(token)) return true
    if (await validateCookieSession()) return true

    const refreshedToken = await refreshAccessToken()
    if (refreshedToken) return validateToken(refreshedToken)

    return validateCookieSession()
  } catch {
    return false
  }
}
