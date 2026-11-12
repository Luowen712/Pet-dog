import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { User } from '@/types'
import {
  changePassword as changePasswordApi,
  deleteAccount as deleteAccountApi,
  fetchMe,
  login as loginApi,
  logoutAll as logoutAllApi,
  register as registerApi,
} from '@/api/auth'
import { bumpEpoch } from '@/utils/epoch'
import { clearSession, getStoredUser, getToken, setStoredUser, setToken } from '@/utils/session'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken())
  const user = ref<User | null>(getStoredUser())
  const loading = ref(false)
  const isLoggedIn = computed(() => Boolean(token.value))
  const uid = computed(() => user.value?.id ?? null)

  async function login(username: string, password: string): Promise<void> {
    loading.value = true
    try {
      const result = await loginApi(username, password)
      // 登录成功后才切换会话代次：失败时保留当前账号，切换账号弹窗不会把原会话弄坏
      bumpEpoch()
      token.value = result.token
      user.value = result.user
      setToken(result.token)
      setStoredUser(result.user)
    } finally {
      loading.value = false
    }
  }

  /** 注册只建账号，不直接登录；注册完回到登录页用新账号登 */
  async function register(username: string, password: string): Promise<User> {
    loading.value = true
    try {
      return await registerApi(username, password)
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

  /** 退出所有设备上的登录，然后清本地状态 */
  async function logoutAll(): Promise<void> {
    try {
      await logoutAllApi()
    } finally {
      reset()
    }
  }

  async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
    await changePasswordApi(oldPassword, newPassword)
    // 只有后端确认改密成功（tv+1）后才需要重新登录；失败时保留当前会话
    reset()
  }

  async function deleteAccount(password: string, confirmUsername: string): Promise<void> {
    await deleteAccountApi(password, confirmUsername)
    reset()
  }

  function reset(): void {
    bumpEpoch()
    token.value = ''
    user.value = null
    clearSession()
  }

  return {
    token,
    user,
    uid,
    loading,
    isLoggedIn,
    login,
    register,
    refreshMe,
    logoutAll,
    changePassword,
    deleteAccount,
    reset,
  }
})
