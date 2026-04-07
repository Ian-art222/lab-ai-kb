<template>
  <AdminLayout>
    <div style="display: flex; gap: 16px; align-items: flex-start">
      <el-card style="width: 320px">
        <template #header>
          <span>目录树</span>
        </template>

        <el-tree
          :data="folderTree"
          node-key="id"
          :props="{ children: 'children', label: 'name' }"
          highlight-current
          default-expand-all
          :current-node-key="currentFolderId ?? -1"
          @node-click="handleNodeClick"
        />
      </el-card>

      <el-card style="flex: 1">
        <template #header>
          <div style="display: flex; flex-direction: column; gap: 10px">
            <el-breadcrumb separator="/">
              <el-breadcrumb-item>
                <el-link type="primary" :underline="false" @click="goRoot">
                  home
                </el-link>
              </el-breadcrumb-item>
              <el-breadcrumb-item v-for="crumb in breadcrumbs" :key="crumb.id">
                <el-link
                  type="primary"
                  :underline="false"
                  @click="goToFolder(crumb.id)"
                >
                  {{ crumb.name }}
                </el-link>
              </el-breadcrumb-item>
            </el-breadcrumb>

            <div style="display: flex; flex-wrap: wrap; gap: 12px; align-items: center">
              <el-button type="primary" @click="refreshCurrent">刷新</el-button>
              <el-button type="warning" @click="goToChatForCurrentFolder">
                在当前目录问答
              </el-button>

              <el-input
                v-model="searchQ"
                placeholder="搜索（当前目录）"
                style="width: 260px"
                clearable
              />

              <el-input
                v-model="newFolderName"
                placeholder="新建文件夹名称"
                style="width: 220px"
                clearable
              />
              <el-button type="success" @click="handleCreateFolder">
                新建文件夹
              </el-button>

              <input
                ref="fileInputRef"
                type="file"
                multiple
                style="display: none"
                @change="handleFileChange"
              />
              <el-button
                type="success"
                :loading="uploading"
                @click="chooseFile"
              >
                批量上传
              </el-button>
            </div>
          </div>
        </template>

        <div style="margin-top: 8px">
          <el-divider>子目录</el-divider>
          <el-table :data="filteredFolders" style="width: 100%" v-loading="loading">
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="created_at" label="创建时间" width="180" />
            <el-table-column label="操作" width="220">
              <template #default="scope">
                <div style="display: flex; flex-wrap: wrap; gap: 8px">
                  <el-button
                    type="success"
                    link
                    :loading="indexingFileId === scope.row.id"
                    :disabled="scope.row.index_status === 'indexing'"
                    @click="handleIngestFile(scope.row.id)"
                  >
                    {{ scope.row.index_status === 'indexed' ? '重新索引' : '建立索引' }}
                  </el-button>
                  <el-button
                    type="primary"
                    link
                    @click="enterFolder(scope.row.id)"
                  >
                    进入
                  </el-button>
                  <el-button
                    type="warning"
                    link
                    v-if="scope.row.parent_id !== null"
                    @click="openRenameFolder(scope.row.id)"
                  >
                    重命名
                  </el-button>
                  <el-button
                    type="info"
                    link
                    v-if="scope.row.parent_id !== null"
                    @click="openMoveFolder(scope.row.id)"
                  >
                    移动
                  </el-button>
                  <el-button
                    type="danger"
                    link
                    v-if="scope.row.parent_id !== null"
                    @click="handleDeleteFolder(scope.row.id)"
                  >
                    删除
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <el-divider>文件</el-divider>
          <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 10px">
            <el-tag type="info">已选中 {{ selectedFiles.length }} 项</el-tag>
            <el-button
              type="primary"
              :disabled="selectedFiles.length === 0 || batchDownloading"
              :loading="batchDownloading"
              @click="handleBatchDownload"
            >
              批量下载
            </el-button>
            <el-button
              :disabled="selectedFiles.length === 0"
              @click="clearSelection"
            >
              取消选择
            </el-button>
          </div>
          <el-table
            ref="fileTableRef"
            :data="filteredFiles"
            style="width: 100%"
            v-loading="loading"
            @selection-change="handleSelectionChange"
          >
            <el-table-column type="selection" width="55" />
            <el-table-column prop="file_name" label="文件名" />
            <el-table-column prop="file_type" label="类型" width="120" />
            <el-table-column label="索引状态" width="120">
              <template #default="scope">
                <el-tag :type="getIndexStatusTagType(scope.row.index_status, scope.row.index_warning)">
                  {{ getIndexStatusLabel(scope.row.index_status, scope.row.index_warning) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="indexed_at" label="最近索引时间" width="180" />
            <el-table-column label="状态说明" min-width="220">
              <template #default="scope">
                {{ getIndexStatusDetail(scope.row) }}
              </template>
            </el-table-column>
            <el-table-column prop="uploader" label="上传者" width="120" />
            <el-table-column prop="upload_time" label="上传时间" />
            <el-table-column label="操作" width="240">
              <template #default="scope">
                <div style="display: flex; flex-wrap: wrap; gap: 8px">
                  <el-button
                    type="primary"
                    link
                    @click="handleDownload(scope.row.id)"
                  >
                    下载
                  </el-button>
                  <el-button
                    type="info"
                    link
                    @click="openMoveFile(scope.row.id, scope.row.folder_id)"
                  >
                    移动
                  </el-button>
                  <el-button
                    type="danger"
                    link
                    @click="handleDeleteFile(scope.row.id)"
                  >
                    删除
                  </el-button>
                  <el-button
                    type="warning"
                    link
                    @click="openFileMeta(scope.row.id)"
                  >
                    详情
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
          <el-empty
            v-if="!loading && filteredFiles.length === 0 && filteredFolders.length === 0"
            description="当前目录暂无内容"
            style="padding: 24px 0 8px"
          />
          <div
            v-if="uploadQueue.length > 0"
            style="margin-top: 16px"
          >
            <el-divider>上传进度</el-divider>
            <div style="margin-bottom: 10px">
              <div style="font-size: 13px; color: #666; margin-bottom: 6px">
                总进度 {{ overallUploadProgress }}%
              </div>
              <el-progress :percentage="overallUploadProgress" />
            </div>
            <div
              v-for="item in uploadQueue"
              :key="item.id"
              style="margin-bottom: 10px"
            >
              <div style="display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px">
                <span>{{ item.name }}</span>
                <span>{{ uploadStatusLabel[item.status] }} {{ item.progress }}%</span>
              </div>
              <el-progress
                :percentage="item.progress"
                :status="item.status === 'failed' ? 'exception' : item.status === 'success' ? 'success' : undefined"
              />
              <div v-if="item.error" style="font-size: 12px; color: #d03050; margin-top: 2px">
                {{ item.error }}
              </div>
            </div>
          </div>
          <div
            v-if="batchDownloading"
            style="margin-top: 16px"
          >
            <el-divider>批量下载进度</el-divider>
            <div style="font-size: 13px; color: #666; margin-bottom: 6px">
              下载中 {{ batchDownloadProgress }}%
            </div>
            <el-progress :percentage="batchDownloadProgress" />
          </div>
        </div>
      </el-card>
    </div>

    <el-dialog
      v-model="renameFolderDialogVisible"
      title="重命名目录"
      width="420px"
    >
      <el-input
        v-model="renameFolderName"
        placeholder="请输入新目录名称"
        clearable
      />
      <template #footer>
        <el-button @click="renameFolderDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRenameFolder">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="moveDialogVisible"
      :title="moveDialogTitle"
      width="420px"
    >
      <div style="margin-bottom: 12px; color: #666">
        请选择目标目录（home 可作为目标）
      </div>

      <div style="margin-bottom: 8px; display: flex; gap: 8px">
        <el-button
          :type="moveTargetParentId === null ? 'primary' : 'default'"
          @click="selectMoveRoot"
        >
          home
        </el-button>
      </div>

      <div style="max-height: 320px; overflow: auto">
        <el-tree
          :data="folderTree"
          node-key="id"
          :props="{ children: 'children', label: 'name' }"
          highlight-current
          default-expand-all
          :current-node-key="moveTargetParentId ?? -1"
          @node-click="handleMoveTreeNodeClick"
        />
      </div>

      <template #footer>
        <el-button @click="moveDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitMoveTarget">确认</el-button>
      </template>
    </el-dialog>

    <el-drawer
      v-model="fileMetaDrawerVisible"
      title="文件详情"
      size="420px"
    >
      <el-skeleton :loading="fileMetaLoading" :rows="6">
        <template #default>
          <div v-if="fileMeta">
            <el-descriptions :column="1" border>
              <el-descriptions-item label="文件名">
                {{ fileMeta.file_name }}
              </el-descriptions-item>
              <el-descriptions-item label="类型">
                {{ fileMeta.file_type }}
              </el-descriptions-item>
              <el-descriptions-item label="上传者">
                {{ fileMeta.uploader }}
              </el-descriptions-item>
              <el-descriptions-item label="上传时间">
                {{ fileMeta.upload_time }}
              </el-descriptions-item>
              <el-descriptions-item label="所在目录">
                {{ fileMeta.folder_name ?? 'home' }}
              </el-descriptions-item>
              <el-descriptions-item label="文件大小">
                {{ fileMeta.file_size ?? fileMeta.size ?? '-' }} bytes
              </el-descriptions-item>
              <el-descriptions-item label="MIME 类型">
                {{ fileMeta.mime_type ?? '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="索引状态">
                <el-tag :type="getIndexStatusTagType(fileMeta.index_status, fileMeta.index_warning)">
                  {{ getIndexStatusLabel(fileMeta.index_status, fileMeta.index_warning) }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="索引时间">
                {{ fileMeta.indexed_at || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="索引错误">
                {{ fileMeta.index_error || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="索引提示">
                {{ fileMeta.index_warning || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="内容哈希">
                <span style="word-break: break-all">{{ fileMeta.content_hash || '-' }}</span>
              </el-descriptions-item>
            </el-descriptions>

            <div style="margin-top: 16px; display: flex; gap: 12px; flex-wrap: wrap">
              <el-button
                type="success"
                :loading="indexingFileId === fileMeta!.id"
                :disabled="!fileMeta || fileMeta.index_status === 'indexing'"
                @click="handleIngestFile(fileMeta!.id, true)"
              >
                {{ fileMeta?.index_status === 'indexed' ? '重新索引' : '建立索引' }}
              </el-button>
              <el-button
                type="info"
                :disabled="!fileMeta"
                @click="goToChatForFile(fileMeta!.id)"
              >
                问这个文件
              </el-button>
              <el-button
                type="primary"
                :disabled="!fileMeta"
                @click="handleDownload(fileMeta!.id)"
              >
                下载
              </el-button>
            </div>
          </div>
        </template>
      </el-skeleton>
    </el-drawer>
  </AdminLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { ElTable } from 'element-plus'
import AdminLayout from '../layouts/AdminLayout.vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getFolderTreeApi,
  getFolderChildrenApi,
  createFolderApi,
  uploadFileApi,
  downloadFileApi,
  batchDownloadFilesApi,
  renameFolderApi,
  moveFolderApi,
  deleteFolderApi,
  moveFileApi,
  deleteFileApi,
  getFileMetaApi,
  type BreadcrumbItem,
  type FileItem,
  type FileMetaItem,
  type FolderItem,
  type FolderTreeItem,
} from '../api/files'
import { getFileIndexStatusApi, ingestFileApi } from '../api/qa'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()

const folderTree = ref<FolderTreeItem[]>([])
const currentFolderId = ref<number | null>(null)

const breadcrumbs = ref<BreadcrumbItem[]>([])
const currentFolders = ref<FolderItem[]>([])
const currentFiles = ref<FileItem[]>([])

const loading = ref(false)
const uploading = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const fileTableRef = ref<InstanceType<typeof ElTable> | null>(null)

type UploadQueueItem = {
  id: string
  name: string
  progress: number
  status: 'pending' | 'uploading' | 'success' | 'failed'
  error?: string
}
const uploadQueue = ref<UploadQueueItem[]>([])
const uploadStatusLabel: Record<UploadQueueItem['status'], string> = {
  pending: '等待中',
  uploading: '上传中',
  success: '成功',
  failed: '失败',
}
const selectedFiles = ref<FileItem[]>([])
const batchDownloading = ref(false)
const batchDownloadProgress = ref(0)

const renameFolderDialogVisible = ref(false)
const renameFolderTargetId = ref<number | null>(null)
const renameFolderName = ref('')

const moveDialogVisible = ref(false)
const moveDialogTargetKind = ref<'folder' | 'file' | null>(null)
const moveDialogTargetId = ref<number | null>(null)
const moveTargetParentId = ref<number | null>(null)

const fileMetaDrawerVisible = ref(false)
const fileMetaLoading = ref(false)
const fileMeta = ref<FileMetaItem | null>(null)
const indexingFileId = ref<number | null>(null)

const searchQ = ref('')
const newFolderName = ref('')

const getIndexStatusLabel = (status?: string, warning?: string | null) => {
  if (status === 'indexing') return '索引中'
  if (status === 'indexed' && warning) return '已索引(有提示)'
  if (status === 'indexed') return '已索引'
  if (status === 'failed') return '失败'
  return '待处理'
}

const normalizeIndexError = (message?: string | null) => {
  if (!message) return ''
  const upper = message.toUpperCase()
  if (message.includes('429') || upper.includes('RESOURCE_EXHAUSTED')) {
    return '当前模型配额不足，请稍后重试或检查模型服务配置。'
  }
  return message
}

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

const pollIndexStatus = async (fileId: number) => {
  for (let i = 0; i < 30; i += 1) {
    await sleep(1000)
    const latest = await getFileIndexStatusApi(fileId)
    if (latest.index_status !== 'indexing') {
      return latest
    }
  }
  return getFileIndexStatusApi(fileId)
}

const showIndexResultMessage = (result: {
  index_status: string
  index_warning?: string | null
  index_error?: string | null
}) => {
  if (result.index_status === 'indexed' && result.index_warning) {
    ElMessage.warning(result.index_warning)
    return
  }
  if (result.index_status === 'indexed') {
    ElMessage.success('文件索引成功')
    return
  }
  if (result.index_status === 'failed') {
    ElMessage.error(normalizeIndexError(result.index_error) || '文件索引失败')
    return
  }
  if (result.index_status === 'indexing') {
    ElMessage.info('该文件正在索引中，请稍后刷新状态')
  }
}

const watchIndexStatusInBackground = async (fileId: number) => {
  try {
    const latestStatus = await pollIndexStatus(fileId)
    await loadChildren()
    await refreshMetaIfOpen(fileId)
    showIndexResultMessage(latestStatus)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '获取索引状态失败')
  }
}

const getIndexStatusTagType = (status?: string, warning?: string | null) => {
  if (status === 'indexing') return 'info'
  if (status === 'indexed' && warning) return 'warning'
  if (status === 'indexed') return 'success'
  if (status === 'failed') return 'danger'
  return 'warning'
}

const getIndexStatusDetail = (row: {
  index_status?: string
  index_warning?: string | null
  index_error?: string | null
}) => {
  if (row.index_status === 'failed') return normalizeIndexError(row.index_error) || '索引失败'
  if (row.index_warning) return row.index_warning
  if (row.index_status === 'indexing') return '后台处理中'
  if (row.index_status === 'indexed') return '索引完成'
  return '等待建立索引'
}

const refreshMetaIfOpen = async (fileId: number) => {
  if (fileMetaDrawerVisible.value && fileMeta.value?.id === fileId) {
    fileMeta.value = await getFileMetaApi(fileId)
  }
}

const loadTree = async () => {
  try {
    folderTree.value = await getFolderTreeApi()
  } catch (error) {
    const message =
      error instanceof Error ? error.message : '加载目录树失败'
    ElMessage.error(message)
  }
}

const loadChildren = async () => {
  try {
    loading.value = true
    const res = await getFolderChildrenApi(currentFolderId.value)
    breadcrumbs.value = res.breadcrumbs
    currentFolders.value = res.folders
    currentFiles.value = res.files
  } catch (error) {
    const message = error instanceof Error ? error.message : '加载文件失败'
    ElMessage.error(message)
  } finally {
    loading.value = false
  }
}

const chooseFile = () => {
  fileInputRef.value?.click()
}

const updateUploadItem = (
  queueId: string,
  patch: Partial<UploadQueueItem>,
) => {
  const idx = uploadQueue.value.findIndex((item) => item.id === queueId)
  if (idx < 0) return
  const prev = uploadQueue.value[idx]
  if (!prev) return
  uploadQueue.value[idx] = { ...prev, ...patch }
}

const handleFileChange = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const selectedFilesRaw = Array.from(target.files ?? [])

  if (selectedFilesRaw.length === 0) {
    return
  }

  try {
    uploading.value = true
    const queueItems: UploadQueueItem[] = selectedFilesRaw.map((file) => ({
      id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
      name: file.name,
      progress: 0,
      status: 'pending',
    }))
    uploadQueue.value = queueItems

    await Promise.all(
      selectedFilesRaw.map(async (file, index) => {
        const queueId = queueItems[index]?.id
        if (!queueId) return
        updateUploadItem(queueId, { status: 'uploading', progress: 0, error: undefined })
        try {
          await uploadFileApi(file, currentFolderId.value, {
            onProgress: (percent) => {
              updateUploadItem(queueId, { progress: percent, status: 'uploading' })
            },
          })
          updateUploadItem(queueId, { status: 'success', progress: 100 })
        } catch (error) {
          const message = error instanceof Error ? error.message : '文件上传失败'
          updateUploadItem(queueId, { status: 'failed', error: message })
        }
      }),
    )

    await loadChildren()
    const failedCount = uploadQueue.value.filter((item) => item.status === 'failed').length
    if (failedCount === 0) {
      ElMessage.success(`成功上传 ${uploadQueue.value.length} 个文件`)
    } else {
      ElMessage.warning(`上传完成：成功 ${uploadQueue.value.length - failedCount}，失败 ${failedCount}`)
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : '文件上传失败'
    ElMessage.error(message)
  } finally {
    uploading.value = false
    if (fileInputRef.value) {
      fileInputRef.value.value = ''
    }
  }
}

const handleDownload = async (fileId: number) => {
  try {
    await downloadFileApi(fileId)
  } catch (error) {
    const message = error instanceof Error ? error.message : '下载失败'
    ElMessage.error(message)
  }
}

const handleSelectionChange = (rows: FileItem[]) => {
  selectedFiles.value = rows
}

const clearSelection = () => {
  fileTableRef.value?.clearSelection()
  selectedFiles.value = []
}

const handleBatchDownload = async () => {
  if (selectedFiles.value.length === 0) {
    ElMessage.warning('请先选择要下载的文件')
    return
  }
  try {
    batchDownloading.value = true
    batchDownloadProgress.value = 0
    await batchDownloadFilesApi(selectedFiles.value.map((item) => item.id), {
      onProgress: (percent) => {
        batchDownloadProgress.value = percent
      },
    })
    batchDownloadProgress.value = 100
    ElMessage.success(`已下载 ${selectedFiles.value.length} 个文件`)
  } catch (error) {
    const message = error instanceof Error ? error.message : '批量下载失败'
    ElMessage.error(message)
  } finally {
    batchDownloading.value = false
  }
}

const handleIngestFile = async (fileId: number, refreshMeta = false) => {
  try {
    indexingFileId.value = fileId
    if (refreshMeta && fileMeta.value?.id === fileId) {
      fileMeta.value = {
        ...fileMeta.value,
        index_status: 'indexing',
        index_error: null,
        index_warning: null,
      }
    }
    await loadChildren()
    const accepted = await ingestFileApi({ file_id: fileId, force_reindex: true })
    await refreshMetaIfOpen(fileId)
    if (accepted.queued) {
      ElMessage.success('已开始索引，正在后台处理')
      void watchIndexStatusInBackground(fileId)
    } else if (accepted.index_status === 'indexing') {
      showIndexResultMessage(accepted)
      void watchIndexStatusInBackground(fileId)
    } else {
      showIndexResultMessage(accepted)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '索引失败')
    await loadChildren()
    await refreshMetaIfOpen(fileId)
  } finally {
    indexingFileId.value = null
  }
}

onMounted(() => {
  ;(async () => {
    await loadTree()
    await loadChildren()
  })()
})

watch(
  () => route.query.open_file_id,
  async (value) => {
    const openFileId = Number(value)
    if (!Number.isNaN(openFileId) && openFileId > 0) {
      await openFileMeta(openFileId)
    }
  },
  { immediate: true },
)

const handleCreateFolder = async () => {
  const name = newFolderName.value.trim()
  if (!name) {
    ElMessage.warning('请输入文件夹名称')
    return
  }

  try {
    const created = await createFolderApi(name, currentFolderId.value)
    ElMessage.success('文件夹创建成功')
    newFolderName.value = ''

    currentFolderId.value = created.id
    await loadTree()
    await loadChildren()
  } catch (error) {
    const message = error instanceof Error ? error.message : '创建文件夹失败'
    ElMessage.error(message)
  }
}

const handleNodeClick = async (data: FolderTreeItem) => {
  searchQ.value = ''
  currentFolderId.value = data.id
  await loadChildren()
}

const enterFolder = async (folderId: number) => {
  searchQ.value = ''
  currentFolderId.value = folderId
  await loadChildren()
}

const goRoot = async () => {
  searchQ.value = ''
  currentFolderId.value = null
  await loadChildren()
}

const goToFolder = async (folderId: number) => {
  searchQ.value = ''
  currentFolderId.value = folderId
  await loadChildren()
}

const refreshCurrent = async () => {
  await loadChildren()
}

const filteredFolders = computed(() => {
  const keyword = searchQ.value.trim().toLowerCase()
  if (!keyword) return currentFolders.value
  return currentFolders.value.filter((f) => f.name.toLowerCase().includes(keyword))
})

const filteredFiles = computed(() => {
  const keyword = searchQ.value.trim().toLowerCase()
  if (!keyword) return currentFiles.value
  return currentFiles.value.filter((f) =>
    f.file_name.toLowerCase().includes(keyword),
  )
})

const overallUploadProgress = computed(() => {
  if (uploadQueue.value.length === 0) return 0
  const sum = uploadQueue.value.reduce((acc, item) => acc + item.progress, 0)
  return Math.round(sum / uploadQueue.value.length)
})

const folderNodeById = computed(() => {
  const map = new Map<number, FolderTreeItem>()
  const walk = (nodes: FolderTreeItem[]) => {
    nodes.forEach((n) => {
      map.set(n.id, n)
      if (n.children?.length) {
        walk(n.children)
      }
    })
  }
  walk(folderTree.value)
  return map
})

const moveDialogTitle = computed(() => {
  if (moveDialogTargetKind.value === 'folder') return '移动目录'
  if (moveDialogTargetKind.value === 'file') return '移动文件'
  return '移动到目录'
})

const goToChatForCurrentFolder = () => {
  const lastCrumb = breadcrumbs.value[breadcrumbs.value.length - 1]
  const currentName =
    currentFolderId.value === null
      ? 'home'
      : (lastCrumb?.name ?? folderNodeById.value.get(currentFolderId.value)?.name ?? `#${currentFolderId.value}`)
  router.push({
    name: 'chat',
    query: {
      scope_type: 'folder',
      folder_id: currentFolderId.value === null ? undefined : String(currentFolderId.value),
      folder_name: currentName,
    },
  })
}

const goToChatForFile = (fileId: number) => {
  router.push({
    name: 'chat',
    query: {
      scope_type: 'files',
      file_ids: String(fileId),
    },
  })
}

const openRenameFolder = (folderId: number) => {
  const node = folderNodeById.value.get(folderId)
  if (node?.parent_id === null) {
    ElMessage.error('根目录 home 不允许重命名')
    return
  }
  renameFolderTargetId.value = folderId
  renameFolderName.value = folderNodeById.value.get(folderId)?.name ?? ''
  renameFolderDialogVisible.value = true
}

const submitRenameFolder = async () => {
  if (renameFolderTargetId.value === null) return

  const name = renameFolderName.value.trim()
  if (!name) {
    ElMessage.warning('请输入新的目录名称')
    return
  }

  try {
    await renameFolderApi(renameFolderTargetId.value, name)
    ElMessage.success('目录重命名成功')
    renameFolderDialogVisible.value = false
    renameFolderTargetId.value = null

    await loadTree()
    await loadChildren()
  } catch (error) {
    const message = error instanceof Error ? error.message : '重命名失败'
    ElMessage.error(message)
  }
}

const openMoveFolder = (folderId: number) => {
  const node = folderNodeById.value.get(folderId)
  if (node?.parent_id === null) {
    ElMessage.error('根目录 home 不允许移动')
    return
  }
  moveDialogTargetKind.value = 'folder'
  moveDialogTargetId.value = folderId
  moveTargetParentId.value = folderNodeById.value.get(folderId)?.parent_id ?? null
  moveDialogVisible.value = true
}

const openMoveFile = (fileId: number, folderId?: number | null) => {
  moveDialogTargetKind.value = 'file'
  moveDialogTargetId.value = fileId
  moveTargetParentId.value = folderId ?? null
  moveDialogVisible.value = true
}

const selectMoveRoot = () => {
  moveTargetParentId.value = null
}

const handleMoveTreeNodeClick = (data: FolderTreeItem) => {
  moveTargetParentId.value = data.id
}

const submitMoveTarget = async () => {
  if (!moveDialogTargetKind.value || moveDialogTargetId.value === null) return

  try {
    if (moveDialogTargetKind.value === 'folder') {
      await moveFolderApi(moveDialogTargetId.value, moveTargetParentId.value)
    } else {
      await moveFileApi(moveDialogTargetId.value, moveTargetParentId.value)
    }

    ElMessage.success('移动成功')
    moveDialogVisible.value = false
    moveDialogTargetKind.value = null
    moveDialogTargetId.value = null

    await loadTree()
    await loadChildren()
  } catch (error) {
    const message = error instanceof Error ? error.message : '移动失败'
    ElMessage.error(message)
  }
}

const handleDeleteFolder = async (folderId: number) => {
  // 使用 element-plus 默认的消息确认框
  try {
    const node = folderNodeById.value.get(folderId)
    if (node?.parent_id === null) {
      ElMessage.error('根目录 home 不允许删除')
      return
    }

    await ElMessageBox.confirm('确定要删除该目录吗？', '确认删除', {
      type: 'warning',
    })

    await deleteFolderApi(folderId)
    ElMessage.success('目录删除成功')

    if (currentFolderId.value === folderId) {
      currentFolderId.value = null
    }

    await loadTree()
    await loadChildren()
  } catch (error) {
    const e: any = error
    if (e === 'cancel') return
    const message = error instanceof Error ? error.message : '目录删除失败'
    ElMessage.error(message)
  }
}

const handleDeleteFile = async (fileId: number) => {
  try {
    await ElMessageBox.confirm('确定要删除该文件吗？', '确认删除', {
      type: 'warning',
    })

    await deleteFileApi(fileId)
    ElMessage.success('文件删除成功')

    await loadTree()
    await loadChildren()
  } catch (error) {
    const e: any = error
    if (e === 'cancel') return
    const message = error instanceof Error ? error.message : '文件删除失败'
    ElMessage.error(message)
  }
}

const openFileMeta = async (fileId: number) => {
  fileMetaDrawerVisible.value = true
  fileMetaLoading.value = true
  fileMeta.value = null

  try {
    fileMeta.value = await getFileMetaApi(fileId)
  } catch (error) {
    const message = error instanceof Error ? error.message : '获取文件详情失败'
    ElMessage.error(message)
    fileMetaDrawerVisible.value = false
  } finally {
    fileMetaLoading.value = false
  }
}
</script>
