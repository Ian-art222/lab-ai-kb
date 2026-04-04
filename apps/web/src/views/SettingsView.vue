<template>
  <AdminLayout>
    <div class="settings-page">
      <el-card class="settings-card">
        <template #header>
          <div class="page-header">
            <div>
              <div class="page-title">系统设置</div>
              <div class="page-subtitle">统一维护系统名称、模型 API 配置与侧边栏交互偏好。</div>
            </div>
            <el-button type="primary" :loading="saving" @click="handleSave">保存设置</el-button>
          </div>
        </template>

        <el-result
          v-if="!authStore.isAdmin"
          icon="warning"
          title="无权限访问"
          sub-title="只有管理员可以修改系统设置。"
        />

        <template v-else>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-card class="inner-card">
                <template #header><span>基础信息</span></template>
                <el-form label-position="top">
                  <el-form-item label="系统名称">
                    <el-input v-model="form.system_name" />
                  </el-form-item>
                  <el-form-item label="实验室名称">
                    <el-input v-model="form.lab_name" />
                  </el-form-item>
                </el-form>
              </el-card>
            </el-col>

            <el-col :span="12">
              <el-card class="inner-card">
                <template #header><span>外观设置</span></template>
                <el-form label-position="top">
                  <el-form-item label="主题模式">
                    <el-select v-model="form.theme_mode" style="width: 100%">
                      <el-option label="暖色产品风" value="warm" />
                    </el-select>
                  </el-form-item>
                  <el-form-item label="侧边栏自动收起">
                    <el-switch v-model="form.sidebar_auto_collapse" />
                  </el-form-item>
                  <el-form-item label="启用智能问答">
                    <el-switch v-model="form.qa_enabled" />
                  </el-form-item>
                </el-form>
              </el-card>
            </el-col>
          </el-row>

          <el-row :gutter="16" style="margin-top: 16px">
            <el-col :span="12">
              <el-card class="inner-card">
                <template #header>
                  <div class="card-header-inline">
                    <span>LLM API 配置</span>
                    <el-button size="small" :loading="testingLlm" @click="handleTestLlm">
                      测试连接
                    </el-button>
                  </div>
                </template>
                <el-form label-position="top">
                  <el-form-item label="LLM Provider">
                    <el-select v-model="form.llm_provider" style="width: 100%">
                      <el-option label="OpenAI" value="openai" />
                      <el-option label="Anthropic" value="anthropic" />
                      <el-option label="Gemini" value="gemini" />
                      <el-option label="OpenAI Compatible" value="openai_compatible" />
                      <el-option label="DeepSeek" value="deepseek" />
                      <el-option label="Kimi" value="kimi" />
                      <el-option label="Qwen / DashScope" value="qwen" />
                      <el-option label="Tencent Hunyuan" value="hunyuan" />
                    </el-select>
                    <div class="masked-tip">
                      <template v-if="needsCredentialVerification(form.llm_provider)">
                        当前协议已适配，但当前环境尚未完成该 provider 的真实账号联调验证。
                      </template>
                      <template v-else>
                        已支持通过统一 provider 适配层接入 chat 能力。
                      </template>
                    </div>
                  </el-form-item>
                  <el-form-item label="LLM API Base URL">
                    <el-input v-model="form.llm_api_base" />
                    <div class="masked-tip">{{ llmApiBaseTip }}</div>
                  </el-form-item>
                  <el-form-item label="LLM Model">
                    <el-input v-model="form.llm_model" />
                    <div v-if="llmModelHint" class="masked-tip">{{ llmModelHint }}</div>
                    <div class="masked-tip">
                      聊天模型只影响最终回答生成，不会改变知识库底层检索使用的 embedding 索引。
                    </div>
                  </el-form-item>
                  <el-form-item label="LLM API Key">
                    <el-input v-model="form.llm_api_key" type="password" show-password />
                    <div class="masked-tip">当前状态：{{ settings?.llm_api_key_masked || '未配置' }}</div>
                    <div v-if="llmTestDetail" class="test-result-line">
                      <el-tag :type="llmTestOk ? 'success' : 'danger'">
                        {{ llmTestOk ? '连接成功' : '连接失败' }}
                      </el-tag>
                      <span>{{ llmTestDetail }}</span>
                    </div>
                  </el-form-item>
                </el-form>
              </el-card>
            </el-col>

            <el-col :span="12">
              <el-card class="inner-card">
                <template #header>
                  <div class="card-header-inline">
                    <span>Embedding API 配置</span>
                    <el-button size="small" :loading="testingEmbedding" @click="handleTestEmbedding">
                      测试连接
                    </el-button>
                  </div>
                </template>
                <el-form label-position="top">
                  <el-form-item label="Embedding Provider">
                    <el-select v-model="form.embedding_provider" style="width: 100%">
                      <el-option label="OpenAI" value="openai" />
                      <el-option label="Gemini" value="gemini" />
                      <el-option label="OpenAI Compatible" value="openai_compatible" />
                      <el-option label="DeepSeek" value="deepseek" />
                      <el-option label="Kimi" value="kimi" />
                      <el-option label="Qwen / DashScope" value="qwen" />
                      <el-option label="Tencent Hunyuan" value="hunyuan" />
                      <el-option label="Anthropic（不支持 embeddings）" value="anthropic" disabled />
                    </el-select>
                    <div class="masked-tip">
                      Anthropic 当前仅支持 chat，不支持 embeddings；索引与检索请使用 Gemini、OpenAI 或 OpenAI-compatible provider。
                    </div>
                  </el-form-item>
                  <el-form-item label="Embedding API Base URL">
                    <el-input v-model="form.embedding_api_base" />
                    <div class="masked-tip">{{ embeddingApiBaseTip }}</div>
                  </el-form-item>
                  <el-form-item label="Embedding Model">
                    <el-input v-model="form.embedding_model" />
                    <div v-if="embeddingModelHint" class="masked-tip">{{ embeddingModelHint }}</div>
                    <div class="masked-tip">
                      Retrieval embedding 是知识库索引标准。切换 Embedding Provider 或 Model 后，已建立索引的文件通常需要重新索引。
                    </div>
                  </el-form-item>
                  <el-form-item label="Embedding Batch Size">
                    <el-input
                      v-model="form.embedding_batch_size"
                      placeholder="留空则使用环境变量 EMBED_BATCH_SIZE 或默认值"
                      clearable
                    />
                    <div class="masked-tip">
                      用于控制建立索引时每批发送多少条文本做 embedding。不同 provider 的上限不同，例如 Qwen / DashScope 的
                      text-embedding-v4 单批最多 10。下方「配置状态」会显示按当前 provider 计算后的生效批大小。
                    </div>
                  </el-form-item>
                  <el-form-item label="Embedding API Key">
                    <el-input v-model="form.embedding_api_key" type="password" show-password />
                    <div class="masked-tip">当前状态：{{ settings?.embedding_api_key_masked || '未配置' }}</div>
                    <div v-if="embeddingTestDetail" class="test-result-line">
                      <el-tag :type="embeddingTestOk ? 'success' : 'danger'">
                        {{ embeddingTestOk ? '连接成功' : '连接失败' }}
                      </el-tag>
                      <span>{{ embeddingTestDetail }}</span>
                    </div>
                  </el-form-item>
                </el-form>
              </el-card>
            </el-col>
          </el-row>

          <el-card class="status-card">
            <template #header><span>配置状态</span></template>
            <div class="status-grid">
              <el-tag :type="status?.llm_configured ? 'success' : 'warning'">
                {{ status?.llm_configured ? `LLM 已配置（${status?.llm_provider}）` : 'LLM 未完整配置' }}
              </el-tag>
              <el-tag :type="status?.embedding_configured ? 'success' : 'warning'">
                {{ status?.embedding_configured ? `Embedding 已配置（${status?.embedding_provider}）` : 'Embedding 未完整配置' }}
              </el-tag>
              <el-tag type="info" v-if="status?.current_chat_standard">
                当前聊天模型：{{ status.current_chat_standard }}
              </el-tag>
              <el-tag type="info" v-if="status?.current_index_standard">
                当前知识库索引标准：{{ status.current_index_standard }}
              </el-tag>
              <el-tag type="info" v-if="status?.embedding_effective_batch_size != null">
                Embedding 生效批大小：{{ status.embedding_effective_batch_size }}
              </el-tag>
              <el-tag :type="status?.qa_enabled ? 'success' : 'info'">
                {{ status?.qa_enabled ? '智能问答已启用' : '智能问答未启用' }}
              </el-tag>
            </div>
            <el-alert
              v-if="status?.index_standard_mismatch"
              title="当前 retrieval embedding 配置与部分已建立索引的文件标准不一致，请重新索引相关文件。"
              :description="`当前索引标准：${status.current_index_standard || '未配置'}；检测到 ${status.index_standard_mismatch_count} 个已索引文件需要重建。`"
              type="warning"
              :closable="false"
              style="margin-top: 16px"
            />
            <el-alert
              title="说明：聊天模型可以随时切换并复用同一套检索结果；但 Retrieval Embedding Provider / Model 变更后，不能继续混用旧索引。"
              type="info"
              :closable="false"
              style="margin-top: 16px"
            />
            <div class="test-history-grid">
              <div class="test-history-card">
                <div class="test-history-title">最近 LLM 测试</div>
                <el-tag :type="status?.last_llm_test_success === true ? 'success' : status?.last_llm_test_success === false ? 'danger' : 'info'">
                  {{ status?.last_llm_test_success === true ? '成功' : status?.last_llm_test_success === false ? '失败' : '暂无记录' }}
                </el-tag>
                <div class="masked-tip">{{ status?.last_llm_test_at || '暂无时间' }}</div>
                <div v-if="status?.last_llm_test_detail" class="test-detail">{{ status.last_llm_test_detail }}</div>
              </div>
              <div class="test-history-card">
                <div class="test-history-title">最近 Embedding 测试</div>
                <el-tag :type="status?.last_embedding_test_success === true ? 'success' : status?.last_embedding_test_success === false ? 'danger' : 'info'">
                  {{ status?.last_embedding_test_success === true ? '成功' : status?.last_embedding_test_success === false ? '失败' : '暂无记录' }}
                </el-tag>
                <div class="masked-tip">{{ status?.last_embedding_test_at || '暂无时间' }}</div>
                <div v-if="status?.last_embedding_test_detail" class="test-detail">{{ status.last_embedding_test_detail }}</div>
              </div>
            </div>
            <el-alert
              title="安全提示：API Key 仅显示脱敏结果；留空表示保留现有密钥，请不要把脱敏值原样重新保存。"
              type="warning"
              :closable="false"
              style="margin-top: 16px"
            />
          </el-card>
        </template>
      </el-card>
    </div>
  </AdminLayout>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AdminLayout from '../layouts/AdminLayout.vue'
