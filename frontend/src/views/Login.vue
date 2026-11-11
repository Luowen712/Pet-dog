<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormItemRule, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import BrandMark from '@/components/BrandMark.vue'
import RobotDog from '@/components/RobotDog.vue'
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
    ...(isRegister.value ? [{ min: 6, message: '密码至少 6 位', trigger: 'blur' }] : []),
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

async function onSubmit(): Promise<void> {
  if (!formRef.value || auth.loading || celebrating.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  // 注册：建号后回到登录，让用户用新账号登进来
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
    // 停一下让狗摇完，再跳转
    await new Promise((resolve) => window.setTimeout(resolve, 1200))
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/devices'
    await router.replace(redirect)
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
    <div class="guides" aria-hidden="true">
      <span class="g g17" />
      <span class="g g50" />
      <span class="g g83" />
    </div>

    <header class="login-top">
      <div class="brand">
        <BrandMark :size="26" />
        <span class="word mono">PET-DOG</span>
        <span class="sub mono">STM32 COMPANION</span>
      </div>
      <div class="top-right">
        <span class="status ok">System online</span>
        <span class="edition mono">V2.0 / 2026</span>
      </div>
    </header>

    <main class="login-main">
      <section class="intro">
        <div class="eyebrow">Unleash the power of</div>

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
          <span class="dog-hint mono">Click the dog</span>
        </div>
      </section>

      <section class="access">
        <div class="access-box corner">
          <div class="access-head mono">
            <span>{{ isRegister ? 'Create account' : 'Secure access' }}</span>
            <span>01 / 01</span>
          </div>

          <h1>{{ isRegister ? '注册账号' : '登录控制台' }}</h1>
          <p class="hint">
            {{ isRegister ? '注册只建账号，成功后回到登录页，用新账号进入控制台。' : '用已有账号登录，没有账号就注册一个。' }}
          </p>

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
                <span class="field-label mono">Username</span>
                <el-input
                  v-model="form.username"
                  :placeholder="isRegister ? '3–20 个字符' : 'admin'"
                  autocomplete="username"
                />
              </div>
            </el-form-item>

            <el-form-item prop="password" class="field-item">
              <div class="field">
                <span class="field-label mono">Password</span>
                <el-input
                  v-model="form.password"
                  type="password"
                  :placeholder="isRegister ? '至少 6 位' : '••••••'"
                  show-password
                  autocomplete="current-password"
                />
              </div>
            </el-form-item>

            <el-form-item v-if="isRegister" prop="confirm" class="field-item">
              <div class="field">
                <span class="field-label mono">Confirm password</span>
                <el-input
                  v-model="form.confirm"
                  type="password"
                  placeholder="••••••"
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
              <span class="arrow">↗</span>
            </el-button>
          </el-form>

          <div class="switch">
            <span class="switch-text mono">{{ isRegister ? '已经有账号？' : '还没有账号？' }}</span>
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
            <span>DEMO · admin / 123456</span>
            <el-link type="primary" underline="never" class="fill" @click="fillDemo">
              一键填入
            </el-link>
          </div>
        </div>

        <div class="access-foot mono">
          <span>Vue 3 · Element Plus</span>
          <span>{{ mockMode ? 'Mock feed' : 'Live feed' }}</span>
        </div>
      </section>
    </main>

    <footer class="login-foot mono">PET-DOG · 2026 · MADE FOR THE DESK</footer>
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
  /* 对上标题「DESKTOP」里 D 的字形左缘，再往左留 5px */
  left: max(62px, calc(50% - 558px));
}

.g50 {
  left: 50%;
}

.g83 {
  left: 83%;
}

.login-top {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 42px;
  border-bottom: 1px solid var(--hair);
  background: rgba(239, 236, 230, 0.86);
  backdrop-filter: blur(8px);
}

.brand {
  display: flex;
  align-items: baseline;
  gap: 9px;
}

.word {
  font-size: 12px;
  letter-spacing: 0.16em;
}

.sub {
  font-size: 8px;
  letter-spacing: 0.14em;
  color: var(--faint);
}

.top-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.top-right .status {
  font-size: 8.5px;
  letter-spacing: 0.14em;
}

.edition {
  font-size: 8.5px;
  letter-spacing: 0.14em;
  color: var(--faint);
}

.login-main {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(340px, 0.72fr);
  gap: 64px;
  align-items: center;
  width: 100%;
  max-width: 1240px;
  margin: 0 auto;
  padding: 38px 42px 30px;
  flex: 1;
}

.intro {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 16px;
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
  padding: 2px 18px 4px;
  border: 2px solid transparent;
  background:
    linear-gradient(var(--paper), var(--paper)) padding-box,
    linear-gradient(100deg, #ffb347, #ff5a5f 50%, #ff3d8b) border-box;
}

.title-box span {
  display: block;
  font-size: clamp(40px, 5.3vw, 82px);
  font-weight: 400;
  line-height: 1.03;
  letter-spacing: -0.035em;
}

.title-box.cut {
  clip-path: polygon(
    0 0,
    100% 0,
    100% calc(100% - 24px),
    calc(100% - 24px) 100%,
    0 100%
  );
}

.title-box.cut span {
  padding-right: 6px;
}

.dog-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  width: 100%;
  max-width: 420px;
}

.dog {
  margin-top: 2px;
  max-width: 420px;
}

.dog-hint {
  font-size: 8px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--faint);
}

