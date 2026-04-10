<template>
  <AdminLayout>
    <div
      ref="readerShellRef"
      class="reader-shell"
      :class="{ 'is-split-dragging': splitDragging, 'is-col-split-dragging': colSplitDragging }"
    >
      <div class="topbar">
        <el-button @click="router.back()">返回</el-button>
        <div class="title">{{ docInfo?.doc?.title || `PDF #${currentFileId}` }}</div>
        <div class="topbar-actions">
          <el-button @click="toggleReaderFullscreen">
            {{ isReaderFullscreen ? '退出全屏' : '全屏阅读' }}
          </el-button>
          <el-button type="primary" plain @click="downloadOriginal">下载原文</el-button>
        </div>
      </div>

      <div ref="bodyRef" class="body">
        <div class="pdf-main">
          <PdfCanvasViewer ref="pdfViewerRef" :file-id="currentFileId" />
        </div>

        <div
          ref="bodyColDividerRef"
          class="body-col-divider"
          title="拖拽调整侧栏宽度"
          @pointerdown="onColSplitPointerDown"
          @pointermove="onColSplitPointerMove"
          @pointerup="onColSplitPointerUp"
          @pointercancel="onColSplitPointerUp"
        />

        <aside class="reader-right-rail" :style="{ width: `${sidebarWidthPx}px`, flexShrink: 0 }">
          <div ref="sidebarStackRef" class="sidebar-stack">
            <div v-if="!notesWorkspaceOpen" class="rstrip" role="button" tabindex="0" @click="notesWorkspaceOpen = true">
              <span class="rstrip-label">笔记工作区</span>
              <el-icon class="rstrip-icon"><ArrowDown /></el-icon>
            </div>

            <div
              v-else
              class="rpanel rpanel-notes"
              :class="{ 'rpanel--fill': !aiAssistantOpen }"
              :style="notesFlexStyle"
            >
              <div class="rpanel-head">
                <span class="rpanel-title">笔记工作区</span>
                <el-button link type="primary" class="rpanel-toggle" @click.stop="notesWorkspaceOpen = false">
                  <el-icon><ArrowUp /></el-icon>
                  收起
                </el-button>
              </div>
              <!-- 列表与内嵌编辑器分列：编辑器固定在笔记区底部（AI 分隔条上方），不放在列表滚动层内，避免被误认为浮层 -->
              <div class="rpanel-notes-shell">
                <div class="notes-lists-scroll">
                  <div class="notes-section">
                    <div class="notes-section-head">
                      <span class="notes-section-title">我的笔记</span>
                      <el-button size="small" @click.stop="openMyNoteCreate">新增</el-button>
                    </div>
                    <div v-for="a in myAnnotations" :key="a.id" class="note note-row" @click="openMyNoteEdit(a)">
                      <div class="note-preview">{{ notePreviewTitle(a) }}</div>
                      <el-button link type="danger" @click.stop="removeNote(a.id)">删除</el-button>
                    </div>
                  </div>

                  <div class="notes-section">
                    <div class="notes-section-title">实验室笔记</div>
                    <p v-if="labPublicAnnotations.length === 0" class="lab-notes-empty">暂无实验室公开笔记</p>
                    <div
                      v-for="row in labPublicAnnotations"
                      :key="row.id"
                      class="note readonly lab-note-row"
                      @click="openLabNoteReadonly(row)"
                    >
                      <div class="lab-note-preview">{{ notePreviewTitle(row) }}</div>
                      <div class="lab-note-author">{{ labAuthorLabel(row) }}</div>
                    </div>
                  </div>

                  <div class="notes-section notes-section--attachments">
                    <div class="notes-section-title">附件</div>
                    <input
                      ref="attachmentInputRef"
                      type="file"
                      class="reader-hidden-file-input"
                      @change="onAttachmentFileSelected"
                    />
                    <el-button size="small" :loading="attachmentUploading" @click.stop="openAttachmentPicker">
                      上传附件
                    </el-button>
                    <p class="attachments-hint">文件会先上传到与本文献相同的文件夹，再关联到本页。</p>
                    <div v-for="att in attachments" :key="att.id" class="note">{{ att.title || `file#${att.file_id}` }}</div>
                  </div>
                </div>

                <div v-if="noteEditorOpen" class="notes-editor-embed">
                  <PdfNoteEditorPanel
                    :key="`${noteEditorMode}-${noteEditorNote?.id ?? 'new'}`"
                    :file-id="currentFileId"
                    :mode="noteEditorMode"
                    :note="noteEditorNote"
                    :get-pdf-selection="getPdfSelectionText"
                    @close="closeNoteEditor"
                    @saved="handleNoteEditorSaved"
                  />
                </div>
              </div>
            </div>

            <div
              v-if="notesWorkspaceOpen && aiAssistantOpen"
              ref="splitDividerRef"
              class="rdivider"
              title="拖拽调整笔记区与 AI 区高度"
              @pointerdown="onSplitPointerDown"
              @pointermove="onSplitPointerMove"
              @pointerup="onSplitPointerUp"
              @pointercancel="onSplitPointerUp"
            />

            <div v-if="!aiAssistantOpen" class="rstrip" role="button" tabindex="0" @click="aiAssistantOpen = true">
              <span class="rstrip-label">AI 助手</span>
              <el-icon class="rstrip-icon"><ArrowDown /></el-icon>
            </div>

            <div v-else class="rpanel rpanel-ai" :class="{ 'rpanel--fill': !notesWorkspaceOpen }" :style="aiFlexStyle">
              <div class="rpanel-head">
                <span class="rpanel-title">AI 助手</span>
                <el-button link type="primary" class="rpanel-toggle" @click.stop="aiAssistantOpen = false">
                  <el-icon><ArrowUp /></el-icon>
                  收起
                </el-button>
              </div>
              <div class="rpanel-body rpanel-body--qa">
                <p class="qa-hint">
                  与「知识库问答」共用后端：请在<strong>管理后台 · 系统设置</strong>中配置聊天模型并开启问答；也可在部署环境变量中设置（示例：
                  <code>LLM_PROVIDER=deepseek</code>、<code>LLM_API_BASE=https://api.deepseek.com</code>、<code>LLM_MODEL=deepseek-chat</code>）。本文献须为<strong>已索引</strong>，且 Embedding 配置正确，否则会失败。
                </p>
                <p v-if="pdfIndexStatus && pdfIndexStatus !== 'indexed'" class="qa-warn">
                  当前文献索引状态：<strong>{{ pdfIndexStatus }}</strong>，请先在该文件的文件中心里完成索引后再提问。
                </p>
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
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  </AdminLayout>
</template>

