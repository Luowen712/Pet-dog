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
  try {
    await auth.changePassword(passwordForm.old, passwordForm.next)
    pet.reset()
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
  try {
    await auth.deleteAccount(deleteForm.password, deleteForm.username.trim())
    pet.reset()
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
      <div>
        <div class="page-kicker">05 / Account</div>
        <h2 class="page-title">账号</h2>
        <p class="page-sub">密码、会话与账号注销，都只影响当前登录的这个账号</p>
      </div>
    </div>

    <div class="cols">
      <section class="card identity">
        <div class="card-head">
          <span class="card-title">当前账号</span>
          <span class="card-meta mono">UID {{ auth.user?.id ?? '--' }}</span>
        </div>
        <div class="identity-body">
          <span class="avatar mono">{{ auth.user?.name?.slice(0, 1) ?? '?' }}</span>
          <div class="identity-text">
            <strong>{{ auth.user?.name ?? '未登录' }}</strong>
            <span class="mono">@{{ auth.user?.username ?? '--' }}</span>
            <span class="role mono">{{ isAdmin ? 'ADMIN' : 'USER' }}</span>
          </div>
        </div>
        <p class="hint">设备、控制台和会话都按这个账号隔离；换账号不会带走上一个人的设备选择。</p>
      </section>

      <section class="card">
        <div class="card-head">
          <span class="card-title">修改密码</span>
          <span class="card-meta">10–128 位</span>
        </div>
        <div class="form">
          <label class="field">
            <span class="field-label mono">原密码</span>
            <el-input v-model="passwordForm.old" type="password" show-password autocomplete="current-password" />
          </label>
          <label class="field">
            <span class="field-label mono">新密码</span>
            <el-input v-model="passwordForm.next" type="password" show-password autocomplete="new-password" />
          </label>
          <label class="field">
            <span class="field-label mono">确认新密码</span>
            <el-input v-model="passwordForm.confirm" type="password" show-password autocomplete="new-password" />
          </label>
          <p class="hint">修改成功后所有会话立即失效，需要用新密码重新登录。</p>
          <el-button type="primary" :loading="passwordSaving" @click="submitPassword">
            修改密码
          </el-button>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <span class="card-title">会话</span>
          <span class="card-meta">tv + 1</span>
        </div>
        <div class="form">
          <p class="hint">
            退出所有设备上的登录：后端会把 token 版本 +1，其它浏览器、手机和实时连接都会立刻失效。
          </p>
          <el-button :loading="logoutSaving" @click="logoutEverywhere">
            退出所有设备上的登录
          </el-button>
        </div>
      </section>

      <section class="card danger">
        <div class="card-head">
          <span class="card-title">注销账号</span>
          <span class="card-meta mono">IRREVERSIBLE</span>
        </div>
        <div class="form">
          <p class="hint">
            注销后账号立即失效，已绑定的设备会解绑并进入待交接状态。注销不是急停，已经写出去的动作可能还会继续。
          </p>
          <el-button type="danger" plain @click="openDelete">注销账号</el-button>
        </div>
      </section>
    </div>

    <el-dialog v-model="deleteVisible" title="注销账号" width="420px">
      <div class="form">
        <p class="hint">需要同时输入密码和用户名确认。此操作不可撤销。</p>
        <label class="field">
          <span class="field-label mono">密码</span>
          <el-input v-model="deleteForm.password" type="password" show-password />
        </label>
        <label class="field">
          <span class="field-label mono">输入用户名「{{ auth.user?.username }}」</span>
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
  grid-template-columns: minmax(280px, 0.9fr) minmax(0, 1.2fr);
  gap: 16px;
  align-items: start;
}

.identity {
  grid-row: span 2;
}

.identity-body {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px;
}

.avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border: 1px solid var(--hair);
  font-size: 18px;
  color: var(--ink);
}

.identity-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.identity-text strong {
  font-size: 17px;
  font-weight: 500;
}

.identity-text span {
  font-size: 11px;
  color: var(--faint);
}

.role {
  margin-top: 4px;
  letter-spacing: 0.12em;
}

.form {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  padding: 18px 20px 20px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.field-label {
  font-size: 8px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

.hint {
  margin: 0;
  padding: 0 20px;
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--dim);
}

.form .hint {
  padding: 0;
}

.danger {
  border-color: rgba(165, 58, 51, 0.3);
}

.danger .card-title {
  color: var(--danger);
}

@media (max-width: 980px) {
  .cols {
    grid-template-columns: 1fr;
  }

  .identity {
    grid-row: auto;
  }
}
</style>
