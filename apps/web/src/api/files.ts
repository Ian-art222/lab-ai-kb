import { apiFetch, getApiBase } from './client'

export interface FileItem {
  id: number
  file_name: string
  file_type: string
  uploader: string
  upload_time: string
  folder_id?: number | null
  folder_name?: string | null
  index_status: string
  index_warning?: string | null
  index_error?: string | null
  indexed_at?: string | null
  mime_type?: string | null
  file_size?: number | null
  can_download?: boolean
  can_rename?: boolean
  can_move?: boolean
  can_copy?: boolean
  can_delete?: boolean
}

export interface FileMetaItem extends FileItem {
  size: number | null
  indexed_at?: string | null
  index_error?: string | null
  index_warning?: string | null
  content_hash?: string | null
}

/** GET /files/{id}/chunk-diagnostics — 索引切块分布（调参/排障） */
export interface ChunkDiagnostics {
  file_id: number
  file_name: string
  index_status: string
  pipeline_version?: string | null
  parent_count: number
  child_count: number
  legacy_count: number
  total_rows: number
  avg_child_token_count?: number | null
  avg_child_char_count?: number | null
  p50_child_char?: number | null
  p90_child_char?: number | null
  short_child_ratio: number
  long_child_ratio: number
  block_type_counts: Record<string, number>
  extractor_version?: string | null
  extractor_rules_version?: string | null
  parent_block_type_counts?: Record<string, number>
  max_heading_depth?: number
  special_block_counts?: Record<string, number>
}

export interface DashboardSummary {
  total_files: number
  indexed_files: number
  pending_files: number
  failed_files: number
}

export interface DashboardResponse {
  summary: DashboardSummary
  recent_files: FileItem[]
  recent_indexed_files: FileItem[]
  recent_failed_files: FileItem[]
  recent_qa_records: Array<{
    id: number
    session_id: number
    session_title?: string | null
    question: string
    scope_type: string
    created_at: string
  }>
  recent_failed_qa_records: Array<{
    id: number
    session_id: number
    session_title?: string | null
    error: string
    created_at: string
  }>
  ops_status: {
    qa_enabled: boolean
    llm_configured: boolean
    embedding_configured: boolean
    last_qa_success?: boolean | null
    last_qa_at?: string | null
    last_qa_error?: string | null
    last_llm_test_success?: boolean | null
    last_llm_test_at?: string | null
    last_llm_test_detail?: string | null
    last_embedding_test_success?: boolean | null
    last_embedding_test_at?: string | null
    last_embedding_test_detail?: string | null
    last_activity_at?: string | null
  }
}

export interface FolderViewUi {
  can_manage_structure: boolean
  can_create_subfolder: boolean
  can_upload: boolean
  can_download_files: boolean
  can_move_or_delete_files: boolean
}

export interface FolderItem {
  id: number
  name: string
  parent_id?: number | null
  scope?: string
  owner_user_id?: number | null
  created_at: string
  can_manage_structure?: boolean | null
  can_open?: boolean
  can_rename_folder?: boolean
  can_delete_folder?: boolean
  can_move_folder?: boolean
}

export interface FolderTreeItem extends FolderItem {
  children: FolderTreeItem[]
}

export interface BreadcrumbItem {
  id: number
  name: string
}

export interface FolderChildrenResponse {
  current_folder: FolderItem | null
  breadcrumbs: BreadcrumbItem[]
  folders: FolderItem[]
  files: FileItem[]
  ui: FolderViewUi
  space_label?: string
  space_kind?: string
}

export interface GetFilesParams {
  q?: string
  folder_id?: number
  file_type?: string
  uploader?: string
}

export type RenameFolderResult = FolderItem
export type MoveFolderResult = FolderItem
export type MoveFileResult = FileItem
export type TransferStatus = 'pending' | 'uploading' | 'success' | 'failed'

export interface UploadFileOptions {
  onProgress?: (percent: number) => void
}

export interface DownloadFileOptions {
  onProgress?: (percent: number) => void
}

function formatErrorDetail(detail: unknown): string {
  if (detail == null) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === 'object' && 'msg' in item) {
        return String((item as { msg: unknown }).msg)
      }
      return JSON.stringify(item)
    })
    return parts.join('; ')
  }
  if (typeof detail === 'object') return JSON.stringify(detail)
  return String(detail)
}

