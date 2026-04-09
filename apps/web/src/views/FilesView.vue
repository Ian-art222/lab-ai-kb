<template>
  <AdminLayout>
    <div class="files-drive-page">
      <el-card class="files-drive-shell" shadow="never">
        <FilesDriveHeaderBar
          :current-title="currentDirectoryTitle"
          :space-label="spaceLabel"
          :space-kind="spaceKind"
          :breadcrumbs="breadcrumbs"
          @go-root="goRoot"
          @go-folder="goToFolder"
        >
          <template #toolbar>
            <input
              ref="fileInputRef"
              type="file"
              multiple
              class="files-hidden-input"
              @change="handleFileChange"
            />
            <el-button
              :disabled="!folderViewUi.can_upload"
              type="primary"
              :loading="uploading"
              @click="chooseFile"
            >
              上传文件
            </el-button>
            <el-button
              :disabled="!folderViewUi.can_create_subfolder"
              type="primary"
              plain
              @click="openNewFolderDialog"
            >
              新建文件夹
            </el-button>
            <el-button
              :disabled="!batchCanDownload"
              :loading="batchDownloading"
              type="primary"
              plain
              @click="handleBatchDownload"
            >
              下载
            </el-button>
            <el-button :disabled="!batchCanDelete" type="danger" plain @click="batchDelete">
              删除
            </el-button>
            <el-button :disabled="!batchCanMove" plain @click="openBatchMove">移动</el-button>
            <el-button :disabled="!batchCanCopy" plain @click="batchCopyToCurrent">复制</el-button>
            <el-button :disabled="!canGoParent" plain @click="goParent">返回上一级</el-button>
            <el-button type="primary" plain :loading="loading" @click="refreshCurrent">刷新</el-button>
            <el-input v-model="searchQ" placeholder="搜索当前目录" style="width: 200px" clearable />
            <el-dropdown trigger="click" @command="onMoreMenuCommand">
              <el-button plain :title="'当前排序：' + sortLabel">
                更多<el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="paste" :disabled="!canToolbarPaste">粘贴</el-dropdown-item>
                  <el-dropdown-item
                    command="clipboard-copy"
                    :disabled="!canCopySelectionToClipboard"
                  >
                    复制到剪贴板
                  </el-dropdown-item>
                  <el-dropdown-item command="clipboard-cut" :disabled="!canCutSelectionToClipboard">
                    剪切
                  </el-dropdown-item>
                  <el-dropdown-item divided command="sort:name:asc">名称 ↑</el-dropdown-item>
                  <el-dropdown-item command="sort:name:desc">名称 ↓</el-dropdown-item>
                  <el-dropdown-item command="sort:mtime:asc">修改时间 ↑</el-dropdown-item>
                  <el-dropdown-item command="sort:mtime:desc">修改时间 ↓</el-dropdown-item>
                  <el-dropdown-item command="sort:size:asc">大小 ↑</el-dropdown-item>
                  <el-dropdown-item command="sort:size:desc">大小 ↓</el-dropdown-item>
                  <el-dropdown-item divided command="chat-folder">在当前目录问答</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </FilesDriveHeaderBar>

        <div v-if="selectionCount > 0" class="files-selection-bar">
          <el-tag>已选 {{ selectionCount }} 项</el-tag>
          <el-button size="small" @click="clearSelection">取消选择</el-button>
        </div>
        <div v-if="!folderViewUi.can_download_files && authStore.isMember" class="files-no-dl-hint">
          当前账号无下载权限；如需下载请联系管理员开启「允许下载」。
        </div>

        <FolderCardNavigator
          :folders="navigatorFolders"
          :loading="loading"
          :variant="currentFolderId === null ? 'home' : 'nested'"
          :space-kind="spaceKind"
          @enter="onNavigatorEnter"
        />

        <div
          ref="dropZoneRef"
          class="files-drop-zone"
          :class="{ 'files-drop-zone-active': dragOver }"
          @dragenter.prevent="dragOver = true"
          @dragover.prevent="dragOver = true"
          @dragleave.prevent="onDragLeave"
          @drop.prevent="onDropFiles"
          @contextmenu="onDropZoneContextMenu"
        >
          <div class="files-list-section-head">
            <span class="files-list-section-label">文件与文件夹列表</span>
          </div>
          <el-table
            ref="driveTableRef"
            v-loading="loading"
            :data="sortedDriveRows"
            row-key="rowUid"
            class="files-drive-table"
            height="520"
            highlight-current-row
            :row-class-name="driveRowClassName"
            @row-click="onDriveRowClick"
            @row-dblclick="onDriveRowDblclick"
            @row-contextmenu="onDriveRowContextmenu"
          >
            <el-table-column width="48">
              <template #default="{ row }">
                <el-checkbox
                  :model-value="isRowSelected(row)"
                  @click.stop
                  @change="() => toggleRowSelect(row)"
                />
              </template>
            </el-table-column>
            <el-table-column label="名称" min-width="240">
              <template #default="{ row }">
                <span class="files-name-cell">
                  <span class="files-icon" :class="row.kind === 'folder' ? 'is-folder' : 'is-file'" />
                  {{ row.kind === 'folder' ? folderDisplayName(row.name) : row.file_name }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="100">
              <template #default="{ row }">
                {{ row.kind === 'folder' ? '—' : formatSize(row.file_size) }}
              </template>
            </el-table-column>
            <el-table-column label="修改/上传时间" width="180">
              <template #default="{ row }">
                {{ row.kind === 'folder' ? row.created_at : row.upload_time }}
              </template>
            </el-table-column>
            <el-table-column label="索引" width="120">
              <template #default="{ row }">
                <template v-if="row.kind === 'file'">
                  <el-tag :type="getIndexStatusTagType(row.index_status, row.index_warning)">
                    {{ getIndexStatusLabel(row.index_status, row.index_warning) }}
                  </el-tag>
                </template>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="上传者" width="120">
              <template #default="{ row }">
                {{ row.kind === 'file' ? row.uploader : '—' }}
              </template>
            </el-table-column>
          </el-table>

          <div class="files-drop-hint" v-if="folderViewUi.can_upload">
            支持将文件拖拽到上方列表区域上传
          </div>

          <el-empty
            v-if="!loading && sortedDriveRows.length === 0"
            description="当前目录暂无内容"
            style="padding: 16px 0"
          />

          <div v-if="uploadQueue.length > 0" class="files-upload-panel">
            <el-divider>上传进度</el-divider>
            <div class="files-upload-summary">
              总进度 {{ overallUploadProgress }}%
              <el-progress :percentage="overallUploadProgress" />
            </div>
            <div v-for="item in uploadQueue" :key="item.id" class="files-upload-item">
              <div class="files-upload-item-head">
                <span>{{ item.name }}</span>
                <span>{{ uploadStatusLabel[item.status] }} {{ item.progress }}%</span>
              </div>
              <el-progress
                :percentage="item.progress"
                :status="
                  item.status === 'failed'
                    ? 'exception'
                    : item.status === 'success'
                      ? 'success'
                      : undefined
                "
              />
              <div v-if="item.error" class="files-upload-err">{{ item.error }}</div>
            </div>
          </div>

          <div v-if="batchDownloading" class="files-upload-panel">
            <el-divider>批量下载</el-divider>
            <el-progress :percentage="batchDownloadProgress" />
          </div>
        </div>
      </el-card>
    </div>

    <teleport to="body">
      <div
        v-show="ctxMenu.visible"
        class="files-ctx-menu"
        :style="{ left: ctxMenu.x + 'px', top: ctxMenu.y + 'px' }"
        @click.stop
      >
        <template v-if="ctxMenu.mode === 'blank'">
          <button type="button" :disabled="!folderViewUi.can_upload" @click="ctxUpload">上传文件</button>
          <button type="button" :disabled="!folderViewUi.can_create_subfolder" @click="ctxNewFolder">
            新建文件夹
          </button>
          <button type="button" @click="ctxRefresh">刷新</button>
          <button type="button" :disabled="!canToolbarPaste" @click="ctxPaste">粘贴</button>
        </template>
        <template v-else-if="ctxMenu.row?.kind === 'folder'">
          <button type="button" @click="ctxOpenFolder">打开</button>
          <button type="button" :disabled="!ctxMenu.row.can_rename_folder" @click="ctxRenameFolder">
            重命名
          </button>
          <button type="button" :disabled="!ctxMenu.row.can_move_folder" @click="ctxMoveFolder">
            移动
          </button>
          <button type="button" disabled title="暂不支持整目录复制">复制</button>
          <button type="button" :disabled="!ctxMenu.row.can_delete_folder" @click="ctxDeleteFolder">
            删除
          </button>
        </template>
        <template v-else-if="ctxMenu.row?.kind === 'file'">
          <button type="button" @click="ctxOpenFile">打开 / 详情</button>
          <button
            type="button"
            :disabled="!fileCtxCanDownload"
            :title="!fileCtxCanDownload ? '无下载权限' : ''"
            @click="ctxDownload"
          >
            下载
          </button>
          <button type="button" :disabled="!ctxMenu.row.can_rename" @click="ctxRenameFile">重命名</button>
          <button type="button" :disabled="!ctxMenu.row.can_move" @click="ctxMoveFile">移动</button>
          <button type="button" :disabled="!ctxMenu.row.can_copy" @click="ctxCopyFileImmediate">
            复制到当前目录
          </button>
          <button type="button" :disabled="!ctxMenu.row.can_copy" @click="ctxCopyToClipboard">
            复制到剪贴板
          </button>
          <button type="button" :disabled="!ctxMenu.row.can_move" @click="ctxCutToClipboard">剪切</button>
          <button type="button" :disabled="!ctxMenu.row.can_delete" @click="ctxDeleteFile">删除</button>
          <button type="button" v-if="!authStore.isMember" @click="ctxIngest">建立索引</button>
          <button type="button" @click="ctxChatFile">问答此文件</button>
        </template>
      </div>
    </teleport>

    <el-dialog v-model="renameFolderDialogVisible" title="重命名目录" width="420px">
      <el-input v-model="renameFolderName" placeholder="新目录名称" clearable />
      <template #footer>
        <el-button @click="renameFolderDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRenameFolder">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="renameFileDialogVisible" title="重命名文件" width="420px">
      <el-input v-model="renameFileName" placeholder="新文件名" clearable />
      <template #footer>
        <el-button @click="renameFileDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRenameFile">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="newFolderDialogVisible" title="新建文件夹" width="420px">
      <el-input v-model="newFolderDialogName" placeholder="文件夹名称" clearable />
      <template #footer>
        <el-button @click="newFolderDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!folderViewUi.can_create_subfolder" @click="submitNewFolderDialog">
          创建
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="moveDialogVisible" :title="moveDialogTitle" width="460px">
      <div class="files-move-hint">请选择目标目录（将移动到所选文件夹内）</div>
      <div class="files-move-root-btns">
        <el-button :type="moveTargetParentId === null ? 'primary' : 'default'" @click="selectMoveRoot">
          home（顶层）
        </el-button>
      </div>
      <div class="files-move-tree">
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

    <el-drawer v-model="fileMetaDrawerVisible" title="文件详情" size="420px">
      <el-skeleton :loading="fileMetaLoading" :rows="6">
        <template #default>
          <div v-if="fileMeta">
            <el-descriptions :column="1" border>
              <el-descriptions-item label="文件名">{{ fileMeta.file_name }}</el-descriptions-item>
              <el-descriptions-item label="类型">{{ fileMeta.file_type }}</el-descriptions-item>
              <el-descriptions-item label="上传者">{{ fileMeta.uploader }}</el-descriptions-item>
              <el-descriptions-item label="上传时间">{{ fileMeta.upload_time }}</el-descriptions-item>
              <el-descriptions-item label="所在目录">{{ fileMeta.folder_name ?? '—' }}</el-descriptions-item>
              <el-descriptions-item label="文件大小">
                {{ fileMeta.file_size ?? fileMeta.size ?? '-' }} bytes
              </el-descriptions-item>
              <el-descriptions-item label="MIME">{{ fileMeta.mime_type ?? '-' }}</el-descriptions-item>
              <el-descriptions-item label="索引状态">
                <el-tag :type="getIndexStatusTagType(fileMeta.index_status, fileMeta.index_warning)">
                  {{ getIndexStatusLabel(fileMeta.index_status, fileMeta.index_warning) }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="索引时间">{{ fileMeta.indexed_at || '-' }}</el-descriptions-item>
              <el-descriptions-item label="索引错误">{{ fileMeta.index_error || '-' }}</el-descriptions-item>
              <el-descriptions-item label="索引提示">{{ fileMeta.index_warning || '-' }}</el-descriptions-item>
              <el-descriptions-item label="内容哈希">
                <span style="word-break: break-all">{{ fileMeta.content_hash || '-' }}</span>
              </el-descriptions-item>
            </el-descriptions>

            <el-collapse
              v-if="authStore.isRoot && (fileChunkDiag || fileChunkDiagLoading)"
              style="margin-top: 12px"
            >
              <el-collapse-item title="切块诊断（v3 structural）" name="chunk-diag">
                <el-skeleton :loading="fileChunkDiagLoading" :rows="4">
                  <template #default>
                    <div v-if="fileChunkDiag">
                      <el-descriptions :column="1" border size="small">
                        <el-descriptions-item label="parent 数">{{
                          fileChunkDiag.parent_count
                        }}</el-descriptions-item>
                        <el-descriptions-item label="child 数">{{
                          fileChunkDiag.child_count
                        }}</el-descriptions-item>
                        <el-descriptions-item label="legacy 行">{{
                          fileChunkDiag.legacy_count
                        }}</el-descriptions-item>
                      </el-descriptions>
                    </div>
                  </template>
                </el-skeleton>
              </el-collapse-item>
            </el-collapse>

            <div class="files-meta-actions">
              <el-button
                v-if="!authStore.isMember"
                type="success"
                :loading="indexingFileId === fileMeta!.id"
                :disabled="!fileMeta || fileMeta.index_status === 'indexing'"
                @click="handleIngestFile(fileMeta!.id, true)"
              >
                {{ fileMeta?.index_status === 'indexed' ? '重新索引' : '建立索引' }}
              </el-button>
              <el-button type="info" :disabled="!fileMeta" @click="goToChatForFile(fileMeta!.id)">
                问这个文件
              </el-button>
              <el-button
                type="primary"
                :disabled="!fileMeta || !metaCanDownload"
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
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import type { ElTable } from 'element-plus'
import AdminLayout from '../layouts/AdminLayout.vue'
import FilesDriveHeaderBar from '../components/files/FilesDriveHeaderBar.vue'
import FolderCardNavigator from '../components/files/FolderCardNavigator.vue'
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
  copyFileApi,
  deleteFileApi,
  renameFileApi,
  getFileMetaApi,
  getChunkDiagnosticsApi,
  type BreadcrumbItem,
  type ChunkDiagnostics,
  type FileItem,
  type FileMetaItem,
  type FolderItem,
  type FolderTreeItem,
  type FolderViewUi,
} from '../api/files'
import { getFileIndexStatusApi, ingestFileApi } from '../api/qa'
import { useAuthStore } from '../stores/auth'
import { formatAdminPrivateFolderDisplayName } from '../utils/folderDisplay'

type DriveRow =
  | ({ kind: 'folder'; rowUid: string } & FolderItem)
  | ({ kind: 'file'; rowUid: string } & FileItem)

type ClipboardPayload = {
  op: 'copy' | 'cut'
  items: Array<{ kind: 'file' | 'folder'; id: number }>
}

const authStore = useAuthStore()
const router = useRouter()

const folderDisplayOpts = computed(() => ({
  isAdmin: authStore.isAdmin,
  isRoot: authStore.isRoot,
  userId: authStore.userId,
}))

function folderDisplayName(raw: string) {
  return formatAdminPrivateFolderDisplayName(raw, folderDisplayOpts.value)
}
const route = useRoute()

const defaultFolderUi: FolderViewUi = {
  can_manage_structure: false,
  can_create_subfolder: false,
  can_upload: false,
  can_download_files: false,
  can_move_or_delete_files: false,
}
const folderViewUi = ref<FolderViewUi>({ ...defaultFolderUi })

const folderTree = ref<FolderTreeItem[]>([])
const currentFolderId = ref<number | null>(null)
const currentFolderRecord = ref<FolderItem | null>(null)
const breadcrumbs = ref<BreadcrumbItem[]>([])
const currentFolders = ref<FolderItem[]>([])
const currentFiles = ref<FileItem[]>([])
const spaceLabel = ref('')
const spaceKind = ref('')

const loading = ref(false)
const uploading = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const dropZoneRef = ref<HTMLElement | null>(null)
const driveTableRef = ref<InstanceType<typeof ElTable> | null>(null)
const dragOver = ref(false)

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
const batchDownloading = ref(false)
const batchDownloadProgress = ref(0)

const selectedKeys = ref<Set<string>>(new Set())
const anchorRowUid = ref<string | null>(null)

const sortBy = ref<'name' | 'mtime' | 'size'>('name')
const sortOrder = ref<'asc' | 'desc'>('asc')

const clipboard = ref<ClipboardPayload | null>(null)

const ctxMenu = ref<{
  visible: boolean
  x: number
  y: number
  mode: 'blank' | 'row'
  row: DriveRow | null
}>({ visible: false, x: 0, y: 0, mode: 'blank', row: null })

const renameFolderDialogVisible = ref(false)
const renameFolderTargetId = ref<number | null>(null)
const renameFolderName = ref('')

const renameFileDialogVisible = ref(false)
const renameFileTargetId = ref<number | null>(null)
const renameFileName = ref('')

const newFolderDialogVisible = ref(false)
const newFolderDialogName = ref('')

const moveDialogVisible = ref(false)
const moveDialogTargetKind = ref<'folder' | 'file' | 'batch' | null>(null)
const moveDialogTargetId = ref<number | null>(null)
const moveBatchFileIds = ref<number[]>([])
const moveTargetParentId = ref<number | null>(null)

const fileMetaDrawerVisible = ref(false)
const fileMetaLoading = ref(false)
const fileMeta = ref<FileMetaItem | null>(null)
const fileChunkDiagLoading = ref(false)
const fileChunkDiag = ref<ChunkDiagnostics | null>(null)
const indexingFileId = ref<number | null>(null)

const searchQ = ref('')

const homeRootId = computed(() => folderTree.value[0]?.id ?? null)

const currentDirectoryTitle = computed(() => {
  if (currentFolderId.value === null) return '全部文件'
  const last = breadcrumbs.value[breadcrumbs.value.length - 1]
  if (last?.name) return last.name
  return currentFolderRecord.value?.name ?? '当前目录'
})

const navigatorFolders = computed(() => {
  const q = searchQ.value.trim().toLowerCase()
  if (!q) return currentFolders.value
  return currentFolders.value.filter((f) => f.name.toLowerCase().includes(q))
})

const sortLabel = computed(() => {
  const field = sortBy.value === 'name' ? '名称' : sortBy.value === 'mtime' ? '时间' : '大小'
  return `${field} ${sortOrder.value === 'asc' ? '升序' : '降序'}`
})

const canGoParent = computed(() => currentFolderId.value !== null)

const driveRows = computed<DriveRow[]>(() => {
  const q = searchQ.value.trim().toLowerCase()
  const folders = !q
    ? currentFolders.value
    : currentFolders.value.filter((f) => f.name.toLowerCase().includes(q))
  const files = !q
    ? currentFiles.value
    : currentFiles.value.filter((f) => f.file_name.toLowerCase().includes(q))
  const out: DriveRow[] = [
    ...folders.map(
      (f) =>
        ({
          kind: 'folder',
          rowUid: `folder:${f.id}`,
          ...f,
        }) as DriveRow,
    ),
    ...files.map(
      (f) =>
        ({
          kind: 'file',
          rowUid: `file:${f.id}`,
          ...f,
        }) as DriveRow,
    ),
  ]
  return out
})

function rowSortKey(row: DriveRow): string {
  if (row.kind === 'folder') return row.name ?? ''
  return row.file_name ?? ''
}

function rowMtime(row: DriveRow): number {
  const s = row.kind === 'folder' ? row.created_at : row.upload_time
  const t = s ? Date.parse(s) : 0
  return Number.isNaN(t) ? 0 : t
}

function rowSize(row: DriveRow): number {
  if (row.kind === 'folder') return -1
  return row.file_size ?? 0
}

const sortedDriveRows = computed(() => {
  const rows = [...driveRows.value]
  const mult = sortOrder.value === 'asc' ? 1 : -1
  rows.sort((a, b) => {
    if (a.kind !== b.kind) {
      return a.kind === 'folder' ? -1 : 1
    }
    if (sortBy.value === 'name') {
      return mult * rowSortKey(a).localeCompare(rowSortKey(b), 'zh-CN')
    }
    if (sortBy.value === 'mtime') {
      return mult * (rowMtime(a) - rowMtime(b))
    }
    return mult * (rowSize(a) - rowSize(b))
  })
  return rows
})

const selectionCount = computed(() => selectedKeys.value.size)

const selectedRows = computed(() =>
  sortedDriveRows.value.filter((r) => selectedKeys.value.has(r.rowUid)),
)

const selectedFiles = computed(() =>
  selectedRows.value.filter((r): r is Extract<DriveRow, { kind: 'file' }> => r.kind === 'file'),
)

const selectedFolders = computed(() =>
  selectedRows.value.filter((r): r is Extract<DriveRow, { kind: 'folder' }> => r.kind === 'folder'),
)

const batchCanDownload = computed(() => {
  if (selectedFiles.value.length === 0) return false
  if (!folderViewUi.value.can_download_files) return false
  return selectedFiles.value.every((f) => f.can_download !== false)
})

const batchCanDelete = computed(() => {
  if (selectedRows.value.length === 0) return false
  const okFiles = selectedFiles.value.every((f) => f.can_delete)
  const okFolders = selectedFolders.value.every((f) => f.can_delete_folder)
  return okFiles && okFolders && (selectedFiles.value.length > 0 || selectedFolders.value.length > 0)
})

const batchCanMove = computed(() => {
  if (selectedRows.value.length === 0) return false
  const okFiles = selectedFiles.value.every((f) => f.can_move)
  const okFolders = selectedFolders.value.every((f) => f.can_move_folder)
  return okFiles && okFolders
})

const batchCanCopy = computed(() => {
  if (!folderViewUi.value.can_upload) return false
  if (selectedFiles.value.length === 0 || selectedFolders.value.length > 0) return false
  return selectedFiles.value.every((f) => f.can_copy)
})

const canToolbarPaste = computed(() => {
  if (!clipboard.value || !folderViewUi.value.can_upload) return false
  if (clipboard.value.op === 'copy') {
    return clipboard.value.items.every((it) => it.kind === 'file')
  }
  return clipboard.value.items.length > 0
})

const canCopySelectionToClipboard = computed(() => {
  if (selectedRows.value.length === 0) return false
  if (selectedRows.value.some((r) => r.kind === 'folder')) return false
  return selectedFiles.value.every((f) => f.can_copy)
})

const canCutSelectionToClipboard = computed(() => {
  if (selectedRows.value.length === 0) return false
  return selectedRows.value.every((r) =>
    r.kind === 'file' ? Boolean(r.can_move) : Boolean(r.can_move_folder),
  )
})

const fileCtxCanDownload = computed(() => {
  const row = ctxMenu.value.row
  if (!row || row.kind !== 'file') return false
  if (!folderViewUi.value.can_download_files) return false
  return row.can_download !== false
})

const metaCanDownload = computed(() => {
  if (!fileMeta.value) return false
  if (!folderViewUi.value.can_download_files) return false
  const live = currentFiles.value.find((f) => f.id === fileMeta.value!.id)
  if (live) return live.can_download !== false
  return true
})

function formatSize(n: number | null | undefined) {
  if (n == null) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function onSortCommand(cmd: string) {
  const [a, o] = cmd.split(':')
  if (a === 'name' || a === 'mtime' || a === 'size') sortBy.value = a
  if (o === 'asc' || o === 'desc') sortOrder.value = o
}

function onMoreMenuCommand(cmd: string) {
  if (cmd === 'paste') {
    void pasteHere()
    return
  }
  if (cmd === 'clipboard-copy') {
    copySelectionToClipboard('copy')
    return
  }
  if (cmd === 'clipboard-cut') {
    copySelectionToClipboard('cut')
    return
  }
  if (cmd === 'chat-folder') {
    goToChatForCurrentFolder()
    return
  }
  if (cmd.startsWith('sort:')) {
    onSortCommand(cmd.slice(5))
  }
}

function isRowSelected(row: DriveRow) {
  return selectedKeys.value.has(row.rowUid)
}

function clearSelection() {
  selectedKeys.value = new Set()
  anchorRowUid.value = null
}

function toggleRowSelect(row: DriveRow) {
  const next = new Set(selectedKeys.value)
  if (next.has(row.rowUid)) next.delete(row.rowUid)
  else next.add(row.rowUid)
  selectedKeys.value = next
  anchorRowUid.value = row.rowUid
}

function driveRowClassName({ row }: { row: DriveRow }) {
  return selectedKeys.value.has(row.rowUid) ? 'files-row-selected' : ''
}

function rangeSelect(toRow: DriveRow) {
  const rows = sortedDriveRows.value
  const anchor = anchorRowUid.value
  if (!anchor) {
    selectedKeys.value = new Set([toRow.rowUid])
    anchorRowUid.value = toRow.rowUid
    return
  }
  const ai = rows.findIndex((r) => r.rowUid === anchor)
  const bi = rows.findIndex((r) => r.rowUid === toRow.rowUid)
  if (ai < 0 || bi < 0) return
  const [lo, hi] = ai <= bi ? [ai, bi] : [bi, ai]
  const next = new Set(selectedKeys.value)
  for (let i = lo; i <= hi; i += 1) {
    const r = rows[i]
    if (r) next.add(r.rowUid)
  }
  selectedKeys.value = next
}

function onDriveRowClick(row: DriveRow, _column: unknown, event: MouseEvent) {
  const e = event
  if (e.ctrlKey || e.metaKey) {
    toggleRowSelect(row)
    return
  }
  if (e.shiftKey) {
    rangeSelect(row)
    return
  }
  selectedKeys.value = new Set([row.rowUid])
  anchorRowUid.value = row.rowUid
}

function onDriveRowDblclick(row: DriveRow) {
  if (row.kind === 'folder') {
    void enterFolder(row.id)
    return
  }
  void openFileMeta(row.id)
}

function closeCtxMenu() {
  ctxMenu.value.visible = false
}

function onDriveRowContextmenu(row: DriveRow, _col: unknown, e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  if (!selectedKeys.value.has(row.rowUid)) {
    selectedKeys.value = new Set([row.rowUid])
    anchorRowUid.value = row.rowUid
  }
  ctxMenu.value = {
    visible: true,
    x: e.clientX,
    y: e.clientY,
    mode: 'row',
    row,
  }
}

function onDropZoneContextMenu(e: MouseEvent) {
  const t = e.target as HTMLElement
  if (t.closest('.el-table__row')) return
  e.preventDefault()
  ctxMenu.value = {
    visible: true,
    x: e.clientX,
    y: e.clientY,
    mode: 'blank',
    row: null,
  }
}

function onGlobalClick() {
  closeCtxMenu()
}

function ctxUpload() {
  closeCtxMenu()
  chooseFile()
}

function ctxNewFolder() {
  closeCtxMenu()
  openNewFolderDialog()
}

function ctxRefresh() {
  closeCtxMenu()
  void refreshCurrent()
}

function ctxPaste() {
  closeCtxMenu()
  void pasteHere()
}

function ctxOpenFolder() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'folder') void enterFolder(row.id)
}