<script setup lang="ts">
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AdminLayout from '../layouts/AdminLayout.vue'
import PdfCanvasViewer from '../components/pdf/PdfCanvasViewer.vue'
import PdfNoteEditorPanel from '../components/pdf/PdfNoteEditorPanel.vue'
import { notePreviewTitle } from '../components/pdf/pdfNoteUtils'
import { uploadFileApi } from '../api/files'
import {
  addAttachmentApi,
  askPdfQaApi,
  deleteAnnotationApi,
  downloadPdfOriginalApi,
  getMyAnnotationsApi,
  getPdfDocumentApi,
  listAttachmentsApi,
  listLabPublicAnnotationsApi,
} from '../api/pdfDocuments'

const route = useRoute()
const router = useRouter()
const currentFileId = computed(() => Number(route.params.fileId))

/** 与列表/详情一致：来自 pdf-documents 接口的 file_record.index_status */
const pdfIndexStatus = computed(() => {
  const d = docInfo.value
  if (!d) return ''
  return (d.doc?.index_status ?? d.file?.index_status ?? '') as string
})

const readerShellRef = ref<HTMLElement | null>(null)
const bodyRef = ref<HTMLElement | null>(null)
const bodyColDividerRef = ref<HTMLElement | null>(null)
/** 右侧总栏宽度（px），与 PDF 区间可左右拖拽调整 */
const sidebarWidthPx = ref(340)
const colSplitDragging = ref(false)
let colDragStartX = 0
let colDragStartW = 0

