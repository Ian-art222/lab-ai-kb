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
        <PdfCanvasViewer
          ref="pdfViewerRef"
          :file-id="currentFileId"
          @scroll="onLeftScroll"
        />

        <section v-if="dualPane" ref="rightPaneRef" class="pane right" @scroll="onRightScroll">
          <div class="translate-status">
            <el-tag v-if="translationState === 'idle'">未翻译</el-tag>
            <el-tag v-else-if="translationState === 'pending'">排队中</el-tag>
            <el-tag v-else-if="translationState === 'running'">翻译中 {{ translationProgress }}%</el-tag>
            <el-tag v-else-if="translationState === 'completed'" type="success">已完成</el-tag>
            <el-tag v-else-if="translationState === 'empty'" type="info">暂无译文</el-tag>
            <el-tag v-else-if="translationState === 'failed'" type="danger">翻译失败</el-tag>
            <span class="translate-debug">{{ translationDebugMessage }}</span>
          </div>

          <div v-if="translationErrorMessage" class="translate-error">{{ translationErrorMessage }}</div>
          <div v-if="translationContentReadError" class="translate-error content-read-hint">
            {{ translationContentReadError }}
          </div>
          <div
            v-if="!translationErrorMessage && !translationContentReadError && translationItems.length === 0"
            class="translate-empty"
          >
            暂无译文内容
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
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AdminLayout from '../layouts/AdminLayout.vue'
import PdfCanvasViewer from '../components/pdf/PdfCanvasViewer.vue'
import { usePdfTranslation } from '@/composables/usePdfTranslation'
import {
  addAttachmentApi,
  askPdfQaApi,
  createAnnotationApi,
  downloadPdfBundleApi,
  deleteAnnotationApi,
  getAnnotationsByUserApi,
  getMyAnnotationsApi,
  getPdfDocumentApi,
  listAttachmentsApi,
  listPublicAnnotationUsersApi,
  selectionTranslateApi,
  triggerPdfTranslateApi,
} from '../api/pdfDocuments'

const route = useRoute()
const router = useRouter()
const currentFileId = computed(() => Number(route.params.fileId))

const dualPane = ref(true)
const linkedScroll = ref(true)
const pdfViewerRef = ref<{
  scrollToPage: (n?: number | null) => void
  getLeftScrollElement: () => HTMLElement | null
} | null>(null)
const rightPaneRef = ref<HTMLElement | null>(null)

const docInfo = ref<any>(null)
const translating = ref(false)

const {
  translationState,
  translationProgress,
  translationItems,
  translationErrorMessage,
  translationContentReadError,
  translationDebugMessage,
  refreshTranslation,
} = usePdfTranslation(currentFileId)

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

function normalizeErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message
  if (typeof error === 'string' && error.trim()) return error
  return fallback
}

function onLeftScroll(ev: Event) {
  if (!linkedScroll.value || !rightPaneRef.value) return
  const left = ev.currentTarget as HTMLElement
  const ratio = left.scrollTop / Math.max(1, left.scrollHeight - left.clientHeight)
  rightPaneRef.value.scrollTop = ratio * Math.max(0, rightPaneRef.value.scrollHeight - rightPaneRef.value.clientHeight)
}

function onRightScroll() {
  if (!linkedScroll.value || !rightPaneRef.value) return
  const left = pdfViewerRef.value?.getLeftScrollElement?.()
  if (!left) return
  const ratio = rightPaneRef.value.scrollTop / Math.max(1, rightPaneRef.value.scrollHeight - rightPaneRef.value.clientHeight)
  left.scrollTop = ratio * Math.max(0, left.scrollHeight - left.clientHeight)
}

function jumpToPage(pageNumber?: number | null) {
  pdfViewerRef.value?.scrollToPage(pageNumber)
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

watch(dualPane, (v) => {
  if (v && Number.isFinite(currentFileId.value) && currentFileId.value > 0) {
    void refreshTranslation(currentFileId.value)
  }
})
</script>

<style scoped>
.pdf-reader {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.title {
  flex: 1;
  font-weight: 600;
}
.body {
  display: grid;
  grid-template-columns: 1fr 1fr 320px;
  gap: 8px;
  height: calc(100vh - 180px);
}
.body.single {
  grid-template-columns: 1fr 320px;
}
.pane {
  border: 1px solid #ddd;
  border-radius: 8px;
  overflow: auto;
  padding: 8px;
  background: #fff;
}
.sidebar {
  border: 1px solid #ddd;
  border-radius: 8px;
  overflow: auto;
  padding: 8px;
}
.translate-status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.translate-debug {
  font-size: 12px;
  color: #777;
}
.translate-error {
  padding: 12px;
  color: #c00;
  font-size: 13px;
  white-space: pre-wrap;
}
.content-read-hint {
  color: #a60;
  margin-top: 4px;
}
.translate-empty {
  padding: 12px;
  color: #666;
  font-size: 13px;
}
.tr-item {
  border-bottom: 1px solid #eee;
  padding: 8px 0;
  cursor: pointer;
}
.meta {
  font-size: 12px;
  color: #666;
}
.note {
  font-size: 12px;
  margin: 6px 0;
  padding: 6px;
  background: #f7f7f7;
  border-radius: 6px;
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
</style>