function ctxRenameFolder() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'folder') openRenameFolder(row.id)
}

function ctxMoveFolder() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'folder') openMoveFolder(row.id)
}

function ctxDeleteFolder() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'folder') void handleDeleteFolder(row.id)
}

function ctxOpenFile() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'file') void openFileMeta(row.id)
}

function ctxDownload() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'file') void handleDownload(row.id)
}

function ctxRenameFile() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind !== 'file') return
  renameFileTargetId.value = row.id
  renameFileName.value = row.file_name
  renameFileDialogVisible.value = true
}

function ctxMoveFile() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'file') openMoveFile(row.id, row.folder_id)
}

function ctxCopyFileImmediate() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'file') void handleCopyFileToCurrent(row.id)
}

function ctxCopyToClipboard() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind !== 'file' || !row.can_copy) return
  clipboard.value = { op: 'copy', items: [{ kind: 'file', id: row.id }] }
  ElMessage.success('已复制到剪贴板，可在目标目录粘贴')
}

function ctxCutToClipboard() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind !== 'file' || !row.can_move) return
  clipboard.value = { op: 'cut', items: [{ kind: 'file', id: row.id }] }
  ElMessage.success('已剪切，可在目标目录粘贴')
}

function copySelectionToClipboard(op: 'copy' | 'cut') {
  const rows = selectedRows.value
  if (rows.length === 0) return
  if (op === 'copy') {
    if (rows.some((r) => r.kind === 'folder')) {
      ElMessage.warning('暂只支持将文件复制到剪贴板')
      return
    }
    if (!rows.every((r) => r.kind === 'file' && r.can_copy)) {
      ElMessage.warning('选中项包含不可复制的文件')
      return
    }
    clipboard.value = {
      op: 'copy',
      items: rows.filter((r): r is Extract<DriveRow, { kind: 'file' }> => r.kind === 'file').map(
        (r) => ({ kind: 'file' as const, id: r.id }),
      ),
    }
  } else {
    if (!rows.every((r) => (r.kind === 'file' ? r.can_move : r.can_move_folder))) {
      ElMessage.warning('选中项包含不可剪切的项')
      return
    }
    clipboard.value = {
      op: 'cut',
      items: rows.map((r) => ({ kind: r.kind, id: r.id })),
    }
  }
  ElMessage.success(op === 'cut' ? '已剪切，可在目标目录粘贴' : '已复制到剪贴板')
}

