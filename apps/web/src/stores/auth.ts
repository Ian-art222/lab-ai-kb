import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type UserRole = 'root' | 'admin' | 'member' | ''

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const username = ref(localStorage.getItem('username') || '')
  const role = ref<UserRole>((localStorage.getItem('role') || '') as UserRole)
  const canDownload = ref(localStorage.getItem('can_download') === 'true')
  /** 登录后由 /users/me 同步，用于私人目录展示名等 */
  const userId = ref<number | null>(null)

  const isLoggedIn = computed(() => !!token.value)
  const isRoot = computed(() => role.value === 'root')
  const isAdmin = computed(() => role.value === 'admin')
  const isMember = computed(() => role.value === 'member')
  const canManageUsers = computed(() => isRoot.value || isAdmin.value)
  const canAccessOpsAndSettings = computed(() => isRoot.value)

  const setAuth = (
    userToken: string,
    userName: string,
    userRole: string,
    userCanDownload?: boolean,
  ) => {
    const cleanToken = userToken.trim()
    token.value = cleanToken
    username.value = userName
    role.value = (userRole || 'member') as UserRole
    const dl =
      userRole === 'root' || userRole === 'admin' ? true : Boolean(userCanDownload)
    canDownload.value = dl

    try {
      localStorage.setItem('token', token.value)
      localStorage.setItem('username', username.value)
      localStorage.setItem('role', role.value)
      localStorage.setItem('can_download', dl ? 'true' : 'false')
    } catch {
      throw new Error(
        '无法写入浏览器本地存储（可能被禁用或已满）。请关闭隐私模式/清理站点数据后重试。',
      )
    }
  }

  const syncFromMe = (me: {
    id?: number
    username: string
    role: string
    can_download: boolean
  }) => {
    if (typeof me.id === 'number') {
      userId.value = me.id
    }
    username.value = me.username
    role.value = (me.role || 'member') as UserRole
    const dl =
      me.role === 'root' || me.role === 'admin' ? true : Boolean(me.can_download)
    canDownload.value = dl
    localStorage.setItem('username', username.value)
    localStorage.setItem('role', role.value)
    localStorage.setItem('can_download', dl ? 'true' : 'false')
  }

  const logout = () => {
    token.value = ''
    username.value = ''
    role.value = ''
    canDownload.value = false
    userId.value = null

    localStorage.removeItem('token')
    localStorage.removeItem('username')
    localStorage.removeItem('role')
    localStorage.removeItem('can_download')
  }

  return {
    token,
    username,
    role,
    userId,
    canDownload,
    isLoggedIn,
    isRoot,
    isAdmin,
    isMember,
    canManageUsers,
    canAccessOpsAndSettings,
    setAuth,
    syncFromMe,
    logout,
  }
})
