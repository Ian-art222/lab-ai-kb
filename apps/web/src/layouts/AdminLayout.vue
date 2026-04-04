<template>
  <div class="admin-layout">
    <div class="layout-shell" @mousemove="handleBoundaryHover">
      <aside
        class="sidebar"
        :class="{ collapsed: sidebarCollapsed, floating: autoCollapseEnabled }"
        @mouseenter="handleSidebarEnter"
        @mouseleave="handleSidebarLeave"
      >
        <div class="brand-block">
          <div class="brand-mark">LK</div>
          <transition name="fade-slide">
            <div v-if="!sidebarCollapsed" class="brand-text">
              <div class="brand-title">{{ systemStore.systemName }}</div>
              <div class="brand-subtitle">{{ systemStore.labName }}</div>
            </div>
          </transition>
        </div>

        <el-menu
          router
          :default-active="$route.path"
          :collapse="sidebarCollapsed"
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
import { ChatDotRound, Expand, Fold, Folder, House, Setting, SwitchButton, User } from '@element-plus/icons-vue'
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
  }, 360)
}

const handleBoundaryHover = (event: MouseEvent) => {
  if (!autoCollapseEnabled.value) return
  if (sidebarCollapsed.value && event.clientX <= 10) {
    sidebarCollapsed.value = false
  }
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
  width: 256px;
  background: linear-gradient(180deg, #fff7f1 0%, #fff3ea 100%);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  padding: 18px 14px;
  transition: width 0.24s ease, transform 0.24s ease, box-shadow 0.24s ease;
  box-shadow: var(--soft-shadow);
  z-index: 10;
}

.sidebar.collapsed {
  width: 84px;
  padding-inline: 10px;
}

.sidebar.floating.collapsed {
  box-shadow: var(--soft-shadow);
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 6px 18px;
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
  background: rgba(255, 153, 102, 0.16);
  color: #c85f26;
}

:deep(.sidebar-menu .el-menu-item:hover) {
  background: rgba(255, 170, 120, 0.12);
}

.sidebar-footer {
  display: flex;
  gap: 10px;
  justify-content: center;
  padding-top: 12px;
}

.side-action {
  border: none;
  background: #fff;
  color: #c96b2d;
  box-shadow: var(--soft-shadow);
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
  background: linear-gradient(135deg, rgba(255, 242, 228, 0.92), rgba(255, 250, 245, 0.98));
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
}

.username-text {
  color: var(--text-secondary);
}

.logout-btn {
  border-radius: 999px;
}

.page-main {
  flex: 1;
  padding: 20px;
  background: var(--app-bg);
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.18s ease;
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateX(-8px);
}
</style>