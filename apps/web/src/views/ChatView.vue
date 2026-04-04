<template>
  <AdminLayout>
    <div class="chat-shell">
      <aside class="chat-sidebar">
        <div class="sidebar-title">知识库问答</div>
        <el-radio-group v-model="scopeType" class="scope-switch">
          <el-radio-button value="all">全库</el-radio-button>
          <el-radio-button value="folder">当前目录</el-radio-button>
          <el-radio-button value="files">选中文件</el-radio-button>
        </el-radio-group>

        <div class="scope-panel">
          <template v-if="scopeType === 'folder'">
            <div class="panel-label">当前目录范围</div>
            <div class="folder-actions">
              <el-tag type="info">{{ selectedFolderLabel }}</el-tag>
              <div class="folder-action-buttons">
                <el-button size="small" @click="openFolderPicker">更换目录</el-button>
                <el-button size="small" @click="clearFolderScope">清空目录</el-button>
                <el-button size="small" type="warning" @click="switchToAllScope">
                  切回全库
                </el-button>
              </div>
            </div>
          </template>

          <template v-if="scopeType === 'files'">
            <div class="panel-label">选择文件范围</div>
            <el-select
              v-model="selectedFileIds"
              multiple
              filterable
              clearable
              collapse-tags
              collapse-tags-tooltip
              class="file-picker-select"
              placeholder="请选择要纳入问答范围的文件"
            >
              <el-option
                v-for="file in selectableFiles"
                :key="file.id"
                :label="getSelectableFileLabel(file)"
                :value="file.id"
              />
            </el-select>
            <div v-if="selectedFiles.length" class="selected-file-tags">
              <el-tag v-for="file in selectedFiles" :key="file.id" closable @close="removeSelectedFile(file.id)">
                {{ file.file_name }}
              </el-tag>
            </div>
          </template>
        </div>

        <div class="sidebar-block">
          <el-switch
            v-model="strictMode"
            active-text="严格基于知识库"
            inactive-text="非严格模式"
          />
        </div>

        <div class="sidebar-block">
          <el-button :disabled="scopeType === 'all'" @click="handleIndexScope">
            建立索引（最多 10 个）
          </el-button>
        </div>

        <div class="sidebar-block history-block">
          <div class="history-header">
            <div class="panel-label" style="margin-bottom: 0">会话列表</div>
            <el-button size="small" plain @click="startNewSession">新建问答</el-button>
          </div>
          <div v-if="sessionList.length" class="session-list">
            <div
              v-for="session in sessionList"
              :key="session.id"
              class="session-item"
              :class="{ 'session-item-active': session.id === currentSessionId }"
              @click="switchSession(session.id)"
            >
              <div class="session-main">
                <div class="session-title-row">
                  <div class="session-title">{{ session.title }}</div>
                  <el-tag size="small" :type="session.last_error ? 'danger' : 'info'">
                    {{ session.scope_type }}
                  </el-tag>
                </div>
                <div class="session-meta">{{ session.updated_at }}</div>
                <div class="session-preview">{{ session.last_question || '尚未提问' }}</div>
                <div v-if="session.last_error" class="session-error">{{ session.last_error }}</div>
              </div>
              <el-button
                size="small"
                text
                type="danger"
                @click.stop="handleDeleteSession(session.id)"
              >
                删除
              </el-button>
            </div>
          </div>
          <el-empty
            v-else
            description="暂无历史会话"
            :image-size="64"
            class="session-empty"
          />
          <div class="panel-label history-subtitle">当前会话记录</div>
          <div v-if="currentSessionId" class="session-tip">会话 ID：{{ currentSessionId }}</div>
          <div v-if="sessionHistory.length" class="history-list">
            <div
              v-for="item in sessionHistory"
              :key="item.id"
              class="history-item"
              @click="switchSession(item.session_id)"
            >
              <div class="history-role">{{ item.role === 'user' ? '问' : '答' }}</div>
              <div class="history-time">{{ item.created_at }}</div>
              <div class="history-text">{{ item.content }}</div>
            </div>
          </div>
        </div>
      </aside>

      <main class="chat-main">
        <div class="chat-header">
          <div class="chat-title">实验室智能检索问答</div>
          <div class="chat-meta">
            <el-tag :type="systemStore.status.qa_enabled ? 'success' : 'warning'">
              {{ systemStore.status.qa_enabled ? '问答已启用' : '问答未启用' }}
            </el-tag>
            <el-tag type="success">范围：{{ scopeLabel }}</el-tag>
          </div>
        </div>

        <div v-if="statusNotice" class="notice-wrap">
          <el-alert
            :title="statusNotice"
            type="warning"
            :closable="false"
          />
        </div>

        <div ref="messagesContainerRef" class="messages-area">
          <div v-if="messages.length === 0" class="dev-state">
            <el-result
              icon="success"
              :title="emptyStateTitle"
              :sub-title="emptyStateSubtitle"
            />
          </div>

          <div
            v-for="m in messages"
            :key="m.id"
            class="message-row"
            :class="{ 'message-row-user': m.role === 'user' }"
          >
            <div
              class="message-bubble"
              :class="{
                'message-bubble-user': m.role === 'user',
                'message-bubble-error': m.state === 'error',
                'message-bubble-loading': m.state === 'loading',
              }"
            >
              <div class="message-role">{{ m.role === 'user' ? '你' : '助手' }}</div>
              <div class="message-content">{{ m.content }}</div>

              <div v-if="m.role === 'assistant' && m.retrievalMeta" class="retrieval-meta">
                检索命中 {{ m.retrievalMeta.matched_chunks }} / {{ m.retrievalMeta.candidate_chunks }}
                ，阈值 {{ (m.retrievalMeta.min_score ?? 0).toFixed(2) }}
              </div>

              <div v-if="m.role === 'assistant' && m.references?.length" class="refs-wrap">
                <div class="refs-title">引用来源（可核查）</div>
                <div class="refs-list">
                  <div v-for="r in m.references" :key="`${m.id}-${r.chunk_id}-${r.chunk_index}`" class="ref-card">
                    <div class="ref-head">
                      <div class="ref-file">{{ r.file_name }}</div>
                      <el-tag size="small" type="warning">score {{ r.score.toFixed(3) }}</el-tag>
                    </div>
                    <div class="ref-meta">
                      <span>片段 #{{ r.chunk_index }}</span>
                      <span v-if="r.section_title">章节：{{ r.section_title }}</span>
                      <span v-if="r.page_number">页码：{{ r.page_number }}</span>
                    </div>
                    <div class="ref-snippet">{{ r.snippet }}</div>
                    <div class="ref-actions">
                      <el-button size="small" @click="handleOpenFileDetail(r.file_id)">
                        查看详情
                      </el-button>
                      <el-button size="small" type="primary" @click="handleDownload(r.file_id)">
                        下载
                      </el-button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="input-area">
          <el-input
            v-model="question"
            type="textarea"
            :rows="3"
            resize="none"
            :disabled="!canAsk"
            placeholder="输入问题后发送，将基于当前范围内已索引资料作答"
            @keydown.enter.exact.prevent="handleAsk"
          />
          <div class="input-actions">
            <el-button
              type="primary"
              :loading="sending"
              :disabled="!question.trim() || !canAsk"
              @click="handleAsk"
            >
              发送
            </el-button>
          </div>
        </div>
      </main>
    </div>

    <el-dialog v-model="folderPickerVisible" title="选择问答目录" width="520px">
      <div style="margin-bottom: 10px">
        <el-button :type="pickerFolderId === null ? 'primary' : 'default'" @click="pickerFolderId = null">
          home
        </el-button>
      </div>
      <el-tree
        :data="folderTree"
        node-key="id"
        :props="{ children: 'children', label: 'name' }"
        highlight-current
        default-expand-all
        :current-node-key="pickerFolderId ?? -1"
        @node-click="handlePickFolderNode"
      />
      <template #footer>
        <el-button @click="folderPickerVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmFolderPick">确认</el-button>
      </template>
    </el-dialog>
  </AdminLayout>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import AdminLayout from '../layouts/AdminLayout.vue'
