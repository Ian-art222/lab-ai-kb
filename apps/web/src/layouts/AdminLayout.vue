<template>
  <div class="admin-layout">
    <div class="layout-shell" @mousemove="onLayoutMouseMove">
      <aside
        class="sidebar"
        :class="{ collapsed: sidebarCollapsed, floating: autoCollapseEnabled }"
        @mouseenter="handleSidebarEnter"
        @mouseleave="handleSidebarLeave"
      >
        <div class="brand-block">
          <div class="brand-mark">LK</div>
          <div class="brand-text-clip" :class="{ 'is-collapsed': sidebarCollapsed }">
            <div class="brand-text">
              <div class="brand-title">{{ systemStore.systemName }}</div>
              <div class="brand-subtitle">{{ systemStore.labName }}</div>
            </div>
          </div>
        </div>

        <el-menu
          router
          :default-active="$route.path"
          :collapse="sidebarCollapsed"
          :collapse-transition="true"
          class="sidebar-menu"
        >
          <el-menu-item index="/">
            <el-icon><House /></el-icon>
            <template #title>首页</template>
          </el-menu-item>
          <el-menu-item index="/files">
            <el-icon><Folder /></el-icon>
            <template #title>文件中心</template>
          </el-menu-item>
          <el-menu-item index="/chat">
            <el-icon><ChatDotRound /></el-icon>
            <template #title>智能问答</template>
          </el-menu-item>
          <el-menu-item v-if="authStore.canManageUsers" index="/users">
            <el-icon><User /></el-icon>
            <template #title>用户管理</template>
          </el-menu-item>
          <el-menu-item v-if="authStore.isRoot" index="/admin/diagnostics">
            <el-icon><DataAnalysis /></el-icon>
            <template #title>诊断中心</template>
          </el-menu-item>
          <el-menu-item v-if="authStore.isRoot" index="/settings">
            <el-icon><Setting /></el-icon>
            <template #title>系统设置</template>
          </el-menu-item>
        </el-menu>

        <div class="sidebar-footer">
          <el-tooltip :content="autoCollapseEnabled ? '切换为固定展开' : '切换为自动收起'" placement="right">
            <el-button circle class="side-action" @click="toggleSidebarMode">
              <el-icon><SwitchButton /></el-icon>
            </el-button>
          </el-tooltip>
          <el-tooltip :content="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'" placement="right">
            <el-button circle class="side-action" @click="toggleSidebarCollapse">
              <el-icon><Fold v-if="!sidebarCollapsed" /><Expand v-else /></el-icon>
            </el-button>
          </el-tooltip>
        </div>
      </aside>

      <div class="main-shell">
        <header class="topbar">
          <div>
            <div class="topbar-title">{{ systemStore.systemName }}</div>
            <div class="topbar-subtitle">红花课题组</div>
          </div>

          <div class="topbar-actions">
            <el-tag effect="light" class="role-tag">
              {{
                authStore.isRoot
                  ? '超级管理员'
                  : authStore.isAdmin
                    ? '管理员'
                    : '成员'
              }}
            </el-tag>
            <span class="username-text">当前用户：{{ authStore.username || '未登录' }}</span>
            <el-button class="logout-btn" @click="handleLogout">退出登录</el-button>
          </div>
        </header>

        <main class="page-main ds-page-main">
          <slot />
        </main>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ChatDotRound, DataAnalysis, Expand, Fold, Folder, House, Setting, SwitchButton, User } from '@element-plus/icons-vue'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useSystemStore } from '../stores/system'
import { getMeApi } from '../api/users'

const $route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const systemStore = useSystemStore()
const sidebarCollapsed = ref(false)
const manualMode = ref<'auto' | 'pinned' | null>(null)
let collapseTimer: number | null = null

const autoCollapseEnabled = ref(false)

const syncMode = () => {
  autoCollapseEnabled.value =
    manualMode.value === null
      ? systemStore.settings.sidebar_auto_collapse
      : manualMode.value === 'auto'

  if (!autoCollapseEnabled.value) {
    sidebarCollapsed.value = false
  }
}

const clearCollapseTimer = () => {
  if (collapseTimer !== null) {
    window.clearTimeout(collapseTimer)
    collapseTimer = null
  }
}

const handleSidebarEnter = () => {
  clearCollapseTimer()
  sidebarCollapsed.value = false
}

const handleSidebarLeave = () => {
  if (!autoCollapseEnabled.value) return
  clearCollapseTimer()
  collapseTimer = window.setTimeout(() => {
    sidebarCollapsed.value = true
  }, 440)
}

let boundaryRaf = 0
const onLayoutMouseMove = (event: MouseEvent) => {
  if (!autoCollapseEnabled.value || !sidebarCollapsed.value) return
  if (event.clientX > 14) return
  if (boundaryRaf) return
  boundaryRaf = window.requestAnimationFrame(() => {
    boundaryRaf = 0
    if (!autoCollapseEnabled.value || !sidebarCollapsed.value) return
    sidebarCollapsed.value = false
  })
}

