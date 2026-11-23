<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useDeviceStore } from '@/stores/device'
import { usePetStore } from '@/stores/pet'

const router = useRouter()
const auth = useAuthStore()
const deviceStore = useDeviceStore()
const pet = usePetStore()

const passwordForm = reactive({ old: '', next: '', confirm: '' })
const passwordSaving = ref(false)
const logoutSaving = ref(false)
const deleteVisible = ref(false)
const deleting = ref(false)
const deleteForm = reactive({ password: '', username: '' })

const isAdmin = computed(() => auth.user?.role === 'admin')

async function submitPassword(): Promise<void> {
  if (passwordSaving.value) return
  if (!passwordForm.old) {
    ElMessage.warning('请输入原密码')
    return
  }
  if (passwordForm.next.length < 10 || passwordForm.next.length > 128) {
    ElMessage.warning('新密码需要 10–128 位')
    return
  }
  if (passwordForm.next !== passwordForm.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  passwordSaving.value = true
  const oldUid = auth.uid
  try {
    await auth.changePassword(passwordForm.old, passwordForm.next)
    pet.reset(oldUid)
    deviceStore.reset()
    ElMessage.success('密码已修改，请用新密码重新登录')
    await router.replace('/login')
  } catch {
    // 错误提示由 request 层统一处理
  } finally {
    passwordSaving.value = false
  }
}

async function logoutEverywhere(): Promise<void> {
  if (logoutSaving.value) return
  try {
    await ElMessageBox.confirm(
      '所有设备上的登录都会失效，包括当前浏览器。确定退出吗？',
      '退出所有设备上的登录',
      { type: 'warning', confirmButtonText: '全部退出', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  logoutSaving.value = true
  try {
    pet.reset()
    deviceStore.reset()
    await auth.logoutAll()
    ElMessage.success('已退出所有会话')
    await router.replace('/login')
  } finally {
    logoutSaving.value = false
  }
}

async function openDelete(): Promise<void> {
  deleteForm.password = ''
  deleteForm.username = ''
  deleteVisible.value = true
}

async function confirmDelete(): Promise<void> {
  if (deleting.value) return
  if (!deleteForm.password || !deleteForm.username) {
    ElMessage.warning('请输入密码和用户名')
    return
  }
  if (deleteForm.username.trim() !== auth.user?.username) {
    ElMessage.warning('用户名不一致')
    return
  }
  try {
    await ElMessageBox.confirm(
      '账号会立即失效，绑定的设备会解绑。这个操作不可撤销，确定注销吗？',
      '注销账号',
      { type: 'error', confirmButtonText: '确认注销', cancelButtonText: '取消' },
    )
  } catch {
    return
  }

  deleting.value = true
  const oldUid = auth.uid
  try {
    await auth.deleteAccount(deleteForm.password, deleteForm.username.trim())
    pet.reset(oldUid)
    deviceStore.reset()
    deleteVisible.value = false
    ElMessage.success('账号已注销')
    await router.replace('/login')
  } catch {
    // 错误提示由 request 层统一处理
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2 class="page-title">账号</h2>
    </div>

    <div class="cols">
      <section class="card identity">
        <div class="identity-body">
          <div class="orbital-avatar">
            <span class="avatar mono">{{ auth.user?.name?.slice(0, 1) ?? '?' }}</span>
          </div>
          <div class="identity-text">
            <strong>{{ auth.user?.name ?? '未登录' }}</strong>
            <span class="mono">@{{ auth.user?.username ?? '--' }}</span>
            <span class="role">{{ isAdmin ? '管理员' : '普通用户' }}</span>
          </div>
          <div v-if="deviceStore.current" class="identity-device">
            <span>绑定设备</span>
            <strong>{{ deviceStore.current.name }}</strong>
          </div>
        </div>
      </section>

      <div class="forms-stack">
        <section class="card">
          <div class="card-head">
            <span class="card-title">修改密码</span>
          </div>
          <div class="form">
            <label class="field">
              <span class="field-label">原密码</span>
              <el-input
                v-model="passwordForm.old"
                type="password"
                show-password
                autocomplete="current-password"
              />
            </label>
            <label class="field">
              <span class="field-label">新密码</span>
              <el-input
                v-model="passwordForm.next"
                type="password"
                show-password
                placeholder="10–128 位"
                autocomplete="new-password"
              />
            </label>
            <label class="field">
              <span class="field-label">确认新密码</span>
              <el-input
                v-model="passwordForm.confirm"
                type="password"
                show-password
                autocomplete="new-password"
              />
            </label>
            <el-button type="primary" :loading="passwordSaving" @click="submitPassword">
              修改密码
            </el-button>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <span class="card-title">登录会话</span>
          </div>
          <div class="form">
            <p class="hint">使当前账号在所有设备上的登录立即失效。</p>
            <el-button :loading="logoutSaving" @click="logoutEverywhere">
              退出所有设备上的登录
            </el-button>
          </div>
        </section>

        <section class="card danger">
          <div class="card-head">
            <span class="card-title">注销账号</span>
          </div>
          <div class="form">
            <p class="hint">注销不可撤销，已绑定的设备会自动解绑。</p>
            <el-button type="danger" plain @click="openDelete">注销账号</el-button>
          </div>
        </section>
      </div>
    </div>

    <el-dialog v-model="deleteVisible" title="注销账号" width="400px">
      <div class="form dialog-form">
        <label class="field">
          <span class="field-label">密码</span>
          <el-input v-model="deleteForm.password" type="password" show-password />
        </label>
        <label class="field">
          <span class="field-label">输入用户名「{{ auth.user?.username }}」确认</span>
          <el-input v-model="deleteForm.username" autocomplete="off" />
        </label>
      </div>
      <template #footer>
        <el-button @click="deleteVisible = false">取消</el-button>
        <el-button type="danger" :loading="deleting" @click="confirmDelete">确认注销</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.cols {
  display: grid;
  grid-template-columns: minmax(280px, 0.85fr) minmax(0, 1.15fr);
  gap: 18px;
  align-items: start;
}

.identity {
  background: var(--bg-stage);
}

.identity-body {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 14px;
  padding: 28px 24px;
}

.orbital-avatar {
  position: relative;
  width: 88px;
  height: 88px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.orbital-avatar::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1.5px dashed var(--accent-border);
  animation: orbitSpin 18s linear infinite;
}

@keyframes orbitSpin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: var(--grad-line);
  font-size: 24px;
  font-weight: 600;
  color: #101214;
}

.identity-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.identity-text strong {
  font-size: 19px;
  font-weight: 600;
}

.identity-text span {
  font-size: 12px;
  color: var(--dim);
}

.role {
  margin-top: 2px;
  color: var(--ink-2);
}

.identity-device {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 6px;
  padding-top: 14px;
  border-top: 1px solid var(--hair-soft);
  font-size: 12.5px;
}

.identity-device span {
  color: var(--dim);
}

.forms-stack {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.form {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 13px;
  padding: 18px 20px 20px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.field-label {
  font-size: 12px;
  color: var(--dim);
}

.dialog-form {
  padding: 0;
}

.hint {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--dim);
}

.danger {
  border-color: var(--danger-border);
}

.danger .card-title {
  color: var(--danger);
}

@media (max-width: 960px) {
  .cols {
    grid-template-columns: 1fr;
  }
}
</style>
