import { ref, watch, onBeforeUnmount, type Ref } from 'vue'
import {
  getPdfTranslationContentApi,
  getPdfTranslationStatusApi,
} from '@/api/pdfDocuments'

/** 与 translation-status 对齐的任务态（标签只用这个，不用 content 读取结果覆盖为 failed） */
export type TranslationTaskState = 'idle' | 'pending' | 'running' | 'completed' | 'failed' | 'empty'

/** 译文 JSON 拉取/解析（与任务是否失败无关） */
export type TranslationContentLoadState = 'idle' | 'loading' | 'ok' | 'timed_out' | 'error' | 'skipped'

function normalizeErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message
  if (typeof error === 'string' && error.trim()) return error
  return fallback
}

function isLikelyResponseBodyTimeout(error: unknown): boolean {
  const msg = (() => {
    if (error instanceof Error) return error.message
    if (typeof DOMException !== 'undefined' && error instanceof DOMException) return error.message
    return String(error)
  })()
  const m = msg.toLowerCase()
  if (m.includes('timed out') || m.includes('timeout') || m.includes('超时')) return true
  if (typeof DOMException !== 'undefined' && error instanceof DOMException && error.name === 'TimeoutError') {
    return true
  }
  return false
}

export function parseTranslationItems(payload: unknown): any[] {
  if (!payload || typeof payload !== 'object') return []
  const p = payload as Record<string, unknown>
  if (Array.isArray(p.items)) return p.items
  const c = p.content
  if (c && typeof c === 'object' && !Array.isArray(c) && Array.isArray((c as { items?: unknown }).items)) {
    return (c as { items: any[] }).items
  }
  if (Array.isArray(c)) return c as any[]
  return []
}

function toTaskState(status: string | undefined): TranslationTaskState {
  const s = (status || '').toLowerCase()
  if (s === 'pending') return 'pending'
  if (s === 'running') return 'running'
  if (s === 'completed') return 'completed'
  if (s === 'failed') return 'failed'
  if (s === 'not_started') return 'idle'
  return 'idle'
}

async function fetchTranslationContentWithRetry(
  id: number,
  seq: number,
  requestSeqRef: () => number,
  maxAttempts = 4,
): Promise<any> {
  let lastErr: unknown
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    if (seq !== requestSeqRef()) throw new Error('aborted')
    try {
      return await getPdfTranslationContentApi(id)
    } catch (e) {
      lastErr = e
      const timeoutLike = isLikelyResponseBodyTimeout(e)
      console.warn('[Translation] content fetch attempt failed', {
        fileId: id,
        attempt,
        timeoutLike,
        message: e instanceof Error ? e.message : String(e),
      })
      if (!timeoutLike || attempt >= maxAttempts) {
        throw e
      }
      const delay = 1200 * attempt
      await new Promise((r) => {
        window.setTimeout(r, delay)
      })
    }
  }
  throw lastErr
}

/**
 * 任务态：只跟 translation-status 一致。
 * 读取态：translation-content 的 fetch/读 body/JSON，单独展示，不把「读取超时」伪装成「翻译失败」。
 */
