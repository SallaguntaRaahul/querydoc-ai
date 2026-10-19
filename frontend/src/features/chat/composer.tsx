import { ArrowUp, Square } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export const MAX_QUESTION_CHARS = 2000

export function Composer({
  onSend,
  onStop,
  streaming,
  disabled,
  disabledReason,
  toolbar,
  autoFocus,
}: {
  onSend: (text: string) => void
  onStop: () => void
  streaming: boolean
  disabled?: boolean
  disabledReason?: string
  toolbar?: ReactNode
  autoFocus?: boolean
}) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [value])

  const submit = () => {
    const text = value.trim()
    if (!text || streaming || disabled || text.length > MAX_QUESTION_CHARS) return
    onSend(text)
    setValue('')
  }

  const over = value.length > MAX_QUESTION_CHARS
  return (
    <div className="rounded-2xl border bg-card shadow-sm transition-shadow focus-within:border-primary/50 focus-within:shadow-md focus-within:shadow-primary/5">
      <label htmlFor="chat-input" className="sr-only">Ask a question</label>
      <textarea
        id="chat-input"
        ref={ref}
        autoFocus={autoFocus}
        rows={1}
        value={value}
        disabled={disabled}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            submit()
          }
        }}
        placeholder={disabled ? (disabledReason ?? 'Upload a document to start') : 'Ask a question about your documents…'}
        className="scrollbar-thin block max-h-[200px] w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed focus-visible:outline-none"
        data-testid="chat-input"
      />
      <div className="flex items-center gap-2 px-2.5 pb-2.5 pt-1">
        <div className="flex min-w-0 flex-1 items-center gap-1.5">{toolbar}</div>
        <span className={cn('hidden text-[11px] tabular-nums sm:inline', over ? 'text-destructive' : 'text-muted-foreground')}>
          {value.length > MAX_QUESTION_CHARS * 0.8 ? `${value.length}/${MAX_QUESTION_CHARS}` : 'Enter to send · Shift+Enter for new line'}
        </span>
        {streaming ? (
          <Button size="icon" variant="secondary" className="size-8 rounded-full" onClick={onStop} aria-label="Stop generating" data-testid="stop-button">
            <Square className="size-3 fill-current" />
          </Button>
        ) : (
          <Button size="icon" className="size-8 rounded-full" onClick={submit} disabled={!value.trim() || disabled || over} aria-label="Send question" data-testid="send-button">
            <ArrowUp className="size-4" />
          </Button>
        )}
      </div>
    </div>
  )
}
