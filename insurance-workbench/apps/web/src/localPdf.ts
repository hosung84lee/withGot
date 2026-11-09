import { AnnotationMode, GlobalWorkerOptions, getDocument, Util } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { LocalDocument, SourceLine, SourcePage } from './privacy'
import { releaseDocuments } from './privacy'

GlobalWorkerOptions.workerSrc = workerUrl

export async function readLocalPdf(file: File, signal: AbortSignal): Promise<LocalDocument> {
  signal.throwIfAborted()
  if (!file.name.toLowerCase().endsWith('.pdf') || (file.type && file.type !== 'application/pdf')) {
    throw new Error('텍스트가 포함된 PDF 파일을 선택해 주세요.')
  }
  if (!file.size || file.size > 10 * 1024 * 1024) throw new Error('PDF는 파일당 10 MiB까지 지원합니다.')
  const bytes = new Uint8Array(await file.arrayBuffer())
  signal.throwIfAborted()
  if (new TextDecoder('ascii').decode(bytes.slice(0, 5)) !== '%PDF-') {
    throw new Error('유효한 PDF 파일이 아닙니다.')
  }
  const loading = getDocument({ data: bytes, useWasm: false,
    enableXfa: false, stopAtErrors: true, maxImageSize: 4_000_000,
    useSystemFonts: true, isOffscreenCanvasSupported: false, verbosity: 0 })
  const limitedSignal = AbortSignal.any([signal, AbortSignal.timeout(15_000)])
  const stop = () => { void loading.destroy().catch(() => {}) }
  limitedSignal.addEventListener('abort', stop, { once: true })
  const pages: SourcePage[] = []
  try {
    limitedSignal.throwIfAborted()
    const pdf = await loading.promise
    if (pdf.numPages > 10) throw new Error('PDF는 파일당 10페이지까지 지원합니다.')
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {
      limitedSignal.throwIfAborted()
      const page = await pdf.getPage(pageNumber)
      const base = page.getViewport({ scale: 1 })
      if (!Number.isFinite(base.width + base.height) || base.width <= 0 || base.height <= 0) {
        throw new Error('invalid_page_size')
      }
      const scale = Math.min(1.2, 1200 / base.width, 1600 / base.height)
      const viewport = page.getViewport({ scale })
      const content = await page.getTextContent()
      if (content.items.length > 2000) throw new Error('page_too_complex')
      const lines: SourceLine[] = []
      for (const item of content.items) {
        if (!('str' in item) || !item.str.trim()) continue
        const matrix = Util.transform(viewport.transform, item.transform)
        const height = Math.max(1, Math.hypot(matrix[2], matrix[3]))
        const piece = { text: item.str, page: pageNumber, left: matrix[4],
          top: matrix[5] - height, width: Math.abs(item.width * scale), height }
        let line = lines.find(line => Math.abs(line.top - piece.top) < 3)
        if (!line) { lines.push(piece); continue }
        // The supported sample writes each complete row as a single text run.
        // Join font fallback runs without losing their source rectangle.
        line.text += item.str
        line.width = Math.max(line.left + line.width, piece.left + piece.width) - Math.min(line.left, piece.left)
        line.left = Math.min(line.left, piece.left)
        line.height = Math.max(line.height, piece.height)
      }
      for (const line of lines) line.text = line.text.trim().replace(/\s+/g, ' ')
      if (!lines.length) throw new Error('텍스트를 읽을 수 없습니다. 스캔 PDF와 사진은 후속 지원 예정입니다.')
      const canvas = document.createElement('canvas')
      canvas.width = Math.ceil(viewport.width)
      canvas.height = Math.ceil(viewport.height)
      const render = page.render({ canvas, viewport, annotationMode: AnnotationMode.DISABLE })
      const cancelRender = () => render.cancel()
      limitedSignal.addEventListener('abort', cancelRender, { once: true })
      let blob: Blob | null
      try {
        await render.promise
        blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/png'))
      } finally {
        limitedSignal.removeEventListener('abort', cancelRender)
        canvas.width = canvas.height = 0
      }
      if (!blob) throw new Error('원본 미리보기를 만들 수 없습니다.')
      limitedSignal.throwIfAborted()
      pages.push({ url: URL.createObjectURL(blob), width: viewport.width, height: viewport.height, lines })
      page.cleanup()
    }
    return { name: file.name, pages }
  } catch (error) {
    releaseDocuments([{ name: '', pages }])
    if (signal.aborted) throw new Error('문서 읽기를 취소했습니다.')
    if (limitedSignal.aborted) throw new Error('PDF 처리 시간이 초과되었습니다. 더 작은 샘플을 선택해 주세요.')
    if (error instanceof Error && error.name === 'PasswordException') throw new Error('암호화된 PDF는 지원하지 않습니다.')
    if (error instanceof Error && error.message.startsWith('PDF는')) throw error
    if (error instanceof Error && ['텍스트를 읽을 수 없습니다.', '원본 미리보기를 만들 수 없습니다.'].some(prefix => error.message.startsWith(prefix))) throw error
    throw new Error('PDF를 읽을 수 없습니다. 손상 여부와 지원 서식을 확인해 주세요.')
  } finally {
    limitedSignal.removeEventListener('abort', stop)
    await loading.destroy().catch(() => {})
  }
}
