<template>
  <div class="folder-navigator">
    <div class="folder-navigator-head">
      <span class="folder-navigator-label">{{ sectionTitle }}</span>
    </div>
    <div v-loading="loading" class="folder-navigator-body">
      <div v-if="!loading && displayFolders.length === 0" class="folder-navigator-empty">
        暂无子文件夹
      </div>
      <div
        v-else
        class="folder-navigator-grid"
        :class="{ 'is-home': variant === 'home' }"
      >
        <button
          v-for="f in displayFolders"
          :key="f.id"
          type="button"
          class="folder-card"
          :class="{ 'is-disabled': f.can_open === false }"
          :disabled="f.can_open === false"
          @click="onCardClick(f)"
        >
          <div class="folder-card-icon" aria-hidden="true" />
          <div class="folder-card-main">
            <div class="folder-card-name">{{ displayFolderName(f) }}</div>
            <div class="folder-card-sub">{{ cardSubtitle(f) }}</div>
          </div>
          <div class="folder-card-badges">
            <span v-if="badgeFor(f)" class="folder-card-badge">{{ badgeFor(f) }}</span>
          </div>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { FolderItem } from '../../api/files'
import { useAuthStore } from '../../stores/auth'
import { formatAdminPrivateFolderDisplayName } from '../../utils/folderDisplay'

const authStore = useAuthStore()

const props = withDefaults(
  defineProps<{
    folders: FolderItem[]
    loading?: boolean
    /** home：顶层空间入口；nested：当前目录下的子文件夹 */
    variant?: 'home' | 'nested'
    spaceKind?: string
  }>(),
  {
    loading: false,
    variant: 'nested',
    spaceKind: '',
  },
)

const emit = defineEmits<{
  enter: [folderId: number]
}>()

const displayFolders = computed(() =>
  props.folders.filter((f) => f.can_open !== false),
)

const sectionTitle = computed(() =>
  props.variant === 'home' ? '空间与目录入口' : '当前目录下的文件夹',
)

function displayFolderName(f: FolderItem): string {
  return formatAdminPrivateFolderDisplayName(f.name, {
    isAdmin: authStore.isAdmin,
    isRoot: authStore.isRoot,
    userId: authStore.userId,
  })
}

function isPersonalSpaceRoot(f: FolderItem): boolean {
  return (f.name || '').trim() === '个人文件夹'
}

function badgeFor(f: FolderItem): string {
  const sc = (f.scope || '').toLowerCase()
  if (sc === 'admin_private') return '个人'
  if (sc === 'private_root' || (props.variant === 'home' && isPersonalSpaceRoot(f)))
    return '私人'
  if (sc === 'public') return '公共'
  return ''
}

function cardSubtitle(f: FolderItem): string {
  const sc = (f.scope || '').toLowerCase()
  if (props.variant === 'home') {
    if (sc === 'admin_private') return '个人目录 · 仅本人与 root 可访问'
    if (sc === 'private_root' || isPersonalSpaceRoot(f)) return '仅个人可用，与公共区隔离'
    if (sc === 'public') return '全员可见与协作'
    return '点击进入'
  }
  if (props.spaceKind === 'admin_private_own') {
    return f.can_rename_folder ? '可管理' : '只读'
  }
  if (props.spaceKind === 'public') {
    return f.can_rename_folder ? '可管理目录' : '仅文件操作'
  }
  if (props.spaceKind === 'admin_private') {
    return '管理员私人空间'
  }
  if (f.can_rename_folder) return '可管理'
  if (f.can_open === false) return '不可访问'
  return '点击进入'
}

function onCardClick(f: FolderItem) {
  if (f.can_open === false) return
  emit('enter', f.id)
}
</script>

<style scoped>
.folder-navigator {
  border-radius: var(--ds-radius-lg, 16px);
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  background: var(--ds-surface-muted, #f0f4f9);
  overflow: hidden;
  margin-bottom: 16px;
  box-shadow: none;
}

.folder-navigator-head {
  padding: 12px 18px;
  border-bottom: 1px solid var(--ds-line-subtle, #e0e3e7);
  background: rgba(255, 255, 255, 0.65);
}

.folder-navigator-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ds-text-tertiary, #747775);
}

.folder-navigator-body {
  min-height: 72px;
  padding: 16px 18px 18px;
}

.folder-navigator-empty {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  text-align: center;
  padding: 24px 8px;
}

.folder-navigator-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(152px, 1fr));
  gap: 12px;
}

.folder-navigator-grid.is-home {
  grid-template-columns: repeat(auto-fill, minmax(192px, 1fr));
  gap: 14px;
}

.folder-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  text-align: left;
  padding: 14px 14px 12px;
  border-radius: var(--ds-radius-md, 12px);
  border: 1px solid transparent;
  background: #fff;
  cursor: pointer;
  transition:
    box-shadow 0.18s ease,
    background 0.18s ease,
    transform 0.12s ease;
  min-height: 96px;
  position: relative;
}

.folder-navigator-grid.is-home .folder-card {
  min-height: 104px;
}

.folder-card:hover:not(:disabled) {
  box-shadow: var(--ds-shadow-float, 0 4px 12px rgba(0, 0, 0, 0.05));
  transform: translateY(-1px);
}

.folder-card:disabled,
.folder-card.is-disabled {
  opacity: 0.48;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

.folder-card-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(145deg, #e8eef7, #d3e3fc);
  margin-bottom: 10px;
  box-shadow: inset 0 0 0 1px rgba(11, 87, 208, 0.08);
}

.folder-card-main {
  width: 100%;
  min-width: 0;
}

.folder-card-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--ds-text, #1f1f1f);
  letter-spacing: -0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-card-sub {
  margin-top: 6px;
  font-size: 11px;
  line-height: 1.4;
  color: var(--ds-text-secondary, #444746);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.folder-card-badges {
  position: absolute;
  top: 10px;
  right: 10px;
}

.folder-card-badge {
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 999px;
  background: #e8eef7;
  color: var(--ds-text-secondary, #444746);
  font-weight: 600;
}
</style>
