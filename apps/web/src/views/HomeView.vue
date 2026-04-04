<template>
  <AdminLayout>
    <div class="dashboard">
      <el-card class="welcome-card">
        <div class="welcome-header">
          <div>
            <div class="welcome-title">{{ systemStore.systemName }}</div>
            <div class="welcome-subtitle">{{ systemStore.labName }} · 统一管理资料，并为后续智能检索问答打好底座。</div>
          </div>
          <div class="quick-actions">
            <el-button type="primary" @click="router.push('/files')">进入文件中心</el-button>
            <el-button @click="router.push('/chat')">查看问答页</el-button>
          </div>
        </div>
      </el-card>

      <div class="stats-grid">
        <el-card class="stat-card">
          <div class="stat-label">总文件数</div>
          <div class="stat-value">{{ dashboard.summary.total_files }}</div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-label">已索引</div>
          <div class="stat-value success">{{ dashboard.summary.indexed_files }}</div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-label">待索引</div>
          <div class="stat-value warning">{{ dashboard.summary.pending_files }}</div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-label">索引失败</div>
          <div class="stat-value danger">{{ dashboard.summary.failed_files }}</div>
        </el-card>
      </div>

      <el-row :gutter="16">
        <el-col :span="16">
          <el-card class="panel-card">
            <template #header>
              <span>最近上传文件</span>
            </template>
            <el-table :data="dashboard.recent_files" v-loading="loading" style="width: 100%">
              <el-table-column prop="file_name" label="文件名" />
              <el-table-column prop="folder_name" label="目录" />
              <el-table-column prop="uploader" label="上传者" width="120" />
              <el-table-column label="索引状态" width="120">
                <template #default="scope">
                  <el-tag :type="getIndexStatusTagType(scope.row.index_status)">
                    {{ getIndexStatusLabel(scope.row.index_status) }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card class="ops-card panel-card">
            <template #header>
              <span>运行状态</span>
            </template>
            <div class="ops-list">
              <div class="ops-item">
                <span>QA 开关</span>
                <el-tag :type="dashboard.ops_status.qa_enabled ? 'success' : 'warning'">
                  {{ dashboard.ops_status.qa_enabled ? '已启用' : '未启用' }}
                </el-tag>
              </div>
              <div class="ops-item">
                <span>LLM 配置</span>
                <el-tag :type="dashboard.ops_status.llm_configured ? 'success' : 'danger'">
                  {{ dashboard.ops_status.llm_configured ? '正常' : '未完成' }}
                </el-tag>
              </div>
              <div class="ops-item">
                <span>Embedding 配置</span>
                <el-tag :type="dashboard.ops_status.embedding_configured ? 'success' : 'danger'">
                  {{ dashboard.ops_status.embedding_configured ? '正常' : '未完成' }}
                </el-tag>
              </div>
              <div class="ops-item ops-item-stack">
                <span>最近一次问答</span>
                <el-tag :type="getQaTagType(dashboard.ops_status.last_qa_success)">
                  {{ getQaStatusLabel(dashboard.ops_status.last_qa_success) }}
                </el-tag>
                <div class="ops-sub">
                  {{ dashboard.ops_status.last_qa_at || '暂无记录' }}
                </div>
                <div v-if="dashboard.ops_status.last_qa_error" class="ops-error">
                  {{ dashboard.ops_status.last_qa_error }}
                </div>
              </div>
              <div class="ops-item ops-item-stack">
                <span>最近活动时间</span>
                <div class="ops-sub">{{ dashboard.ops_status.last_activity_at || '暂无记录' }}</div>
              </div>
              <div class="ops-item ops-item-stack">
                <span>最近 LLM 测试</span>
                <el-tag :type="getQaTagType(dashboard.ops_status.last_llm_test_success)">
                  {{ getQaStatusLabel(dashboard.ops_status.last_llm_test_success) }}
                </el-tag>
                <div class="ops-sub">{{ dashboard.ops_status.last_llm_test_at || '暂无记录' }}</div>
                <div v-if="dashboard.ops_status.last_llm_test_detail" class="ops-error">
                  {{ dashboard.ops_status.last_llm_test_detail }}
                </div>
              </div>
              <div class="ops-item ops-item-stack">
                <span>最近 Embedding 测试</span>
                <el-tag :type="getQaTagType(dashboard.ops_status.last_embedding_test_success)">
                  {{ getQaStatusLabel(dashboard.ops_status.last_embedding_test_success) }}
                </el-tag>
                <div class="ops-sub">{{ dashboard.ops_status.last_embedding_test_at || '暂无记录' }}</div>
                <div v-if="dashboard.ops_status.last_embedding_test_detail" class="ops-error">
                  {{ dashboard.ops_status.last_embedding_test_detail }}
                </div>
              </div>
            </div>
          </el-card>

          <el-card class="quick-card panel-card">
            <template #header>
              <span>快捷入口</span>
            </template>
            <div class="action-list">
              <el-button type="primary" plain @click="router.push('/files')">上传和管理文件</el-button>
              <el-button type="warning" plain @click="router.push('/chat')">进入问答页</el-button>
              <el-button plain @click="loadDashboard">刷新统计</el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-card class="panel-card">
            <template #header>
              <span>最近索引完成</span>
            </template>
            <el-table :data="dashboard.recent_indexed_files" v-loading="loading" style="width: 100%">
              <el-table-column prop="file_name" label="文件名" />
              <el-table-column prop="indexed_at" label="索引时间" width="180" />
              <el-table-column label="状态" width="120">
                <template #default="scope">
                  <el-tag :type="getIndexStatusTagType(scope.row.index_status)">
                    {{ getIndexStatusLabel(scope.row.index_status) }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card class="panel-card">
            <template #header>
              <span>最近索引失败</span>
            </template>
            <el-table :data="dashboard.recent_failed_files" v-loading="loading" style="width: 100%">
              <el-table-column prop="file_name" label="文件名" width="180" />
              <el-table-column prop="index_error" label="失败原因" />
            </el-table>
          </el-card>
        </el-col>
      </el-row>

      <el-card class="panel-card">
        <template #header>
          <span>最近问答记录</span>
        </template>
        <el-table :data="dashboard.recent_qa_records" v-loading="loading" style="width: 100%">
          <el-table-column prop="session_title" label="会话" width="180" />
          <el-table-column prop="question" label="问题" />
          <el-table-column prop="scope_type" label="范围" width="120" />
          <el-table-column prop="created_at" label="时间" width="180" />
        </el-table>
      </el-card>

      <el-card class="panel-card">
        <template #header>
          <span>最近问答失败</span>
        </template>
        <el-table :data="dashboard.recent_failed_qa_records" v-loading="loading" style="width: 100%">
          <el-table-column prop="session_title" label="会话" width="180" />
          <el-table-column prop="error" label="失败原因" />
          <el-table-column prop="created_at" label="时间" width="180" />
        </el-table>
      </el-card>
    </div>
  </AdminLayout>
</template>

<script setup lang="ts">
import AdminLayout from '../layouts/AdminLayout.vue'
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getDashboardApi, type DashboardResponse } from '../api/files'
import { useSystemStore } from '../stores/system'

const router = useRouter()
const systemStore = useSystemStore()
const loading = ref(false)
const dashboard = reactive<DashboardResponse>({
  summary: {
    total_files: 0,
    indexed_files: 0,
    pending_files: 0,
    failed_files: 0,
  },
  recent_files: [],
  recent_indexed_files: [],
  recent_failed_files: [],
  recent_qa_records: [],
  recent_failed_qa_records: [],
  ops_status: {
    qa_enabled: false,
    llm_configured: false,
    embedding_configured: false,
    last_qa_success: null,
    last_qa_at: null,
    last_qa_error: null,
    last_llm_test_success: null,
    last_llm_test_at: null,
    last_llm_test_detail: null,
    last_embedding_test_success: null,
    last_embedding_test_at: null,
    last_embedding_test_detail: null,
    last_activity_at: null,
  },
})

const getIndexStatusLabel = (status?: string) => {
  if (status === 'indexed') return '已索引'
  if (status === 'failed') return '失败'
  return '待处理'
}

const getIndexStatusTagType = (status?: string) => {
  if (status === 'indexing') return 'info'
  if (status === 'indexed') return 'success'
  if (status === 'failed') return 'danger'
  return 'warning'
}

const getQaStatusLabel = (success?: boolean | null) => {
  if (success === true) return '成功'
  if (success === false) return '失败'
  return '暂无记录'
}

const getQaTagType = (success?: boolean | null) => {
  if (success === true) return 'success'
  if (success === false) return 'danger'
  return 'info'
}

const loadDashboard = async () => {
  try {
    loading.value = true
    const res = await getDashboardApi()
    dashboard.summary = res.summary
    dashboard.recent_files = res.recent_files
    dashboard.recent_indexed_files = res.recent_indexed_files
    dashboard.recent_failed_files = res.recent_failed_files
    dashboard.recent_qa_records = res.recent_qa_records
    dashboard.recent_failed_qa_records = res.recent_failed_qa_records
    dashboard.ops_status = res.ops_status
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载首页统计失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadDashboard()
})
</script>

<style scoped>
.dashboard { display: flex; flex-direction: column; gap: 16px; }
.welcome-card { border-radius: 16px; background: linear-gradient(135deg, rgba(255, 206, 158, 0.9), rgba(255, 236, 214, 0.95)) !important; }
.panel-card { border-radius: 16px; }
.welcome-header { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.welcome-title { font-size: 24px; font-weight: 700; color: #6a3417; }
.welcome-subtitle { color: #8f6148; margin-top: 6px; }
.quick-actions { display: flex; gap: 12px; flex-wrap: wrap; }
.stats-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.stat-card { border-radius: 16px; }
.stat-label { color: #909399; font-size: 13px; }
.stat-value { font-size: 30px; font-weight: 700; margin-top: 8px; }
.stat-value.success { color: #67c23a; }
.stat-value.warning { color: #e6a23c; }
.stat-value.danger { color: #f56c6c; }
.action-list { display: flex; flex-direction: column; gap: 12px; }
.ops-card,
.quick-card { margin-bottom: 16px; }
.ops-list { display: flex; flex-direction: column; gap: 12px; }
.ops-item { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.ops-item-stack { align-items: flex-start; flex-direction: column; }
.ops-sub { color: var(--text-secondary); font-size: 12px; }
.ops-error { color: var(--danger-color); font-size: 12px; line-height: 1.5; }
</style>