function ctxDeleteFile() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'file') void handleDeleteFile(row.id)
}

function ctxIngest() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'file') void handleIngestFile(row.id)
}

function ctxChatFile() {
  const row = ctxMenu.value.row
  closeCtxMenu()
  if (row?.kind === 'file') goToChatForFile(row.id)
}

const moveDialogTitle = computed(() => {
  if (moveDialogTargetKind.value === 'folder') return '移动目录'
  if (moveDialogTargetKind.value === 'file') return '移动文件'
  if (moveDialogTargetKind.value === 'batch') return '批量移动文件'
  return '移动到目录'
})

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

const UPLOAD_CONCURRENCY = 3

async function runWithConcurrency<T>(
  items: T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<void>,
): Promise<void> {
  if (items.length === 0) return
  const limit = Math.max(1, Math.min(concurrency, items.length))
  let next = 0
  const runNext = async (): Promise<void> => {
    const i = next
    next += 1
    if (i >= items.length) return
    const item = items[i]
    if (item === undefined) return
    await worker(item, i)
    await runNext()
  }
  await Promise.all(Array.from({ length: limit }, () => runNext()))
}

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

const refreshMetaIfOpen = async (fileId: number) => {
  if (fileMetaDrawerVisible.value && fileMeta.value?.id === fileId) {
    fileMeta.value = await getFileMetaApi(fileId)
  }
}

