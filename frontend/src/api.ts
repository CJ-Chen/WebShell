let csrfToken = ''

export class ApiError extends Error {
  code: string
  status: number
  detail?: string

  constructor(status: number, code: string, message: string, detail?: string) {
    super(message)
    this.status = status
    this.code = code
    this.detail = detail
  }
}

export function setCsrfToken(value: string) {
  csrfToken = value
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const method = (init.method || 'GET').toUpperCase()
  if (!(init.body instanceof FormData) && init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken)
  }
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers,
    credentials: 'include',
  })
  if (!response.ok) {
    let payload: { code?: string; message?: string; detail?: string } = {}
    try {
      payload = await response.json()
    } catch {
      payload = {}
    }
    throw new ApiError(
      response.status,
      payload.code || 'REQUEST_FAILED',
      payload.message || `请求失败 (${response.status})`,
      payload.detail,
    )
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function terminalWebSocketUrl(terminalId: string, cols = 80, rows = 24) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const query = new URLSearchParams({ cols: String(cols), rows: String(rows) })
  return `${protocol}//${window.location.host}/api/v1/terminals/ws/${terminalId}?${query}`
}