import {
  downloadFileApi,
  getFilesApi,
  getFolderChildrenApi,
  getFolderTreeApi,
  type FileItem,
  type FolderTreeItem,
} from '../api/files'
import {
  askApi,
  createSessionApi,
  deleteSessionApi,
  getSessionsApi,
  getSessionMessagesApi,
  ingestFileApi,
  type AskReference,
  QaApiError,
  type QAMessageItem,
  type QASessionItem,
  type RetrievalMeta,
  type ScopeType,
} from '../api/qa'
import { useSystemStore } from '../stores/system'

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  state?: 'normal' | 'loading' | 'error'
  references?: AskReference[]
  retrievalMeta?: RetrievalMeta
}

const route = useRoute()
const router = useRouter()
const systemStore = useSystemStore()

const scopeType = ref<ScopeType>('all')
const strictMode = ref(true)
const folderId = ref<number | null>(null)
const folderName = ref('home')
const sending = ref(false)
const question = ref('')
const messages = ref<ChatMessage[]>([])
const messagesContainerRef = ref<HTMLElement | null>(null)

const folderTree = ref<FolderTreeItem[]>([])
const folderPickerVisible = ref(false)
const pickerFolderId = ref<number | null>(null)
const selectableFiles = ref<FileItem[]>([])
const selectedFileIds = ref<number[]>([])
const currentSessionId = ref<number | null>(null)
const sessionHistory = ref<QAMessageItem[]>([])
const sessionList = ref<QASessionItem[]>([])

