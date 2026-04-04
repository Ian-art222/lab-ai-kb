import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '../views/LoginView.vue'
import HomeView from '../views/HomeView.vue'
import FilesView from '../views/FilesView.vue'
import ChatView from '../views/ChatView.vue'
import UsersView from '../views/UsersView.vue'
import SettingsView from '../views/SettingsView.vue'
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
      meta: { adminOnly: true },
    },
    {
      path: '/settings',
      name: 'settings',
      component: SettingsView,
      meta: { adminOnly: true },
    },
  ],
})

router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()

  if (to.path === '/login') {
    next()
    return
  }

  if (!authStore.isLoggedIn) {
    next('/login')
    return
  }

  if (to.meta.adminOnly && !authStore.isAdmin) {
    next('/')
    return
  }

  next()
})

export default router