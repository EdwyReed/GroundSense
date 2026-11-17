import { describe, expect, it, vi } from 'vitest'
import { ApiClient } from './api'

describe('ApiClient', () => {
  it('includes CSRF on an explicit administrative tombstone', async () => {
    const fetcher=vi.fn().mockResolvedValue(new Response('{"tombstoned":true}'))
    const api=new ApiClient('token',fetcher)
    await (api as any).remove('/protocols/temporary',{expected_version:3})
    expect(fetcher.mock.calls[0][1].method).toBe('DELETE')
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({expected_version:3})
    expect(new Headers(fetcher.mock.calls[0][1].headers).get('X-CSRF-Token')).toBe('token')
  })
  it('binds the native fetch receiver rather than the Vue-proxied ApiClient', async () => {
    vi.stubGlobal('fetch', function (this: typeof globalThis) {
      if (this !== globalThis) throw new TypeError('Illegal invocation')
      return Promise.resolve(new Response('{"status":"ok"}', { status: 200 }))
    })
    try { await expect(new ApiClient('test').get('/health')).resolves.toEqual({status:'ok'}) }
    finally { vi.unstubAllGlobals() }
  })

  it('adds CSRF and idempotency headers to mutation requests', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'job-1' }), { status: 200 }))
    const api = new ApiClient('token-1', fetcher)

    await api.post('/analyses', { assessment_date: '2027-03-15', gross_mass_t: 20 }, 'request-1')

    const [url, init] = fetcher.mock.calls[0]
    expect(url).toBe('/api/v1/analyses')
    expect(init?.method).toBe('POST')
    const headers = new Headers(init?.headers)
    expect(headers.get('X-CSRF-Token')).toBe('token-1')
    expect(headers.get('Idempotency-Key')).toBe('request-1')
  })

  it('keeps multipart content type unset so browser provides the boundary', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'upload-1' }), { status: 200 }))
    const api = new ApiClient('token-1', fetcher)
    const file = new FormData(); file.append('file', new Blob(['evidence']), 'evidence.jpg')
    await api.upload('/uploads', file)
    const headers = new Headers(fetcher.mock.calls[0][1]?.headers)
    expect(headers.get('Content-Type')).toBeNull()
    expect(headers.get('X-CSRF-Token')).toBe('token-1')
  })

  it('reports non-successful server responses explicitly', async () => {
    const api = new ApiClient('token-1', async () => new Response(JSON.stringify({ detail: 'Адаптер не підключено' }), { status: 409 }))
    await expect(api.post('/sources/weather/sync', {})).rejects.toThrow('Адаптер не підключено')
  })
})
