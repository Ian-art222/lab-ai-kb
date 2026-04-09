<template>
  <AdminLayout>
    <div class="users-page">
      <el-card class="page-card">
        <template #header>
          <div class="page-header">
            <div>
              <div class="page-title">用户管理</div>
              <div class="page-subtitle">创建成员账号，调整角色，并维护实验室访问权限。</div>
            </div>
            <el-button v-if="authStore.canManageUsers" type="primary" @click="openCreateDialog">
              新建用户
            </el-button>
          </div>
        </template>

        <el-result
          v-if="!authStore.canManageUsers"
          icon="warning"
          title="无权限访问"
          sub-title="仅 root 或业务管理员可以查看用户列表。"
        />

        <template v-else>
          <div class="toolbar">
            <el-input
              v-model="searchQ"
              placeholder="搜索用户名"
              clearable
              style="width: 280px"
              @keyup.enter="loadUsers"
            />
            <el-button @click="loadUsers">搜索</el-button>
          </div>

          <el-table :data="users" v-loading="loading" style="width: 100%">
            <el-table-column prop="username" label="用户名" />
            <el-table-column label="角色" width="140">
              <template #default="scope">
                <el-tag
                  :type="
                    scope.row.role === 'root'
                      ? 'danger'
                      : scope.row.role === 'admin'
                        ? 'warning'
                        : 'info'
                  "
                >
                  {{
                    scope.row.role === 'root'
                      ? '超级管理员'
                      : scope.row.role === 'admin'
                        ? '管理员'
                        : '成员'
                  }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="可下载" width="100">
              <template #default="scope">
                <template v-if="scope.row.role === 'member'">
                  <el-tag :type="scope.row.can_download ? 'success' : 'info'" size="small">
                    {{ scope.row.can_download ? '是' : '否' }}
                  </el-tag>
                </template>
                <span v-else class="cell-dash">—</span>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="scope">
                <el-switch
                  :disabled="!rowOperable(scope.row)"
                  :model-value="scope.row.is_active"
                  @change="(value: string | number | boolean) => handleStatusChange(scope.row.id, Boolean(value))"
                />
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="180" />
            <el-table-column prop="last_login_at" label="最近登录" width="180" />
            <el-table-column label="操作" width="280">
              <template #default="scope">
                <div class="row-actions">
                  <el-button
                    v-if="rowOperable(scope.row)"
                    link
                    type="primary"
                    @click="openEditDialog(scope.row)"
                  >
                    编辑
                  </el-button>
                  <el-switch
                    v-if="canAdjustDownload(scope.row)"
                    :model-value="scope.row.can_download"
                    size="small"
                    inline-prompt
                    active-text="下载开"
                    inactive-text="下载关"
                    @change="(v: string | number | boolean) => handleDownloadToggle(scope.row, Boolean(v))"
                  />
                  <el-button
                    v-if="rowOperable(scope.row)"
                    link
                    type="warning"
                    @click="openResetPasswordDialog(scope.row)"
                  >
                    重置密码
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-if="!loading && users.length === 0" description="暂无用户数据" />
        </template>
      </el-card>

      <el-dialog v-model="createVisible" title="新建用户" width="460px">
        <el-form label-position="top">
          <el-form-item label="用户名">
            <el-input v-model="createForm.username" />
          </el-form-item>
          <el-form-item label="初始密码">
            <el-input v-model="createForm.password" type="password" show-password />
          </el-form-item>
          <el-form-item label="角色">
            <el-select v-model="createForm.role" style="width: 100%">
              <el-option label="成员" value="member" />
              <el-option v-if="authStore.isRoot" label="管理员" value="admin" />
              <el-option v-if="authStore.isRoot" label="超级管理员" value="root" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="createForm.role === 'member'" label="允许下载">
            <el-switch v-model="createForm.can_download" />
          </el-form-item>
          <el-form-item label="启用账号">
            <el-switch v-model="createForm.is_active" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="createVisible = false">取消</el-button>
          <el-button type="primary" @click="handleCreateUser">创建</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="editVisible" title="编辑用户" width="460px">
        <el-form label-position="top">
          <el-form-item label="用户名">
            <el-input v-model="editForm.username" />
          </el-form-item>
          <el-form-item v-if="authStore.isRoot" label="角色">
            <el-select v-model="editForm.role" style="width: 100%">
              <el-option label="成员" value="member" />
              <el-option label="管理员" value="admin" />
              <el-option label="超级管理员" value="root" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="editForm.role === 'member'" label="允许下载">
            <el-switch v-model="editForm.can_download" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editVisible = false">取消</el-button>
          <el-button type="primary" @click="handleUpdateUser">保存</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="resetVisible" title="重置密码" width="420px">
        <el-form label-position="top">
          <el-form-item label="新密码">
            <el-input v-model="resetPassword" type="password" show-password />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="resetVisible = false">取消</el-button>
          <el-button type="warning" @click="handleResetPassword">确认重置</el-button>
        </template>
      </el-dialog>
    </div>
  </AdminLayout>
</template>

<script setup lang="ts">
import AdminLayout from '../layouts/AdminLayout.vue'
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import {
  createUserApi,
  getUsersApi,
  resetUserPasswordApi,
  updateUserApi,
  updateUserStatusApi,
  type UserItem,
  type UserUpdatePayload,
} from '../api/users'

const authStore = useAuthStore()

const rowOperable = (user: UserItem) => {
  if (authStore.isRoot) return true
  if (authStore.isAdmin) return user.role === 'member'
  return false
}

const canAdjustDownload = (user: UserItem) =>
  rowOperable(user) && user.role === 'member'
const loading = ref(false)
const searchQ = ref('')
const users = ref<UserItem[]>([])

const createVisible = ref(false)
const editVisible = ref(false)
const resetVisible = ref(false)
const currentUserId = ref<number | null>(null)
const resetPassword = ref('')

const createForm = reactive({
  username: '',
  password: '',
  role: 'member' as UserItem['role'],
  is_active: true,
  can_download: false,
})

const editForm = reactive({
  username: '',
  role: 'member' as UserItem['role'],
  can_download: false,
})

const loadUsers = async () => {
  if (!authStore.canManageUsers) return
  try {
    loading.value = true
    users.value = await getUsersApi(searchQ.value.trim() || undefined)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载用户失败')
  } finally {
    loading.value = false
  }
}

const openCreateDialog = () => {
  createForm.username = ''
  createForm.password = ''
  createForm.role = 'member'
  createForm.is_active = true
  createForm.can_download = false
  createVisible.value = true
}

const handleCreateUser = async () => {
  try {
    await createUserApi(createForm)
    ElMessage.success('用户创建成功')
    createVisible.value = false
    await loadUsers()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '用户创建失败')
  }
}