const scopeLabel = computed(() => {
  if (scopeType.value === 'all') return '全库'
  if (scopeType.value === 'folder') return `目录：${selectedFolderLabel.value}`
  return `文件：${selectedFiles.value.map((file) => file.file_name).join('、') || '-'}`
})

const emptyStateTitle = computed(() => {
  if (currentSessionId.value) return '当前会话暂无消息'
  return '问答已进入内部试用'
})

const emptyStateSubtitle = computed(() => {
  if (currentSessionId.value) {
    return '你可以直接继续提问，或切换左侧历史会话查看此前问答记录。'
  }
  return '当前版本支持单轮问答、范围限制和引用来源核查；当证据不足时系统会拒答而不是勉强生成。'
})

const statusNotice = computed(() => {
  if (!systemStore.status.qa_enabled) return '系统设置中尚未启用智能问答。'
  if (!systemStore.status.embedding_configured) return 'Embedding 配置不完整，当前无法执行问答。'
  if (!systemStore.status.llm_configured) return 'LLM 配置不完整，当前无法执行问答。'
  return ''
})
const canAsk = computed(() => !statusNotice.value && !sending.value)

const selectedFolderLabel = computed(() => (folderId.value === null ? 'home' : folderName.value || `#${folderId.value}`))
const selectedFiles = computed(() =>
  selectedFileIds.value
    .map((id) => selectableFiles.value.find((file) => file.id === id))
    .filter((file): file is FileItem => Boolean(file)),
)

const folderNameById = computed(() => {
  const map = new Map<number, string>()
  const walk = (nodes: FolderTreeItem[]) => {
    nodes.forEach((n) => {
      map.set(n.id, n.name)
      if (n.children?.length) walk(n.children)
    })
  }
  walk(folderTree.value)
  return map
})

