<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormItemRule, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import BrandMark from '@/components/BrandMark.vue'
import RobotDog from '@/components/RobotDog.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const mockMode = import.meta.env.VITE_USE_MOCK === 'true'
const formRef = ref<FormInstance>()
const isRegister = ref(false)
const celebrating = ref(false)
let celebrateTimer: number | null = null

const form = reactive({ username: '', password: '', confirm: '' })

const confirmRule: FormItemRule = {
  trigger: 'blur',
  validator: (_rule, value, callback) => {
    if (!value) {
      callback(new Error('请再次输入密码'))
    } else if (value !== form.password) {
      callback(new Error('两次输入的密码不一致'))
    } else {
      callback()
    }
  },
}

const rules = computed<FormRules>(() => ({
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    ...(isRegister.value
      ? [{ min: 3, max: 20, message: '用户名 3–20 个字符', trigger: 'blur' }]
      : []),
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    ...(isRegister.value
      ? [{ min: 10, max: 128, message: '密码需要 10–128 位', trigger: 'blur' }]
      : []),
  ],
  confirm: isRegister.value ? [confirmRule] : [],
}))

function celebrate(): void {
  celebrating.value = true
  if (celebrateTimer !== null) window.clearTimeout(celebrateTimer)
  celebrateTimer = window.setTimeout(() => {
    celebrating.value = false
    celebrateTimer = null
  }, 1600)
}

function switchMode(register: boolean): void {
  if (isRegister.value === register) return
  isRegister.value = register
  form.confirm = ''
  formRef.value?.clearValidate()
}

function fillDemo(): void {
  form.username = 'admin'
  form.password = 'admin123'
}

function safeRedirect(raw: unknown): string {
  if (typeof raw === 'string' && raw.startsWith('/') && !raw.startsWith('//')) {
    return raw
  }
  return '/devices'
}

async function onSubmit(): Promise<void> {
  if (!formRef.value || auth.loading) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  if (isRegister.value) {
    try {
      await auth.register(form.username.trim(), form.password)
      ElMessage.success('注册成功，用新账号登录即可')
      celebrate()
      isRegister.value = false
      form.password = ''
      form.confirm = ''
      formRef.value.clearValidate()
    } catch {
      // 错误提示由 request 层统一弹出
    }
    return
  }

  try {
    await auth.login(form.username, form.password)
    celebrate()
    ElMessage.success('登录成功')
    await new Promise((resolve) => window.setTimeout(resolve, 1200))
    await router.replace(safeRedirect(route.query.redirect))
  } catch {
    // 错误提示由 request 层统一弹出
  }
}

onBeforeUnmount(() => {
  if (celebrateTimer !== null) window.clearTimeout(celebrateTimer)
})
</script>

