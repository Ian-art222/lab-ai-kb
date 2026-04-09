import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  getSettingsShellApi,
  type SettingItem,
  type SettingStatus,
} from '../api/settings'

const defaultSettings: SettingItem = {
  system_name: '实验室知识库',
  lab_name: '实验室内部',
  llm_provider: 'openai_compatible',
  llm_api_base: '',
  llm_api_key_masked: '',
  llm_api_key_configured: false,
  llm_model: '',
  embedding_provider: 'openai_compatible',
  embedding_api_base: '',
  embedding_api_key_masked: '',
  embedding_api_key_configured: false,
  embedding_model: '',
  embedding_batch_size: null,
  embedding_effective_batch_size: 100,
  qa_enabled: false,
  sidebar_auto_collapse: false,
  theme_mode: 'warm',
  updated_at: new Date().toISOString(),
}

const defaultStatus: SettingStatus = {
  qa_enabled: false,
  llm_provider: 'openai_compatible',
  llm_model: '',
  llm_configured: false,
  embedding_provider: 'openai_compatible',
  embedding_model: '',
  embedding_configured: false,
  embedding_batch_size: null,
  embedding_effective_batch_size: 100,
  current_chat_standard: '',
  current_index_standard: '',
  indexed_files_count: 0,
  index_standard_mismatch: false,
  index_standard_mismatch_count: 0,
  sidebar_auto_collapse: false,
  theme_mode: 'warm',
}

export const useSystemStore = defineStore('system', () => {
  const settings = ref<SettingItem>({ ...defaultSettings })
  const status = ref<SettingStatus>({ ...defaultStatus })
  const loaded = ref(false)

  const systemName = computed(() => settings.value.system_name || '实验室知识库')
  const labName = computed(() => settings.value.lab_name || '实验室内部')

  const fetchSettings = async () => {
    const shell = await getSettingsShellApi()
    settings.value = {
      ...defaultSettings,
      system_name: shell.system_name,
      lab_name: shell.lab_name,
      qa_enabled: shell.qa_enabled,
      sidebar_auto_collapse: shell.sidebar_auto_collapse,
      theme_mode: shell.theme_mode,
      llm_provider: shell.llm_provider,
      llm_model: shell.llm_model,
      embedding_provider: shell.embedding_provider,
      embedding_model: shell.embedding_model,
      embedding_batch_size: shell.embedding_batch_size ?? null,
      embedding_effective_batch_size: shell.embedding_effective_batch_size,
      updated_at: shell.updated_at,
    }
    status.value = {
      ...defaultStatus,
      qa_enabled: shell.qa_enabled,
      llm_provider: shell.llm_provider,
      llm_model: shell.llm_model,
      llm_configured: shell.llm_configured,
      embedding_provider: shell.embedding_provider,
      embedding_model: shell.embedding_model,
      embedding_configured: shell.embedding_configured,
      embedding_batch_size: shell.embedding_batch_size ?? null,
      embedding_effective_batch_size: shell.embedding_effective_batch_size,
      current_chat_standard: shell.current_chat_standard,
      current_index_standard: shell.current_index_standard,
      indexed_files_count: shell.indexed_files_count,
      index_standard_mismatch: shell.index_standard_mismatch,
      index_standard_mismatch_count: shell.index_standard_mismatch_count,
      sidebar_auto_collapse: shell.sidebar_auto_collapse,
      theme_mode: shell.theme_mode,
    }
    loaded.value = true
  }

  const applySettings = (next: SettingItem) => {
    settings.value = next
    status.value = {
      qa_enabled: next.qa_enabled,
      llm_provider: next.llm_provider,
      llm_model: next.llm_model,
      llm_configured: next.llm_api_key_configured && !!next.llm_api_base && !!next.llm_model,
      embedding_provider: next.embedding_provider,
      embedding_model: next.embedding_model,
      embedding_configured:
        next.embedding_api_key_configured &&
        !!next.embedding_api_base &&
        !!next.embedding_model,
      embedding_batch_size: next.embedding_batch_size ?? null,
      embedding_effective_batch_size: next.embedding_effective_batch_size,
      current_chat_standard: `${next.llm_provider}:${next.llm_model}`.replace(/:$/, ''),
      current_index_standard: `${next.embedding_provider}:${next.embedding_model}`.replace(/:$/, ''),
      indexed_files_count: 0,
      index_standard_mismatch: false,
      index_standard_mismatch_count: 0,
      sidebar_auto_collapse: next.sidebar_auto_collapse,
      theme_mode: next.theme_mode,
    }
    loaded.value = true
  }

  return {
    settings,
    status,
    loaded,
    systemName,
    labName,
    fetchSettings,
    applySettings,
  }
})