const syncFromRoute = () => {
  const queryScope = route.query.scope_type
  scopeType.value = queryScope === 'folder' || queryScope === 'files' || queryScope === 'all' ? queryScope : 'all'

  if (route.query.folder_id !== undefined) {
    const raw = String(route.query.folder_id).trim()
    folderId.value = raw ? Number(raw) : null
  } else {
    folderId.value = null
  }

  folderName.value = route.query.folder_name ? String(route.query.folder_name) : folderId.value === null ? 'home' : `#${folderId.value}`

  selectedFileIds.value = route.query.file_ids
    ? String(route.query.file_ids)
        .split(',')
        .map((item) => Number(item.trim()))
        .filter((item) => !Number.isNaN(item))
    : []
  currentSessionId.value =
    route.query.session_id !== undefined && !Number.isNaN(Number(route.query.session_id))
      ? Number(route.query.session_id)
      : null
}

const pushRouteQuery = () => {
  const q: Record<string, string> = { scope_type: scopeType.value }
  if (scopeType.value === 'folder') {
    if (folderId.value !== null) q.folder_id = String(folderId.value)
    q.folder_name = selectedFolderLabel.value
  }
  if (scopeType.value === 'files' && selectedFileIds.value.length) {
    q.file_ids = selectedFileIds.value.join(',')
  }
  if (currentSessionId.value) {
    q.session_id = String(currentSessionId.value)
  }
  router.replace({ name: 'chat', query: q })
}

const loadFolderTree = async () => {
  try {
    folderTree.value = await getFolderTreeApi()
    if (folderId.value !== null) {
      const name = folderNameById.value.get(folderId.value)
      if (name) folderName.value = name
    }
  } catch {
    ElMessage.error('加载目录树失败')
  }
}

const loadSelectableFiles = async () => {
  try {
    selectableFiles.value = await getFilesApi()
  } catch {
    ElMessage.error('加载文件选择列表失败')
  }
}

const scrollMessagesToBottom = async () => {
  await nextTick()
  if (!messagesContainerRef.value) return
  messagesContainerRef.value.scrollTop = messagesContainerRef.value.scrollHeight
}

const handleDownload = async (fileId: number) => {
  try {
    await downloadFileApi(fileId)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '下载失败')
  }
}

const handleOpenFileDetail = (fileId: number) => {
  router.push({ name: 'files', query: { open_file_id: String(fileId) } })
}

const loadSessions = async () => {
  try {
    const res = await getSessionsApi()
    sessionList.value = res.sessions
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载会话列表失败')
  }
}

const loadSessionHistory = async () => {
  if (!currentSessionId.value) {
    sessionHistory.value = []
    messages.value = []
    return
  }
  try {
    const res = await getSessionMessagesApi(currentSessionId.value)
    sessionHistory.value = res.messages
      .filter((item) => item.role === 'user')
      .slice()
      .sort((a, b) => Number(new Date(b.created_at)) - Number(new Date(a.created_at)))
    messages.value = res.messages.map((item) => ({
      id: String(item.id),
      role: item.role,
      content: item.content,
      state: item.state ?? 'normal',
      references:
        item.role === 'assistant' && Array.isArray(item.references_json)
          ? item.references_json
          : [],
    }))
    await scrollMessagesToBottom()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载问答历史失败')
  }
}

const openFolderPicker = () => {
  pickerFolderId.value = folderId.value
  folderPickerVisible.value = true
}

const handlePickFolderNode = (node: FolderTreeItem) => {
  pickerFolderId.value = node.id
}

const confirmFolderPick = () => {
  folderId.value = pickerFolderId.value
  folderName.value = folderId.value === null ? 'home' : folderNameById.value.get(folderId.value) || `#${folderId.value}`
  folderPickerVisible.value = false
  scopeType.value = 'folder'
  pushRouteQuery()
}

const clearFolderScope = () => {
  folderId.value = null
  folderName.value = 'home'
  pushRouteQuery()
}

const switchToAllScope = () => {
  scopeType.value = 'all'
  pushRouteQuery()
}

const getSelectableFileLabel = (file: FileItem) => {
  return `${file.file_name} · ${file.folder_name || 'home'} · ${file.index_status}`
}

