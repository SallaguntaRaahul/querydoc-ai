import { useEffect, useRef, useState } from 'react'
import { Document, Page } from 'react-pdf'

import { fileUrl } from '@/features/viewer/pdf-setup'

/** First-page thumbnail, rendered lazily when the card scrolls into view. */
export default function PdfThumbnail({ documentId }: { documentId: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(false)
  const [width, setWidth] = useState(240)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    setWidth(el.clientWidth || 240)
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true)
      return
    }
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setVisible(true), { rootMargin: '200px' })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  return (
    <div ref={ref} className="size-full overflow-hidden bg-white">
      {visible && (
        <Document file={fileUrl(documentId)} loading={<div className="size-full animate-pulse bg-muted" />} error={<div className="size-full bg-muted" />}>
          <Page pageNumber={1} width={width} renderTextLayer={false} renderAnnotationLayer={false} />
        </Document>
      )}
    </div>
  )
}