const COL_DIVIDER_W = 8
const SIDEBAR_MIN_W = 280
const PDF_MAIN_MIN_W = 380
const SIDEBAR_MAX_RATIO = 0.5

function colSidebarClampRange() {
  const body = bodyRef.value
  if (!body) {
    return { min: SIDEBAR_MIN_W, max: 480 }
  }
  const total = body.getBoundingClientRect().width
  const maxByPdf = total - PDF_MAIN_MIN_W - COL_DIVIDER_W
  const maxByRatio = Math.floor(total * SIDEBAR_MAX_RATIO)
  let max = Math.min(maxByPdf, maxByRatio)
  if (max < SIDEBAR_MIN_W) {
    /* 极窄：允许侧栏略小于理想下限，避免 max < min；PDF 区可能触发横向滚动 */
    max = Math.max(220, total - 260 - COL_DIVIDER_W)
  }
  max = Math.max(max, 220)
  const min = Math.min(SIDEBAR_MIN_W, max)
  return { min, max }
}

function onColSplitPointerDown(e: PointerEvent) {
  e.preventDefault()
  const bar = bodyColDividerRef.value
  if (!bar) return
  colSplitDragging.value = true
  colDragStartX = e.clientX
  colDragStartW = sidebarWidthPx.value
  bar.setPointerCapture(e.pointerId)
}

function onColSplitPointerMove(e: PointerEvent) {
  if (!colSplitDragging.value) return
  const { min, max } = colSidebarClampRange()
  const dx = e.clientX - colDragStartX
  sidebarWidthPx.value = Math.min(max, Math.max(min, colDragStartW + dx))
}

function onColSplitPointerUp(e: PointerEvent) {
  if (!colSplitDragging.value) return
  colSplitDragging.value = false
  try {
    bodyColDividerRef.value?.releasePointerCapture(e.pointerId)
  } catch {
    /* ignore */
  }
}

const isReaderFullscreen = ref(false)

const pdfViewerRef = ref<{
  scrollToPage: (n?: number | null) => void
  getLeftScrollElement: () => HTMLElement | null
  setCssScale?: (n: number) => void
} | null>(null)
const docInfo = ref<any>(null)

const myAnnotations = ref<any[]>([])
/** 本文献下实验室可见笔记（聚合，含 username） */
const labPublicAnnotations = ref<any[]>([])
const attachments = ref<any[]>([])
const attachmentInputRef = ref<HTMLInputElement | null>(null)
const attachmentUploading = ref(false)

const qaQuestion = ref('')
const qaLoading = ref(false)
const qaAnswer = ref('')
const qaRefs = ref<any[]>([])

const sidebarStackRef = ref<HTMLElement | null>(null)
const splitDividerRef = ref<HTMLElement | null>(null)
const notesWorkspaceOpen = ref(true)
const aiAssistantOpen = ref(true)
/** 两区均展开时，笔记区所占高度比例（剩余为 AI 区） */
const splitRatio = ref(0.52)
const splitDragging = ref(false)
let splitDragStartY = 0
let splitDragStartRatio = 0
let splitDragShellH = 400

const splitGrowNotes = computed(() => Math.max(22, Math.round(splitRatio.value * 100)))
const splitGrowAi = computed(() => Math.max(22, 100 - splitGrowNotes.value))

const notesFlexStyle = computed(() => {
  if (!notesWorkspaceOpen.value) return {}
  if (!aiAssistantOpen.value) {
    return { flex: '1 1 auto', minHeight: '0' }
  }
  return { flex: `${splitGrowNotes.value} 1 0px`, minHeight: '120px' }
})

const aiFlexStyle = computed(() => {
  if (!aiAssistantOpen.value) return {}
  if (!notesWorkspaceOpen.value) {
    return { flex: '1 1 auto', minHeight: '0' }
  }
  return { flex: `${splitGrowAi.value} 1 0px`, minHeight: '100px' }
})

