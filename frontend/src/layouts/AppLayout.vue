<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import BrandMark from '@/components/BrandMark.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { describeDeviceStatus } from '@/utils/format'
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

watch(
  () => deviceStore.currentId,
  (id) => {
    if (!id) everConnected.value = false
  },
)

const showOffline = computed(
  () => deviceStore.currentId > 0 && pet.socketStatus === 'closed' && everConnected.value,
)
const liveStatus = computed(() =>
  describeDeviceStatus({
    online: pet.online,
    controlState: pet.controlState,
  }),
)
const pageTitle = computed(() => (typeof route.meta.title === 'string' ? route.meta.title : '控制台'))
const initial = computed(() => auth.user?.name?.slice(0, 1) ?? 'A')

const navItems = [
  { path: '/devices', label: '设备' },
  { path: '/console', label: '控制台' },
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
  everConnected.value = false
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
    const prevUid = auth.uid
    await auth.login(username, switchForm.password)
    everConnected.value = false
    pet.reset(prevUid)
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
    // 错误提示由 request 层统一弹出
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
    <header class="top">
      <router-link to="/devices" class="brand" :aria-label="pageTitle">
        <BrandMark :size="27" />
        <strong class="brand-name mono">PET-DOG</strong>
      </router-link>

      <nav class="nav" aria-label="主导航">
        <div class="nav-pill">
          <router-link
            v-for="item in navItems"
            :key="item.path"
            :to="item.path"
            class="nav-item"
            :class="{ active: item.path === '/console' && route.path === '/faces' }"
            active-class="active"
          >
            <span>{{ item.label }}</span>
          </router-link>
        </div>
      </nav>

      <div class="actions">
        <span v-if="mockMode" class="mock mono">MOCK</span>

        <ThemeToggle />

        <el-select
          v-if="deviceStore.devices.length > 0"
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

        <span v-if="deviceStore.current" class="status live" :class="liveStatus.tone">
          {{ liveStatus.label }}
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
      <div v-if="showOffline" class="offline">连接已断开，正在重连…</div>
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
      width="380px"
      class="switch-dialog"
      :close-on-click-modal="!switchLoading"
      :close-on-press-escape="!switchLoading"
      @closed="switchForm.password = ''"
    >
      <div class="switch-body">
        <div class="switch-current">
          <span class="avatar mono">{{ initial }}</span>
          <div class="switch-current-text">
            <strong>{{ auth.user?.name ?? '未登录' }}</strong>
            <span class="mono">@{{ auth.user?.username ?? '--' }}</span>
          </div>
        </div>

        <label class="switch-field">
          <span class="switch-label">账号</span>
          <el-input
            v-model="switchForm.username"
            placeholder="用户名"
            autocomplete="username"
            :disabled="switchLoading"
          />
        </label>

        <label class="switch-field">
          <span class="switch-label">密码</span>
          <el-input
            v-model="switchForm.password"
            type="password"
            show-password
            placeholder="输入密码"
            autocomplete="current-password"
            :disabled="switchLoading"
            @keyup.enter="submitSwitch"
          />
        </label>
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

.top {
  position: relative;
  z-index: 20;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 24px;
  height: 64px;
  flex-shrink: 0;
  padding: 0 36px;
  background: var(--glass-nav);
  border-bottom: 1px solid var(--hair);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  white-space: nowrap;
}

.brand-name {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.16em;
}

.nav {
  display: flex;
  align-items: center;
  min-width: 0;
}

.nav-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--hair);
  background: var(--surface-2);
}

.nav-item {
  display: inline-flex;
  align-items: center;
  height: 30px;
  padding: 0 16px;
  border-radius: var(--radius-pill);
  font-size: 13px;
  font-weight: 500;
  color: var(--dim);
  white-space: nowrap;
  transition:
    color 0.2s var(--ease-out),
    background-color 0.2s var(--ease-out);
}

.nav-item:hover {
  color: var(--ink);
}

.nav-item.active {
  color: var(--btn-primary-ink);
  background: var(--btn-primary-bg);
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mock {
  padding: 3px 7px;
  border: 1px solid var(--hair);
  border-radius: var(--radius-xs);
  font-size: 9px;
  letter-spacing: 0.12em;
  color: var(--faint);
}

.device-select {
  width: 158px;
}

.device-select :deep(.el-select__wrapper) {
  border-radius: var(--radius-pill);
  background: var(--surface-2);
  box-shadow: 0 0 0 1px var(--hair) inset;
  padding: 0 12px;
  min-height: 32px;
}

.device-select :deep(.el-select__selected-item) {
  font-size: 12px;
  color: var(--ink);
}

.option {
  display: flex;
  align-items: center;
  gap: 8px;
}

.live {
  height: 32px;
}

.user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 3px 10px 3px 4px;
  border-radius: var(--radius-pill);
  border: 1px solid var(--hair);
  background: var(--surface-2);
  cursor: pointer;
  outline: none;
  white-space: nowrap;
  transition: border-color 0.18s ease;
}

.user:hover {
  border-color: var(--hair-strong);
}

.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  background: var(--grad-line);
  color: #101214;
  font-size: 11px;
  font-weight: 600;
  border-radius: 50%;
  flex-shrink: 0;
}

.user-name {
  font-size: 12.5px;
  color: var(--ink-2);
}

.caret {
  font-size: 10px;
  color: var(--faint);
}

.offline {
  position: relative;
  z-index: 19;
  padding: 8px 36px;
  background: var(--warn-soft);
  border-bottom: 1px solid var(--warn-border);
  color: var(--warn);
  font-size: 12px;
  font-weight: 500;
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
  border-radius: var(--radius-md);
  background: var(--surface-2);
}

.switch-current .avatar {
  width: 38px;
  height: 38px;
  font-size: 15px;
}

.switch-current-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.switch-current-text strong {
  font-size: 14.5px;
  font-weight: 600;
}

.switch-current-text .mono {
  font-size: 11px;
  color: var(--dim);
}

.switch-label {
  font-size: 12px;
  color: var(--dim);
}

.switch-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

@media (max-width: 1120px) {
  .top {
    gap: 14px;
    padding: 0 20px;
  }

  .mock {
    display: none;
  }
}

@media (max-width: 900px) {
  .top {
    padding: 0 14px;
    gap: 10px;
  }

  .nav-item {
    padding: 0 11px;
    font-size: 12px;
  }

  .device-select,
  .user-name {
    display: none;
  }

  .offline {
    padding: 8px 16px;
  }
}
</style>
