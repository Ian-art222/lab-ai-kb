<template>
  <AdminLayout>
    <div class="chat-shell">
      <aside class="chat-sidebar">
        <header class="sidebar-head">
          <h2 class="sidebar-head-title">知识库问答</h2>
          <p class="sidebar-head-desc">检索范围与会话控制</p>
        </header>

        <section class="sidebar-section">
          <el-radio-group v-model="scopeType" class="scope-switch" aria-label="问答范围">
            <el-radio-button value="all">全库</el-radio-button>
            <el-radio-button value="folder">当前目录</el-radio-button>
            <el-radio-button value="files">选中文件</el-radio-button>
          </el-radio-group>

          <div class="scope-panel">
            <template v-if="scopeType === 'folder'">
              <div class="panel-label">当前目录范围</div>
              <div class="folder-actions">
                <el-tag type="info" class="panel-scope-tag">{{ selectedFolderLabel }}</el-tag>
                <div class="folder-action-buttons">
                  <el-button size="small" class="panel-ctl-btn" @click="openFolderPicker">更换目录</el-button>
                  <el-button size="small" class="panel-ctl-btn" @click="clearFolderScope">清空目录</el-button>
                  <el-button size="small" class="panel-ctl-btn panel-ctl-btn--emph" @click="switchToAllScope">
                    切回全库
                  </el-button>
                </div>
              </div>
            </template>

            <template v-if="scopeType === 'files'">
              <div class="panel-label">选择文件范围</div>
              <div class="file-select-shell">
                <el-select
                  v-model="selectedFileIds"
                  multiple
                  filterable
                  clearable
                  collapse-tags
                  collapse-tags-tooltip
                  class="file-picker-select"
                  placeholder="选择已上传文件作为检索范围"
                >
                  <el-option
                    v-for="file in selectableFiles"
                    :key="file.id"
                    :label="getSelectableFileLabel(file)"
                    :value="file.id"
                  />
                </el-select>
              </div>
              <div v-if="selectedFiles.length" class="selected-file-tags">
                <el-tag v-for="file in selectedFiles" :key="file.id" closable @close="removeSelectedFile(file.id)">
                  {{ file.file_name }}
                </el-tag>
              </div>
            </template>
          </div>
        </section>

        <section class="sidebar-section sidebar-section--divider">
          <div class="strict-setting-card">
            <div class="strict-setting-text">
              <div class="strict-setting-title">{{ strictMode ? '严格模式' : '非严格模式' }}</div>
              <p class="strict-setting-sub">
                {{
                  strictMode
                    ? '仅依据知识库检索结果回答，无足够依据时不作答'
                    : '优先参考知识库；无可用依据时允许模型基于通用知识回答'
                }}
              </p>
            </div>
            <el-switch v-model="strictMode" class="strict-switch" />
          </div>

          <el-button
            class="btn-index-scope"
            :disabled="scopeType === 'all'"
            @click="handleIndexScope"
          >
            建立索引（最多 10 个）
          </el-button>
        </section>

        <section class="sidebar-section sidebar-section--sessions">
          <div class="session-block-head">
            <div class="session-block-head-text">
              <span class="section-kicker">会话</span>
              <span class="section-title">会话列表</span>
            </div>
            <el-button size="small" class="btn-new-session" @click="startNewSession">新建问答</el-button>
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
                class="session-delete-btn"
                @click.stop="handleDeleteSession(session.id)"
              >
                删除
              </el-button>
            </div>
          </div>
          <div v-else class="session-empty-state" role="status">
            <div class="session-empty-icon" aria-hidden="true">
              <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path
                  d="M14 22c0-5.523 4.477-10 10-10s10 4.477 10 10-4.477 10-10 10-10-4.477-10-10z"
                  stroke="currentColor"
                  stroke-width="1.6"
                  opacity="0.35"
                />
                <path
                  d="M20 26h8M24 22v8"
                  stroke="currentColor"
                  stroke-width="1.6"
                  stroke-linecap="round"
                  opacity="0.45"
                />
              </svg>
            </div>
            <p class="session-empty-title">暂无历史会话</p>
            <p class="session-empty-hint">新建问答后，记录将保存在这里</p>
          </div>

          <div class="current-session-block">
            <div class="current-session-head">
              <span class="section-kicker">当前</span>
              <span class="section-title section-title--sub">当前会话记录</span>
            </div>
            <div v-if="currentSessionId" class="session-tip">会话 ID：{{ currentSessionId }}</div>
            <div v-else class="session-placeholder">尚未选择或新建会话</div>
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
        </section>
      </aside>

      <main class="chat-main" :class="{ 'chat-main--empty': messages.length === 0 }">
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

        <div
          ref="messagesContainerRef"
          class="messages-area"
          :class="{ 'messages-area--empty': messages.length === 0 }"
        >
          <div v-if="messages.length === 0" class="gemini-empty">
            <div class="gemini-empty-inner">
              <div class="gemini-welcome-row">
                <div class="gemini-star" aria-hidden="true">
                  <svg viewBox="0 0 24 24" width="32" height="32" focusable="false">
                    <defs>
                      <linearGradient id="gemini-star-grad" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stop-color="#0b57d0" />
                        <stop offset="100%" stop-color="#5c9eff" />
                      </linearGradient>
                    </defs>
                    <path
                      fill="url(#gemini-star-grad)"
                      d="M12 2.2l1.4 4.5h4.8l-3.9 2.8 1.5 4.5-3.8-2.8-3.8 2.8 1.5-4.5-3.9-2.8h4.8L12 2.2z"
                    />
                  </svg>
                </div>
                <div class="gemini-welcome-texts">
                  <p class="gemini-greeting">{{ greetingLine }}</p>
                  <h1 class="gemini-headline">需要我为你做些什么？</h1>
                  <p v-if="emptySessionHint" class="gemini-hint">{{ emptySessionHint }}</p>
                </div>
              </div>

              <div class="gemini-composer-card">
                <el-input
                  v-model="question"
                  type="textarea"
                  :rows="4"
                  resize="none"
                  :disabled="!canAsk"
                  class="gemini-composer-input"
                  placeholder="输入问题，将基于当前范围内已索引资料作答"
                  @keydown.enter.exact.prevent="handleAsk"
                />
                <div class="gemini-composer-footer">
                  <el-button
                    type="primary"
                    round
                    :loading="sending"
                    :disabled="!question.trim() || !canAsk"
                    @click="handleAsk"
                  >
                    发送
                  </el-button>
                </div>
              </div>

              <div class="gemini-pills" role="group" aria-label="快捷建议">
                <button
                  v-for="item in suggestionPills"
                  :key="item"
                  type="button"
                  class="gemini-pill"
                  @click="applySuggestion(item)"
                >
                  {{ item }}
                </button>
              </div>
            </div>
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
              <div
                v-if="
                  m.role === 'assistant' &&
                  m.state === 'normal' &&
                  m.answerSource === 'model_general'
                "
                class="answer-source-hint"
              >
                当前未检索到相关知识库资料，以下回答由模型基于通用知识生成
              </div>
              <div
                v-else-if="
                  m.role === 'assistant' &&
                  m.state === 'normal' &&
                  m.answerSource === 'knowledge_base_low_confidence'
                "
                class="answer-source-hint"
              >
                检索到片段但相似度低于采用阈值，未将片段作为引用依据；以下回答由模型基于通用知识生成
              </div>
              <div class="message-content">{{ m.content }}</div>
              <div v-if="m.role === 'assistant' && m.state === 'normal' && (m.taskType || m.selectedSkill || m.workflowSummary)" class="workflow-pill-wrap">
                <el-tag size="small" type="info" effect="plain">task: {{ m.taskType || '—' }}</el-tag>
                <el-tag size="small" type="info" effect="plain">scope: {{ m.selectedScope || '—' }}</el-tag>
                <el-tag size="small" type="success" effect="plain">skill: {{ m.selectedSkill || '—' }}</el-tag>
                <el-tag v-if="m.isCompareMode" size="small" type="warning" effect="plain">比较模式</el-tag>
                <el-tag v-if="m.clarificationNeeded" size="small" type="danger" effect="plain">需要澄清</el-tag>
                <el-tag v-if="m.fallbackTriggered" size="small" type="warning" effect="plain">追加检索已触发</el-tag>
                <el-tag v-if="m.sourceSkewed" size="small" type="danger" effect="plain">单源倾斜</el-tag>
                <el-tag v-if="m.evidenceAsymmetric" size="small" type="danger" effect="plain">证据不对称</el-tag>
                <span class="workflow-summary-text">{{ m.workflowSummary || '—' }}</span>
              </div>

              <details
                v-if="m.role === 'assistant' && m.state === 'normal' && m.retrievalMeta"
                class="retrieval-details"
              >
                <summary class="retrieval-details-summary">
                  检索详情
                  <span class="retrieval-details-summary-sub">
                    · 命中 {{ m.retrievalMeta.matched_chunks ?? '—' }} /
                    {{ m.retrievalMeta.candidate_chunks ?? '—' }}
                    · {{ m.retrievalMeta.answer_source ?? '—' }}
                  </span>
                </summary>
                <dl class="retrieval-detail-dl">
                  <template v-for="row in retrievalMetaRows(m.retrievalMeta)" :key="row.label">
                    <dt>{{ row.label }}</dt>
                    <dd>{{ row.value }}</dd>
                  </template>
                </dl>
                <details
                  v-if="m.retrievalMeta?.coverage_diagnostics"
                  class="retrieval-coverage-details"
                >
                  <summary class="retrieval-details-summary">覆盖与来源诊断</summary>
                  <dl class="retrieval-detail-dl">
                    <template
                      v-for="row in coverageDiagnosticsRows(m.retrievalMeta.coverage_diagnostics, m.retrievalMeta)"
                      :key="row.label"
                    >
                      <dt>{{ row.label }}</dt>
                      <dd>{{ row.value }}</dd>
                    </template>
                  </dl>
                </details>
              </details>

              <div v-if="m.role === 'assistant' && m.references?.length" class="refs-wrap">
                <div class="refs-title">引用来源（可核查）</div>
                <div class="refs-list">
                  <div v-for="r in m.references" :key="`${m.id}-${r.chunk_id}-${r.chunk_index}`" class="ref-card">
                    <div class="ref-head">
                      <div class="ref-file">{{ r.file_name }}</div>
                      <el-tag size="small" type="warning">score {{ formatRefScore(r.score) }}</el-tag>
                      <el-tag v-if="r.provenance_type" size="small" type="success" effect="plain">{{
                        provenanceLabel(r.provenance_type)
                      }}</el-tag>
                    </div>
                    <div class="ref-meta">
                      <span>片段 #{{ r.chunk_index }}</span>
                      <span v-if="r.section_title">章节：{{ r.section_title }}</span>
                      <span v-if="r.page_number">页码：{{ r.page_number }}</span>
                      <span v-if="r.heading_path">路径：{{ r.heading_path }}</span>
                      <span v-if="r.block_type">块类型：{{ r.block_type }}</span>
                      <span v-if="r.chunk_role">chunk_role：{{ r.chunk_role }}</span>
                      <span v-if="r.context_chunk_role">上下文：{{ r.context_chunk_role }}</span>
                      <span v-if="r.matched_query_index != null && r.matched_query_index >= 0"
                        >子查询：#{{ r.matched_query_index }}</span
                      >
                      <span v-if="r.source_file_rank != null">来源序：{{ r.source_file_rank }}</span>
                      <span v-if="r.file_char_share != null">字符占比：{{ (Number(r.file_char_share) * 100).toFixed(1) }}%</span>
                      <span v-if="r.parent_sequence_index != null && r.parent_sequence_index !== undefined"
                        >parent_seq：{{ r.parent_sequence_index }}</span
                      >
                      <el-tag v-if="r.adjacent_expansion" size="small" type="info">含相邻扩展</el-tag>
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

        <div v-if="messages.length > 0" class="input-area">
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
  type AnswerSource,
  type AskReference,
  QaApiError,
  type QAMessageItem,
  type QASessionItem,
  type CoverageDiagnostics,
  type RetrievalMeta,
  type ScopeType,
} from '../api/qa'
import { useSystemStore } from '../stores/system'
import { useAuthStore } from '../stores/auth'

type ChatMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  state?: 'normal' | 'loading' | 'error'
  references?: AskReference[]
  retrievalMeta?: Partial<RetrievalMeta>
  answerSource?: AnswerSource
  taskType?: string | null
  selectedScope?: string | null
  selectedSkill?: string | null
  workflowSummary?: string | null
  clarificationNeeded?: boolean
  fallbackTriggered?: boolean
  isCompareMode?: boolean
  sourceSkewed?: boolean
  evidenceAsymmetric?: boolean
}

type RetrievalMetaRow = { label: string; value: string }

const formatRefScore = (score: unknown) => {
  const n = typeof score === 'number' ? score : Number(score)
  return Number.isFinite(n) ? n.toFixed(3) : '—'
}

const provenanceLabel = (t: string | null | undefined) => {
  const m: Record<string, string> = {
    retrieved_hit: '命中',
    neighbor_expansion: '邻居扩展',
    parent_recovery: 'parent补充',
    adjacent_parent_expansion: '相邻parent扩展',
    maybe_supporting_context: '补充上下文',
  }
  if (!t) return ''
  return m[t] || t
}

const coverageDiagnosticsRows = (
  cd: CoverageDiagnostics,
  meta?: Partial<RetrievalMeta>,
): RetrievalMetaRow[] => {
  const fmt = (v: unknown) => {
    if (v === undefined || v === null || v === '') return '—'
    if (typeof v === 'boolean') return v ? '是' : '否'
    if (Array.isArray(v)) return v.length ? JSON.stringify(v) : '—'
    if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '—'
    if (typeof v === 'object') return JSON.stringify(v)
    return String(v)
  }
  const trace = (cd.packing_decision_trace || {}) as Record<string, unknown>
  const notices = trace.coverage_shortfall_notice
  const as = meta?.answer_synthesis as Record<string, unknown> | undefined
  return [
    { label: 'query_type', value: fmt(cd.query_type) },
    { label: 'distinct_files_pre_pack', value: fmt(cd.distinct_files_pre_pack) },
    { label: 'distinct_files_post_pack', value: fmt(cd.distinct_files_post_pack) },
    { label: 'dominant_file_ratio_post_pack (chars)', value: fmt(cd.dominant_file_ratio_post_pack) },
    { label: 'dominant_file_ratio_chunks', value: fmt(cd.dominant_file_ratio_chunks) },
    { label: 'selected_file_distribution', value: fmt(cd.selected_file_distribution) },
    { label: 'coverage_shortfall_notice', value: fmt(notices) },
    { label: 'dominant_source_warning', value: fmt(cd.dominant_source_warning) },
    { label: 'citation_source_count', value: fmt(cd.citation_source_count) },
    { label: 'unmatched_queries', value: fmt(cd.unmatched_queries) },
    { label: 'weak_query_indices', value: fmt(cd.weak_query_indices) },
    { label: 'answer_synthesis.coverage_assessment', value: fmt(as?.coverage_assessment) },
  ]
}

