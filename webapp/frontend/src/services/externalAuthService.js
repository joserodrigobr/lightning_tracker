const AUTH_API_BASE_URL = (
  import.meta.env.VITE_AUTH_API_URL ||
  'https://previsoesbrblueocean.com.br/api'
).replace(/\/+$/, '')

const LEGACY_TOKEN_KEYS = ['accessToken', 'refreshToken', 'token', 'authToken']

function clearLegacyTokenStorage() {
  try {
    LEGACY_TOKEN_KEYS.forEach((key) => {
      window.localStorage.removeItem(key)
      window.sessionStorage.removeItem(key)
    })
  } catch {
    // Storage can be unavailable in some browser/privacy modes.
  }
}

async function validateCookieSession() {
  const response = await fetch(`${AUTH_API_BASE_URL}/auth/me`, {
    credentials: 'include',
  })

  return response.ok
}

async function refreshCookieSession() {
  const response = await fetch(`${AUTH_API_BASE_URL}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({}),
  })

  return response.ok
}

export async function checkExternalAuthorization() {
  clearLegacyTokenStorage()

  try {
    if (await validateCookieSession()) return true
    if (!await refreshCookieSession()) return false

    return validateCookieSession()
  } catch {
    return false
  }
}