const removeSelectedFile = (fileId: number) => {
  selectedFileIds.value = selectedFileIds.value.filter((id) => id !== fileId)
}

const switchSession = (sessionId: number) => {
  currentSessionId.value = sessionId
}

const startNewSession = () => {
  currentSessionId.value = null
  sessionHistory.value = []
  messages.value = []
  pushRouteQuery()
}

const handleDeleteSession = async (sessionId: number) => {
  try {
    await ElMessageBox.confirm('确定要删除该问答会话吗？', '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      distinguishCancelAndClose: true,
    })
    await deleteSessionApi(sessionId)
    if (currentSessionId.value === sessionId) {
      startNewSession()
    }
    await loadSessions()
    ElMessage.success('会话已删除')
  } catch (error) {
    if (error === 'cancel') return
    ElMessage.error(error instanceof Error ? error.message : '删除会话失败')
  }
}

const normalizeAskError = (message: string) => {
  if (message.includes('Embedding 配置不完整')) return 'Embedding 配置不完整，请先在系统设置中补全并测试连接。'
  if (message.includes('LLM 配置不完整')) return 'LLM 配置不完整，请先在系统设置中补全并测试连接。'
  return message
}

const getAskErrorMessage = (error: unknown) => {
  if (error instanceof QaApiError) {
    if (error.code === 'QA_DISABLED') return '智能问答尚未启用，请先在系统设置中开启 QA。'
    if (error.code === 'EMBEDDING_NOT_CONFIGURED') return 'Embedding 配置不完整，请先在系统设置中补全并测试连接。'
    if (error.code === 'LLM_NOT_CONFIGURED') return 'LLM 配置不完整，请先在系统设置中补全并测试连接。'
    if (error.code === 'NO_INDEXED_CONTENT') return '当前范围下没有已索引资料，请先建立索引后再提问。'
    if (error.code === 'EMBEDDING_DATA_UNAVAILABLE') return '当前范围文件缺少可用向量数据，请重新索引后再试。'
    if (error.code === 'EMBEDDING_DIMENSION_MISMATCH') return '当前索引数据维度不一致，请重新索引相关文件后再试。'
    if (error.code === 'NO_RELIABLE_EVIDENCE') return '未检索到足够可靠的依据，当前问题暂时无法回答。'
    if (error.code === 'MODEL_REQUEST_FAILED') return '模型服务请求失败，请检查 LLM / Embedding 配置与服务状态。'
    return error.message
  }
  return normalizeAskError(error instanceof Error ? error.message : '提问失败')
}

const handleAsk = async () => {
  if (!question.value.trim() || sending.value) return
  if (statusNotice.value) {
    ElMessage.warning(statusNotice.value)
    return
  }
  if (scopeType.value === 'files' && selectedFileIds.value.length === 0) {
    ElMessage.warning('请先选择至少一个文件，再按文件范围提问。')
    return
  }

  const userText = question.value.trim()
  question.value = ''
  messages.value.push({
    id: `${Date.now()}-user`,
    role: 'user',
    content: userText,
    state: 'normal',
  })
  await scrollMessagesToBottom()

  const pendingId = `${Date.now()}-assistant-pending`
  messages.value.push({
    id: pendingId,
    role: 'assistant',
    content: '正在检索资料并生成回答...',
    state: 'loading',
    references: [],
  })
  await scrollMessagesToBottom()

  let nextSessionId = currentSessionId.value
  try {
    sending.value = true
    if (!nextSessionId) {
      const created = await createSessionApi()
      nextSessionId = created.session_id
    }
    const res = await askApi({
      question: userText,
      session_id: nextSessionId,
      scope_type: scopeType.value,
      folder_id: scopeType.value === 'folder' ? folderId.value : null,
      file_ids: scopeType.value === 'files' ? selectedFileIds.value : undefined,
      strict_mode: strictMode.value,
      top_k: 6,
    })
    messages.value = messages.value.map((item) =>
      item.id === pendingId
        ? {
            id: `${Date.now()}-assistant`,
            role: 'assistant',
            content: res.answer,
            state: 'normal',
            references: res.references,
            retrievalMeta: res.retrieval_meta,
          }
        : item,
    )
    currentSessionId.value = res.session_id
    await loadSessions()
    await scrollMessagesToBottom()
  } catch (error) {
    const message = getAskErrorMessage(error)
    if (nextSessionId) {
      currentSessionId.value = nextSessionId
    }
    messages.value = messages.value.map((item) =>
      item.id === pendingId
        ? {
            id: `${Date.now()}-error`,
            role: 'assistant',
            content: message,
            state: 'error',
            references: [],
          }
        : item,
    )
    await loadSessions()
    await scrollMessagesToBottom()
  } finally {
    sending.value = false
  }
}

