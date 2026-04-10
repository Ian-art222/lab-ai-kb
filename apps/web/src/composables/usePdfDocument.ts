import {
  nextTick,
  onBeforeUnmount,
  ref,
  shallowRef,
  watch,
  type Ref,
} from 'vue'
import * as pdfjsLib from 'pdfjs-dist/build/pdf.min.mjs'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { readApiErrorMessage } from '@/api/client'
import { getPdfContentApi } from '@/api/pdfDocuments'

;(pdfjsLib as { GlobalWorkerOptions: { workerSrc: string } }).GlobalWorkerOptions.workerSrc = pdfWorkerUrl

export type PdfRenderState = 'idle' | 'loading' | 'loaded' | 'failed'

type PageRenderTask = { cancel?: () => void; promise: Promise<void> }

function normalizeErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.name === 'AbortError') return ''
  if (error instanceof Error && error.message.trim()) return error.message
  if (typeof error === 'string' && error.trim()) return error
  return fallback
}

/**
 * PDF.js：二进制 → getDocument → 按页 canvas。
 *
 * 重要：禁止在 bindCanvas(ref 回调) 里调用 page.render。
 * ref 在 v-for 挂载时会与 load 完成后的 renderAllPages 叠加，导致同一 canvas 并发 render（PDF.js 报错）。
 */
