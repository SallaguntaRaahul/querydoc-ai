import { Activity, FlaskConical } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { EmptyState, PageHeader } from '@/components/common'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { ChartCard, ChartTooltipBox, Legend, MetricCard, useChartColors } from '@/features/analytics/charts'
import { formatBytes, formatMs, formatNumber, formatPct } from '@/lib/format'
import { useAnalyticsOverview, useBenchmarks } from '@/services/queries'

const METRICS = ['hit@5', 'precision@5', 'recall@5', 'mrr', 'ndcg@5'] as const

function SectionTitle({ icon: Icon, title, badge, description }: { icon: typeof Activity; title: string; badge: string; description: string }) {
  return (
    <div className="mb-4 mt-2">
      <div className="flex items-center gap-2">
        <Icon className="size-4 text-primary" aria-hidden />
        <h2 className="text-base font-semibold">{title}</h2>
        <Badge variant="secondary" className="text-[10px]">{badge}</Badge>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{description}</p>
    </div>
  )
}

function axisProps(color: string) {
  return { stroke: color, tick: { fill: color, fontSize: 11 }, tickLine: false, axisLine: false }
}

function LiveTelemetry() {
  const { data, isLoading } = useAnalyticsOverview()
  const c = useChartColors()
  if (isLoading || !data) return <div className="grid gap-3 sm:grid-cols-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20" />)}</div>
  const q = data.queries
  const recent = q.recent.map((r, i) => ({ i: i + 1, retrieval: r.retrieval_ms, generation: r.generation_ms, total: r.total_ms }))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard label="Retrieval latency p50 / p95" value={`${formatMs(q.retrieval_ms.p50)} / ${formatMs(q.retrieval_ms.p95)}`} sub={`${q.retrieval_ms.count} queries`} />
        <MetricCard label="Generation latency p50 / p95" value={`${formatMs(q.generation_ms.p50)} / ${formatMs(q.generation_ms.p95)}`} sub={`time to first token p50 ${formatMs(q.ttft_ms.p50)}`} />
        <MetricCard label="Total response p50 / p95" value={`${formatMs(q.total_ms.p50)} / ${formatMs(q.total_ms.p95)}`} sub={`${q.total_ms.count} generated answers`} />
        <MetricCard label="Index" value={`${formatNumber(data.index.vectors)} vectors`} sub={`${formatBytes(data.index.approx_bytes)} · ${data.index.type} · ${data.index.dim}-d`} />
        <MetricCard label="Process memory (RSS)" value={`${formatNumber(Math.round(data.process.rss_mb))} MB`} sub={`peak ${formatNumber(Math.round(data.process.peak_rss_mb))} MB`} />
        <MetricCard label="Documents ready" value={`${data.documents.ready} / ${data.documents.total}`} sub={`${formatNumber(data.documents.pages)} pages · ${formatNumber(data.documents.chunks)} chunks`} />
        <MetricCard label="Queries by outcome" value={formatNumber(q.total)} sub={Object.entries(q.by_mode).map(([k, v]) => `${k.replace('_', ' ')} ${v}`).join(' · ') || 'none yet'} />
        <MetricCard label="Conversations" value={formatNumber(data.conversations)} />
      </div>
      {recent.length > 1 ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartCard title="Retrieval latency, recent queries" description="Milliseconds per query, oldest → newest (this installation).">
            <div className="h-48"><ResponsiveContainer>
              <LineChart data={recent} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="i" {...axisProps(c.axis)} />
                <YAxis {...axisProps(c.axis)} width={44} />
                <RTooltip content={<ChartTooltipBox unit=" ms" />} cursor={{ stroke: c.grid }} />
                <Line isAnimationActive={false} type="linear" dataKey="retrieval" name="retrieval" stroke={c.c1} strokeWidth={2} dot={{ r: 2.5 }} activeDot={{ r: 4 }} connectNulls />
              </LineChart>
            </ResponsiveContainer></div>
          </ChartCard>
          <ChartCard title="Response latency, recent answers" description="Generation vs total milliseconds per answer (this installation).">
            <Legend items={[{ label: 'generation', color: c.c2 }, { label: 'total', color: c.c3 }]} />
            <div className="h-40"><ResponsiveContainer>
              <LineChart data={recent} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="i" {...axisProps(c.axis)} />
                <YAxis {...axisProps(c.axis)} width={48} />
                <RTooltip content={<ChartTooltipBox unit=" ms" />} cursor={{ stroke: c.grid }} />
                <Line isAnimationActive={false} type="linear" dataKey="generation" name="generation" stroke={c.c2} strokeWidth={2} dot={{ r: 2.5 }} connectNulls />
                <Line isAnimationActive={false} type="linear" dataKey="total" name="total" stroke={c.c3} strokeWidth={2} dot={{ r: 2.5 }} connectNulls />
              </LineChart>
            </ResponsiveContainer></div>
          </ChartCard>
        </div>
      ) : (
        <p className="rounded-lg border border-dashed p-4 text-center text-xs text-muted-foreground">Ask a few questions to see live latency charts.</p>
      )}
      {data.ingestion.length > 0 && (
        <ChartCard title="Document processing" description="Measured when each document was indexed on this machine.">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow><TableHead>Document</TableHead><TableHead className="text-right">Pages</TableHead><TableHead className="text-right">Chunks</TableHead><TableHead className="text-right">Extract</TableHead><TableHead className="text-right">Embed</TableHead><TableHead className="text-right">Total</TableHead><TableHead className="text-right">Chunks/s</TableHead></TableRow></TableHeader>
              <TableBody>
                {data.ingestion.map((d) => (
                  <TableRow key={d.document_id}>
                    <TableCell className="max-w-[240px] truncate" title={d.filename}>{d.filename}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.pages}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.chunks}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatMs(d.timings_ms.extract)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatMs(d.timings_ms.embed)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatMs(d.total_ms)}</TableCell>
                    <TableCell className="text-right tabular-nums">{d.chunks_per_second ? d.chunks_per_second.toFixed(0) : '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </ChartCard>
      )}
      <p className="text-[11px] text-muted-foreground">{data.process.note}</p>
    </div>
  )
}

