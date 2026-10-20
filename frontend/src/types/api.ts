// Types mirroring backend/app/schemas/api.py (QueryDoc AI v1 API).

export type DocumentStatus = 'queued' | 'processing' | 'ready' | 'failed'

export interface DocumentItem {
  id: string
  filename: string
  title: string
  size_bytes: number
  page_count: number
  chunk_count: number
  status: DocumentStatus
  stage: string
  progress: number
  error: string | null
  chunking: Record<string, unknown>
  timings_ms: Record<string, number>
  embedding_stats: Record<string, number>
  scanned_pages: number[]
  created_at: string
  updated_at: string
}

export interface DocumentList {
  items: DocumentItem[]
  total: number
}

export interface UploadResult {
  documents: DocumentItem[]
  errors: { filename: string; code: string; message: string }[]
}

export interface Citation {
  tag: string
  chunk_id: string
  doc_id: string
  source: string
  page_start: number
  page_end: number
  excerpt: string
  retrieval_score: number
  support: number
  method: 'model' | 'attributed' | string
}

export interface Source {
  rank: number
  chunk_id: string
  doc_id: string
  source: string
  page_start: number
  page_end: number
  score: number
  scores: Record<string, number>
  text: string
}

export type AnswerStatus =
  | 'verified'
  | 'partially_verified'
  | 'unverified'
  | 'insufficient_evidence'
  | 'retrieval_only'
  | 'cancelled'
  | 'error'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  status: AnswerStatus | string | null
  mode: string | null
  document_ids: string[]
  citations: Citation[]
  sources: Source[]
  notes: string[]
  timings_ms: Record<string, number>
  feedback: number | null
  created_at: string
}

export interface ConversationSummary {
  id: string
  title: string
  document_ids: string[]
  message_count: number
  last_message: string | null
  created_at: string
  updated_at: string
}

export interface ConversationDetail {
  id: string
  title: string
  document_ids: string[]
  created_at: string
  updated_at: string
  messages: Message[]
}

export interface ChatRequest {
  message: string
  conversation_id?: string | null
  document_ids?: string[] | null
  regenerate_of?: string | null
  top_k?: number
  use_rerank?: boolean
  max_new_tokens?: number
  temperature?: number
}

export type Device = 'auto' | 'cpu' | 'mps' | 'cuda'

export interface AppSettings {
  embedding_model: string
  llm_model: string
  llm_device: Device
  reranker_device: Device
  chunk_size: number
  chunk_overlap: number
  top_k: number
  fetch_k: number
  use_hybrid: boolean
  use_rerank: boolean
  rerank_k: number
  max_new_tokens: number
  temperature: number
  theme: 'dark' | 'light' | 'system'
  performance_mode: 'quality' | 'balanced' | 'speed'
  enable_ocr: boolean
}

export interface SettingsResponse {
  settings: AppSettings
  options: {
    embedding_models: string[]
    llm_models: { id: string; label: string; params: string; approx_memory_gb: number; license: string; note: string }[]
    devices: Device[]
    embedding_model_locked: boolean
    embedding_model_locked_reason: string | null
    ocr_available: boolean
    can_edit: boolean
  }
  restart_required: string[]
}

export interface AuthConfig {
  auth_enabled: boolean
  signup_enabled: boolean
}

export interface CurrentUser {
  id: string
  email: string
  is_admin: boolean
  auth_enabled: boolean
}

export interface ModelState {
  model: string
  device: string
  loaded: boolean
  error?: string | null
  dim?: number
}

export interface Health {
  status: 'ok' | 'degraded'
  version: string
  models: { embedder: ModelState; reranker: ModelState; llm: ModelState }
  documents: number
  index_vectors: number
  ingestion_queue: number
}

export interface LatencySummary {
  count: number
  p50: number | null
  p95: number | null
  mean: number | null
}

export interface AnalyticsOverview {
  source: 'runtime'
  documents: { total: number; ready: number; processing: number; failed: number; pages: number; chunks: number; bytes: number }
  conversations: number
  index: { vectors: number; approx_bytes: number; type: string; embedding_model: string; dim: number }
  queries: {
    total: number
    by_mode: Record<string, number>
    retrieval_ms: LatencySummary
    generation_ms: LatencySummary
    ttft_ms: LatencySummary
    total_ms: LatencySummary
    recent: { at: string; mode: string; retrieval_ms: number | null; generation_ms: number | null; total_ms: number | null }[]
  }
  ingestion: {
    document_id: string
    filename: string
    pages: number
    chunks: number
    total_ms: number | null
    timings_ms: Record<string, number>
    chunks_per_second: number | null
  }[]
  process: { rss_mb: number; peak_rss_mb: number; note: string }
  models: Health['models']
}

export interface BenchmarkMeta {
  command: string | null
  timestamp: string | null
  git_commit: string | null
  hardware: string
  swap_used_gb: number | null
}

export interface MetricSet {
  'hit@5': number
  'precision@5': number
  'recall@5': number
  mrr: number
  'ndcg@5': number
  latency_ms: number
}

export interface BenchmarkData {
  source: 'benchmark'
  results_dir: string
  relevance?: {
    meta: BenchmarkMeta
    primary_metric: string
    baseline: string
    optimized: string
    selection_rule: string | null
    comparison: Record<'test' | 'dev' | 'all', {
      baseline: MetricSet
      optimized: MetricSet
      relative_improvement_pct: Record<string, number>
      absolute_improvement_pts: Record<string, number>
      primary_metric_ci95_pct: [number, number]
    }>
    sweep: { chunking: string; retrieval: string; ndcg_all: number; ndcg_dev: number; ndcg_test: number; hit_all: number; latency_ms: number }[]
  }
  retrieval_latency?: LatencyBench
  retrieval_latency_cpu?: LatencyBench
  embeddings?: {
    meta: BenchmarkMeta
    document: string
    comparisons: Record<string, { peak_rss_reduction_pct: number | null; working_set_reduction_pct: number | null; throughput_change_pct: number | null }>
    rows: { strategy: string; peak_rss_mb: number; working_set_mb: number; chunks_per_second: number; chunks: number }[]
  }
  concurrency?: {
    meta: BenchmarkMeta
    index: { documents: number; chunks: number; pages: number }
    generation_controls: Record<string, unknown>
    retrieval: { users: number; requests: number; errors: number; rps: number; p50_ms: number; p95_ms: number }[]
    generation: { users: number; requests: number; ok: number; errors: Record<string, number>; rps: number; p50_ms: number; p95_ms: number }[]
  }
  generation?: {
    meta: BenchmarkMeta
    models: {
      model: string
      accuracy: number
      cited_rate: number
      model_tagged_rate: number | null
      on_evidence_rate: number
      declined_unanswerable: number | null
      e2e_p50_ms: number
      e2e_p95_ms: number
      ttft_p50_ms: number
      tokens_per_second: number
    }[]
  }
  ingestion?: { meta: BenchmarkMeta; rows: ({ document: string; pages: number; chunks: number; total_ms_mean: number; pages_per_second: number } & Record<string, number | string>)[] }
  api_e2e?: Record<string, unknown>
}

export interface LatencyBench {
  meta: BenchmarkMeta
  reranker_device: string
  rows: { dataset: string; config: string; pages: number; chunks: number; p50_ms: number; p95_ms: number; p99_ms: number; cold_ms: number }[]
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: unknown }
}