const handleIndexScope = async () => {
  try {
    sending.value = true
    if (scopeType.value === 'files') {
      const idsToIngest = selectedFileIds.value.slice(0, 10)
      if (idsToIngest.length === 0) throw new Error('请先选择文件')
      for (const fid of idsToIngest) await ingestFileApi({ file_id: fid })
      ElMessage.success('文件索引任务已提交，请稍后提问或在文件中心查看状态')
      return
    }

    if (scopeType.value === 'folder') {
      const res = await getFolderChildrenApi(folderId.value)
      const ids = res.files.map((f) => f.id).slice(0, 10)
      if (ids.length === 0) throw new Error('当前目录没有文件可索引')
      for (const fid of ids) await ingestFileApi({ file_id: fid })
      ElMessage.success('目录索引任务已提交，请稍后刷新状态')
      return
    }
  } catch (e) {
    const message = e instanceof Error ? e.message : '索引失败'
    ElMessage.error(message)
  } finally {
    sending.value = false
  }
}

watch(
  () => route.query,
  () => {
    syncFromRoute()
    if (scopeType.value === 'folder' && folderId.value !== null) {
      const name = folderNameById.value.get(folderId.value)
      if (name) folderName.value = name
    }
  },
  { immediate: true, deep: true },
)

watch([scopeType, selectedFileIds], () => {
  pushRouteQuery()
})

watch(
  () => currentSessionId.value,
  async () => {
    pushRouteQuery()
    await loadSessionHistory()
    await loadSessions()
  },
)

onMounted(async () => {
  if (!systemStore.loaded) {
    try {
      await systemStore.fetchSettings()
    } catch {
      ElMessage.error('加载系统配置失败')
    }
  }
  await loadFolderTree()
  await loadSelectableFiles()
  await loadSessions()
  await loadSessionHistory()
})
</script>

