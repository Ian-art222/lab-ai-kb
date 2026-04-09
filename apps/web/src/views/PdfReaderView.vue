<template>
  <AdminLayout>
    <div class="pdf-reader">
      <div class="topbar">
        <el-button @click="router.back()">返回</el-button>
        <div class="title">{{ docInfo?.doc?.title || `PDF #${currentFileId}` }}</div>
        <el-switch v-model="dualPane" active-text="双栏" inactive-text="单栏" />
        <el-switch v-model="linkedScroll" active-text="联动滚动" inactive-text="解耦滚动" />
        <el-button :loading="translating" @click="triggerTranslate">全文翻译</el-button>
        <el-button @click="downloadOriginal">下载原文</el-button>
        <el-button @click="downloadBundle">下载原文+译文</el-button>
      </div>

      <div class="body" :class="{ single: !dualPane }">
        <section ref="leftPaneRef" class="pane left" @scroll="onLeftScroll">
          <div v-if="pdfState === 'loading'" class="pdf-status">PDF 正在加载…</div>
          <div v-else-if="pdfState === 'failed'" class="pdf-load-error">{{ pdfErrorMessage }}</div>
          <template v-else>
            <div
              v-for="p in pageCount"
              :key="`page-${currentFileId}-${p}`"
              :data-page="p"
              class="pdf-page-wrap"
            >
              <div class="pdf-page-meta">第 {{ p }} / {{ pageCount }} 页</div>
              <canvas :ref="(el) => bindCanvas(el, p)" class="pdf-canvas" />
            </div>
          </template>
        </section>

        <section v-if="dualPane" ref="rightPaneRef" class="pane right" @scroll="onRightScroll">
          <div class="translate-status">
            <el-tag v-if="translationState === 'idle'">未翻译</el-tag>
            <el-tag v-else-if="translationState === 'pending'">排队中</el-tag>
            <el-tag v-else-if="translationState === 'running'">翻译中 {{ translationProgress }}%</el-tag>
            <el-tag v-else-if="translationState === 'completed'" type="success">已完成</el-tag>
            <el-tag v-else-if="translationState === 'empty'" type="info">暂无译文</el-tag>
            <el-tag v-else type="danger">翻译失败</el-tag>
            <span class="translate-debug">{{ translationDebugMessage }}</span>
          </div>

          <div v-if="translationErrorMessage" class="translate-error">{{ translationErrorMessage }}</div>
          <div v-else-if="translationItems.length === 0" class="translate-empty">暂无译文内容</div>
          <div
            v-for="item in translationItems"
            :key="item.chunk_id"
            class="tr-item"
            @click="jumpToPage(item.page_number)"
          >
            <div class="meta">p.{{ item.page_number || '-' }} · chunk {{ item.chunk_id }}</div>
            <div class="text">{{ item.translated }}</div>
          </div>
        </section>

        <aside class="sidebar">
          <h4>我的笔记</h4>
          <el-button size="small" @click="addNote">新增</el-button>
          <div v-for="a in myAnnotations" :key="a.id" class="note">
            <div>{{ a.annotation_json?.text }}</div>
            <el-button link type="danger" @click="removeNote(a.id)">删除</el-button>
          </div>

          <h4>实验室笔记</h4>
          <el-select v-model="selectedPublicUser" placeholder="选择同事" @change="loadPublicAnnotations">
            <el-option v-for="uid in publicUserIds" :key="uid" :label="`用户 ${uid}`" :value="uid" />
          </el-select>
          <div v-for="a in publicAnnotations" :key="a.id" class="note readonly">{{ a.annotation_json?.text }}</div>

          <h4>附件</h4>
          <div v-for="att in attachments" :key="att.id" class="note">{{ att.title || `file#${att.file_id}` }}</div>

          <h4>AI 助手</h4>
          <el-input v-model="qaQuestion" type="textarea" :rows="3" placeholder="在当前文献中提问" />
          <el-button size="small" :loading="qaLoading" @click="askQa">提问</el-button>
          <div v-if="qaAnswer" class="qa-answer">{{ qaAnswer }}</div>
          <div
            v-for="ref in qaRefs"
            :key="`${ref.chunk_id}-${ref.page_number}`"
            class="qa-ref"
            @click="jumpToPage(ref.page_number)"
          >
            p.{{ ref.page_number || '-' }} {{ ref.snippet }}
          </div>

          <h4>划词翻译</h4>
          <el-button size="small" @click="translateSelection">翻译当前选中文本</el-button>
          <div class="qa-answer">{{ selectionTranslation }}</div>
        </aside>
      </div>
    </div>
  </AdminLayout>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as pdfjsLib from 'pdfjs-dist/build/pdf.min.mjs'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import AdminLayout from '../layouts/AdminLayout.vue'
