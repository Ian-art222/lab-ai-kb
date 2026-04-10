<template>
  <div class="pdf-note-editor-panel">
    <div class="panel-head">
      <span class="panel-title">{{ panelTitle }}</span>
      <el-button link type="primary" @click="emitClose">{{ readonly ? '关闭' : '返回列表' }}</el-button>
    </div>

    <template v-if="readonly">
      <div class="readonly-meta">
        <span v-if="authorLabel">作者：{{ authorLabel }}</span>
        <el-tag v-if="labPublic" size="small" type="success" effect="plain">实验室可见</el-tag>
        <el-tag v-else size="small" type="info" effect="plain">仅本人</el-tag>
      </div>
      <h3 v-if="displayTitle" class="readonly-title">{{ displayTitle }}</h3>
      <div class="readonly-scroll">
        <div class="readonly-body" v-html="safeBodyHtml" />
      </div>
    </template>
    <template v-else>
      <el-input v-model="title" placeholder="笔记标题（可选）" maxlength="200" show-word-limit class="mb-8" />
      <div class="editor-wrap">
        <QuillEditor
          v-model:content="bodyHtml"
          content-type="html"
          theme="snow"
          :toolbar="toolbarOptions"
        />
      </div>
      <div class="note-extras">
        <el-switch v-model="isPublic" active-text="实验室可见" inactive-text="仅自己可见" />
        <el-button size="small" @click="insertPdfSelection">插入选中文字</el-button>
      </div>
      <p v-if="quoteFromPdf" class="quote-preview">
        <span class="quote-label">摘录：</span>{{ quoteFromPdf }}
      </p>
    </template>

    <div v-if="!readonly" class="panel-footer">
      <el-button @click="emitClose">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { QuillEditor } from '@vueup/vue-quill'
import '@vueup/vue-quill/dist/vue-quill.snow.css'
import DOMPurify from 'dompurify'
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { createAnnotationApi, updateAnnotationApi } from '@/api/pdfDocuments'
import {
  buildLiteratureNotePayload,
  noteBodyHtmlFromJson,
  notePreviewTitle,
  stripHtml,
} from './pdfNoteUtils'

const props = withDefaults(
  defineProps<{
    fileId: number
    /** create | edit | readonly */
    mode: 'create' | 'edit' | 'readonly'
    note?: {
      id: number
      is_public?: boolean
      annotation_json?: Record<string, unknown> | null
      username?: string
    } | null
    /** 从阅读区取选区 */
    getPdfSelection?: () => string
  }>(),
  {
    note: null,
    getPdfSelection: undefined,
  },
)

const emit = defineEmits<{
  close: []
  saved: []
}>()

function emitClose() {
  quoteFromPdf.value = ''
  emit('close')
}

const title = ref('')
const bodyHtml = ref('')
const isPublic = ref(false)
const quoteFromPdf = ref('')
const saving = ref(false)

const readonly = computed(() => props.mode === 'readonly')

const panelTitle = computed(() => {
  if (props.mode === 'create') return '新建笔记'
  if (props.mode === 'edit') return '编辑笔记'
  return '查看笔记'
})

const displayTitle = computed(() => {
  if (!props.note) return ''
  return notePreviewTitle(props.note)
})

const authorLabel = computed(() => props.note?.username || '')

const labPublic = computed(() => Boolean(props.note?.is_public))

const safeBodyHtml = computed(() => {
  const raw = noteBodyHtmlFromJson(props.note?.annotation_json || undefined)
  return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })
})

const toolbarOptions: unknown[] = [
  ['bold', 'italic', 'underline', 'strike'],
  ['blockquote', 'code-block'],
  [{ header: 1 }, { header: 2 }, { header: 3 }],
  [{ list: 'ordered' }, { list: 'bullet' }],
  ['clean'],
]

function resetForCreate() {
  title.value = ''
  bodyHtml.value = '<p><br></p>'
  isPublic.value = false
  quoteFromPdf.value = ''
}

function loadFromNote() {
  const n = props.note
  if (!n?.annotation_json) {
    resetForCreate()
    return
  }
  const j = n.annotation_json as Record<string, unknown>
  title.value = typeof j.title === 'string' ? j.title : ''
  bodyHtml.value = noteBodyHtmlFromJson(j) || '<p><br></p>'
  isPublic.value = Boolean(n.is_public)
  quoteFromPdf.value = typeof j.quote_from_pdf === 'string' ? j.quote_from_pdf : ''
}

watch(
  () => [props.mode, props.note?.id] as const,
  () => {
    if (props.mode === 'create') {
      resetForCreate()
      const t = props.getPdfSelection?.()?.trim()
      if (t) quoteFromPdf.value = t.slice(0, 2000)
    } else if (props.mode === 'edit') {
      loadFromNote()
    }
  },
  { immediate: true },
)

function insertPdfSelection() {
  const fn = props.getPdfSelection
  const t = fn?.()?.trim()
  if (!t) {
    ElMessage.info('请先在 PDF 中选中一段文字')
    return
  }
  quoteFromPdf.value = t.slice(0, 2000)
}

async function save() {
  const fid = props.fileId
  if (!Number.isFinite(fid) || fid <= 0) return
  const payloadJson = buildLiteratureNotePayload({
    title: title.value,
    bodyHtml: bodyHtml.value === '<p><br></p>' ? '' : bodyHtml.value,
    quoteFromPdf: quoteFromPdf.value || undefined,
  })
  const plainLen = payloadJson.body_html ? stripTagsLen(payloadJson.body_html as string) : 0
  if (!String(payloadJson.title || '').trim() && plainLen === 0) {
    ElMessage.warning('请填写标题或正文')
    return
  }
  saving.value = true
  try {
    if (props.mode === 'edit' && props.note?.id) {
      await updateAnnotationApi(fid, props.note.id, {
        annotation_json: payloadJson,
        is_public: isPublic.value,
      })
    } else {
      await createAnnotationApi(fid, { annotation_json: payloadJson, is_public: isPublic.value })
    }
    ElMessage.success('已保存')
    quoteFromPdf.value = ''
    emit('saved')
    emit('close')
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '保存失败')
  } finally {
    saving.value = false
  }
}

function stripTagsLen(html: string): number {
  return stripHtml(html).length
}
</script>

<style scoped>
/* 内嵌于阅读器右侧栏：禁止 fixed/居中浮层语义，仅用文档流布局 */
.pdf-note-editor-panel {
  position: relative;
  left: auto;
  top: auto;
  transform: none;
  z-index: auto;
  width: 100%;
  max-width: 100%;
  margin: 0;
  box-sizing: border-box;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 10px;
  background: var(--el-fill-color-blank);
  isolation: isolate;
}

.readonly-scroll {
  max-height: min(36vh, 320px);
  overflow-y: auto;
  overflow-x: hidden;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.panel-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.mb-8 {
  margin-bottom: 8px;
}
.editor-wrap {
  position: relative;
  min-height: 200px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  overflow: hidden;
}
.editor-wrap :deep(.ql-container) {
  min-height: 160px;
  font-size: 14px;
}
.note-extras {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.quote-preview {
  margin-top: 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.quote-label {
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.readonly-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  flex-wrap: wrap;
}
.readonly-title {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
}
.readonly-body {
  font-size: 13px;
  line-height: 1.6;
}
.readonly-body :deep(p) {
  margin: 0 0 0.6em;
}
</style>