export function usePdfDocument(fileId: Ref<number>) {
  const pdfState = ref<PdfRenderState>('idle')
  const pdfErrorMessage = ref('')
  const pageCount = ref(0)
  /** 与 canvas 一致的 CSS 缩放（不含 DPR）；变更会触发整本重绘 */
  const cssScale = ref(1.25)
  const pdfDocumentRef = shallowRef<{
    numPages: number
    getPage: (n: number) => Promise<any>
    destroy: () => Promise<void>
  } | null>(null)

  let pdfDoc: { numPages: number; getPage: (n: number) => Promise<any>; destroy: () => Promise<void> } | null =
    null
  let pdfLoadingTask: { promise: Promise<any>; destroy?: () => void } | null = null
  let requestSeq = 0
  /** 任意 cleanup / 新加载时递增，用于作废进行中的 renderPage */
  let renderGeneration = 0
  let fetchAbort: AbortController | null = null

  const canvasMap = new Map<number, HTMLCanvasElement>()
  const renderTaskMap = new Map<number, PageRenderTask>()

  /** 仅登记 canvas，绝不在此处触发 render（避免与 renderAllPages 并发）。 */
  function bindCanvas(el: unknown, pageNo: number) {
    if (el instanceof HTMLCanvasElement) {
      canvasMap.set(pageNo, el)
    } else {
      canvasMap.delete(pageNo)
    }
  }

  async function cancelPageRenderTask(pageNo: number) {
    const t = renderTaskMap.get(pageNo)
    if (!t) return
    renderTaskMap.delete(pageNo)
    try {
      t.cancel?.()
    } catch {
      /* ignore */
    }
    try {
      await t.promise
    } catch {
      /* cancelled / render error */
    }
  }

  async function cancelAllPageRenderTasks() {
    const pages = [...renderTaskMap.keys()]
    await Promise.all(pages.map((p) => cancelPageRenderTask(p)))
  }

  async function cleanupPdfResources() {
    renderGeneration += 1
    await cancelAllPageRenderTasks()

    if (pdfLoadingTask?.destroy) {
      try {
        pdfLoadingTask.destroy()
      } catch {
        /* ignore */
      }
    }
    pdfLoadingTask = null

    if (pdfDoc) {
      try {
        await pdfDoc.destroy()
      } catch {
        /* ignore */
      }
    }
    pdfDoc = null
    pdfDocumentRef.value = null
    canvasMap.clear()
  }

  function viewportScaleForPage(page: {
    getViewport: (o: { scale: number; rotation?: number }) => { width: number; height: number }
    rotate?: number
  }) {
    const dpr = typeof window !== 'undefined' && window.devicePixelRatio ? window.devicePixelRatio : 1
    const base = cssScale.value
    const rotation = typeof page.rotate === 'number' ? page.rotate : 0
    const vp = page.getViewport({ scale: base * dpr, rotation })
    return { vp, dpr, cssScale: base, rotation }
  }

  /**
   * 调用入口：仅 renderAllPages（以及未来可能的单页重绘，同样需先 cancel 同页旧 task）。
   */
  async function renderPage(pageNo: number, seq: number, gen: number) {
    if (gen !== renderGeneration || seq !== requestSeq || !pdfDoc) return

    await cancelPageRenderTask(pageNo)
    if (gen !== renderGeneration || seq !== requestSeq || !pdfDoc) return

    const canvas = canvasMap.get(pageNo)
    if (!canvas) {
      console.warn('[PDF] renderPage skip: no canvas', { pageNo, seq, gen })
      return
    }

    const t0 = performance.now()
    console.info('[PDF] renderPage start', {
      entry: 'renderAllPages',
      pageNo,
      seq,
      gen,
      canvasTag: canvas.tagName,
      dataPage: canvas.closest('[data-page]')?.getAttribute('data-page'),
    })

    const page = await pdfDoc.getPage(pageNo)
    if (gen !== renderGeneration || seq !== requestSeq || !pdfDoc) return

    const { vp, dpr } = viewportScaleForPage(page)
    const ctx = canvas.getContext('2d', { alpha: false })
    if (!ctx) return

    canvas.width = Math.floor(vp.width)
    canvas.height = Math.floor(vp.height)
    canvas.style.width = `${Math.floor(vp.width / dpr)}px`
    canvas.style.height = `${Math.floor(vp.height / dpr)}px`

    const pdfRenderTask = page.render({ canvasContext: ctx, viewport: vp }) as PageRenderTask
    renderTaskMap.set(pageNo, pdfRenderTask)

    try {
      await pdfRenderTask.promise
      console.info('[PDF] renderPage done', {
        pageNo,
        seq,
        gen,
        ms: Math.round(performance.now() - t0),
      })
    } catch (e) {
      if (gen === renderGeneration && seq === requestSeq) {
        console.warn('[PDF] renderPage task error', { pageNo, seq, gen, e })
      }
    } finally {
      if (renderTaskMap.get(pageNo) === pdfRenderTask) {
        renderTaskMap.delete(pageNo)
      }
    }
  }

  /** 等待 v-for 中全部 canvas 通过 ref 回调写入 canvasMap */
  async function waitForAllCanvasesBound(expected: number, seq: number, gen: number): Promise<boolean> {
    for (let i = 0; i < 50; i += 1) {
      if (seq !== requestSeq || gen !== renderGeneration) return false
      if (canvasMap.size >= expected) {
        console.info('[PDF] canvases bound', { expected, bound: canvasMap.size, ticks: i })
        return true
      }
      await nextTick()
    }
    console.warn('[PDF] canvases not fully bound', { expected, bound: canvasMap.size })
    return canvasMap.size >= expected
  }

  async function renderAllPages(seq: number) {
    const gen = renderGeneration
    if (!pdfDoc || seq !== requestSeq || gen !== renderGeneration) return

    const n = Number(pdfDoc.numPages || 0)
    console.info('[PDF] renderAllPages enter', {
      entry: 'loadPdfDocument',
      seq,
      gen,
      pageCount: n,
      fileId: fileId.value,
    })

    await cancelAllPageRenderTasks()
    if (seq !== requestSeq || gen !== renderGeneration || !pdfDoc) return

    const ready = await waitForAllCanvasesBound(n, seq, gen)
    if (!ready || seq !== requestSeq || gen !== renderGeneration) {
      console.warn('[PDF] renderAllPages aborted before draw', { seq, gen, ready })
      return
    }

    for (let pageNo = 1; pageNo <= n; pageNo += 1) {
      if (seq !== requestSeq || gen !== renderGeneration) return
      await renderPage(pageNo, seq, gen)
    }
    console.info('[PDF] renderAllPages done', { seq, gen, pageCount: n })
  }

  async function loadPdfDocument(id: number) {
    const seq = ++requestSeq
    pdfState.value = 'loading'
    pdfErrorMessage.value = ''
    pageCount.value = 0

    fetchAbort?.abort()
    fetchAbort = new AbortController()
    const signal = fetchAbort.signal

    await cleanupPdfResources()
    if (seq !== requestSeq) return

    try {
      const response = await getPdfContentApi(id, { signal })
      const contentType = response.headers.get('content-type') || 'unknown'

      console.info('[PDF] fetch response', {
        fileId: id,
        url: response.url,
        status: response.status,
        contentType,
      })

      if (!response.ok) {
        throw new Error(await readApiErrorMessage(response, 'PDF 内容请求失败'))
      }

      const arrayBuffer = await response.arrayBuffer()

      if (signal.aborted || seq !== requestSeq) return

      if (arrayBuffer.byteLength <= 0) {
        throw new Error('PDF 内容为空（0 字节）')
      }

      const ct = contentType.toLowerCase()
      if (!ct.includes('application/pdf') && !ct.includes('application/octet-stream')) {
        const head = new TextDecoder().decode(arrayBuffer.slice(0, 240))
        throw new Error(`响应 Content-Type 非 PDF：${contentType}；片段：${head}`)
      }

      const loadTask = pdfjsLib.getDocument({ data: new Uint8Array(arrayBuffer) })
      pdfLoadingTask = loadTask
      const doc = await loadTask.promise
      pdfDoc = doc
      pdfDocumentRef.value = doc

      if (signal.aborted || seq !== requestSeq) return

      const numPages = Number(doc.numPages || 0)
      pageCount.value = numPages

      if (numPages <= 0) {
        throw new Error('PDF 页数为 0，无法渲染')
      }

      pdfState.value = 'loaded'
      await nextTick()
      await nextTick()
      await renderAllPages(seq)
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        return
      }
      console.error('[PDF] load failed', error)
      if (seq !== requestSeq) return
      pdfState.value = 'failed'
      const msg = normalizeErrorMessage(error, '未知错误')
      pdfErrorMessage.value = msg ? `PDF 加载失败：${msg}` : 'PDF 加载失败：请求已取消'
    }
  }

  watch(
    fileId,
    (id) => {
      if (Number.isFinite(id) && id > 0) {
        void loadPdfDocument(id)
      } else {
        void cleanupPdfResources()
        pdfState.value = 'idle'
        pdfErrorMessage.value = ''
        pageCount.value = 0
      }
    },
    { immediate: true },
  )

  watch(cssScale, () => {
    if (pdfState.value === 'loaded' && pdfDoc && pageCount.value > 0) {
      void renderAllPages(requestSeq)
    }
  })

  onBeforeUnmount(() => {
    fetchAbort?.abort()
    fetchAbort = null
    void cleanupPdfResources()
  })

  function getCanvasForPage(pageNo: number): HTMLCanvasElement | null {
    return canvasMap.get(pageNo) ?? null
  }

  return {
    pdfState,
    pdfErrorMessage,
    pageCount,
    bindCanvas,
    cleanupPdfResources,
    pdfWorkerUrl,
    pdfDocumentRef,
    cssScale,
    setCssScale: (v: number) => {
      const n = Number(v)
      if (Number.isFinite(n) && n >= 0.5 && n <= 3) {
        cssScale.value = n
      }
    },
    getCanvasForPage,
  }
}
