<template>
  <div class="login-page">
    <el-card class="login-card">
      <template #header>
        <div class="login-title">实验室知识库登录</div>
      </template>

      <el-form label-position="top">
        <el-form-item label="用户名">
          <el-input
            v-model="username"
            placeholder="请输入用户名"
            clearable
          />
        </el-form-item>

        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            placeholder="请输入密码"
            show-password
            clearable
          />
        </el-form-item>

        <el-button
  type="primary"
  style="width: 100%"
  :loading="loading"
  @click="handleLogin"
>
  登录
</el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import { loginApi } from '../api/auth'

const router = useRouter()
const authStore = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)

const handleLogin = async () => {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }

  try {
    loading.value = true

    const result = await loginApi({
      username: username.value,
      password: password.value,
    })

    authStore.setAuth(result.access_token, result.username, result.role)

    ElMessage.success('登录成功')
    router.push('/')
  } catch (error) {
    const message = error instanceof Error ? error.message : '登录失败'
    ElMessage.error(message)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f5f7fa;
}

.login-card {
  width: 420px;
}

.login-title {
  font-size: 20px;
  font-weight: 700;
  text-align: center;
}
</style>