import { readApiErrorMessage } from '../api/client'
import {
  addAttachmentApi,
  askPdfQaApi,
  createAnnotationApi,
  downloadPdfBundleApi,
  getPdfContentApi,
  deleteAnnotationApi,
  getAnnotationsByUserApi,
  getMyAnnotationsApi,
  getPdfDocumentApi,
  getPdfTranslationContentApi,
  getPdfTranslationStatusApi,
  listAttachmentsApi,
  listPublicAnnotationUsersApi,
  selectionTranslateApi,
  triggerPdfTranslateApi,
} from '../api/pdfDocuments'

(pdfjsLib as any).GlobalWorkerOptions.workerSrc = pdfWorkerUrl

type PdfRenderState = 'idle' | 'loading' | 'loaded' | 'failed'
type TranslationViewState = 'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'empty'

const route = useRoute()
const router = useRouter()
const currentFileId = computed(() => Number(route.params.fileId))

const dualPane = ref(true)
const linkedScroll = ref(true)
const leftPaneRef = ref<HTMLElement | null>(null)
const rightPaneRef = ref<HTMLElement | null>(null)

const docInfo = ref<any>(null)
const pdfState = ref<PdfRenderState>('idle')
const pdfErrorMessage = ref('')
const pageCount = ref(0)
const translating = ref(false)

const translationState = ref<TranslationViewState>('idle')
const translationProgress = ref(0)
const translationItems = ref<any[]>([])
const translationErrorMessage = ref('')
const translationDebugMessage = ref('')

const myAnnotations = ref<any[]>([])
const publicUserIds = ref<number[]>([])
const selectedPublicUser = ref<number | null>(null)
const publicAnnotations = ref<any[]>([])
const attachments = ref<any[]>([])

const qaQuestion = ref('')
const qaLoading = ref(false)
const qaAnswer = ref('')
const qaRefs = ref<any[]>([])
const selectionTranslation = ref('')

let pdfDoc: any = null
let pdfLoadingTask: any = null
let pdfRequestSeq = 0
let translationRequestSeq = 0
let translationPollTimer: number | null = null

const canvasMap = new Map<number, HTMLCanvasElement>()
const renderTaskMap = new Map<number, any>()

function bindCanvas(el: unknown, pageNo: number) {
  if (el instanceof HTMLCanvasElement) {
    canvasMap.set(pageNo, el)
    if (pdfState.value === 'loaded') {
      void renderPage(pageNo, pdfRequestSeq)
    }
  } else {
    canvasMap.delete(pageNo)
  }
}

function normalizeErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message
  if (typeof error === 'string' && error.trim()) return error
  return fallback
}

async function cleanupPdfResources() {
  for (const [, renderTask] of renderTaskMap) {
    try {
      renderTask.cancel()
    } catch {
      // ignore
    }
  }
  renderTaskMap.clear()

  if (pdfLoadingTask) {
    try {
      pdfLoadingTask.destroy()
    } catch {
      // ignore
    }
    pdfLoadingTask = null
  }

  if (pdfDoc) {
    try {
      await pdfDoc.destroy()
    } catch {
      // ignore
    }
    pdfDoc = null
  }
  canvasMap.clear()
}

