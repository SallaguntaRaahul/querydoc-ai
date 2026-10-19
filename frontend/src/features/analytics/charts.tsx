import { Info } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useTheme } from '@/hooks/use-theme'
import type { BenchmarkMeta } from '@/types/api'

export interface ChartColors {
  c1: string
  c2: string
  c3: string
  c4: string
  c5: string
  grid: string
  axis: string
  text: string
  card: string
}

/** Resolve chart tokens to concrete colours (SVG presentation attributes cannot use CSS variables). */
export function useChartColors(): ChartColors {
  const { resolved } = useTheme()
  const read = (): ChartColors => {
    const cs = getComputedStyle(document.documentElement)
    const v = (n: string, fb: string) => cs.getPropertyValue(n).trim() || fb
    return {
      c1: v('--chart-1', '#2a78d6'), c2: v('--chart-2', '#eb6834'), c3: v('--chart-3', '#1baf7a'),
      c4: v('--chart-4', '#6250d6'), c5: v('--chart-5', '#eda100'),
      grid: v('--border', '#e5e5e5'), axis: v('--muted-foreground', '#737373'), text: v('--foreground', '#111'),
      card: v('--popover', '#fff'),
    }
  }
  const [colors, setColors] = useState<ChartColors>(read)
  useEffect(() => {
    const id = requestAnimationFrame(() => setColors(read()))
    return () => cancelAnimationFrame(id)
  }, [resolved])
  return colors
}

export function ChartTooltipBox({ active, payload, label, unit = '' }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string | number; unit?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md">
      {label != null && <div className="mb-1 font-medium">{label}</div>}
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="size-2 rounded-sm" style={{ background: p.color }} aria-hidden />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="ml-auto pl-3 font-medium tabular-nums">{typeof p.value === 'number' ? p.value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : p.value}{unit}</span>
        </div>
      ))}
    </div>
  )
}

export function MetricCard({ label, value, sub, tone }: { label: string; value: string; sub?: ReactNode; tone?: 'good' | 'bad' | 'neutral' }) {
  return (
    <div className="rounded-xl border bg-card px-4 py-3.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-1 text-xl font-semibold tabular-nums tracking-tight ${tone === 'good' ? 'text-success' : tone === 'bad' ? 'text-destructive' : ''}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  )
}

export function Provenance({ meta }: { meta?: BenchmarkMeta }) {
  if (!meta) return null
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" className="inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground" aria-label="Benchmark provenance">
          <Info className="size-3" aria-hidden />
          {meta.timestamp ? new Date(meta.timestamp).toLocaleDateString() : 'recorded'} · {meta.git_commit ?? 'n/a'}
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-sm">
        <div className="font-mono text-[11px]">{meta.command}</div>
        <div className="mt-1">{meta.hardware}{meta.swap_used_gb != null && ` · ${meta.swap_used_gb} GB swap in use at start`}</div>
      </TooltipContent>
    </Tooltip>
  )
}

export function ChartCard({ title, description, meta, children, className }: { title: string; description?: ReactNode; meta?: BenchmarkMeta; children: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader className="gap-1">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <CardTitle className="text-sm">{title}</CardTitle>
          <Provenance meta={meta} />
        </div>
        {description && <CardDescription className="text-xs">{description}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export function Legend({ items }: { items: { label: string; color: string; dashed?: boolean }[] }) {
  return (
    <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-3 rounded-sm" style={i.dashed ? { borderTop: `2px dashed ${i.color}`, height: 0 } : { background: i.color }} aria-hidden />
          {i.label}
        </span>
      ))}
    </div>
  )
}