const loadTree = async () => {
  try {
    folderTree.value = await getFolderTreeApi()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载目录树失败')
  }
}

const loadChildren = async () => {
  try {
    loading.value = true
    const res = await getFolderChildrenApi(currentFolderId.value)
    breadcrumbs.value = res.breadcrumbs.map((b) => ({
      ...b,
      name: formatAdminPrivateFolderDisplayName(b.name, folderDisplayOpts.value),
    }))
    currentFolders.value = res.folders
    currentFiles.value = res.files
    folderViewUi.value = res.ui ?? { ...defaultFolderUi }
    currentFolderRecord.value = res.current_folder
    spaceLabel.value = res.space_label ?? ''
    spaceKind.value = res.space_kind ?? ''
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载文件失败')
  } finally {
    loading.value = false
  }
}

const chooseFile = () => {
  fileInputRef.value?.click()
}

const updateUploadItem = (queueId: string, patch: Partial<UploadQueueItem>) => {
  const idx = uploadQueue.value.findIndex((item) => item.id === queueId)
  if (idx < 0) return
  const prev = uploadQueue.value[idx]
  if (!prev) return
  uploadQueue.value[idx] = { ...prev, ...patch }
}

async function runUploadFiles(selectedFilesRaw: File[]) {
  if (selectedFilesRaw.length === 0) return
  try {
    uploading.value = true
    const queueItems: UploadQueueItem[] = selectedFilesRaw.map((file) => ({
      id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
      name: file.name,
      progress: 0,
      status: 'pending',
    }))
    uploadQueue.value = queueItems

    await runWithConcurrency(selectedFilesRaw, UPLOAD_CONCURRENCY, async (file, index) => {
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
    })

    await loadChildren()
    const failedItems = uploadQueue.value.filter((item) => item.status === 'failed')
    const failedCount = failedItems.length
    if (failedCount === 0) {
      ElMessage.success(`成功上传 ${uploadQueue.value.length} 个文件`)
    } else {
      const successCount = uploadQueue.value.length - failedCount
      ElMessage.warning(`上传完成：成功 ${successCount}，失败 ${failedCount}`)
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '文件上传失败')
  } finally {
    uploading.value = false
    if (fileInputRef.value) {
      fileInputRef.value.value = ''
    }
  }
}