import {
  getSettingsApi,
  getSettingsStatusApi,
  testEmbeddingConnectionApi,
  testLlmConnectionApi,
  updateSettingsApi,
  type SettingItem,
  type SettingStatus,
} from '../api/settings'
import { useAuthStore } from '../stores/auth'
import { useSystemStore } from '../stores/system'

const authStore = useAuthStore()
const systemStore = useSystemStore()
const saving = ref(false)
const testingLlm = ref(false)
const testingEmbedding = ref(false)
const llmTestOk = ref<boolean | null>(null)
const llmTestDetail = ref('')
const embeddingTestOk = ref<boolean | null>(null)
const embeddingTestDetail = ref('')
const settings = ref<SettingItem | null>(null)
const status = ref<SettingStatus | null>(null)
const isSyncingForm = ref(false)

const LLM_PROVIDER_DEFAULT_BASES: Record<string, string> = {
  gemini: 'https://generativelanguage.googleapis.com/v1beta',
  anthropic: 'https://api.anthropic.com/v1',
  openai: 'https://api.openai.com/v1',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  dashscope: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  openai_compatible: '',
}

const EMBEDDING_PROVIDER_DEFAULT_BASES: Record<string, string> = {
  gemini: 'https://generativelanguage.googleapis.com/v1beta',
  openai: 'https://api.openai.com/v1',
  qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  dashscope: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  openai_compatible: '',
  anthropic: '',
}

