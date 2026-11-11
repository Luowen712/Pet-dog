<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import BrandMark from '@/components/BrandMark.vue'
import { useAuthStore } from '@/stores/auth'
import { useDeviceStore } from '@/stores/device'
import { usePetStore } from '@/stores/pet'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const deviceStore = useDeviceStore()
const pet = usePetStore()

const mockMode = import.meta.env.VITE_USE_MOCK === 'true'
const everConnected = ref(false)

const switchVisible = ref(false)
const switchLoading = ref(false)
const switchForm = reactive({ username: '', password: '' })

watch(
  () => pet.socketStatus,
  (status) => {
    if (status === 'open') everConnected.value = true
  },
)

const showOffline = computed(() => pet.socketStatus === 'closed' && everConnected.value)
const pageTitle = computed(() => (typeof route.meta.title === 'string' ? route.meta.title : '控制台'))
const initial = computed(() => auth.user?.name?.slice(0, 1) ?? 'A')

const navItems = [
  { path: '/devices', label: '设备', icon: 'Monitor' },
  { path: '/console', label: '控制台', icon: 'Odometer' },
  { path: '/faces', label: '表情', icon: 'Sunny' },
  { path: '/account', label: '账号', icon: 'User' },
]

onMounted(async () => {
  await auth.refreshMe()
  if (!auth.uid) return
  deviceStore.bindUser(auth.uid)
  if (!deviceStore.loaded) await deviceStore.load()
  pet.connect(deviceStore.currentId)
})

onBeforeUnmount(() => {
  pet.disconnect()
})

function onDeviceChange(value: number): void {
  deviceStore.select(value)
  pet.connect(value)
}

function onCommand(command: string | number | object): void {
  if (command === 'logout') void logout()
  if (command === 'account') void router.push('/account')
  if (command === 'switch') openSwitch()
}

function openSwitch(): void {
  switchForm.username = ''
  switchForm.password = ''
  switchVisible.value = true
}

async function submitSwitch(): Promise<void> {
  if (switchLoading.value) return
  const username = switchForm.username.trim()
  if (!username || !switchForm.password) {
    ElMessage.warning('请输入要切换的账号和密码')
    return
  }

  switchLoading.value = true
  try {
    // 直接换新 token，不需要先调 logout；旧账号在其它设备上的登录不受影响
    await auth.login(username, switchForm.password)
    pet.reset()
    deviceStore.reset()
    if (auth.uid) {
      deviceStore.bindUser(auth.uid)
      await deviceStore.load()
    }
    pet.connect(deviceStore.currentId)
    switchVisible.value = false
    ElMessage.success(`已切换到 ${auth.user?.name ?? username}`)
    await router.replace('/devices')
  } catch {
    // 登录失败保留原账号，错误提示由 request 层统一弹出
  } finally {
    switchLoading.value = false
  }
}

async function logout(): Promise<void> {
  pet.reset()
  deviceStore.reset()
  await auth.logoutAll()
  void router.replace('/login')
}
</script>

<template>
  <div class="shell">
    <div class="guides" aria-hidden="true">
      <span class="g g17" />
      <span class="g g50" />
      <span class="g g83" />
    </div>

    <header class="top">
      <router-link to="/devices" class="brand" :aria-label="pageTitle">
        <BrandMark :size="27" />
        <span class="brand-text">
          <strong>PET-DOG</strong>
          <em>STM32 COMPANION</em>
        </span>
      </router-link>

      <nav class="nav">
        <router-link
          v-for="(item, index) in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          active-class="active"
        >
          <span class="idx mono">0{{ index + 1 }}</span>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="actions">
        <span v-if="mockMode" class="mock mono">MOCK</span>

        <label v-if="deviceStore.devices.length > 0" class="device">
          <span class="device-label mono">DEVICE</span>
          <el-select
            :model-value="deviceStore.currentId"
            class="device-select"
            size="small"
            @change="onDeviceChange"
          >
            <el-option
              v-for="device in deviceStore.devices"
              :key="device.id"
              :label="device.name"
              :value="device.id"
            >
              <span class="option">
                <span class="dot" :class="{ online: device.online }" />
                {{ device.name }}
              </span>
            </el-option>
          </el-select>
        </label>

        <span class="live" :class="{ on: pet.connected }">
          <span class="dot" :class="{ online: pet.connected }" />
          {{ pet.connected ? 'LIVE' : 'LINK…' }}
        </span>

        <el-dropdown trigger="click" @command="onCommand">
          <span class="user">
            <span class="avatar mono">{{ initial }}</span>
            <span class="user-name">{{ auth.user?.name ?? '未登录' }}</span>
            <el-icon class="caret"><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item disabled>{{ auth.user?.username ?? 'admin' }}</el-dropdown-item>
              <el-dropdown-item divided command="account">账号管理</el-dropdown-item>
              <el-dropdown-item command="switch">切换账号</el-dropdown-item>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </header>

    <transition name="fade">
      <div v-if="showOffline" class="offline mono">
        REALTIME LINK LOST — RECONNECTING
      </div>
    </transition>

    <main class="content">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>

    <el-dialog
      v-model="switchVisible"
      title="切换账号"
      width="400px"
      class="switch-dialog"
      :close-on-click-modal="!switchLoading"
      :close-on-press-escape="!switchLoading"
      @closed="switchForm.password = ''"
    >
      <div class="switch-body">
        <div class="switch-current">
          <span class="avatar mono">{{ initial }}</span>
          <div class="switch-current-text">
            <span class="mono switch-label">当前账号</span>
            <strong>{{ auth.user?.name ?? '未登录' }}</strong>
            <span class="mono">@{{ auth.user?.username ?? '--' }}</span>
          </div>
        </div>

        <label class="switch-field">
          <span class="switch-label mono">新账号</span>
          <el-input
            v-model="switchForm.username"
            placeholder="用户名"
            autocomplete="username"
            :disabled="switchLoading"
          />
        </label>

        <label class="switch-field">
          <span class="switch-label mono">密码</span>
          <el-input
            v-model="switchForm.password"
            type="password"
            show-password
            placeholder="输入新账号密码"
            autocomplete="current-password"
            :disabled="switchLoading"
            @keyup.enter="submitSwitch"
          />
        </label>

        <p class="switch-hint">
          切换后会重新加载新账号的设备和实时连接。旧账号不会被登出，它在其它设备上的登录仍然有效。
        </p>
      </div>

      <template #footer>
        <el-button :disabled="switchLoading" @click="switchVisible = false">取消</el-button>
        <el-button type="primary" :loading="switchLoading" @click="submitSwitch">
          登录并切换
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.shell {
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: transparent;
}