const handleFileChange = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const selectedFilesRaw = Array.from(target.files ?? [])
  await runUploadFiles(selectedFilesRaw)
}

function onDragLeave(e: DragEvent) {
  const rel = e.relatedTarget as Node | null
  if (dropZoneRef.value && rel && dropZoneRef.value.contains(rel)) return
  dragOver.value = false
}

async function onDropFiles(e: DragEvent) {
  dragOver.value = false
  if (!folderViewUi.value.can_upload) {
    ElMessage.warning('当前目录不允许上传')
    return
  }
  const list = e.dataTransfer?.files
  if (!list?.length) return
  await runUploadFiles(Array.from(list))
}

const handleDownload = async (fileId: number) => {
  try {
    await downloadFileApi(fileId)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '下载失败')
  }
}

const handleCopyFileToCurrent = async (fileId: number) => {
  try {
    await copyFileApi(fileId, currentFolderId.value ?? null)
    ElMessage.success('已复制到当前目录')
    await loadTree()
    await loadChildren()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '复制失败')
  }
}

async function pasteHere() {
  if (!clipboard.value) return
  try {
    for (const it of clipboard.value.items) {
      if (it.kind === 'file') {
        if (clipboard.value.op === 'copy') {
          await copyFileApi(it.id, currentFolderId.value ?? null)
        } else {
          await moveFileApi(it.id, currentFolderId.value ?? null)
        }
      } else if (clipboard.value.op === 'cut') {
        await moveFolderApi(it.id, currentFolderId.value ?? null)
      }
    }
    ElMessage.success('粘贴完成')
    if (clipboard.value.op === 'cut') {
      clipboard.value = null
    }
    await loadTree()
    await loadChildren()
    clearSelection()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '粘贴失败')
  }
}