async function renderPage(pageNo: number, requestSeq: number) {
  if (!pdfDoc || requestSeq !== pdfRequestSeq) return
  const canvas = canvasMap.get(pageNo)
  if (!canvas) return

  const page = await pdfDoc.getPage(pageNo)
  const viewport = page.getViewport({ scale: 1.3 })
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  canvas.width = Math.floor(viewport.width)
  canvas.height = Math.floor(viewport.height)
  console.info('[PDF] renderPage', { fileId: currentFileId.value, pageNo, width: canvas.width, height: canvas.height })

  const renderTask = page.render({ canvasContext: ctx, viewport })
  renderTaskMap.set(pageNo, renderTask)
  try {
    await renderTask.promise
  } finally {
    renderTaskMap.delete(pageNo)
  }
}

async function renderAllPages(requestSeq: number) {
  if (!pdfDoc || requestSeq !== pdfRequestSeq) return
  console.info('[PDF] renderAllPages start', { fileId: currentFileId.value, pageCount: pageCount.value })
  for (let pageNo = 1; pageNo <= pageCount.value; pageNo += 1) {
    if (requestSeq !== pdfRequestSeq) return
    await renderPage(pageNo, requestSeq)
  }
  console.info('[PDF] renderAllPages done', { fileId: currentFileId.value, pageCount: pageCount.value })
}

function parseTranslationItems(payload: any): any[] {
  if (!payload || typeof payload !== 'object') return []
  if (Array.isArray(payload.items)) return payload.items
  if (payload.content && Array.isArray(payload.content.items)) return payload.content.items
  if (Array.isArray(payload.content)) return payload.content
  return []
}

async function loadPdfDocument(fileId: number) {
  const requestSeq = ++pdfRequestSeq
  pdfState.value = 'loading'
  pdfErrorMessage.value = ''
  pageCount.value = 0
  await cleanupPdfResources()

  try {
    const response = await getPdfContentApi(fileId)
    const contentType = response.headers.get('content-type') || 'unknown'
    console.info('[PDF] fetch', { url: response.url, status: response.status, contentType })

    if (!response.ok) {
      throw new Error(await readApiErrorMessage(response, 'PDF 内容请求失败'))
    }

    const arrayBuffer = await response.arrayBuffer()
    console.info('[PDF] arrayBuffer', { fileId, byteLength: arrayBuffer.byteLength })
    if (arrayBuffer.byteLength <= 0) {
      throw new Error('PDF 内容为空（0 字节）')
    }

    if (!contentType.toLowerCase().includes('application/pdf')) {
      const head = new TextDecoder().decode(arrayBuffer.slice(0, 240))
      throw new Error(`响应 Content-Type 非 PDF：${contentType}；内容片段：${head}`)
    }

    pdfLoadingTask = pdfjsLib.getDocument({ data: new Uint8Array(arrayBuffer) })
    pdfDoc = await pdfLoadingTask.promise
    if (requestSeq !== pdfRequestSeq) return

    pageCount.value = Number(pdfDoc.numPages || 0)
    console.info('[PDF] getDocument success', { fileId, pageCount: pageCount.value, workerSrc: pdfWorkerUrl })

    if (pageCount.value <= 0) {
      throw new Error('PDF 页数为 0，无法渲染')
    }

    pdfState.value = 'loaded'
    await nextTick()
    await renderAllPages(requestSeq)
  } catch (error) {
    console.error('[PDF] load failed', error)
    if (requestSeq !== pdfRequestSeq) return
    pdfState.value = 'failed'
    pdfErrorMessage.value = `PDF 加载失败：${normalizeErrorMessage(error, '未知错误')}`
  }
}

function toTranslationViewState(status: string | undefined): TranslationViewState {
  const s = (status || '').toLowerCase()
  if (s === 'pending') return 'pending'
  if (s === 'running') return 'running'
  if (s === 'completed') return 'completed'
  if (s === 'failed') return 'failed'
  if (s === 'not_started') return 'idle'
  return 'idle'
}

