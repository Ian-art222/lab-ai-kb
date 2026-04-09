<template>
  <div class="login-page">
    <el-card class="login-card">
      <template #header>
        <div class="login-title">知识库登录</div>
      </template>

      <!-- el-form 自身会渲染 <form>，外层禁止再包 form，否则嵌套 form 无效且 Enter 提交可能绕过外层 @submit.prevent，导致整页刷新 -->
      <el-form label-position="top" @submit.prevent="handleLogin">
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
          native-type="submit"
          :loading="loading"
        >
          登录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { loginApi } from '../api/auth'

const authStore = useAuthStore()
const router = useRouter()

const username = ref('')
const password = ref('')
const loading = ref(false)

const handleLogin = async () => {
  if (loading.value) {
    return
  }
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

    authStore.setAuth(
      result.access_token,
      result.username,
      result.role,
      result.can_download,
    )

    ElMessage.success('登录成功')
    // SPA 内跳转：token 已在 Pinia + localStorage，避免整页刷新与并发 /me、/dashboard 请求竞态
    await router.replace({ path: '/' })
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
  padding: 24px;
  background: var(--ds-page-bg, #f0f4f9);
}

.login-card {
  width: 100%;
  max-width: 420px;
  border-radius: var(--ds-radius-lg, 16px);
  box-shadow: var(--ds-shadow-float, 0 4px 12px rgba(0, 0, 0, 0.05));
}

.login-title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: -0.02em;
  text-align: center;
  color: var(--ds-text, #1f1f1f);
}
</style>