function onSplitPointerDown(e: PointerEvent) {
  if (!notesWorkspaceOpen.value || !aiAssistantOpen.value) return
  e.preventDefault()
  const bar = splitDividerRef.value
  if (!bar) return
  splitDragging.value = true
  splitDragStartY = e.clientY
  splitDragStartRatio = splitRatio.value
  const shell = sidebarStackRef.value
  splitDragShellH = shell ? Math.max(160, shell.getBoundingClientRect().height - 8) : 400
  bar.setPointerCapture(e.pointerId)
}

function onSplitPointerMove(e: PointerEvent) {
  if (!splitDragging.value) return
  const dy = e.clientY - splitDragStartY
  const next = splitDragStartRatio - dy / splitDragShellH
  splitRatio.value = Math.min(0.78, Math.max(0.22, next))
}

function onSplitPointerUp(e: PointerEvent) {
  if (!splitDragging.value) return
  splitDragging.value = false
  try {
    splitDividerRef.value?.releasePointerCapture(e.pointerId)
  } catch {
    /* ignore */
  }
}

type NoteDialogPayload = {
  id: number
  is_public?: boolean
  annotation_json?: Record<string, unknown> | null
  username?: string
}

const noteEditorOpen = ref(false)
const noteEditorMode = ref<'create' | 'edit' | 'readonly'>('create')
const noteEditorNote = ref<NoteDialogPayload | null>(null)

function getPdfSelectionText() {
  return window.getSelection()?.toString() ?? ''
}

function closeNoteEditor() {
  noteEditorOpen.value = false
  noteEditorNote.value = null
}

async function handleNoteEditorSaved() {
  await onNoteSaved()
  closeNoteEditor()
}

function openMyNoteCreate() {
  noteEditorMode.value = 'create'
  noteEditorNote.value = null
  noteEditorOpen.value = true
}

function openMyNoteEdit(a: { id: number; is_public?: boolean; annotation_json?: unknown }) {
  noteEditorMode.value = 'edit'
  noteEditorNote.value = {
    id: a.id,
    is_public: a.is_public,
    annotation_json: (a.annotation_json as Record<string, unknown> | null) ?? null,
  }
  noteEditorOpen.value = true
}

function labAuthorLabel(row: { username?: string | null; user_id?: number }) {
  const name = row.username != null ? String(row.username).trim() : ''
  if (name) return name
  if (row.user_id != null && Number.isFinite(Number(row.user_id))) return `用户 ${row.user_id}`
  return '未知作者'
}

function openLabNoteReadonly(row: {
  id: number
  user_id?: number
  username?: string | null
  annotation_json?: unknown
  is_public?: boolean
}) {
  noteEditorMode.value = 'readonly'
  noteEditorNote.value = {
    id: row.id,
    is_public: row.is_public ?? true,
    annotation_json: (row.annotation_json as Record<string, unknown> | null) ?? null,
    username: labAuthorLabel(row),
  }
  noteEditorOpen.value = true
}

async function onNoteSaved() {
  const fid = currentFileId.value
  if (!Number.isFinite(fid) || fid <= 0) return
  try {
    myAnnotations.value = await getMyAnnotationsApi(fid)
    await loadLabPublicAnnotations(fid)
  } catch {
    /* 与 loadReaderMeta 侧栏策略一致：刷新失败不阻塞 */
  }
}

function syncFullscreenFlag() {
  isReaderFullscreen.value = document.fullscreenElement === readerShellRef.value
  requestAnimationFrame(() => clampSidebarWidthToBody())
}

async function toggleReaderFullscreen() {
  const el = readerShellRef.value
  if (!el) return
  try {
    if (!document.fullscreenElement) {
      await el.requestFullscreen()
    } else {
      await document.exitFullscreen()
    }
  } catch {
    ElMessage.warning('无法进入全屏，请检查浏览器权限')
  }
}

function normalizeErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message
  if (typeof error === 'string' && error.trim()) return error
  return fallback
}

function jumpToPage(pageNumber?: number | null) {
  pdfViewerRef.value?.scrollToPage(pageNumber)
}

