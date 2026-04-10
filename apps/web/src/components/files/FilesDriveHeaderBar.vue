<template>
  <header class="drive-header-bar">
    <div class="drive-header-main">
      <div class="drive-header-title-row">
        <h2 class="drive-dir-title">{{ currentTitle }}</h2>
        <div class="drive-header-meta">
          <el-tag v-if="spaceLabel" type="info" effect="plain" class="drive-space-tag">
            {{ spaceLabel }}
          </el-tag>
          <span v-if="spaceKind === 'admin_private_own'" class="drive-private-hint">
            仅您与 root 可访问
          </span>
        </div>
      </div>
    </div>
    <div class="drive-toolbar-wrap">
      <slot name="toolbar" />
    </div>
  </header>
</template>

<script setup lang="ts">
defineProps<{
  currentTitle: string
  spaceLabel: string
  spaceKind: string
}>()
</script>

<style scoped>
.drive-header-bar {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-bottom: 4px;
}

.drive-header-main {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.drive-header-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 16px;
}

.drive-dir-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--ds-text, #1f1f1f);
  letter-spacing: -0.02em;
}

.drive-header-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.drive-space-tag {
  border-radius: 999px;
}

.drive-private-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.drive-toolbar-wrap {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.drive-toolbar-wrap :deep(.el-button) {
  border-radius: var(--ds-radius-md, 12px);
}

.drive-toolbar-wrap :deep(.el-input__wrapper) {
  border-radius: var(--ds-radius-md, 12px);
}
</style>
