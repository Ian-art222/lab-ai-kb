<template>
  <AdminLayout>
    <div class="diag-page">
      <el-card class="page-card">
        <template #header>
          <div class="header-row">
            <div>
              <div class="page-title">管理员诊断中心</div>
              <div class="page-subtitle">查看 QA Trace、原因码统计并执行 retry/reindex。</div>
            </div>
            <el-button :loading="loading" @click="reloadAll">刷新</el-button>
          </div>
        </template>

        <el-result
          v-if="forbidden"
          icon="warning"
          title="无权限访问"
          sub-title="该页面仅管理员可用。请确认账号角色，或联系管理员。"
        />

        <template v-else>
          <div class="toolbar">
            <el-input v-model="filters.trace_id" placeholder="trace_id" clearable style="width: 180px" />
            <el-input v-model="filters.request_id" placeholder="request_id" clearable style="width: 180px" />
            <el-input v-model="filters.session_id" placeholder="session_id" clearable style="width: 140px" />
            <el-select v-model="filters.is_abstained" placeholder="是否拒答" clearable style="width: 120px">
              <el-option label="是" value="true" />
              <el-option label="否" value="false" />
            </el-select>
            <el-select v-model="filters.failed" placeholder="是否失败" clearable style="width: 120px">
              <el-option label="是" value="true" />
              <el-option label="否" value="false" />
            </el-select>
            <el-button type="primary" :loading="loading" @click="loadTraces(0)">查询</el-button>
          </div>

          <el-alert v-if="errorMsg" :title="errorMsg" type="error" show-icon :closable="false" class="mb-12" />

          <el-table :data="traces" v-loading="loading" style="width: 100%" empty-text="暂无 trace 记录">
            <el-table-column prop="trace_id" label="trace_id" min-width="190" />
            <el-table-column prop="request_id" label="request_id" min-width="170" />
            <el-table-column prop="created_at" label="时间" min-width="165">
              <template #default="scope">{{ fmtDate(scope.row.created_at) }}</template>
            </el-table-column>
            <el-table-column prop="question" label="query 摘要" min-width="240">
              <template #default="scope">{{ snippet(scope.row.question) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="150">
              <template #default="scope">
                <el-tag :type="scope.row.is_abstained ? 'warning' : 'success'">
                  {{ scope.row.is_abstained ? 'abstained' : 'answered' }}
                </el-tag>
                <el-tag v-if="scope.row.failed" type="danger" class="ml-4">failed</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="reason_code" min-width="180">
              <template #default="scope">{{ scope.row.abstain_reason || scope.row.failure_reason || '-' }}</template>
            </el-table-column>
            <el-table-column label="strict" width="90">
              <template #default="scope">{{ scope.row.strict_mode ? 'strict' : 'non-strict' }}</template>
            </el-table-column>
            <el-table-column prop="model_name" label="model" min-width="130" />
            <el-table-column label="evidence" width="95">
              <template #default="scope">{{ evidenceCount(scope.row) }}</template>
            </el-table-column>
            <el-table-column label="coverage" min-width="170">
              <template #default="scope">
                src={{ scope.row.source_count ?? '-' }} · dom={{ asPct(scope.row.dominant_source_ratio) }}
              </template>
            </el-table-column>
            <el-table-column label="fallback" width="95">
              <template #default="scope">{{ scope.row.fallback_triggered ? 'yes' : '-' }}</template>
            </el-table-column>
            <el-table-column label="skill" min-width="130">
              <template #default="scope">{{ scope.row.selected_skill || '-' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="scope">
                <el-button link type="primary" @click="openDetail(scope.row.trace_id)">查看详情</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="footer-row">
            <el-pagination
              background
              layout="prev, pager, next"
              :total="total"
              :current-page="Math.floor(offset / limit) + 1"
              :page-size="limit"
              @current-change="(p: number) => loadTraces((p - 1) * limit)"
            />
          </div>

          <el-divider content-position="left">Reason 码统计（最近查询范围）</el-divider>
          <el-empty v-if="reasonStats.length === 0" description="暂无统计数据" />
          <div v-else class="reason-grid">
            <el-tag v-for="item in reasonStats" :key="item.reason_code" type="info">
              {{ item.reason_code }}: {{ item.count }}
            </el-tag>
          </div>
        </template>
      </el-card>

      <el-drawer v-model="detailVisible" title="Trace 详情" size="55%" destroy-on-close>
        <div v-if="detailLoading">加载中...</div>
        <el-empty v-else-if="!detail" description="暂无详情" />
        <div v-else class="detail-wrap">
          <el-descriptions :column="1" border>
            <el-descriptions-item label="trace_id">{{ detail.trace_id }}</el-descriptions-item>
            <el-descriptions-item label="request_id">{{ detail.request_id || '-' }}</el-descriptions-item>
            <el-descriptions-item label="session_id">{{ detail.session_id }}</el-descriptions-item>
            <el-descriptions-item label="created_at">{{ fmtDate(detail.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="query">{{ detail.question }}</el-descriptions-item>
            <el-descriptions-item label="normalized_query">{{ detail.normalized_query || '-' }}</el-descriptions-item>
            <el-descriptions-item label="rewritten_queries">
              <pre>{{ JSON.stringify(detail.rewritten_queries || [], null, 2) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="reason_code">
              {{ detail.abstain_reason || detail.failure_reason || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="task / scope / skill">
              {{ detail.task_type || '-' }} / {{ detail.selected_scope || '-' }} / {{ detail.selected_skill || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="workflow_summary">
              {{ (detail.debug_json || {}).workflow_summary || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="fallback / rounds / stop">
              {{ detail.fallback_triggered ?? '-' }} / {{ detail.retrieval_rounds ?? '-' }} / {{ detail.stop_reason || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="source coverage">
              source_count={{ detail.source_count ?? '-' }}, dominant_ratio={{ asPct(detail.dominant_source_ratio) }},
              multi_source_coverage={{ asPct(detail.multi_source_coverage) }}
            </el-descriptions-item>
            <el-descriptions-item label="retrieval_meta">
              <pre>{{ JSON.stringify({
                retrieval_strategy: detail.retrieval_strategy,
                strict_mode: detail.strict_mode,
                model_name: detail.model_name,
                latency_ms: detail.latency_ms,
                token_usage: detail.token_usage,
              }, null, 2) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="planner_meta">
              <pre>{{ pretty(detail.planner_meta) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="workflow_steps">
              <pre>{{ pretty(detail.workflow_steps) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="tool_traces">
              <pre>{{ pretty(detail.tool_traces) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="guardrail_events">
              <pre>{{ pretty(detail.guardrail_events) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="compare_result">
              <pre>{{ pretty(detail.compare_result) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="clarification_needed">
              {{ detail.clarification_needed ?? '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="evidence_bundles">
              <pre>{{ JSON.stringify(detail.evidence_bundles || {}, null, 2) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="references/selected_evidence">
              <pre>{{ JSON.stringify(detail.selected_evidence || [], null, 2) }}</pre>
            </el-descriptions-item>
            <el-descriptions-item label="开发预留(debug_json)">
              <pre>{{ JSON.stringify(detail.debug_json || {}, null, 2) }}</pre>
            </el-descriptions-item>
          </el-descriptions>

          <div class="retry-box">
            <el-divider content-position="left">retry / reindex</el-divider>
            <div class="retry-actions">
              <el-select v-model="pickedFileId" placeholder="选择 file_id" style="width: 220px" clearable>
                <el-option v-for="id in sourceFileIds" :key="id" :label="String(id)" :value="id" />
              </el-select>
              <el-input-number v-model="manualFileId" :min="1" placeholder="手动 file_id" />
              <el-button @click="confirmRetry(false)">retry</el-button>
              <el-button type="warning" @click="confirmRetry(true)">force reindex</el-button>
              <el-button @click="downloadExport">导出 JSON</el-button>
            </div>
          </div>
        </div>
      </el-drawer>
    </div>
  </AdminLayout>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AdminLayout from '../layouts/AdminLayout.vue'
import {
  exportTraceApi,
  getDiagnosticsTraceDetailApi,
  getDiagnosticsTracesApi,
  getReasonStatsApi,
  retryIndexFileApi,
  type ReasonStatsItem,
  type TraceDetail,
  type TraceItem,
} from '../api/adminDiagnostics'

const traces = ref<TraceItem[]>([])
const loading = ref(false)
const detailLoading = ref(false)
const detailVisible = ref(false)
const detail = ref<TraceDetail | null>(null)
const forbidden = ref(false)
const errorMsg = ref('')
const reasonStats = ref<ReasonStatsItem[]>([])
const total = ref(0)
const limit = ref(20)
const offset = ref(0)
const pickedFileId = ref<number | null>(null)
const manualFileId = ref<number | null>(null)

const filters = reactive({
  trace_id: '',
  request_id: '',
  session_id: '',
  is_abstained: '',
  failed: '',
})

const sourceFileIds = computed(() => detail.value?.source_file_ids || [])

function fmtDate(v?: string) {
  if (!v) return '-'
  return new Date(v).toLocaleString()
}

function snippet(v: string): string {
  return v.length > 60 ? `${v.slice(0, 60)}...` : v
}

function evidenceCount(item: TraceItem): number {
  return item.selected_evidence?.length || 0
}

function pretty(payload: unknown): string {
  return JSON.stringify(payload ?? {}, null, 2)
}

function asPct(v?: number | null): string {
  if (v === undefined || v === null) return '-'
  return `${(v * 100).toFixed(0)}%`
}

async function loadReasonStats() {
  try {
    reasonStats.value = await getReasonStatsApi()
  } catch {
    reasonStats.value = []
  }
}

async function loadTraces(nextOffset = 0) {
  loading.value = true
  forbidden.value = false
  errorMsg.value = ''
  try {
    offset.value = nextOffset
    const response = await getDiagnosticsTracesApi({
      ...filters,
      is_abstained: filters.is_abstained === '' ? undefined : filters.is_abstained,
      failed: filters.failed === '' ? undefined : filters.failed,
      limit: limit.value,
      offset: offset.value,
    })
    traces.value = response.items
    total.value = response.total
  } catch (error) {
    const msg = error instanceof Error ? error.message : '加载诊断列表失败'
    if (msg.includes('403') || msg.includes('无权限')) {
      forbidden.value = true
    }
    errorMsg.value = msg
    traces.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

async function openDetail(traceId: string) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  pickedFileId.value = null
  manualFileId.value = null
  try {
    detail.value = await getDiagnosticsTraceDetailApi(traceId)
    if (sourceFileIds.value.length > 0) pickedFileId.value = sourceFileIds.value[0] ?? null
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function confirmRetry(force: boolean) {
  const fileId = pickedFileId.value || manualFileId.value
  if (!fileId) {
    ElMessage.warning('请先选择或输入 file_id')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确认对 file_id=${fileId} 执行 ${force ? 'force reindex' : 'retry'}？`,
      '确认操作',
      { type: 'warning' },
    )
    await retryIndexFileApi(fileId, force)
    ElMessage.success(force ? '已触发 force reindex' : '已触发 retry')
  } catch (error) {
    if (error === 'cancel') return
    ElMessage.error(error instanceof Error ? error.message : '操作失败')
  }
}

async function downloadExport() {
  if (!detail.value?.trace_id) return
  try {
    const payload = await exportTraceApi(detail.value.trace_id)
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${detail.value.trace_id}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '导出失败')
  }
}

async function reloadAll() {
  await Promise.all([loadTraces(offset.value), loadReasonStats()])
}

reloadAll()
</script>

<style scoped>
.diag-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.page-card {
  border-radius: var(--ds-radius-lg, 16px);
}
.header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.page-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--ds-text, #1f1f1f);
}
.page-subtitle {
  color: var(--ds-text-secondary, #444746);
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.5;
  max-width: 480px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}
.footer-row {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
.reason-grid {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.detail-wrap pre {
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: ui-monospace, 'Cascadia Code', monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ds-text-secondary, #444746);
}
.retry-box {
  margin-top: 12px;
}
.retry-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.mb-12 {
  margin-bottom: 12px;
}
.ml-4 {
  margin-left: 4px;
}
</style>
