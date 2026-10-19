import type { ApiErrorBody } from '@/types/api'

export const API_BASE = '/api/v1'

/** Error carrying the backend's machine-readable code and HTTP status. */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

async function toError(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as ApiErrorBody
    if (body?.error) return new ApiError(res.status, body.error.code, body.error.message, body.error.details)
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, 'http_error', `Request failed (${res.status})`)
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: init.body instanceof FormData ? init.headers : { 'Content-Type': 'application/json', ...init.headers },
    })
  } catch {
    throw new ApiError(0, 'network_error', 'Cannot reach the QueryDoc AI server. Is the backend running?')
  }
  if (!res.ok) throw await toError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body instanceof FormData ? body : JSON.stringify(body ?? {}) }),
  put: <T>(path: string, body: unknown) => request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
  delete: (path: string) => request<void>(path, { method: 'DELETE' }),
}

/** Upload with progress events (fetch has no upload progress; XHR does). */
export function uploadWithProgress<T>(path: string, form: FormData, onProgress: (fraction: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}${path}`)
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onerror = () => reject(new ApiError(0, 'network_error', 'Upload failed: cannot reach the server.'))
    xhr.onload = () => {
      let body: unknown = null
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T)
      else {
        const err = (body as ApiErrorBody | null)?.error
        reject(new ApiError(xhr.status, err?.code ?? 'http_error', err?.message ?? `Upload failed (${xhr.status})`, err?.details))
      }
    }
    xhr.send(form)
  })
}
