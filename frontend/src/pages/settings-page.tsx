import { zodResolver } from '@hookform/resolvers/zod'
import { Info, Loader2, Lock, RotateCcw, Save } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'
import { Controller, useForm, type FieldPath } from 'react-hook-form'
import { toast } from 'sonner'

import { PageHeader } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { settingsSchema, type SettingsForm } from '@/features/settings/schema'
import { useTheme } from '@/hooks/use-theme'
import { ApiError } from '@/lib/api'
import { useSettings, useUpdateSettings } from '@/services/queries'

function Field({ id, label, hint, error, children }: { id: string; label: string; hint?: ReactNode; error?: string; children: ReactNode }) {
  return (
    <div className="grid min-w-0 content-start gap-1.5">
      <Label htmlFor={id} className="text-sm">{label}</Label>
      {children}
      {error ? <p id={`${id}-error`} role="alert" className="text-xs text-destructive">{error}</p> : hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export default function SettingsPage() {
  const { data, isLoading } = useSettings()
  const update = useUpdateSettings()
  const { setPreference } = useTheme()
  const form = useForm<SettingsForm>({ resolver: zodResolver(settingsSchema), mode: 'onChange' })
  const { register, control, handleSubmit, reset, formState, watch } = form

  useEffect(() => {
    if (data) reset(data.settings)
  }, [data, reset])

  const onSubmit = async (values: SettingsForm) => {
    try {
      const res = await update.mutateAsync(values)
      reset(res.settings)
      setPreference(res.settings.theme)
      toast.success('Settings saved')
      res.restart_required.forEach((n) => toast.info(n))
    } catch (e) {
      if (e instanceof ApiError && Array.isArray(e.details)) {
        for (const d of e.details as { loc: (string | number)[]; msg: string }[]) {
          const field = d.loc.at(-1)
          if (typeof field === 'string') form.setError(field as FieldPath<SettingsForm>, { message: d.msg })
        }
      }
      toast.error(e instanceof ApiError ? e.message : 'Could not save settings')
    }
  }

  if (isLoading || !data) {
    return <div className="mx-auto max-w-4xl space-y-4 p-8">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-48" />)}</div>
  }
  const { options } = data
  const err = formState.errors
  const num = (name: FieldPath<SettingsForm>) => register(name, { valueAsNumber: true })
  const llm = options.llm_models.find((m) => m.id === watch('llm_model'))

  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <form onSubmit={handleSubmit(onSubmit)} className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-8 sm:py-8" noValidate aria-label="Settings">
        <PageHeader
          title="Settings"
          description="Models, retrieval and generation. Changes apply immediately; chunking applies to new uploads and re-indexed documents."
          actions={
            <>
              <Button type="button" variant="ghost" size="sm" disabled={!formState.isDirty} onClick={() => reset(data.settings)}>
                <RotateCcw className="size-4" /> Reset
              </Button>
              <Button type="submit" size="sm" disabled={!formState.isDirty || !formState.isValid || update.isPending} data-testid="save-settings">
                {update.isPending ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />} Save changes
              </Button>
            </>
          }
        />
        <div className="space-y-5">
          <Card>
            <CardHeader><CardTitle className="text-base">Appearance & performance</CardTitle><CardDescription>Theme and a retrieval preset.</CardDescription></CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              <Field id="theme" label="Theme">
                <Controller control={control} name="theme" render={({ field }) => (
                  <ToggleGroup id="theme" type="single" variant="outline" value={field.value} onValueChange={(v) => { if (v) { field.onChange(v); setPreference(v as SettingsForm['theme']) } }} aria-label="Theme">
                    <ToggleGroupItem value="dark">Dark</ToggleGroupItem>
                    <ToggleGroupItem value="light">Light</ToggleGroupItem>
                    <ToggleGroupItem value="system">System</ToggleGroupItem>
                  </ToggleGroup>
                )} />
              </Field>
              <Field id="performance_mode" label="Performance preset" hint="Quality reranks 30 candidates, balanced 20, speed skips the reranker.">
                <Controller control={control} name="performance_mode" render={({ field }) => (
                  <ToggleGroup id="performance_mode" type="single" variant="outline" value={field.value} aria-label="Performance preset"
                    onValueChange={(v) => {
                      if (!v) return
                      field.onChange(v)
                      if (v === 'speed') form.setValue('use_rerank', false, { shouldDirty: true, shouldValidate: true })
                      else {
                        form.setValue('use_rerank', true, { shouldDirty: true })
                        form.setValue('rerank_k', v === 'quality' ? 30 : 20, { shouldDirty: true, shouldValidate: true })
                      }
                    }}>
                    <ToggleGroupItem value="quality">Quality</ToggleGroupItem>
                    <ToggleGroupItem value="balanced">Balanced</ToggleGroupItem>
                    <ToggleGroupItem value="speed">Speed</ToggleGroupItem>
                  </ToggleGroup>
                )} />
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Models & devices</CardTitle><CardDescription>All models run locally. Unavailable devices are hidden.</CardDescription></CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              <Field id="llm_model" label="Language model" hint={llm ? `${llm.params} · ~${llm.approx_memory_gb} GB · ${llm.license} · ${llm.note}` : undefined}>
                <Controller control={control} name="llm_model" render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="llm_model" className="w-full min-w-0 [&>span]:truncate"><SelectValue /></SelectTrigger>
                    <SelectContent>{options.llm_models.map((m) => <SelectItem key={m.id} value={m.id}>{m.label}</SelectItem>)}</SelectContent>
                  </Select>
                )} />
              </Field>
              <Field id="embedding_model" label="Embedding model"
                hint={options.embedding_model_locked ? <span className="inline-flex items-center gap-1"><Lock className="size-3" aria-hidden /> {options.embedding_model_locked_reason}</span> : 'Changing it creates a new, empty index.'}>
                <Controller control={control} name="embedding_model" render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange} disabled={options.embedding_model_locked}>
                    <SelectTrigger id="embedding_model" className="w-full min-w-0 [&>span]:truncate"><SelectValue /></SelectTrigger>
                    <SelectContent>{options.embedding_models.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                  </Select>
                )} />
              </Field>
              {(['llm_device', 'reranker_device'] as const).map((name) => (
                <Field key={name} id={name} label={name === 'llm_device' ? 'Language model device' : 'Reranker device'}
                  hint={name === 'reranker_device' ? 'Measured: GPU reranking kept p95 ≤ 129 ms; CPU only was ~550 ms on real PDFs.' : 'auto picks CUDA, then Apple GPU (MPS), then CPU.'}>
                  <Controller control={control} name={name} render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger id={name} className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>{options.devices.map((d) => <SelectItem key={d} value={d}>{d === 'mps' ? 'mps (Apple GPU)' : d}</SelectItem>)}</SelectContent>
                    </Select>
                  )} />
                </Field>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Chunking</CardTitle><CardDescription>Applies to new uploads. Re-index a document from the library to apply changes to it.</CardDescription></CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              <Field id="chunk_size" label="Chunk size (characters)" error={err.chunk_size?.message} hint="Benchmarked best: 1000">
                <Input id="chunk_size" type="number" inputMode="numeric" aria-invalid={!!err.chunk_size} {...num('chunk_size')} />
              </Field>
              <Field id="chunk_overlap" label="Chunk overlap (characters)" error={err.chunk_overlap?.message} hint="Benchmarked best: 200 (at most half the chunk size)">
                <Input id="chunk_overlap" type="number" inputMode="numeric" aria-invalid={!!err.chunk_overlap} {...num('chunk_overlap')} />
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Retrieval</CardTitle></CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              <Field id="top_k" label={`Passages given to the model (top-k): ${watch('top_k') ?? ''}`} error={err.top_k?.message}>
                <Controller control={control} name="top_k" render={({ field }) => (
                  <Slider id="top_k" min={1} max={10} step={1} value={[field.value ?? 5]} onValueChange={([v]) => field.onChange(v)} aria-label="Top-k" />
                )} />
              </Field>
              <Field id="fetch_k" label="Candidates per retriever" error={err.fetch_k?.message} hint="Dense and BM25 each return this many before fusion.">
                <Input id="fetch_k" type="number" aria-invalid={!!err.fetch_k} {...num('fetch_k')} />
              </Field>
              <div className="flex items-center justify-between gap-4 rounded-lg border p-3">
                <div>
                  <Label htmlFor="use_hybrid">Hybrid search (BM25 + dense)</Label>
                  <p className="text-xs text-muted-foreground">Catches exact identifiers like “AAL3”.</p>
                </div>
                <Controller control={control} name="use_hybrid" render={({ field }) => <Switch id="use_hybrid" checked={field.value} onCheckedChange={field.onChange} />} />
              </div>
              <div className="flex items-center justify-between gap-4 rounded-lg border p-3">
                <div>
                  <Label htmlFor="use_rerank">Cross-encoder reranking</Label>
                  <p className="text-xs text-muted-foreground">Largest measured quality gain (+20 nDCG points).</p>
                </div>
                <Controller control={control} name="use_rerank" render={({ field }) => <Switch id="use_rerank" checked={field.value} onCheckedChange={field.onChange} />} />
              </div>
              <Field id="rerank_k" label="Rerank candidates" error={err.rerank_k?.message} hint="Cost grows linearly with this number.">
                <Input id="rerank_k" type="number" aria-invalid={!!err.rerank_k} disabled={!watch('use_rerank')} {...num('rerank_k')} />
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base">Generation</CardTitle></CardHeader>
            <CardContent className="grid gap-5 sm:grid-cols-2">
              <Field id="max_new_tokens" label="Maximum answer tokens" error={err.max_new_tokens?.message} hint="The main driver of answer latency.">
                <Input id="max_new_tokens" type="number" aria-invalid={!!err.max_new_tokens} {...num('max_new_tokens')} />
              </Field>
              <Field id="temperature" label={`Temperature: ${Number(watch('temperature') ?? 0).toFixed(2)}`} error={err.temperature?.message} hint="0 = deterministic (recommended for grounded answers).">
                <Controller control={control} name="temperature" render={({ field }) => (
                  <Slider id="temperature" min={0} max={1.5} step={0.05} value={[field.value ?? 0]} onValueChange={([v]) => field.onChange(v)} aria-label="Temperature" />
                )} />
              </Field>
            </CardContent>
          </Card>

          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Local single-user mode: there is no authentication. Do not expose this server to a network you do not trust.
          </p>
        </div>
      </form>
    </div>
  )
}