export function usePdfTranslation(fileId: Ref<number>) {
  /** UI 标签主状态：来自 status 接口；empty 仅在任务 completed 且成功拉到 content 且无 items 时设置 */
  const translationState = ref<TranslationTaskState>('idle')
  const translationProgress = ref(0)
  const translationItems = ref<any[]>([])
  /** 仅任务失败原因（来自 status.error_message 或后端任务逻辑），不含纯读取超时 */
  const translationErrorMessage = ref('')
  /** 译文 JSON 拉取/解析问题（超时、网络、非 JSON） */
  const translationContentReadError = ref('')
  const translationContentLoadState = ref<TranslationContentLoadState>('idle')
  const translationDebugMessage = ref('')

  let requestSeq = 0
  let pollTimer: number | null = null

  function clearPoll() {
    if (pollTimer != null) {
      window.clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  function resetForNewFile() {
    clearPoll()
    translationState.value = 'idle'
    translationProgress.value = 0
    translationItems.value = []
    translationErrorMessage.value = ''
    translationContentReadError.value = ''
    translationContentLoadState.value = 'idle'
    translationDebugMessage.value = ''
  }

  function applyTaskFromStatus(statusRes: {
    status?: string
    progress?: number
    error_message?: string | null
  }) {
    const taskStatus = toTaskState(statusRes.status)
    translationProgress.value = Number(statusRes.progress ?? 0)
    const err = typeof statusRes.error_message === 'string' ? statusRes.error_message.trim() : ''

    translationDebugMessage.value = `status=${statusRes.status || 'unknown'}, progress=${translationProgress.value}%`

    if (taskStatus === 'failed') {
      translationState.value = 'failed'
      translationErrorMessage.value = err || '翻译任务失败（后端未返回详细原因）'
    } else if (taskStatus === 'idle') {
      translationState.value = 'idle'
      translationErrorMessage.value = ''
    } else {
      translationState.value = taskStatus
      translationErrorMessage.value = ''
    }
  }

  async function refreshTranslation(id: number) {
    const seq = ++requestSeq
    translationContentReadError.value = ''

    try {
      const statusRes = await getPdfTranslationStatusApi(id)
      if (seq !== requestSeq) return

      console.info('[Translation] translation-status', {
        fileId: id,
        method: 'GET',
        path: `/api/pdf-documents/${id}/translation-status`,
        body: statusRes,
      })

      applyTaskFromStatus(statusRes)

      const taskStatus = translationState.value
      const taskErrSnapshot = translationErrorMessage.value

      const needContent =
        taskStatus === 'completed' ||
        taskStatus === 'pending' ||
        taskStatus === 'running' ||
        taskStatus === 'failed'

      if (!needContent) {
        translationItems.value = []
        translationContentLoadState.value = 'skipped'
        clearPoll()
        return
      }

      translationContentLoadState.value = 'loading'

      try {
        const contentRes = await fetchTranslationContentWithRetry(id, seq, () => requestSeq)
        if (seq !== requestSeq) return

        console.info('[Translation] translation-content', {
          fileId: id,
          method: 'GET',
          path: `/api/pdf-documents/${id}/translation-content`,
          envelopeStatus: contentRes?.status,
          progress: contentRes?.progress,
          itemCountPreview: parseTranslationItems(contentRes).length,
        })

        translationContentLoadState.value = 'ok'

        const items = parseTranslationItems(contentRes)
        translationItems.value = items

        const envelopeStatus = typeof contentRes.status === 'string' ? contentRes.status.toLowerCase() : ''

        if (envelopeStatus === 'failed' && taskStatus !== 'failed') {
          translationState.value = 'failed'
          const envErr =
            typeof contentRes.error_message === 'string' ? contentRes.error_message.trim() : ''
          translationErrorMessage.value = envErr || '翻译任务失败'
        }

        if (taskStatus === 'failed' || translationState.value === 'failed') {
          translationState.value = 'failed'
          if (!translationErrorMessage.value && typeof contentRes.error_message === 'string') {
            const m = contentRes.error_message.trim()
            if (m) translationErrorMessage.value = m
          }
          if (!translationErrorMessage.value) {
            translationErrorMessage.value = taskErrSnapshot || '翻译任务失败'
          }
        } else if (translationState.value === 'completed') {
          if (items.length === 0) {
            translationState.value = 'empty'
          } else {
            translationState.value = 'completed'
          }
        }
      } catch (contentErr) {
        if (seq !== requestSeq) return

        const timeoutLike = isLikelyResponseBodyTimeout(contentErr)
        const readMsg = normalizeErrorMessage(contentErr, '未知错误')

        console.error('[Translation] translation-content fetch/read failed', {
          fileId: id,
          path: `/api/pdf-documents/${id}/translation-content`,
          taskStatus,
          timeoutLike,
          message: readMsg,
        })

        if (timeoutLike) {
          translationContentLoadState.value = 'timed_out'
        } else {
          translationContentLoadState.value = 'error'
        }

        if (taskStatus === 'completed') {
          translationContentReadError.value = timeoutLike
            ? '译文数据读取超时（任务已完成，可点击「全文翻译」旁刷新或稍后重试拉取译文 JSON）'
            : `译文数据加载失败：${readMsg}`
          translationState.value = 'completed'
          translationErrorMessage.value = ''
        } else if (taskStatus === 'pending' || taskStatus === 'running') {
          translationContentReadError.value = timeoutLike
            ? '译文接口响应体读取超时，将继续轮询任务状态…'
            : `译文接口异常：${readMsg}，将重试…`
          clearPoll()
          pollTimer = window.setTimeout(() => {
            void refreshTranslation(id)
          }, timeoutLike ? 5000 : 3500)
          return
        } else if (taskStatus === 'failed') {
          translationState.value = 'failed'
          translationErrorMessage.value =
            taskErrSnapshot || translationErrorMessage.value || '翻译任务失败（后端未返回详细原因）'
          translationContentReadError.value = timeoutLike
            ? `另：译文 JSON 拉取超时（与任务失败无关；任务原因见上）`
            : `另：译文 JSON 拉取失败：${readMsg}`
        }
        clearPoll()
        return
      }

      clearPoll()
      if (translationState.value === 'pending' || translationState.value === 'running') {
        pollTimer = window.setTimeout(() => {
          void refreshTranslation(id)
        }, 2500)
      }
    } catch (error) {
      if (seq !== requestSeq) return
      translationState.value = 'failed'
      translationErrorMessage.value = `无法获取翻译状态：${normalizeErrorMessage(error, '未知错误')}`
      translationContentLoadState.value = 'error'
      console.error('[Translation] translation-status failed', error)
    }
  }

  watch(
    fileId,
    (fid) => {
      resetForNewFile()
      if (Number.isFinite(fid) && fid > 0) {
        void refreshTranslation(fid)
      }
    },
    { immediate: true },
  )

  onBeforeUnmount(() => {
    clearPoll()
  })

  return {
    translationState,
    translationProgress,
    translationItems,
    translationErrorMessage,
    translationContentReadError,
    translationContentLoadState,
    translationDebugMessage,
    refreshTranslation,
    clearPoll,
  }
}