function downloadOriginal() {
  void downloadPdfOriginalApi(currentFileId.value)
}

async function removeNote(id: number) {
  const fid = currentFileId.value
  await deleteAnnotationApi(fid, id)
  myAnnotations.value = await getMyAnnotationsApi(fid)
  await loadLabPublicAnnotations(fid)
}

async function loadLabPublicAnnotations(fileId: number) {
  if (!Number.isFinite(fileId) || fileId <= 0) return
  try {
    labPublicAnnotations.value = await listLabPublicAnnotationsApi(fileId)
  } catch {
    labPublicAnnotations.value = []
  }
}

function openAttachmentPicker() {
  attachmentInputRef.value?.click()
}

async function onAttachmentFileSelected(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return

  const folderId = docInfo.value?.file?.folder_id
  attachmentUploading.value = true
  try {
    const uploaded = await uploadFileApi(file, folderId ?? null)
    const newId = typeof uploaded?.id === 'number' ? uploaded.id : Number(uploaded?.id)
    if (!Number.isFinite(newId)) throw new Error('上传返回无效')
    await addAttachmentApi(currentFileId.value, newId, file.name)
    attachments.value = await listAttachmentsApi(currentFileId.value)
    ElMessage.success('附件已添加')
  } catch (e) {
    ElMessage.error(normalizeErrorMessage(e, '上传或关联附件失败'))
  } finally {
    attachmentUploading.value = false
  }
}

async function askQa() {
  if (!qaQuestion.value.trim()) return
  qaLoading.value = true
  try {
    const res = await askPdfQaApi(currentFileId.value, qaQuestion.value)
    qaAnswer.value = (res?.answer ?? '') as string
    qaRefs.value = (res?.references ?? []) as any[]
    if (!qaAnswer.value.trim() && (!qaRefs.value || qaRefs.value.length === 0)) {
      ElMessage.warning('未返回答案或引用，请确认文献已索引且后台已开启问答并配置 LLM。')
    }
  } catch (e) {
    ElMessage.error(normalizeErrorMessage(e, '文献问答失败'))
  } finally {
    qaLoading.value = false
  }
}

async function loadReaderMeta(fileId: number) {
  try {
    docInfo.value = await getPdfDocumentApi(fileId)
  } catch (e) {
    ElMessage.error(normalizeErrorMessage(e, '获取文献详情失败'))
    return
  }

  try {
    myAnnotations.value = await getMyAnnotationsApi(fileId)
    attachments.value = await listAttachmentsApi(fileId)
    await loadLabPublicAnnotations(fileId)
  } catch {
    /* 侧栏失败不阻塞阅读 */
  }

  if (attachments.value.length === 0) {
    try {
      await addAttachmentApi(fileId, fileId, '原始文献')
      attachments.value = await listAttachmentsApi(fileId)
    } catch {
      /* ignore */
    }
  }
}

watch(
  currentFileId,
  (nextId) => {
    if (Number.isFinite(nextId) && nextId > 0) {
      void loadReaderMeta(nextId)
    }
  },
  { immediate: true },
)

function clampSidebarWidthToBody() {
  const { min, max } = colSidebarClampRange()
  sidebarWidthPx.value = Math.min(max, Math.max(min, sidebarWidthPx.value))
}

onMounted(() => {
  document.addEventListener('fullscreenchange', syncFullscreenFlag)
  window.addEventListener('resize', clampSidebarWidthToBody)
  requestAnimationFrame(() => clampSidebarWidthToBody())
})
onUnmounted(() => {
  document.removeEventListener('fullscreenchange', syncFullscreenFlag)
  window.removeEventListener('resize', clampSidebarWidthToBody)
})
</script>

<style scoped>
.reader-shell {
  display: flex;
  flex-direction: column;
  min-height: 0;
  max-height: calc(100vh - 72px);
  box-sizing: border-box;
}

.reader-shell:fullscreen {
  max-height: none;
  height: 100%;
  padding: 12px;
  background: #f5f5f5;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  margin-bottom: 8px;
}

