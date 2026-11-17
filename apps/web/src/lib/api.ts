export class ApiError extends Error {
  constructor(readonly status: number, message: string) { super(message) }
}

type Fetcher = typeof fetch

export class ApiClient {
  constructor(private csrf: string, private fetcher: Fetcher = globalThis.fetch.bind(globalThis)) {}

  private async request<T>(path: string, init: RequestInit = {}, idempotencyKey?: string): Promise<T> {
    const headers = new Headers(init.headers)
    if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
    if (init.method && init.method !== 'GET') headers.set('X-CSRF-Token', this.csrf)
    if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey)
    const response = await this.fetcher(`/api/v1${path}`, { credentials: 'same-origin', ...init, headers })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new ApiError(response.status, payload.detail || payload.message || `Помилка сервера (${response.status})`)
    return payload as T
  }

  get<T>(path: string) { return this.request<T>(path) }
  remove<T>(path: string, body: {expected_version:number}) { return this.request<T>(path, {method:'DELETE',body:JSON.stringify(body)}) }
  post<T>(path: string, body: unknown, idempotencyKey?: string) {
    return this.request<T>(path, { method: 'POST', body: JSON.stringify(body) }, idempotencyKey)
  }
  patch<T>(path: string, body: unknown) { return this.request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }) }
  upload<T>(path: string, data: FormData) {
    return this.request<T>(path, { method: 'POST', body: data, headers: { 'X-CSRF-Token': this.csrf } })
  }
}

export const createKey = () => crypto.randomUUID()
