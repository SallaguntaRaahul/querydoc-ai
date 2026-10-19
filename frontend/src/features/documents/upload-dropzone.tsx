import { FileUp, UploadCloud } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { ApiError } from '@/lib/api'
import { formatBytes } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useUploadDocuments } from '@/services/queries'

export const MAX_UPLOAD_MB = 50
export const MAX_FILES = 20

export interface FileCheck {
  ok: File[]
  rejected: { name: string; reason: string }[]
}

/** Client-side checks mirror the server's (the server re-validates everything). */
export function validateFiles(files: File[], maxMb = MAX_UPLOAD_MB): FileCheck {
  const ok: File[] = []
  const rejected: FileCheck['rejected'] = []
  for (const f of files.slice(0, MAX_FILES)) {
    if (!f.name.toLowerCase().endsWith('.pdf') && f.type !== 'application/pdf') rejected.push({ name: f.name, reason: 'Not a PDF file' })
    else if (f.size === 0) rejected.push({ name: f.name, reason: 'File is empty' })
    else if (f.size > maxMb * 1024 * 1024) rejected.push({ name: f.name, reason: `Larger than ${maxMb} MB (${formatBytes(f.size)})` })
    else ok.push(f)
  }
  if (files.length > MAX_FILES) rejected.push({ name: `${files.length - MAX_FILES} more`, reason: `At most ${MAX_FILES} files per upload` })
  return { ok, rejected }
}

export function UploadDropzone({ compact = false, className }: { compact?: boolean; className?: string }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const upload = useUploadDocuments()

  const handleFiles = useCallback(
    async (list: FileList | File[]) => {
      const { ok, rejected } = validateFiles(Array.from(list))
      rejected.forEach((r) => toast.error(`${r.name}: ${r.reason}`))
      if (!ok.length) return
      setProgress(0)
      try {
        const res = await upload.mutateAsync({ files: ok, onProgress: setProgress })
        if (res.documents.length)
          toast.success(`${res.documents.length} file${res.documents.length > 1 ? 's' : ''} uploaded — indexing in the background`)
        res.errors.forEach((e) => toast.error(`${e.filename}: ${e.message}`))
      } catch (e) {
        toast.error(e instanceof ApiError ? e.message : 'Upload failed')
      } finally {
        setProgress(null)
        if (inputRef.current) inputRef.current.value = ''
      }
    },
    [upload],
  )

  const busy = progress !== null
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); if (!busy) void handleFiles(e.dataTransfer.files) }}
      className={cn(
        'relative flex flex-col items-center justify-center rounded-xl border border-dashed text-center transition-colors',
        compact ? 'gap-2 px-4 py-6' : 'gap-3 px-6 py-12',
        dragging ? 'border-primary bg-primary/6' : 'border-border bg-card/40 hover:border-primary/50 hover:bg-accent/40',
        className,
      )}
      data-testid="upload-dropzone"
    >
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        className="sr-only"
        aria-label="Choose PDF files to upload"
        data-testid="file-input"
        onChange={(e) => e.target.files && void handleFiles(e.target.files)}
      />
      <div className={cn('grid place-items-center rounded-full bg-primary/12 text-primary', compact ? 'size-10' : 'size-12')}>
        {dragging ? <FileUp className="size-5" aria-hidden /> : <UploadCloud className="size-5" aria-hidden />}
      </div>
      <div>
        <p className="text-sm font-medium">{dragging ? 'Drop to upload' : 'Drag PDFs here or browse'}</p>
        <p className="mt-0.5 text-xs text-muted-foreground">Up to {MAX_FILES} files · {MAX_UPLOAD_MB} MB each · text PDFs (scanned pages need OCR)</p>
      </div>
      {busy ? (
        <div className="w-full max-w-xs" aria-live="polite">
          <Progress value={(progress ?? 0) * 100} aria-label="Upload progress" />
          <p className="mt-1.5 text-xs text-muted-foreground">Uploading… {Math.round((progress ?? 0) * 100)}%</p>
        </div>
      ) : (
        <Button size={compact ? 'sm' : 'default'} variant="secondary" onClick={() => inputRef.current?.click()}>
          Browse files
        </Button>
      )}
    </div>
  )
}
