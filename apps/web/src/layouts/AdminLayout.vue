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
          <el-menu-item v-if="authStore.isAdmin" index="/users">
            <el-icon><User /></el-icon>
            <template #title>用户管理</template>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/admin/diagnostics">
            <el-icon><DataAnalysis /></el-icon>
            <template #title>诊断中心</template>
          </el-menu-item>
          <el-menu-item v-if="authStore.isAdmin" index="/settings">
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
            <div class="topbar-subtitle">温暖、亲和、可持续演进的实验室知识库</div>
          </div>

          <div class="topbar-actions">
            <el-tag effect="light" class="role-tag">
              {{ authStore.isAdmin ? '管理员' : '成员' }}
            </el-tag>
            <span class="username-text">当前用户：{{ authStore.username || '未登录' }}</span>
            <el-button class="logout-btn" @click="handleLogout">退出登录</el-button>
          </div>
        </header>

        <main class="page-main">
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
  background: var(--app-bg);
}

.sidebar {
  --sidebar-transition-duration: 0.42s;
  --sidebar-transition-ease: cubic-bezier(0.33, 1, 0.68, 1);
  width: 256px;
  flex-shrink: 0;
  background: linear-gradient(180deg, #fff6ee 0%, #ffefe4 100%);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  padding: 18px 12px;
  overflow: hidden;
  transition:
    width var(--sidebar-transition-duration) var(--sidebar-transition-ease),
    box-shadow 0.35s ease;
  box-shadow: var(--soft-shadow);
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
  border-radius: 14px;
  background: var(--warm-gradient);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  box-shadow: var(--soft-shadow);
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
  background: rgba(240, 170, 120, 0.22);
  color: #a14f22;
}

:deep(.sidebar-menu .el-menu-item:hover) {
  background: rgba(255, 188, 140, 0.14);
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
  border: 1px solid rgba(230, 195, 170, 0.55);
  background: rgba(255, 252, 248, 0.95);
  color: #b55f28;
  box-shadow: 0 2px 10px rgba(200, 140, 95, 0.08);
}

.side-action:hover {
  border-color: rgba(215, 170, 130, 0.65);
  color: #9c4f1c;
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
  padding: 18px 24px;
  background: linear-gradient(135deg, rgba(255, 244, 232, 0.96), rgba(255, 250, 244, 0.99));
  border-bottom: 1px solid var(--border-color);
  backdrop-filter: blur(10px);
}

.topbar-title {
  font-size: 20px;
  font-weight: 700;
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
  border-color: rgba(220, 185, 155, 0.45) !important;
}

.username-text {
  color: var(--text-secondary);
  font-size: 13px;
}

.logout-btn {
  border-radius: 999px;
  border: 1px solid rgba(215, 175, 145, 0.5);
  background: rgba(255, 252, 248, 0.95);
  color: var(--text-primary);
}

.logout-btn:hover {
  border-color: rgba(200, 155, 115, 0.6);
  background: #fff;
  color: var(--warm-accent, #d97a3e);
}

.page-main {
  flex: 1;
  padding: 20px;
  background: var(--app-bg);
}

</style>