const handleBatchDownload = async () => {
  if (selectedFiles.value.length === 0) {
    ElMessage.warning('请选择要下载的文件')
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
    ElMessage.error(error instanceof Error ? error.message : '批量下载失败')
  } finally {
    batchDownloading.value = false
  }
}

async function batchDelete() {
  if (selectedRows.value.length === 0) return
  try {
    await ElMessageBox.confirm(`确定删除选中的 ${selectedRows.value.length} 项吗？`, '确认删除', {
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    for (const r of selectedFiles.value) {
      await deleteFileApi(r.id)
    }
    for (const r of selectedFolders.value) {
      await deleteFolderApi(r.id)
    }
    ElMessage.success('已删除')
    clearSelection()
    await loadTree()
    await loadChildren()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  }
}

function openBatchMove() {
  const files = selectedFiles.value
  if (files.length === 0) {
    ElMessage.warning('批量移动当前仅支持文件')
    return
  }
  if (!files.every((f) => f.can_move)) {
    ElMessage.warning('选中项包含不可移动的文件')
    return
  }
  moveDialogTargetKind.value = 'batch'
  moveDialogTargetId.value = null
  moveBatchFileIds.value = files.map((f) => f.id)
  moveTargetParentId.value = currentFolderId.value
  moveDialogVisible.value = true
}

async function batchCopyToCurrent() {
  const files = selectedFiles.value
  if (files.length === 0 || selectedFolders.value.length > 0) {
    ElMessage.warning('请仅选择文件进行复制')
    return
  }
  try {
    for (const f of files) {
      await copyFileApi(f.id, currentFolderId.value ?? null)
    }
    ElMessage.success('已复制到当前目录')
    await loadTree()
    await loadChildren()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '复制失败')
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
  void (async () => {
    await loadTree()
    await loadChildren()
  })()
  window.addEventListener('click', onGlobalClick)
  window.addEventListener('keydown', onGlobalKey)
})

onUnmounted(() => {
  window.removeEventListener('click', onGlobalClick)
  window.removeEventListener('keydown', onGlobalKey)
})

function onGlobalKey(e: KeyboardEvent) {
  if (e.key === 'Escape') closeCtxMenu()
}

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

watch(
  () => authStore.userId,
  (id) => {
    if (id == null) return
    void loadChildren()
  },
)

function openNewFolderDialog() {
  newFolderDialogName.value = ''
  newFolderDialogVisible.value = true
}

async function submitNewFolderDialog() {
  const name = newFolderDialogName.value.trim()
  if (!name) {
    ElMessage.warning('请输入文件夹名称')
    return
  }
  try {
    const created = await createFolderApi(name, currentFolderId.value)
    ElMessage.success('文件夹创建成功')
    newFolderDialogVisible.value = false
    newFolderDialogName.value = ''
    currentFolderId.value = created.id
    await loadTree()
    await loadChildren()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '创建文件夹失败')
  }
}

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