.access {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.access-box {
  padding: 24px 26px 20px;
  background: var(--panel);
  border: 1px solid var(--hair);
}

.access-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 20px;
  font-size: 8.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

.access-box h1 {
  font-size: 26px;
  font-weight: 500;
  letter-spacing: -0.02em;
}

.hint {
  margin: 7px 0 20px;
  font-size: 12px;
  color: var(--dim);
}

.field-item {
  margin-bottom: 20px;
}

.field-item :deep(.el-form-item__content) {
  display: block;
  line-height: normal;
}

.field-item :deep(.el-form-item__error) {
  position: static;
  margin-top: 4px;
  font-family: var(--mono);
  font-size: 9px;
  line-height: 1.45;
  letter-spacing: 0.03em;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 100%;
}

.field-label {
  font-size: 8.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
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
  font-size: 13px;
  letter-spacing: 0.08em;
}

.arrow {
  position: absolute;
  right: 16px;
  top: 50%;
  transform: translateY(-50%);
  font-family: var(--mono);
  font-size: 14px;
}

.switch {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  margin-top: 14px;
  font-size: 9.5px;
  letter-spacing: 0.04em;
  color: var(--dim);
}

.switch-text {
  color: var(--faint);
}

.switch-link {
  font-size: 10px;
  letter-spacing: 0.06em;
}

.demo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 16px;
  padding-top: 13px;
  border-top: 1px dashed var(--hair);
  font-size: 9.5px;
  letter-spacing: 0.06em;
  color: var(--dim);
}

.fill {
  font-size: 10px;
  letter-spacing: 0.06em;
}

.access-foot {
  display: flex;
  justify-content: space-between;
  font-size: 8px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--faint);
}

.login-foot {
  position: relative;
  z-index: 1;
  padding: 16px 42px 18px;
  border-top: 1px solid var(--hair);
  text-align: center;
  font-size: 8.5px;
  letter-spacing: 0.18em;
  color: var(--faint);
}

@media (max-width: 960px) {
  .guides {
    display: none;
  }

  .login-top {
    padding: 0 18px;
  }

  .sub,
  .top-right .status {
    display: none;
  }

  .login-main {
    grid-template-columns: 1fr;
    gap: 32px;
    padding: 26px 18px 34px;
  }

  .title-box span {
    font-size: clamp(38px, 12vw, 64px);
  }

  .dog {
    max-width: 300px;
  }

  .login-foot {
    padding: 14px 18px 16px;
  }
}
</style>
