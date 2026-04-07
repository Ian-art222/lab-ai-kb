import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent } from 'vue'

vi.mock('../../api/adminDiagnostics', () => ({
  getDiagnosticsTracesApi: vi.fn(async () => ({ total: 1, limit: 20, offset: 0, items: [{ trace_id: 't-1', session_id: 1, question: 'q', is_abstained: true, failed: false, abstain_reason: 'low_retrieval_confidence', created_at: '2026-04-01T00:00:00' }] })),
  getDiagnosticsTraceDetailApi: vi.fn(async () => ({ trace_id: 't-1', session_id: 1, question: 'q', is_abstained: true, failed: false, source_file_ids: [7], created_at: '2026-04-01T00:00:00' })),
  getReasonStatsApi: vi.fn(async () => ([{ reason_code: 'low_retrieval_confidence', count: 3 }])),
  retryIndexFileApi: vi.fn(async () => undefined),
  exportTraceApi: vi.fn(async () => ({ trace_id: 't-1' })),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn(async () => true) },
}))

import AdminDiagnosticsView from '../AdminDiagnosticsView.vue'
import { useAuthStore } from '../../stores/auth'

const stubs = {
  AdminLayout: defineComponent({ template: '<div><slot /></div>' }),
  'el-card': defineComponent({ template: '<div><slot /><slot name="header" /></div>' }),
  'el-result': true,
  'el-input': true,
  'el-select': true,
  'el-option': true,
  'el-button': defineComponent({ template: '<button><slot /></button>' }),
  'el-alert': true,
  'el-table': defineComponent({ props: ['data'], template: '<div><slot /></div>' }),
  'el-table-column': true,
  'el-tag': defineComponent({ template: '<span><slot /></span>' }),
  'el-pagination': true,
  'el-divider': true,
  'el-empty': true,
  'el-drawer': defineComponent({ template: '<div><slot /></div>' }),
  'el-descriptions': defineComponent({ template: '<div><slot /></div>' }),
  'el-descriptions-item': defineComponent({ template: '<div><slot /></div>' }),
  'el-input-number': true,
}

describe('AdminDiagnosticsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const auth = useAuthStore()
    auth.setAuth('t', 'admin', 'admin')
  })

  it('renders title and reason code area', async () => {
    const wrapper = mount(AdminDiagnosticsView, { global: { stubs } })
    await Promise.resolve()
    expect(wrapper.text()).toContain('管理员诊断中心')
    expect(wrapper.text()).toContain('Reason 码统计')
  })
})