async function readErrorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  const statusBit = `HTTP ${response.status}${
    response.statusText ? ` ${response.statusText}` : ''
  }`
  const text = await response.text().catch(() => '')
  const trimmed = text.trim()
  if (trimmed) {
    try {
      const errorData = JSON.parse(trimmed) as { detail?: unknown }
      const fromDetail = formatErrorDetail(errorData.detail)
      if (fromDetail) return fromDetail
    } catch {
      /* nginx/HTML 或纯文本错误页 */
    }
    const snippet = trimmed.length > 400 ? `${trimmed.slice(0, 400)}…` : trimmed
    return `${fallback}（${statusBit}）：${snippet}`
  }
  return `${fallback}（${statusBit}）`
}

export async function getFilesApi(params?: GetFilesParams): Promise<FileItem[]> {
  const baseUrl = '/files'
  const searchParams = new URLSearchParams()

  if (params?.q) searchParams.append('q', params.q)
  if (params?.folder_id !== undefined) {
    // 允许 folder_id=0 这类特殊值；实际场景一般为正整数
    searchParams.append('folder_id', String(params.folder_id))
  }
  if (params?.file_type) searchParams.append('file_type', params.file_type)
  if (params?.uploader) searchParams.append('uploader', params.uploader)

  const url = searchParams.toString()
    ? `${baseUrl}?${searchParams.toString()}`
    : baseUrl

  const response = await apiFetch(url)

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '获取文件列表失败'))
  }

  return response.json()
}

export async function uploadFileApi(
  file: File,
  folderId?: number | null,
  options?: UploadFileOptions,
) {
  const formData = new FormData()
  formData.append('file', file)

  if (folderId !== undefined && folderId !== null) {
    formData.append('folder_id', String(folderId))
  }

  const response = await uploadWithProgress('/files/upload', formData, options)

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '上传失败'))
  }

  return response.json()
}

export async function getFolderTreeApi(): Promise<FolderTreeItem[]> {
  const response = await apiFetch('/files/folders')

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '获取文件夹树失败'))
  }

  return response.json()
}

export async function getDashboardApi(): Promise<DashboardResponse> {
  const response = await apiFetch('/files/dashboard')

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '获取首页统计失败'))
  }

  return response.json()
}

export async function getFolderChildrenApi(
  parentId?: number | null,
): Promise<FolderChildrenResponse> {
  const baseUrl = '/files/folders/children'
  const searchParams = new URLSearchParams()

  if (parentId !== undefined && parentId !== null) {
    searchParams.append('parent_id', String(parentId))
  }

  const url = searchParams.toString()
    ? `${baseUrl}?${searchParams.toString()}`
    : baseUrl

  const response = await apiFetch(url)

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '获取目录内容失败'))
  }

  return response.json()
}

export async function createFolderApi(
  name: string,
  parentId?: number | null,
): Promise<FolderItem> {
  const response = await apiFetch('/files/folders', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ name, parent_id: parentId ?? null }),
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '创建文件夹失败'))
  }

  return response.json()
}

export async function renameFolderApi(
  folderId: number,
  name: string,
): Promise<RenameFolderResult> {
  const response = await apiFetch(`/files/folders/${folderId}/rename`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ name }),
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '重命名失败'))
  }

  return response.json()
}

export async function moveFolderApi(
  folderId: number,
  parentId?: number | null,
): Promise<MoveFolderResult> {
  const response = await apiFetch(`/files/folders/${folderId}/move`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ parent_id: parentId ?? null }),
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '移动失败'))
  }

  return response.json()
}

export async function deleteFolderApi(folderId: number): Promise<{ message: string }> {
  const response = await apiFetch(
    `/files/folders/${folderId}`,
    { method: 'DELETE' },
  )

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '删除失败'))
  }

  return response.json()
}

export async function moveFileApi(
  fileId: number,
  folderId?: number | null,
): Promise<MoveFileResult> {
  const response = await apiFetch(`/files/${fileId}/move`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ folder_id: folderId ?? null }),
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '移动文件失败'))
  }

  return response.json()
}

export async function renameFileApi(
  fileId: number,
  fileName: string,
): Promise<FileItem> {
  const response = await apiFetch(`/files/${fileId}/rename`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ file_name: fileName }),
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '重命名文件失败'))
  }

  return response.json()
}

export async function copyFileApi(
  fileId: number,
  folderId?: number | null,
): Promise<MoveFileResult> {
  const response = await apiFetch(`/files/${fileId}/copy`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ folder_id: folderId ?? null }),
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '复制文件失败'))
  }

  return response.json()
}