const form = reactive({
  system_name: '',
  lab_name: '',
  llm_provider: 'openai_compatible',
  llm_api_base: '',
  llm_api_key: '',
  llm_model: '',
  embedding_provider: 'openai_compatible',
  embedding_api_base: '',
  embedding_api_key: '',
  embedding_model: '',
  embedding_batch_size: '',
  qa_enabled: false,
  sidebar_auto_collapse: false,
  theme_mode: 'warm',
})

const unsupportedEmbeddingMessage =
  'Anthropic 当前仅支持 chat，不支持 embeddings，请改用 Gemini、OpenAI 或 OpenAI-compatible provider。'

const needsCredentialVerification = (provider: string) =>
  provider === 'openai' || provider === 'anthropic'

const getDefaultBaseUrl = (service: 'llm' | 'embedding', provider: string): string | null => {
  const mapping =
    service === 'llm' ? LLM_PROVIDER_DEFAULT_BASES : EMBEDDING_PROVIDER_DEFAULT_BASES
  const value = mapping[provider]
  return value ? value : null
}

const maybeApplyProviderDefaultBase = ({
  service,
  nextProvider,
  previousProvider,
  currentBase,
  setBase,
}: {
  service: 'llm' | 'embedding'
  nextProvider: string
  previousProvider?: string
  currentBase: string
  setBase: (next: string) => void
}) => {
  const trimmedBase = currentBase.trim()
  const nextDefault = getDefaultBaseUrl(service, nextProvider)
  const previousDefault = previousProvider
    ? getDefaultBaseUrl(service, previousProvider)
    : null

  if (!trimmedBase) {
    if (nextDefault) {
      setBase(nextDefault)
    }
    return
  }

  if (previousDefault && trimmedBase === previousDefault && nextDefault) {
    setBase(nextDefault)
  }
}

