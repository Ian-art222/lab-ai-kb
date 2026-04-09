import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import HomeView from '../views/HomeView.vue'
import FilesView from '../views/FilesView.vue'
import ChatView from '../views/ChatView.vue'
import UsersView from '../views/UsersView.vue'
import SettingsView from '../views/SettingsView.vue'
import AdminDiagnosticsView from '../views/AdminDiagnosticsView.vue'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginView,
    },
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/files',
      name: 'files',
      component: FilesView,
    },
    {
      path: '/chat',
      name: 'chat',
      component: ChatView,
    },
    {
      path: '/users',
      name: 'users',
      component: UsersView,
      meta: { requiresUserManager: true },
    },
    {
      path: '/settings',
      name: 'settings',
      component: SettingsView,
      meta: { rootOnly: true },
    },

    {
      path: '/admin/diagnostics',
      name: 'admin-diagnostics',
      component: AdminDiagnosticsView,
      meta: { rootOnly: true },
    },
  ],
})

router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()

  if (to.path === '/login') {
    if (authStore.isLoggedIn) {
      next({ path: '/' })
      return
    }
    next()
    return
  }

  if (!authStore.isLoggedIn) {
    next('/login')
    return
  }

  if (to.meta.requiresUserManager && !authStore.canManageUsers) {
    next('/')
    return
  }

  if (to.meta.rootOnly && !authStore.isRoot) {
    next('/')
    return
  }

  next()
})

export default router