function clearTranslationPoll() {
  if (translationPollTimer != null) {
    window.clearTimeout(translationPollTimer)
    translationPollTimer = null
  }
}

async function refreshTranslation(fileId: number) {
  const requestSeq = ++translationRequestSeq
  translationErrorMessage.value = ''

  try {
    const statusRes = await getPdfTranslationStatusApi(fileId)
    if (requestSeq !== translationRequestSeq) return

    translationState.value = toTranslationViewState(statusRes.status)
    translationProgress.value = Number(statusRes.progress || 0)
    translationDebugMessage.value = `status=${statusRes.status || 'unknown'}, progress=${translationProgress.value}%`
    console.info('[Translation] status', { fileId, status: statusRes.status, progress: statusRes.progress })

    const shouldFetchContent = translationState.value === 'completed' || translationState.value === 'running' || translationState.value === 'pending'

    if (shouldFetchContent) {
      const contentRes = await getPdfTranslationContentApi(fileId)
      if (requestSeq !== translationRequestSeq) return
      const items = parseTranslationItems(contentRes)
      translationItems.value = items
      console.info('[Translation] content', { fileId, itemCount: items.length })

      if (items.length > 0 && translationState.value !== 'failed') {
        if (translationState.value !== 'running' && translationState.value !== 'pending') {
          translationState.value = 'completed'
        }
      } else if (translationState.value === 'completed') {
        translationState.value = 'empty'
      }
    } else {
      translationItems.value = []
    }

    clearTranslationPoll()
    if (translationState.value === 'pending' || translationState.value === 'running') {
      translationPollTimer = window.setTimeout(() => {
        void refreshTranslation(fileId)
      }, 2500)
    }
  } catch (error) {
    if (requestSeq !== translationRequestSeq) return
    translationState.value = 'failed'
    translationErrorMessage.value = `译文加载失败：${normalizeErrorMessage(error, '未知错误')}`
    console.error('[Translation] refresh failed', error)
  }
}

function onLeftScroll() {
  if (!linkedScroll.value || !leftPaneRef.value || !rightPaneRef.value) return
  const ratio = leftPaneRef.value.scrollTop / Math.max(1, leftPaneRef.value.scrollHeight - leftPaneRef.value.clientHeight)
  rightPaneRef.value.scrollTop = ratio * Math.max(0, rightPaneRef.value.scrollHeight - rightPaneRef.value.clientHeight)
}

function onRightScroll() {
  if (!linkedScroll.value || !leftPaneRef.value || !rightPaneRef.value) return
  const ratio = rightPaneRef.value.scrollTop / Math.max(1, rightPaneRef.value.scrollHeight - rightPaneRef.value.clientHeight)
  leftPaneRef.value.scrollTop = ratio * Math.max(0, leftPaneRef.value.scrollHeight - leftPaneRef.value.clientHeight)
}