.guides {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}

.g {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--grid);
}

.g17 {
  left: 17%;
}

.g50 {
  left: 50%;
}

.g83 {
  left: 83%;
}

.top {
  position: relative;
  z-index: 20;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 34px;
  height: 64px;
  flex-shrink: 0;
  padding: 0 42px;
  background: rgba(239, 236, 230, 0.86);
  border-bottom: 1px solid var(--hair);
  backdrop-filter: blur(8px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  line-height: 1.1;
}

.brand-text strong {
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.16em;
}

.brand-text em {
  font-family: var(--mono);
  font-style: normal;
  font-size: 8px;
  letter-spacing: 0.14em;
  color: var(--faint);
}

.nav {
  display: flex;
  align-items: center;
  gap: 22px;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
}

.nav::-webkit-scrollbar {
  display: none;
}

.nav-item {
  position: relative;
  display: inline-flex;
  align-items: baseline;
  gap: 5px;
  padding: 6px 0;
  font-size: 12.5px;
  letter-spacing: 0.02em;
  color: var(--dim);
  white-space: nowrap;
  transition: color 0.18s ease;
}

.nav-item .idx {
  font-size: 8px;
  letter-spacing: 0.06em;
  color: var(--faint);
}

.nav-item:hover {
  color: var(--ink);
}

.nav-item.active {
  color: var(--ink);
}

.nav-item.active::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: var(--grad-line);
}

.actions {
  display: flex;
  align-items: center;
  gap: 18px;
}

.mock {
  padding: 2px 6px;
  border: 1px solid var(--hair);
  font-size: 8px;
  letter-spacing: 0.14em;
  color: var(--faint);
}

.device {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.device-label {
  font-size: 8px;
  letter-spacing: 0.14em;
  color: var(--faint);
}

.device-select {
  width: 168px;
}

.device-select :deep(.el-select__wrapper) {
  box-shadow: none;
  background: transparent;
  padding: 0;
  min-height: 20px;
}

.device-select :deep(.el-select__wrapper:hover) {
  box-shadow: none;
}

.device-select :deep(.el-select__selected-item) {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.02em;
  color: var(--ink);
}

.option {
  display: flex;
  align-items: center;
  gap: 8px;
}

.live {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  color: var(--faint);
}

.live.on {
  color: var(--ok);
}

.user {
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  outline: none;
}

.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 25px;
  height: 25px;
  background: var(--ink);
  color: var(--paper);
  font-size: 11px;
  border-radius: var(--radius);
}

.user-name {
  font-size: 12px;
  color: var(--dim);
}

.caret {
  font-size: 10px;
  color: var(--faint);
}

.offline {
  position: relative;
  z-index: 19;
  padding: 7px 42px;
  background: #f4e6cf;
  border-bottom: 1px solid rgba(20, 20, 20, 0.1);
  color: #6d4a12;
  font-size: 9.5px;
  letter-spacing: 0.12em;
}

.content {
  position: relative;
  z-index: 1;
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

.switch-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.switch-current {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--hair-soft);
  background: rgba(247, 244, 238, 0.6);
}

.switch-current .avatar {
  width: 40px;
  height: 40px;
  font-size: 16px;
}

.switch-current-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.switch-current-text strong {
  font-size: 15px;
  font-weight: 500;
}

.switch-current-text .mono {
  font-size: 9px;
  color: var(--faint);
}

.switch-label {
  font-size: 8px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

.switch-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.switch-hint {
  margin: 0;
  font-size: 11px;
  line-height: 1.65;
  color: var(--dim);
}

@media (max-width: 1180px) {
  .top {
    gap: 22px;
    padding: 0 28px;
  }

  .nav {
    gap: 16px;
  }

  .brand-text em {
    display: none;
  }

  .mock {
    display: none;
  }
}

@media (max-width: 900px) {
  .guides {
    display: none;
  }

  .top {
    grid-template-columns: auto 1fr;
    gap: 14px;
    padding: 0 16px;
  }

  .nav {
    display: none;
  }

  .actions {
    justify-self: end;
    gap: 12px;
  }

  .device-select {
    width: 138px;
  }

  .device-label,
  .user-name,
  .live {
    display: none;
  }

  .offline {
    padding: 7px 16px;
  }

  .page {
    padding: 20px 16px 56px;
  }
}
</style>
