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
            <el-button v-if="authStore.isAdmin" type="primary" @click="openCreateDialog">
              新建用户
            </el-button>
          </div>
        </template>

        <el-result
          v-if="!authStore.isAdmin"
          icon="warning"
          title="无权限访问"
          sub-title="只有管理员可以查看和维护用户列表。"
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
            <el-table-column label="角色" width="120">
              <template #default="scope">
                <el-tag :type="scope.row.role === 'admin' ? 'danger' : 'warning'">
                  {{ scope.row.role === 'admin' ? '管理员' : '成员' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="scope">
                <el-switch
                  :model-value="scope.row.is_active"
                  @change="(value: string | number | boolean) => handleStatusChange(scope.row.id, Boolean(value))"
                />
              </template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" width="180" />
            <el-table-column prop="last_login_at" label="最近登录" width="180" />
            <el-table-column label="操作" width="220">
              <template #default="scope">
                <div class="row-actions">
                  <el-button link type="primary" @click="openEditDialog(scope.row)">编辑</el-button>
                  <el-button link type="warning" @click="openResetPasswordDialog(scope.row)">重置密码</el-button>
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
              <el-option label="管理员" value="admin" />
            </el-select>
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
          <el-form-item label="角色">
            <el-select v-model="editForm.role" style="width: 100%">
              <el-option label="成员" value="member" />
              <el-option label="管理员" value="admin" />
            </el-select>
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
} from '../api/users'

const authStore = useAuthStore()
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
  role: 'member' as 'admin' | 'member',
  is_active: true,
})

const editForm = reactive({
  username: '',
  role: 'member' as 'admin' | 'member',
})

const loadUsers = async () => {
  if (!authStore.isAdmin) return
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
  editVisible.value = true
}

const handleUpdateUser = async () => {
  if (currentUserId.value === null) return
  try {
    await updateUserApi(currentUserId.value, editForm)
    ElMessage.success('用户更新成功')
    editVisible.value = false
    await loadUsers()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新失败')
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
.users-page { display: flex; flex-direction: column; gap: 16px; }
.page-card { border-radius: var(--card-radius); }
.page-header { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
.page-title { font-size: 22px; font-weight: 700; color: var(--text-primary); }
.page-subtitle { color: var(--text-secondary); margin-top: 6px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; }
.row-actions { display: flex; gap: 10px; }
</style>