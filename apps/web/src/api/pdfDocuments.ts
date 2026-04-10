import { apiFetch, apiFetchRaw, readJsonOk } from './client'

async function parseJson<T>(res: Response, fallback: string): Promise<T> {
  return readJsonOk<T>(res, fallback)
}

export function getPdfDocumentApi(fileId: number) {
  return apiFetch(`/pdf-documents/${fileId}`).then((r) => parseJson<any>(r, '获取文献详情失败'))
}

export function getPdfContentApi(fileId: number, init: RequestInit = {}) {
  return apiFetchRaw(`/pdf-documents/${fileId}/content`, init)
}

/** 仅下载用户上传的原始 PDF（无译文/打包） */
export async function downloadPdfOriginalApi(fileId: number) {
  const res = await apiFetch(`/pdf-documents/${fileId}/download?include_original=true`)
  if (!res.ok) throw new Error('下载失败')
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `pdf-${fileId}.pdf`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export async function exportBibApi(fileId: number) {
  const res = await apiFetch(`/pdf-documents/${fileId}/export/bib`)
  if (!res.ok) throw new Error('导出 bib 失败')
  return res.text()
}

export async function exportRisApi(fileId: number) {
  const res = await apiFetch(`/pdf-documents/${fileId}/export/ris`)
  if (!res.ok) throw new Error('导出 ris 失败')
  return res.text()
}

export function getMyAnnotationsApi(fileId: number) {
  return apiFetch(`/pdf-documents/${fileId}/annotations/me`).then((r) => parseJson<any[]>(r, '获取批注失败'))
}

export function createAnnotationApi(fileId: number, payload: { annotation_json: Record<string, unknown>; is_public?: boolean }) {
  return apiFetch(`/pdf-documents/${fileId}/annotations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => parseJson<any>(r, '创建批注失败'))
}

export function updateAnnotationApi(
  fileId: number,
  annotationId: number,
  payload: { annotation_json: Record<string, unknown>; is_public?: boolean },
) {
  return apiFetch(`/pdf-documents/${fileId}/annotations/${annotationId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then((r) => parseJson<any>(r, '更新批注失败'))
}

export function deleteAnnotationApi(fileId: number, annotationId: number) {
  return apiFetch(`/pdf-documents/${fileId}/annotations/${annotationId}`, { method: 'DELETE' }).then((r) =>
    parseJson<any>(r, '删除批注失败'),
  )
}

export function listPublicAnnotationUsersApi(fileId: number) {
  return apiFetch(`/pdf-documents/${fileId}/annotations/public-users`).then((r) =>
    parseJson<{ user_ids: number[] }>(r, '获取公开用户失败'),
  )
}

export function getAnnotationsByUserApi(fileId: number, userId: number) {
  return apiFetch(`/pdf-documents/${fileId}/annotations/by-user/${userId}`).then((r) =>
    parseJson<any[]>(r, '获取同事批注失败'),
  )
}

/** 本文献下所有「实验室可见」笔记（含作者），用于聚合查看他人笔记 */
export function listLabPublicAnnotationsApi(fileId: number) {
  return apiFetch(`/pdf-documents/${fileId}/annotations/lab-public`).then((r) => parseJson<any[]>(r, '获取实验室笔记失败'))
}

export function askPdfQaApi(fileId: number, question: string) {
  return apiFetch(`/pdf-documents/${fileId}/qa`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, strict_mode: true, top_k: 6 }),
  }).then((r) => parseJson<any>(r, '文献问答失败'))
}

export function listAttachmentsApi(fileId: number) {
  return apiFetch(`/pdf-documents/${fileId}/attachments`).then((r) => parseJson<any[]>(r, '获取附件失败'))
}

export function addAttachmentApi(fileId: number, file_id: number, title?: string) {
  return apiFetch(`/pdf-documents/${fileId}/attachments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ file_id, title }),
  }).then((r) => parseJson<any>(r, '添加附件失败'))
}

export function deleteAttachmentApi(fileId: number, attachmentId: number) {
  return apiFetch(`/pdf-documents/${fileId}/attachments/${attachmentId}`, { method: 'DELETE' }).then((r) =>
    parseJson<any>(r, '删除附件失败'),
  )
}