const retrievalMetaRows = (meta: Partial<RetrievalMeta>): RetrievalMetaRow[] => {
  const fmt = (v: unknown) => {
    if (v === undefined || v === null || v === '') return '—'
    if (typeof v === 'boolean') return v ? '是' : '否'
    if (Array.isArray(v)) return v.length ? JSON.stringify(v) : '—'
    if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '—'
    return String(v)
  }
  return [
    { label: 'retrieval_strategy', value: fmt(meta.retrieval_strategy) },
    { label: 'answer_source', value: fmt(meta.answer_source) },
    { label: 'scope_type', value: fmt(meta.scope_type) },
    { label: 'strict_mode', value: fmt(meta.strict_mode) },
    { label: 'top_k', value: fmt(meta.top_k) },
    { label: 'min_similarity_score', value: fmt(meta.min_similarity_score ?? meta.min_score) },
    { label: 'candidate_chunks', value: fmt(meta.candidate_chunks) },
    { label: 'matched_chunks', value: fmt(meta.matched_chunks) },
    { label: 'selected_chunks', value: fmt(meta.selected_chunks) },
    { label: 'compatible_file_count', value: fmt(meta.compatible_file_count) },
    { label: 'used_file_ids', value: fmt(meta.used_file_ids) },
    { label: 'candidate_k', value: fmt(meta.candidate_k) },
    { label: 'expanded_chunks', value: fmt(meta.expanded_chunks) },
    { label: 'packed_chunks', value: fmt(meta.packed_chunks) },
    { label: 'context_chars', value: fmt(meta.context_chars) },
    { label: 'neighbor_window', value: fmt(meta.neighbor_window) },
    { label: 'dedupe_adjacent_chunks', value: fmt(meta.dedupe_adjacent_chunks) },
    { label: 'retrieval_mode', value: fmt(meta.retrieval_mode) },
    { label: 'semantic_candidate_count', value: fmt(meta.semantic_candidate_count) },
    { label: 'lexical_candidate_count', value: fmt(meta.lexical_candidate_count) },
    { label: 'fusion_method', value: fmt(meta.fusion_method) },
    { label: 'rerank_enabled', value: fmt(meta.rerank_enabled) },
    { label: 'rerank_input_count', value: fmt(meta.rerank_input_count) },
    { label: 'rerank_output_count', value: fmt(meta.rerank_output_count) },
    { label: 'rerank_model_name', value: fmt(meta.rerank_model_name) },
    { label: 'rerank_applied', value: fmt(meta.rerank_applied) },
    { label: 'parent_recovered_chunks', value: fmt(meta.parent_recovered_chunks) },
    { label: 'parent_deduped_groups', value: fmt(meta.parent_deduped_groups) },
    { label: 'task_type', value: fmt(meta.task_type) },
    { label: 'selected_skill', value: fmt(meta.selected_skill) },
    { label: 'workflow_summary', value: fmt(meta.workflow_summary) },
    { label: 'fallback_triggered', value: fmt(meta.fallback_triggered) },
    { label: 'stop_reason', value: fmt(meta.stop_reason) },
    { label: 'source_count', value: fmt(meta.source_count) },
    { label: 'dominant_source_ratio', value: fmt(meta.dominant_source_ratio) },
    { label: 'multi_source_coverage', value: fmt(meta.multi_source_coverage) },
    { label: 'pack_diversification', value: fmt((meta.retrieval_trace as Record<string, unknown> | undefined)?.pack_diversification) },
    { label: 'packing_trace', value: fmt((meta.retrieval_trace as Record<string, unknown> | undefined)?.packing) },
    { label: 'query_type', value: fmt(meta.query_understanding?.query_type) },
    { label: 'query_rewrite_enabled', value: fmt(meta.query_understanding?.rewrite_enabled) },
    { label: 'rewritten_query', value: fmt(meta.query_understanding?.rewritten_query) },
    { label: 'retrieval_query_count', value: fmt(meta.query_understanding?.retrieval_query_count) },
    { label: 'multi_query_merge', value: fmt(meta.query_understanding?.multi_query_merge_used) },
    { label: 'final_retrieval_queries', value: fmt(meta.query_understanding?.final_retrieval_queries) },
    { label: 'answer_synthesis', value: fmt(meta.answer_synthesis) },
  ]
}