function Benchmarks() {
  const { data, isLoading } = useBenchmarks()
  const c = useChartColors()
  const [split, setSplit] = useState<'test' | 'dev' | 'all'>('test')
  const [device, setDevice] = useState<'gpu' | 'cpu'>('gpu')
  const [sweepView, setSweepView] = useState<'hybrid+rerank@20' | 'dense' | 'hybrid'>('hybrid+rerank@20')

  const latency = device === 'gpu' ? data?.retrieval_latency : data?.retrieval_latency_cpu
  const latencyRows = useMemo(() => {
    if (!latency) return []
    const byDs = new Map<string, Record<string, number | string>>()
    for (const r of latency.rows) {
      const row = byDs.get(r.dataset) ?? { dataset: r.dataset.replace('synthetic_', 'syn ').replace('nist_', ''), pages: r.pages }
      row[`${r.config}_p50`] = r.p50_ms
      row[`${r.config}_p95`] = r.p95_ms
      byDs.set(r.dataset, row)
    }
    return [...byDs.values()]
  }, [latency])

  if (isLoading) return <Skeleton className="h-64" />
  if (!data || Object.keys(data).length <= 2) {
    return <EmptyState icon={FlaskConical} title="No benchmark results found" description="Run python benchmarks/run_all_benchmarks.py to record results in results/." />
  }
  const rel = data.relevance
  const cmp = rel?.comparison[split]
  const relBars = cmp ? METRICS.map((m) => ({ metric: m, baseline: cmp.baseline[m], optimized: cmp.optimized[m] })) : []
  const sweep = rel ? rel.sweep.filter((s) => s.retrieval === sweepView).sort((a, b) => b.ndcg_all - a.ndcg_all) : []
  const mem = data.embeddings

  return (
    <div className="space-y-4">
      {rel && cmp && (
        <div className="grid gap-4 lg:grid-cols-5">
          <ChartCard className="lg:col-span-3" title="Retrieval quality: baseline vs optimized" meta={rel.meta}
            description={<>Baseline <code className="font-mono">{rel.baseline}</code> vs <code className="font-mono">{rel.optimized}</code> (selected automatically on the dev split).</>}>
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <ToggleGroup type="single" size="sm" variant="outline" value={split} onValueChange={(v) => v && setSplit(v as typeof split)} aria-label="Question split">
                <ToggleGroupItem value="test">Held-out test</ToggleGroupItem>
                <ToggleGroupItem value="dev">Dev</ToggleGroupItem>
                <ToggleGroupItem value="all">All 63</ToggleGroupItem>
              </ToggleGroup>
              <Legend items={[{ label: 'baseline', color: c.c1 }, { label: 'optimized', color: c.c2 }]} />
            </div>
            <div className="h-56"><ResponsiveContainer>
              <BarChart data={relBars} margin={{ top: 4, right: 4, left: -16, bottom: 0 }} barGap={2}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="metric" {...axisProps(c.axis)} />
                <YAxis domain={[0, 1]} {...axisProps(c.axis)} />
                <RTooltip content={<ChartTooltipBox />} cursor={{ fill: c.grid, opacity: 0.4 }} />
                <Bar isAnimationActive={false} dataKey="baseline" name="baseline" fill={c.c1} radius={[4, 4, 0, 0]} maxBarSize={28} />
                <Bar isAnimationActive={false} dataKey="optimized" name="optimized" fill={c.c2} radius={[4, 4, 0, 0]} maxBarSize={28} />
              </BarChart>
            </ResponsiveContainer></div>
          </ChartCard>
          <div className="grid gap-3 lg:col-span-2">
            <MetricCard label={`Context relevance (nDCG@5), ${split === 'all' ? 'all questions' : `${split} split`}`}
              value={formatPct(cmp.relative_improvement_pct['ndcg@5'])}
              sub={<>{cmp.baseline['ndcg@5'].toFixed(3)} → {cmp.optimized['ndcg@5'].toFixed(3)} · 95% CI {formatPct(cmp.primary_metric_ci95_pct[0], 0)} … {formatPct(cmp.primary_metric_ci95_pct[1], 0)}</>}
              tone={cmp.relative_improvement_pct['ndcg@5'] >= 40 ? 'good' : 'neutral'} />
            <MetricCard label="Hit@5" value={`${(cmp.baseline['hit@5'] * 100).toFixed(0)}% → ${(cmp.optimized['hit@5'] * 100).toFixed(0)}%`} sub={`+${cmp.absolute_improvement_pts['hit@5'].toFixed(1)} percentage points`} />
            <MetricCard label="Mean retrieval time in sweep" value={`${formatMs(cmp.baseline.latency_ms)} → ${formatMs(cmp.optimized.latency_ms)}`} sub={rel.selection_rule ?? undefined} />
          </div>
        </div>
      )}

      {rel && (
        <ChartCard title="Chunking sweep" meta={rel.meta} description="nDCG@5 on all 63 questions for every chunking strategy, for the chosen retrieval pipeline.">
          <div className="mb-3">
            <ToggleGroup type="single" size="sm" variant="outline" value={sweepView} onValueChange={(v) => v && setSweepView(v as typeof sweepView)} aria-label="Retrieval pipeline">
              <ToggleGroupItem value="dense">Dense</ToggleGroupItem>
              <ToggleGroupItem value="hybrid">Hybrid</ToggleGroupItem>
              <ToggleGroupItem value="hybrid+rerank@20">Hybrid + rerank</ToggleGroupItem>
            </ToggleGroup>
          </div>
          <div style={{ height: Math.max(160, sweep.length * 30) }}><ResponsiveContainer>
            <BarChart data={sweep} layout="vertical" margin={{ top: 0, right: 24, left: 40, bottom: 0 }}>
              <CartesianGrid stroke={c.grid} horizontal={false} />
              <XAxis type="number" domain={[0, 1]} {...axisProps(c.axis)} />
              <YAxis type="category" dataKey="chunking" width={110} interval={0} {...axisProps(c.axis)} />
              <RTooltip content={<ChartTooltipBox />} cursor={{ fill: c.grid, opacity: 0.4 }} />
              <Bar isAnimationActive={false} dataKey="ndcg_all" name="nDCG@5" fill={c.c1} radius={[0, 4, 4, 0]} maxBarSize={16}
                label={{ position: 'right', fill: c.axis, fontSize: 10, formatter: (v: unknown) => Number(v).toFixed(3) }} />
            </BarChart>
          </ResponsiveContainer></div>
        </ChartCard>
      )}

      {latency && (
        <ChartCard title="Retrieval latency by document size" meta={latency.meta}
          description="Warm retrieval, 200 queries × 3 trials per cell. Excludes LLM generation. Dashed line: 300 ms target.">
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <ToggleGroup type="single" size="sm" variant="outline" value={device} onValueChange={(v) => v && setDevice(v as typeof device)} aria-label="Reranker device">
              <ToggleGroupItem value="gpu" disabled={!data.retrieval_latency}>Reranker on GPU (MPS)</ToggleGroupItem>
              <ToggleGroupItem value="cpu" disabled={!data.retrieval_latency_cpu}>CPU only</ToggleGroupItem>
            </ToggleGroup>
            <Legend items={[{ label: 'baseline dense p95', color: c.c1 }, { label: 'optimized p50', color: c.c3 }, { label: 'optimized p95', color: c.c2 }]} />
          </div>
          <div className="h-64"><ResponsiveContainer>
            <BarChart data={latencyRows} margin={{ top: 8, right: 8, left: -8, bottom: 0 }} barGap={2}>
              <CartesianGrid stroke={c.grid} vertical={false} />
              <XAxis dataKey="dataset" {...axisProps(c.axis)} interval={0} />
              <YAxis {...axisProps(c.axis)} width={44} />
              <RTooltip content={<ChartTooltipBox unit=" ms" />} cursor={{ fill: c.grid, opacity: 0.4 }} />
              <ReferenceLine y={300} stroke={c.axis} strokeDasharray="5 4" />
              <Bar isAnimationActive={false} dataKey="baseline_dense_p95" name="baseline dense p95" fill={c.c1} radius={[4, 4, 0, 0]} maxBarSize={22} />
              <Bar isAnimationActive={false} dataKey="optimized_p50" name="optimized p50" fill={c.c3} radius={[4, 4, 0, 0]} maxBarSize={22} />
              <Bar isAnimationActive={false} dataKey="optimized_p95" name="optimized p95" fill={c.c2} radius={[4, 4, 0, 0]} maxBarSize={22} />
            </BarChart>
          </ResponsiveContainer></div>
        </ChartCard>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {mem && (
          <ChartCard title="Embedding peak memory" meta={mem.meta} description={`Peak process RSS while embedding ${mem.document} (${mem.rows[0]?.chunks} chunks), CPU, fresh process per run.`}>
            <div className="h-60"><ResponsiveContainer>
              <BarChart data={mem.rows} margin={{ top: 4, right: 4, left: -4, bottom: 24 }}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="strategy" {...axisProps(c.axis)} angle={-30} textAnchor="end" interval={0} height={40} />
                <YAxis {...axisProps(c.axis)} width={48} />
                <RTooltip content={<ChartTooltipBox unit=" MB" />} cursor={{ fill: c.grid, opacity: 0.4 }} />
                <Bar isAnimationActive={false} dataKey="peak_rss_mb" name="peak RSS" fill={c.c1} radius={[4, 4, 0, 0]} maxBarSize={22} />
              </BarChart>
            </ResponsiveContainer></div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[11px]">
              {Object.entries(mem.comparisons).slice(0, 3).map(([k, v]) => (
                <div key={k} className="rounded-md bg-muted/60 px-2 py-1.5">
                  <div className="font-semibold tabular-nums">{v.peak_rss_reduction_pct != null ? `−${v.peak_rss_reduction_pct.toFixed(1)}%` : '—'}</div>
                  <div className="text-muted-foreground">{k.replace('_vs_streaming_32', '').replace('_', ' ')} → streaming 32</div>
                </div>
              ))}
            </div>
          </ChartCard>
        )}
        {data.concurrency && (
          <ChartCard title="Concurrent retrieval" meta={data.concurrency.meta}
            description={`Closed-loop users on one shared service (${data.concurrency.index.documents} documents, ${formatNumber(data.concurrency.index.chunks)} chunks). Errors: ${data.concurrency.retrieval.reduce((a, r) => a + r.errors, 0)}.`}>
            <Legend items={[{ label: 'p50', color: c.c3 }, { label: 'p95', color: c.c2 }]} />
            <div className="h-44"><ResponsiveContainer>
              <LineChart data={data.concurrency.retrieval} margin={{ top: 8, right: 8, left: -4, bottom: 0 }}>
                <CartesianGrid stroke={c.grid} vertical={false} />
                <XAxis dataKey="users" {...axisProps(c.axis)} />
                <YAxis {...axisProps(c.axis)} width={48} />
                <RTooltip content={<ChartTooltipBox unit=" ms" />} cursor={{ stroke: c.grid }} />
                <Line isAnimationActive={false} dataKey="p50_ms" name="p50" stroke={c.c3} strokeWidth={2} dot={{ r: 3 }} />
                <Line isAnimationActive={false} dataKey="p95_ms" name="p95" stroke={c.c2} strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer></div>
            <p className="mt-2 text-[11px] text-muted-foreground">Throughput: {data.concurrency.retrieval.map((r) => `${r.users}u ${r.rps.toFixed(1)}/s`).join(' · ')} — flat because the single reranker serialises requests.</p>
          </ChartCard>
        )}
      </div>

      {data.generation && (
        <ChartCard title="Local generation" meta={data.generation.meta} description="Held-out questions over the NIST index. Accuracy is keyword-based.">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader><TableRow><TableHead>Model</TableHead><TableHead className="text-right">Accuracy</TableHead><TableHead className="text-right">Cited</TableHead><TableHead className="text-right">Model-tagged</TableHead><TableHead className="text-right">Declined unanswerable</TableHead><TableHead className="text-right">E2E p50 / p95</TableHead><TableHead className="text-right">TTFT p50</TableHead><TableHead className="text-right">Tok/s</TableHead></TableRow></TableHeader>
              <TableBody>
                {data.generation.models.map((m) => (
                  <TableRow key={m.model}>
                    <TableCell className="font-medium">{m.model.split('/').pop()}</TableCell>
                    <TableCell className="text-right tabular-nums">{(m.accuracy * 100).toFixed(0)}%</TableCell>
                    <TableCell className="text-right tabular-nums">{(m.cited_rate * 100).toFixed(0)}%</TableCell>
                    <TableCell className="text-right tabular-nums">{m.model_tagged_rate != null ? `${(m.model_tagged_rate * 100).toFixed(0)}%` : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{m.declined_unanswerable != null ? `${(m.declined_unanswerable * 100).toFixed(0)}%` : '—'}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatMs(m.e2e_p50_ms)} / {formatMs(m.e2e_p95_ms)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatMs(m.ttft_p50_ms)}</TableCell>
                    <TableCell className="text-right tabular-nums">{m.tokens_per_second.toFixed(1)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </ChartCard>
      )}
    </div>
  )
}

export default function AnalyticsPage() {
  const [view, setView] = useState<'all' | 'live' | 'bench'>('all')
  return (
    <div className="scrollbar-thin h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-8 sm:py-8">
        <PageHeader
          title="RAG analytics"
          description="Live telemetry from this installation, and recorded benchmark evidence. The two are never mixed."
          actions={
            <Select value={view} onValueChange={(v) => setView(v as typeof view)}>
              <SelectTrigger size="sm" className="w-48" aria-label="Show"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Live + benchmarks</SelectItem>
                <SelectItem value="live">Live telemetry only</SelectItem>
                <SelectItem value="bench">Benchmarks only</SelectItem>
              </SelectContent>
            </Select>
          }
        />
        {view !== 'bench' && (
          <section aria-labelledby="live" className="mb-10">
            <SectionTitle icon={Activity} title="Live telemetry" badge="runtime" description="Recorded by this server for every question asked and every document indexed." />
            <LiveTelemetry />
          </section>
        )}
        {view !== 'live' && (
          <section aria-labelledby="bench">
            <SectionTitle icon={FlaskConical} title="Benchmark evidence" badge="results/" description="Read from the benchmark result files. Hover the info marker on a card for the command, date and commit." />
            <Benchmarks />
          </section>
        )}
      </div>
    </div>
  )
}
