import { apiFetch } from './client'

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
}

export interface FileMetaItem extends FileItem {
  size: number | null
  indexed_at?: string | null
  index_error?: string | null
  index_warning?: string | null
  content_hash?: string | null
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

export interface FolderItem {
  id: number
  name: string
  parent_id?: number | null
  created_at: string
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

async function readErrorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  const errorData = await response.json().catch(() => ({}))
  return errorData.detail || fallback
}

export async function getFilesApi(params?: GetFilesParams): Promise<FileItem[]> {
  const baseUrl = '/api/files'
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
) {
  const formData = new FormData()
  formData.append('file', file)

  if (folderId !== undefined && folderId !== null) {
    formData.append('folder_id', String(folderId))
  }

  const response = await apiFetch('/api/files/upload', {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '上传失败'))
  }

  return response.json()
}

export async function getFolderTreeApi(): Promise<FolderTreeItem[]> {
  const response = await apiFetch('/api/files/folders')

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '获取文件夹树失败'))
  }

  return response.json()
}

export async function getDashboardApi(): Promise<DashboardResponse> {
  const response = await apiFetch('/api/files/dashboard')

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '获取首页统计失败'))
  }

  return response.json()
}

export async function getFolderChildrenApi(
  parentId?: number | null,
): Promise<FolderChildrenResponse> {
  const baseUrl = '/api/files/folders/children'
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
  const response = await apiFetch('/api/files/folders', {
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
  const response = await apiFetch(`/api/files/folders/${folderId}/rename`, {
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
  const response = await apiFetch(`/api/files/folders/${folderId}/move`, {
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
    `/api/files/folders/${folderId}`,
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
  const response = await apiFetch(`/api/files/${fileId}/move`, {
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

export async function deleteFileApi(fileId: number): Promise<{ message: string }> {
  const response = await apiFetch(`/api/files/${fileId}`, {
    method: 'DELETE',
  })

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '删除文件失败'))
  }

  return response.json()
}

export async function getFileMetaApi(fileId: number): Promise<FileMetaItem> {
  const response = await apiFetch(`/api/files/${fileId}/meta`)

  if (!response.ok) {
    throw new Error(await readErrorMessage(response, '获取文件详情失败'))
  }

  return response.json()
}

export async function downloadFileApi(fileId: number): Promise<void> {
  const response = await apiFetch(`/api/files/${fileId}/download`)

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