const route = useRoute()
const router = useRouter()
const systemStore = useSystemStore()
const authStore = useAuthStore()

/** Fixed experiment defaults for per-request rerank overrides; edit here only. */
const CHAT_ASK_RERANK_EXPERIMENT = {
  rerank_enabled: true,
  rerank_top_n: 20,
} as const

const suggestionPills = [
  '帮我总结文档',
  '帮我查知识库',
  '帮我找上传文件',
  '帮我回答问题',
  '帮我整理内容',
  '帮我开始检索',
] as const

const applySuggestion = (text: string) => {
  question.value = text
}

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

const greetingLine = computed(() => {
  const name = authStore.username?.trim()
  if (name) return `${name}，你好`
  return '欢迎使用'
})

const emptySessionHint = computed(() => {
  if (!currentSessionId.value) return ''
  return '当前会话暂无消息，可直接输入问题开始。'
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
    messages.value = res.messages.map((item) => {
      const base = {
        id: String(item.id),
        role: item.role,
        content: item.content,
        state: item.state ?? 'normal' as const,
      }
      if (item.role !== 'assistant') return base
      const raw = item.references_json
      if (raw && typeof raw === 'object' && !Array.isArray(raw) && (raw as { kind?: string }).kind === 'error') {
        return { ...base, references: [], answerSource: 'error' as const }
      }
      if (Array.isArray(raw)) {
        return { ...base, references: raw as AskReference[], answerSource: 'knowledge_base' as const }
      }
      if (raw && typeof raw === 'object' && (raw as { answer_source?: string }).answer_source === 'model_general') {
        return { ...base, references: [], answerSource: 'model_general' as const }
      }
      if (
        raw &&
        typeof raw === 'object' &&
        (raw as { answer_source?: string }).answer_source === 'knowledge_base_low_confidence'
      ) {
        return { ...base, references: [], answerSource: 'knowledge_base_low_confidence' as const }
      }
      return { ...base, references: [], answerSource: 'knowledge_base' as const }
    })
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
    if (error.code === 'NO_RELIABLE_EVIDENCE')
      return '知识库中未找到足够可用的依据；在严格模式下无法回答，可尝试放宽范围或关闭严格模式。'
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
      candidate_k: 12,
      max_context_chars: 12000,
      neighbor_window: 1,
      dedupe_adjacent_chunks: true,
      ...CHAT_ASK_RERANK_EXPERIMENT,
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
            answerSource: res.answer_source,
            taskType: res.task_type ?? res.retrieval_meta?.task_type ?? null,
            selectedScope: res.retrieval_meta?.selected_scope ?? null,
            selectedSkill: res.selected_skill ?? res.retrieval_meta?.selected_skill ?? null,
            workflowSummary: res.workflow_summary ?? res.retrieval_meta?.workflow_summary ?? null,
            clarificationNeeded: Boolean(res.clarification_needed ?? res.retrieval_meta?.clarification_needed),
            fallbackTriggered: Boolean(res.retrieval_meta?.fallback_triggered),
            isCompareMode: (res.task_type ?? res.retrieval_meta?.task_type) === 'compare',
            sourceSkewed: Number(res.retrieval_meta?.dominant_source_ratio ?? 0) >= 0.75,
            evidenceAsymmetric: Boolean((res.compare_result as Record<string, unknown> | null)?.evidence_asymmetry),
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
            answerSource: 'error',
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
.chat-shell {
  display: flex;
  gap: 20px;
  height: calc(100vh - 112px);
  min-height: 640px;
}
.chat-sidebar {
  --cp-gap: 14px;
  --cp-radius-outer: 16px;
  --cp-radius-inner: 14px;
  --cp-radius-control: 12px;
  width: 280px;
  flex-shrink: 0;
  padding: 20px 16px 20px;
  border-radius: var(--cp-radius-outer);
  border: none;
  background: var(--ds-surface-muted, #f0f4f9);
  box-shadow: none;
}
.sidebar-head {
  margin-bottom: calc(var(--cp-gap) + 4px);
  padding-bottom: var(--cp-gap);
  border-bottom: 1px solid var(--ds-line-subtle, #e0e3e7);
}
.sidebar-head-title {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--text-primary);
  line-height: 1.3;
}
.sidebar-head-desc {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 1.45;
  color: var(--text-secondary);
}
.sidebar-section {
  margin-bottom: var(--cp-gap);
}
.sidebar-section:last-child {
  margin-bottom: 0;
}
.sidebar-section--divider {
  padding-top: var(--cp-gap);
  border-top: 1px solid var(--ds-line-subtle, #e0e3e7);
  margin-top: 2px;
}
.sidebar-section--sessions {
  padding-top: var(--cp-gap);
  margin-top: 4px;
  border-top: 1px solid var(--ds-line-subtle, #e0e3e7);
}
.scope-switch {
  display: flex;
  width: 100%;
  margin-bottom: var(--cp-gap);
  padding: 4px;
  gap: 4px;
  border-radius: var(--cp-radius-inner);
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
}
.scope-switch :deep(.el-radio-button) {
  flex: 1;
  margin: 0 !important;
}
.scope-switch :deep(.el-radio-button__inner) {
  width: 100%;
  padding: 8px 4px;
  font-size: 12px;
  font-weight: 500;
  border: none !important;
  border-radius: 10px !important;
  box-shadow: none !important;
  background: transparent !important;
  color: var(--text-secondary);
}
.scope-switch :deep(.el-radio-button.is-active .el-radio-button__inner) {
  background: #fff !important;
  color: var(--ds-brand, #0b57d0) !important;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
}
.scope-panel {
  border-radius: var(--cp-radius-inner);
  padding: 12px;
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  background: #fff;
}
.panel-label {
  margin-bottom: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}
.folder-action-buttons {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.panel-ctl-btn {
  border-radius: 10px !important;
}
.panel-ctl-btn--emph {
  color: var(--ds-brand, #0b57d0) !important;
}
.file-select-shell {
  border-radius: var(--cp-radius-control);
  padding: 4px;
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  background: #fff;
}
.file-picker-select :deep(.el-select__wrapper) {
  min-height: 38px;
  border-radius: 10px !important;
  box-shadow: none !important;
  border: none !important;
}
.selected-file-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.strict-setting-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  margin-bottom: 12px;
  border-radius: var(--cp-radius-inner);
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  background: #fff;
}
.strict-setting-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.strict-setting-sub {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.45;
  color: var(--text-secondary);
}
.strict-switch {
  --el-switch-on-color: #0b57d0;
  --el-switch-off-color: #c4c7c5;
}
.btn-index-scope {
  width: 100%;
  height: 40px;
  border-radius: 12px !important;
  font-weight: 500;
  font-size: 13px;
  border: 1px solid var(--ds-line, #e6eaf0) !important;
  background: #fff !important;
  color: var(--text-primary) !important;
}
.btn-index-scope:hover:not(:disabled) {
  border-color: var(--ds-brand, #0b57d0) !important;
  color: var(--ds-brand, #0b57d0) !important;
}
.session-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}
.section-kicker {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-secondary);
  opacity: 0.85;
}
.section-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.section-title--sub {
  font-size: 13px;
  font-weight: 600;
}
.btn-new-session {
  flex-shrink: 0;
  border-radius: 999px !important;
  font-weight: 500 !important;
  font-size: 12px !important;
}
.session-empty-state {
  text-align: center;
  padding: 20px 12px;
  margin-bottom: 4px;
  border-radius: 14px;
  border: 1px dashed var(--ds-line, #e6eaf0);
  background: rgba(255, 255, 255, 0.6);
}
.session-empty-icon {
  display: flex;
  justify-content: center;
  margin-bottom: 8px;
  color: var(--text-secondary);
  opacity: 0.45;
}
.session-empty-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.session-empty-hint {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.current-session-block {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--ds-line-subtle, #e0e3e7);
}
.session-placeholder,
.session-tip {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.7);
  margin-bottom: 8px;
}
.session-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 260px;
  overflow: auto;
}
.session-item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  justify-content: space-between;
  border: 1px solid transparent;
  border-radius: 12px;
  padding: 10px 12px;
  background: #fff;
  cursor: pointer;
  transition: box-shadow 0.15s ease, border-color 0.15s ease;
}
.session-item:hover {
  border-color: var(--ds-line-subtle, #e0e3e7);
  box-shadow: var(--ds-shadow-float, 0 4px 12px rgba(0, 0, 0, 0.05));
}
.session-item-active {
  border-color: rgba(11, 87, 208, 0.25);
  box-shadow: 0 0 0 1px rgba(11, 87, 208, 0.12);
}
.session-item-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 9px;
  bottom: 9px;
  width: 3px;
  border-radius: 999px;
  background: var(--ds-brand, #0b57d0);
}
.session-item {
  position: relative;
}
.session-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}
.session-meta {
  font-size: 11px;
  color: var(--text-secondary);
  margin-top: 4px;
}
.session-preview {
  font-size: 12px;
  color: var(--text-primary);
  margin-top: 6px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.session-error {
  font-size: 12px;
  color: var(--danger-color);
  margin-top: 6px;
}
.history-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 220px;
  overflow: auto;
}
.history-item {
  border-radius: 10px;
  padding: 9px 10px;
  background: #fff;
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  cursor: pointer;
  transition: background 0.15s ease;
}
.history-item:hover {
  background: rgba(11, 87, 208, 0.04);
}
.history-role {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
}
.history-time {
  font-size: 11px;
  color: var(--text-secondary);
  margin: 4px 0;
}
.history-text {
  font-size: 13px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chat-main {
  flex: 1;
  border: none;
  border-radius: 16px;
  background: #fff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: var(--ds-shadow-float, 0 4px 12px rgba(0, 0, 0, 0.05));
}
.chat-main--empty {
  background: #fff;
}
.chat-header {
  padding: 16px 24px;
  border-bottom: 1px solid var(--ds-line-subtle, #e0e3e7);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  background: #fff;
}
.chat-title {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}
.chat-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.notice-wrap {
  padding: 12px 24px 0;
}
.messages-area {
  flex: 1;
  overflow: auto;
  padding: 24px 28px 100px;
  background: #fff;
}
.messages-area--empty {
  background: #fff;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: clamp(40px, 10vh, 100px);
}
.gemini-empty {
  width: 100%;
  display: flex;
  justify-content: center;
}
.gemini-empty-inner {
  width: 100%;
  max-width: 720px;
  padding: 0 8px;
}
.gemini-welcome-row {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 28px;
}
.gemini-star {
  flex-shrink: 0;
  margin-top: 4px;
}
.gemini-greeting {
  margin: 0 0 8px;
  font-size: 1rem;
  font-weight: 500;
  color: var(--text-secondary);
}
.gemini-headline {
  margin: 0;
  font-size: clamp(1.5rem, 2.4vw, 2rem);
  font-weight: 500;
  line-height: 1.25;
  color: var(--text-primary);
  letter-spacing: -0.03em;
}
.gemini-hint {
  margin: 12px 0 0;
  font-size: 0.875rem;
  color: var(--text-secondary);
  line-height: 1.5;
}
.gemini-composer-card {
  background: #fff;
  border-radius: 24px;
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  box-shadow: var(--ds-shadow-float, 0 4px 12px rgba(0, 0, 0, 0.05));
  padding: 16px 18px 14px;
  margin-bottom: 20px;
}
.gemini-composer-input :deep(.el-textarea__inner) {
  border: none !important;
  box-shadow: none !important;
  background: transparent;
  font-size: 15px;
  line-height: 1.55;
  padding: 4px 2px;
  min-height: 96px !important;
}
.gemini-composer-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
.gemini-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-start;
}
.gemini-pill {
  appearance: none;
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  background: #f0f4f9;
  color: var(--text-primary);
  font-size: 13px;
  padding: 10px 16px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.gemini-pill:hover {
  background: #e8eef5;
  border-color: #d0d7e0;
}
.message-row {
  display: flex;
  margin-bottom: 20px;
}
.message-row-user {
  justify-content: flex-end;
}
.message-bubble {
  width: min(88%, 760px);
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0 4px;
  box-shadow: none;
}
.message-bubble-user .message-content {
  margin-left: auto;
  background: #f0f4f9;
  border-radius: 22px 22px 6px 22px;
  padding: 14px 18px;
  max-width: 100%;
  display: inline-block;
  text-align: left;
}
.message-bubble:not(.message-bubble-user) .message-content {
  background: transparent;
  padding: 4px 0 0;
  line-height: 1.75;
  font-size: 15px;
  color: var(--text-primary);
}
.message-bubble-user .message-role {
  text-align: right;
  padding-right: 8px;
}
.message-bubble-user {
  text-align: right;
}
.message-bubble-error .message-content {
  background: #ffebee;
  border-radius: 16px;
  padding: 14px 18px;
  display: inline-block;
  text-align: left;
  color: var(--ds-danger-text, #b71c1c);
}
.message-bubble-loading .message-content {
  color: var(--text-secondary);
  font-style: normal;
}
.message-role {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.answer-source-hint {
  font-size: 12px;
  line-height: 1.45;
  color: var(--text-secondary);
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: 12px;
  background: #f5f8fb;
  border: none;
}
.message-content {
  white-space: pre-wrap;
  line-height: 1.7;
}
.workflow-pill-wrap {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.workflow-summary-text {
  font-size: 12px;
  color: var(--text-secondary);
}
.retrieval-details {
  margin-top: 12px;
  border-radius: 12px;
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  background: #fafbfc;
  padding: 10px 12px;
}
.retrieval-details-summary {
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  list-style: none;
}
.retrieval-details-summary::-webkit-details-marker {
  display: none;
}
.retrieval-details-summary-sub {
  font-weight: 400;
  color: var(--text-secondary);
  margin-left: 6px;
}
.retrieval-coverage-details {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--ds-line-subtle, #e0e3e7);
}
.retrieval-detail-dl {
  margin: 10px 0 0;
  display: grid;
  grid-template-columns: minmax(160px, 1fr) minmax(0, 2fr);
  gap: 6px 14px;
  font-size: 12px;
  line-height: 1.45;
}
.retrieval-detail-dl dt {
  margin: 0;
  color: var(--text-secondary);
  font-weight: 600;
  font-family: ui-monospace, monospace;
  font-size: 11px;
}
.retrieval-detail-dl dd {
  margin: 0;
  color: var(--text-primary);
  word-break: break-word;
  font-family: ui-monospace, monospace;
  font-size: 11px;
}
.refs-wrap {
  margin-top: 16px;
}
.refs-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: var(--text-primary);
}
.refs-list {
  display: grid;
  gap: 10px;
}
.ref-card {
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  border-radius: 14px;
  padding: 12px 14px;
  background: #fafbfc;
}
.ref-head {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.ref-file {
  font-weight: 600;
  word-break: break-all;
  color: var(--text-primary);
  flex: 1;
  min-width: 0;
}
.ref-meta {
  margin-top: 8px;
  color: var(--text-secondary);
  font-size: 12px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.ref-snippet {
  margin-top: 10px;
  white-space: pre-wrap;
  color: var(--text-primary);
  line-height: 1.6;
  font-size: 13px;
}
.ref-actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}
.input-area {
  padding: 16px 24px 20px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0) 0%, #fff 12%);
  border-top: 1px solid var(--ds-line-subtle, #e0e3e7);
}
.input-area :deep(.el-textarea__inner) {
  border-radius: 16px !important;
  min-height: 72px !important;
  padding: 14px 16px;
  font-size: 15px;
}
.input-actions {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}
@media (max-width: 768px) {
  .chat-shell {
    flex-direction: column;
    height: auto;
    min-height: 0;
  }
  .chat-sidebar {
    width: 100%;
  }
}

</style>
