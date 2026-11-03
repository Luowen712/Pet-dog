<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'
import { ElMessage } from 'element-plus'
import BrandMark from '@/components/BrandMark.vue'
import RobotDog from '@/components/RobotDog.vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const mockMode = import.meta.env.VITE_USE_MOCK === 'true'
const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function fillDemo(): void {
  form.username = 'admin'
  form.password = '123456'
}

async function onSubmit(): Promise<void> {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  try {
    await auth.login(form.username, form.password)
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/devices'
    await router.replace(redirect)
  } catch {
    // 错误提示由 request 层统一弹出
  }
}
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

        <p class="lede">
          STM32 智能桌面宠物 · 网页控制台。19 个动作、7 张表情、时间天气和音乐，都在这一个页面里。
        </p>

        <RobotDog class="dog" />
      </section>

      <section class="access">
        <div class="access-box corner">
          <div class="access-head mono">
            <span>Secure access</span>
            <span>01 / 01</span>
          </div>

          <h1>登录控制台</h1>
          <p class="hint">账号由后端初始化，演示环境直接用下面的账号。</p>

          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            size="large"
            class="form"
            @submit.prevent="onSubmit"
          >
            <el-form-item prop="username" class="field-item">
              <div class="field">
                <span class="field-label mono">Username</span>
                <el-input v-model="form.username" placeholder="admin" autocomplete="username" />
              </div>
            </el-form-item>

            <el-form-item prop="password" class="field-item">
              <div class="field">
                <span class="field-label mono">Password</span>
                <el-input
                  v-model="form.password"
                  type="password"
                  placeholder="••••••"
                  show-password
                  autocomplete="current-password"
                  @keyup.enter="onSubmit"
                />
              </div>
            </el-form-item>

            <el-button
              type="primary"
              native-type="submit"
              class="submit"
              :loading="auth.loading"
              @click="onSubmit"
            >
              <span>进入控制台</span>
              <span class="arrow">↗</span>
            </el-button>
          </el-form>

          <div v-if="mockMode" class="demo">
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
  left: 17%;
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

.lede {
  max-width: 400px;
  font-size: 13px;
  line-height: 1.75;
  color: var(--dim);
  letter-spacing: 0.01em;
}

.dog {
  margin-top: 2px;
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
  margin-bottom: 13px;
}

.field-item :deep(.el-form-item__content) {
  display: block;
  line-height: normal;
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