.title {
  flex: 1;
  min-width: 0;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.body {
  display: flex;
  flex-direction: row;
  flex: 1;
  min-height: 0;
  min-width: 0;
  align-items: stretch;
  gap: 0;
  overflow-x: auto;
}

.body-col-divider {
  flex: 0 0 8px;
  margin: 0 4px;
  align-self: stretch;
  border-radius: 4px;
  background: var(--el-border-color);
  cursor: col-resize;
  touch-action: none;
}

.body-col-divider:hover {
  background: var(--el-color-primary-light-7);
}

.reader-shell:fullscreen .body {
  flex: 1;
  min-height: 0;
}

.pdf-main {
  flex: 1 1 auto;
  min-width: 380px;
  min-height: 0;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
  display: flex;
  flex-direction: column;
  /* 主列占满剩余宽度，阅读区在列内通过 PdfCanvasViewer 居中对齐画布 */
}

.pdf-main :deep(.pdf-canvas-viewer) {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.reader-right-rail {
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  overflow: hidden;
  padding: 10px;
  background: #fff;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.reader-right-rail .sidebar-stack {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.rstrip {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  margin-bottom: 6px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  cursor: pointer;
  user-select: none;
  border: 1px solid var(--el-border-color-lighter);
}

.rstrip:last-child {
  margin-bottom: 0;
}

.rstrip-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.rstrip-icon {
  color: var(--el-text-color-secondary);
}

.rpanel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.rpanel--fill {
  flex: 1 1 auto !important;
  min-height: 0;
}

.rpanel-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-bottom: 8px;
  margin-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.rpanel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.rpanel-toggle {
  flex-shrink: 0;
}

.rpanel-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.rpanel-notes-shell {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.notes-lists-scroll {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 2px;
  padding-bottom: 4px;
}

.notes-editor-embed {
  flex-shrink: 0;
  max-height: min(48vh, 440px);
  overflow-x: hidden;
  overflow-y: auto;
  padding-top: 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-light);
}

.notes-section {
  margin-bottom: 14px;
}

.notes-section:last-child {
  margin-bottom: 0;
}

.notes-section-title {
  display: block;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--el-text-color-regular);
}

.notes-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.notes-section-head .notes-section-title {
  margin-bottom: 0;
}

.rdivider {
  flex: 0 0 8px;
  margin: 4px 0;
  border-radius: 4px;
  background: var(--el-border-color);
  cursor: row-resize;
  touch-action: none;
}

.rdivider:hover {
  background: var(--el-color-primary-light-7);
}

.reader-shell.is-split-dragging {
  cursor: row-resize;
  user-select: none;
}

.reader-shell.is-col-split-dragging {
  cursor: col-resize;
  user-select: none;
}

.lab-notes-empty {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}

.lab-note-row {
  cursor: pointer;
  display: block;
  padding: 8px;
}

.lab-note-preview {
  font-size: 12px;
  line-height: 1.4;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.lab-note-author {
  margin-top: 4px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.note {
  font-size: 12px;
  margin: 6px 0;
  padding: 6px;
  background: #f7f7f7;
  border-radius: 6px;
}
.note-row {
  cursor: pointer;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.note-preview {
  flex: 1;
  min-width: 0;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
}
.readonly {
  opacity: 0.7;
}
.qa-answer {
  font-size: 12px;
  white-space: pre-wrap;
  margin-top: 6px;
}
.qa-ref {
  font-size: 12px;
  color: #1f66cc;
  cursor: pointer;
  margin-top: 4px;
}

.reader-hidden-file-input {
  display: none;
}

.attachments-hint {
  margin: 6px 0 8px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}

.qa-hint {
  margin: 0 0 8px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  line-height: 1.45;
}

.qa-hint code {
  font-size: 10px;
  padding: 0 3px;
  border-radius: 3px;
  background: var(--el-fill-color-light);
}

.qa-warn {
  margin: 0 0 8px;
  font-size: 11px;
  color: var(--el-color-warning-dark-2);
  line-height: 1.4;
}
</style>