<style scoped>
.chat-shell { display: flex; gap: 16px; height: calc(100vh - 120px); min-height: 700px; }
.chat-sidebar { width: 280px; border: 1px solid #ebeef5; border-radius: 16px; padding: 14px; background: #fff; }
.sidebar-title { font-size: 16px; font-weight: 600; margin-bottom: 12px; }
.scope-switch { width: 100%; margin-bottom: 14px; }
.scope-panel { border: 1px solid #eef0f4; border-radius: 12px; padding: 10px; margin-bottom: 12px; }
.panel-label { color: #666; margin-bottom: 8px; font-size: 13px; }
.folder-actions { display: flex; flex-direction: column; gap: 10px; }
.folder-action-buttons { display: flex; flex-wrap: wrap; gap: 8px; }
.file-picker-select { width: 100%; }
.selected-file-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.sidebar-block { margin-top: 12px; }
.history-block { border-top: 1px solid #f2e2d4; padding-top: 12px; }
.history-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px; }
.history-subtitle { margin-top: 12px; }
.session-tip { color: var(--text-secondary); font-size: 12px; margin-bottom: 8px; }
.session-list { display: flex; flex-direction: column; gap: 8px; max-height: 260px; overflow: auto; }
.session-item { display: flex; gap: 8px; align-items: flex-start; justify-content: space-between; border: 1px solid #f1ddd0; border-radius: 12px; padding: 10px; background: #fffaf5; cursor: pointer; }
.session-item-active { border-color: #f0b68b; background: #fff3e6; box-shadow: 0 4px 12px rgba(240, 182, 139, 0.18); position: relative; }
.session-item-active::before { content: ''; position: absolute; left: 0; top: 10px; bottom: 10px; width: 4px; border-radius: 999px; background: linear-gradient(180deg, #f2a65a, #ef7d57); }
.session-main { min-width: 0; flex: 1; }
.session-title-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.session-title { font-size: 13px; font-weight: 600; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.session-meta { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }
.session-preview { font-size: 12px; color: var(--text-primary); line-height: 1.5; margin-top: 6px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.session-error { font-size: 12px; color: var(--danger-color); line-height: 1.5; margin-top: 6px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.session-empty :deep(.el-empty__description) { margin-top: 4px; }
.history-list { display: flex; flex-direction: column; gap: 8px; margin-top: 10px; max-height: 220px; overflow: auto; }
.history-item { border: 1px solid #f1ddd0; border-radius: 10px; padding: 8px; background: #fff8f2; cursor: pointer; }
.history-role { font-size: 12px; color: var(--text-secondary); margin-bottom: 4px; }
.history-time { font-size: 11px; color: var(--text-secondary); margin-bottom: 4px; }
.history-text { font-size: 13px; line-height: 1.5; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.chat-main { flex: 1; border: 1px solid #ebeef5; border-radius: 16px; background: #fff; display: flex; flex-direction: column; overflow: hidden; }
.chat-header { padding: 14px 16px; border-bottom: 1px solid #f0f2f5; display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.chat-title { font-size: 17px; font-weight: 600; }
.chat-meta { display: flex; gap: 8px; flex-wrap: wrap; }
.notice-wrap { padding: 12px 14px 0; background: #fff; }
.messages-area { flex: 1; overflow: auto; padding: 18px; background: #fafbfd; }
.dev-state { display: flex; align-items: center; justify-content: center; min-height: 100%; }
.dev-features { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
.message-row { display: flex; margin-bottom: 16px; }
.message-row-user { justify-content: flex-end; }
.message-bubble { width: min(86%, 860px); background: #fff; border: 1px solid #e8ebf0; border-radius: 14px; padding: 12px 14px; box-shadow: 0 2px 8px rgba(34,42,53,0.04); }
.message-bubble-user { background: #f3f8ff; border-color: #dbe9ff; }
.message-bubble-error { background: #fff5f4; border-color: #ffd6d2; }
.message-bubble-loading { background: #fff8f0; border-color: #f5d7bc; }
.message-role { font-size: 12px; color: #7a8596; margin-bottom: 6px; }
.message-content { white-space: pre-wrap; line-height: 1.7; }
.retrieval-meta { margin-top: 10px; color: var(--text-secondary); font-size: 12px; }
.refs-wrap { margin-top: 12px; }
.refs-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.refs-list { display: grid; gap: 8px; }
.ref-card { border: 1px solid #f4ddcc; border-radius: 12px; padding: 10px; background: #fffaf6; }
.ref-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.ref-file { font-weight: 600; word-break: break-all; }
.ref-meta { margin-top: 6px; color: #7e8794; font-size: 12px; display: flex; gap: 8px; flex-wrap: wrap; }
.ref-snippet { margin-top: 8px; white-space: pre-wrap; color: #2e3440; line-height: 1.6; }
.ref-actions { margin-top: 10px; display: flex; gap: 8px; }
.input-area { border-top: 1px solid #f0f2f5; padding: 12px 14px; background: #fff; position: sticky; bottom: 0; }
.input-actions { margin-top: 8px; display: flex; justify-content: flex-end; }
</style>