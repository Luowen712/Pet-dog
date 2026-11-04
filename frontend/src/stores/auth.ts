import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { User } from '@/types'
import { fetchMe, login as loginApi } from '@/api/auth'
import { clearSession, getStoredUser, getToken, setStoredUser, setToken } from '@/utils/session'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken())
  const user = ref<User | null>(getStoredUser())
  const loading = ref(false)
  const isLoggedIn = computed(() => Boolean(token.value))

  async function login(username: string, password: string): Promise<void> {
    loading.value = true
    try {
      const result = await loginApi(username, password)
      token.value = result.token
      user.value = result.user
      setToken(result.token)
      setStoredUser(result.user)
    } finally {
      loading.value = false
    }
  }

  /** 刷新页面后用 token 换回用户信息；401 由 request 层统一处理 */
  async function refreshMe(): Promise<void> {
    if (!token.value) return
    try {
      const me = await fetchMe()
      user.value = me
      setStoredUser(me)
    } catch {
      // 401 已经跳登录页，这里不用再做什么
    }
  }

  function reset(): void {
    token.value = ''
    user.value = null
    clearSession()
  }

  return { token, user, loading, isLoggedIn, login, refreshMe, reset }
})