const llmApiBaseTip = computed(() => {
  if (form.llm_provider === 'openai_compatible') {
    return 'OpenAI-compatible 通常使用自定义网关或第三方兼容地址，请按实际服务商填写。'
  }
  if (form.llm_provider === 'qwen') {
    return '默认会填入 DashScope OpenAI-compatible 地址；如使用代理或企业网关，可手动修改。'
  }
  return '已根据 Provider 自动填入默认 Base URL，可手动修改。'
})

const embeddingApiBaseTip = computed(() => {
  if (form.embedding_provider === 'openai_compatible') {
    return 'OpenAI-compatible 通常使用自定义网关或第三方兼容地址，请按实际服务商填写。'
  }
  if (form.embedding_provider === 'qwen') {
    return '默认已填 DashScope OpenAI-compatible 地址；如使用代理或企业网关，可手动修改。'
  }
  return '已根据 Provider 自动填入默认 Base URL，可手动修改。'
})

const llmModelHint = computed(() => {
  if (form.llm_provider === 'gemini' && !form.llm_model.trim()) {
    return '可填写 Gemini 对应模型，例如 gemini-2.5-flash。'
  }
  if (form.llm_provider === 'qwen' && !form.llm_model.trim()) {
    return '可按实际开通情况填写 Qwen 模型，例如 qwen-plus 或 qwen-max。'
  }
  return ''
})

const embeddingModelHint = computed(() => {
  if (form.embedding_provider === 'qwen' && !form.embedding_model.trim()) {
    return '推荐填写 DashScope 的 embedding 模型，例如 text-embedding-v4。'
  }
  if (form.embedding_provider === 'gemini' && !form.embedding_model.trim()) {
    return '可填写 Gemini 的 embedding 模型，例如 text-embedding-004。'
  }
  return ''
})

const validateProviderSelection = () => {
  if (form.embedding_provider === 'anthropic') {
    ElMessage.error(unsupportedEmbeddingMessage)
    return false
  }
  return true
}

const fillForm = (data: SettingItem) => {
  isSyncingForm.value = true
  form.system_name = data.system_name
  form.lab_name = data.lab_name
  form.llm_provider = data.llm_provider
  form.llm_api_base = data.llm_api_base
  form.llm_api_key = ''
  form.llm_model = data.llm_model
  form.embedding_provider = data.embedding_provider
  form.embedding_api_base = data.embedding_api_base
  form.embedding_api_key = ''
  form.embedding_model = data.embedding_model
  form.embedding_batch_size =
    data.embedding_batch_size != null && data.embedding_batch_size !== undefined
      ? String(data.embedding_batch_size)
      : ''
  form.qa_enabled = data.qa_enabled
  form.sidebar_auto_collapse = data.sidebar_auto_collapse
  form.theme_mode = data.theme_mode
  isSyncingForm.value = false
}

watch(
  () => form.llm_provider,
  (nextProvider, previousProvider) => {
    if (isSyncingForm.value) return
    maybeApplyProviderDefaultBase({
      service: 'llm',
      nextProvider,
      previousProvider,
      currentBase: form.llm_api_base,
      setBase: (next) => {
        form.llm_api_base = next
      },
    })
  },
)

watch(
  () => form.embedding_provider,
  (nextProvider, previousProvider) => {
    if (isSyncingForm.value) return
    maybeApplyProviderDefaultBase({
      service: 'embedding',
      nextProvider,
      previousProvider,
      currentBase: form.embedding_api_base,
      setBase: (next) => {
        form.embedding_api_base = next
      },
    })
  },
)

