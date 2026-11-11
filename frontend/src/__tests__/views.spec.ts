import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import App from '@/App.vue'
import router from '@/router'

vi.mock('echarts', () => {
  const chart = {
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
  }
  return {
    init: vi.fn(() => chart),
    getInstanceByDom: vi.fn(() => null),
    graphic: {
      LinearGradient: class {
        constructor() {}
      },
    },
  }
})

const SESSION = {
  token: 'mock-token',
  user: { id: 1, username: 'admin', name: '管理员', role: 'admin' },
}

let wrapper: VueWrapper | null = null
let consoleErrors: string[] = []

function spyConsole(): void {
  consoleErrors = []
  vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
    consoleErrors.push(args.map(String).join(' '))
  })
}

async function mountAt(path: string): Promise<VueWrapper> {
  const pinia = createPinia()
  // 先挂载再导航：main.ts 里 pinia 先于 router 安装，路由守卫才能拿到 store
  wrapper = mount(App, {
    global: {
      plugins: [pinia, router],
    },
    attachTo: document.body,
  })
  await router.push(path)
  await router.isReady()
  await flushPromises()
  await new Promise((resolve) => setTimeout(resolve, 80))
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('petdog_token', SESSION.token)
  localStorage.setItem('petdog_user', JSON.stringify(SESSION.user))
  spyConsole()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  const broken = consoleErrors.filter(
    (line) => line.includes('Failed to resolve component') || line.includes('Invalid prop'),
  )
  expect(broken).toEqual([])
})

describe('页面冒烟', () => {
  it('未登录访问 /devices 会回到登录页', async () => {
    localStorage.clear()
    const view = await mountAt('/devices')
    expect(view.text()).toContain('登录控制台')
    expect(view.text()).toContain('PET-DOG')
  })

  it('登录页能切到注册表单', async () => {
    localStorage.clear()
    const view = await mountAt('/login')
    const link = view.findAll('.el-link').find((node) => node.text() === '注册')
    expect(link).toBeTruthy()
    await link!.trigger('click')
    await flushPromises()
    expect(view.text()).toContain('注册账号')
    expect(view.text()).toContain('Confirm password')
    expect(view.text()).toContain('创建账号')
  })

  it('设备页列出 mock 设备', async () => {
    const view = await mountAt('/devices')
    expect(view.text()).toContain('我的设备')
    expect(view.text()).toContain('桌宠一号')
    expect(view.text()).toContain('进入控制台')
  })

  it('控制台铺出 19 个动作按钮，其中只有 7 个启用，7 张表情', async () => {
    const view = await mountAt('/console')
    expect(view.text()).toContain('动作指令')
    expect(view.findAll('.action-btn')).toHaveLength(19)
    expect(view.findAll('.action-btn.disabled')).toHaveLength(12)
    expect(view.findAll('.action-btn:not(.disabled)')).toHaveLength(7)
    expect(view.findAll('.face-btn')).toHaveLength(7)
  })

  it('点动作按钮先变黄；没有 done 回执前不会变绿', async () => {
    const view = await mountAt('/console')
    const button = view.findAll('.action-btn:not(.disabled)')[0]
    await button.trigger('click')
    await flushPromises()
    expect(['pending', 'accepted']).toContain(
      button.classes().find((name) => ['pending', 'accepted', 'ok'].includes(name)),
    )

    await new Promise((resolve) => setTimeout(resolve, 1500))
    await flushPromises()
    expect(button.classes()).not.toContain('ok')
  })

  it('日志、看板、场景的路由已隐藏，深链回到设备页', async () => {
    expect(router.hasRoute('logs')).toBe(false)
    expect(router.hasRoute('dashboard')).toBe(false)
    expect(router.hasRoute('scenes')).toBe(false)

    const view = await mountAt('/logs')
    expect(view.text()).toContain('我的设备')
    expect(view.text()).not.toContain('指令日志')
  })

  it('表情库有 7 张内置表情，没有上传入口', async () => {
    const view = await mountAt('/faces')
    expect(view.text()).toContain('内置表情')
    expect(view.findAll('.face-card').length).toBeGreaterThanOrEqual(7)
    expect(view.text()).not.toContain('上传表情')
  })

  it('账号页提供改密、全部退出和注销', async () => {
    const view = await mountAt('/account')
    expect(view.text()).toContain('修改密码')
    expect(view.text()).toContain('退出所有设备上的登录')
    expect(view.text()).toContain('注销账号')
  })
})