function jumpToPage(pageNumber?: number | null) {
  if (!pageNumber || !leftPaneRef.value) return
  const node = leftPaneRef.value.querySelector(`[data-page="${pageNumber}"]`)
  if (node) node.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function triggerTranslate() {
  try {
    translating.value = true
    await triggerPdfTranslateApi(currentFileId.value)
    await refreshTranslation(currentFileId.value)
    ElMessage.success('已触发翻译任务')
  } catch (e) {
    ElMessage.error(normalizeErrorMessage(e, '翻译失败'))
  } finally {
    translating.value = false
  }
}

function downloadOriginal() {
  void downloadPdfBundleApi(currentFileId.value, false)
}

function downloadBundle() {
  void downloadPdfBundleApi(currentFileId.value, true)
}

async function addNote() {
  const text = window.getSelection()?.toString().trim() || `note-${Date.now()}`
  await createAnnotationApi(currentFileId.value, { annotation_json: { text }, is_public: false })
  myAnnotations.value = await getMyAnnotationsApi(currentFileId.value)
}

async function removeNote(id: number) {
  await deleteAnnotationApi(currentFileId.value, id)
  myAnnotations.value = await getMyAnnotationsApi(currentFileId.value)
}

async function loadPublicAnnotations() {
  if (!selectedPublicUser.value) return
  publicAnnotations.value = await getAnnotationsByUserApi(currentFileId.value, selectedPublicUser.value)
}

async function askQa() {
  if (!qaQuestion.value.trim()) return
  qaLoading.value = true
  try {
    const res = await askPdfQaApi(currentFileId.value, qaQuestion.value)
    qaAnswer.value = res.answer
    qaRefs.value = res.references || []
  } finally {
    qaLoading.value = false
  }
}

async function translateSelection() {
  const text = window.getSelection()?.toString().trim()
  if (!text) return
  const res = await selectionTranslateApi(currentFileId.value, text)
  selectionTranslation.value = res.translated
}

async function loadReaderMeta(fileId: number) {
  translationItems.value = []
  translationErrorMessage.value = ''
  translationState.value = 'idle'
  translationProgress.value = 0

  try {
    docInfo.value = await getPdfDocumentApi(fileId)
  } catch (e) {
    ElMessage.error(normalizeErrorMessage(e, '获取文献详情失败'))
    return
  }

  try {
    myAnnotations.value = await getMyAnnotationsApi(fileId)
    publicUserIds.value = (await listPublicAnnotationUsersApi(fileId)).user_ids || []
    attachments.value = await listAttachmentsApi(fileId)
  } catch {
    // 侧栏失败不阻塞阅读
  }

  if (attachments.value.length === 0) {
    try {
      await addAttachmentApi(fileId, fileId, '原始文献')
      attachments.value = await listAttachmentsApi(fileId)
    } catch {
      // ignore
    }
  }

  await Promise.all([loadPdfDocument(fileId), refreshTranslation(fileId)])
}

watch(currentFileId, (nextId) => {
  if (Number.isFinite(nextId) && nextId > 0) {
    clearTranslationPoll()
    void loadReaderMeta(nextId)
  }
}, { immediate: true })

onMounted(() => {
  console.info('[PDF] worker configured', { workerSrc: pdfWorkerUrl })
})

onBeforeUnmount(async () => {
  clearTranslationPoll()
  await cleanupPdfResources()
})
</script>

<style scoped>
.pdf-reader { display:flex; flex-direction:column; gap:8px; }
.topbar { display:flex; align-items:center; gap:8px; }
.title { flex:1; font-weight:600; }
.body { display:grid; grid-template-columns: 1fr 1fr 320px; gap:8px; height: calc(100vh - 180px); }
.body.single { grid-template-columns: 1fr 320px; }
.pane { border:1px solid #ddd; border-radius:8px; overflow:auto; padding:8px; background:#fff; }
.sidebar { border:1px solid #ddd; border-radius:8px; overflow:auto; padding:8px; }
.pdf-status { padding: 16px; color: #666; }
.pdf-load-error { padding: 16px; color: #c00; font-size: 14px; line-height: 1.5; }
.pdf-page-wrap { margin-bottom: 12px; background: #f5f5f5; border-radius: 8px; padding: 8px; }
.pdf-page-meta { font-size: 12px; color: #666; margin-bottom: 6px; }
.pdf-canvas { width: 100%; background: #fafafa; border-radius: 4px; }
.translate-status { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
.translate-debug { font-size: 12px; color: #777; }
.translate-error { padding: 12px; color: #c00; font-size: 13px; }
.translate-empty { padding: 12px; color: #666; font-size: 13px; }
.tr-item { border-bottom:1px solid #eee; padding:8px 0; cursor:pointer; }
.meta { font-size:12px; color:#666; }
.note { font-size:12px; margin:6px 0; padding:6px; background:#f7f7f7; border-radius:6px; }
.readonly { opacity: 0.7; }
.qa-answer { font-size:12px; white-space: pre-wrap; margin-top:6px; }
.qa-ref { font-size:12px; color:#1f66cc; cursor:pointer; margin-top:4px; }
</style>
