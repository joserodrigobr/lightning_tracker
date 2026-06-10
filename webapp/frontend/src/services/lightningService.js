export function getTakers() {
  return fetch('/api/takers')
}

export function getActiveTaker() {
  return fetch('/api/takers/active')
}

export function getEvents(queryString) {
  return fetch(`/api/events?${queryString}`)
}

export function getNowcast(queryString) {
  return fetch(`/api/nowcast?${queryString}`)
}

export function getAbiOverlay(queryString) {
  return fetch(`/api/abi?${queryString}`)
}

export function getLatestTables(queryString) {
  return fetch(`/api/tables/latest?${queryString}`)
}

export function getSavedTable(queryString) {
  return fetch(`/api/tables/load?${queryString}`)
}

export function generateTableData(queryString) {
  return fetch(`/api/tables/generate?${queryString}`)
}

export function renderCurrentImage(queryString) {
  return fetch(`/api/render?${queryString}`)
}

export function renderAnimation(queryString) {
  return fetch(`/api/render/animation?${queryString}`)
}

export function submitDataRequest(payload) {
  return fetch('/api/data-requests', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  })
}
