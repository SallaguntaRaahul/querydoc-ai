import { Check, ChevronsUpDown, Files } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import type { DocumentItem } from '@/types/api'

/** Selects which documents a question is answered from. [] means "all ready documents". */
export function ScopePicker({
  documents,
  value,
  onChange,
  disabled,
}: {
  documents: DocumentItem[]
  value: string[]
  onChange: (ids: string[]) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const ready = useMemo(() => documents.filter((d) => d.status === 'ready'), [documents])
  const label =
    value.length === 0
      ? `All documents (${ready.length})`
      : value.length === 1
        ? (ready.find((d) => d.id === value[0])?.filename ?? '1 document')
        : `${value.length} documents`

  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled} className="max-w-[260px] justify-between gap-2" aria-label="Choose documents to search">
          <Files className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate">{label}</span>
          <ChevronsUpDown className="size-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-80 p-0" align="start">
        <Command>
          <CommandInput placeholder="Filter documents…" />
          <CommandList>
            <CommandEmpty>No ready documents.</CommandEmpty>
            <CommandGroup>
              <CommandItem onSelect={() => onChange([])}>
                <Check className={cn('size-4', value.length === 0 ? 'opacity-100' : 'opacity-0')} />
                All documents
              </CommandItem>
            </CommandGroup>
            <CommandSeparator />
            <CommandGroup heading="Documents">
              {ready.map((d) => (
                <CommandItem key={d.id} value={`${d.filename} ${d.title}`} onSelect={() => toggle(d.id)}>
                  <Check className={cn('size-4 shrink-0', value.includes(d.id) ? 'opacity-100' : 'opacity-0')} />
                  <div className="min-w-0">
                    <div className="truncate">{d.filename}</div>
                    <div className="text-[11px] text-muted-foreground">{d.page_count} pages</div>
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
