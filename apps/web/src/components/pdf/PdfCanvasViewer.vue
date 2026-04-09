<template>
  <section ref="leftPaneRef" class="pane left pdf-canvas-viewer" @scroll="onScroll">
    <div v-if="pdfState === 'loading'" class="pdf-status">PDF 正在加载…</div>
    <div v-else-if="pdfState === 'failed'" class="pdf-load-error">{{ pdfErrorMessage }}</div>
    <template v-else-if="pdfState === 'loaded'">
      <div
        v-for="p in pageCount"
        :key="`page-${fileId}-${p}`"
        :data-page="p"
        class="pdf-page-wrap"
      >
        <div class="pdf-page-meta">第 {{ p }} / {{ pageCount }} 页</div>
        <canvas :ref="(el) => bindCanvas(el, p)" class="pdf-canvas" />
      </div>
    </template>
    <div v-else class="pdf-status">请选择文献</div>
  </section>
</template>

<script setup lang="ts">
import { ref, toRef } from 'vue'
import { usePdfDocument } from '@/composables/usePdfDocument'

const props = defineProps<{
  fileId: number
}>()

const emit = defineEmits<{
  scroll: [Event]
}>()

const leftPaneRef = ref<HTMLElement | null>(null)
const fileIdRef = toRef(props, 'fileId')

const { pdfState, pdfErrorMessage, pageCount, bindCanvas } = usePdfDocument(fileIdRef)

function onScroll(ev: Event) {
  emit('scroll', ev)
}

function scrollToPage(pageNumber?: number | null) {
  if (!pageNumber || !leftPaneRef.value) return
  const node = leftPaneRef.value.querySelector(`[data-page="${pageNumber}"]`)
  if (node) node.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

defineExpose({
  scrollToPage,
  getLeftScrollElement: () => leftPaneRef.value,
})
</script>

<style scoped>
.pdf-canvas-viewer.pane {
  border: 1px solid #ddd;
  border-radius: 8px;
  overflow: auto;
  padding: 8px;
  background: #fff;
}
.pdf-status {
  padding: 16px;
  color: #666;
}
.pdf-load-error {
  padding: 16px;
  color: #c00;
  font-size: 14px;
  line-height: 1.5;
  white-space: pre-wrap;
}
.pdf-page-wrap {
  margin-bottom: 12px;
  background: #f5f5f5;
  border-radius: 8px;
  padding: 8px;
}
.pdf-page-meta {
  font-size: 12px;
  color: #666;
  margin-bottom: 6px;
}
.pdf-canvas {
  display: block;
  max-width: 100%;
  height: auto;
  background: #fafafa;
  border-radius: 4px;
}
</style>
