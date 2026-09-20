import type {
  AgentResponse,
  AlertDisposition,
  AlertQueueItem,
  ApiErrorPayload,
  AuditResponse,
  CustomerDetail,
  CustomerFilters,
  CustomerPage,
  DatasetInfo,
  DatasetInspection,
  DatasetSwitchResult,
  DatasetUploadResult,
  HealthResponse,
  InvestigationRecord,
  InvestigationSummary,
  ModelCard,
  ModelDriftReport,
  PolicyResponse,
  QueueResponse,
  QueueSummary,
  TransactionFilters,
  TransactionPage,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')

const RETRYABLE_STATUS = new Set([429, 502, 503, 504])
const DEFAULT_TIMEOUT_MS = 30_000

export class ApiClientError extends Error {
  readonly status: number
  readonly code: string | null
  readonly requestId: string | null
  readonly retryable: boolean

  constructor(
    message: string,
    options: {
      status?: number
      code?: string | null
      requestId?: string | null
      retryable?: boolean
      cause?: unknown
    } = {},
  ) {
    super(message)
    this.name = 'ApiClientError'
    this.status = options.status ?? 0
    this.code = options.code ?? null
    this.requestId = options.requestId ?? null
    this.retryable = options.retryable ?? false
    this.cause = options.cause
  }
}

interface ApiRequestInit extends RequestInit {
  timeoutMs?: number
}

async function readErrorPayload(response: Response): Promise<ApiErrorPayload> {
  try {
    return (await response.json()) as ApiErrorPayload
  } catch {
    return {}
  }
}

function clientRequestId() {
  return globalThis.crypto?.randomUUID?.()
    ?? `sentinel-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

async function request<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  const method = init?.method?.toUpperCase() ?? 'GET'
  const attempts = method === 'GET' ? 3 : 1
  const requestId = clientRequestId()
  let lastError: unknown

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const controller = new AbortController()
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      init.timeoutMs ?? DEFAULT_TIMEOUT_MS,
    )
    const abortRequest = () => controller.abort()
    init.signal?.addEventListener('abort', abortRequest, { once: true })

    try {
      const headers = new Headers(init?.headers)
      const hasBody = init.body !== undefined && init.body !== null
      if (hasBody && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
        headers.set('Content-Type', 'application/json')
      }
      headers.set('Accept', 'application/json')
      // Keep idempotent reads CORS-simple. Write requests retain correlation IDs.
      if (method !== 'GET') headers.set('X-Client-Request-Id', requestId)
      const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers,
        signal: controller.signal,
      })
      if (response.ok) {
        if (response.status === 204) return undefined as T
        return response.json() as Promise<T>
      }

      const payload = await readErrorPayload(response)
      throw new ApiClientError(
        payload.detail ?? `Request failed with status ${response.status}`,
        {
          status: response.status,
          code: payload.code,
          requestId:
            payload.request_id
            ?? response.headers.get('x-request-id')
            ?? requestId,
          retryable: RETRYABLE_STATUS.has(response.status),
        },
      )
    } catch (reason) {
      const normalizedError =
        reason instanceof ApiClientError
          ? reason
          : new ApiClientError(
              controller.signal.aborted
                ? 'The request timed out before the service responded.'
                : 'Sentinel could not reach the API service.',
              {
                requestId,
                retryable: method === 'GET',
                cause: reason,
              },
            )
      lastError = normalizedError
      if (
        attempt === attempts - 1
        || !normalizedError.retryable
      ) throw normalizedError
    } finally {
      window.clearTimeout(timeoutId)
      init.signal?.removeEventListener('abort', abortRequest)
    }
    await new Promise((resolve) => setTimeout(resolve, 750 * 2 ** attempt))
  }
  throw lastError instanceof Error
    ? lastError
    : new ApiClientError('Request failed', { requestId })
}

export function checkHealth() {
  return request<HealthResponse>('/health')
}

export function runQuery(query: string, datasetId?: string) {
  return request<AgentResponse>('/query', {
    method: 'POST',
    body: JSON.stringify({ query, dataset_id: datasetId }),
  })
}

export function getModelCard() {
  return request<ModelCard>('/model-card')
}

export function getModelDrift(limit = 1_000) {
  return request<ModelDriftReport>(`/model-card/drift?limit=${limit}`)
}

export function getInvestigations(limit = 50) {
  return request<InvestigationSummary[]>(`/investigations?limit=${limit}`)
}

export function getInvestigation(investigationId: string) {
  return request<InvestigationRecord>(
    `/investigations/${encodeURIComponent(investigationId)}`,
  )
}

export function getQueue(status?: string) {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  return request<QueueResponse>(`/queue${query}`)
}

export function getQueueSummary() {
  return request<QueueSummary>('/queue/summary')
}

export function assignAlert(alertId: string, assignedTo: string) {
  return request<AlertQueueItem>(
    `/queue/${encodeURIComponent(alertId)}/assign`,
    {
      method: 'POST',
      body: JSON.stringify({
        assigned_to: assignedTo,
        actor: 'demo.analyst',
      }),
    },
  )
}

export function dispositionAlert(
  alertId: string,
  disposition: Exclude<AlertDisposition, 'pending'>,
) {
  return request<AlertQueueItem>(
    `/queue/${encodeURIComponent(alertId)}/disposition`,
    {
      method: 'POST',
      body: JSON.stringify({
        disposition,
        actor: 'demo.analyst',
      }),
    },
  )
}

export function addAlertNote(alertId: string, note: string) {
  return request<AlertQueueItem>(
    `/queue/${encodeURIComponent(alertId)}/notes`,
    {
      method: 'POST',
      body: JSON.stringify({ note, actor: 'demo.analyst' }),
    },
  )
}

export function getAuditEvents(eventType?: string) {
  const query = eventType
    ? `?event_type=${encodeURIComponent(eventType)}`
    : ''
  return request<AuditResponse>(`/audit${query}`)
}

export function getPolicy() {
  return request<PolicyResponse>('/policy')
}

export function getDatasets() {
  return request<DatasetInfo[]>('/datasets')
}

export function inspectDataset(file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<DatasetInspection>('/datasets/inspect', {
    method: 'POST',
    body: form,
  })
}

export function uploadDataset(
  file: File,
  displayName: string,
  datasetType: DatasetInfo['dataset_type'],
) {
  const form = new FormData()
  form.append('file', file)
  form.append('display_name', displayName)
  form.append('dataset_type', datasetType)
  return request<DatasetUploadResult>('/datasets/upload', {
    method: 'POST',
    body: form,
  })
}

export function activateDataset(datasetId: string) {
  return request<DatasetSwitchResult>(
    `/datasets/${encodeURIComponent(datasetId)}/activate`,
    { method: 'POST' },
  )
}

export function deleteDataset(datasetId: string) {
  return request<void>(`/datasets/${encodeURIComponent(datasetId)}`, {
    method: 'DELETE',
  })
}

function today() {
  return new Date().toISOString().slice(0, 10)
}

async function downloadFile(path: string, filename: string) {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    let message = `Export failed with status ${response.status}`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) message = payload.detail
    } catch {
      // Keep the status message for non-JSON upstream failures.
    }
    throw new Error(message)
  }
  const blob = await response.blob()
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(href)
}

export function exportEntities(
  investigationId: string,
  format: 'csv' | 'json',
) {
  return downloadFile(
    `/exports/investigations/${encodeURIComponent(investigationId)}/entities?format=${format}`,
    `sentinel_entities_${investigationId}_${today()}.${format}`,
  )
}

export function exportInvestigation(
  investigationId: string,
  format: 'json' | 'md',
) {
  return downloadFile(
    `/exports/investigations/${encodeURIComponent(investigationId)}?format=${format}`,
    `investigation_${investigationId}.${format}`,
  )
}

export function exportTrace(investigationId: string, format: 'csv' | 'json') {
  return downloadFile(
    `/exports/investigations/${encodeURIComponent(investigationId)}/trace?format=${format}`,
    `trace_${investigationId}.${format}`,
  )
}

export function exportSar(
  entityId: string,
  investigationId: string,
  format: 'txt' | 'pdf',
) {
  return downloadFile(
    `/export/sar/${encodeURIComponent(entityId)}?format=${format}&investigation_id=${encodeURIComponent(investigationId)}`,
    `sar_draft_${entityId}.${format}`,
  )
}

export function exportModelCard(format: 'json' | 'md' | 'pdf') {
  return downloadFile(
    `/export/model-card?format=${format}`,
    `sentinel_model_card.${format}`,
  )
}

export function exportAudit(format: 'csv' | 'json') {
  return downloadFile(
    `/export/audit?format=${format}`,
    `sentinel_audit_${today()}.${format}`,
  )
}

function queryString(values: object) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value))
    }
  })
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

export function getCustomers(filters: CustomerFilters = {}) {
  return request<CustomerPage>(`/customers${queryString(filters)}`)
}

export function getCustomer(accountId: string) {
  return request<CustomerDetail>(
    `/customers/${encodeURIComponent(accountId)}`,
  )
}

export function getTransactions(filters: TransactionFilters = {}) {
  return request<TransactionPage>(`/transactions${queryString(filters)}`)
}

export function getTransactionPaymentFormats() {
  return request<{ items: string[] }>('/transactions/payment-formats')
}