const toggleSidebarMode = () => {
  manualMode.value = autoCollapseEnabled.value ? 'pinned' : 'auto'
  syncMode()
}

const toggleSidebarCollapse = () => {
  clearCollapseTimer()
  sidebarCollapsed.value = !sidebarCollapsed.value
}

const handleLogout = () => {
  authStore.logout()
  ElMessage.success('已退出登录')
  router.push('/login')
}

watch(
  () => systemStore.settings.sidebar_auto_collapse,
  () => {
    if (manualMode.value === null) {
      syncMode()
    }
  },
)

onMounted(async () => {
  if (authStore.isLoggedIn) {
    try {
      const me = await getMeApi()
      authStore.syncFromMe(me)
    } catch {
      // ignore profile refresh failures
    }
  }
  if (!systemStore.loaded) {
    try {
      await systemStore.fetchSettings()
    } catch {
      // layout should still render even if settings fail
    }
  }
  syncMode()
})

onBeforeUnmount(() => {
  clearCollapseTimer()
  if (boundaryRaf) {
    window.cancelAnimationFrame(boundaryRaf)
    boundaryRaf = 0
  }
})
</script>

<style scoped>
.admin-layout {
  width: 100%;
  height: 100%;
}

.layout-shell {
  min-height: 100vh;
  display: flex;
  background: var(--ds-page-bg, #f0f4f9);
}

.sidebar {
  --sidebar-transition-duration: 0.42s;
  --sidebar-transition-ease: cubic-bezier(0.33, 1, 0.68, 1);
  width: 256px;
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid var(--ds-line-subtle, #e0e3e7);
  display: flex;
  flex-direction: column;
  padding: 20px 14px;
  overflow: hidden;
  transition:
    width var(--sidebar-transition-duration) var(--sidebar-transition-ease),
    box-shadow 0.35s ease;
  box-shadow: none;
  z-index: 10;
}

.sidebar.collapsed {
  width: 84px;
}

.sidebar.floating.collapsed {
  box-shadow: var(--soft-shadow);
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 4px 18px;
  min-height: 56px;
}

.brand-text-clip {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  max-width: 220px;
  opacity: 1;
  transition:
    max-width var(--sidebar-transition-duration) var(--sidebar-transition-ease),
    opacity 0.28s ease;
}

.brand-text-clip.is-collapsed {
  max-width: 0;
  opacity: 0;
  pointer-events: none;
}

.brand-text {
  white-space: nowrap;
  padding-right: 4px;
}

.brand-mark {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: linear-gradient(145deg, #0b57d0, #1967d2);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  letter-spacing: -0.02em;
  box-shadow: 0 2px 8px rgba(11, 87, 208, 0.22);
}

.brand-title {
  font-weight: 700;
  color: var(--text-primary);
}

.brand-subtitle {
  color: var(--text-secondary);
  font-size: 12px;
  margin-top: 4px;
}

.sidebar-menu {
  flex: 1;
  border-right: none;
  background: transparent;
}

:deep(.sidebar-menu .el-menu-item),
:deep(.sidebar-menu .el-sub-menu__title) {
  border-radius: 14px;
  margin-bottom: 8px;
  color: var(--text-primary);
  height: 46px;
}

:deep(.sidebar-menu .el-menu-item.is-active) {
  background: rgba(11, 87, 208, 0.08);
  color: var(--ds-brand, #0b57d0);
  font-weight: 600;
}

:deep(.sidebar-menu .el-menu-item:hover) {
  background: rgba(11, 87, 208, 0.05);
}

/* 与侧栏 width 动画对齐，减轻菜单与外壳「各动各的」的顿挫感 */
.sidebar :deep(.horizontal-collapse-transition) {
  transition:
    width var(--sidebar-transition-duration) var(--sidebar-transition-ease),
    padding-left var(--sidebar-transition-duration) var(--sidebar-transition-ease),
    padding-right var(--sidebar-transition-duration) var(--sidebar-transition-ease) !important;
}

.sidebar-footer {
  display: flex;
  gap: 10px;
  justify-content: center;
  padding-top: 12px;
}

.side-action {
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  background: #f5f8fb;
  color: var(--text-secondary);
}

.side-action:hover {
  border-color: var(--ds-line, #e6eaf0);
  color: var(--ds-brand, #0b57d0);
  background: #fff;
}

.main-shell {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 18px 28px;
  background: #fff;
  border-bottom: 1px solid var(--ds-line-subtle, #e0e3e7);
}

.topbar-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--text-primary);
}

.topbar-subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.role-tag {
  border-radius: 999px;
}

.username-text {
  color: var(--text-secondary);
  font-size: 13px;
}

.logout-btn {
  border-radius: 12px;
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  background: #fff;
  color: var(--text-primary);
}

.logout-btn:hover {
  border-color: var(--ds-brand, #0b57d0);
  color: var(--ds-brand, #0b57d0);
  background: rgba(11, 87, 208, 0.04);
}

.page-main {
  flex: 1;
  min-width: 0;
  background: var(--ds-page-bg, #f0f4f9);
}

</style>