export async function deleteFileApi(fileId: number): Promise<{ message: string }> {
  const response = await apiFetch(`/files/${fileId}`, {
    method: 'DELETE',
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '删除文件失败'))
  }

  return response.json()
}

export async function getFileMetaApi(fileId: number): Promise<FileMetaItem> {
  const response = await apiFetch(`/files/${fileId}/meta`)

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '获取文件详情失败'))
  }

  return response.json()
}

export async function getChunkDiagnosticsApi(fileId: number): Promise<ChunkDiagnostics> {
  const response = await apiFetch(`/files/${fileId}/chunk-diagnostics`)
  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '获取 chunk 诊断失败'))
  }
  return response.json()
}

export async function downloadFileApi(fileId: number): Promise<void> {
  const response = await downloadWithProgress(`/files/${fileId}/download`)

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '下载文件失败'))
  }

  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') || ''
  const matchedFileName = disposition.match(/filename="?([^"]+)"?/)
  const fileName = matchedFileName?.[1] || `file-${fileId}`
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

export async function batchDownloadFilesApi(
  fileIds: number[],
  options?: DownloadFileOptions,
): Promise<void> {
  const response = await downloadWithProgress('/files/batch-download', {
    method: 'POST',
    body: JSON.stringify({ file_ids: fileIds }),
    headers: {
      'Content-Type': 'application/json',
    },
  }, options)

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '批量下载失败'))
  }

  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') || ''
  const matchedFileName = disposition.match(/filename="?([^"]+)"?/)
  const fileName = matchedFileName?.[1] || 'files-batch.zip'
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(url)
}

async function uploadWithProgress(
  url: string,
  formData: FormData,
  options?: UploadFileOptions,
): Promise<Response> {
  const token = localStorage.getItem('token')
  const headers: Record<string, string> = {}
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  return xhrRequest(`${getApiBase()}${url}`, {
    method: 'POST',
    body: formData,
    headers,
    onUploadProgress: options?.onProgress,
  })
}

async function downloadWithProgress(
  url: string,
  init: RequestInit = {},
  options?: DownloadFileOptions,
): Promise<Response> {
  const token = localStorage.getItem('token')
  const headers = new Headers(init.headers ?? {})
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }
  return xhrRequest(`${getApiBase()}${url}`, {
    method: init.method ?? 'GET',
    body: (init.body as XMLHttpRequestBodyInit | null) ?? null,
    headers: Object.fromEntries(headers.entries()),
    responseType: 'blob',
    onDownloadProgress: options?.onProgress,
  })
}

function xhrRequest(
  url: string,
  config: {
    method: string
    body?: XMLHttpRequestBodyInit | null
    headers?: Record<string, string>
    responseType?: XMLHttpRequestResponseType
    onUploadProgress?: (percent: number) => void
    onDownloadProgress?: (percent: number) => void
  },
): Promise<Response> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(config.method, url, true)
    if (config.responseType) {
      xhr.responseType = config.responseType
    }
    Object.entries(config.headers || {}).forEach(([key, value]) => {
      xhr.setRequestHeader(key, value)
    })
    xhr.upload.onprogress = (event) => {
      if (!config.onUploadProgress || !event.lengthComputable || event.total <= 0) return
      config.onUploadProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onprogress = (event) => {
      if (!config.onDownloadProgress || !event.lengthComputable || event.total <= 0) return
      config.onDownloadProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onerror = () => reject(new Error('网络请求失败'))
    xhr.onload = () => {
      if (xhr.status === 401) {
        localStorage.removeItem('token')
        localStorage.removeItem('username')
        localStorage.removeItem('role')
        if (window.location.pathname !== '/login') {
          window.alert('登录状态已失效，请重新登录')
          window.location.href = '/login'
        }
      }
      const headers = new Headers()
      xhr.getAllResponseHeaders()
        .trim()
        .split(/[\r\n]+/)
        .forEach((line) => {
          if (!line) return
          const parts = line.split(': ')
          const header = parts.shift()
          if (header) headers.append(header, parts.join(': '))
        })
      const response = new Response(xhr.response, {
        status: xhr.status,
        statusText: xhr.statusText,
        headers,
      })
      resolve(response)
    }
    xhr.send(config.body ?? null)
  })
}
