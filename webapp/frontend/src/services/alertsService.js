export async function getAlertQueues() {
  const [pendingRes, activeRes] = await Promise.all([
    fetch('/api/alerts/pending'),
    fetch('/api/alerts/active'),
  ])

  return {
    pending: await pendingRes.json(),
    active: await activeRes.json(),
  }
}

export function approveAlert(id, { duration, eta } = {}) {
  const qs = new URLSearchParams({ duration: duration ?? 60 })
  if (eta !== undefined) qs.set('eta', eta)

  return fetch(`/api/alerts/${id}/approve?${qs}`, { method: 'POST' })
}

export function updateAlert(id, { level, duration }) {
  const qs = new URLSearchParams({
    newLevel: level,
    newDuration: duration,
  })

  return fetch(`/api/alerts/${id}/update?${qs}`, { method: 'POST' })
}

export function closeAlert(id) {
  return fetch(`/api/alerts/${id}/close`, { method: 'POST' })
}

export function rejectAlert(id) {
  return fetch(`/api/alerts/${id}/reject`, { method: 'POST' })
}
