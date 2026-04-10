<template>
  <section ref="scrollRootRef" class="pdf-canvas-viewer">
    <div v-if="pdfState === 'loading'" class="pdf-status">PDF 正在加载…</div>
    <div v-else-if="pdfState === 'failed'" class="pdf-load-error">{{ pdfErrorMessage }}</div>
    <template v-else-if="pdfState === 'loaded'">
      <div class="pdf-zoom-bar">
        <span class="pdf-zoom-label">缩放</span>
        <el-slider
          v-model="zoomSlider"
          :min="0.75"
          :max="2.25"
          :step="0.05"
          :show-tooltip="true"
          style="width: 160px"
        />
        <span class="pdf-zoom-val">{{ zoomSlider.toFixed(2) }}×</span>
      </div>
      <div
        v-for="p in pageCount"
        :key="`page-${fileId}-${p}`"
        :data-page="p"
        class="pdf-page-wrap"
      >
        <div class="pdf-page-meta">第 {{ p }} / {{ pageCount }} 页</div>
        <div class="pdf-canvas-stack">
          <canvas :ref="(el) => bindCanvas(el, p)" class="pdf-canvas" />
        </div>
      </div>
    </template>
    <div v-else class="pdf-status">请选择文献</div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, toRef } from 'vue'
import { usePdfDocument } from '@/composables/usePdfDocument'

const props = defineProps<{
  fileId: number
}>()

const scrollRootRef = ref<HTMLElement | null>(null)
const fileIdRef = toRef(props, 'fileId')

const {
  pdfState,
  pdfErrorMessage,
  pageCount,
  bindCanvas,
  cssScale,
  setCssScale,
} = usePdfDocument(fileIdRef)

const zoomSlider = computed({
  get: () => cssScale.value,
  set: (v: number) => setCssScale(Number(v)),
})

function scrollToPage(pageNumber?: number | null) {
  if (!pageNumber || !scrollRootRef.value) return
  const node = scrollRootRef.value.querySelector(`[data-page="${pageNumber}"]`)
  if (node) node.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

defineExpose({
  scrollToPage,
  getLeftScrollElement: () => scrollRootRef.value,
  setCssScale,
  cssScale,
})
</script>

<style scoped>
.pdf-canvas-viewer {
  height: 100%;
  min-height: 240px;
  padding: 10px;
  box-sizing: border-box;
}
.pdf-page-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 1rem;
}
.pdf-page-meta {
  font-size: 12px;
  color: #666;
  margin-bottom: 6px;
}
.pdf-canvas-stack {
  position: relative;
  display: inline-block;
}
.pdf-canvas {
  display: block;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.12);
}
.pdf-status,
.pdf-load-error {
  padding: 12px;
  font-size: 14px;
  color: #606266;
}
.pdf-load-error {
  color: #c00;
}
.pdf-zoom-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 12px;
  flex-shrink: 0;
  width: 100%;
}
.pdf-zoom-label {
  font-size: 12px;
  color: #606266;
}
.pdf-zoom-val {
  font-size: 12px;
  color: #303133;
  min-width: 3rem;
}
</style>