<template>
  <div class="login">
    <header class="login-top">
      <div class="brand">
        <BrandMark :size="26" />
        <span class="word mono">PET-DOG</span>
      </div>
      <ThemeToggle />
    </header>

    <main class="login-main">
      <section class="intro">
        <div class="title-stack">
          <div class="title-box cut">
            <span>DESKTOP</span>
          </div>
          <div class="title-box">
            <span>PET</span>
          </div>
        </div>

        <div class="dog-wrap">
          <RobotDog :celebrating="celebrating" class="dog" />
        </div>
      </section>

      <section class="access">
        <div class="card access-box">
          <h1>{{ isRegister ? '注册账号' : '登录控制台' }}</h1>

          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            :validate-on-rule-change="false"
            size="large"
            class="form"
            @submit.prevent="onSubmit"
          >
            <el-form-item prop="username" class="field-item">
              <div class="field">
                <span class="field-label">用户名</span>
                <el-input
                  v-model="form.username"
                  :placeholder="isRegister ? '3–20 个字符' : '输入用户名'"
                  autocomplete="username"
                />
              </div>
            </el-form-item>

            <el-form-item prop="password" class="field-item">
              <div class="field">
                <span class="field-label">密码</span>
                <el-input
                  v-model="form.password"
                  type="password"
                  :placeholder="isRegister ? '10–128 位' : '输入密码'"
                  show-password
                  autocomplete="current-password"
                />
              </div>
            </el-form-item>

            <el-form-item v-if="isRegister" prop="confirm" class="field-item">
              <div class="field">
                <span class="field-label">确认密码</span>
                <el-input
                  v-model="form.confirm"
                  type="password"
                  placeholder="再次输入密码"
                  show-password
                  autocomplete="new-password"
                />
              </div>
            </el-form-item>

            <el-button
              type="primary"
              native-type="submit"
              class="submit"
              :loading="auth.loading"
            >
              <span>{{ isRegister ? '创建账号' : '进入控制台' }}</span>
              <span class="arrow mono">↗</span>
            </el-button>
          </el-form>

          <div class="switch">
            <span class="switch-text">{{ isRegister ? '已经有账号？' : '还没有账号？' }}</span>
            <el-link
              type="primary"
              underline="never"
              class="switch-link"
              @click="switchMode(!isRegister)"
            >
              {{ isRegister ? '返回登录' : '注册' }}
            </el-link>
          </div>

          <div v-if="mockMode && !isRegister" class="demo">
            <span class="mono">admin / admin123</span>
            <el-link type="primary" underline="never" class="fill" @click="fillDemo">
              一键填入
            </el-link>
          </div>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.login {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  overflow: hidden;
}

.login-top {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 36px;
  border-bottom: 1px solid var(--hair);
  background: var(--glass-nav);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.word {
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.16em;
}

.login-main {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(340px, 0.74fr);
  gap: 56px;
  align-items: center;
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 36px 36px 32px;
  flex: 1;
}

.intro {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 18px;
  min-width: 0;
}

.title-stack {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.title-box {
  display: block;
  width: max-content;
  max-width: 100%;
  padding: 3px 20px 5px;
  border: 2px solid transparent;
  background:
    linear-gradient(var(--paper), var(--paper)) padding-box,
    var(--grad-line) border-box;
}

.title-box span {
  display: block;
  font-size: clamp(40px, 5vw, 78px);
  font-weight: 600;
  line-height: 1.02;
  letter-spacing: -0.04em;
}

.title-box.cut {
  clip-path: polygon(
    0 0,
    100% 0,
    100% calc(100% - 22px),
    calc(100% - 22px) 100%,
    0 100%
  );
}

.title-box.cut span {
  padding-right: 6px;
}

.dog-wrap {
  width: 100%;
  max-width: 400px;
}

.dog {
  max-width: 400px;
}

.access {
  min-width: 0;
}

.access-box {
  position: relative;
  z-index: 1;
  padding: 28px 28px 24px;
}

.access-box h1 {
  margin-bottom: 22px;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.02em;
}

.field-item {
  margin-bottom: 18px;
}

.field-item :deep(.el-form-item__content) {
  display: block;
  line-height: normal;
}

.field-item :deep(.el-form-item__error) {
  position: static;
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.45;
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

.submit {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 44px;
  margin-top: 8px;
  padding: 0 16px;
  background: var(--grad-line);
  border-color: transparent;
  color: #101214;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.submit:hover {
  background: var(--grad-line);
  border-color: transparent;
  color: #101214;
  filter: brightness(1.06);
}

.arrow {
  position: absolute;
  right: 16px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 14px;
}

.switch {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 16px;
  font-size: 12px;
  color: var(--dim);
}

.switch-text {
  color: var(--dim);
}

.switch-link {
  font-size: 12px;
}

.demo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--hair);
  font-size: 11.5px;
  color: var(--dim);
}

.fill {
  font-size: 12px;
}

@media (max-width: 960px) {
  .login-top {
    padding: 0 18px;
  }

  .login-main {
    grid-template-columns: 1fr;
    gap: 30px;
    padding: 24px 18px 34px;
  }

  .title-box span {
    font-size: clamp(36px, 12vw, 60px);
  }

  .dog {
    max-width: 300px;
  }
}
</style>