const loadSettings = async () => {
  if (!authStore.isAdmin) return
  try {
    settings.value = await getSettingsApi()
    status.value = await getSettingsStatusApi()
    fillForm(settings.value)
    systemStore.applySettings(settings.value)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载设置失败')
  }
}

const parseEmbeddingBatchSizeForSave = (): number | null => {
  const raw = form.embedding_batch_size.trim()
  if (!raw) return null
  const n = Number(raw)
  if (!Number.isInteger(n) || n < 1) {
    throw new Error('Embedding Batch Size 须为 ≥1 的整数，或留空以使用环境变量与默认值')
  }
  if (n > 100) {
    throw new Error('Embedding Batch Size 不能超过 100')
  }
  if (form.embedding_provider === 'qwen' && n > 10) {
    throw new Error('Qwen / DashScope 的 embedding 单批最多 10 条，请将该值设为不超过 10')
  }
  return n
}

const handleSave = async () => {
  if (!validateProviderSelection()) return
  let embeddingBatchSize: number | null
  try {
    embeddingBatchSize = parseEmbeddingBatchSizeForSave()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : 'Embedding Batch Size 无效')
    return
  }
  try {
    saving.value = true
    const next = await updateSettingsApi({
      ...form,
      embedding_batch_size: embeddingBatchSize,
      llm_api_key: form.llm_api_key.trim() ? form.llm_api_key : null,
      embedding_api_key: form.embedding_api_key.trim() ? form.embedding_api_key : null,
    })
    settings.value = next
    status.value = await getSettingsStatusApi()
    fillForm(next)
    systemStore.applySettings(next)
    ElMessage.success('系统设置已保存')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存设置失败')
  } finally {
    saving.value = false
  }
}

const handleTestLlm = async () => {
  try {
    testingLlm.value = true
    const result = await testLlmConnectionApi({
      provider: form.llm_provider,
      api_base: form.llm_api_base.trim(),
      api_key: form.llm_api_key.trim(),
      model: form.llm_model.trim(),
    })
    llmTestOk.value = result.ok
    llmTestDetail.value = result.detail
    status.value = await getSettingsStatusApi()
    ElMessage.success(result.detail)
  } catch (error) {
    llmTestOk.value = false
    llmTestDetail.value = error instanceof Error ? error.message : 'LLM 测试失败'
    status.value = await getSettingsStatusApi().catch(() => status.value)
    ElMessage.error(llmTestDetail.value)
  } finally {
    testingLlm.value = false
  }
}

const handleTestEmbedding = async () => {
  if (!validateProviderSelection()) return
  try {
    testingEmbedding.value = true
    const result = await testEmbeddingConnectionApi({
      provider: form.embedding_provider,
      api_base: form.embedding_api_base.trim(),
      api_key: form.embedding_api_key.trim(),
      model: form.embedding_model.trim(),
    })
    embeddingTestOk.value = result.ok
    embeddingTestDetail.value = result.detail
    status.value = await getSettingsStatusApi()
    ElMessage.success(result.detail)
  } catch (error) {
    embeddingTestOk.value = false
    embeddingTestDetail.value = error instanceof Error ? error.message : 'Embedding 测试失败'
    status.value = await getSettingsStatusApi().catch(() => status.value)
    ElMessage.error(embeddingTestDetail.value)
  } finally {
    testingEmbedding.value = false
  }
}

loadSettings()
</script>

<style scoped>
.settings-page { display: flex; flex-direction: column; gap: 16px; }
.settings-card,
.inner-card,
.status-card { border-radius: var(--card-radius); }
.page-header { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
.page-title { font-size: 22px; font-weight: 700; color: var(--text-primary); }
.page-subtitle { color: var(--text-secondary); margin-top: 6px; }
.card-header-inline { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.masked-tip { color: var(--text-secondary); font-size: 12px; margin-top: 8px; }
.test-result-line { display: flex; align-items: center; gap: 8px; margin-top: 8px; color: var(--text-secondary); font-size: 12px; }
.status-grid { display: flex; gap: 12px; flex-wrap: wrap; }
.test-history-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.test-history-card { border: 1px solid #f4ddcc; border-radius: 14px; padding: 12px; background: #fffaf6; }
.test-history-title { font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
.test-detail { margin-top: 8px; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
</style>