const goToChatForCurrentFolder = () => {
  const lastCrumb = breadcrumbs.value[breadcrumbs.value.length - 1]
  const currentName =
    currentFolderId.value === null
      ? 'home'
      : (lastCrumb?.name ??
        folderNodeById.value.get(currentFolderId.value!)?.name ??
        `#${currentFolderId.value}`)
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

async function goParent() {
  const rec = currentFolderRecord.value
  if (!rec?.parent_id) {
    currentFolderId.value = null
    await loadChildren()
    return
  }
  const hid = homeRootId.value
  if (hid !== null && rec.parent_id === hid) {
    currentFolderId.value = null
  } else {
    currentFolderId.value = rec.parent_id
  }
  await loadChildren()
}

const enterFolder = async (folderId: number) => {
  searchQ.value = ''
  currentFolderId.value = folderId
  clearSelection()
  await loadChildren()
}

function onNavigatorEnter(folderId: number) {
  void enterFolder(folderId)
}

const goRoot = async () => {
  searchQ.value = ''
  currentFolderId.value = null
  clearSelection()
  await loadChildren()
}

const goToFolder = async (folderId: number) => {
  searchQ.value = ''
  currentFolderId.value = folderId
  clearSelection()
  await loadChildren()
}

const refreshCurrent = async () => {
  await loadChildren()
}

const overallUploadProgress = computed(() => {
  if (uploadQueue.value.length === 0) return 0
  const sum = uploadQueue.value.reduce((acc, item) => acc + item.progress, 0)
  return Math.round(sum / uploadQueue.value.length)
})

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
    ElMessage.error(error instanceof Error ? error.message : '重命名失败')
  }
}

const submitRenameFile = async () => {
  if (renameFileTargetId.value === null) return
  const name = renameFileName.value.trim()
  if (!name) {
    ElMessage.warning('请输入新文件名')
    return
  }
  try {
    await renameFileApi(renameFileTargetId.value, name)
    ElMessage.success('文件重命名成功')
    renameFileDialogVisible.value = false
    renameFileTargetId.value = null
    await loadChildren()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '重命名失败')
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
  moveBatchFileIds.value = []
  moveTargetParentId.value = folderNodeById.value.get(folderId)?.parent_id ?? null
  moveDialogVisible.value = true
}

