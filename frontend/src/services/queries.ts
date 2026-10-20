// TanStack Query hooks: one place for server-state keys, polling and invalidation.
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError, uploadWithProgress } from '@/lib/api'
import type {
  AnalyticsOverview,
  AppSettings,
  AuthConfig,
  CurrentUser,
  BenchmarkData,
  ConversationDetail,
  ConversationSummary,
  DocumentItem,
  DocumentList,
  Health,
  SettingsResponse,
  UploadResult,
} from '@/types/api'

export const keys = {
  authConfig: ['auth', 'config'] as const,
  me: ['auth', 'me'] as const,
  documents: ['documents'] as const,
  document: (id: string) => ['documents', id] as const,
  conversations: ['conversations'] as const,
  conversation: (id: string) => ['conversations', id] as const,
  health: ['health'] as const,
  settings: ['settings'] as const,
  overview: ['analytics', 'overview'] as const,
  benchmarks: ['analytics', 'benchmarks'] as const,
}

const isBusy = (d: DocumentItem) => d.status === 'queued' || d.status === 'processing'

export function useDocuments() {
  return useQuery({
    queryKey: keys.documents,
    queryFn: () => api.get<DocumentList>('/documents'),
    // Poll only while something is being processed; stop when everything settles.
    refetchInterval: (q) => (q.state.data?.items.some(isBusy) ? 800 : false),
    placeholderData: keepPreviousData,
  })
}

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: keys.document(id ?? ''),
    queryFn: () => api.get<DocumentItem>(`/documents/${id}`),
    enabled: !!id,
  })
}

export function useUploadDocuments() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ files, onProgress }: { files: File[]; onProgress?: (f: number) => void }) => {
      const form = new FormData()
      files.forEach((f) => form.append('files', f))
      return uploadWithProgress<UploadResult>('/documents/upload', form, onProgress ?? (() => {}))
    },
    onSettled: () => qc.invalidateQueries({ queryKey: keys.documents }),
  })
}

export function useDeleteDocument() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/documents/${id}`),
    onSuccess: (_d, id) => {
      qc.setQueryData<DocumentList>(keys.documents, (old) =>
        old ? { items: old.items.filter((d) => d.id !== id), total: old.total - 1 } : old,
      )
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.documents })
      qc.invalidateQueries({ queryKey: keys.overview })
    },
  })
}

export function useReindexDocument() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.post<DocumentItem>(`/documents/${id}/reindex`),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.documents }),
  })
}

export function useConversations() {
  return useQuery({ queryKey: keys.conversations, queryFn: () => api.get<ConversationSummary[]>('/conversations') })
}

export function useConversation(id: string | undefined) {
  return useQuery({
    queryKey: keys.conversation(id ?? ''),
    queryFn: () => api.get<ConversationDetail>(`/conversations/${id}`),
    enabled: !!id,
  })
}

export function useDeleteConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.delete(`/conversations/${id}`),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.conversations }),
  })
}

export function useFeedback(conversationId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ messageId, value }: { messageId: string; value: 1 | -1 | null }) =>
      api.put(`/conversations/${conversationId}/messages/${messageId}/feedback`, { value }),
    onSettled: () => qc.invalidateQueries({ queryKey: keys.conversation(conversationId) }),
  })
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: () => api.get<Health>('/health'),
    refetchInterval: (q) => (q.state.data && !q.state.data.models.llm.loaded && !q.state.data.models.llm.error ? 3000 : 15000),
  })
}

export function useSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: () => api.get<SettingsResponse>('/settings') })
}

export function useUpdateSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (patch: Partial<AppSettings>) => api.put<SettingsResponse>('/settings', patch),
    onSuccess: (data) => qc.setQueryData(keys.settings, data),
  })
}

export function useAnalyticsOverview() {
  return useQuery({ queryKey: keys.overview, queryFn: () => api.get<AnalyticsOverview>('/analytics/overview'), refetchInterval: 10000 })
}

export function useBenchmarks() {
  return useQuery({ queryKey: keys.benchmarks, queryFn: () => api.get<BenchmarkData>('/analytics/benchmarks'), staleTime: 60_000 })
}

// ------------------------------------------------------------------ accounts
export function useAuthConfig() {
  return useQuery({ queryKey: keys.authConfig, queryFn: () => api.get<AuthConfig>('/auth/config'), staleTime: Infinity })
}

/** The signed-in user; null when signed out (401). */
export function useMe(enabled = true) {
  return useQuery({
    queryKey: keys.me,
    enabled,
    staleTime: 60_000,
    queryFn: async () => {
      try {
        return await api.get<CurrentUser>('/auth/me')
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
  })
}

export function useAuthAction(action: 'login' | 'signup') {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; password: string }) => api.post<CurrentUser>(`/auth/${action}`, body),
    onSuccess: (user) => {
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })  // never show a previous user's data
      qc.setQueryData(keys.me, user)
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.post<void>('/auth/logout'),
    onSettled: () => {
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
      qc.setQueryData(keys.me, null)
    },
  })
}

export function useDeleteAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (password: string) => api.delete('/auth/me', { password }),
    onSuccess: () => {
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== 'auth' })
      qc.setQueryData(keys.me, null)
    },
  })
}
