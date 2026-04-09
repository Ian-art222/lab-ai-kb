<template>
  <AdminLayout>
    <div class="pdf-reader">
      <div class="topbar">
        <el-button @click="router.back()">返回</el-button>
        <div class="title">{{ docInfo?.doc?.title || `PDF #${fileId}` }}</div>
        <el-switch v-model="dualPane" active-text="双栏" inactive-text="单栏" />
        <el-switch v-model="linkedScroll" active-text="联动滚动" inactive-text="解耦滚动" />
        <el-button :loading="translating" @click="triggerTranslate">全文翻译</el-button>
        <el-button @click="downloadOriginal">下载原文</el-button>
        <el-button @click="downloadBundle">下载原文+译文</el-button>
      </div>

      <div class="body" :class="{ single: !dualPane }">
        <section ref="leftPaneRef" class="pane left" @scroll="onLeftScroll">
          <div v-if="pdfLoadError" class="pdf-load-error">{{ pdfLoadError }}</div>
          <template v-else>
            <div v-for="p in pageCount" :key="p" :data-page="p" class="pdf-page-wrap">
              <canvas :ref="(el) => bindCanvas(el, p)" class="pdf-canvas" />
            </div>
          </template>
        </section>

        <section v-if="dualPane" ref="rightPaneRef" class="pane right" @scroll="onRightScroll">
          <div class="translate-status">
            <el-tag v-if="translationStatus === 'not_started'">未翻译</el-tag>
            <el-tag v-else-if="translationStatus === 'running'">翻译中 {{ translationProgress }}%</el-tag>
            <el-tag v-else-if="translationStatus === 'completed'" type="success">已完成</el-tag>
            <el-tag v-else type="danger">{{ translationStatus }}</el-tag>
          </div>
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
          <div v-for="ref in qaRefs" :key="`${ref.chunk_id}-${ref.page_number}`" class="qa-ref" @click="jumpToPage(ref.page_number)">
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
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import * as pdfjsLib from 'pdfjs-dist'
import workerSrcImport from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import AdminLayout from '../layouts/AdminLayout.vue'
import { apiFetchBinary, readApiErrorMessage } from '../api/client'
import {
  addAttachmentApi,
  askPdfQaApi,
  createAnnotationApi,
  deleteAnnotationApi,
  downloadPdfBundleApi,
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

// Vite：worker 资源 URL 需相对当前模块解析，否则在子路径部署或打包后可能 404 → PDF.js 报 Failed to fetch
;(pdfjsLib as any).GlobalWorkerOptions.workerSrc = new URL(
  workerSrcImport,
  import.meta.url,
).href

const route = useRoute()
const router = useRouter()
const fileId = Number(route.params.fileId)

const dualPane = ref(true)
const linkedScroll = ref(true)
const leftPaneRef = ref<HTMLElement | null>(null)
const rightPaneRef = ref<HTMLElement | null>(null)

const docInfo = ref<any>(null)
const pdfLoadError = ref<string | null>(null)
const pageCount = ref(0)
const translating = ref(false)
const translationStatus = ref('not_started')
const translationProgress = ref(0)
const translationItems = ref<any[]>([])
const canvasMap = new Map<number, HTMLCanvasElement>()

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

function bindCanvas(el: any, pageNo: number) {
  if (el instanceof HTMLCanvasElement) {
    canvasMap.set(pageNo, el)
    void renderPage(pageNo)
  }
}

async function renderPage(pageNo: number) {
  if (!pdfDoc) return
  const canvas = canvasMap.get(pageNo)
  if (!canvas) return
  const page = await pdfDoc.getPage(pageNo)
  const viewport = page.getViewport({ scale: 1.25 })
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  canvas.width = viewport.width
  canvas.height = viewport.height
  await page.render({ canvasContext: ctx, viewport }).promise
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

async function refreshTranslation() {
  try {
    const status = await getPdfTranslationStatusApi(fileId)
    translationStatus.value = status.status || 'not_started'
    translationProgress.value = status.progress || 0
    if (status.status === 'completed') {
      const content = await getPdfTranslationContentApi(fileId)
      translationItems.value = content.content?.items || []
    } else {
      translationItems.value = []
    }
  } catch (e) {
    translationStatus.value = 'not_started'
    translationItems.value = []
    const msg = e instanceof Error ? e.message : '获取翻译状态失败'
    ElMessage.warning(msg)
  }
}

async function triggerTranslate() {
  try {
    translating.value = true
    await triggerPdfTranslateApi(fileId)
    await refreshTranslation()
    ElMessage.success('已触发翻译任务')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '翻译失败')
  } finally {
    translating.value = false
  }
}

function downloadOriginal() {
  void downloadPdfBundleApi(fileId, false)
}
function downloadBundle() {
  void downloadPdfBundleApi(fileId, true)
}

async function addNote() {
  const text = window.getSelection()?.toString().trim() || `note-${Date.now()}`
  await createAnnotationApi(fileId, { annotation_json: { text }, is_public: false })
  myAnnotations.value = await getMyAnnotationsApi(fileId)
}

async function removeNote(id: number) {
  await deleteAnnotationApi(fileId, id)
  myAnnotations.value = await getMyAnnotationsApi(fileId)
}

async function loadPublicAnnotations() {
  if (!selectedPublicUser.value) return
  publicAnnotations.value = await getAnnotationsByUserApi(fileId, selectedPublicUser.value)
}

async function askQa() {
  if (!qaQuestion.value.trim()) return
  qaLoading.value = true
  try {
    const res = await askPdfQaApi(fileId, qaQuestion.value)
    qaAnswer.value = res.answer
    qaRefs.value = res.references || []
  } finally {
    qaLoading.value = false
  }
}

async function translateSelection() {
  const text = window.getSelection()?.toString().trim()
  if (!text) return
  const res = await selectionTranslateApi(fileId, text)
  selectionTranslation.value = res.translated
}

onMounted(async () => {
  try {
    docInfo.value = await getPdfDocumentApi(fileId)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '获取文献详情失败')
    return
  }

  // 二进制下载：专用 apiFetchBinary，避免与 JSON 封装混用；URL 使用 buildApiUrl 保证绝对地址
  try {
    pdfLoadError.value = null
    const res = await apiFetchBinary(`/files/${fileId}/download`)
    if (!res.ok) {
      throw new Error(await readApiErrorMessage(res, '下载 PDF 失败'))
    }
    const buf = await res.arrayBuffer()
    if (buf.byteLength === 0) {
      throw new Error('下载的 PDF 为空（0 字节）')
    }
    const loadingTask = pdfjsLib.getDocument({ data: new Uint8Array(buf) })
    pdfDoc = await loadingTask.promise
    pageCount.value = pdfDoc.numPages || 0
    if (!pageCount.value) {
      const msg = '该 PDF 页数为 0，无法渲染'
      pdfLoadError.value = msg
      ElMessage.warning(msg)
    }
  } catch (e) {
    const msg =
      e instanceof Error ? e.message : typeof e === 'string' ? e : '加载 PDF 失败'
    pdfLoadError.value = `PDF 加载失败：${msg}`
    ElMessage.error(pdfLoadError.value)
  }

  try {
    myAnnotations.value = await getMyAnnotationsApi(fileId)
    publicUserIds.value = (await listPublicAnnotationUsersApi(fileId)).user_ids || []
    attachments.value = await listAttachmentsApi(fileId)
  } catch {
    /* 侧栏失败不阻塞阅读 */
  }

  await refreshTranslation()

  if (attachments.value.length === 0) {
    try {
      await addAttachmentApi(fileId, fileId, '原始文献')
      attachments.value = await listAttachmentsApi(fileId)
    } catch {
      // ignore
    }
  }
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
.pdf-load-error { padding: 16px; color: #c00; font-size: 14px; line-height: 1.5; }
.pdf-page-wrap { margin-bottom: 12px; }
.pdf-canvas { width: 100%; background: #fafafa; }
.tr-item { border-bottom:1px solid #eee; padding:8px 0; cursor:pointer; }
.meta { font-size:12px; color:#666; }
.note { font-size:12px; margin:6px 0; padding:6px; background:#f7f7f7; border-radius:6px; }
.readonly { opacity: 0.7; }
.qa-answer { font-size:12px; white-space: pre-wrap; margin-top:6px; }
.qa-ref { font-size:12px; color:#1f66cc; cursor:pointer; margin-top:4px; }
</style>