const openMoveFile = (fileId: number, folderId?: number | null) => {
  moveDialogTargetKind.value = 'file'
  moveDialogTargetId.value = fileId
  moveBatchFileIds.value = []
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
  if (!moveDialogTargetKind.value) return
  try {
    if (moveDialogTargetKind.value === 'folder') {
      if (moveDialogTargetId.value === null) return
      await moveFolderApi(moveDialogTargetId.value, moveTargetParentId.value)
    } else if (moveDialogTargetKind.value === 'file') {
      if (moveDialogTargetId.value === null) return
      await moveFileApi(moveDialogTargetId.value, moveTargetParentId.value)
    } else if (moveDialogTargetKind.value === 'batch') {
      for (const fid of moveBatchFileIds.value) {
        await moveFileApi(fid, moveTargetParentId.value)
      }
    }
    ElMessage.success('移动成功')
    moveDialogVisible.value = false
    moveDialogTargetKind.value = null
    moveDialogTargetId.value = null
    moveBatchFileIds.value = []
    clearSelection()
    await loadTree()
    await loadChildren()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '移动失败')
  }
}

const handleDeleteFolder = async (folderId: number) => {
  try {
    const node = folderNodeById.value.get(folderId)
    if (node?.parent_id === null) {
      ElMessage.error('根目录 home 不允许删除')
      return
    }
    await ElMessageBox.confirm('确定要删除该目录吗？', '确认删除', { type: 'warning' })
    await deleteFolderApi(folderId)
    ElMessage.success('目录删除成功')
    if (currentFolderId.value === folderId) {
      currentFolderId.value = null
    }
    await loadTree()
    await loadChildren()
  } catch (error) {
    const e: unknown = error
    if (e === 'cancel') return
    ElMessage.error(error instanceof Error ? error.message : '目录删除失败')
  }
}

const handleDeleteFile = async (fileId: number) => {
  try {
    await ElMessageBox.confirm('确定要删除该文件吗？', '确认删除', { type: 'warning' })
    await deleteFileApi(fileId)
    ElMessage.success('文件删除成功')
    await loadTree()
    await loadChildren()
  } catch (error) {
    const e: unknown = error
    if (e === 'cancel') return
    ElMessage.error(error instanceof Error ? error.message : '文件删除失败')
  }
}

const openFileMeta = async (fileId: number) => {
  fileMetaDrawerVisible.value = true
  fileMetaLoading.value = true
  fileMeta.value = null
  fileChunkDiag.value = null
  try {
    fileMeta.value = await getFileMetaApi(fileId)
    if (authStore.isRoot) {
      fileChunkDiagLoading.value = true
      try {
        fileChunkDiag.value = await getChunkDiagnosticsApi(fileId)
      } catch {
        fileChunkDiag.value = null
      } finally {
        fileChunkDiagLoading.value = false
      }
    } else {
      fileChunkDiag.value = null
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '获取文件详情失败')
    fileMetaDrawerVisible.value = false
  } finally {
    fileMetaLoading.value = false
  }
}
</script>

<style scoped>
.files-drive-page {
  width: 100%;
  min-width: 0;
}

.files-drive-shell {
  border-radius: var(--ds-radius-lg, 16px);
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  background: var(--ds-surface, #fff);
}

.files-drive-shell :deep(.el-card__body) {
  padding: 24px 28px 28px;
}

.files-list-section-head {
  margin-bottom: 10px;
}

.files-list-section-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ds-text-tertiary, #747775);
}

.files-selection-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  padding: 10px 14px;
  border-radius: var(--ds-radius-md, 12px);
  background: var(--ds-surface-muted, #f0f4f9);
}
.files-no-dl-hint {
  font-size: 12px;
  color: var(--ds-warning-text, #6d4c00);
  margin-bottom: 10px;
  padding: 8px 12px;
  border-radius: var(--ds-radius-md, 12px);
  background: var(--ds-warning-bg, #fff8e1);
}
.files-hidden-input {
  display: none;
}
.files-drop-zone {
  margin-top: 8px;
  border-radius: var(--ds-radius-md, 12px);
  padding: 8px;
  transition: background 0.15s ease;
}
.files-drop-zone-active {
  background: rgba(11, 87, 208, 0.06);
  outline: 1px dashed rgba(11, 87, 208, 0.35);
  outline-offset: 0;
}
.files-drop-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 6px;
}
.files-name-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.files-icon {
  width: 18px;
  height: 18px;
  border-radius: 3px;
  flex-shrink: 0;
}
.files-icon.is-folder {
  background: linear-gradient(145deg, #e8eef7, #d3e3fc);
  box-shadow: inset 0 0 0 1px rgba(11, 87, 208, 0.1);
}
.files-icon.is-file {
  background: linear-gradient(145deg, #f1f3f4, #e8eaed);
  box-shadow: inset 0 0 0 1px var(--ds-line-subtle, #e0e3e7);
}
.files-upload-panel {
  margin-top: 12px;
}
.files-upload-summary {
  margin-bottom: 10px;
}
.files-upload-item {
  margin-bottom: 10px;
}
.files-upload-item-head {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  margin-bottom: 4px;
}
.files-upload-err {
  font-size: 12px;
  color: var(--el-color-danger);
  margin-top: 2px;
}
.files-ctx-menu {
  position: fixed;
  z-index: 5000;
  min-width: 188px;
  padding: 8px;
  background: #fff;
  border: 1px solid var(--ds-line-subtle, #e0e3e7);
  border-radius: var(--ds-radius-md, 12px);
  box-shadow: var(--ds-shadow-popover, 0 8px 24px rgba(0, 0, 0, 0.08));
}
.files-ctx-menu button {
  display: block;
  width: 100%;
  text-align: left;
  padding: 9px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  color: var(--ds-text, #1f1f1f);
}
.files-ctx-menu button:hover:not(:disabled) {
  background: var(--ds-surface-muted, #f0f4f9);
}
.files-ctx-menu button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.files-move-hint {
  margin-bottom: 10px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.files-move-root-btns {
  margin-bottom: 8px;
}
.files-move-tree {
  max-height: 320px;
  overflow: auto;
}
.files-meta-actions {
  margin-top: 16px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
:deep(.files-row-selected > td) {
  background-color: rgba(11, 87, 208, 0.07) !important;
}
:deep(.files-drive-table) {
  border-radius: var(--ds-radius-md, 12px);
}
</style>
