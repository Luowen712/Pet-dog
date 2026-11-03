import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    redirect: '/devices',
    children: [
      {
        path: 'devices',
        name: 'devices',
        component: () => import('@/views/DeviceList.vue'),
        meta: { title: '设备' },
      },
      {
        path: 'console',
        name: 'console',
        component: () => import('@/views/Console.vue'),
        meta: { title: '控制台' },
      },
      {
        path: 'logs',
        name: 'logs',
        component: () => import('@/views/Logs.vue'),
        meta: { title: '指令日志' },
      },
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '数据看板' },
      },
      {
        path: 'faces',
        name: 'faces',
        component: () => import('@/views/Faces.vue'),
        meta: { title: '表情库' },
      },
      {
        path: 'scenes',
        name: 'scenes',
        component: () => import('@/views/Scenes.vue'),
        meta: { title: '场景编排' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/devices' },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.public !== true && !auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && auth.isLoggedIn) {
    return { path: '/devices' }
  }
  return true
})

router.afterEach((to) => {
  const title = typeof to.meta.title === 'string' ? to.meta.title : ''
  document.title = title ? `${title} · Pet-dog 桌宠控制台` : 'Pet-dog 桌宠控制台'
})

export default router