const openEditDialog = (user: UserItem) => {
  currentUserId.value = user.id
  editForm.username = user.username
  editForm.role = user.role
  editForm.can_download = Boolean(user.can_download)
  editVisible.value = true
}

const handleUpdateUser = async () => {
  if (currentUserId.value === null) return
  try {
    const payload: UserUpdatePayload = {
      username: editForm.username.trim(),
    }
    if (authStore.isRoot) {
      payload.role = editForm.role
    }
    if (editForm.role === 'member') {
      payload.can_download = editForm.can_download
    }
    await updateUserApi(currentUserId.value, payload)
    ElMessage.success('用户更新成功')
    editVisible.value = false
    await loadUsers()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新失败')
  }
}

const handleDownloadToggle = async (user: UserItem, enabled: boolean) => {
  try {
    await updateUserApi(user.id, { can_download: enabled })
    ElMessage.success(enabled ? '已开启下载权限' : '已关闭下载权限')
    await loadUsers()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新下载权限失败')
    await loadUsers()
  }
}

const handleStatusChange = async (userId: number, isActive: boolean) => {
  try {
    await updateUserStatusApi(userId, isActive)
    ElMessage.success(isActive ? '用户已启用' : '用户已禁用')
    await loadUsers()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '状态更新失败')
    await loadUsers()
  }
}

const openResetPasswordDialog = (user: UserItem) => {
  currentUserId.value = user.id
  resetPassword.value = ''
  resetVisible.value = true
}

const handleResetPassword = async () => {
  if (currentUserId.value === null) return
  try {
    await resetUserPasswordApi(currentUserId.value, resetPassword.value)
    ElMessage.success('密码重置成功')
    resetVisible.value = false
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '密码重置失败')
  }
}

loadUsers()
</script>

<style scoped>
.users-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.page-card {
  border-radius: var(--ds-radius-lg, 16px);
}
.page-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: flex-start;
}
.page-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--ds-text, #1f1f1f);
}
.page-subtitle {
  color: var(--ds-text-secondary, #444746);
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.5;
  max-width: 520px;
}
.toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.row-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.cell-dash {
  color: var(--ds-text-tertiary, #747775);
  font-size: 13px;
}
</style>