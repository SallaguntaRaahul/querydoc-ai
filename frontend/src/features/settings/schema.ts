import { z } from 'zod'

const device = z.enum(['auto', 'cpu', 'mps', 'cuda'])

/** Mirrors SettingsModel in backend/app/schemas/api.py — the server re-validates. */
export const settingsSchema = z
  .object({
    embedding_model: z.string().min(1),
    llm_model: z.string().min(1),
    llm_device: device,
    reranker_device: device,
    chunk_size: z.number().int().min(200, 'At least 200 characters').max(2000, 'At most 2000 characters'),
    chunk_overlap: z.number().int().min(0, 'Cannot be negative').max(1000),
    top_k: z.number().int().min(1).max(10),
    fetch_k: z.number().int().min(5).max(100),
    use_hybrid: z.boolean(),
    use_rerank: z.boolean(),
    rerank_k: z.number().int().min(1).max(100),
    max_new_tokens: z.number().int().min(16, 'At least 16 tokens').max(1024, 'At most 1024 tokens'),
    temperature: z.number().min(0).max(1.5),
    theme: z.enum(['dark', 'light', 'system']),
    performance_mode: z.enum(['quality', 'balanced', 'speed']),
  })
  .superRefine((v, ctx) => {
    if (v.chunk_overlap > Math.floor(v.chunk_size / 2))
      ctx.addIssue({ code: 'custom', path: ['chunk_overlap'], message: 'Overlap must be at most half the chunk size' })
    if (v.fetch_k < v.top_k) ctx.addIssue({ code: 'custom', path: ['fetch_k'], message: 'Candidates must be ≥ top-k' })
    if (v.rerank_k < v.top_k) ctx.addIssue({ code: 'custom', path: ['rerank_k'], message: 'Rerank candidates must be ≥ top-k' })
  })

export type SettingsForm = z.infer<typeof settingsSchema>
